"""Corpus-scale, domain-neutral streaming graph physical writer.

The original :mod:`hf_graphrag.graph` writer deliberately keeps a complete
``GraphLayout`` in memory.  That remains useful for fixtures and small graphs,
but it is not a production path for graphs containing millions of nodes and
edges.  This module implements the same durable Parquet row contracts and
canonical routing paths without materialising the graph:

* node and edge inputs are consumed once and externally sorted on disk;
* duplicate durable identities are rejected while the sorted streams are
  sharded;
* edge endpoints are verified by a merge against the disk-backed node stream,
  never by constructing a process-wide node set;
* outgoing and incoming pointer streams are externally sorted, paged, and
  written under the shared graph bounds; and
* the exact edge-CID multiset is independently sorted and reconciled for both
  adjacency directions.

The writer is local-only.  Compact proofs (for example BM25 vocabulary/DF
digests) may be attached to its manifest fragment, but this module never turns
such metadata into durable term-document edges.
"""

from __future__ import annotations

import itertools
import math
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from .artifacts import (
    ArtifactWriterConfig,
    atomic_staging,
    confine_path,
    describe_file,
    resolve_release_root,
    validate_zstd_parquet,
    verify_descriptor,
    write_zstd_parquet,
)
from .external_sort import (
    DEFAULT_MAX_RECORDS_IN_MEMORY,
    ExternalSortReceipt,
    external_sort_to_file,
    iter_jsonl,
    write_jsonl_atomic,
)
from .graph import (
    ADJACENCY_SORTED_BY,
    EDGES_SORTED_BY,
    GRAPH_ADJACENCY_IN_DIR,
    GRAPH_ADJACENCY_OUT_DIR,
    GRAPH_ADJACENCY_SCHEMA_VERSION,
    GRAPH_EDGE_INDEX_PATH,
    GRAPH_EDGE_SCHEMA_VERSION,
    GRAPH_EDGES_DIR,
    GRAPH_IN_ADJACENCY_INDEX_PATH,
    GRAPH_NODE_INDEX_PATH,
    GRAPH_NODE_SCHEMA_VERSION,
    GRAPH_NODES_DIR,
    GRAPH_OUT_ADJACENCY_INDEX_PATH,
    GRAPH_ROUTING_SCHEMA_VERSION,
    MATERIALIZED_GRAPH_WRITER_PRODUCTION_READY,
    MAX_ADJACENCY_POINTERS_PER_SHARD,
    NODES_SORTED_BY,
    AdjacencyPage,
    GraphEdge,
    GraphInputError,
    GraphIntegrityError,
    GraphNode,
    GraphOrderingError,
    GraphRangeError,
    adjacency_order_key,
    graph_part_relative_path,
)
from .schema import (
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_ROUTING_ROWS_PER_INDEX,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    ArtifactDescriptor,
    ArtifactFamily,
    PhysicalBoundError,
    canonical_json_dumps,
    normalize_relative_artifact_path,
)

SCHEMA_VERSION: Final = "hf-graphrag-streaming-graph/v1"
PRODUCER: Final = "retrieval/hf_graphrag/streaming_graph.py"
EDGE_IDENTITY_DIGEST_ENCODING: Final = "canonical-json-string-lines/sha256"
MAX_COMPACT_PROOF_BYTES: Final = 65_536
AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
PERFORMS_NETWORK_IO: Final = False

# The sequence/materialised writer remains a compatibility and fixture API.
# Production callers must use the streaming result below.
LEGACY_MATERIALIZED_GRAPH_WRITER_PRODUCTION_READY: Final = (
    MATERIALIZED_GRAPH_WRITER_PRODUCTION_READY
)
STREAMING_GRAPH_WRITER_PRODUCTION_READY: Final = True

CANONICAL_GRAPH_INDEX_PATHS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "graph_node_chunks": GRAPH_NODE_INDEX_PATH,
        "graph_edge_chunks": GRAPH_EDGE_INDEX_PATH,
        "graph_out_adjacency": GRAPH_OUT_ADJACENCY_INDEX_PATH,
        "graph_in_adjacency": GRAPH_IN_ADJACENCY_INDEX_PATH,
    }
)


class StreamingGraphError(GraphIntegrityError):
    """Base error for the corpus-scale graph writer."""


class StreamingGraphDuplicateError(StreamingGraphError):
    """Raised when a durable node or edge identity is repeated."""


class StreamingGraphEndpointError(StreamingGraphError):
    """Raised when a disk-backed endpoint join cannot resolve an edge."""


class StreamingGraphCoverageError(StreamingGraphError):
    """Raised when either adjacency direction differs from durable edges."""


class StreamingGraphProofError(StreamingGraphError):
    """Raised when supposedly compact metadata contains an expansion."""


