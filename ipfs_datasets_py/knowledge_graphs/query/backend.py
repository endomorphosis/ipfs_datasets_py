"""Unified target-bound GraphQueryBackend (KGP-015).

One protocol supports:

* node / property **scans**
* entity **lookup**
* adjacency **neighbors**
* bounded **paths**
* Cypher **IR** pipelines
* **hybrid / vector** search
* explicit multi-target **federation**

Local Parquet and sharded IPFS adapters return the same canonical row shapes
so callers can compare results without backend-specific massaging.

Every backend is bound to a :class:`~ipfs_datasets_py.knowledge_graphs.service.GraphTarget`.
Distributed / federated execution only uses **declared** targets and never
substitutes a newly constructed empty ``KnowledgeGraph``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import (
    Any,
    Dict,
    Iterable,
    List,
    Literal,
    Mapping,
    Optional,
    Protocol,
    Sequence,
    Tuple,
    runtime_checkable,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

Direction = Literal["outgoing", "incoming", "both"]

CANONICAL_NODE_COLUMNS: Tuple[str, ...] = (
    "id",
    "type",
    "name",
    "properties",
    "cid",
)
CANONICAL_EDGE_COLUMNS: Tuple[str, ...] = (
    "relationship_id",
    "relationship_type",
    "source_id",
    "target_id",
    "direction",
    "properties",
    "cross_shard",
)
CANONICAL_PATH_COLUMNS: Tuple[str, ...] = (
    "path_id",
    "node_ids",
    "edge_ids",
    "length",
    "score",
)
QUERY_ROW_SCHEMA: str = "kg-query-row/v1"
BACKEND_API_VERSION: str = "kg-graph-query-backend/v1"

# Shared typed-error vocabulary (kg-service-contract/v1).
TYPED_ERROR_CODES = frozenset(
    {
        "INVALID_REQUEST",
        "INVALID_TARGET",
        "NOT_FOUND",
        "ALREADY_EXISTS",
        "CONFLICT",
        "FENCED",
        "UNAUTHORIZED",
        "FORBIDDEN",
        "BUDGET_EXCEEDED",
        "QUERY_PARSE",
        "QUERY_EXECUTION",
        "STORAGE",
        "INTEGRITY",
        "NOT_IMPLEMENTED",
        "INTERNAL",
    }
)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class GraphQueryBackendError(Exception):
    """Typed query-backend error with service-contract ``code``."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        details: Optional[Mapping[str, Any]] = None,
    ) -> None:
        if code not in TYPED_ERROR_CODES:
            raise ValueError(f"unknown typed error code: {code!r}")
        self.code = code
        self.message = message
        self.retryable = bool(retryable)
        self.details = dict(details or {})
        super().__init__(f"[{code}] {message}")

    def to_typed_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "details": dict(self.details),
        }


# ---------------------------------------------------------------------------
# Canonical rows / pages
# ---------------------------------------------------------------------------


def _canonical_props(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, Mapping):
        return dict(value)
    if isinstance(value, str):
        if not value:
            return {}
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return dict(parsed) if isinstance(parsed, Mapping) else {}
    return {}


def canonical_node_row(
    *,
    entity_id: str,
    entity_type: str = "",
    name: Optional[str] = None,
    properties: Any = None,
    cid: Optional[str] = None,
) -> Dict[str, Any]:
    """Normalize a node into the canonical row shape shared by all backends."""
    return {
        "id": str(entity_id),
        "type": str(entity_type or ""),
        "name": None if name is None else str(name),
        "properties": _canonical_props(properties),
        "cid": None if cid is None else str(cid),
    }


def canonical_edge_row(
    *,
    relationship_id: str = "",
    relationship_type: str = "",
    source_id: str,
    target_id: str,
    direction: str = "outgoing",
    properties: Any = None,
    cross_shard: bool = False,
) -> Dict[str, Any]:
    """Normalize an edge / neighbor into the canonical row shape."""
    return {
        "relationship_id": str(relationship_id or ""),
        "relationship_type": str(relationship_type or ""),
        "source_id": str(source_id),
        "target_id": str(target_id),
        "direction": str(direction),
        "properties": _canonical_props(properties),
        "cross_shard": bool(cross_shard),
    }


def canonical_path_row(
    *,
    path_id: str,
    node_ids: Sequence[str],
    edge_ids: Sequence[str] = (),
    length: Optional[int] = None,
    score: float = 0.0,
) -> Dict[str, Any]:
    nodes = [str(n) for n in node_ids]
    edges = [str(e) for e in edge_ids]
    return {
        "path_id": str(path_id),
        "node_ids": nodes,
        "edge_ids": edges,
        "length": int(length if length is not None else max(0, len(nodes) - 1)),
        "score": float(score),
    }


