"""Shared graph and bounded adjacency layouts for HF GraphRAG (USCIR-022).

Domain-neutral node/edge sorting, physical sharding, bidirectional adjacency
paging, and key-range routing indexes:

* deterministic node sort by ``node_cid`` and edge sort by stable keys;
* physical shards of at most 4,096 rows (nodes/edges/adjacency pages);
* adjacency pages of at most 4,096 edge pointers, score/priority ordered;
* incoming and outgoing adjacency that fully reconcile every durable edge;
* inclusive key-range locators that are non-overlapping and complete for
  node and edge shards; and
* fail-closed validation for dangling or duplicate durable edges.

Domain builders (US Code, SkillCenter, CVEfixes) wrap these helpers; this
module owns no domain ontology.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Literal, Optional

from .artifacts import (
    ArtifactWriterConfig,
    confine_path,
    describe_file,
    resolve_release_root,
    write_zstd_parquet,
)
from .schema import (
    MAX_ADJACENCY_POINTERS_PER_ROW,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    ArtifactFamily,
    HfGraphragSchemaError,
    PhysicalBoundError,
    canonical_json_dumps,
    content_sha256,
    normalize_relative_artifact_path,
    part_filename,
    physical_bounds_policy,
    validate_physical_pointer_count,
    validate_physical_row_count,
)

# ---------------------------------------------------------------------------
# Module identity / defaults
# ---------------------------------------------------------------------------

GRAPH_LAYOUT_SCHEMA_VERSION: Final = "hf-graphrag-graph-layout/v1"
GRAPH_NODE_SCHEMA_VERSION: Final = "hf-graphrag-graph-node/v1"
GRAPH_EDGE_SCHEMA_VERSION: Final = "hf-graphrag-graph-edge/v1"
GRAPH_ADJACENCY_SCHEMA_VERSION: Final = "hf-graphrag-graph-adjacency/v1"
GRAPH_ROUTING_SCHEMA_VERSION: Final = "hf-graphrag-graph-routing/v1"
GRAPH_FIXTURE_SCHEMA_VERSION: Final = "hf-graphrag-graph-adjacency-fixture/v1"
TASK_ID: Final = "USCIR-022"
GOAL_ID: Final = "USCIR-G060"

# SkillCenter / release policy: 4,096 pointers per page, 8,192 per shard file.
MAX_ADJACENCY_POINTERS_PER_SHARD: Final = 8192
NODES_SORTED_BY: Final = "node_cid_asc"
EDGES_SORTED_BY: Final = "edge_cid_asc"
ADJACENCY_SORTED_BY: Final = (
    "node_cid_asc_score_desc_nulls_last_edge_type_neighbor_edge_cid"
)

GRAPH_NODES_DIR: Final = "data/graph/nodes"
GRAPH_EDGES_DIR: Final = "data/graph/edges"
GRAPH_ADJACENCY_OUT_DIR: Final = "data/graph/adjacency/out"
GRAPH_ADJACENCY_IN_DIR: Final = "data/graph/adjacency/in"
GRAPH_NODE_INDEX_PATH: Final = "indexes/graph_node_chunks.parquet"
GRAPH_EDGE_INDEX_PATH: Final = "indexes/graph_edge_chunks.parquet"
GRAPH_OUT_ADJACENCY_INDEX_PATH: Final = "indexes/graph_out_adjacency.parquet"
GRAPH_IN_ADJACENCY_INDEX_PATH: Final = "indexes/graph_in_adjacency.parquet"

DirectionName = Literal["out", "in"]
_DIRECTION_ALIASES: Final[Mapping[str, DirectionName]] = MappingProxyType(
    {
        "out": "out",
        "outgoing": "out",
        "forward": "out",
        "in": "in",
        "incoming": "in",
        "inverse": "in",
        "reverse": "in",
    }
)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class HfGraphragGraphError(HfGraphragSchemaError):
    """Base error for domain-neutral graph layout failures."""


class GraphInputError(HfGraphragGraphError):
    """Raised when nodes or edges are malformed."""


class GraphIntegrityError(HfGraphragGraphError):
    """Raised when dangling, duplicate, or incomplete durable edges fail."""


class GraphAdjacencyError(HfGraphragGraphError):
    """Raised when forward/inverse adjacency cannot reconcile."""


class GraphRangeError(HfGraphragGraphError):
    """Raised when key ranges overlap, gap, or are incomplete."""


class GraphOrderingError(HfGraphragGraphError):
    """Raised when node/edge/adjacency ordering is not deterministic."""


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GraphInputError(f"{name} must be a non-empty string")
    if "\x00" in value:
        raise GraphInputError(f"{name} must not contain NUL")
    text = value.strip()
    if len(text) > maximum:
        raise GraphInputError(f"{name} exceeds maximum length {maximum}")
    return text


def _optional_str(value: Any, name: str = "value") -> Optional[str]:
    if value is None or value == "":
        return None
    return _require_non_empty_str(value, name)


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GraphInputError(f"{name} must be a non-negative integer")
    return value


def _positive_int(value: Any, name: str) -> int:
    number = _non_negative_int(value, name)
    if number <= 0:
        raise GraphInputError(f"{name} must be a positive integer")
    return number


def _optional_score(value: Any, name: str = "score") -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GraphInputError(f"{name} must be a finite number or null")
    number = float(value)
    if not math.isfinite(number):
        raise GraphInputError(f"{name} must be finite")
    return number


def normalize_direction(value: Any, *, name: str = "direction") -> DirectionName:
    """Normalize direction aliases to ``out`` or ``in``."""

    text = _require_non_empty_str(value, name).lower().replace("-", "_")
    if text not in _DIRECTION_ALIASES:
        raise GraphInputError(
            f"{name} must be out/in/outgoing/incoming, got {value!r}"
        )
    return _DIRECTION_ALIASES[text]


def adjacency_order_key(
    *,
    score: Optional[float],
    edge_type: str,
    neighbor_cid: str,
    edge_cid: str,
) -> tuple[Any, ...]:
    """Stable score/priority order key (null scores last, score descending)."""

    return (
        1 if score is None else 0,
        -(score if score is not None else 0.0),
        edge_type,
        neighbor_cid,
        edge_cid,
    )


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GraphNode:
    """One durable graph node keyed by ``node_cid``."""

    node_cid: str
    node_type: str
    label: Optional[str] = None
    entry_cid: Optional[str] = None
    properties: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "node_cid", _require_non_empty_str(self.node_cid, "node_cid")
        )
        object.__setattr__(
            self,
            "node_type",
            _require_non_empty_str(self.node_type, "node_type", maximum=256),
        )
        if self.label is not None:
            object.__setattr__(self, "label", _optional_str(self.label, "label"))
        if self.entry_cid is not None:
            object.__setattr__(
                self, "entry_cid", _optional_str(self.entry_cid, "entry_cid")
            )
        if not isinstance(self.properties, Mapping):
            raise GraphInputError("properties must be a mapping")
        object.__setattr__(
            self, "properties", MappingProxyType(dict(self.properties))
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "entry_cid": self.entry_cid,
            "label": self.label,
            "node_cid": self.node_cid,
            "node_type": self.node_type,
            "schema_version": GRAPH_NODE_SCHEMA_VERSION,
        }
        if self.properties:
            payload["properties"] = dict(self.properties)
        return payload

    def data_row(self) -> dict[str, Any]:
        """Compact Parquet row (no freeform nested property maps)."""

        return {
            "entry_cid": self.entry_cid,
            "label": self.label,
            "node_cid": self.node_cid,
            "node_type": self.node_type,
            "schema_version": GRAPH_NODE_SCHEMA_VERSION,
        }


@dataclass(frozen=True, slots=True)
class GraphEdge:
    """One durable graph edge keyed by ``edge_cid``."""

    edge_cid: str
    edge_type: str
    source_node_cid: str
    target_node_cid: str
    score: Optional[float] = None
    retrieval_method: str = "structural"
    properties: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "edge_cid", _require_non_empty_str(self.edge_cid, "edge_cid")
        )
        object.__setattr__(
            self,
            "edge_type",
            _require_non_empty_str(self.edge_type, "edge_type", maximum=256),
        )
        object.__setattr__(
            self,
            "source_node_cid",
            _require_non_empty_str(self.source_node_cid, "source_node_cid"),
        )
        object.__setattr__(
            self,
            "target_node_cid",
            _require_non_empty_str(self.target_node_cid, "target_node_cid"),
        )
        object.__setattr__(self, "score", _optional_score(self.score, "score"))
        object.__setattr__(
            self,
            "retrieval_method",
            _require_non_empty_str(
                self.retrieval_method, "retrieval_method", maximum=128
            ),
        )
        if not isinstance(self.properties, Mapping):
            raise GraphInputError("properties must be a mapping")
        object.__setattr__(
            self, "properties", MappingProxyType(dict(self.properties))
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "edge_cid": self.edge_cid,
            "edge_type": self.edge_type,
            "retrieval_method": self.retrieval_method,
            "schema_version": GRAPH_EDGE_SCHEMA_VERSION,
            "score": self.score,
            "source_node_cid": self.source_node_cid,
            "target_node_cid": self.target_node_cid,
        }
        if self.properties:
            payload["properties"] = dict(self.properties)
        return payload

    def data_row(self) -> dict[str, Any]:
        """Compact Parquet row (no freeform nested property maps)."""

        return {
            "edge_cid": self.edge_cid,
            "edge_type": self.edge_type,
            "retrieval_method": self.retrieval_method,
            "schema_version": GRAPH_EDGE_SCHEMA_VERSION,
            "score": self.score,
            "source_node_cid": self.source_node_cid,
            "target_node_cid": self.target_node_cid,
        }

    def order_key_for(self, direction: DirectionName) -> tuple[Any, ...]:
        if direction == "out":
            anchor = self.source_node_cid
            neighbor = self.target_node_cid
        else:
            anchor = self.target_node_cid
            neighbor = self.source_node_cid
        return (
            anchor,
            *adjacency_order_key(
                score=self.score,
                edge_type=self.edge_type,
                neighbor_cid=neighbor,
                edge_cid=self.edge_cid,
            ),
        )


@dataclass(frozen=True, slots=True)
class AdjacencyPage:
    """One bounded adjacency page (≤4,096 edge pointers) for a single node."""

    node_cid: str
    direction: DirectionName
    page_index: int
    page_count: int
    total_neighbor_count: int
    edge_cids: tuple[str, ...]
    edge_types: tuple[str, ...]
    neighbor_cids: tuple[str, ...]
    neighbor_node_types: tuple[str, ...]
    scores: tuple[Optional[float], ...]
    retrieval_methods: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "node_cid", _require_non_empty_str(self.node_cid, "node_cid")
        )
        object.__setattr__(self, "direction", normalize_direction(self.direction))
        object.__setattr__(
            self, "page_index", _non_negative_int(self.page_index, "page_index")
        )
        object.__setattr__(
            self, "page_count", _positive_int(self.page_count, "page_count")
        )
        object.__setattr__(
            self,
            "total_neighbor_count",
            _non_negative_int(self.total_neighbor_count, "total_neighbor_count"),
        )
        count = len(self.edge_cids)
        if not (
            len(self.edge_types)
            == len(self.neighbor_cids)
            == len(self.neighbor_node_types)
            == len(self.scores)
            == len(self.retrieval_methods)
            == count
        ):
            raise GraphAdjacencyError(
                "adjacency page pointer arrays must be aligned"
            )
        validate_physical_pointer_count(
            count,
            name="neighbor_count",
            maximum=MAX_ADJACENCY_POINTERS_PER_ROW,
        )
        if count < 1:
            raise GraphAdjacencyError("adjacency page must contain at least one pointer")
        if self.page_index >= self.page_count:
            raise GraphAdjacencyError(
                f"page_index={self.page_index} exceeds page_count={self.page_count}"
            )

    @property
    def neighbor_count(self) -> int:
        return len(self.edge_cids)

    def to_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "edge_cids": list(self.edge_cids),
            "edge_types": list(self.edge_types),
            "neighbor_cids": list(self.neighbor_cids),
            "neighbor_count": self.neighbor_count,
            "neighbor_node_types": list(self.neighbor_node_types),
            "node_cid": self.node_cid,
            "page_count": self.page_count,
            "page_index": self.page_index,
            "retrieval_methods": list(self.retrieval_methods),
            "schema_version": GRAPH_ADJACENCY_SCHEMA_VERSION,
            "scores": list(self.scores),
            "total_neighbor_count": self.total_neighbor_count,
        }

    def data_row(self) -> dict[str, Any]:
        return self.to_dict()


@dataclass(frozen=True, slots=True)
class KeyRangeShard:
    """One physical shard with an inclusive key range and ordered rows."""

    shard_id: int
    relative_path: str
    first_key: str
    last_key: str
    rows: tuple[Mapping[str, Any], ...]
    kind: str
    pointer_count: int = 0
    first_page_index: int = 0
    last_page_index: int = 0
    node_count: int = 0
    family: ArtifactFamily = ArtifactFamily.GRAPH_NODES

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "shard_id", _non_negative_int(self.shard_id, "shard_id")
        )
        object.__setattr__(
            self,
            "relative_path",
            normalize_relative_artifact_path(self.relative_path),
        )
        object.__setattr__(
            self, "first_key", _require_non_empty_str(self.first_key, "first_key")
        )
        object.__setattr__(
            self, "last_key", _require_non_empty_str(self.last_key, "last_key")
        )
        if self.first_key > self.last_key:
            raise GraphRangeError(
                f"inverted key range [{self.first_key!r}, {self.last_key!r}]"
            )
        if not self.rows:
            raise GraphInputError("shard rows must be non-empty")
        validate_physical_row_count(len(self.rows))
        object.__setattr__(
            self,
            "pointer_count",
            _non_negative_int(self.pointer_count, "pointer_count"),
        )
        object.__setattr__(
            self,
            "first_page_index",
            _non_negative_int(self.first_page_index, "first_page_index"),
        )
        object.__setattr__(
            self,
            "last_page_index",
            _non_negative_int(self.last_page_index, "last_page_index"),
        )
        object.__setattr__(
            self, "node_count", _non_negative_int(self.node_count, "node_count")
        )
        object.__setattr__(self, "family", ArtifactFamily.coerce(self.family))
        object.__setattr__(
            self, "kind", _require_non_empty_str(self.kind, "kind", maximum=128)
        )
        # Freeze row mappings.
        frozen_rows = tuple(
            MappingProxyType(dict(row)) if not isinstance(row, MappingProxyType) else row
            for row in self.rows
        )
        object.__setattr__(self, "rows", frozen_rows)

    @property
    def row_count(self) -> int:
        return len(self.rows)

    def routing_row(
        self,
        *,
        sha256: str = "",
        size_bytes: int = 0,
        content_cid: str | None = None,
        direction: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "first_key": self.first_key,
            "kind": self.kind,
            "last_key": self.last_key,
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "schema_version": GRAPH_ROUTING_SCHEMA_VERSION,
            "sha256": sha256,
            "shard_id": self.shard_id,
            "size_bytes": size_bytes,
        }
        if self.pointer_count:
            payload["adjacency_count"] = self.pointer_count
            payload["first_page_index"] = self.first_page_index
            payload["last_page_index"] = self.last_page_index
            payload["node_count"] = self.node_count
        if direction is not None:
            payload["direction"] = normalize_direction(direction)
        if content_cid is not None:
            payload["content_cid"] = content_cid
            payload["cid"] = content_cid
        return payload

    def to_dict(self) -> dict[str, Any]:
        return {
            "first_key": self.first_key,
            "first_page_index": self.first_page_index,
            "kind": self.kind,
            "last_key": self.last_key,
            "last_page_index": self.last_page_index,
            "node_count": self.node_count,
            "pointer_count": self.pointer_count,
            "relative_path": self.relative_path,
            "row_count": self.row_count,
            "rows": [dict(row) for row in self.rows],
            "shard_id": self.shard_id,
        }


@dataclass(frozen=True, slots=True)
class GraphLayout:
    """Complete deterministic graph layout with bidirectional adjacency."""

    nodes: tuple[GraphNode, ...]
    edges: tuple[GraphEdge, ...]
    node_shards: tuple[KeyRangeShard, ...]
    edge_shards: tuple[KeyRangeShard, ...]
    out_adjacency_pages: tuple[AdjacencyPage, ...]
    in_adjacency_pages: tuple[AdjacencyPage, ...]
    out_adjacency_shards: tuple[KeyRangeShard, ...]
    in_adjacency_shards: tuple[KeyRangeShard, ...]
    max_rows_per_shard: int
    max_pointers_per_page: int
    max_pointers_per_shard: int
    schema_version: str = GRAPH_LAYOUT_SCHEMA_VERSION

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def all_node_cids(self) -> tuple[str, ...]:
        return tuple(node.node_cid for node in self.nodes)

    def all_edge_cids(self) -> tuple[str, ...]:
        return tuple(edge.edge_cid for edge in self.edges)

    def adjacency_pages(self, direction: str) -> tuple[AdjacencyPage, ...]:
        normalized = normalize_direction(direction)
        if normalized == "out":
            return self.out_adjacency_pages
        return self.in_adjacency_pages

    def adjacency_shards(self, direction: str) -> tuple[KeyRangeShard, ...]:
        normalized = normalize_direction(direction)
        if normalized == "out":
            return self.out_adjacency_shards
        return self.in_adjacency_shards

    def routing_rows(
        self,
        *,
        descriptors: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> dict[str, tuple[dict[str, Any], ...]]:
        """Emit ordered compact routing rows for every physical shard family."""

        descriptor_map = descriptors or {}

        def _rows(
            shards: Sequence[KeyRangeShard],
            *,
            direction: str | None = None,
        ) -> tuple[dict[str, Any], ...]:
            rows: list[dict[str, Any]] = []
            for shard in shards:
                extra = descriptor_map.get(shard.relative_path, {})
                rows.append(
                    shard.routing_row(
                        sha256=str(extra.get("sha256", "")),
                        size_bytes=int(extra.get("size_bytes", 0) or 0),
                        content_cid=extra.get("content_cid") or extra.get("cid"),
                        direction=direction,
                    )
                )
            return tuple(rows)

        return {
            "graph_edge_chunks": _rows(self.edge_shards),
            "graph_in_adjacency": _rows(
                self.in_adjacency_shards, direction="in"
            ),
            "graph_node_chunks": _rows(self.node_shards),
            "graph_out_adjacency": _rows(
                self.out_adjacency_shards, direction="out"
            ),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "adjacency_sorted_by": ADJACENCY_SORTED_BY,
            "edge_count": self.edge_count,
            "edge_shards": [shard.to_dict() for shard in self.edge_shards],
            "edges_sorted_by": EDGES_SORTED_BY,
            "in_adjacency_pages": [
                page.to_dict() for page in self.in_adjacency_pages
            ],
            "in_adjacency_shards": [
                shard.to_dict() for shard in self.in_adjacency_shards
            ],
            "max_pointers_per_page": self.max_pointers_per_page,
            "max_pointers_per_shard": self.max_pointers_per_shard,
            "max_rows_per_shard": self.max_rows_per_shard,
            "node_count": self.node_count,
            "node_shards": [shard.to_dict() for shard in self.node_shards],
            "nodes_sorted_by": NODES_SORTED_BY,
            "out_adjacency_pages": [
                page.to_dict() for page in self.out_adjacency_pages
            ],
            "out_adjacency_shards": [
                shard.to_dict() for shard in self.out_adjacency_shards
            ],
            "schema_version": self.schema_version,
        }

    def manifest_config(self) -> dict[str, Any]:
        """Compact layout config for release manifests / receipts."""

        return {
            "adjacency_pointers_per_row": self.max_pointers_per_page,
            "adjacency_pointers_per_shard": self.max_pointers_per_shard,
            "adjacency_sorted_by": ADJACENCY_SORTED_BY,
            "edge_count": self.edge_count,
            "edge_shard_count": len(self.edge_shards),
            "edges_sorted_by": EDGES_SORTED_BY,
            "in_adjacency_edge_count": sum(
                page.neighbor_count for page in self.in_adjacency_pages
            ),
            "in_adjacency_row_count": len(self.in_adjacency_pages),
            "in_adjacency_shard_count": len(self.in_adjacency_shards),
            "layout": "bounded_bidirectional_adjacency",
            "max_rows_per_shard": self.max_rows_per_shard,
            "node_count": self.node_count,
            "node_shard_count": len(self.node_shards),
            "nodes_sorted_by": NODES_SORTED_BY,
            "out_adjacency_edge_count": sum(
                page.neighbor_count for page in self.out_adjacency_pages
            ),
            "out_adjacency_row_count": len(self.out_adjacency_pages),
            "out_adjacency_shard_count": len(self.out_adjacency_shards),
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class GraphLayoutWriteResult:
    """On-disk write outcome for a bounded graph layout."""

    layout: GraphLayout
    data_descriptors: tuple[Any, ...]
    routing_rows: Mapping[str, tuple[dict[str, Any], ...]]
    index_descriptors: Mapping[str, Any]
    output_root: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "data_descriptors": [
                item.to_dict() if hasattr(item, "to_dict") else dict(item)
                for item in self.data_descriptors
            ],
            "index_descriptors": {
                key: (
                    value.to_dict()
                    if value is not None and hasattr(value, "to_dict")
                    else value
                )
                for key, value in self.index_descriptors.items()
            },
            "layout": self.layout.to_dict(),
            "output_root": self.output_root,
            "routing_rows": {
                key: [dict(row) for row in rows]
                for key, rows in self.routing_rows.items()
            },
        }


# ---------------------------------------------------------------------------
# Public configuration helpers
# ---------------------------------------------------------------------------


def graph_bounds_policy() -> dict[str, int]:
    """Return sealed graph physical bounds (subset of shared policy)."""

    bounds = physical_bounds_policy()
    return {
        "max_adjacency_pointers_per_row": bounds[
            "max_adjacency_pointers_per_row"
        ],
        "max_adjacency_pointers_per_shard": MAX_ADJACENCY_POINTERS_PER_SHARD,
        "max_rows_per_physical_shard": bounds["max_rows_per_physical_shard"],
    }


def graph_part_relative_path(
    directory: str,
    shard_id: int,
    *,
    width: int = 6,
) -> str:
    """Release-relative ``data/.../part-NNNNNN.parquet`` path."""

    base = normalize_relative_artifact_path(directory)
    return f"{base}/{part_filename(shard_id, width=width)}"


# ---------------------------------------------------------------------------
# Input coercion
# ---------------------------------------------------------------------------


def coerce_graph_nodes(
    rows: Sequence[Mapping[str, Any] | GraphNode],
) -> tuple[GraphNode, ...]:
    """Coerce mappings / records into validated :class:`GraphNode` values."""

    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise GraphInputError("nodes must be a sequence")
    nodes: list[GraphNode] = []
    for position, row in enumerate(rows):
        if isinstance(row, GraphNode):
            nodes.append(row)
            continue
        if not isinstance(row, Mapping):
            raise GraphInputError(f"nodes[{position}] must be a mapping")
        properties = row.get("properties") or row.get("payload") or {}
        if not isinstance(properties, Mapping):
            raise GraphInputError(f"nodes[{position}].properties must be a mapping")
        nodes.append(
            GraphNode(
                node_cid=str(
                    row.get("node_cid") or row.get("cid") or row.get("id") or ""
                ),
                node_type=str(row.get("node_type") or row.get("type") or ""),
                label=row.get("label"),
                entry_cid=row.get("entry_cid"),
                properties=dict(properties),
            )
        )
    return tuple(nodes)


def coerce_graph_edges(
    rows: Sequence[Mapping[str, Any] | GraphEdge],
) -> tuple[GraphEdge, ...]:
    """Coerce mappings / records into validated :class:`GraphEdge` values."""

    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise GraphInputError("edges must be a sequence")
    edges: list[GraphEdge] = []
    for position, row in enumerate(rows):
        if isinstance(row, GraphEdge):
            edges.append(row)
            continue
        if not isinstance(row, Mapping):
            raise GraphInputError(f"edges[{position}] must be a mapping")
        properties = row.get("properties") or row.get("payload") or {}
        if not isinstance(properties, Mapping):
            raise GraphInputError(f"edges[{position}].properties must be a mapping")
        score = row.get("score", row.get("weight"))
        edges.append(
            GraphEdge(
                edge_cid=str(
                    row.get("edge_cid") or row.get("cid") or row.get("id") or ""
                ),
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
                score=score,
                retrieval_method=str(
                    row.get("retrieval_method") or "structural"
                ),
                properties=dict(properties),
            )
        )
    return tuple(edges)


def _validate_and_sort_nodes(
    nodes: Sequence[GraphNode],
) -> tuple[GraphNode, ...]:
    if not nodes:
        raise GraphInputError("graph requires at least one node")
    seen: set[str] = set()
    for node in nodes:
        if node.node_cid in seen:
            raise GraphIntegrityError(
                f"duplicate durable node_cid: {node.node_cid!r}"
            )
        seen.add(node.node_cid)
    return tuple(sorted(nodes, key=lambda item: item.node_cid))


def _validate_and_sort_edges(
    edges: Sequence[GraphEdge],
    *,
    node_cids: set[str],
) -> tuple[GraphEdge, ...]:
    seen: set[str] = set()
    for edge in edges:
        if edge.edge_cid in seen:
            raise GraphIntegrityError(
                f"duplicate durable edge_cid: {edge.edge_cid!r}"
            )
        seen.add(edge.edge_cid)
        if edge.source_node_cid not in node_cids:
            raise GraphIntegrityError(
                f"dangling edge {edge.edge_cid!r}: missing source "
                f"{edge.source_node_cid!r}"
            )
        if edge.target_node_cid not in node_cids:
            raise GraphIntegrityError(
                f"dangling edge {edge.edge_cid!r}: missing target "
                f"{edge.target_node_cid!r}"
            )
    return tuple(sorted(edges, key=lambda item: item.edge_cid))


# ---------------------------------------------------------------------------
# Adjacency paging
# ---------------------------------------------------------------------------


def _edge_pointer_tuple(
    edge: GraphEdge,
    *,
    direction: DirectionName,
    node_types: Mapping[str, str],
) -> tuple[str, str, str, str, Optional[float], str]:
    if direction == "out":
        neighbor = edge.target_node_cid
    else:
        neighbor = edge.source_node_cid
    return (
        edge.edge_cid,
        edge.edge_type,
        neighbor,
        node_types[neighbor],
        edge.score,
        edge.retrieval_method,
    )


def build_adjacency_pages(
    edges: Sequence[GraphEdge],
    *,
    direction: str,
    node_types: Mapping[str, str],
    max_pointers_per_page: int = MAX_ADJACENCY_POINTERS_PER_ROW,
) -> tuple[AdjacencyPage, ...]:
    """Page score-ordered adjacency for one direction."""

    normalized = normalize_direction(direction)
    max_pointers_per_page = _positive_int(
        max_pointers_per_page, "max_pointers_per_page"
    )
    if max_pointers_per_page > MAX_ADJACENCY_POINTERS_PER_ROW:
        raise PhysicalBoundError(
            f"max_pointers_per_page={max_pointers_per_page} exceeds "
            f"{MAX_ADJACENCY_POINTERS_PER_ROW}"
        )
    if not edges:
        return ()

    grouped: dict[str, list[GraphEdge]] = defaultdict(list)
    for edge in edges:
        if normalized == "out":
            grouped[edge.source_node_cid].append(edge)
        else:
            grouped[edge.target_node_cid].append(edge)

    pages: list[AdjacencyPage] = []
    for node_cid in sorted(grouped):
        ordered = sorted(
            grouped[node_cid],
            key=lambda edge: edge.order_key_for(normalized),
        )
        total = len(ordered)
        page_count = max(1, math.ceil(total / max_pointers_per_page))
        for page_index, start in enumerate(
            range(0, total, max_pointers_per_page)
        ):
            selected = ordered[start : start + max_pointers_per_page]
            pointers = [
                _edge_pointer_tuple(
                    edge, direction=normalized, node_types=node_types
                )
                for edge in selected
            ]
            pages.append(
                AdjacencyPage(
                    node_cid=node_cid,
                    direction=normalized,
                    page_index=page_index,
                    page_count=page_count,
                    total_neighbor_count=total,
                    edge_cids=tuple(item[0] for item in pointers),
                    edge_types=tuple(item[1] for item in pointers),
                    neighbor_cids=tuple(item[2] for item in pointers),
                    neighbor_node_types=tuple(item[3] for item in pointers),
                    scores=tuple(item[4] for item in pointers),
                    retrieval_methods=tuple(item[5] for item in pointers),
                )
            )
    return tuple(pages)


def _shard_records(
    rows: Sequence[Mapping[str, Any]],
    *,
    key_field: str,
    directory: str,
    kind: str,
    family: ArtifactFamily,
    max_rows_per_shard: int,
) -> tuple[KeyRangeShard, ...]:
    if not rows:
        return ()
    shards: list[KeyRangeShard] = []
    for shard_id, start in enumerate(range(0, len(rows), max_rows_per_shard)):
        group = tuple(rows[start : start + max_rows_per_shard])
        validate_physical_row_count(len(group), maximum=max_rows_per_shard)
        first_key = str(group[0][key_field])
        last_key = str(group[-1][key_field])
        shards.append(
            KeyRangeShard(
                shard_id=shard_id,
                relative_path=graph_part_relative_path(directory, shard_id),
                first_key=first_key,
                last_key=last_key,
                rows=group,
                kind=kind,
                family=family,
            )
        )
    return tuple(shards)


def _shard_adjacency_pages(
    pages: Sequence[AdjacencyPage],
    *,
    direction: DirectionName,
    directory: str,
    max_rows_per_shard: int,
    max_pointers_per_shard: int,
) -> tuple[KeyRangeShard, ...]:
    if not pages:
        return ()
    family = (
        ArtifactFamily.GRAPH_ADJACENCY_OUT
        if direction == "out"
        else ArtifactFamily.GRAPH_ADJACENCY_IN
    )
    kind = f"graph_{direction}_adjacency"
    shards: list[KeyRangeShard] = []
    pending: list[dict[str, Any]] = []
    pending_pointers = 0
    shard_id = 0

    def flush() -> None:
        nonlocal pending, pending_pointers, shard_id
        if not pending:
            return
        first_key = str(pending[0]["node_cid"])
        last_key = str(pending[-1]["node_cid"])
        node_ids = {str(row["node_cid"]) for row in pending}
        shards.append(
            KeyRangeShard(
                shard_id=shard_id,
                relative_path=graph_part_relative_path(directory, shard_id),
                first_key=first_key,
                last_key=last_key,
                rows=tuple(pending),
                kind=kind,
                family=family,
                pointer_count=pending_pointers,
                first_page_index=int(pending[0]["page_index"]),
                last_page_index=int(pending[-1]["page_index"]),
                node_count=len(node_ids),
            )
        )
        shard_id += 1
        pending = []
        pending_pointers = 0

    for page in pages:
        row = page.data_row()
        pointers = page.neighbor_count
        if pending and (
            len(pending) >= max_rows_per_shard
            or pending_pointers + pointers > max_pointers_per_shard
        ):
            flush()
        pending.append(row)
        pending_pointers += pointers
    flush()
    return tuple(shards)


# ---------------------------------------------------------------------------
# Layout construction / validation
# ---------------------------------------------------------------------------


def build_graph_layout(
    nodes: Sequence[Mapping[str, Any] | GraphNode],
    edges: Sequence[Mapping[str, Any] | GraphEdge] = (),
    *,
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    max_pointers_per_page: int = MAX_ADJACENCY_POINTERS_PER_ROW,
    max_pointers_per_shard: int = MAX_ADJACENCY_POINTERS_PER_SHARD,
    nodes_dir: str = GRAPH_NODES_DIR,
    edges_dir: str = GRAPH_EDGES_DIR,
    out_adjacency_dir: str = GRAPH_ADJACENCY_OUT_DIR,
    in_adjacency_dir: str = GRAPH_ADJACENCY_IN_DIR,
) -> GraphLayout:
    """Build a deterministic bounded graph layout with bidirectional adjacency.

    Guarantees:

    * nodes sorted by ``node_cid``; edges sorted by ``edge_cid``;
    * no duplicate durable ``node_cid`` / ``edge_cid`` values;
    * every edge endpoint exists (no dangling edges);
    * adjacency pages have ``<= max_pointers_per_page`` pointers and are
      score/priority ordered;
    * forward and inverse adjacency fully reconcile every edge;
    * node and edge key ranges are non-overlapping and complete.
    """

    max_rows_per_shard = _positive_int(max_rows_per_shard, "max_rows_per_shard")
    max_pointers_per_page = _positive_int(
        max_pointers_per_page, "max_pointers_per_page"
    )
    max_pointers_per_shard = _positive_int(
        max_pointers_per_shard, "max_pointers_per_shard"
    )
    if max_rows_per_shard > MAX_ROWS_PER_PHYSICAL_SHARD:
        raise PhysicalBoundError(
            f"max_rows_per_shard={max_rows_per_shard} exceeds "
            f"{MAX_ROWS_PER_PHYSICAL_SHARD}"
        )
    if max_pointers_per_page > MAX_ADJACENCY_POINTERS_PER_ROW:
        raise PhysicalBoundError(
            f"max_pointers_per_page={max_pointers_per_page} exceeds "
            f"{MAX_ADJACENCY_POINTERS_PER_ROW}"
        )
    if max_pointers_per_shard < max_pointers_per_page:
        raise PhysicalBoundError(
            "max_pointers_per_shard must be >= max_pointers_per_page"
        )

    ordered_nodes = _validate_and_sort_nodes(coerce_graph_nodes(nodes))
    node_cids = {node.node_cid for node in ordered_nodes}
    node_types = {node.node_cid: node.node_type for node in ordered_nodes}
    ordered_edges = _validate_and_sort_edges(
        coerce_graph_edges(edges),
        node_cids=node_cids,
    )

    node_rows = tuple(node.data_row() for node in ordered_nodes)
    edge_rows = tuple(edge.data_row() for edge in ordered_edges)
    node_shards = _shard_records(
        node_rows,
        key_field="node_cid",
        directory=nodes_dir,
        kind="graph_nodes",
        family=ArtifactFamily.GRAPH_NODES,
        max_rows_per_shard=max_rows_per_shard,
    )
    edge_shards = _shard_records(
        edge_rows,
        key_field="edge_cid",
        directory=edges_dir,
        kind="graph_edges",
        family=ArtifactFamily.GRAPH_EDGES,
        max_rows_per_shard=max_rows_per_shard,
    )

    out_pages = build_adjacency_pages(
        ordered_edges,
        direction="out",
        node_types=node_types,
        max_pointers_per_page=max_pointers_per_page,
    )
    in_pages = build_adjacency_pages(
        ordered_edges,
        direction="in",
        node_types=node_types,
        max_pointers_per_page=max_pointers_per_page,
    )
    out_shards = _shard_adjacency_pages(
        out_pages,
        direction="out",
        directory=out_adjacency_dir,
        max_rows_per_shard=max_rows_per_shard,
        max_pointers_per_shard=max_pointers_per_shard,
    )
    in_shards = _shard_adjacency_pages(
        in_pages,
        direction="in",
        directory=in_adjacency_dir,
        max_rows_per_shard=max_rows_per_shard,
        max_pointers_per_shard=max_pointers_per_shard,
    )

    layout = GraphLayout(
        nodes=ordered_nodes,
        edges=ordered_edges,
        node_shards=node_shards,
        edge_shards=edge_shards,
        out_adjacency_pages=out_pages,
        in_adjacency_pages=in_pages,
        out_adjacency_shards=out_shards,
        in_adjacency_shards=in_shards,
        max_rows_per_shard=max_rows_per_shard,
        max_pointers_per_page=max_pointers_per_page,
        max_pointers_per_shard=max_pointers_per_shard,
    )
    validate_graph_layout(layout)
    return layout


def _row_primary_key(row: Mapping[str, Any], *, label: str) -> str:
    if label == "node":
        return str(row.get("node_cid") or "")
    if label == "edge":
        return str(row.get("edge_cid") or "")
    return str(row.get("node_cid") or row.get("edge_cid") or "")


def _validate_strict_key_ranges(
    shards: Sequence[KeyRangeShard],
    *,
    expected_keys: Sequence[str],
    label: str,
) -> None:
    if not expected_keys:
        if shards:
            raise GraphRangeError(f"{label} shards present without keys")
        return
    if not shards:
        raise GraphRangeError(f"{label} shards missing for non-empty key set")
    covered: list[str] = []
    previous: KeyRangeShard | None = None
    for shard in shards:
        if previous is not None:
            if previous.last_key >= shard.first_key:
                raise GraphRangeError(
                    f"{label} key ranges overlap or are unordered: "
                    f"[{previous.first_key!r}, {previous.last_key!r}] vs "
                    f"[{shard.first_key!r}, {shard.last_key!r}]"
                )
            if previous.shard_id >= shard.shard_id:
                raise GraphRangeError(
                    f"{label} shard_id must strictly increase"
                )
        first_row_key = _row_primary_key(shard.rows[0], label=label)
        last_row_key = _row_primary_key(shard.rows[-1], label=label)
        if first_row_key != shard.first_key:
            raise GraphRangeError(
                f"{label} shard first_key differs from first row"
            )
        if last_row_key != shard.last_key:
            raise GraphRangeError(
                f"{label} shard last_key differs from last row"
            )
        for row in shard.rows:
            covered.append(_row_primary_key(row, label=label))
        previous = shard
    if covered != list(expected_keys):
        raise GraphRangeError(
            f"{label} key coverage is incomplete or reordered"
        )


def _validate_adjacency_key_ranges(
    shards: Sequence[KeyRangeShard],
    pages: Sequence[AdjacencyPage],
    *,
    label: str,
    max_pointers_per_shard: int,
) -> None:
    if not pages:
        if shards:
            raise GraphRangeError(f"{label} shards present without pages")
        return
    if not shards:
        raise GraphRangeError(f"{label} shards missing for non-empty pages")
    covered_rows = 0
    covered_pointers = 0
    previous: KeyRangeShard | None = None
    for shard in shards:
        if shard.pointer_count > max_pointers_per_shard:
            raise PhysicalBoundError(
                f"{label} shard exceeds max_pointers_per_shard"
            )
        if previous is not None:
            # Non-overlapping except equality when a high-degree node spans
            # consecutive shards (same node_cid continues).
            if previous.last_key > shard.first_key:
                raise GraphRangeError(
                    f"{label} adjacency key ranges are unordered/overlapping: "
                    f"[{previous.last_key!r}] > [{shard.first_key!r}]"
                )
            if previous.shard_id >= shard.shard_id:
                raise GraphRangeError(
                    f"{label} adjacency shard_id must strictly increase"
                )
        if str(shard.rows[0]["node_cid"]) != shard.first_key:
            raise GraphRangeError(
                f"{label} adjacency first_key differs from first row"
            )
        if str(shard.rows[-1]["node_cid"]) != shard.last_key:
            raise GraphRangeError(
                f"{label} adjacency last_key differs from last row"
            )
        pointer_sum = sum(int(row["neighbor_count"]) for row in shard.rows)
        if pointer_sum != shard.pointer_count:
            raise GraphAdjacencyError(
                f"{label} adjacency pointer_count metadata differs"
            )
        covered_rows += shard.row_count
        covered_pointers += shard.pointer_count
        previous = shard
    if covered_rows != len(pages):
        raise GraphAdjacencyError(
            f"{label} adjacency page coverage differs"
        )
    expected_pointers = sum(page.neighbor_count for page in pages)
    if covered_pointers != expected_pointers:
        raise GraphAdjacencyError(
            f"{label} adjacency pointer coverage differs"
        )


def _validate_adjacency_pages(
    pages: Sequence[AdjacencyPage],
    *,
    direction: DirectionName,
    max_pointers_per_page: int,
    expected_edge_cids: set[str],
) -> set[str]:
    seen_edges: set[str] = set()
    previous_node = ""
    previous_page = -1
    expected_pages = 0
    expected_neighbors = 0
    seen_neighbors = 0
    previous_order: tuple[Any, ...] | None = None

    for page in pages:
        if page.direction != direction:
            raise GraphAdjacencyError(
                f"adjacency direction {page.direction!r} differs from {direction!r}"
            )
        if page.neighbor_count > max_pointers_per_page:
            raise PhysicalBoundError(
                f"adjacency page exceeds {max_pointers_per_page} pointers"
            )
        if page.node_cid < previous_node:
            raise GraphOrderingError(
                "adjacency pages are not sorted by node_cid"
            )
        if page.node_cid != previous_node:
            if previous_node and (
                previous_page + 1 != expected_pages
                or seen_neighbors != expected_neighbors
            ):
                raise GraphAdjacencyError(
                    f"adjacency pages incomplete for node {previous_node!r}"
                )
            if page.page_index != 0 or page.page_count < 1:
                raise GraphAdjacencyError(
                    f"adjacency pages for {page.node_cid!r} do not start at zero"
                )
            previous_node = page.node_cid
            previous_page = -1
            expected_pages = page.page_count
            expected_neighbors = page.total_neighbor_count
            seen_neighbors = 0
            previous_order = None
        if (
            page.page_index != previous_page + 1
            or page.page_count != expected_pages
            or page.total_neighbor_count != expected_neighbors
        ):
            raise GraphAdjacencyError(
                f"adjacency page sequence differs for {page.node_cid!r}"
            )
        for offset in range(page.neighbor_count):
            edge_cid = page.edge_cids[offset]
            if edge_cid in seen_edges:
                raise GraphIntegrityError(
                    f"duplicate edge in {direction} adjacency: {edge_cid!r}"
                )
            if edge_cid not in expected_edge_cids:
                raise GraphIntegrityError(
                    f"unknown edge in {direction} adjacency: {edge_cid!r}"
                )
            order = adjacency_order_key(
                score=page.scores[offset],
                edge_type=page.edge_types[offset],
                neighbor_cid=page.neighbor_cids[offset],
                edge_cid=edge_cid,
            )
            if previous_order is not None and order < previous_order:
                raise GraphOrderingError(
                    f"{direction} adjacency is not score/priority ordered "
                    f"for node {page.node_cid!r}"
                )
            previous_order = order
            seen_edges.add(edge_cid)
        previous_page = page.page_index
        seen_neighbors += page.neighbor_count

    if previous_node and (
        previous_page + 1 != expected_pages
        or seen_neighbors != expected_neighbors
    ):
        raise GraphAdjacencyError(
            f"adjacency pages incomplete for node {previous_node!r}"
        )
    return seen_edges


def reconcile_forward_inverse_adjacency(layout: GraphLayout) -> None:
    """Fail closed unless every durable edge appears once in each direction."""

    expected = set(layout.all_edge_cids())
    out_edges = _validate_adjacency_pages(
        layout.out_adjacency_pages,
        direction="out",
        max_pointers_per_page=layout.max_pointers_per_page,
        expected_edge_cids=expected,
    )
    in_edges = _validate_adjacency_pages(
        layout.in_adjacency_pages,
        direction="in",
        max_pointers_per_page=layout.max_pointers_per_page,
        expected_edge_cids=expected,
    )
    if out_edges != expected:
        missing = sorted(expected - out_edges)
        extra = sorted(out_edges - expected)
        raise GraphAdjacencyError(
            f"outgoing adjacency does not reconcile edges "
            f"(missing={missing[:5]!r}, extra={extra[:5]!r})"
        )
    if in_edges != expected:
        missing = sorted(expected - in_edges)
        extra = sorted(in_edges - expected)
        raise GraphAdjacencyError(
            f"incoming adjacency does not reconcile edges "
            f"(missing={missing[:5]!r}, extra={extra[:5]!r})"
        )
    if out_edges != in_edges:
        raise GraphAdjacencyError(
            "incoming and outgoing adjacency edge coverage differs"
        )

    # Per-edge endpoint consistency: each edge appears under the correct anchor.
    out_by_edge: dict[str, tuple[str, str]] = {}
    for page in layout.out_adjacency_pages:
        for offset, edge_cid in enumerate(page.edge_cids):
            out_by_edge[edge_cid] = (page.node_cid, page.neighbor_cids[offset])
    in_by_edge: dict[str, tuple[str, str]] = {}
    for page in layout.in_adjacency_pages:
        for offset, edge_cid in enumerate(page.edge_cids):
            in_by_edge[edge_cid] = (page.node_cid, page.neighbor_cids[offset])
    for edge in layout.edges:
        source, target = out_by_edge[edge.edge_cid]
        if source != edge.source_node_cid or target != edge.target_node_cid:
            raise GraphAdjacencyError(
                f"outgoing adjacency endpoints differ for {edge.edge_cid!r}"
            )
        target_anchor, source_neighbor = in_by_edge[edge.edge_cid]
        if (
            target_anchor != edge.target_node_cid
            or source_neighbor != edge.source_node_cid
        ):
            raise GraphAdjacencyError(
                f"incoming adjacency endpoints differ for {edge.edge_cid!r}"
            )


def validate_graph_layout(layout: GraphLayout) -> None:
    """Fail closed if bounds, ranges, ordering, or reconciliation break."""

    if not isinstance(layout, GraphLayout):
        raise GraphIntegrityError("layout must be a GraphLayout")

    # Node uniqueness / sort.
    node_cids = layout.all_node_cids()
    if len(node_cids) != len(set(node_cids)):
        raise GraphIntegrityError("layout contains duplicate node_cids")
    if list(node_cids) != sorted(node_cids):
        raise GraphOrderingError("nodes are not sorted by node_cid")

    # Edge uniqueness / sort / endpoints.
    edge_cids = layout.all_edge_cids()
    if len(edge_cids) != len(set(edge_cids)):
        raise GraphIntegrityError("layout contains duplicate edge_cids")
    if list(edge_cids) != sorted(edge_cids):
        raise GraphOrderingError("edges are not sorted by edge_cid")
    node_set = set(node_cids)
    for edge in layout.edges:
        if edge.source_node_cid not in node_set:
            raise GraphIntegrityError(
                f"dangling edge source: {edge.source_node_cid!r}"
            )
        if edge.target_node_cid not in node_set:
            raise GraphIntegrityError(
                f"dangling edge target: {edge.target_node_cid!r}"
            )

    # Physical shard row bounds.
    for shard in (
        *layout.node_shards,
        *layout.edge_shards,
        *layout.out_adjacency_shards,
        *layout.in_adjacency_shards,
    ):
        if shard.row_count > layout.max_rows_per_shard:
            raise PhysicalBoundError(
                f"shard {shard.relative_path} exceeds max_rows_per_shard"
            )

    _validate_strict_key_ranges(
        layout.node_shards,
        expected_keys=node_cids,
        label="node",
    )
    _validate_strict_key_ranges(
        layout.edge_shards,
        expected_keys=edge_cids,
        label="edge",
    )
    _validate_adjacency_key_ranges(
        layout.out_adjacency_shards,
        layout.out_adjacency_pages,
        label="out",
        max_pointers_per_shard=layout.max_pointers_per_shard,
    )
    _validate_adjacency_key_ranges(
        layout.in_adjacency_shards,
        layout.in_adjacency_pages,
        label="in",
        max_pointers_per_shard=layout.max_pointers_per_shard,
    )
    reconcile_forward_inverse_adjacency(layout)


# ---------------------------------------------------------------------------
# Optional Parquet writers
# ---------------------------------------------------------------------------


def write_graph_layout(
    nodes: Sequence[Mapping[str, Any] | GraphNode],
    edges: Sequence[Mapping[str, Any] | GraphEdge] = (),
    output_root: str | Path = ".",
    *,
    max_rows_per_shard: int = MAX_ROWS_PER_PHYSICAL_SHARD,
    max_pointers_per_page: int = MAX_ADJACENCY_POINTERS_PER_ROW,
    max_pointers_per_shard: int = MAX_ADJACENCY_POINTERS_PER_SHARD,
    write_indexes: bool = True,
) -> GraphLayoutWriteResult:
    """Build the layout and write ZSTD Parquet shards + optional routing indexes."""

    layout = build_graph_layout(
        nodes,
        edges,
        max_rows_per_shard=max_rows_per_shard,
        max_pointers_per_page=max_pointers_per_page,
        max_pointers_per_shard=max_pointers_per_shard,
    )
    root = resolve_release_root(output_root, must_exist=False)
    root.mkdir(parents=True, exist_ok=True)
    config = ArtifactWriterConfig(max_rows_per_shard=layout.max_rows_per_shard)

    descriptors: list[Any] = []
    descriptor_map: dict[str, dict[str, Any]] = {}

    def _write_shards(shards: Sequence[KeyRangeShard]) -> None:
        for shard in shards:
            path = confine_path(root, shard.relative_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            write_zstd_parquet(
                path,
                [dict(row) for row in shard.rows],
                max_rows=layout.max_rows_per_shard,
                config=config,
            )
            descriptor = describe_file(
                path,
                root=root,
                row_count=shard.row_count,
                family=shard.family,
                schema_id=(
                    GRAPH_ADJACENCY_SCHEMA_VERSION
                    if "adjacency" in shard.kind
                    else (
                        GRAPH_NODE_SCHEMA_VERSION
                        if shard.kind == "graph_nodes"
                        else GRAPH_EDGE_SCHEMA_VERSION
                    )
                ),
                first_key=shard.first_key,
                last_key=shard.last_key,
                shard_id=shard.shard_id,
                metadata={
                    "kind": shard.kind,
                    "pointer_count": shard.pointer_count,
                },
            )
            descriptors.append(descriptor)
            descriptor_map[shard.relative_path] = descriptor.to_dict()

    _write_shards(layout.node_shards)
    _write_shards(layout.edge_shards)
    _write_shards(layout.out_adjacency_shards)
    _write_shards(layout.in_adjacency_shards)

    routing = layout.routing_rows(descriptors=descriptor_map)
    index_descriptors: dict[str, Any] = {}
    if write_indexes:
        index_targets = {
            "graph_node_chunks": (
                GRAPH_NODE_INDEX_PATH,
                routing["graph_node_chunks"],
                ArtifactFamily.ROUTING_INDEX,
            ),
            "graph_edge_chunks": (
                GRAPH_EDGE_INDEX_PATH,
                routing["graph_edge_chunks"],
                ArtifactFamily.ROUTING_INDEX,
            ),
            "graph_out_adjacency": (
                GRAPH_OUT_ADJACENCY_INDEX_PATH,
                routing["graph_out_adjacency"],
                ArtifactFamily.ROUTING_INDEX,
            ),
            "graph_in_adjacency": (
                GRAPH_IN_ADJACENCY_INDEX_PATH,
                routing["graph_in_adjacency"],
                ArtifactFamily.ROUTING_INDEX,
            ),
        }
        for name, (relative, rows, family) in index_targets.items():
            if not rows:
                index_descriptors[name] = None
                continue
            relative_path = normalize_relative_artifact_path(relative)
            path = confine_path(root, relative_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            write_zstd_parquet(
                path,
                list(rows),
                max_rows=MAX_ROWS_PER_PHYSICAL_SHARD,
                config=ArtifactWriterConfig(
                    max_rows_per_shard=MAX_ROWS_PER_PHYSICAL_SHARD
                ),
            )
            index_descriptors[name] = describe_file(
                path,
                root=root,
                row_count=len(rows),
                family=family,
                schema_id=GRAPH_ROUTING_SCHEMA_VERSION,
            )

    return GraphLayoutWriteResult(
        layout=layout,
        data_descriptors=tuple(descriptors),
        routing_rows=routing,
        index_descriptors=MappingProxyType(index_descriptors),
        output_root=str(root),
    )


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def build_fixture_graph_rows(
    recipe: Mapping[str, Any],
) -> tuple[tuple[dict[str, Any], ...], tuple[dict[str, Any], ...]]:
    """Materialize a compact fixture recipe into node/edge input mappings."""

    if not isinstance(recipe, Mapping):
        raise GraphInputError("fixture recipe must be a mapping")
    nodes_spec = recipe.get("nodes")
    edges_spec = recipe.get("edges")
    if not isinstance(nodes_spec, Sequence):
        raise GraphInputError("fixture recipe.nodes must be a sequence")
    if edges_spec is None:
        edges_spec = ()
    if not isinstance(edges_spec, Sequence):
        raise GraphInputError("fixture recipe.edges must be a sequence")

    nodes: list[dict[str, Any]] = []
    for position, item in enumerate(nodes_spec):
        if not isinstance(item, Mapping):
            raise GraphInputError(f"fixture nodes[{position}] must be a mapping")
        node_cid = str(item.get("node_cid") or f"node-{position:04d}")
        nodes.append(
            {
                "entry_cid": item.get("entry_cid"),
                "label": item.get("label") or node_cid,
                "node_cid": node_cid,
                "node_type": str(item.get("node_type") or "NODE"),
                "properties": dict(item.get("properties") or {}),
            }
        )

    edges: list[dict[str, Any]] = []
    for position, item in enumerate(edges_spec):
        if not isinstance(item, Mapping):
            raise GraphInputError(f"fixture edges[{position}] must be a mapping")
        edge_cid = str(item.get("edge_cid") or f"edge-{position:04d}")
        edges.append(
            {
                "edge_cid": edge_cid,
                "edge_type": str(item.get("edge_type") or "RELATED_TO"),
                "retrieval_method": str(
                    item.get("retrieval_method") or "structural"
                ),
                "score": item.get("score", item.get("weight")),
                "source_node_cid": str(
                    item.get("source_node_cid")
                    or item.get("source_cid")
                    or item.get("source")
                    or ""
                ),
                "target_node_cid": str(
                    item.get("target_node_cid")
                    or item.get("target_cid")
                    or item.get("target")
                    or ""
                ),
                "properties": dict(item.get("properties") or {}),
            }
        )
    return tuple(nodes), tuple(edges)


def build_graph_adjacency_fixture_payload(
    *,
    include_realized_layout: bool = True,
) -> dict[str, Any]:
    """Build the sealed unit-test fixture payload (compact recipes).

    The on-disk fixture stores the recipe and sealed bounds. Structural
    expectations are derived deterministically at test time so bulk golden
    adjacency dumps are unnecessary.
    """

    # Compact diamond plus one multi-page high-degree node exercised via
    # test-time bounds (max_pointers_per_page=2).
    recipe = {
        "edges": [
            {
                "edge_cid": "edge-a-b",
                "edge_type": "CONTAINS",
                "score": 0.9,
                "source_node_cid": "node-a",
                "target_node_cid": "node-b",
            },
            {
                "edge_cid": "edge-a-c",
                "edge_type": "CONTAINS",
                "score": 0.8,
                "source_node_cid": "node-a",
                "target_node_cid": "node-c",
            },
            {
                "edge_cid": "edge-a-d",
                "edge_type": "CITES",
                "score": 0.7,
                "source_node_cid": "node-a",
                "target_node_cid": "node-d",
            },
            {
                "edge_cid": "edge-b-c",
                "edge_type": "CITES",
                "score": 0.5,
                "source_node_cid": "node-b",
                "target_node_cid": "node-c",
            },
            {
                "edge_cid": "edge-c-d",
                "edge_type": "RELATED_TO",
                "score": None,
                "source_node_cid": "node-c",
                "target_node_cid": "node-d",
            },
            {
                "edge_cid": "edge-d-a",
                "edge_type": "DERIVED_FROM",
                "score": 0.1,
                "source_node_cid": "node-d",
                "target_node_cid": "node-a",
            },
        ],
        "nodes": [
            {"label": "A", "node_cid": "node-a", "node_type": "SECTION"},
            {"label": "B", "node_cid": "node-b", "node_type": "SECTION"},
            {"label": "C", "node_cid": "node-c", "node_type": "SECTION"},
            {"label": "D", "node_cid": "node-d", "node_type": "NOTE"},
            {"label": "E", "node_cid": "node-e", "node_type": "SECTION"},
        ],
    }
    test_bounds = {
        "max_pointers_per_page": 2,
        "max_pointers_per_shard": 4,
        "max_rows_per_shard": 2,
    }
    nodes, edges = build_fixture_graph_rows(recipe)
    expected: dict[str, Any] = {
        "adjacency_sorted_by": ADJACENCY_SORTED_BY,
        "edge_count": len(edges),
        "edges_sorted_by": EDGES_SORTED_BY,
        "max_pointers_per_page": test_bounds["max_pointers_per_page"],
        "max_pointers_per_shard": test_bounds["max_pointers_per_shard"],
        "max_rows_per_shard": test_bounds["max_rows_per_shard"],
        "node_count": len(nodes),
        "nodes_sorted_by": NODES_SORTED_BY,
        "unique_edge_cids": sorted(edge["edge_cid"] for edge in edges),
        "unique_node_cids": sorted(node["node_cid"] for node in nodes),
    }
    if include_realized_layout:
        layout = build_graph_layout(nodes, edges, **test_bounds)
        out_summary = []
        for page in layout.out_adjacency_pages:
            out_summary.append(
                {
                    "edge_cids": list(page.edge_cids),
                    "neighbor_count": page.neighbor_count,
                    "node_cid": page.node_cid,
                    "page_count": page.page_count,
                    "page_index": page.page_index,
                }
            )
        layout_digest = content_sha256(
            canonical_json_dumps(
                {
                    "edge_cids": list(layout.all_edge_cids()),
                    "in_pages": [page.to_dict() for page in layout.in_adjacency_pages],
                    "node_cids": list(layout.all_node_cids()),
                    "out_pages": [page.to_dict() for page in layout.out_adjacency_pages],
                }
            )
        )
        expected.update(
            {
                "edge_shard_count": len(layout.edge_shards),
                "in_adjacency_page_count": len(layout.in_adjacency_pages),
                "in_adjacency_shard_count": len(layout.in_adjacency_shards),
                "layout_digest": layout_digest,
                "node_shard_count": len(layout.node_shards),
                "out_adjacency_page_count": len(layout.out_adjacency_pages),
                "out_adjacency_shard_count": len(layout.out_adjacency_shards),
                "out_page_summary": out_summary,
            }
        )
    return {
        "bounds": graph_bounds_policy(),
        "description": (
            "Compact deterministic recipes for USCIR-022 shared graph and "
            "bounded adjacency layout unit tests. Nodes/edges are regenerated "
            "from the recipe; structural expectations (paging, inverse "
            "reconciliation, key ranges) are derived deterministically at "
            "test time (no bulk golden adjacency dumps)."
        ),
        "expected": expected,
        "goal_id": GOAL_ID,
        "recipe": recipe,
        "schema_version": GRAPH_FIXTURE_SCHEMA_VERSION,
        "task_id": TASK_ID,
        "test_bounds": test_bounds,
    }


def default_graph_adjacency_fixture_path() -> Path:
    """Return the sealed fixture path relative to the repository tests tree."""

    return (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "hf_graphrag"
        / "graph_adjacency.json"
    )


def load_graph_adjacency_fixture(
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Load and lightly validate the graph-adjacency fixture payload."""

    import json

    target = (
        Path(path) if path is not None else default_graph_adjacency_fixture_path()
    )
    if not target.is_file():
        raise HfGraphragGraphError(f"graph adjacency fixture missing: {target}")
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise HfGraphragGraphError("graph adjacency fixture must be a mapping")
    if payload.get("schema_version") != GRAPH_FIXTURE_SCHEMA_VERSION:
        raise HfGraphragGraphError(
            "graph adjacency fixture schema_version differs"
        )
    if payload.get("task_id") != TASK_ID:
        raise HfGraphragGraphError("graph adjacency fixture task_id differs")
    return dict(payload)