@dataclass(frozen=True, slots=True)
class StreamingGraphConfig:
    """Sealed memory and physical bounds for one streaming graph build."""

    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD
    max_pointers_per_page: int = MAX_ADJACENCY_POINTERS_PER_ROW
    max_pointers_per_shard: int = MAX_ADJACENCY_POINTERS_PER_SHARD
    max_records_in_memory: int = DEFAULT_MAX_RECORDS_IN_MEMORY
    max_bytes_in_memory: int | None = None
    overwrite: bool = False
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "max_rows_per_shard",
            "max_pointers_per_page",
            "max_pointers_per_shard",
            "max_records_in_memory",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise PhysicalBoundError(f"{name} must be a positive integer")
        if self.max_rows_per_shard > MAX_ROWS_PER_PHYSICAL_SHARD:
            raise PhysicalBoundError(
                f"max_rows_per_shard exceeds {MAX_ROWS_PER_PHYSICAL_SHARD}"
            )
        if self.max_pointers_per_page > MAX_ADJACENCY_POINTERS_PER_ROW:
            raise PhysicalBoundError(
                "max_pointers_per_page exceeds the shared adjacency row bound"
            )
        if self.max_pointers_per_shard < self.max_pointers_per_page:
            raise PhysicalBoundError(
                "max_pointers_per_shard must be >= max_pointers_per_page"
            )
        if self.max_pointers_per_shard > MAX_ADJACENCY_POINTERS_PER_SHARD:
            raise PhysicalBoundError(
                "max_pointers_per_shard exceeds the shared graph shard bound"
            )
        # The merge implementation needs at least two run heads.
        if self.max_records_in_memory < 2:
            raise PhysicalBoundError("max_records_in_memory must be >= 2")
        if self.max_bytes_in_memory is not None and (
            isinstance(self.max_bytes_in_memory, bool)
            or not isinstance(self.max_bytes_in_memory, int)
            or self.max_bytes_in_memory < 1
        ):
            raise PhysicalBoundError("max_bytes_in_memory must be positive")
        if not isinstance(self.overwrite, bool):
            raise StreamingGraphError("overwrite must be a boolean")
        if self.schema_version != SCHEMA_VERSION:
            raise StreamingGraphError(
                f"unsupported streaming graph schema {self.schema_version!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_bytes_in_memory": self.max_bytes_in_memory,
            "max_pointers_per_page": self.max_pointers_per_page,
            "max_pointers_per_shard": self.max_pointers_per_shard,
            "max_records_in_memory": self.max_records_in_memory,
            "max_rows_per_shard": self.max_rows_per_shard,
            "overwrite": self.overwrite,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class _ShardFamilyResult:
    descriptors: tuple[ArtifactDescriptor, ...]
    routing_rows: tuple[Mapping[str, Any], ...]
    row_count: int
    identity_sha256: str = ""
    pointer_count: int = 0
    page_count: int = 0
    anchor_node_count: int = 0


@dataclass(frozen=True, slots=True)
class StreamingGraphWriteResult:
    """Compact on-disk graph result; never contains all graph rows."""

    output_root: str
    config: StreamingGraphConfig
    data_descriptors: tuple[ArtifactDescriptor, ...]
    index_descriptors: Mapping[str, ArtifactDescriptor]
    routing_rows: Mapping[str, tuple[Mapping[str, Any], ...]]
    counts: Mapping[str, int]
    identity_proofs: Mapping[str, str]
    sort_receipts: Mapping[str, Mapping[str, Any]]
    compact_proofs: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    checks: Mapping[str, bool] = field(default_factory=dict)
    verified_at_write: bool = False
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "index_descriptors", MappingProxyType(dict(self.index_descriptors))
        )
        object.__setattr__(
            self,
            "routing_rows",
            MappingProxyType(
                {
                    str(name): tuple(MappingProxyType(dict(row)) for row in rows)
                    for name, rows in self.routing_rows.items()
                }
            ),
        )
        object.__setattr__(self, "counts", MappingProxyType(dict(self.counts)))
        object.__setattr__(
            self, "identity_proofs", MappingProxyType(dict(self.identity_proofs))
        )
        object.__setattr__(
            self,
            "sort_receipts",
            MappingProxyType(
                {
                    str(name): MappingProxyType(dict(receipt))
                    for name, receipt in self.sort_receipts.items()
                }
            ),
        )
        object.__setattr__(
            self,
            "compact_proofs",
            MappingProxyType(
                {
                    str(name): MappingProxyType(dict(proof))
                    for name, proof in self.compact_proofs.items()
                }
            ),
        )
        object.__setattr__(self, "checks", MappingProxyType(dict(self.checks)))

    @property
    def production_ready(self) -> bool:
        return (
            STREAMING_GRAPH_WRITER_PRODUCTION_READY
            and self.verified_at_write
            and bool(self.checks)
            and all(self.checks.values())
            and self.counts.get("nodes", 0) > 0
            and self.counts.get("edges", 0) > 0
            and self.counts.get("outgoing_adjacency_pointers")
            == self.counts.get("edges")
            and self.counts.get("incoming_adjacency_pointers")
            == self.counts.get("edges")
        )

    def verify(self) -> None:
        """Rehash descriptors and revalidate the compact physical closure."""

        verify_streaming_graph_result(self)

    def _iter_node_column(self, column: str) -> Iterator[str]:
        """Replay one node identity column from verified bounded Parquet shards."""

        try:
            import pyarrow.parquet as pq
        except ImportError as exc:  # pragma: no cover - writer needs pyarrow too
            raise ImportError("streaming graph replay requires pyarrow") from exc
        root = resolve_release_root(self.output_root, must_exist=True)
        descriptors = sorted(
            (
                item
                for item in self.data_descriptors
                if item.family is ArtifactFamily.GRAPH_NODES
            ),
            key=lambda item: int(item.shard_id or 0),
        )
        for descriptor in descriptors:
            path = verify_descriptor(root, descriptor)
            parquet = pq.ParquetFile(path)
            for batch in parquet.iter_batches(
                batch_size=self.config.max_rows_per_shard,
                columns=[column],
            ):
                for row in batch.to_pylist():
                    value = row.get(column)
                    if value is not None and str(value).strip():
                        yield str(value).strip()

    def iter_node_cids(self) -> Iterator[str]:
        """Replay sorted durable node CIDs without materialising them."""

        yield from self._iter_node_column("node_cid")

    def iter_entry_cids(self) -> Iterator[str]:
        """Replay non-null parent/source entry CIDs for release key parity."""

        yield from self._iter_node_column("entry_cid")

    @property
    def key_evidence(self) -> dict[str, Iterable[str]]:
        """Disk-backed graph key evidence consumed by local release gates."""

        return {
            "entry_cids": self.iter_entry_cids(),
            "node_cids": self.iter_node_cids(),
        }

    def graph_report(self) -> dict[str, Any]:
        """Return compact shared graph metadata without replaying graph rows."""

        vocabulary_proof = self.compact_proofs.get("bm25_vocabulary")
        return {
            "adjacency_sorted_by": ADJACENCY_SORTED_BY,
            "checks": {
                "direct_parquet_columns": True,
                "edge_identities_exact": True,
                "endpoint_integrity": True,
                "node_identities_exact": True,
                "term_document_edges_not_materialized": True,
                "two_way_adjacency_required": True,
            },
            "edge_count": self.counts["edges"],
            "edge_identity_sha256": self.identity_proofs["edge_cids_sha256"],
            "edge_shard_count": len(self.routing_rows["graph_edge_chunks"]),
            "edges_sorted_by": EDGES_SORTED_BY,
            "in_adjacency_edge_count": self.counts["incoming_adjacency_pointers"],
            "in_adjacency_row_count": self.counts["incoming_adjacency_pages"],
            "layout": "bounded_bidirectional_adjacency",
            "node_count": self.counts["nodes"],
            "node_identity_sha256": self.identity_proofs["node_cids_sha256"],
            "node_shard_count": len(self.routing_rows["graph_node_chunks"]),
            "nodes_sorted_by": NODES_SORTED_BY,
            "out_adjacency_edge_count": self.counts["outgoing_adjacency_pointers"],
            "out_adjacency_row_count": self.counts["outgoing_adjacency_pages"],
            "schema_version": self.schema_version,
            "streaming": True,
            "vocabulary_parity": (
                dict(vocabulary_proof) if vocabulary_proof is not None else {}
            ),
        }

    def manifest_fragment(self) -> dict[str, Any]:
        return {
            "artifacts": [item.to_dict() for item in self.data_descriptors],
            "checks": dict(self.checks),
            "compact_proofs": {
                name: dict(proof) for name, proof in self.compact_proofs.items()
            },
            "config": self.config.to_dict(),
            "counts": dict(self.counts),
            "graph": self.graph_report(),
            "identity_proofs": dict(self.identity_proofs),
            "indexes": {
                name: descriptor.to_dict()
                for name, descriptor in self.index_descriptors.items()
            },
            "local_only": True,
            "network_io": PERFORMS_NETWORK_IO,
            "producer": PRODUCER,
            "production_ready": self.production_ready,
            "publication_authorized": AUTHORIZES_PUBLICATION,
            "schema_version": self.schema_version,
            "sort_receipts": {
                name: dict(receipt) for name, receipt in self.sort_receipts.items()
            },
        }

    def to_dict(self) -> dict[str, Any]:
        payload = self.manifest_fragment()
        payload["output_root"] = self.output_root
        payload["routing_rows"] = {
            name: [dict(row) for row in rows]
            for name, rows in self.routing_rows.items()
        }
        return payload