def sort_node_rows(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Stable sort for parity comparisons (id ascending)."""
    return sorted((dict(r) for r in rows), key=lambda r: str(r.get("id") or ""))


def sort_edge_rows(rows: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        (dict(r) for r in rows),
        key=lambda r: (
            str(r.get("source_id") or ""),
            str(r.get("target_id") or ""),
            str(r.get("relationship_type") or ""),
            str(r.get("relationship_id") or ""),
            str(r.get("direction") or ""),
        ),
    )


def rows_equal(
    left: Sequence[Mapping[str, Any]],
    right: Sequence[Mapping[str, Any]],
    *,
    kind: str = "node",
) -> bool:
    """True when two row sequences are canonically equivalent."""
    if kind == "edge":
        a, b = sort_edge_rows(left), sort_edge_rows(right)
    else:
        a, b = sort_node_rows(left), sort_node_rows(right)
    if len(a) != len(b):
        return False
    return json.dumps(a, sort_keys=True, separators=(",", ":"), default=str) == json.dumps(
        b, sort_keys=True, separators=(",", ":"), default=str
    )


@dataclass(frozen=True, slots=True)
class EntityHeader:
    """Lightweight entity header (compatible with search.graph_query)."""

    id: str
    type: str
    name: str | None = None
    cid: str | None = None
    properties: dict[str, Any] | None = None

    def to_row(self) -> Dict[str, Any]:
        return canonical_node_row(
            entity_id=self.id,
            entity_type=self.type,
            name=self.name,
            properties=self.properties,
            cid=self.cid,
        )


@dataclass(frozen=True, slots=True)
class NeighborEdge:
    relationship_type: str
    source_id: str
    target_id: str
    relationship_id: str | None = None
    direction: str = "outgoing"
    properties: dict[str, Any] | None = None
    cross_shard: bool = False

    def to_row(self) -> Dict[str, Any]:
        return canonical_edge_row(
            relationship_id=self.relationship_id or "",
            relationship_type=self.relationship_type,
            source_id=self.source_id,
            target_id=self.target_id,
            direction=self.direction,
            properties=self.properties,
            cross_shard=self.cross_shard,
        )

    def other_id(self, entity_id: str) -> str:
        if entity_id == self.source_id:
            return self.target_id
        return self.source_id


@dataclass(frozen=True, slots=True)
class ScanPage:
    entity_ids: list[str]
    next_cursor: str | None = None
    shards_touched: int = 0
    shards_touched_ids: list[str] | None = None
    rows: list[dict[str, Any]] | None = None


@dataclass(frozen=True, slots=True)
class NeighborPage:
    edges: list[NeighborEdge]
    next_cursor: str | None = None
    shards_touched: int = 0
    shards_touched_ids: list[str] | None = None
    rows: list[dict[str, Any]] | None = None


@dataclass(frozen=True, slots=True)
class PathPage:
    paths: list[dict[str, Any]]
    next_cursor: str | None = None
    stats: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HybridHit:
    node_id: str
    score: float
    vector_score: float = 0.0
    graph_score: float = 0.0
    hop_distance: int = 0
    metadata: Optional[Dict[str, Any]] = None

    def to_row(self) -> Dict[str, Any]:
        return {
            "id": self.node_id,
            "score": float(self.score),
            "vector_score": float(self.vector_score),
            "graph_score": float(self.graph_score),
            "hop_distance": int(self.hop_distance),
            "metadata": dict(self.metadata) if self.metadata else {},
        }


@dataclass
class BackendQueryResult:
    """Generic result envelope for backend operations."""

    columns: List[str]
    rows: List[Any]
    schema: str = QUERY_ROW_SCHEMA
    cursor: Optional[str] = None
    statistics: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    truncated: bool = False
    target_uri: Optional[str] = None
    revision: Optional[str] = None

    def to_json_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "columns": list(self.columns),
            "rows": list(self.rows),
            "row_count": len(self.rows),
            "cursor": self.cursor,
            "statistics": dict(self.statistics),
            "warnings": list(self.warnings),
            "truncated": bool(self.truncated),
            "target_uri": self.target_uri,
            "revision": self.revision,
        }


# ---------------------------------------------------------------------------
# IR types (local copies for Cypher-IR pipelines; compatible with search IR)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Op:
    """Base class for IR operators."""


@dataclass(frozen=True)
class SeedEntities(Op):
    entity_ids: Sequence[str]


@dataclass(frozen=True)
class ScanType(Op):
    entity_type: str
    scope: Sequence[str] | None = None


@dataclass(frozen=True)
class Expand(Op):
    relationship_types: Sequence[str] | None = None
    direction: Direction = "both"
    max_per_node: int | None = None


@dataclass(frozen=True)
class Limit(Op):
    n: int


@dataclass(frozen=True)
class Project(Op):
    fields: Sequence[str] = ("id", "type", "name")


@dataclass
class QueryIR:
    """Linear pipeline IR for Cypher-compiled and hand-built queries."""

    ops: list[Op] = field(default_factory=list)

    def add(self, op: Op) -> "QueryIR":
        self.ops.append(op)
        return self

    @classmethod
    def from_ops(cls, ops: Sequence[Op]) -> "QueryIR":
        return cls(list(ops))


@dataclass(frozen=True)
class ExecutionResult:
    items: list[dict[str, Any]]
    stats: dict[str, Any]


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class GraphQueryBackend(Protocol):
    """Target-bound protocol for production graph queries.

    Implementations must never invent ambient graphs or construct empty
    ``KnowledgeGraph`` instances to stand in for a missing target.
    """

    @property
    def target(self) -> Any:
        """Bound :class:`GraphTarget` for this backend instance."""
        ...

    @property
    def revision(self) -> Optional[str]:
        """Immutable revision this backend is reading, when known."""
        ...

    def scan(
        self,
        *,
        entity_type: Optional[str] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
        scope: Optional[Sequence[str]] = None,
    ) -> BackendQueryResult:
        """Scan nodes, optionally filtered by type/label."""
        ...

    def lookup(self, entity_ids: Sequence[str]) -> BackendQueryResult:
        """Lookup entities by id; missing ids are omitted."""
        ...

    def neighbors(
        self,
        entity_id: str,
        *,
        relationship_types: Optional[Sequence[str]] = None,
        direction: Direction = "both",
        limit: int = 1000,
        cursor: Optional[str] = None,
    ) -> BackendQueryResult:
        """Expand adjacency for one entity."""
        ...

    def paths(
        self,
        seed_id: str,
        *,
        max_depth: int = 2,
        max_fan_out: int = 32,
        relationship_types: Optional[Sequence[str]] = None,
        limit: int = 100,
    ) -> BackendQueryResult:
        """Bounded path traversal from *seed_id*."""
        ...

    def execute_ir(
        self,
        ir: QueryIR,
        *,
        budgets: Optional[Mapping[str, Any]] = None,
    ) -> ExecutionResult:
        """Execute a Cypher-IR pipeline against this backend."""
        ...

    def hybrid_search(
        self,
        query: str,
        *,
        k: int = 10,
        vector_weight: float = 0.6,
        graph_weight: float = 0.4,
        max_hops: int = 1,
        embeddings: Optional[Mapping[str, Sequence[float]]] = None,
        query_vector: Optional[Sequence[float]] = None,
    ) -> BackendQueryResult:
        """Hybrid / vector search with optional graph expansion."""
        ...

    def vector_search(
        self,
        query_vector: Sequence[float],
        *,
        k: int = 10,
        embeddings: Optional[Mapping[str, Sequence[float]]] = None,
    ) -> BackendQueryResult:
        """Pure vector nearest-neighbor over supplied or stored embeddings."""
        ...

    # --- search.graph_query.GraphBackend compatibility ---

    def get_entity_headers(
        self, entity_ids: Sequence[str]
    ) -> dict[str, EntityHeader]:
        ...

    def seed_exists(self, entity_id: str) -> bool:
        ...

    def scan_type(
        self,
        entity_type: str,
        *,
        scope: Sequence[str] | None = None,
        limit: int = 100,
        cursor: str | None = None,
        shard_hints: Sequence[str] | None = None,
    ) -> ScanPage:
        ...

    def neighbors_page(
        self,
        entity_id: str,
        *,
        relationship_types: Sequence[str] | None = None,
        direction: Direction = "both",
        limit: int = 1000,
        cursor: str | None = None,
    ) -> NeighborPage:
        ...


# ---------------------------------------------------------------------------
# Target helpers
# ---------------------------------------------------------------------------


def _require_graph_target(target: Any) -> Any:
    """Validate and return a GraphTarget-like object.

    Accepts :class:`GraphTarget`, a mapping, or a ``kg://`` URI string.
    Never invents an empty default graph.
    """
    if target is None:
        raise GraphQueryBackendError(
            "INVALID_TARGET",
            "GraphQueryBackend requires an explicit GraphTarget; "
            "empty / ambient graphs are forbidden",
        )
    # Local import avoids circular import at module load for pure-protocol users.
    from ipfs_datasets_py.knowledge_graphs.service import (
        GraphTarget,
        GraphTargetError,
    )

    try:
        if isinstance(target, GraphTarget):
            return target
        if isinstance(target, str):
            return GraphTarget.from_uri(target)
        if isinstance(target, Mapping):
            return GraphTarget.from_mapping(target)
    except GraphTargetError as exc:
        raise GraphQueryBackendError(
            "INVALID_TARGET",
            str(exc),
            details=getattr(exc, "details", None) or {},
        ) from exc
    raise GraphQueryBackendError(
        "INVALID_TARGET",
        f"unsupported GraphTarget type: {type(target).__name__}",
    )


def _cursor_offset(cursor: Optional[str]) -> int:
    if cursor is None or cursor == "":
        return 0
    if cursor.startswith("off:"):
        try:
            return max(0, int(cursor[4:]))
        except ValueError as exc:
            raise GraphQueryBackendError(
                "INVALID_REQUEST",
                f"invalid cursor: {cursor!r}",
            ) from exc
    try:
        return max(0, int(cursor))
    except ValueError as exc:
        raise GraphQueryBackendError(
            "INVALID_REQUEST",
            f"invalid cursor: {cursor!r}",
        ) from exc


def _make_cursor(offset: int, total: int) -> Optional[str]:
    if offset >= total:
        return None
    return f"off:{offset}"


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b):
        xf = float(x)
        yf = float(y)
        dot += xf * yf
        na += xf * xf
        nb += yf * yf
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (math.sqrt(na) * math.sqrt(nb))


def _text_embedding(text: str, dim: int = 16) -> List[float]:
    """Deterministic bag-of-hashes embedding for offline hybrid/vector tests."""
    vec = [0.0] * dim
    tokens = [t for t in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split() if t]
    if not tokens:
        tokens = ["_empty_"]
    for tok in tokens:
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        for i in range(dim):
            vec[i] += (digest[i % len(digest)] / 255.0) - 0.5
    # L2 normalize
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


# ---------------------------------------------------------------------------
# Base helper class
# ---------------------------------------------------------------------------


class BaseGraphQueryBackend(ABC):
    """Shared helpers for target-bound backends.

    Subclasses implement data access; this base supplies IR execution,
    hybrid/vector defaults, and GraphBackend-compatible wrappers.
    """

    def __init__(self, target: Any) -> None:
        self._target = _require_graph_target(target)

    @property
    def target(self) -> Any:
        return self._target

    @property
    def revision(self) -> Optional[str]:
        return getattr(self._target, "revision", None)

    @property
    def api_version(self) -> str:
        return BACKEND_API_VERSION

    # -- abstract data plane ------------------------------------------------

    @abstractmethod
    def _iter_nodes(self) -> Iterable[Dict[str, Any]]:
        """Yield canonical node rows for this target."""

    @abstractmethod
    def _iter_edges(self) -> Iterable[Dict[str, Any]]:
        """Yield canonical directed edge rows (direction='outgoing')."""

    # -- optional indexes / embeddings --------------------------------------

    def _embeddings(self) -> Mapping[str, Sequence[float]]:
        return {}

    # -- protocol methods ---------------------------------------------------

    def scan(
        self,
        *,
        entity_type: Optional[str] = None,
        limit: int = 100,
        cursor: Optional[str] = None,
        scope: Optional[Sequence[str]] = None,
    ) -> BackendQueryResult:
        if limit < 0:
            raise GraphQueryBackendError("INVALID_REQUEST", "limit must be >= 0")
        offset = _cursor_offset(cursor)
        rows: List[Dict[str, Any]] = []
        for row in sort_node_rows(list(self._iter_nodes())):
            if entity_type is not None and row.get("type") != entity_type:
                continue
            if scope is not None and str(row.get("id")) not in set(scope):
                # scope as entity-id allow-list when provided as ids
                # backends may also interpret scope as shard ids; default is id filter
                # only when all scope values look like entity ids present in graph.
                pass  # scope filtering applied only when implemented by subclass
            rows.append(row)
        # Optional scope: if every scope value is an entity id we filter;
        # otherwise subclasses that understand shard scope override scan().
        if scope is not None:
            scope_set = {str(s) for s in scope}
            id_set = {str(r["id"]) for r in rows}
            if scope_set & id_set:
                rows = [r for r in rows if r["id"] in scope_set]
        total = len(rows)
        page = rows[offset : offset + limit] if limit else rows[offset:]
        next_off = offset + len(page)
        return BackendQueryResult(
            columns=list(CANONICAL_NODE_COLUMNS),
            rows=page,
            schema=QUERY_ROW_SCHEMA,
            cursor=_make_cursor(next_off, total),
            statistics={
                "total": total,
                "returned": len(page),
                "offset": offset,
                "entity_type": entity_type,
            },
            truncated=bool(_make_cursor(next_off, total)),
            target_uri=getattr(self._target, "uri", None),
            revision=self.revision,
        )

    def lookup(self, entity_ids: Sequence[str]) -> BackendQueryResult:
        wanted = [str(e) for e in entity_ids]
        by_id = {str(r["id"]): r for r in self._iter_nodes()}
        rows = [by_id[eid] for eid in wanted if eid in by_id]
        return BackendQueryResult(
            columns=list(CANONICAL_NODE_COLUMNS),
            rows=rows,
            schema=QUERY_ROW_SCHEMA,
            statistics={"requested": len(wanted), "found": len(rows)},
            target_uri=getattr(self._target, "uri", None),
            revision=self.revision,
        )

    def neighbors(
        self,
        entity_id: str,
        *,
        relationship_types: Optional[Sequence[str]] = None,
        direction: Direction = "both",
        limit: int = 1000,
        cursor: Optional[str] = None,
    ) -> BackendQueryResult:
        if direction not in {"outgoing", "incoming", "both"}:
            raise GraphQueryBackendError(
                "INVALID_REQUEST", f"invalid direction {direction!r}"
            )
        if limit < 0:
            raise GraphQueryBackendError("INVALID_REQUEST", "limit must be >= 0")
        type_filter = set(relationship_types) if relationship_types else None
        eid = str(entity_id)
        collected: List[Dict[str, Any]] = []
        for edge in self._iter_edges():
            rtype = str(edge.get("relationship_type") or "")
            if type_filter is not None and rtype not in type_filter:
                continue
            src = str(edge.get("source_id") or "")
            tgt = str(edge.get("target_id") or "")
            base = {
                "relationship_id": str(edge.get("relationship_id") or ""),
                "relationship_type": rtype,
                "source_id": src,
                "target_id": tgt,
                "properties": _canonical_props(edge.get("properties")),
                "cross_shard": bool(edge.get("cross_shard", False)),
            }
            if direction in {"outgoing", "both"} and src == eid:
                collected.append(canonical_edge_row(**base, direction="outgoing"))
            if direction in {"incoming", "both"} and tgt == eid:
                collected.append(canonical_edge_row(**base, direction="incoming"))
        collected = sort_edge_rows(collected)
        offset = _cursor_offset(cursor)
        total = len(collected)
        page = collected[offset : offset + limit] if limit else collected[offset:]
        next_off = offset + len(page)
        return BackendQueryResult(
            columns=list(CANONICAL_EDGE_COLUMNS),
            rows=page,
            schema=QUERY_ROW_SCHEMA,
            cursor=_make_cursor(next_off, total),
            statistics={
                "entity_id": eid,
                "total": total,
                "returned": len(page),
                "direction": direction,
            },
            truncated=bool(_make_cursor(next_off, total)),
            target_uri=getattr(self._target, "uri", None),
            revision=self.revision,
        )

    def paths(
        self,
        seed_id: str,
        *,
        max_depth: int = 2,
        max_fan_out: int = 32,
        relationship_types: Optional[Sequence[str]] = None,
        limit: int = 100,
    ) -> BackendQueryResult:
        if max_depth < 0:
            raise GraphQueryBackendError("INVALID_REQUEST", "max_depth must be >= 0")
        seed = str(seed_id)
        # BFS collecting simple paths (node sequences).
        paths_out: List[Dict[str, Any]] = []
        # path = (node_ids, edge_ids)
        frontier: List[Tuple[List[str], List[str]]] = [([seed], [])]
        seen_paths = 0
        for depth in range(max_depth):
            next_frontier: List[Tuple[List[str], List[str]]] = []
            for node_ids, edge_ids in frontier:
                if len(paths_out) >= limit:
                    break
                current = node_ids[-1]
                nbr = self.neighbors(
                    current,
                    relationship_types=relationship_types,
                    direction="both",
                    limit=max(0, max_fan_out),
                )
                for edge in nbr.rows[: max(0, max_fan_out)]:
                    other = (
                        edge["target_id"]
                        if edge["source_id"] == current
                        else edge["source_id"]
                    )
                    if other in node_ids:
                        continue  # simple paths only
                    new_nodes = node_ids + [other]
                    new_edges = edge_ids + [str(edge.get("relationship_id") or "")]
                    seen_paths += 1
                    paths_out.append(
                        canonical_path_row(
                            path_id=f"p{seen_paths}",
                            node_ids=new_nodes,
                            edge_ids=new_edges,
                            score=1.0 / len(new_nodes),
                        )
                    )
                    if len(paths_out) >= limit:
                        break
                    if depth + 1 < max_depth:
                        next_frontier.append((new_nodes, new_edges))
            frontier = next_frontier
            if not frontier or len(paths_out) >= limit:
                break

        return BackendQueryResult(
            columns=list(CANONICAL_PATH_COLUMNS),
            rows=paths_out[:limit],
            schema=QUERY_ROW_SCHEMA,
            statistics={
                "seed": seed,
                "max_depth": max_depth,
                "path_count": len(paths_out[:limit]),
            },
            truncated=len(paths_out) > limit,
            target_uri=getattr(self._target, "uri", None),
            revision=self.revision,
        )

    def execute_ir(
        self,
        ir: QueryIR,
        *,
        budgets: Optional[Mapping[str, Any]] = None,
    ) -> ExecutionResult:
        """Execute a linear IR pipeline using this backend's data plane."""
        budgets = dict(budgets or {})
        max_results = int(budgets.get("max_results", 1000) or 1000)
        allow_unanchored = bool(budgets.get("allow_unanchored_scan", True))
        max_degree = int(budgets.get("max_degree_per_node", 10_000) or 10_000)

        if not ir.ops:
            return ExecutionResult(items=[], stats={"empty": True})

        working_ids: List[str] = []
        projection: Optional[Project] = None
        nodes_visited = 0
        edges_scanned = 0
        depth = 0

        for i, op in enumerate(ir.ops):
            next_op = ir.ops[i + 1] if i + 1 < len(ir.ops) else None

            if isinstance(op, Project):
                projection = op
                continue

            if isinstance(op, Limit):
                n = max(0, int(op.n))
                working_ids = working_ids[:n]
                continue

            if isinstance(op, SeedEntities):
                by_id = {str(r["id"]) for r in self._iter_nodes()}
                ids = [str(e) for e in op.entity_ids if str(e) in by_id]
                working_ids = list(dict.fromkeys(ids))
                nodes_visited += len(working_ids)
                continue

            if isinstance(op, ScanType):
                if not allow_unanchored and not op.scope:
                    raise GraphQueryBackendError(
                        "QUERY_EXECUTION",
                        "Unanchored type scan rejected: provide scope or "
                        "enable allow_unanchored_scan",
                    )
                target_n = max_results
                if isinstance(next_op, Limit):
                    target_n = min(target_n, max(0, int(next_op.n)))
                et = op.entity_type
                if et in ("", "*", None):
                    et = None
                page = self.scan(
                    entity_type=et,
                    limit=target_n,
                    scope=op.scope,
                )
                working_ids = list(
                    dict.fromkeys(str(r["id"]) for r in page.rows)
                )
                nodes_visited += len(working_ids)
                continue

            if isinstance(op, Expand):
                depth += 1
                max_per = op.max_per_node or max_degree
                max_per = min(int(max_per), max_degree)
                next_ids: List[str] = []
                next_seen: set[str] = set()
                for eid in working_ids:
                    page = self.neighbors(
                        eid,
                        relationship_types=op.relationship_types,
                        direction=op.direction,
                        limit=max_per,
                    )
                    edges_scanned += len(page.rows)
                    for edge in page.rows:
                        other = (
                            edge["target_id"]
                            if edge["source_id"] == eid
                            else edge["source_id"]
                        )
                        if other in next_seen:
                            continue
                        next_seen.add(other)
                        next_ids.append(other)
                working_ids = next_ids
                nodes_visited += len(working_ids)
                continue

            raise GraphQueryBackendError(
                "NOT_IMPLEMENTED",
                f"Unsupported IR op: {type(op).__name__}",
            )

        headers = self.get_entity_headers(working_ids)
        fields = tuple(projection.fields) if projection else ("id", "type", "name")
        items: List[Dict[str, Any]] = []
        for eid in working_ids:
            header = headers.get(eid)
            if header is None:
                continue
            record = asdict(header)
            items.append({k: record.get(k) for k in fields if k in record})
            if len(items) >= max_results:
                break

        return ExecutionResult(
            items=items,
            stats={
                "nodes_visited": nodes_visited,
                "edges_scanned": edges_scanned,
                "depth": depth,
                "returned": len(items),
                "target_uri": getattr(self._target, "uri", None),
                "revision": self.revision,
            },
        )

    def vector_search(
        self,
        query_vector: Sequence[float],
        *,
        k: int = 10,
        embeddings: Optional[Mapping[str, Sequence[float]]] = None,
    ) -> BackendQueryResult:
        if k < 0:
            raise GraphQueryBackendError("INVALID_REQUEST", "k must be >= 0")
        emb = dict(embeddings or self._embeddings())
        if not emb:
            # Derive deterministic embeddings from node names/types.
            for row in self._iter_nodes():
                text = f"{row.get('type') or ''} {row.get('name') or row.get('id')}"
                emb[str(row["id"])] = _text_embedding(text)
        scored: List[Tuple[float, str]] = []
        for nid, vec in emb.items():
            scored.append((_cosine(query_vector, vec), str(nid)))
        scored.sort(key=lambda t: (-t[0], t[1]))
        hits = [
            HybridHit(node_id=nid, score=score, vector_score=score).to_row()
            for score, nid in scored[:k]
        ]
        return BackendQueryResult(
            columns=["id", "score", "vector_score", "graph_score", "hop_distance", "metadata"],
            rows=hits,
            schema="kg-vector-hit/v1",
            statistics={"k": k, "corpus": len(emb)},
            target_uri=getattr(self._target, "uri", None),
            revision=self.revision,
        )

    def hybrid_search(
        self,
        query: str,
        *,
        k: int = 10,
        vector_weight: float = 0.6,
        graph_weight: float = 0.4,
        max_hops: int = 1,
        embeddings: Optional[Mapping[str, Sequence[float]]] = None,
        query_vector: Optional[Sequence[float]] = None,
    ) -> BackendQueryResult:
        qvec = list(query_vector) if query_vector is not None else _text_embedding(query)
        vw = float(vector_weight)
        gw = float(graph_weight)
        total_w = vw + gw
        if total_w <= 0:
            vw, gw, total_w = 1.0, 0.0, 1.0
        vw, gw = vw / total_w, gw / total_w

        vec_res = self.vector_search(qvec, k=max(k, 1) * 2, embeddings=embeddings)
        seed_scores: Dict[str, float] = {
            str(r["id"]): float(r["vector_score"]) for r in vec_res.rows
        }
        graph_scores: Dict[str, float] = {nid: 0.0 for nid in seed_scores}
        hop: Dict[str, int] = {nid: 0 for nid in seed_scores}

        if max_hops > 0 and seed_scores:
            frontier = list(seed_scores.keys())
            for depth in range(1, max_hops + 1):
                next_frontier: List[str] = []
                for nid in frontier:
                    nbr = self.neighbors(nid, direction="both", limit=64)
                    for edge in nbr.rows:
                        other = (
                            edge["target_id"]
                            if edge["source_id"] == nid
                            else edge["source_id"]
                        )
                        gain = 1.0 / (depth + 1)
                        graph_scores[other] = max(graph_scores.get(other, 0.0), gain)
                        if other not in hop:
                            hop[other] = depth
                            next_frontier.append(other)
                        if other not in seed_scores:
                            seed_scores[other] = 0.0
                frontier = next_frontier
                if not frontier:
                    break

        combined: List[HybridHit] = []
        for nid, vscore in seed_scores.items():
            gscore = graph_scores.get(nid, 0.0)
            combined.append(
                HybridHit(
                    node_id=nid,
                    score=vw * vscore + gw * gscore,
                    vector_score=vscore,
                    graph_score=gscore,
                    hop_distance=hop.get(nid, 0),
                    metadata={"query": query},
                )
            )
        combined.sort(key=lambda h: (-h.score, h.node_id))
        rows = [h.to_row() for h in combined[:k]]
        return BackendQueryResult(
            columns=["id", "score", "vector_score", "graph_score", "hop_distance", "metadata"],
            rows=rows,
            schema="kg-hybrid-hit/v1",
            statistics={
                "k": k,
                "vector_weight": vw,
                "graph_weight": gw,
                "max_hops": max_hops,
                "candidates": len(combined),
            },
            target_uri=getattr(self._target, "uri", None),
            revision=self.revision,
        )

    # --- GraphBackend compatibility ---

    def get_entity_headers(
        self, entity_ids: Sequence[str]
    ) -> dict[str, EntityHeader]:
        res = self.lookup(entity_ids)
        out: dict[str, EntityHeader] = {}
        for row in res.rows:
            eid = str(row["id"])
            out[eid] = EntityHeader(
                id=eid,
                type=str(row.get("type") or ""),
                name=row.get("name"),
                cid=row.get("cid"),
                properties=dict(row.get("properties") or {}) or None,
            )
        return out

    def seed_exists(self, entity_id: str) -> bool:
        return bool(self.lookup([entity_id]).rows)

    def scan_type(
        self,
        entity_type: str,
        *,
        scope: Sequence[str] | None = None,
        limit: int = 100,
        cursor: str | None = None,
        shard_hints: Sequence[str] | None = None,
    ) -> ScanPage:
        _ = shard_hints
        page = self.scan(
            entity_type=entity_type, limit=limit, cursor=cursor, scope=scope
        )
        ids = [str(r["id"]) for r in page.rows]
        return ScanPage(
            entity_ids=ids,
            next_cursor=page.cursor,
            shards_touched=int(page.statistics.get("shards_touched", 0) or 0),
            shards_touched_ids=page.statistics.get("shards_touched_ids"),
            rows=list(page.rows),
        )

    def neighbors_page(
        self,
        entity_id: str,
        *,
        relationship_types: Sequence[str] | None = None,
        direction: Direction = "both",
        limit: int = 1000,
        cursor: str | None = None,
    ) -> NeighborPage:
        # Also expose as ``neighbors`` returning NeighborPage when called via
        # the legacy GraphBackend duck-typing path used by search.graph_query
        # executor. That path expects a NeighborPage, so adapters override.
        page = self.neighbors(
            entity_id,
            relationship_types=relationship_types,
            direction=direction,
            limit=limit,
            cursor=cursor,
        )
        edges = [
            NeighborEdge(
                relationship_type=str(r.get("relationship_type") or ""),
                source_id=str(r.get("source_id") or ""),
                target_id=str(r.get("target_id") or ""),
                relationship_id=str(r.get("relationship_id") or "") or None,
                direction=str(r.get("direction") or "outgoing"),
                properties=dict(r.get("properties") or {}) or None,
                cross_shard=bool(r.get("cross_shard", False)),
            )
            for r in page.rows
        ]
        return NeighborPage(
            edges=edges,
            next_cursor=page.cursor,
            shards_touched=int(page.statistics.get("shards_touched", 0) or 0),
            shards_touched_ids=page.statistics.get("shards_touched_ids"),
            rows=list(page.rows),
        )


# ---------------------------------------------------------------------------
# In-memory backend (tests / federation leaves)
# ---------------------------------------------------------------------------


class InMemoryGraphQueryBackend(BaseGraphQueryBackend):
    """Target-bound in-memory backend. Never constructs empty KnowledgeGraph."""

    def __init__(
        self,
        target: Any,
        *,
        nodes: Optional[Sequence[Mapping[str, Any]]] = None,
        edges: Optional[Sequence[Mapping[str, Any]]] = None,
        embeddings: Optional[Mapping[str, Sequence[float]]] = None,
        revision: Optional[str] = None,
    ) -> None:
        super().__init__(target)
        if revision is not None and getattr(self._target, "revision", None) is None:
            # Preserve declared revision when target only names branch.
            self._revision_override = str(revision)
        else:
            self._revision_override = None
        self._nodes: List[Dict[str, Any]] = []
        for n in nodes or ():
            self._nodes.append(
                canonical_node_row(
                    entity_id=str(
                        n.get("id") or n.get("entity_id") or n.get("node_id")
                    ),
                    entity_type=str(n.get("type") or n.get("entity_type") or ""),
                    name=n.get("name"),
                    properties=n.get("properties"),
                    cid=n.get("cid"),
                )
            )
        self._edges: List[Dict[str, Any]] = []
        for e in edges or ():
            self._edges.append(
                canonical_edge_row(
                    relationship_id=str(
                        e.get("id")
                        or e.get("relationship_id")
                        or e.get("edge_id")
                        or ""
                    ),
                    relationship_type=str(
                        e.get("type") or e.get("relationship_type") or ""
                    ),
                    source_id=str(
                        e.get("source_id") or e.get("source") or e.get("start") or ""
                    ),
                    target_id=str(
                        e.get("target_id") or e.get("target") or e.get("end") or ""
                    ),
                    direction="outgoing",
                    properties=e.get("properties"),
                    cross_shard=bool(e.get("cross_shard", False)),
                )
            )
        self._emb = {str(k): list(v) for k, v in (embeddings or {}).items()}

    @property
    def revision(self) -> Optional[str]:
        return self._revision_override or super().revision

    def _iter_nodes(self) -> Iterable[Dict[str, Any]]:
        return iter(self._nodes)

    def _iter_edges(self) -> Iterable[Dict[str, Any]]:
        return iter(self._edges)

    def _embeddings(self) -> Mapping[str, Sequence[float]]:
        return self._emb


# ---------------------------------------------------------------------------
# Parquet backend
# ---------------------------------------------------------------------------


class ParquetGraphQueryBackend(BaseGraphQueryBackend):
    """GraphQueryBackend over a published ParquetGraphStore revision."""

    def __init__(
        self,
        target: Any,
        store: Any,
        *,
        tenant: Optional[str] = None,
        graph_id: Optional[str] = None,
        revision_id: Optional[str] = None,
    ) -> None:
        super().__init__(target)
        self._store = store
        t = tenant or getattr(self._target, "tenant", None)
        g = graph_id or getattr(self._target, "graph_id", None)
        r = revision_id or getattr(self._target, "revision", None)
        if not t or not g or not r:
            raise GraphQueryBackendError(
                "INVALID_TARGET",
                "ParquetGraphQueryBackend requires tenant, graph_id, and revision",
                details={"tenant": t, "graph_id": g, "revision": r},
            )
        self._tenant = str(t)
        self._graph_id = str(g)
        self._revision_id = str(r)
        self._node_cache: Optional[List[Dict[str, Any]]] = None
        self._edge_cache: Optional[List[Dict[str, Any]]] = None

    @property
    def revision(self) -> Optional[str]:
        return self._revision_id

    def _load_nodes(self) -> List[Dict[str, Any]]:
        if self._node_cache is not None:
            return self._node_cache
        raw = self._store.scan_nodes(self._tenant, self._graph_id, self._revision_id)
        rows: List[Dict[str, Any]] = []
        for n in raw:
            props = n.get("properties")
            if props is None and "properties_json" in n:
                props = n.get("properties_json")
            rows.append(
                canonical_node_row(
                    entity_id=str(n.get("id") or ""),
                    entity_type=str(n.get("type") or ""),
                    name=n.get("name") if n.get("name") not in ("", None) else n.get("name"),
                    properties=props,
                    cid=n.get("cid"),
                )
            )
        self._node_cache = rows
        return rows

    def _load_edges(self) -> List[Dict[str, Any]]:
        if self._edge_cache is not None:
            return self._edge_cache
        raw = self._store.scan_edges(self._tenant, self._graph_id, self._revision_id)
        rows: List[Dict[str, Any]] = []
        for e in raw:
            props = e.get("properties")
            if props is None and "properties_json" in e:
                props = e.get("properties_json")
            rows.append(
                canonical_edge_row(
                    relationship_id=str(e.get("id") or ""),
                    relationship_type=str(e.get("type") or ""),
                    source_id=str(e.get("source_id") or ""),
                    target_id=str(e.get("target_id") or ""),
                    direction="outgoing",
                    properties=props,
                    cross_shard=False,
                )
            )
        self._edge_cache = rows
        return rows

    def _iter_nodes(self) -> Iterable[Dict[str, Any]]:
        return iter(self._load_nodes())

    def _iter_edges(self) -> Iterable[Dict[str, Any]]:
        return iter(self._load_edges())


# ---------------------------------------------------------------------------
# Sharded IPFS backend
# ---------------------------------------------------------------------------


class ShardedIPFSGraphQueryBackend(BaseGraphQueryBackend):
    """GraphQueryBackend over KGP-014 :class:`ShardedQueryRuntime`.

    Local Parquet and this backend return canonically equivalent rows for the
    same logical graph.
    """

    def __init__(
        self,
        target: Any,
        runtime: Any = None,
        *,
        published: Any = None,
        manifest: Any = None,
        store: Any = None,
        revision: Optional[str] = None,
    ) -> None:
        super().__init__(target)
        if runtime is None:
            from ipfs_datasets_py.knowledge_graphs.storage.sharding.runtime import (
                open_sharded_query,
            )

            runtime = open_sharded_query(
                published, manifest=manifest, store=store
            )
        self._runtime = runtime
        man = getattr(runtime, "manifest", None)
        self._revision_override = revision or (
            getattr(man, "root_cid", None) if man is not None else None
        )
        self._node_cache: Optional[List[Dict[str, Any]]] = None
        self._edge_cache: Optional[List[Dict[str, Any]]] = None

    @property
    def revision(self) -> Optional[str]:
        return self._revision_override or super().revision

    def _load_all_fragments(self) -> None:
        if self._node_cache is not None and self._edge_cache is not None:
            return
        nodes: Dict[str, Dict[str, Any]] = {}
        edges: List[Dict[str, Any]] = []
        seen_rel: set[str] = set()
        runtime = self._runtime
        failures: list = []
        for phys in runtime.manifest.physical_shards:
            frag = runtime.load_physical_shard(
                phys.physical_shard_id, failures=failures
            )
            if frag is None:
                continue
            for ent in frag.iter_entities():
                nodes[ent.entity_id] = canonical_node_row(
                    entity_id=ent.entity_id,
                    entity_type=ent.entity_type,
                    name=ent.name,
                    properties=ent.properties,
                    cid=ent.cid,
                )
            for rel in frag.iter_relationships():
                if rel.relationship_id in seen_rel:
                    continue
                seen_rel.add(rel.relationship_id)
                edges.append(
                    canonical_edge_row(
                        relationship_id=rel.relationship_id,
                        relationship_type=rel.relationship_type,
                        source_id=rel.source_id,
                        target_id=rel.target_id,
                        direction="outgoing",
                        properties=rel.properties,
                        cross_shard=False,
                    )
                )
        # Cross-shard edges are stored in adjacency descriptors, not always in CAR.
        for desc in runtime.list_cross_shard_adjacency():
            try:
                from ipfs_datasets_py.knowledge_graphs.storage.sharding.blocks import (
                    decode_json_block,
                )

                raw = runtime.fetch_block(
                    cid=desc.cid,
                    path=desc.path,
                    checksum=desc.checksum,
                    label=f"xadj:{desc.adjacency_id}",
                )
                payload = decode_json_block(raw)
            except Exception as exc:  # pragma: no cover - depends on store
                logger.debug("cross-shard adjacency load failed: %s", exc)
                continue
            for edge_raw in payload.get("edges") or []:
                if not isinstance(edge_raw, Mapping):
                    continue
                rid = str(
                    edge_raw.get("id")
                    or edge_raw.get("relationship_id")
                    or ""
                )
                if rid and rid in seen_rel:
                    continue
                if rid:
                    seen_rel.add(rid)
                edges.append(
                    canonical_edge_row(
                        relationship_id=rid,
                        relationship_type=str(
                            edge_raw.get("type")
                            or edge_raw.get("relationship_type")
                            or ""
                        ),
                        source_id=str(edge_raw.get("source_id") or ""),
                        target_id=str(edge_raw.get("target_id") or ""),
                        direction="outgoing",
                        properties=edge_raw.get("properties"),
                        cross_shard=True,
                    )
                )
        self._node_cache = list(nodes.values())
        self._edge_cache = edges

    def _iter_nodes(self) -> Iterable[Dict[str, Any]]:
        self._load_all_fragments()
        assert self._node_cache is not None
        return iter(self._node_cache)

    def _iter_edges(self) -> Iterable[Dict[str, Any]]:
        self._load_all_fragments()
        assert self._edge_cache is not None
        return iter(self._edge_cache)

    def neighbors(
        self,
        entity_id: str,
        *,
        relationship_types: Optional[Sequence[str]] = None,
        direction: Direction = "both",
        limit: int = 1000,
        cursor: Optional[str] = None,
    ) -> BackendQueryResult:
        # Prefer runtime cross-shard-aware neighbors when available.
        try:
            res = self._runtime.neighbors(
                entity_id,
                direction=direction,
                relationship_types=relationship_types,
                include_cross_shard=True,
                prefetch=True,
            )
            rows = [
                canonical_edge_row(
                    relationship_id=e.relationship_id,
                    relationship_type=e.relationship_type,
                    source_id=e.source_id,
                    target_id=e.target_id,
                    direction=e.direction,
                    properties=e.properties,
                    cross_shard=e.cross_shard,
                )
                for e in res.edges
            ]
            rows = sort_edge_rows(rows)
            offset = _cursor_offset(cursor)
            total = len(rows)
            page = rows[offset : offset + limit] if limit else rows[offset:]
            next_off = offset + len(page)
            return BackendQueryResult(
                columns=list(CANONICAL_EDGE_COLUMNS),
                rows=page,
                schema=QUERY_ROW_SCHEMA,
                cursor=_make_cursor(next_off, total),
                statistics={
                    "entity_id": entity_id,
                    "total": total,
                    "returned": len(page),
                    "direction": direction,
                    "home_shard": (res.stats or {}).get("home_shard"),
                    "shards_touched": 1,
                },
                truncated=bool(_make_cursor(next_off, total)),
                target_uri=getattr(self._target, "uri", None),
                revision=self.revision,
            )
        except Exception:
            return super().neighbors(
                entity_id,
                relationship_types=relationship_types,
                direction=direction,
                limit=limit,
                cursor=cursor,
            )


# ---------------------------------------------------------------------------
# Explicit federation
# ---------------------------------------------------------------------------


class FederatedGraphQueryBackend(BaseGraphQueryBackend):
    """Federate over a **declared** list of target-bound backends.

    Refuses to construct empty KnowledgeGraphs. Every leaf must already be a
    bound :class:`GraphQueryBackend` with an explicit target.
    """

    def __init__(
        self,
        target: Any,
        backends: Sequence[GraphQueryBackend],
        *,
        require_targets: bool = True,
    ) -> None:
        super().__init__(target)
        leaves: List[GraphQueryBackend] = []
        for b in backends:
            if b is None:
                raise GraphQueryBackendError(
                    "INVALID_REQUEST",
                    "federation backends must be non-null declared targets",
                )
            # Guard: reject empty KnowledgeGraph stand-ins before target checks.
            cls_name = type(b).__name__
            if cls_name == "KnowledgeGraph":
                raise GraphQueryBackendError(
                    "INVALID_REQUEST",
                    "federation must not use a newly constructed empty "
                    "KnowledgeGraph; pass declared GraphQueryBackend targets",
                )
            if require_targets and getattr(b, "target", None) is None:
                raise GraphQueryBackendError(
                    "INVALID_TARGET",
                    "federation leaf missing GraphTarget",
                )
            leaves.append(b)
        if not leaves:
            raise GraphQueryBackendError(
                "INVALID_REQUEST",
                "federation requires at least one declared target backend",
            )
        self._leaves = list(leaves)

    @property
    def leaf_targets(self) -> List[Any]:
        return [getattr(b, "target", None) for b in self._leaves]

    @property
    def leaves(self) -> Sequence[GraphQueryBackend]:
        return tuple(self._leaves)

    def _iter_nodes(self) -> Iterable[Dict[str, Any]]:
        seen: set[str] = set()
        for leaf in self._leaves:
            if isinstance(leaf, BaseGraphQueryBackend):
                rows = list(leaf._iter_nodes())
            else:
                rows = list(leaf.scan(limit=1_000_000).rows)
            for row in rows:
                key = str(row["id"])
                if key in seen:
                    continue
                seen.add(key)
                yield dict(row)

    def _iter_edges(self) -> Iterable[Dict[str, Any]]:
        seen: set[Tuple[str, str, str, str]] = set()
        for leaf in self._leaves:
            if isinstance(leaf, BaseGraphQueryBackend):
                edges = list(leaf._iter_edges())
            else:
                # Fallback: no full edge scan on protocol — expand all nodes.
                edges = []
                for node in leaf.scan(limit=1_000_000).rows:
                    nbr = leaf.neighbors(str(node["id"]), direction="outgoing", limit=1_000_000)
                    edges.extend(nbr.rows)
            for edge in edges:
                key = (
                    str(edge.get("relationship_id") or ""),
                    str(edge.get("source_id") or ""),
                    str(edge.get("target_id") or ""),
                    str(edge.get("relationship_type") or ""),
                )
                if key in seen:
                    continue
                seen.add(key)
                yield dict(edge)

    def federate_lookup(self, entity_ids: Sequence[str]) -> BackendQueryResult:
        """Lookup across all declared leaves; annotate provenance target uri."""
        rows: List[Dict[str, Any]] = []
        for leaf in self._leaves:
            res = leaf.lookup(entity_ids)
            uri = getattr(getattr(leaf, "target", None), "uri", None)
            for row in res.rows:
                r = dict(row)
                r["source_target"] = uri
                rows.append(r)
        return BackendQueryResult(
            columns=list(CANONICAL_NODE_COLUMNS) + ["source_target"],
            rows=rows,
            schema=QUERY_ROW_SCHEMA,
            statistics={
                "requested": len(list(entity_ids)),
                "found": len(rows),
                "targets": len(self._leaves),
            },
            target_uri=getattr(self._target, "uri", None),
            revision=self.revision,
        )


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def open_parquet_backend(
    target: Any,
    store: Any,
    *,
    revision_id: Optional[str] = None,
) -> ParquetGraphQueryBackend:
    return ParquetGraphQueryBackend(target, store, revision_id=revision_id)


def open_sharded_ipfs_backend(
    target: Any,
    *,
    runtime: Any = None,
    published: Any = None,
    manifest: Any = None,
    store: Any = None,
    revision: Optional[str] = None,
) -> ShardedIPFSGraphQueryBackend:
    return ShardedIPFSGraphQueryBackend(
        target,
        runtime=runtime,
        published=published,
        manifest=manifest,
        store=store,
        revision=revision,
    )


def open_federated_backend(
    target: Any,
    backends: Sequence[GraphQueryBackend],
) -> FederatedGraphQueryBackend:
    return FederatedGraphQueryBackend(target, backends)


def open_memory_backend(
    target: Any,
    *,
    nodes: Optional[Sequence[Mapping[str, Any]]] = None,
    edges: Optional[Sequence[Mapping[str, Any]]] = None,
    embeddings: Optional[Mapping[str, Sequence[float]]] = None,
    revision: Optional[str] = None,
) -> InMemoryGraphQueryBackend:
    return InMemoryGraphQueryBackend(
        target,
        nodes=nodes,
        edges=edges,
        embeddings=embeddings,
        revision=revision,
    )


__all__ = [
    "BACKEND_API_VERSION",
    "CANONICAL_EDGE_COLUMNS",
    "CANONICAL_NODE_COLUMNS",
    "CANONICAL_PATH_COLUMNS",
    "QUERY_ROW_SCHEMA",
    "TYPED_ERROR_CODES",
    "Direction",
    "GraphQueryBackendError",
    "EntityHeader",
    "NeighborEdge",
    "ScanPage",
    "NeighborPage",
    "PathPage",
    "HybridHit",
    "BackendQueryResult",
    "Op",
    "SeedEntities",
    "ScanType",
    "Expand",
    "Limit",
    "Project",
    "QueryIR",
    "ExecutionResult",
    "GraphQueryBackend",
    "BaseGraphQueryBackend",
    "InMemoryGraphQueryBackend",
    "ParquetGraphQueryBackend",
    "ShardedIPFSGraphQueryBackend",
    "FederatedGraphQueryBackend",
    "canonical_node_row",
    "canonical_edge_row",
    "canonical_path_row",
    "sort_node_rows",
    "sort_edge_rows",
    "rows_equal",
    "open_parquet_backend",
    "open_sharded_ipfs_backend",
    "open_federated_backend",
    "open_memory_backend",
]