def layout_from_fixture(
    payload: Mapping[str, Any] | None = None,
    *,
    path: str | Path | None = None,
) -> GraphLayout:
    """Rebuild a :class:`GraphLayout` from the sealed fixture recipe."""

    data = (
        dict(payload)
        if payload is not None
        else load_graph_adjacency_fixture(path)
    )
    recipe = data.get("recipe")
    if not isinstance(recipe, Mapping):
        raise HfGraphragGraphError("fixture recipe missing")
    bounds = data.get("test_bounds") or {}
    nodes, edges = build_fixture_graph_rows(recipe)
    return build_graph_layout(
        nodes,
        edges,
        max_rows_per_shard=int(bounds.get("max_rows_per_shard", 2)),
        max_pointers_per_page=int(bounds.get("max_pointers_per_page", 2)),
        max_pointers_per_shard=int(bounds.get("max_pointers_per_shard", 4)),
    )


__all__ = [
    "ADJACENCY_SORTED_BY",
    "EDGES_SORTED_BY",
    "GOAL_ID",
    "GRAPH_ADJACENCY_IN_DIR",
    "GRAPH_ADJACENCY_OUT_DIR",
    "GRAPH_ADJACENCY_SCHEMA_VERSION",
    "GRAPH_EDGE_INDEX_PATH",
    "GRAPH_EDGE_SCHEMA_VERSION",
    "GRAPH_EDGES_DIR",
    "GRAPH_FIXTURE_SCHEMA_VERSION",
    "GRAPH_IN_ADJACENCY_INDEX_PATH",
    "GRAPH_LAYOUT_SCHEMA_VERSION",
    "GRAPH_NODE_INDEX_PATH",
    "GRAPH_NODE_SCHEMA_VERSION",
    "GRAPH_NODES_DIR",
    "GRAPH_OUT_ADJACENCY_INDEX_PATH",
    "GRAPH_ROUTING_SCHEMA_VERSION",
    "MAX_ADJACENCY_POINTERS_PER_ROW",
    "MAX_ADJACENCY_POINTERS_PER_SHARD",
    "MAX_ROWS_PER_PHYSICAL_SHARD",
    "NODES_SORTED_BY",
    "TASK_ID",
    "AdjacencyPage",
    "GraphAdjacencyError",
    "GraphEdge",
    "GraphInputError",
    "GraphIntegrityError",
    "GraphLayout",
    "GraphLayoutWriteResult",
    "GraphNode",
    "GraphOrderingError",
    "GraphRangeError",
    "HfGraphragGraphError",
    "KeyRangeShard",
    "adjacency_order_key",
    "build_adjacency_pages",
    "build_fixture_graph_rows",
    "build_graph_adjacency_fixture_payload",
    "build_graph_layout",
    "coerce_graph_edges",
    "coerce_graph_nodes",
    "default_graph_adjacency_fixture_path",
    "graph_bounds_policy",
    "graph_part_relative_path",
    "layout_from_fixture",
    "load_graph_adjacency_fixture",
    "normalize_direction",
    "reconcile_forward_inverse_adjacency",
    "validate_graph_layout",
    "write_graph_layout",
]