def _node_sort_key(row: Mapping[str, Any]) -> tuple[str]:
    return (str(row.get("node_cid") or ""),)


def _edge_sort_key(row: Mapping[str, Any]) -> tuple[str]:
    return (str(row.get("edge_cid") or ""),)


def _endpoint_sort_key(row: Mapping[str, Any]) -> tuple[str, str, str]:
    return (
        str(row.get("lookup_node_cid") or ""),
        str(row.get("edge_cid") or ""),
        str(row.get("role") or ""),
    )


def _adjacency_pointer_sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        str(row.get("node_cid") or ""),
        *adjacency_order_key(
            score=row.get("score"),
            edge_type=str(row.get("edge_type") or ""),
            neighbor_cid=str(row.get("neighbor_cid") or ""),
            edge_cid=str(row.get("edge_cid") or ""),
        ),
    )


def _identity_sort_key(row: Mapping[str, Any]) -> tuple[str]:
    return (str(row.get("identity") or ""),)


def _coerce_node_row(
    row: Mapping[str, Any] | GraphNode, position: int
) -> dict[str, Any]:
    if isinstance(row, GraphNode):
        return row.data_row()
    if not isinstance(row, Mapping):
        raise GraphInputError(f"nodes[{position}] must be a mapping or GraphNode")
    properties = row.get("properties") or row.get("payload") or {}
    if not isinstance(properties, Mapping):
        raise GraphInputError(f"nodes[{position}].properties must be a mapping")
    return GraphNode(
        node_cid=str(row.get("node_cid") or row.get("cid") or row.get("id") or ""),
        node_type=str(row.get("node_type") or row.get("type") or ""),
        label=row.get("label"),
        entry_cid=row.get("entry_cid"),
        properties=dict(properties),
    ).data_row()


def _coerce_edge_row(
    row: Mapping[str, Any] | GraphEdge, position: int
) -> dict[str, Any]:
    if isinstance(row, GraphEdge):
        return row.data_row()
    if not isinstance(row, Mapping):
        raise GraphInputError(f"edges[{position}] must be a mapping or GraphEdge")
    properties = row.get("properties") or row.get("payload") or {}
    if not isinstance(properties, Mapping):
        raise GraphInputError(f"edges[{position}].properties must be a mapping")
    return GraphEdge(
        edge_cid=str(row.get("edge_cid") or row.get("cid") or row.get("id") or ""),
        edge_type=str(row.get("edge_type") or row.get("type") or ""),
        source_node_cid=str(
            row.get("source_node_cid")
            or row.get("source_cid")
            or row.get("source")
            or ""
        ),
        target_node_cid=str(
            row.get("target_node_cid")
            or row.get("target_cid")
            or row.get("target")
            or ""
        ),
        score=row.get("score", row.get("weight")),
        retrieval_method=str(row.get("retrieval_method") or "structural"),
        properties=dict(properties),
    ).data_row()


def _iter_node_rows(
    rows: Iterable[Mapping[str, Any] | GraphNode],
) -> Iterator[dict[str, Any]]:
    for position, row in enumerate(rows):
        yield _coerce_node_row(row, position)


def _iter_edge_rows(
    rows: Iterable[Mapping[str, Any] | GraphEdge],
) -> Iterator[dict[str, Any]]:
    for position, row in enumerate(rows):
        yield _coerce_edge_row(row, position)


def _run_sort(
    rows: Iterable[Mapping[str, Any]],
    *,
    output_path: Path,
    work_dir: Path,
    key_fn: Any,
    config: StreamingGraphConfig,
) -> ExternalSortReceipt:
    receipt = external_sort_to_file(
        rows,
        output_path,
        work_dir=work_dir,
        key_fn=key_fn,
        family="documents",
        max_records_in_memory=config.max_records_in_memory,
        max_bytes_in_memory=config.max_bytes_in_memory,
        resume=False,
    )
    if receipt.interrupted or receipt.status != "complete":
        raise StreamingGraphError(f"external sort did not complete: {output_path}")
    return receipt


def _compact_sort_receipt(receipt: ExternalSortReceipt) -> Mapping[str, Any]:
    payload = receipt.to_dict()
    # Sort work paths are deliberately ephemeral and are not release artifacts.
    payload.pop("output_path", None)
    return MappingProxyType(payload)


def _update_identity_digest(hasher: Any, identity: str) -> None:
    hasher.update(canonical_json_dumps(identity).encode("utf-8"))
    hasher.update(b"\n")


def _routing_row(
    descriptor: ArtifactDescriptor,
    *,
    kind: str,
    direction: str | None = None,
    pointer_count: int = 0,
    first_page_index: int = 0,
    last_page_index: int = 0,
    node_count: int = 0,
) -> Mapping[str, Any]:
    payload: dict[str, Any] = {
        "cid": descriptor.content_cid,
        "content_cid": descriptor.content_cid,
        "first_key": descriptor.first_key,
        "kind": kind,
        "last_key": descriptor.last_key,
        "relative_path": descriptor.relative_path,
        "row_count": descriptor.row_count,
        "schema_version": GRAPH_ROUTING_SCHEMA_VERSION,
        "sha256": descriptor.sha256,
        "shard_id": descriptor.shard_id,
        "size_bytes": descriptor.size_bytes,
    }
    if direction is not None:
        payload.update(
            {
                "adjacency_count": pointer_count,
                "direction": direction,
                "first_page_index": first_page_index,
                "last_page_index": last_page_index,
                "node_count": node_count,
            }
        )
    return MappingProxyType(payload)


