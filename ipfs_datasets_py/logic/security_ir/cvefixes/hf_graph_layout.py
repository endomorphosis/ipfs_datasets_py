"""Deterministic Hugging Face graph layout for CVEfixes Security IR.

The layout mirrors the graph portion of ``Publicus/skillcenter-ir``:

* graph node and edge shards live below ``data/graph``;
* bounded incoming and outgoing adjacency pages support remote traversal; and
* compact Parquet meta indexes bind every physical shard by CID, SHA-256,
  byte size, row count, key range, and path.

This module is intentionally independent of the complete CVEfixes release
builder.  It returns immutable in-memory artifacts that can be merged into a
larger release without writing to disk or contacting Hugging Face.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import io
import json
import math
from pathlib import PurePosixPath
import re
from types import MappingProxyType
from typing import Any, Final

from ...ir_core.canonical import canonical_json_bytes
from ...ir_core.identity import cid_v1_from_digest
from .graph import CVEfixesGraph
from .schemas import GraphEdge, GraphNode


CVEFIXES_HF_GRAPH_LAYOUT_SCHEMA_VERSION: Final = (
    "cvefixes-hf-graph-layout/v1"
)
CVEFIXES_HF_GRAPH_NODE_SCHEMA_VERSION: Final = (
    "cvefixes-hf-graph-node/v1"
)
CVEFIXES_HF_GRAPH_EDGE_SCHEMA_VERSION: Final = (
    "cvefixes-hf-graph-edge/v1"
)
CVEFIXES_HF_GRAPH_ADJACENCY_SCHEMA_VERSION: Final = (
    "cvefixes-hf-graph-adjacency/v1"
)
CVEFIXES_HF_SHARD_META_SCHEMA_VERSION: Final = (
    "cvefixes-hf-shard-meta/v1"
)

GRAPH_HF_CONFIG_PATHS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "graph_edges": "data/graph/edges/*.parquet",
        "graph_incoming_adjacency": (
            "data/graph/adjacency/incoming/*.parquet"
        ),
        "graph_nodes": "data/graph/nodes/*.parquet",
        "graph_outgoing_adjacency": (
            "data/graph/adjacency/outgoing/*.parquet"
        ),
        "graph_edge_chunk_index": "indexes/graph_edge_chunks.parquet",
        "graph_incoming_adjacency_index": (
            "indexes/graph_incoming_adjacency.parquet"
        ),
        "graph_node_chunk_index": "indexes/graph_node_chunks.parquet",
        "graph_outgoing_adjacency_index": (
            "indexes/graph_outgoing_adjacency.parquet"
        ),
    }
)
GRAPH_HF_MANIFEST_INDEX_PATHS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "graph_edge_chunks": "indexes/graph_edge_chunks.parquet",
        "graph_incoming_adjacency": (
            "indexes/graph_incoming_adjacency.parquet"
        ),
        "graph_node_chunks": "indexes/graph_node_chunks.parquet",
        "graph_outgoing_adjacency": (
            "indexes/graph_outgoing_adjacency.parquet"
        ),
    }
)

_DATA_CONFIG_BY_PREFIX: Final[Mapping[str, str]] = MappingProxyType(
    {
        "data/graph/adjacency/incoming/": "graph_incoming_adjacency",
        "data/graph/adjacency/outgoing/": "graph_outgoing_adjacency",
        "data/graph/edges/": "graph_edges",
        "data/graph/nodes/": "graph_nodes",
    }
)
_INDEX_CONFIG_BY_PATH: Final[Mapping[str, str]] = MappingProxyType(
    {
        "indexes/graph_edge_chunks.parquet": "graph_edge_chunk_index",
        "indexes/graph_incoming_adjacency.parquet": (
            "graph_incoming_adjacency_index"
        ),
        "indexes/graph_node_chunks.parquet": "graph_node_chunk_index",
        "indexes/graph_outgoing_adjacency.parquet": (
            "graph_outgoing_adjacency_index"
        ),
    }
)
_DATA_CONFIG_TO_INDEX: Final[Mapping[str, str]] = MappingProxyType(
    {
        "graph_edges": "indexes/graph_edge_chunks.parquet",
        "graph_incoming_adjacency": (
            "indexes/graph_incoming_adjacency.parquet"
        ),
        "graph_nodes": "indexes/graph_node_chunks.parquet",
        "graph_outgoing_adjacency": (
            "indexes/graph_outgoing_adjacency.parquet"
        ),
    }
)
_DATA_CONFIG_TO_KIND: Final[Mapping[str, str]] = MappingProxyType(
    {
        "graph_edges": "graph_edges",
        "graph_incoming_adjacency": "graph_incoming_adjacency",
        "graph_nodes": "graph_nodes",
        "graph_outgoing_adjacency": "graph_outgoing_adjacency",
    }
)
_DATA_KEY_COLUMN: Final[Mapping[str, str]] = MappingProxyType(
    {
        "graph_edges": "edge_cid",
        "graph_incoming_adjacency": "node_cid",
        "graph_nodes": "node_cid",
        "graph_outgoing_adjacency": "node_cid",
    }
)
_CID_RE = re.compile(r"b[a-z2-7]{58}")
_PART_RE = re.compile(r"part-(\d{6})\.parquet")
_BASE_META_COLUMNS: Final[tuple[str, ...]] = (
    "cid",
    "end_document_index",
    "first_key",
    "kind",
    "last_key",
    "relative_path",
    "row_count",
    "schema_version",
    "sha256",
    "shard_id",
    "size_bytes",
    "start_document_index",
)
_ADJACENCY_META_COLUMNS: Final[tuple[str, ...]] = (
    "adjacency_count",
    "direction",
    "first_page_index",
    "last_page_index",
    "node_count",
)
_NODE_LABEL_KEYS: Final[tuple[str, ...]] = (
    "cve_id",
    "cwe_id",
    "repository",
    "commit_hash",
    "path",
    "predicate",
    "language",
    "source_cid",
    "code_unit_cid",
    "fact_cid",
)


class HuggingFaceGraphLayoutError(ValueError):
    """Base error for malformed graph layouts."""


class HuggingFaceGraphLayoutIntegrityError(HuggingFaceGraphLayoutError):
    """Raised when a graph artifact or pointer fails integrity validation."""


class HuggingFaceGraphLayoutLimitError(HuggingFaceGraphLayoutError):
    """Raised when an artifact exceeds an explicit release bound."""


def _positive_int(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise HuggingFaceGraphLayoutError(
            f"{label} must be a positive integer"
        )
    return value


@dataclass(frozen=True, slots=True)
class HuggingFaceGraphLayoutConfig:
    """Physical sharding limits shared by local and remote graph clients."""

    max_rows_per_shard: int = 4_096
    max_shards_per_config: int = 4_096
    max_shard_bytes: int = 64 * 1024 * 1024
    row_group_size: int = 4_096
    adjacency_pointers_per_row: int = 4_096
    adjacency_pointers_per_shard: int = 8_192
    compression: str = "zstd"
    compression_level: int = 6
    schema_version: str = CVEFIXES_HF_GRAPH_LAYOUT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for name in (
            "max_rows_per_shard",
            "max_shards_per_config",
            "max_shard_bytes",
            "row_group_size",
            "adjacency_pointers_per_row",
            "adjacency_pointers_per_shard",
            "compression_level",
        ):
            _positive_int(getattr(self, name), name)
        if self.row_group_size > self.max_rows_per_shard:
            raise HuggingFaceGraphLayoutError(
                "row_group_size cannot exceed max_rows_per_shard"
            )
        if (
            self.adjacency_pointers_per_row
            > self.adjacency_pointers_per_shard
        ):
            raise HuggingFaceGraphLayoutError(
                "adjacency_pointers_per_row cannot exceed "
                "adjacency_pointers_per_shard"
            )
        if self.compression != "zstd":
            raise HuggingFaceGraphLayoutError(
                "SkillCenter-compatible graph shards require zstd"
            )
        if self.schema_version != CVEFIXES_HF_GRAPH_LAYOUT_SCHEMA_VERSION:
            raise HuggingFaceGraphLayoutError(
                "unsupported graph layout schema version"
            )


def _expected_config(path: str) -> str:
    if path in _INDEX_CONFIG_BY_PATH:
        return _INDEX_CONFIG_BY_PATH[path]
    for prefix, config_name in _DATA_CONFIG_BY_PREFIX.items():
        if path.startswith(prefix):
            suffix = path[len(prefix) :]
            if _PART_RE.fullmatch(suffix):
                return config_name
    raise HuggingFaceGraphLayoutError(
        f"unsupported graph artifact path: {path!r}"
    )


@dataclass(frozen=True, slots=True)
class HuggingFaceGraphArtifact:
    """One immutable graph Parquet artifact and its raw-byte CID."""

    path: str
    config_name: str
    content: bytes = field(repr=False)
    row_count: int
    sha256: str = ""
    cid: str = ""

    def __post_init__(self) -> None:
        if (
            not isinstance(self.path, str)
            or not self.path
            or self.path != PurePosixPath(self.path).as_posix()
            or PurePosixPath(self.path).is_absolute()
            or any(
                part in {"", ".", ".."}
                for part in PurePosixPath(self.path).parts
            )
        ):
            raise HuggingFaceGraphLayoutError("unsafe graph artifact path")
        expected_config = _expected_config(self.path)
        if self.config_name != expected_config:
            raise HuggingFaceGraphLayoutError(
                "graph artifact config does not match its path"
            )
        if not isinstance(self.content, bytes):
            raise HuggingFaceGraphLayoutError(
                "graph artifact content must be bytes"
            )
        if type(self.row_count) is not int or self.row_count < 0:
            raise HuggingFaceGraphLayoutError(
                "graph artifact row_count must be non-negative"
            )
        digest = hashlib.sha256(self.content).digest()
        digest_hex = digest.hex()
        content_cid = cid_v1_from_digest(digest)
        if self.sha256 and self.sha256 != digest_hex:
            raise HuggingFaceGraphLayoutIntegrityError(
                "graph artifact SHA-256 differs from its content"
            )
        if self.cid and self.cid != content_cid:
            raise HuggingFaceGraphLayoutIntegrityError(
                "graph artifact CID differs from its content"
            )
        object.__setattr__(self, "sha256", digest_hex)
        object.__setattr__(self, "cid", content_cid)

    @property
    def is_index(self) -> bool:
        return self.path.startswith("indexes/")

    @property
    def is_data(self) -> bool:
        return self.path.startswith("data/")

    def descriptor(self) -> dict[str, Any]:
        return {
            "cid": self.cid,
            "config_name": self.config_name,
            "relative_path": self.path,
            "row_count": self.row_count,
            "sha256": self.sha256,
            "size_bytes": len(self.content),
        }


@dataclass(frozen=True, slots=True)
class CVEfixesHuggingFaceGraphLayout:
    """Complete graph data and meta-index artifact inventory."""

    graph_root: str
    artifacts: tuple[HuggingFaceGraphArtifact, ...]
    config: HuggingFaceGraphLayoutConfig
    entry_cid_by_node: Mapping[str, str] = field(default_factory=dict)
    schema_version: str = CVEFIXES_HF_GRAPH_LAYOUT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.graph_root, str) or not _CID_RE.fullmatch(
            self.graph_root
        ):
            raise HuggingFaceGraphLayoutIntegrityError(
                "graph_root must be a CIDv1"
            )
        if not isinstance(self.config, HuggingFaceGraphLayoutConfig):
            raise HuggingFaceGraphLayoutError(
                "config must be HuggingFaceGraphLayoutConfig"
            )
        if self.schema_version != CVEFIXES_HF_GRAPH_LAYOUT_SCHEMA_VERSION:
            raise HuggingFaceGraphLayoutIntegrityError(
                "unsupported graph layout schema version"
            )
        if not isinstance(self.entry_cid_by_node, Mapping):
            raise HuggingFaceGraphLayoutError(
                "entry_cid_by_node must be a mapping"
            )
        entry_cid_by_node = dict(sorted(self.entry_cid_by_node.items()))
        if any(
            not isinstance(node_cid, str)
            or _CID_RE.fullmatch(node_cid) is None
            or not isinstance(entry_cid, str)
            or _CID_RE.fullmatch(entry_cid) is None
            for node_cid, entry_cid in entry_cid_by_node.items()
        ):
            raise HuggingFaceGraphLayoutIntegrityError(
                "entry_cid_by_node must bind CIDv1 strings"
            )
        if len(set(entry_cid_by_node.values())) != len(entry_cid_by_node):
            raise HuggingFaceGraphLayoutIntegrityError(
                "entry_cid_by_node values must be unique"
            )
        object.__setattr__(
            self,
            "entry_cid_by_node",
            MappingProxyType(entry_cid_by_node),
        )
        artifacts = tuple(sorted(self.artifacts, key=lambda item: item.path))
        if not artifacts or len({item.path for item in artifacts}) != len(
            artifacts
        ):
            raise HuggingFaceGraphLayoutIntegrityError(
                "graph artifacts must be non-empty with unique paths"
            )
        if not all(
            isinstance(item, HuggingFaceGraphArtifact)
            for item in artifacts
        ):
            raise HuggingFaceGraphLayoutError(
                "artifacts must contain HuggingFaceGraphArtifact values"
            )
        configs = {item.config_name for item in artifacts}
        if configs != set(GRAPH_HF_CONFIG_PATHS):
            raise HuggingFaceGraphLayoutIntegrityError(
                "graph artifact config inventory is incomplete"
            )
        for index_path in _INDEX_CONFIG_BY_PATH:
            if sum(item.path == index_path for item in artifacts) != 1:
                raise HuggingFaceGraphLayoutIntegrityError(
                    f"graph layout requires exactly one {index_path}"
                )
        for config_name in _DATA_CONFIG_TO_INDEX:
            if not any(
                item.config_name == config_name for item in artifacts
            ):
                raise HuggingFaceGraphLayoutIntegrityError(
                    f"graph layout has no {config_name} shard"
                )
        object.__setattr__(self, "artifacts", artifacts)

    @property
    def data_artifacts(self) -> tuple[HuggingFaceGraphArtifact, ...]:
        return tuple(item for item in self.artifacts if item.is_data)

    @property
    def index_artifacts(self) -> tuple[HuggingFaceGraphArtifact, ...]:
        return tuple(item for item in self.artifacts if item.is_index)

    def artifact(self, path: str) -> HuggingFaceGraphArtifact:
        for artifact in self.artifacts:
            if artifact.path == path:
                return artifact
        raise KeyError(path)


@dataclass(frozen=True, slots=True)
class HuggingFaceGraphLayoutValidation:
    """Summary returned after exact graph and pointer validation."""

    graph_root: str
    artifact_count: int
    data_shard_count: int
    node_count: int
    edge_count: int
    outgoing_adjacency_rows: int
    incoming_adjacency_rows: int
    valid: bool = True


def _pyarrow() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - project release dependency
        raise HuggingFaceGraphLayoutError(
            "pyarrow is required to build the graph Hugging Face layout"
        ) from exc
    return pa, pq


def _node_schema() -> Any:
    pa, _ = _pyarrow()
    return pa.schema(
        [
            ("node_cid", pa.string(), False),
            ("node_type", pa.string(), False),
            # Nullable to retain the SkillCenter graph-node physical schema.
            # CVEfixes rows currently populate this from their first source CID.
            ("entry_cid", pa.string()),
            ("label", pa.string(), False),
            ("properties_json", pa.large_string(), False),
            ("schema_version", pa.string(), False),
        ],
        metadata={
            b"schema_version": (
                CVEFIXES_HF_GRAPH_NODE_SCHEMA_VERSION.encode("ascii")
            )
        },
    )


def _edge_schema() -> Any:
    pa, _ = _pyarrow()
    return pa.schema(
        [
            ("edge_cid", pa.string(), False),
            ("edge_type", pa.string(), False),
            ("source_cid", pa.string(), False),
            ("target_cid", pa.string(), False),
            ("retrieval_method", pa.string(), False),
            ("score", pa.float64()),
            ("query_terms_json", pa.large_string(), False),
            ("properties_json", pa.large_string(), False),
            ("schema_version", pa.string(), False),
        ],
        metadata={
            b"schema_version": (
                CVEFIXES_HF_GRAPH_EDGE_SCHEMA_VERSION.encode("ascii")
            )
        },
    )


def _adjacency_schema() -> Any:
    pa, _ = _pyarrow()
    return pa.schema(
        [
            ("direction", pa.string(), False),
            ("edge_cids", pa.list_(pa.string()), False),
            ("edge_types", pa.list_(pa.string()), False),
            ("neighbor_cids", pa.list_(pa.string()), False),
            ("neighbor_count", pa.int32(), False),
            ("neighbor_node_types", pa.list_(pa.string()), False),
            ("node_cid", pa.string(), False),
            ("page_count", pa.int32(), False),
            ("page_index", pa.int32(), False),
            ("retrieval_methods", pa.list_(pa.string()), False),
            ("schema_version", pa.string(), False),
            ("scores", pa.list_(pa.float64()), False),
            ("total_neighbor_count", pa.int64(), False),
        ],
        metadata={
            b"schema_version": (
                CVEFIXES_HF_GRAPH_ADJACENCY_SCHEMA_VERSION.encode("ascii")
            )
        },
    )


def _meta_schema(*, adjacency: bool) -> Any:
    pa, _ = _pyarrow()
    fields = [
        ("cid", pa.string(), False),
        ("end_document_index", pa.int64(), False),
        ("first_key", pa.string(), False),
        ("kind", pa.string(), False),
        ("last_key", pa.string(), False),
        ("relative_path", pa.string(), False),
        ("row_count", pa.int64(), False),
        ("schema_version", pa.string(), False),
        ("sha256", pa.string(), False),
        ("shard_id", pa.int32(), False),
        ("size_bytes", pa.int64(), False),
        ("start_document_index", pa.int64(), False),
    ]
    if adjacency:
        fields.extend(
            [
                ("adjacency_count", pa.int64(), False),
                ("direction", pa.string(), False),
                ("first_page_index", pa.int32(), False),
                ("last_page_index", pa.int32(), False),
                ("node_count", pa.int32(), False),
            ]
        )
    return pa.schema(
        fields,
        metadata={
            b"schema_version": (
                CVEFIXES_HF_SHARD_META_SCHEMA_VERSION.encode("ascii")
            )
        },
    )


def _parquet_bytes(
    rows: Sequence[Mapping[str, Any]],
    schema: Any,
    config: HuggingFaceGraphLayoutConfig,
) -> bytes:
    pa, pq = _pyarrow()
    table = pa.Table.from_pylist(list(rows), schema=schema)
    output = io.BytesIO()
    pq.write_table(
        table,
        output,
        compression=config.compression,
        compression_level=config.compression_level,
        data_page_version="1.0",
        row_group_size=config.row_group_size,
        use_dictionary=True,
        version="2.6",
        write_statistics=True,
    )
    return output.getvalue()


def _canonical_json(value: Any) -> str:
    try:
        return canonical_json_bytes(value).decode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HuggingFaceGraphLayoutError(
            "graph properties must be finite canonical JSON"
        ) from exc


def _node_label(node: GraphNode) -> str:
    for key in _NODE_LABEL_KEYS:
        value = node.payload.get(key)
        if isinstance(value, str) and value:
            return value
    return f"{node.node_type}:{node.cid}"


def _node_rows(
    graph: CVEfixesGraph,
    *,
    entry_cid_by_node: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], ...]:
    entry_cid_by_node = entry_cid_by_node or {}
    return tuple(
        {
            "entry_cid": entry_cid_by_node.get(
                node.cid, node.source_cids[0]
            ),
            "label": _node_label(node),
            "node_cid": node.cid,
            "node_type": node.node_type,
            "properties_json": _canonical_json(node.to_dict()),
            "schema_version": CVEFIXES_HF_GRAPH_NODE_SCHEMA_VERSION,
        }
        for node in graph.nodes
    )


def _edge_score(edge: GraphEdge) -> float | None:
    value = edge.payload.get("score")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    result = float(value)
    if not math.isfinite(result):
        raise HuggingFaceGraphLayoutError("graph edge score must be finite")
    return result


def _retrieval_method(edge: GraphEdge) -> str:
    explicit = edge.payload.get("retrieval_method")
    if isinstance(explicit, str) and explicit:
        return explicit
    if edge.payload.get("edge_class") == "similarity":
        return "vector_similarity"
    return "deterministic_graph"


def _query_terms(edge: GraphEdge) -> list[str]:
    raw = edge.payload.get("query_terms", ())
    if isinstance(raw, Sequence) and not isinstance(
        raw, (str, bytes, bytearray)
    ):
        values = [
            item for item in raw if isinstance(item, str) and item
        ]
        return sorted(set(values))
    return []


def _edge_rows(graph: CVEfixesGraph) -> tuple[dict[str, Any], ...]:
    return tuple(
        {
            "edge_cid": edge.cid,
            "edge_type": edge.edge_type,
            "properties_json": _canonical_json(edge.to_dict()),
            "query_terms_json": _canonical_json(_query_terms(edge)),
            "retrieval_method": _retrieval_method(edge),
            "schema_version": CVEFIXES_HF_GRAPH_EDGE_SCHEMA_VERSION,
            "score": _edge_score(edge),
            "source_cid": edge.source_node_cid,
            "target_cid": edge.target_node_cid,
        }
        for edge in graph.edges
    )


def _adjacency_sort_key(
    edge: GraphEdge,
    *,
    neighbor_cid: str,
) -> tuple[Any, ...]:
    score = _edge_score(edge)
    return (
        score is None,
        -(score if score is not None else 0.0),
        edge.edge_type,
        neighbor_cid,
        edge.cid,
    )


def _adjacency_rows(
    graph: CVEfixesGraph,
    *,
    direction: str,
    config: HuggingFaceGraphLayoutConfig,
) -> tuple[dict[str, Any], ...]:
    if direction not in {"incoming", "outgoing"}:
        raise HuggingFaceGraphLayoutError(
            f"unsupported graph adjacency direction: {direction}"
        )
    node_by_cid = {node.cid: node for node in graph.nodes}
    edge_by_cid = {edge.cid: edge for edge in graph.edges}
    adjacency = graph.outgoing if direction == "outgoing" else graph.incoming
    result: list[dict[str, Any]] = []
    for node_cid in sorted(node_by_cid):
        selected: list[tuple[GraphEdge, str]] = []
        for edge_cid in adjacency[node_cid]:
            edge = edge_by_cid[edge_cid]
            neighbor_cid = (
                edge.target_node_cid
                if direction == "outgoing"
                else edge.source_node_cid
            )
            selected.append((edge, neighbor_cid))
        selected.sort(
            key=lambda item: _adjacency_sort_key(
                item[0], neighbor_cid=item[1]
            )
        )
        page_count = max(
            1,
            math.ceil(
                len(selected) / config.adjacency_pointers_per_row
            ),
        )
        starts: Sequence[int] = (
            range(
                0,
                len(selected),
                config.adjacency_pointers_per_row,
            )
            if selected
            else (0,)
        )
        for page_index, start in enumerate(starts):
            page = selected[
                start : start + config.adjacency_pointers_per_row
            ]
            result.append(
                {
                    "direction": direction,
                    "edge_cids": [edge.cid for edge, _ in page],
                    "edge_types": [edge.edge_type for edge, _ in page],
                    "neighbor_cids": [
                        neighbor_cid for _, neighbor_cid in page
                    ],
                    "neighbor_count": len(page),
                    "neighbor_node_types": [
                        node_by_cid[neighbor_cid].node_type
                        for _, neighbor_cid in page
                    ],
                    "node_cid": node_cid,
                    "page_count": page_count,
                    "page_index": page_index,
                    "retrieval_methods": [
                        _retrieval_method(edge) for edge, _ in page
                    ],
                    "schema_version": (
                        CVEFIXES_HF_GRAPH_ADJACENCY_SCHEMA_VERSION
                    ),
                    "scores": [
                        _edge_score(edge) for edge, _ in page
                    ],
                    "total_neighbor_count": len(selected),
                }
            )
    return tuple(result)


def _chunks(
    rows: Sequence[Mapping[str, Any]],
    *,
    maximum: int,
) -> Iterator[tuple[Mapping[str, Any], ...]]:
    if not rows:
        yield ()
        return
    for start in range(0, len(rows), maximum):
        yield tuple(rows[start : start + maximum])


def _adjacency_chunks(
    rows: Sequence[Mapping[str, Any]],
    config: HuggingFaceGraphLayoutConfig,
) -> Iterator[tuple[Mapping[str, Any], ...]]:
    if not rows:
        yield ()
        return
    pending: list[Mapping[str, Any]] = []
    pointer_count = 0
    for row in rows:
        row_pointers = int(row["neighbor_count"])
        if row_pointers > config.adjacency_pointers_per_row:
            raise HuggingFaceGraphLayoutLimitError(
                "adjacency row exceeds pointer bound"
            )
        if pending and (
            len(pending) >= config.max_rows_per_shard
            or pointer_count + row_pointers
            > config.adjacency_pointers_per_shard
        ):
            yield tuple(pending)
            pending = []
            pointer_count = 0
        pending.append(row)
        pointer_count += row_pointers
    if pending:
        yield tuple(pending)


def _make_data_artifacts(
    rows: Sequence[Mapping[str, Any]],
    *,
    config_name: str,
    directory: str,
    schema: Any,
    config: HuggingFaceGraphLayoutConfig,
    adjacency: bool = False,
) -> tuple[HuggingFaceGraphArtifact, ...]:
    row_chunks = (
        _adjacency_chunks(rows, config)
        if adjacency
        else _chunks(rows, maximum=config.max_rows_per_shard)
    )
    artifacts: list[HuggingFaceGraphArtifact] = []
    for shard_id, chunk in enumerate(row_chunks):
        content = _parquet_bytes(chunk, schema, config)
        if len(content) > config.max_shard_bytes:
            raise HuggingFaceGraphLayoutLimitError(
                f"{config_name} shard exceeds max_shard_bytes"
            )
        artifacts.append(
            HuggingFaceGraphArtifact(
                path=f"{directory}/part-{shard_id:06d}.parquet",
                config_name=config_name,
                content=content,
                row_count=len(chunk),
            )
        )
    if len(artifacts) > config.max_shards_per_config:
        raise HuggingFaceGraphLayoutLimitError(
            f"{config_name} exceeds max_shards_per_config"
        )
    return tuple(artifacts)


def _read_table(artifact: HuggingFaceGraphArtifact) -> Any:
    _, pq = _pyarrow()
    try:
        return pq.read_table(io.BytesIO(artifact.content))
    except Exception as exc:
        raise HuggingFaceGraphLayoutIntegrityError(
            f"cannot decode graph artifact {artifact.path}"
        ) from exc


def _shard_id(artifact: HuggingFaceGraphArtifact) -> int:
    match = _PART_RE.fullmatch(PurePosixPath(artifact.path).name)
    if match is None:
        raise HuggingFaceGraphLayoutIntegrityError(
            "data shard name is malformed"
        )
    return int(match.group(1))


def _meta_row(
    artifact: HuggingFaceGraphArtifact,
    rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    key_column = _DATA_KEY_COLUMN[artifact.config_name]
    first_key = str(rows[0][key_column]) if rows else ""
    last_key = str(rows[-1][key_column]) if rows else ""
    result = {
        "cid": artifact.cid,
        "end_document_index": -1,
        "first_key": first_key,
        "kind": _DATA_CONFIG_TO_KIND[artifact.config_name],
        "last_key": last_key,
        "relative_path": artifact.path,
        "row_count": artifact.row_count,
        "schema_version": CVEFIXES_HF_SHARD_META_SCHEMA_VERSION,
        "sha256": artifact.sha256,
        "shard_id": _shard_id(artifact),
        "size_bytes": len(artifact.content),
        "start_document_index": -1,
    }
    if "adjacency" in artifact.config_name:
        direction = (
            "incoming"
            if artifact.config_name == "graph_incoming_adjacency"
            else "outgoing"
        )
        result.update(
            {
                "adjacency_count": sum(
                    int(row["neighbor_count"]) for row in rows
                ),
                "direction": direction,
                "first_page_index": (
                    int(rows[0]["page_index"]) if rows else -1
                ),
                "last_page_index": (
                    int(rows[-1]["page_index"]) if rows else -1
                ),
                "node_count": len(
                    {str(row["node_cid"]) for row in rows}
                ),
            }
        )
    return result


def _make_index_artifact(
    data_artifacts: Sequence[HuggingFaceGraphArtifact],
    *,
    index_path: str,
    config: HuggingFaceGraphLayoutConfig,
) -> HuggingFaceGraphArtifact:
    if not data_artifacts:
        raise HuggingFaceGraphLayoutIntegrityError(
            f"cannot index an empty shard inventory: {index_path}"
        )
    rows = []
    for artifact in sorted(data_artifacts, key=lambda item: item.path):
        rows.append(_meta_row(artifact, _read_table(artifact).to_pylist()))
    adjacency = "adjacency" in data_artifacts[0].config_name
    content = _parquet_bytes(
        rows,
        _meta_schema(adjacency=adjacency),
        config,
    )
    if len(content) > config.max_shard_bytes:
        raise HuggingFaceGraphLayoutLimitError(
            f"meta index exceeds max_shard_bytes: {index_path}"
        )
    return HuggingFaceGraphArtifact(
        path=index_path,
        config_name=_INDEX_CONFIG_BY_PATH[index_path],
        content=content,
        row_count=len(rows),
    )


def build_cvefixes_hf_graph_layout(
    graph: CVEfixesGraph,
    *,
    config: HuggingFaceGraphLayoutConfig | None = None,
    entry_cid_by_node: Mapping[str, str] | None = None,
) -> CVEfixesHuggingFaceGraphLayout:
    """Build all graph data shards and exact one-to-one meta indexes."""

    if not isinstance(graph, CVEfixesGraph):
        raise HuggingFaceGraphLayoutError("graph must be CVEfixesGraph")
    if not graph.nodes:
        raise HuggingFaceGraphLayoutError(
            "graph must contain at least one node"
        )
    resolved_config = config or HuggingFaceGraphLayoutConfig()
    if not isinstance(resolved_config, HuggingFaceGraphLayoutConfig):
        raise HuggingFaceGraphLayoutError(
            "config must be HuggingFaceGraphLayoutConfig"
        )
    entry_cid_by_node = entry_cid_by_node or {}
    if not isinstance(entry_cid_by_node, Mapping):
        raise HuggingFaceGraphLayoutError(
            "entry_cid_by_node must be a mapping"
        )
    if entry_cid_by_node and set(entry_cid_by_node) != {
        node.cid for node in graph.nodes
    }:
        raise HuggingFaceGraphLayoutIntegrityError(
            "entry_cid_by_node must bind every and only graph node"
        )

    nodes = _make_data_artifacts(
        _node_rows(graph, entry_cid_by_node=entry_cid_by_node),
        config_name="graph_nodes",
        directory="data/graph/nodes",
        schema=_node_schema(),
        config=resolved_config,
    )
    edges = _make_data_artifacts(
        _edge_rows(graph),
        config_name="graph_edges",
        directory="data/graph/edges",
        schema=_edge_schema(),
        config=resolved_config,
    )
    outgoing = _make_data_artifacts(
        _adjacency_rows(
            graph, direction="outgoing", config=resolved_config
        ),
        config_name="graph_outgoing_adjacency",
        directory="data/graph/adjacency/outgoing",
        schema=_adjacency_schema(),
        config=resolved_config,
        adjacency=True,
    )
    incoming = _make_data_artifacts(
        _adjacency_rows(
            graph, direction="incoming", config=resolved_config
        ),
        config_name="graph_incoming_adjacency",
        directory="data/graph/adjacency/incoming",
        schema=_adjacency_schema(),
        config=resolved_config,
        adjacency=True,
    )
    grouped = {
        "graph_edges": edges,
        "graph_incoming_adjacency": incoming,
        "graph_nodes": nodes,
        "graph_outgoing_adjacency": outgoing,
    }
    indexes = tuple(
        _make_index_artifact(
            grouped[config_name],
            index_path=index_path,
            config=resolved_config,
        )
        for config_name, index_path in _DATA_CONFIG_TO_INDEX.items()
    )
    layout = CVEfixesHuggingFaceGraphLayout(
        graph_root=graph.graph_root,
        artifacts=tuple(
            item
            for config_name in sorted(grouped)
            for item in grouped[config_name]
        )
        + indexes,
        config=resolved_config,
        entry_cid_by_node=entry_cid_by_node,
    )
    validate_cvefixes_hf_graph_layout(layout, graph=graph)
    return layout


def _expected_schema(config_name: str) -> Any:
    if config_name == "graph_nodes":
        return _node_schema()
    if config_name == "graph_edges":
        return _edge_schema()
    if config_name in {
        "graph_incoming_adjacency",
        "graph_outgoing_adjacency",
    }:
        return _adjacency_schema()
    if config_name in {
        "graph_node_chunk_index",
        "graph_edge_chunk_index",
    }:
        return _meta_schema(adjacency=False)
    if config_name in {
        "graph_incoming_adjacency_index",
        "graph_outgoing_adjacency_index",
    }:
        return _meta_schema(adjacency=True)
    raise HuggingFaceGraphLayoutIntegrityError(
        f"unsupported graph config: {config_name}"
    )


def _validate_artifact_table(
    artifact: HuggingFaceGraphArtifact,
    config: HuggingFaceGraphLayoutConfig,
) -> list[dict[str, Any]]:
    if len(artifact.content) > config.max_shard_bytes:
        raise HuggingFaceGraphLayoutLimitError(
            f"artifact exceeds max_shard_bytes: {artifact.path}"
        )
    table = _read_table(artifact)
    expected_schema = _expected_schema(artifact.config_name)
    # Parquet normalizes nested-list child names from ``item`` to ``element``.
    # PyArrow treats the fields as equal but may reject the complete schema
    # when ``check_metadata=True``, even when the schema metadata is identical.
    if (
        not table.schema.equals(expected_schema, check_metadata=False)
        or table.schema.metadata != expected_schema.metadata
    ):
        raise HuggingFaceGraphLayoutIntegrityError(
            f"unexpected Parquet schema: {artifact.path}"
        )
    if table.num_rows != artifact.row_count:
        raise HuggingFaceGraphLayoutIntegrityError(
            f"Parquet row count differs: {artifact.path}"
        )
    if (
        artifact.is_data
        and table.num_rows > config.max_rows_per_shard
    ):
        raise HuggingFaceGraphLayoutLimitError(
            f"data shard exceeds row bound: {artifact.path}"
        )
    rows = table.to_pylist()
    if (
        artifact.is_data
        and "adjacency" in artifact.config_name
        and sum(int(row["neighbor_count"]) for row in rows)
        > config.adjacency_pointers_per_shard
    ):
        raise HuggingFaceGraphLayoutLimitError(
            f"adjacency shard exceeds pointer bound: {artifact.path}"
        )
    return rows


def _validate_canonical_graph_rows(
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Mapping[str, Any]],
    *,
    entry_cid_by_node: Mapping[str, str],
) -> tuple[dict[str, str], set[str]]:
    node_types: dict[str, str] = {}
    for row in nodes:
        try:
            node = GraphNode.from_dict(json.loads(row["properties_json"]))
        except Exception as exc:
            raise HuggingFaceGraphLayoutIntegrityError(
                "graph node properties are not a canonical GraphNode"
            ) from exc
        if (
            row["node_cid"] != node.cid
            or row["node_type"] != node.node_type
            or row["entry_cid"]
            != entry_cid_by_node.get(node.cid, node.source_cids[0])
            or row["label"] != _node_label(node)
            or row["schema_version"]
            != CVEFIXES_HF_GRAPH_NODE_SCHEMA_VERSION
            or row["properties_json"] != _canonical_json(node.to_dict())
            or node.cid in node_types
        ):
            raise HuggingFaceGraphLayoutIntegrityError(
                "graph node identity columns differ"
            )
        node_types[node.cid] = node.node_type
    edge_ids: set[str] = set()
    for row in edges:
        try:
            edge = GraphEdge.from_dict(json.loads(row["properties_json"]))
        except Exception as exc:
            raise HuggingFaceGraphLayoutIntegrityError(
                "graph edge properties are not a canonical GraphEdge"
            ) from exc
        if (
            row["edge_cid"] != edge.cid
            or row["edge_type"] != edge.edge_type
            or row["source_cid"] != edge.source_node_cid
            or row["target_cid"] != edge.target_node_cid
            or row["retrieval_method"] != _retrieval_method(edge)
            or row["score"] != _edge_score(edge)
            or row["query_terms_json"] != _canonical_json(_query_terms(edge))
            or row["schema_version"]
            != CVEFIXES_HF_GRAPH_EDGE_SCHEMA_VERSION
            or row["properties_json"] != _canonical_json(edge.to_dict())
            or edge.cid in edge_ids
            or edge.source_node_cid not in node_types
            or edge.target_node_cid not in node_types
        ):
            raise HuggingFaceGraphLayoutIntegrityError(
                "graph edge identity columns differ"
            )
        edge_ids.add(edge.cid)
    return node_types, edge_ids


def _validate_adjacency_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    direction: str,
    node_types: Mapping[str, str],
    edge_ids: set[str],
    edge_rows: Mapping[str, Mapping[str, Any]],
    config: HuggingFaceGraphLayoutConfig,
) -> None:
    node_ids = set(node_types)
    pages_by_node: dict[str, list[Mapping[str, Any]]] = {}
    seen_edges: set[str] = set()
    for row in rows:
        node_cid = str(row["node_cid"])
        aligned = (
            row["edge_cids"],
            row["edge_types"],
            row["neighbor_cids"],
            row["neighbor_node_types"],
            row["retrieval_methods"],
            row["scores"],
        )
        neighbor_count = int(row["neighbor_count"])
        if (
            row["direction"] != direction
            or row["schema_version"]
            != CVEFIXES_HF_GRAPH_ADJACENCY_SCHEMA_VERSION
            or node_cid not in node_ids
            or any(len(value) != neighbor_count for value in aligned)
            or neighbor_count > config.adjacency_pointers_per_row
            or int(row["page_count"]) < 1
            or int(row["page_index"]) < 0
            or int(row["page_index"]) >= int(row["page_count"])
            or int(row["total_neighbor_count"]) < neighbor_count
        ):
            raise HuggingFaceGraphLayoutIntegrityError(
                f"{direction} adjacency row is malformed"
            )
        pages_by_node.setdefault(node_cid, []).append(row)
        for offset, edge_cid in enumerate(row["edge_cids"]):
            edge = edge_rows.get(str(edge_cid))
            if edge is None or edge_cid in seen_edges:
                raise HuggingFaceGraphLayoutIntegrityError(
                    f"{direction} adjacency edge coverage differs"
                )
            expected_node = (
                edge["source_cid"]
                if direction == "outgoing"
                else edge["target_cid"]
            )
            expected_neighbor = (
                edge["target_cid"]
                if direction == "outgoing"
                else edge["source_cid"]
            )
            if (
                node_cid != expected_node
                or row["neighbor_cids"][offset] != expected_neighbor
                or row["neighbor_node_types"][offset]
                != node_types[expected_neighbor]
                or row["edge_types"][offset] != edge["edge_type"]
                or row["retrieval_methods"][offset]
                != edge["retrieval_method"]
                or row["scores"][offset] != edge["score"]
            ):
                raise HuggingFaceGraphLayoutIntegrityError(
                    f"{direction} adjacency pointer differs from its edge"
                )
            seen_edges.add(str(edge_cid))
    if set(pages_by_node) != node_ids:
        raise HuggingFaceGraphLayoutIntegrityError(
            f"{direction} adjacency does not cover every graph node"
        )
    if seen_edges != edge_ids:
        raise HuggingFaceGraphLayoutIntegrityError(
            f"{direction} adjacency does not cover every graph edge"
        )
    endpoint_field = (
        "source_cid" if direction == "outgoing" else "target_cid"
    )
    neighbor_field = (
        "target_cid" if direction == "outgoing" else "source_cid"
    )
    expected_edges_by_node: dict[
        str, list[Mapping[str, Any]]
    ] = {node_cid: [] for node_cid in node_ids}
    try:
        for edge in edge_rows.values():
            expected_edges_by_node[str(edge[endpoint_field])].append(edge)
    except KeyError as exc:
        raise HuggingFaceGraphLayoutIntegrityError(
            f"{direction} adjacency edge endpoint is unknown"
        ) from exc
    for expected_edges in expected_edges_by_node.values():
        expected_edges.sort(
            key=lambda edge: (
                edge["score"] is None,
                -(
                    float(edge["score"])
                    if edge["score"] is not None
                    else 0.0
                ),
                edge["edge_type"],
                edge[neighbor_field],
                edge["edge_cid"],
            )
        )
    for node_cid, pages in pages_by_node.items():
        page_count = int(pages[0]["page_count"])
        flattened_edge_ids = [
            str(edge_cid)
            for row in pages
            for edge_cid in row["edge_cids"]
        ]
        expected_edges = expected_edges_by_node[node_cid]
        expected_page_count = max(
            1,
            math.ceil(
                len(expected_edges) / config.adjacency_pointers_per_row
            ),
        )
        if (
            [int(row["page_index"]) for row in pages]
            != list(range(page_count))
            or any(int(row["page_count"]) != page_count for row in pages)
            or page_count != expected_page_count
            or flattened_edge_ids
            != [str(edge["edge_cid"]) for edge in expected_edges]
        ):
            raise HuggingFaceGraphLayoutIntegrityError(
                f"{direction} adjacency page sequence differs"
            )
        pointer_count = sum(int(row["neighbor_count"]) for row in pages)
        if any(
            int(row["total_neighbor_count"]) != pointer_count
            for row in pages
        ):
            raise HuggingFaceGraphLayoutIntegrityError(
                f"{direction} adjacency total differs for {node_cid}"
            )


def validate_cvefixes_hf_graph_layout(
    layout: CVEfixesHuggingFaceGraphLayout,
    *,
    graph: CVEfixesGraph | None = None,
) -> HuggingFaceGraphLayoutValidation:
    """Validate schemas, identities, adjacency, and exact meta coverage."""

    if not isinstance(layout, CVEfixesHuggingFaceGraphLayout):
        raise HuggingFaceGraphLayoutError(
            "layout must be CVEfixesHuggingFaceGraphLayout"
        )
    if graph is not None and not isinstance(graph, CVEfixesGraph):
        raise HuggingFaceGraphLayoutError("graph must be CVEfixesGraph")
    if graph is not None and graph.graph_root != layout.graph_root:
        raise HuggingFaceGraphLayoutIntegrityError(
            "layout graph_root differs from its graph"
        )

    rows_by_config: dict[str, list[dict[str, Any]]] = {}
    data_by_config: dict[
        str, list[tuple[HuggingFaceGraphArtifact, list[dict[str, Any]]]]
    ] = {}
    for artifact in layout.artifacts:
        rows = _validate_artifact_table(artifact, layout.config)
        rows_by_config.setdefault(artifact.config_name, []).extend(rows)
        if artifact.is_data:
            data_by_config.setdefault(artifact.config_name, []).append(
                (artifact, rows)
            )

    for config_name, values in data_by_config.items():
        values.sort(key=lambda item: item[0].path)
        if [_shard_id(item[0]) for item in values] != list(
            range(len(values))
        ):
            raise HuggingFaceGraphLayoutIntegrityError(
                f"{config_name} shard IDs are not contiguous"
            )
        if len(values) > layout.config.max_shards_per_config:
            raise HuggingFaceGraphLayoutLimitError(
                f"{config_name} exceeds max_shards_per_config"
            )

    node_rows = rows_by_config["graph_nodes"]
    edge_rows = rows_by_config["graph_edges"]
    if [row["node_cid"] for row in node_rows] != sorted(
        row["node_cid"] for row in node_rows
    ):
        raise HuggingFaceGraphLayoutIntegrityError(
            "graph node shards are not globally CID ordered"
        )
    if [row["edge_cid"] for row in edge_rows] != sorted(
        row["edge_cid"] for row in edge_rows
    ):
        raise HuggingFaceGraphLayoutIntegrityError(
            "graph edge shards are not globally CID ordered"
        )
    node_types, edge_ids = _validate_canonical_graph_rows(
        node_rows,
        edge_rows,
        entry_cid_by_node=layout.entry_cid_by_node,
    )
    edge_by_cid = {str(row["edge_cid"]): row for row in edge_rows}
    _validate_adjacency_rows(
        rows_by_config["graph_outgoing_adjacency"],
        direction="outgoing",
        node_types=node_types,
        edge_ids=edge_ids,
        edge_rows=edge_by_cid,
        config=layout.config,
    )
    _validate_adjacency_rows(
        rows_by_config["graph_incoming_adjacency"],
        direction="incoming",
        node_types=node_types,
        edge_ids=edge_ids,
        edge_rows=edge_by_cid,
        config=layout.config,
    )

    covered_paths: set[str] = set()
    for data_config, index_path in _DATA_CONFIG_TO_INDEX.items():
        index_artifact = layout.artifact(index_path)
        actual_meta = rows_by_config[index_artifact.config_name]
        expected_meta = [
            _meta_row(artifact, rows)
            for artifact, rows in data_by_config[data_config]
        ]
        if actual_meta != expected_meta:
            raise HuggingFaceGraphLayoutIntegrityError(
                f"meta-index pointer mismatch: {index_path}"
            )
        for row in actual_meta:
            relative_path = str(row["relative_path"])
            if relative_path in covered_paths:
                raise HuggingFaceGraphLayoutIntegrityError(
                    "data shard is indexed more than once"
                )
            covered_paths.add(relative_path)
    if covered_paths != {
        artifact.path for artifact in layout.data_artifacts
    }:
        raise HuggingFaceGraphLayoutIntegrityError(
            "meta indexes do not cover data shards exactly"
        )

    if graph is not None:
        if node_rows != list(
            _node_rows(
                graph,
                entry_cid_by_node=layout.entry_cid_by_node,
            )
        ):
            raise HuggingFaceGraphLayoutIntegrityError(
                "node shards differ from the supplied graph"
            )
        if edge_rows != list(_edge_rows(graph)):
            raise HuggingFaceGraphLayoutIntegrityError(
                "edge shards differ from the supplied graph"
            )
        for direction in ("outgoing", "incoming"):
            config_name = f"graph_{direction}_adjacency"
            if rows_by_config[config_name] != list(
                _adjacency_rows(
                    graph, direction=direction, config=layout.config
                )
            ):
                raise HuggingFaceGraphLayoutIntegrityError(
                    f"{direction} adjacency differs from the supplied graph"
                )

    return HuggingFaceGraphLayoutValidation(
        graph_root=layout.graph_root,
        artifact_count=len(layout.artifacts),
        data_shard_count=len(layout.data_artifacts),
        node_count=len(node_rows),
        edge_count=len(edge_rows),
        outgoing_adjacency_rows=len(
            rows_by_config["graph_outgoing_adjacency"]
        ),
        incoming_adjacency_rows=len(
            rows_by_config["graph_incoming_adjacency"]
        ),
    )


# Descriptive aliases for release integration.
GraphHFLayout = CVEfixesHuggingFaceGraphLayout
GraphHFLayoutArtifact = HuggingFaceGraphArtifact
GraphHFLayoutConfig = HuggingFaceGraphLayoutConfig
build_graph_hf_layout = build_cvefixes_hf_graph_layout
validate_graph_hf_layout = validate_cvefixes_hf_graph_layout


__all__ = [
    "CVEFIXES_HF_GRAPH_ADJACENCY_SCHEMA_VERSION",
    "CVEFIXES_HF_GRAPH_EDGE_SCHEMA_VERSION",
    "CVEFIXES_HF_GRAPH_LAYOUT_SCHEMA_VERSION",
    "CVEFIXES_HF_GRAPH_NODE_SCHEMA_VERSION",
    "CVEFIXES_HF_SHARD_META_SCHEMA_VERSION",
    "CVEfixesHuggingFaceGraphLayout",
    "GRAPH_HF_CONFIG_PATHS",
    "GRAPH_HF_MANIFEST_INDEX_PATHS",
    "GraphHFLayout",
    "GraphHFLayoutArtifact",
    "GraphHFLayoutConfig",
    "HuggingFaceGraphArtifact",
    "HuggingFaceGraphLayoutConfig",
    "HuggingFaceGraphLayoutError",
    "HuggingFaceGraphLayoutIntegrityError",
    "HuggingFaceGraphLayoutLimitError",
    "HuggingFaceGraphLayoutValidation",
    "build_cvefixes_hf_graph_layout",
    "build_graph_hf_layout",
    "validate_cvefixes_hf_graph_layout",
    "validate_graph_hf_layout",
]