def _write_keyed_shards(
    rows: Iterable[Mapping[str, Any]],
    *,
    root: Path,
    key_field: str,
    directory: str,
    kind: str,
    family: ArtifactFamily,
    schema_id: str,
    config: StreamingGraphConfig,
) -> _ShardFamilyResult:
    descriptors: list[ArtifactDescriptor] = []
    routes: list[Mapping[str, Any]] = []
    buffer: list[dict[str, Any]] = []
    identity_hasher = sha256()
    previous_key: str | None = None
    row_count = 0

    def flush() -> None:
        if not buffer:
            return
        shard_id = len(descriptors)
        if shard_id >= MAX_ROUTING_ROWS_PER_INDEX:
            raise PhysicalBoundError(
                f"{kind} requires more than {MAX_ROUTING_ROWS_PER_INDEX} routes"
            )
        relative = graph_part_relative_path(directory, shard_id)
        path = confine_path(root, relative)
        write_zstd_parquet(
            path,
            buffer,
            max_rows=config.max_rows_per_shard,
            config=ArtifactWriterConfig(max_rows_per_shard=config.max_rows_per_shard),
        )
        descriptor = describe_file(
            path,
            root=root,
            row_count=len(buffer),
            family=family,
            schema_id=schema_id,
            first_key=str(buffer[0][key_field]),
            last_key=str(buffer[-1][key_field]),
            shard_id=shard_id,
            metadata={"kind": kind, "streaming": True},
        )
        descriptors.append(descriptor)
        routes.append(_routing_row(descriptor, kind=kind))
        buffer.clear()

    for row in rows:
        payload = dict(row)
        key = str(payload.get(key_field) or "")
        if not key:
            raise StreamingGraphError(f"{kind} row is missing {key_field}")
        if previous_key is not None:
            if key == previous_key:
                raise StreamingGraphDuplicateError(
                    f"duplicate durable {key_field}: {key!r}"
                )
            if key < previous_key:
                raise GraphOrderingError(f"{kind} external sort is not canonical")
        previous_key = key
        _update_identity_digest(identity_hasher, key)
        buffer.append(payload)
        row_count += 1
        if len(buffer) >= config.max_rows_per_shard:
            flush()
    flush()
    return _ShardFamilyResult(
        descriptors=tuple(descriptors),
        routing_rows=tuple(routes),
        row_count=row_count,
        identity_sha256=identity_hasher.hexdigest(),
    )


def _iter_endpoint_requests(edge_path: Path) -> Iterator[dict[str, Any]]:
    for edge in iter_jsonl(edge_path):
        common = {
            "edge_cid": str(edge["edge_cid"]),
            "edge_type": str(edge["edge_type"]),
            "retrieval_method": str(edge["retrieval_method"]),
            "score": edge.get("score"),
            "source_node_cid": str(edge["source_node_cid"]),
            "target_node_cid": str(edge["target_node_cid"]),
        }
        yield {
            **common,
            "lookup_node_cid": common["source_node_cid"],
            "role": "source",
        }
        yield {
            **common,
            "lookup_node_cid": common["target_node_cid"],
            "role": "target",
        }


def _iter_typed_endpoints(
    node_path: Path,
    endpoint_path: Path,
    counts: dict[str, int],
) -> Iterator[dict[str, Any]]:
    node_rows = iter_jsonl(node_path)
    current_node = next(node_rows, None)
    previous_key: tuple[str, str, str] | None = None
    for endpoint in iter_jsonl(endpoint_path):
        key = _endpoint_sort_key(endpoint)
        if previous_key is not None and key <= previous_key:
            if key == previous_key:
                raise StreamingGraphDuplicateError(
                    f"duplicate endpoint lookup record: {key!r}"
                )
            raise GraphOrderingError("endpoint lookup records are not sorted")
        previous_key = key
        lookup = key[0]
        while current_node is not None and str(current_node["node_cid"]) < lookup:
            current_node = next(node_rows, None)
        if current_node is None or str(current_node["node_cid"]) != lookup:
            raise StreamingGraphEndpointError(
                f"dangling edge {endpoint['edge_cid']!r}: missing "
                f"{endpoint['role']} node {lookup!r}"
            )
        role = str(endpoint["role"])
        if role not in {"source", "target"}:
            raise StreamingGraphEndpointError(f"invalid endpoint role {role!r}")
        if str(endpoint[f"{role}_node_cid"]) != lookup:
            raise StreamingGraphEndpointError(
                f"endpoint role/key mismatch for edge {endpoint['edge_cid']!r}"
            )
        counts[role] += 1
        yield {**endpoint, "endpoint_node_type": str(current_node["node_type"])}


def _iter_direction_pointers(
    typed_endpoint_path: Path,
    direction: str,
) -> Iterator[dict[str, Any]]:
    if direction not in {"out", "in"}:
        raise StreamingGraphError(f"invalid adjacency direction {direction!r}")
    selected_role = "target" if direction == "out" else "source"
    for endpoint in iter_jsonl(typed_endpoint_path):
        if endpoint["role"] != selected_role:
            continue
        if direction == "out":
            anchor = endpoint["source_node_cid"]
            neighbor = endpoint["target_node_cid"]
        else:
            anchor = endpoint["target_node_cid"]
            neighbor = endpoint["source_node_cid"]
        yield {
            "direction": direction,
            "edge_cid": endpoint["edge_cid"],
            "edge_type": endpoint["edge_type"],
            "neighbor_cid": neighbor,
            "neighbor_node_type": endpoint["endpoint_node_type"],
            "node_cid": anchor,
            "retrieval_method": endpoint["retrieval_method"],
            "score": endpoint.get("score"),
        }


def _iter_adjacency_counts(pointer_path: Path) -> Iterator[dict[str, Any]]:
    current = ""
    count = 0
    previous_order: tuple[Any, ...] | None = None
    for pointer in iter_jsonl(pointer_path):
        order = _adjacency_pointer_sort_key(pointer)
        if previous_order is not None and order < previous_order:
            raise GraphOrderingError("adjacency pointer stream is not canonical")
        previous_order = order
        node_cid = str(pointer["node_cid"])
        if node_cid != current:
            if current:
                yield {"node_cid": current, "total_neighbor_count": count}
            current = node_cid
            count = 0
        count += 1
    if current:
        yield {"node_cid": current, "total_neighbor_count": count}


def _iter_adjacency_pages(
    pointer_path: Path,
    count_path: Path,
    *,
    direction: str,
    max_pointers_per_page: int,
) -> Iterator[dict[str, Any]]:
    pointers = iter_jsonl(pointer_path)
    for count_row in iter_jsonl(count_path):
        node_cid = str(count_row["node_cid"])
        total = int(count_row["total_neighbor_count"])
        if total < 1:
            raise StreamingGraphCoverageError(
                f"empty adjacency count for node {node_cid!r}"
            )
        page_count = math.ceil(total / max_pointers_per_page)
        remaining = total
        previous_order: tuple[Any, ...] | None = None
        for page_index in range(page_count):
            take = min(max_pointers_per_page, remaining)
            selected = list(itertools.islice(pointers, take))
            if len(selected) != take:
                raise StreamingGraphCoverageError(
                    f"adjacency pointers ended inside node {node_cid!r}"
                )
            for pointer in selected:
                if pointer.get("direction") != direction:
                    raise StreamingGraphCoverageError(
                        f"mixed direction in {direction} adjacency"
                    )
                if pointer.get("node_cid") != node_cid:
                    raise StreamingGraphCoverageError(
                        f"adjacency count/pointer node mismatch for {node_cid!r}"
                    )
                order = _adjacency_pointer_sort_key(pointer)
                if previous_order is not None and order < previous_order:
                    raise GraphOrderingError(
                        f"{direction} adjacency order drifted for {node_cid!r}"
                    )
                previous_order = order
            page = AdjacencyPage(
                node_cid=node_cid,
                direction=direction,  # type: ignore[arg-type]
                page_index=page_index,
                page_count=page_count,
                total_neighbor_count=total,
                edge_cids=tuple(str(row["edge_cid"]) for row in selected),
                edge_types=tuple(str(row["edge_type"]) for row in selected),
                neighbor_cids=tuple(str(row["neighbor_cid"]) for row in selected),
                neighbor_node_types=tuple(
                    str(row["neighbor_node_type"]) for row in selected
                ),
                scores=tuple(row.get("score") for row in selected),
                retrieval_methods=tuple(
                    str(row["retrieval_method"]) for row in selected
                ),
            )
            yield page.data_row()
            remaining -= take
        if remaining:
            raise StreamingGraphCoverageError(
                f"adjacency paging did not exhaust {node_cid!r}"
            )
    extra = next(pointers, None)
    if extra is not None:
        raise StreamingGraphCoverageError(
            f"adjacency counts omit pointer {extra.get('edge_cid')!r}"
        )


def _write_adjacency_shards(
    pages: Iterable[Mapping[str, Any]],
    *,
    root: Path,
    direction: str,
    config: StreamingGraphConfig,
) -> _ShardFamilyResult:
    if direction == "out":
        directory = GRAPH_ADJACENCY_OUT_DIR
        family = ArtifactFamily.GRAPH_ADJACENCY_OUT
    elif direction == "in":
        directory = GRAPH_ADJACENCY_IN_DIR
        family = ArtifactFamily.GRAPH_ADJACENCY_IN
    else:  # pragma: no cover - guarded by caller
        raise StreamingGraphError(f"invalid direction {direction!r}")
    kind = f"graph_{direction}_adjacency"
    descriptors: list[ArtifactDescriptor] = []
    routes: list[Mapping[str, Any]] = []
    buffer: list[dict[str, Any]] = []
    pending_pointers = 0
    total_pointers = 0
    total_pages = 0
    anchor_nodes = 0
    previous_anchor = ""

    def flush() -> None:
        nonlocal pending_pointers
        if not buffer:
            return
        shard_id = len(descriptors)
        if shard_id >= MAX_ROUTING_ROWS_PER_INDEX:
            raise PhysicalBoundError(
                f"{kind} requires more than {MAX_ROUTING_ROWS_PER_INDEX} routes"
            )
        relative = graph_part_relative_path(directory, shard_id)
        path = confine_path(root, relative)
        write_zstd_parquet(
            path,
            buffer,
            max_rows=config.max_rows_per_shard,
            config=ArtifactWriterConfig(max_rows_per_shard=config.max_rows_per_shard),
        )
        unique_nodes = len({str(row["node_cid"]) for row in buffer})
        descriptor = describe_file(
            path,
            root=root,
            row_count=len(buffer),
            family=family,
            schema_id=GRAPH_ADJACENCY_SCHEMA_VERSION,
            first_key=str(buffer[0]["node_cid"]),
            last_key=str(buffer[-1]["node_cid"]),
            shard_id=shard_id,
            metadata={
                "kind": kind,
                "pointer_count": pending_pointers,
                "streaming": True,
            },
        )
        descriptors.append(descriptor)
        routes.append(
            _routing_row(
                descriptor,
                kind=kind,
                direction=direction,
                pointer_count=pending_pointers,
                first_page_index=int(buffer[0]["page_index"]),
                last_page_index=int(buffer[-1]["page_index"]),
                node_count=unique_nodes,
            )
        )
        buffer.clear()
        pending_pointers = 0

    for page in pages:
        payload = dict(page)
        pointer_count = int(payload.get("neighbor_count") or 0)
        if pointer_count < 1 or pointer_count > config.max_pointers_per_page:
            raise PhysicalBoundError(
                f"{direction} adjacency page violates pointer bound"
            )
        if buffer and (
            len(buffer) >= config.max_rows_per_shard
            or pending_pointers + pointer_count > config.max_pointers_per_shard
        ):
            flush()
        anchor = str(payload["node_cid"])
        if anchor != previous_anchor:
            anchor_nodes += 1
            previous_anchor = anchor
        buffer.append(payload)
        pending_pointers += pointer_count
        total_pointers += pointer_count
        total_pages += 1
    flush()
    return _ShardFamilyResult(
        descriptors=tuple(descriptors),
        routing_rows=tuple(routes),
        row_count=total_pages,
        pointer_count=total_pointers,
        page_count=total_pages,
        anchor_node_count=anchor_nodes,
    )


def _iter_identity_rows(path: Path, field: str) -> Iterator[dict[str, str]]:
    for row in iter_jsonl(path):
        identity = str(row.get(field) or "")
        if not identity:
            raise StreamingGraphCoverageError(f"coverage row lacks {field}")
        yield {"identity": identity}


def _digest_unique_identity_file(path: Path, *, label: str) -> tuple[int, str]:
    count = 0
    previous: str | None = None
    hasher = sha256()
    for row in iter_jsonl(path):
        identity = str(row.get("identity") or "")
        if not identity:
            raise StreamingGraphCoverageError(f"{label} contains an empty identity")
        if previous is not None:
            if identity == previous:
                raise StreamingGraphCoverageError(
                    f"duplicate edge in {label}: {identity!r}"
                )
            if identity < previous:
                raise GraphOrderingError(f"{label} identities are not sorted")
        previous = identity
        _update_identity_digest(hasher, identity)
        count += 1
    return count, hasher.hexdigest()


def _validate_compact_proof(proof: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(proof, Mapping):
        raise StreamingGraphProofError("compact proof must be a mapping")
    payload = dict(proof)
    encoded = canonical_json_dumps(payload).encode("utf-8")
    if len(encoded) > MAX_COMPACT_PROOF_BYTES:
        raise StreamingGraphProofError(
            f"compact proof exceeds {MAX_COMPACT_PROOF_BYTES} bytes"
        )
    forbidden = {
        "durable_term_document_edges",
        "postings",
        "term_document_edges",
        "terms",
        "vocabulary",
    }

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, nested in value.items():
                if str(key).lower() in forbidden:
                    raise StreamingGraphProofError(
                        f"compact proof contains expanded field {key!r}"
                    )
                visit(nested)
        elif isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            for nested in value:
                visit(nested)

    visit(payload)
    expanded = payload.get("full_term_document_expansion_performed")
    if expanded is not None and expanded is not False:
        raise StreamingGraphProofError("term-document expansion is forbidden")
    try:
        durable_edge_count = int(payload.get("durable_term_document_edge_count") or 0)
    except (TypeError, ValueError) as exc:
        raise StreamingGraphProofError(
            "durable term-document edge count must be an integer"
        ) from exc
    if durable_edge_count != 0:
        raise StreamingGraphProofError("durable term-document edges are forbidden")
    virtual = payload.get("term_document_edges_are_virtual")
    if virtual is not None and virtual is not True:
        raise StreamingGraphProofError("term-document edges must remain virtual")
    proof_ready = payload.get("production_ready")
    if proof_ready is not None and proof_ready is not True:
        raise StreamingGraphProofError("compact proof is not production-ready")
    neighbor_ready = payload.get("optional_neighbor_edges_production_ready")
    if neighbor_ready is not None and neighbor_ready is not True:
        raise StreamingGraphProofError(
            "compact proof depends on non-production neighbor edges"
        )
    return MappingProxyType(payload)


def _write_routing_indexes(
    *,
    root: Path,
    routing_rows: Mapping[str, tuple[Mapping[str, Any], ...]],
) -> Mapping[str, ArtifactDescriptor]:
    descriptors: dict[str, ArtifactDescriptor] = {}
    config = ArtifactWriterConfig(max_rows_per_shard=MAX_ROUTING_ROWS_PER_INDEX)
    for name, relative in CANONICAL_GRAPH_INDEX_PATHS.items():
        rows = routing_rows.get(name, ())
        if not rows:
            raise StreamingGraphCoverageError(
                f"canonical graph routing index {name!r} would be empty"
            )
        if len(rows) > MAX_ROUTING_ROWS_PER_INDEX:
            raise PhysicalBoundError(
                f"routing index {name!r} exceeds {MAX_ROUTING_ROWS_PER_INDEX} rows"
            )
        relative_path = normalize_relative_artifact_path(relative)
        path = confine_path(root, relative_path)
        write_zstd_parquet(
            path,
            list(rows),
            max_rows=MAX_ROUTING_ROWS_PER_INDEX,
            config=config,
        )
        descriptors[name] = describe_file(
            path,
            root=root,
            row_count=len(rows),
            family=ArtifactFamily.ROUTING_INDEX,
            schema_id=GRAPH_ROUTING_SCHEMA_VERSION,
            metadata={"kind": name, "streaming": True},
        )
    return MappingProxyType(descriptors)


def _verify_route_family(
    *,
    name: str,
    rows: Sequence[Mapping[str, Any]],
    descriptors: Mapping[str, ArtifactDescriptor],
    strict_ranges: bool,
) -> None:
    if not rows or len(rows) > MAX_ROUTING_ROWS_PER_INDEX:
        raise StreamingGraphCoverageError(f"invalid routing rows for {name!r}")
    previous_last: str | None = None
    seen_paths: set[str] = set()
    for expected_shard, row in enumerate(rows):
        relative = str(row.get("relative_path") or "")
        descriptor = descriptors.get(relative)
        if descriptor is None:
            raise StreamingGraphCoverageError(
                f"route {name!r} points outside graph descriptors: {relative!r}"
            )
        if relative in seen_paths:
            raise StreamingGraphCoverageError(f"route {name!r} repeats {relative!r}")
        seen_paths.add(relative)
        if int(row.get("shard_id", -1)) != expected_shard:
            raise GraphRangeError(f"route {name!r} shard IDs are not contiguous")
        for attribute in ("sha256", "size_bytes", "row_count", "content_cid"):
            expected = getattr(descriptor, attribute)
            if row.get(attribute) != expected:
                raise StreamingGraphCoverageError(
                    f"route {name!r} {attribute} differs from descriptor"
                )
        first = str(row.get("first_key") or "")
        last = str(row.get("last_key") or "")
        if first != descriptor.first_key or last != descriptor.last_key:
            raise GraphRangeError(f"route {name!r} key range differs")
        if first > last:
            raise GraphRangeError(f"route {name!r} has an inverted key range")
        if previous_last is not None:
            invalid = previous_last >= first if strict_ranges else previous_last > first
            if invalid:
                raise GraphRangeError(f"route {name!r} ranges overlap or regress")
        previous_last = last


def verify_streaming_graph_result(result: StreamingGraphWriteResult) -> None:
    """Verify bytes, routing closure, bounds, counts, and identity proofs."""

    if not isinstance(result, StreamingGraphWriteResult):
        raise StreamingGraphError("result must be a StreamingGraphWriteResult")
    root = resolve_release_root(result.output_root, must_exist=True)
    all_descriptors = (*result.data_descriptors, *result.index_descriptors.values())
    if len({item.relative_path for item in all_descriptors}) != len(all_descriptors):
        raise StreamingGraphCoverageError("graph descriptors repeat a path")
    for descriptor in all_descriptors:
        path = verify_descriptor(root, descriptor)
        validate_zstd_parquet(
            path,
            max_rows=(
                MAX_ROUTING_ROWS_PER_INDEX
                if descriptor.family is ArtifactFamily.ROUTING_INDEX
                else result.config.max_rows_per_shard
            ),
            expected_row_count=descriptor.row_count,
        )

    expected_indexes = set(CANONICAL_GRAPH_INDEX_PATHS)
    if set(result.index_descriptors) != expected_indexes:
        raise StreamingGraphCoverageError("canonical graph index set is incomplete")
    for name, relative in CANONICAL_GRAPH_INDEX_PATHS.items():
        if result.index_descriptors[name].relative_path != relative:
            raise StreamingGraphCoverageError(
                f"canonical graph index path drifted for {name!r}"
            )
        if result.index_descriptors[name].row_count != len(result.routing_rows[name]):
            raise StreamingGraphCoverageError(
                f"routing index row count differs for {name!r}"
            )

    data_by_path = {item.relative_path: item for item in result.data_descriptors}
    _verify_route_family(
        name="graph_node_chunks",
        rows=result.routing_rows["graph_node_chunks"],
        descriptors=data_by_path,
        strict_ranges=True,
    )
    _verify_route_family(
        name="graph_edge_chunks",
        rows=result.routing_rows["graph_edge_chunks"],
        descriptors=data_by_path,
        strict_ranges=True,
    )
    _verify_route_family(
        name="graph_out_adjacency",
        rows=result.routing_rows["graph_out_adjacency"],
        descriptors=data_by_path,
        strict_ranges=False,
    )
    _verify_route_family(
        name="graph_in_adjacency",
        rows=result.routing_rows["graph_in_adjacency"],
        descriptors=data_by_path,
        strict_ranges=False,
    )

    family_counts = {
        ArtifactFamily.GRAPH_NODES: "nodes",
        ArtifactFamily.GRAPH_EDGES: "edges",
        ArtifactFamily.GRAPH_ADJACENCY_OUT: "outgoing_adjacency_pages",
        ArtifactFamily.GRAPH_ADJACENCY_IN: "incoming_adjacency_pages",
    }
    for family, count_name in family_counts.items():
        physical = sum(
            descriptor.row_count
            for descriptor in result.data_descriptors
            if descriptor.family is family
        )
        if physical != result.counts.get(count_name):
            raise StreamingGraphCoverageError(
                f"{family.value} descriptor rows do not reconcile"
            )
    edge_count = result.counts.get("edges", 0)
    if result.counts.get("verified_endpoints") != edge_count * 2:
        raise StreamingGraphEndpointError("endpoint count does not reconcile")
    if result.counts.get("outgoing_adjacency_pointers") != edge_count:
        raise StreamingGraphCoverageError("outgoing adjacency coverage differs")
    if result.counts.get("incoming_adjacency_pointers") != edge_count:
        raise StreamingGraphCoverageError("incoming adjacency coverage differs")
    edge_digest = result.identity_proofs.get("edge_cids_sha256")
    if not edge_digest or (
        result.identity_proofs.get("outgoing_edge_cids_sha256") != edge_digest
        or result.identity_proofs.get("incoming_edge_cids_sha256") != edge_digest
    ):
        raise StreamingGraphCoverageError(
            "incoming/outgoing exact edge identity coverage differs"
        )
    for proof in result.compact_proofs.values():
        _validate_compact_proof(proof)
    expected_receipt_rows = {
        "edges": edge_count,
        "endpoints": edge_count * 2,
        "incoming_adjacency": edge_count,
        "incoming_edge_coverage": edge_count,
        "nodes": result.counts.get("nodes", 0),
        "outgoing_adjacency": edge_count,
        "outgoing_edge_coverage": edge_count,
    }
    if set(result.sort_receipts) != set(expected_receipt_rows):
        raise StreamingGraphError("streaming graph sort receipt set is incomplete")
    for name, receipt in result.sort_receipts.items():
        if (
            receipt.get("status") != "complete"
            or receipt.get("interrupted") is not False
        ):
            raise StreamingGraphError("sort receipt is not complete")
        if int(receipt.get("row_count") or -1) != expected_receipt_rows[name]:
            raise StreamingGraphError(f"sort receipt row count differs for {name!r}")
        digest = str(receipt.get("output_digest") or "")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise StreamingGraphError(f"sort receipt digest is invalid for {name!r}")
        peak = int(receipt.get("peak_resident_records") or 0)
        maximum = int(receipt.get("max_records_in_memory") or 0)
        if peak > maximum:
            raise PhysicalBoundError("sort receipt exceeds its resident-record bound")


def write_streaming_graph_layout(
    nodes: Iterable[Mapping[str, Any] | GraphNode],
    edges: Iterable[Mapping[str, Any] | GraphEdge],
    output_root: str | Path,
    *,
    config: StreamingGraphConfig | None = None,
    bm25_vocabulary_proof: Mapping[str, Any] | None = None,
) -> StreamingGraphWriteResult:
    """Write a bounded graph from one-shot node and edge iterables.

    No network or publication operation is performed.  The returned result is
    marked production-ready only after all staged descriptors, endpoint joins,
    exact adjacency coverage proofs, and canonical routing indexes verify.
    """

    selected = config or StreamingGraphConfig()
    if isinstance(nodes, (str, bytes, bytearray)) or not isinstance(nodes, Iterable):
        raise GraphInputError("nodes must be an iterable")
    if isinstance(edges, (str, bytes, bytearray)) or not isinstance(edges, Iterable):
        raise GraphInputError("edges must be an iterable")
    compact_proofs: dict[str, Mapping[str, Any]] = {}
    if bm25_vocabulary_proof is not None:
        compact_proofs["bm25_vocabulary"] = _validate_compact_proof(
            bm25_vocabulary_proof
        )

    release_root = resolve_release_root(output_root, must_exist=False)
    release_root.mkdir(parents=True, exist_ok=True)
    with atomic_staging(release_root, prefix=".streaming-graph-stage-") as stage:
        work = stage.path / "_streaming_graph_work"
        work.mkdir(parents=True, exist_ok=True)

        node_path = work / "nodes.sorted.jsonl"
        node_sort = _run_sort(
            _iter_node_rows(nodes),
            output_path=node_path,
            work_dir=work / "node-sort",
            key_fn=_node_sort_key,
            config=selected,
        )
        node_family = _write_keyed_shards(
            iter_jsonl(node_path),
            root=stage.path,
            key_field="node_cid",
            directory=GRAPH_NODES_DIR,
            kind="graph_nodes",
            family=ArtifactFamily.GRAPH_NODES,
            schema_id=GRAPH_NODE_SCHEMA_VERSION,
            config=selected,
        )
        if node_family.row_count < 1:
            raise StreamingGraphError("graph requires at least one node")

        edge_path = work / "edges.sorted.jsonl"
        edge_sort = _run_sort(
            _iter_edge_rows(edges),
            output_path=edge_path,
            work_dir=work / "edge-sort",
            key_fn=_edge_sort_key,
            config=selected,
        )
        edge_family = _write_keyed_shards(
            iter_jsonl(edge_path),
            root=stage.path,
            key_field="edge_cid",
            directory=GRAPH_EDGES_DIR,
            kind="graph_edges",
            family=ArtifactFamily.GRAPH_EDGES,
            schema_id=GRAPH_EDGE_SCHEMA_VERSION,
            config=selected,
        )
        if edge_family.row_count < 1:
            raise StreamingGraphError(
                "query-compatible streaming graph requires at least one edge"
            )

        endpoint_path = work / "endpoints.sorted.jsonl"
        endpoint_sort = _run_sort(
            _iter_endpoint_requests(edge_path),
            output_path=endpoint_path,
            work_dir=work / "endpoint-sort",
            key_fn=_endpoint_sort_key,
            config=selected,
        )
        if endpoint_sort.row_count != edge_family.row_count * 2:
            raise StreamingGraphEndpointError("endpoint expansion count differs")

        typed_path = work / "endpoints.typed.jsonl"
        endpoint_counts = {"source": 0, "target": 0}
        typed_receipt = write_jsonl_atomic(
            typed_path,
            _iter_typed_endpoints(node_path, endpoint_path, endpoint_counts),
        )
        if endpoint_counts != {
            "source": edge_family.row_count,
            "target": edge_family.row_count,
        }:
            raise StreamingGraphEndpointError("endpoint roles do not reconcile")

        pointer_sorts: dict[str, ExternalSortReceipt] = {}
        adjacency_families: dict[str, _ShardFamilyResult] = {}
        coverage_sorts: dict[str, ExternalSortReceipt] = {}
        coverage_digests: dict[str, str] = {}
        for direction in ("out", "in"):
            pointer_path = work / f"adjacency-{direction}.sorted.jsonl"
            pointer_sort = _run_sort(
                _iter_direction_pointers(typed_path, direction),
                output_path=pointer_path,
                work_dir=work / f"adjacency-{direction}-sort",
                key_fn=_adjacency_pointer_sort_key,
                config=selected,
            )
            if pointer_sort.row_count != edge_family.row_count:
                raise StreamingGraphCoverageError(
                    f"{direction} pointer count differs from durable edges"
                )
            pointer_sorts[direction] = pointer_sort

            coverage_path = work / f"coverage-{direction}.sorted.jsonl"
            coverage_sort = _run_sort(
                _iter_identity_rows(pointer_path, "edge_cid"),
                output_path=coverage_path,
                work_dir=work / f"coverage-{direction}-sort",
                key_fn=_identity_sort_key,
                config=selected,
            )
            coverage_count, coverage_digest = _digest_unique_identity_file(
                coverage_path,
                label=f"{direction} adjacency",
            )
            if coverage_count != edge_family.row_count:
                raise StreamingGraphCoverageError(
                    f"{direction} exact edge coverage count differs"
                )
            if coverage_digest != edge_family.identity_sha256:
                raise StreamingGraphCoverageError(
                    f"{direction} exact edge CID set differs"
                )
            coverage_sorts[direction] = coverage_sort
            coverage_digests[direction] = coverage_digest

            count_path = work / f"adjacency-{direction}.counts.jsonl"
            count_receipt = write_jsonl_atomic(
                count_path,
                _iter_adjacency_counts(pointer_path),
            )
            family = _write_adjacency_shards(
                _iter_adjacency_pages(
                    pointer_path,
                    count_path,
                    direction=direction,
                    max_pointers_per_page=selected.max_pointers_per_page,
                ),
                root=stage.path,
                direction=direction,
                config=selected,
            )
            if family.pointer_count != edge_family.row_count:
                raise StreamingGraphCoverageError(
                    f"{direction} physical adjacency coverage differs"
                )
            if family.anchor_node_count != count_receipt.row_count:
                raise StreamingGraphCoverageError(
                    f"{direction} adjacency anchor counts differ"
                )
            adjacency_families[direction] = family

        routing_rows: dict[str, tuple[Mapping[str, Any], ...]] = {
            "graph_node_chunks": node_family.routing_rows,
            "graph_edge_chunks": edge_family.routing_rows,
            "graph_out_adjacency": adjacency_families["out"].routing_rows,
            "graph_in_adjacency": adjacency_families["in"].routing_rows,
        }
        index_descriptors = _write_routing_indexes(
            root=stage.path,
            routing_rows=routing_rows,
        )
        data_descriptors = (
            *node_family.descriptors,
            *edge_family.descriptors,
            *adjacency_families["out"].descriptors,
            *adjacency_families["in"].descriptors,
        )
        # Verify all staged bytes before any graph artifact is promoted.
        for descriptor in (*data_descriptors, *index_descriptors.values()):
            verify_descriptor(stage.path, descriptor)

        stage.commit_tree("data/graph", overwrite=selected.overwrite)
        for relative in CANONICAL_GRAPH_INDEX_PATHS.values():
            stage.commit_file(relative, overwrite=selected.overwrite)

    counts = MappingProxyType(
        {
            "edges": edge_family.row_count,
            "incoming_adjacency_anchor_nodes": adjacency_families[
                "in"
            ].anchor_node_count,
            "incoming_adjacency_pages": adjacency_families["in"].page_count,
            "incoming_adjacency_pointers": adjacency_families["in"].pointer_count,
            "nodes": node_family.row_count,
            "outgoing_adjacency_anchor_nodes": adjacency_families[
                "out"
            ].anchor_node_count,
            "outgoing_adjacency_pages": adjacency_families["out"].page_count,
            "outgoing_adjacency_pointers": adjacency_families["out"].pointer_count,
            "verified_endpoints": typed_receipt.row_count,
        }
    )
    identity_proofs = MappingProxyType(
        {
            "digest_encoding": EDGE_IDENTITY_DIGEST_ENCODING,
            "edge_cids_sha256": edge_family.identity_sha256,
            "incoming_edge_cids_sha256": coverage_digests["in"],
            "node_cids_sha256": node_family.identity_sha256,
            "outgoing_edge_cids_sha256": coverage_digests["out"],
        }
    )
    sort_receipts = MappingProxyType(
        {
            "edges": _compact_sort_receipt(edge_sort),
            "endpoints": _compact_sort_receipt(endpoint_sort),
            "incoming_adjacency": _compact_sort_receipt(pointer_sorts["in"]),
            "incoming_edge_coverage": _compact_sort_receipt(coverage_sorts["in"]),
            "nodes": _compact_sort_receipt(node_sort),
            "outgoing_adjacency": _compact_sort_receipt(pointer_sorts["out"]),
            "outgoing_edge_coverage": _compact_sort_receipt(coverage_sorts["out"]),
        }
    )
    checks = MappingProxyType(
        {
            "bounded_physical_shards": True,
            "canonical_external_sort": True,
            "compact_proofs_not_expanded": True,
            "descriptor_verification": True,
            "disk_backed_endpoint_merge": True,
            "duplicate_identity_rejection": True,
            "exact_bidirectional_edge_coverage": True,
            "local_only": True,
            "one_shot_inputs_consumed_once": True,
            "two_way_adjacency": True,
        }
    )
    result = StreamingGraphWriteResult(
        output_root=str(release_root),
        config=selected,
        data_descriptors=tuple(data_descriptors),
        index_descriptors=index_descriptors,
        routing_rows=routing_rows,
        counts=counts,
        identity_proofs=identity_proofs,
        sort_receipts=sort_receipts,
        compact_proofs=compact_proofs,
        checks=checks,
        verified_at_write=True,
    )
    verify_streaming_graph_result(result)
    return result


__all__ = [
    "AUTHORIZES_HUB_UPLOAD",
    "AUTHORIZES_PUBLICATION",
    "CANONICAL_GRAPH_INDEX_PATHS",
    "EDGE_IDENTITY_DIGEST_ENCODING",
    "LEGACY_MATERIALIZED_GRAPH_WRITER_PRODUCTION_READY",
    "MAX_COMPACT_PROOF_BYTES",
    "PERFORMS_NETWORK_IO",
    "PRODUCER",
    "SCHEMA_VERSION",
    "STREAMING_GRAPH_WRITER_PRODUCTION_READY",
    "StreamingGraphConfig",
    "StreamingGraphCoverageError",
    "StreamingGraphDuplicateError",
    "StreamingGraphEndpointError",
    "StreamingGraphError",
    "StreamingGraphProofError",
    "StreamingGraphWriteResult",
    "verify_streaming_graph_result",
    "write_streaming_graph_layout",
]
