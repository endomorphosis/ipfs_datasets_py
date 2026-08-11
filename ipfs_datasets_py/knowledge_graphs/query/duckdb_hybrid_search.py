"""Bounded hybrid graph + vector + full-text retrieval (DQK-024).

Unifies graph predicates, exact/approximate vector ranking, text ranking,
provenance filters, and revision/generation filters behind a single bounded
query API. Results bind **graph revision / graph generation** and **vector
collection generation** without intermediate JSON serialization on the hot
path: candidates and scores stay as native dataclasses / SQL rows until the
caller optionally projects them.

Acceptance (DQK-024)
--------------------
* Results bind graph and vector generations
* Query budgets prevent control-plane starvation (reserved capacity)
* Legacy hybrid results meet declared differential thresholds

The analytical path is workload-isolated from the control plane: every query
must leave ``reserved_control_plane_ms`` of wall-clock headroom inside the
caller-supplied budget window so heartbeats / leases are not starved.
"""

from __future__ import annotations

import hashlib
import math
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Dict,
    Final,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from ipfs_datasets_py.vector_stores.duckdb_exact import (
    ExactHit,
    ExactVectorStore,
    ExactVectorStoreError,
    distance as exact_distance,
)

__all__ = [
    "DEFAULT_DIFFERENTIAL_OVERLAP_THRESHOLD",
    "DEFAULT_DIFFERENTIAL_RANK_AGREEMENT_THRESHOLD",
    "DEFAULT_MAX_EDGES",
    "DEFAULT_MAX_NODES",
    "DEFAULT_MAX_ROWS",
    "DEFAULT_MAX_TIME_MS",
    "DEFAULT_MAX_VECTOR_CANDIDATES",
    "DEFAULT_RESERVED_CONTROL_PLANE_MS",
    "DUCKDB_HYBRID_SEARCH_SCHEMA",
    "SCHEMA_VERSION",
    "DifferentialReport",
    "DuckDBHybridSearch",
    "DuckDBHybridSearchError",
    "GraphPredicate",
    "HybridHit",
    "HybridQuery",
    "HybridQueryBudget",
    "HybridSearchResponse",
    "ProvenanceFilter",
    "RevisionFilter",
    "TextQuery",
    "VectorMode",
    "VectorQuery",
    "compare_legacy_hybrid_results",
    "create_duckdb_hybrid_search",
    "legacy_hybrid_fuse",
    "text_rank_score",
    "tokenize_text",
]


# ---------------------------------------------------------------------------
# Pins / defaults
# ---------------------------------------------------------------------------

DUCKDB_HYBRID_SEARCH_SCHEMA: Final[str] = (
    "ipfs_datasets_py/kg-duckdb-hybrid-search@1"
)
SCHEMA_VERSION: Final[int] = 1

# Explicit differential thresholds vs legacy HybridSearchEngine fusion
# (top-k set overlap and pairwise rank agreement).
DEFAULT_DIFFERENTIAL_OVERLAP_THRESHOLD: Final[float] = 0.8
DEFAULT_DIFFERENTIAL_RANK_AGREEMENT_THRESHOLD: Final[float] = 0.7

DEFAULT_MAX_TIME_MS: Final[int] = 5_000
DEFAULT_MAX_ROWS: Final[int] = 1_000
DEFAULT_MAX_NODES: Final[int] = 5_000
DEFAULT_MAX_EDGES: Final[int] = 20_000
DEFAULT_MAX_VECTOR_CANDIDATES: Final[int] = 500
# Capacity reserved so control-plane heartbeats are not starved by analytics.
DEFAULT_RESERVED_CONTROL_PLANE_MS: Final[int] = 250

VERTICES_TABLE: Final[str] = "hybrid_vertices"
EDGES_TABLE: Final[str] = "hybrid_edges"
PROVENANCE_TABLE: Final[str] = "hybrid_provenance"

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@+/-]{0,255}$")
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+", re.UNICODE)
_SUPPORTED_METRICS: Final[frozenset[str]] = frozenset({"l2", "cosine"})


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class DuckDBHybridSearchError(ValueError):
    """Fail-closed rejection of a hybrid query contract or budget breach."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.details = details


# ---------------------------------------------------------------------------
# Enums / query contracts (native structures — no JSON intermediate)
# ---------------------------------------------------------------------------


class VectorMode(str, Enum):
    """Vector retrieval mode for the hybrid API."""

    EXACT = "exact"
    APPROX = "approx"
    AUTO = "auto"


@dataclass(frozen=True)
class HybridQueryBudget:
    """Hard caps plus reserved control-plane capacity.

    ``reserved_control_plane_ms`` is *not* available to the analytical query.
    Effective analytical wall-clock limit is::

        max(1, max_time_ms - reserved_control_plane_ms)

    This prevents hybrid scans from consuming the entire budget window and
    starving control-plane heartbeats / lease renewals.
    """

    max_time_ms: int = DEFAULT_MAX_TIME_MS
    max_rows: int = DEFAULT_MAX_ROWS
    max_nodes: int = DEFAULT_MAX_NODES
    max_edges: int = DEFAULT_MAX_EDGES
    max_vector_candidates: int = DEFAULT_MAX_VECTOR_CANDIDATES
    reserved_control_plane_ms: int = DEFAULT_RESERVED_CONTROL_PLANE_MS

    def __post_init__(self) -> None:
        for name in (
            "max_time_ms",
            "max_rows",
            "max_nodes",
            "max_edges",
            "max_vector_candidates",
            "reserved_control_plane_ms",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise DuckDBHybridSearchError(
                    "BUDGET", f"{name} must be a non-negative int"
                )
        if self.max_time_ms <= 0:
            raise DuckDBHybridSearchError("BUDGET", "max_time_ms must be > 0")
        if self.reserved_control_plane_ms >= self.max_time_ms:
            raise DuckDBHybridSearchError(
                "BUDGET",
                "reserved_control_plane_ms must be < max_time_ms "
                "(control-plane capacity must remain)",
            )
        if self.max_rows > 1_000_000:
            raise DuckDBHybridSearchError("BUDGET", "max_rows exceeds hard cap")
        if self.max_nodes > 5_000_000:
            raise DuckDBHybridSearchError("BUDGET", "max_nodes exceeds hard cap")

    @property
    def analytical_time_ms(self) -> int:
        """Wall-clock budget available to analytical work."""

        return max(1, int(self.max_time_ms) - int(self.reserved_control_plane_ms))

    def to_dict(self) -> Dict[str, Any]:
        # Projection helper only — not used on the search hot path.
        return {
            "max_time_ms": self.max_time_ms,
            "max_rows": self.max_rows,
            "max_nodes": self.max_nodes,
            "max_edges": self.max_edges,
            "max_vector_candidates": self.max_vector_candidates,
            "reserved_control_plane_ms": self.reserved_control_plane_ms,
            "analytical_time_ms": self.analytical_time_ms,
        }


@dataclass(frozen=True)
class GraphPredicate:
    """Graph-side filters and optional bounded multi-hop expansion."""

    node_types: Tuple[str, ...] = ()
    labels: Tuple[str, ...] = ()
    edge_types: Tuple[str, ...] = ()
    property_equals: Tuple[Tuple[str, str], ...] = ()  # (key, value)
    seed_node_ids: Tuple[str, ...] = ()
    max_hops: int = 0
    direction: str = "out"  # out | in | both

    def __post_init__(self) -> None:
        if not isinstance(self.max_hops, int) or isinstance(self.max_hops, bool):
            raise DuckDBHybridSearchError("GRAPH", "max_hops must be int")
        if self.max_hops < 0 or self.max_hops > 64:
            raise DuckDBHybridSearchError("GRAPH", "max_hops out of range [0, 64]")
        direction = (self.direction or "out").lower()
        if direction not in {"out", "in", "both", "outgoing", "incoming"}:
            raise DuckDBHybridSearchError(
                "GRAPH", f"unsupported direction {self.direction!r}"
            )
        # Normalize aliases without mutating frozen fields via object.__setattr__
        # only when needed for stable comparisons in tests/digests.
        normalized = {
            "outgoing": "out",
            "incoming": "in",
        }.get(direction, direction)
        if normalized != self.direction:
            object.__setattr__(self, "direction", normalized)


@dataclass(frozen=True)
class VectorQuery:
    """Exact or approximate vector search request bound to a collection."""

    collection_id: str
    query_vector: Tuple[float, ...]
    k: int = 10
    metric: str = "l2"
    mode: VectorMode = VectorMode.AUTO
    generation_id: Optional[int] = None  # None → use store's published gen
    weight: float = 0.5

    def __post_init__(self) -> None:
        if not isinstance(self.collection_id, str) or not self.collection_id:
            raise DuckDBHybridSearchError("VECTOR", "collection_id required")
        if _SAFE_ID.fullmatch(self.collection_id) is None:
            raise DuckDBHybridSearchError("VECTOR", "invalid collection_id")
        if not isinstance(self.query_vector, Sequence) or isinstance(
            self.query_vector, (str, bytes, bytearray)
        ):
            raise DuckDBHybridSearchError("VECTOR", "query_vector must be numeric")
        if len(self.query_vector) < 1:
            raise DuckDBHybridSearchError("VECTOR", "query_vector empty")
        if not isinstance(self.k, int) or isinstance(self.k, bool) or self.k < 1:
            raise DuckDBHybridSearchError("VECTOR", "k must be >= 1")
        if self.metric not in _SUPPORTED_METRICS:
            raise DuckDBHybridSearchError(
                "VECTOR", f"unsupported metric {self.metric!r}"
            )
        mode = self.mode
        if isinstance(mode, str):
            try:
                mode = VectorMode(mode.lower())
            except ValueError as exc:
                raise DuckDBHybridSearchError(
                    "VECTOR", f"unsupported mode {self.mode!r}"
                ) from exc
            object.__setattr__(self, "mode", mode)
        if self.generation_id is not None:
            if (
                not isinstance(self.generation_id, int)
                or isinstance(self.generation_id, bool)
                or self.generation_id < 1
            ):
                raise DuckDBHybridSearchError(
                    "VECTOR", "generation_id must be int >= 1"
                )
        if not isinstance(self.weight, (int, float)) or isinstance(self.weight, bool):
            raise DuckDBHybridSearchError("VECTOR", "weight must be numeric")
        # Canonicalize vector to tuple[float] for hashability / no JSON path.
        object.__setattr__(
            self, "query_vector", tuple(float(x) for x in self.query_vector)
        )


@dataclass(frozen=True)
class TextQuery:
    """Full-text ranking request over name / source_text fields."""

    query: str
    fields: Tuple[str, ...] = ("name", "source_text")
    weight: float = 0.25

    def __post_init__(self) -> None:
        if not isinstance(self.query, str):
            raise DuckDBHybridSearchError("TEXT", "query must be str")
        if not self.query.strip():
            raise DuckDBHybridSearchError("TEXT", "query must be non-empty")
        allowed = {"name", "source_text", "type"}
        for f in self.fields:
            if f not in allowed:
                raise DuckDBHybridSearchError(
                    "TEXT", f"unsupported text field {f!r}"
                )
        if not isinstance(self.weight, (int, float)) or isinstance(self.weight, bool):
            raise DuckDBHybridSearchError("TEXT", "weight must be numeric")


@dataclass(frozen=True)
class ProvenanceFilter:
    """Filter hybrid candidates by provenance columns (first-class, not JSON)."""

    source_cids: Tuple[str, ...] = ()
    tenants: Tuple[str, ...] = ()
    provenance_kinds: Tuple[str, ...] = ()


@dataclass(frozen=True)
class RevisionFilter:
    """Bind / filter by graph revision and graph generation identity."""

    graph_revisions: Tuple[str, ...] = ()
    graph_generation_ids: Tuple[int, ...] = ()
    require_bound_generations: bool = True


@dataclass(frozen=True)
class HybridQuery:
    """Composed bounded hybrid query (native contracts only)."""

    k: int = 10
    graph: Optional[GraphPredicate] = None
    vector: Optional[VectorQuery] = None
    text: Optional[TextQuery] = None
    provenance: Optional[ProvenanceFilter] = None
    revision: Optional[RevisionFilter] = None
    graph_weight: float = 0.25
    budget: Optional[HybridQueryBudget] = None
    # When True, compute differential report against legacy fusion.
    measure_legacy_differential: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.k, int) or isinstance(self.k, bool) or self.k < 1:
            raise DuckDBHybridSearchError("QUERY", "k must be >= 1")
        if self.vector is None and self.text is None and self.graph is None:
            raise DuckDBHybridSearchError(
                "QUERY",
                "at least one of graph, vector, or text must be provided",
            )


# ---------------------------------------------------------------------------
# Result types (native — never assembled via JSON round-trips)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class HybridHit:
    """One ranked hybrid hit bound to graph and vector generations."""

    node_id: str
    score: float
    vector_score: float = 0.0
    graph_score: float = 0.0
    text_score: float = 0.0
    hop_distance: int = 0
    graph_revision: str = ""
    graph_generation_id: int = 0
    vector_generation_id: int = 0
    vector_collection_id: str = ""
    content_digest: str = ""
    source_cid: str = ""
    tenant: str = ""
    provenance_kind: str = ""
    node_type: str = ""
    name: str = ""
    used_approx_vector: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Optional projection helper; search path never requires this."""

        return {
            "node_id": self.node_id,
            "score": self.score,
            "vector_score": self.vector_score,
            "graph_score": self.graph_score,
            "text_score": self.text_score,
            "hop_distance": self.hop_distance,
            "graph_revision": self.graph_revision,
            "graph_generation_id": self.graph_generation_id,
            "vector_generation_id": self.vector_generation_id,
            "vector_collection_id": self.vector_collection_id,
            "content_digest": self.content_digest,
            "source_cid": self.source_cid,
            "tenant": self.tenant,
            "provenance_kind": self.provenance_kind,
            "node_type": self.node_type,
            "name": self.name,
            "used_approx_vector": self.used_approx_vector,
        }


@dataclass(frozen=True)
class DifferentialReport:
    """Legacy hybrid fusion parity against this engine's ranking."""

    overlap_ratio: float
    rank_agreement: float
    overlap_threshold: float
    rank_agreement_threshold: float
    meets_thresholds: bool
    legacy_ids: Tuple[str, ...]
    hybrid_ids: Tuple[str, ...]
    k: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overlap_ratio": self.overlap_ratio,
            "rank_agreement": self.rank_agreement,
            "overlap_threshold": self.overlap_threshold,
            "rank_agreement_threshold": self.rank_agreement_threshold,
            "meets_thresholds": self.meets_thresholds,
            "legacy_ids": list(self.legacy_ids),
            "hybrid_ids": list(self.hybrid_ids),
            "k": self.k,
        }


@dataclass
class HybridSearchResponse:
    """Bounded hybrid search outcome with generation bindings and budgets."""

    hits: List[HybridHit]
    graph_revision: str = ""
    graph_generation_id: int = 0
    vector_collection_id: str = ""
    vector_generation_id: int = 0
    used_approx_vector: bool = False
    budget: Optional[HybridQueryBudget] = None
    elapsed_ms: int = 0
    analytical_time_ms: int = 0
    reserved_control_plane_ms: int = 0
    nodes_scanned: int = 0
    edges_scanned: int = 0
    vector_candidates: int = 0
    budget_exhausted: bool = False
    differential: Optional[DifferentialReport] = None
    schema: str = DUCKDB_HYBRID_SEARCH_SCHEMA

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": self.schema,
            "hits": [h.to_dict() for h in self.hits],
            "graph_revision": self.graph_revision,
            "graph_generation_id": self.graph_generation_id,
            "vector_collection_id": self.vector_collection_id,
            "vector_generation_id": self.vector_generation_id,
            "used_approx_vector": self.used_approx_vector,
            "budget": self.budget.to_dict() if self.budget else None,
            "elapsed_ms": self.elapsed_ms,
            "analytical_time_ms": self.analytical_time_ms,
            "reserved_control_plane_ms": self.reserved_control_plane_ms,
            "nodes_scanned": self.nodes_scanned,
            "edges_scanned": self.edges_scanned,
            "vector_candidates": self.vector_candidates,
            "budget_exhausted": self.budget_exhausted,
            "differential": (
                self.differential.to_dict() if self.differential else None
            ),
        }


# ---------------------------------------------------------------------------
# Budget tracker
# ---------------------------------------------------------------------------


class _BudgetTracker:
    """Tracks analytical resource use; raises on control-plane starvation risk."""

    def __init__(self, budget: HybridQueryBudget) -> None:
        self.budget = budget
        self.started = time.monotonic()
        self.nodes_scanned = 0
        self.edges_scanned = 0
        self.vector_candidates = 0
        self.exhausted = False
        self.reason: Optional[str] = None

    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started) * 1000)

    def check_time(self) -> None:
        elapsed = self.elapsed_ms()
        limit = self.budget.analytical_time_ms
        if elapsed > limit:
            self.exhausted = True
            self.reason = (
                f"analytical time {elapsed}ms exceeds limit {limit}ms "
                f"(reserved_control_plane_ms={self.budget.reserved_control_plane_ms})"
            )
            raise DuckDBHybridSearchError(
                "BUDGET_EXCEEDED",
                self.reason,
                elapsed_ms=elapsed,
                analytical_time_ms=limit,
                reserved_control_plane_ms=self.budget.reserved_control_plane_ms,
            )

    def add_nodes(self, n: int = 1) -> None:
        self.nodes_scanned += n
        if self.nodes_scanned > self.budget.max_nodes:
            self.exhausted = True
            self.reason = (
                f"nodes_scanned {self.nodes_scanned} > {self.budget.max_nodes}"
            )
            raise DuckDBHybridSearchError(
                "BUDGET_EXCEEDED",
                self.reason,
                nodes_scanned=self.nodes_scanned,
                max_nodes=self.budget.max_nodes,
            )
        self.check_time()

    def add_edges(self, n: int = 1) -> None:
        self.edges_scanned += n
        if self.edges_scanned > self.budget.max_edges:
            self.exhausted = True
            self.reason = (
                f"edges_scanned {self.edges_scanned} > {self.budget.max_edges}"
            )
            raise DuckDBHybridSearchError(
                "BUDGET_EXCEEDED",
                self.reason,
                edges_scanned=self.edges_scanned,
                max_edges=self.budget.max_edges,
            )
        self.check_time()

    def add_vector_candidates(self, n: int) -> None:
        self.vector_candidates += n
        if self.vector_candidates > self.budget.max_vector_candidates:
            self.exhausted = True
            self.reason = (
                f"vector_candidates {self.vector_candidates} > "
                f"{self.budget.max_vector_candidates}"
            )
            raise DuckDBHybridSearchError(
                "BUDGET_EXCEEDED",
                self.reason,
                vector_candidates=self.vector_candidates,
                max_vector_candidates=self.budget.max_vector_candidates,
            )
        self.check_time()


# ---------------------------------------------------------------------------
# Text ranking (BM25-ish TF scoring, pure Python, no JSON)
# ---------------------------------------------------------------------------


def tokenize_text(text: str) -> List[str]:
    """Lowercase alphanumeric tokenization for hermetic text ranking."""

    if not text:
        return []
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def text_rank_score(query: str, document: str) -> float:
    """Simple TF / length-normalized score in ``[0, 1]``.

    Not a full BM25 implementation; sufficient for differential ranking and
    hermetic unit tests without external FTS extensions.
    """

    q_tokens = tokenize_text(query)
    if not q_tokens:
        return 0.0
    d_tokens = tokenize_text(document)
    if not d_tokens:
        return 0.0
    d_counts: Dict[str, int] = {}
    for tok in d_tokens:
        d_counts[tok] = d_counts.get(tok, 0) + 1
    score = 0.0
    q_set = set(q_tokens)
    for tok in q_set:
        tf = d_counts.get(tok, 0)
        if tf <= 0:
            continue
        # Length-normalized TF with mild saturation.
        score += (tf / (tf + 1.0)) / math.log(2.0 + len(d_tokens))
    # Normalize by query term count so scores stay in a stable band.
    raw = score / max(1, len(q_set))
    return max(0.0, min(1.0, raw * 4.0))  # scale into ~[0,1]


# ---------------------------------------------------------------------------
# Legacy fusion (mirrors HybridSearchEngine.fuse_results scoring)
# ---------------------------------------------------------------------------


def legacy_hybrid_fuse(
    vector_scores: Mapping[str, float],
    graph_hops: Mapping[str, int],
    *,
    vector_weight: float = 0.6,
    graph_weight: float = 0.4,
    k: int = 10,
) -> List[Tuple[str, float, float, float, int]]:
    """Reproduce legacy hybrid fusion without importing the full engine.

    Returns list of ``(node_id, score, vector_score, graph_score, hop)``
    sorted by score descending, then node_id ascending for ties.
    """

    total = float(vector_weight) + float(graph_weight)
    if total > 0:
        vw = float(vector_weight) / total
        gw = float(graph_weight) / total
    else:
        vw, gw = 0.5, 0.5

    all_ids = set(vector_scores) | set(graph_hops)
    max_hop = max(graph_hops.values()) if graph_hops else 1
    ranked: List[Tuple[str, float, float, float, int]] = []
    for node_id in all_ids:
        v_score = float(vector_scores.get(node_id, 0.0))
        hop = int(graph_hops.get(node_id, 0 if node_id in vector_scores else max_hop))
        if node_id in graph_hops:
            g_score = 1.0 - (hop / (max_hop + 1))
        else:
            g_score = 0.0
        score = vw * v_score + gw * g_score
        ranked.append((node_id, score, v_score, g_score, hop))
    ranked.sort(key=lambda item: (-item[1], item[0]))
    return ranked[:k]


def compare_legacy_hybrid_results(
    hybrid_ids: Sequence[str],
    legacy_ids: Sequence[str],
    *,
    k: int,
    overlap_threshold: float = DEFAULT_DIFFERENTIAL_OVERLAP_THRESHOLD,
    rank_agreement_threshold: float = DEFAULT_DIFFERENTIAL_RANK_AGREEMENT_THRESHOLD,
) -> DifferentialReport:
    """Measure set-overlap and pairwise rank agreement vs legacy ordering."""

    h = list(hybrid_ids)[:k]
    l = list(legacy_ids)[:k]
    h_set, l_set = set(h), set(l)
    if k <= 0:
        overlap = 1.0
    elif not h_set and not l_set:
        overlap = 1.0
    else:
        overlap = len(h_set & l_set) / max(1, max(len(h_set), len(l_set)))

    # Pairwise rank agreement over shared IDs: fraction of pairs with same order.
    shared = [nid for nid in h if nid in l_set]
    if len(shared) < 2:
        rank_agreement = 1.0 if shared or (not h and not l) else 0.0
    else:
        h_pos = {nid: i for i, nid in enumerate(h)}
        l_pos = {nid: i for i, nid in enumerate(l)}
        agree = 0
        total_pairs = 0
        for i in range(len(shared)):
            for j in range(i + 1, len(shared)):
                a, b = shared[i], shared[j]
                total_pairs += 1
                h_order = h_pos[a] - h_pos[b]
                l_order = l_pos[a] - l_pos[b]
                if (h_order == 0 and l_order == 0) or (h_order * l_order > 0):
                    agree += 1
                elif h_order == 0 or l_order == 0:
                    # One side tied: count as half agreement via skip of strictness
                    agree += 1
        rank_agreement = agree / total_pairs if total_pairs else 1.0

    meets = (
        overlap + 1e-12 >= overlap_threshold
        and rank_agreement + 1e-12 >= rank_agreement_threshold
    )
    return DifferentialReport(
        overlap_ratio=float(overlap),
        rank_agreement=float(rank_agreement),
        overlap_threshold=float(overlap_threshold),
        rank_agreement_threshold=float(rank_agreement_threshold),
        meets_thresholds=bool(meets),
        legacy_ids=tuple(l),
        hybrid_ids=tuple(h),
        k=int(k),
    )


# ---------------------------------------------------------------------------
# Distance → similarity
# ---------------------------------------------------------------------------


def _distance_to_similarity(dist: float, metric: str) -> float:
    """Map exact/approx distance into a ``[0, 1]`` similarity score."""

    d = max(0.0, float(dist))
    if metric == "cosine":
        # cosine distance is already in [0, 2] typically; clamp to [0,1] sim
        return max(0.0, min(1.0, 1.0 - min(d, 1.0)))
    # L2: 1 / (1 + d)
    return 1.0 / (1.0 + d)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


def _require_duckdb() -> Any:
    try:
        import duckdb  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise DuckDBHybridSearchError(
            "DUCKDB_REQUIRED", "duckdb package is required"
        ) from exc
    return duckdb


class DuckDBHybridSearch:
    """Bounded hybrid retrieval over DuckDB graph rows + vector stores.

    Graph vertices/edges live in typed tables with first-class revision and
    provenance columns. Vector identity remains in
    :class:`~ipfs_datasets_py.vector_stores.duckdb_exact.ExactVectorStore`
    (optional approximate acceleration via VSS). Intermediate candidate sets
    are held as native Python structures — never serialized to JSON for
    fusion or ranking.
    """

    SCHEMA: Final[str] = DUCKDB_HYBRID_SEARCH_SCHEMA

    def __init__(
        self,
        path: Union[str, Path, None] = None,
        *,
        exact_store: Optional[ExactVectorStore] = None,
        vss_index: Optional[Any] = None,
        default_budget: Optional[HybridQueryBudget] = None,
        differential_overlap_threshold: float = DEFAULT_DIFFERENTIAL_OVERLAP_THRESHOLD,
        differential_rank_agreement_threshold: float = (
            DEFAULT_DIFFERENTIAL_RANK_AGREEMENT_THRESHOLD
        ),
    ) -> None:
        duckdb = _require_duckdb()
        self._path = Path(path) if path not in (None, ":memory:") else None
        if self._path is not None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            conn_target = str(self._path)
        else:
            conn_target = ":memory:"
        self._lock = threading.RLock()
        self._conn = duckdb.connect(conn_target)
        self._closed = False
        self._exact = exact_store
        self._vss = vss_index
        self._default_budget = default_budget or HybridQueryBudget()
        self._diff_overlap = float(differential_overlap_threshold)
        self._diff_rank = float(differential_rank_agreement_threshold)
        # In-process property map (node_id -> {key: value}) — native, not JSON.
        self._properties: Dict[str, Dict[str, str]] = {}
        self._init_schema()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def _init_schema(self) -> None:
        self._conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {VERTICES_TABLE} (
                node_id VARCHAR PRIMARY KEY,
                graph_revision VARCHAR NOT NULL,
                graph_generation_id INTEGER NOT NULL,
                node_type VARCHAR NOT NULL DEFAULT '',
                name VARCHAR NOT NULL DEFAULT '',
                source_text VARCHAR NOT NULL DEFAULT '',
                source_cid VARCHAR NOT NULL DEFAULT '',
                tenant VARCHAR NOT NULL DEFAULT '',
                provenance_kind VARCHAR NOT NULL DEFAULT '',
                confidence DOUBLE NOT NULL DEFAULT 1.0,
                labels VARCHAR[] NOT NULL DEFAULT []
            )
            """
        )
        self._conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {EDGES_TABLE} (
                edge_id VARCHAR PRIMARY KEY,
                graph_revision VARCHAR NOT NULL,
                graph_generation_id INTEGER NOT NULL,
                edge_type VARCHAR NOT NULL,
                source_id VARCHAR NOT NULL,
                target_id VARCHAR NOT NULL
            )
            """
        )
        self._conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {PROVENANCE_TABLE} (
                node_id VARCHAR NOT NULL,
                source_cid VARCHAR NOT NULL,
                tenant VARCHAR NOT NULL DEFAULT '',
                provenance_kind VARCHAR NOT NULL DEFAULT '',
                graph_revision VARCHAR NOT NULL,
                PRIMARY KEY (node_id, source_cid, graph_revision)
            )
            """
        )
        self._conn.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{EDGES_TABLE}_source
            ON {EDGES_TABLE} (source_id)
            """
        )
        self._conn.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{EDGES_TABLE}_target
            ON {EDGES_TABLE} (target_id)
            """
        )
        self._conn.execute(
            f"""
            CREATE INDEX IF NOT EXISTS idx_{VERTICES_TABLE}_revision
            ON {VERTICES_TABLE} (graph_revision, graph_generation_id)
            """
        )

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._conn.close()
                self._closed = True

    def __enter__(self) -> "DuckDBHybridSearch":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Mutations (typed columns — properties stay native dicts)
    # ------------------------------------------------------------------

    def upsert_vertex(
        self,
        node_id: str,
        *,
        graph_revision: str,
        graph_generation_id: int = 1,
        node_type: str = "",
        name: str = "",
        source_text: str = "",
        source_cid: str = "",
        tenant: str = "",
        provenance_kind: str = "",
        confidence: float = 1.0,
        labels: Optional[Sequence[str]] = None,
        properties: Optional[Mapping[str, Any]] = None,
    ) -> None:
        if _SAFE_ID.fullmatch(node_id) is None:
            raise DuckDBHybridSearchError("ID", "invalid node_id")
        if not isinstance(graph_revision, str) or not graph_revision:
            raise DuckDBHybridSearchError("REVISION", "graph_revision required")
        if (
            not isinstance(graph_generation_id, int)
            or isinstance(graph_generation_id, bool)
            or graph_generation_id < 1
        ):
            raise DuckDBHybridSearchError(
                "REVISION", "graph_generation_id must be int >= 1"
            )
        label_list = list(labels or ())
        # Store properties as native str map — never dump to JSON for indexing.
        prop_map: Dict[str, str] = {}
        if properties:
            for key, value in properties.items():
                if not isinstance(key, str):
                    raise DuckDBHybridSearchError("PROP", "property keys must be str")
                prop_map[key] = value if isinstance(value, str) else str(value)
        with self._lock:
            self._conn.execute(
                f"DELETE FROM {VERTICES_TABLE} WHERE node_id = ?", [node_id]
            )
            self._conn.execute(
                f"""
                INSERT INTO {VERTICES_TABLE} (
                    node_id, graph_revision, graph_generation_id, node_type,
                    name, source_text, source_cid, tenant, provenance_kind,
                    confidence, labels
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    node_id,
                    graph_revision,
                    int(graph_generation_id),
                    node_type or "",
                    name or "",
                    source_text or "",
                    source_cid or "",
                    tenant or "",
                    provenance_kind or "",
                    float(confidence),
                    label_list,
                ],
            )
            if source_cid:
                self._conn.execute(
                    f"""
                    INSERT OR REPLACE INTO {PROVENANCE_TABLE}
                        (node_id, source_cid, tenant, provenance_kind, graph_revision)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    [
                        node_id,
                        source_cid,
                        tenant or "",
                        provenance_kind or "",
                        graph_revision,
                    ],
                )
            self._properties[node_id] = prop_map

    def upsert_edge(
        self,
        edge_id: str,
        *,
        source_id: str,
        target_id: str,
        edge_type: str,
        graph_revision: str,
        graph_generation_id: int = 1,
    ) -> None:
        if _SAFE_ID.fullmatch(edge_id) is None:
            raise DuckDBHybridSearchError("ID", "invalid edge_id")
        if not edge_type:
            raise DuckDBHybridSearchError("EDGE", "edge_type required")
        with self._lock:
            self._conn.execute(
                f"DELETE FROM {EDGES_TABLE} WHERE edge_id = ?", [edge_id]
            )
            self._conn.execute(
                f"""
                INSERT INTO {EDGES_TABLE} (
                    edge_id, graph_revision, graph_generation_id,
                    edge_type, source_id, target_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    edge_id,
                    graph_revision,
                    int(graph_generation_id),
                    edge_type,
                    source_id,
                    target_id,
                ],
            )

    def bind_exact_store(self, store: ExactVectorStore) -> None:
        """Attach / replace the authoritative exact vector store."""

        self._exact = store

    def bind_vss_index(self, index: Any) -> None:
        """Attach optional approximate VSS acceleration (must wrap exact)."""

        self._vss = index

    # ------------------------------------------------------------------
    # Internal loaders (SQL → native rows; no JSON intermediate)
    # ------------------------------------------------------------------

    def _load_vertices(
        self,
        *,
        revision: Optional[RevisionFilter],
        provenance: Optional[ProvenanceFilter],
        tracker: _BudgetTracker,
    ) -> Dict[str, Dict[str, Any]]:
        """Load vertex rows as native dicts keyed by node_id."""

        clauses: List[str] = []
        params: List[Any] = []
        if revision and revision.graph_revisions:
            placeholders = ", ".join("?" for _ in revision.graph_revisions)
            clauses.append(f"graph_revision IN ({placeholders})")
            params.extend(list(revision.graph_revisions))
        if revision and revision.graph_generation_ids:
            placeholders = ", ".join("?" for _ in revision.graph_generation_ids)
            clauses.append(f"graph_generation_id IN ({placeholders})")
            params.extend(int(g) for g in revision.graph_generation_ids)
        if provenance and provenance.source_cids:
            placeholders = ", ".join("?" for _ in provenance.source_cids)
            clauses.append(f"source_cid IN ({placeholders})")
            params.extend(list(provenance.source_cids))
        if provenance and provenance.tenants:
            placeholders = ", ".join("?" for _ in provenance.tenants)
            clauses.append(f"tenant IN ({placeholders})")
            params.extend(list(provenance.tenants))
        if provenance and provenance.provenance_kinds:
            placeholders = ", ".join("?" for _ in provenance.provenance_kinds)
            clauses.append(f"provenance_kind IN ({placeholders})")
            params.extend(list(provenance.provenance_kinds))

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT node_id, graph_revision, graph_generation_id, node_type, "
            f"name, source_text, source_cid, tenant, provenance_kind, "
            f"confidence, labels FROM {VERTICES_TABLE}{where}"
        )
        rows = self._conn.execute(sql, params).fetchall()
        tracker.add_nodes(len(rows))
        if len(rows) > tracker.budget.max_rows * 50:
            # Soft pre-check: huge scans should not run unbounded.
            raise DuckDBHybridSearchError(
                "BUDGET_EXCEEDED",
                "vertex scan exceeds safe analytical bound",
                rows=len(rows),
            )

        out: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            node_id = str(row[0])
            labels_raw = row[10]
            if labels_raw is None:
                labels: Tuple[str, ...] = ()
            elif isinstance(labels_raw, (list, tuple)):
                labels = tuple(str(x) for x in labels_raw)
            else:
                labels = (str(labels_raw),)
            out[node_id] = {
                "node_id": node_id,
                "graph_revision": str(row[1]),
                "graph_generation_id": int(row[2]),
                "node_type": str(row[3] or ""),
                "name": str(row[4] or ""),
                "source_text": str(row[5] or ""),
                "source_cid": str(row[6] or ""),
                "tenant": str(row[7] or ""),
                "provenance_kind": str(row[8] or ""),
                "confidence": float(row[9] if row[9] is not None else 1.0),
                "labels": labels,
                "properties": dict(self._properties.get(node_id, {})),
            }
        return out

    def _load_edges(
        self,
        *,
        revision: Optional[RevisionFilter],
        tracker: _BudgetTracker,
    ) -> List[Tuple[str, str, str, str]]:
        """Return ``(edge_id, edge_type, source_id, target_id)`` tuples."""

        clauses: List[str] = []
        params: List[Any] = []
        if revision and revision.graph_revisions:
            placeholders = ", ".join("?" for _ in revision.graph_revisions)
            clauses.append(f"graph_revision IN ({placeholders})")
            params.extend(list(revision.graph_revisions))
        if revision and revision.graph_generation_ids:
            placeholders = ", ".join("?" for _ in revision.graph_generation_ids)
            clauses.append(f"graph_generation_id IN ({placeholders})")
            params.extend(int(g) for g in revision.graph_generation_ids)
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        sql = (
            f"SELECT edge_id, edge_type, source_id, target_id "
            f"FROM {EDGES_TABLE}{where}"
        )
        rows = self._conn.execute(sql, params).fetchall()
        tracker.add_edges(len(rows))
        return [(str(r[0]), str(r[1]), str(r[2]), str(r[3])) for r in rows]

    def _apply_graph_predicates(
        self,
        vertices: Dict[str, Dict[str, Any]],
        graph: Optional[GraphPredicate],
    ) -> Dict[str, Dict[str, Any]]:
        if graph is None:
            return vertices
        filtered: Dict[str, Dict[str, Any]] = {}
        type_set = set(graph.node_types) if graph.node_types else None
        label_set = set(graph.labels) if graph.labels else None
        prop_eq = list(graph.property_equals) if graph.property_equals else []
        for node_id, row in vertices.items():
            if type_set is not None and row["node_type"] not in type_set:
                continue
            if label_set is not None:
                row_labels = set(row["labels"]) | (
                    {row["node_type"]} if row["node_type"] else set()
                )
                if row_labels.isdisjoint(label_set):
                    continue
            if prop_eq:
                props = row["properties"]
                if any(props.get(k) != v for k, v in prop_eq):
                    continue
            filtered[node_id] = row
        return filtered

    def _expand_graph(
        self,
        seeds: Iterable[str],
        edges: Sequence[Tuple[str, str, str, str]],
        graph: GraphPredicate,
        tracker: _BudgetTracker,
        allowed: Mapping[str, Any],
    ) -> Dict[str, int]:
        """BFS expansion returning node_id → hop distance (bounded)."""

        edge_types = set(graph.edge_types) if graph.edge_types else None
        direction = graph.direction
        adj: Dict[str, List[str]] = {}
        for _eid, etype, src, tgt in edges:
            if edge_types is not None and etype not in edge_types:
                continue
            if direction in {"out", "both"}:
                adj.setdefault(src, []).append(tgt)
            if direction in {"in", "both"}:
                adj.setdefault(tgt, []).append(src)

        visited: Dict[str, int] = {}
        frontier = [s for s in seeds if s in allowed]
        for s in frontier:
            visited[s] = 0
        tracker.add_nodes(0)  # time check
        current = list(frontier)
        for hop in range(1, graph.max_hops + 1):
            tracker.check_time()
            nxt: List[str] = []
            for node in current:
                neighbors = adj.get(node, [])
                tracker.add_edges(len(neighbors))
                for nb in neighbors:
                    if nb not in allowed:
                        continue
                    if nb in visited:
                        continue
                    if len(visited) >= tracker.budget.max_nodes:
                        tracker.exhausted = True
                        raise DuckDBHybridSearchError(
                            "BUDGET_EXCEEDED",
                            "graph expansion hit max_nodes",
                            max_nodes=tracker.budget.max_nodes,
                        )
                    visited[nb] = hop
                    nxt.append(nb)
                    tracker.add_nodes(1)
            current = nxt
            if not current:
                break
        return visited

    def _vector_search(
        self,
        vector: VectorQuery,
        tracker: _BudgetTracker,
    ) -> Tuple[Dict[str, float], Dict[str, ExactHit], int, bool]:
        """Run exact or approx vector search; return scores, hits, gen, approx."""

        if self._exact is None and self._vss is None:
            raise DuckDBHybridSearchError(
                "VECTOR",
                "no exact vector store or VSS index bound",
            )

        # Candidate budget must leave room for at least one hit when vectors run.
        max_cand = int(tracker.budget.max_vector_candidates)
        if max_cand < 1:
            tracker.add_vector_candidates(1)  # raises BUDGET_EXCEEDED
        search_k = min(int(vector.k), max_cand)

        mode = vector.mode
        used_approx = False
        hits: List[ExactHit] = []

        if mode in (VectorMode.APPROX, VectorMode.AUTO) and self._vss is not None:
            try:
                result = self._vss.search(
                    list(vector.query_vector),
                    k=search_k,
                    metric=vector.metric,
                )
                hits = list(result.hits)
                used_approx = not bool(getattr(result, "used_fallback", True))
            except Exception as exc:
                if mode is VectorMode.APPROX and self._exact is None:
                    raise DuckDBHybridSearchError(
                        "VECTOR", f"approx search failed: {exc}"
                    ) from exc
                used_approx = False
                hits = []

        if not hits:
            if self._exact is None:
                raise DuckDBHybridSearchError(
                    "VECTOR", "exact store required for fallback/exact mode"
                )
            # Optional generation pin: ExactVectorStore binds published generation.
            if vector.generation_id is not None:
                # Verify store generation matches when caller pins it.
                try:
                    _dim, gen = self._exact._collection_dim(vector.collection_id)  # noqa: SLF001
                except ExactVectorStoreError as exc:
                    raise DuckDBHybridSearchError(
                        getattr(exc, "code", "VECTOR") or "VECTOR",
                        str(exc),
                    ) from exc
                if int(gen) != int(vector.generation_id):
                    raise DuckDBHybridSearchError(
                        "GENERATION",
                        "vector generation mismatch",
                        expected=vector.generation_id,
                        actual=int(gen),
                        collection_id=vector.collection_id,
                    )
            try:
                hits = self._exact.search(
                    vector.collection_id,
                    list(vector.query_vector),
                    k=search_k,
                    metric=vector.metric,
                )
            except ExactVectorStoreError as exc:
                raise DuckDBHybridSearchError(
                    getattr(exc, "code", "VECTOR") or "VECTOR",
                    str(exc),
                ) from exc
            used_approx = False

        tracker.add_vector_candidates(len(hits))
        scores: Dict[str, float] = {}
        hit_map: Dict[str, ExactHit] = {}
        generation_id = 0
        for hit in hits:
            sim = _distance_to_similarity(hit.distance, vector.metric)
            scores[hit.vector_id] = sim
            hit_map[hit.vector_id] = hit
            generation_id = int(hit.generation_id)
        if vector.generation_id is not None and hits:
            if generation_id != int(vector.generation_id):
                raise DuckDBHybridSearchError(
                    "GENERATION",
                    "vector generation mismatch in hits",
                    expected=vector.generation_id,
                    actual=generation_id,
                )
        return scores, hit_map, generation_id, used_approx

    def _text_scores(
        self,
        text: TextQuery,
        vertices: Mapping[str, Dict[str, Any]],
        tracker: _BudgetTracker,
    ) -> Dict[str, float]:
        scores: Dict[str, float] = {}
        for node_id, row in vertices.items():
            tracker.check_time()
            parts: List[str] = []
            for f in text.fields:
                parts.append(str(row.get(f, "") or ""))
            doc = " ".join(parts)
            scores[node_id] = text_rank_score(text.query, doc)
        return scores

    # ------------------------------------------------------------------
    # Public search
    # ------------------------------------------------------------------

    def search(self, query: HybridQuery) -> HybridSearchResponse:
        """Execute a bounded hybrid query; results bind graph + vector gens."""

        if not isinstance(query, HybridQuery):
            raise DuckDBHybridSearchError("QUERY", "query must be HybridQuery")
        budget = query.budget or self._default_budget
        tracker = _BudgetTracker(budget)

        with self._lock:
            try:
                return self._search_locked(query, budget, tracker)
            except DuckDBHybridSearchError as exc:
                if exc.code == "BUDGET_EXCEEDED":
                    # Surface a partial response only when explicitly exhausted
                    # mid-query via the exception path from callers that catch.
                    raise
                raise

    def _search_locked(
        self,
        query: HybridQuery,
        budget: HybridQueryBudget,
        tracker: _BudgetTracker,
    ) -> HybridSearchResponse:
        tracker.check_time()
        revision = query.revision
        provenance = query.provenance

        vertices = self._load_vertices(
            revision=revision, provenance=provenance, tracker=tracker
        )
        vertices = self._apply_graph_predicates(vertices, query.graph)

        edges: List[Tuple[str, str, str, str]] = []
        if query.graph is not None and query.graph.max_hops > 0:
            edges = self._load_edges(revision=revision, tracker=tracker)

        vector_scores: Dict[str, float] = {}
        vector_hits: Dict[str, ExactHit] = {}
        vector_generation_id = 0
        vector_collection_id = ""
        used_approx = False
        if query.vector is not None:
            vector_collection_id = query.vector.collection_id
            (
                vector_scores,
                vector_hits,
                vector_generation_id,
                used_approx,
            ) = self._vector_search(query.vector, tracker)
            # Restrict vector scores to graph-visible nodes when graph data exists.
            if vertices:
                vector_scores = {
                    nid: sc
                    for nid, sc in vector_scores.items()
                    if nid in vertices
                }

        text_scores: Dict[str, float] = {}
        if query.text is not None:
            text_scores = self._text_scores(query.text, vertices, tracker)

        # Seed selection for graph expansion.
        graph_hops: Dict[str, int] = {}
        if query.graph is not None:
            seeds: List[str] = []
            if query.graph.seed_node_ids:
                seeds.extend(
                    s for s in query.graph.seed_node_ids if s in vertices
                )
            if not seeds and vector_scores:
                # Top vector hits as seeds (native ids, no JSON).
                seeds = [
                    nid
                    for nid, _ in sorted(
                        vector_scores.items(),
                        key=lambda kv: (-kv[1], kv[0]),
                    )[: min(query.k * 2, len(vector_scores))]
                ]
            if not seeds and text_scores:
                seeds = [
                    nid
                    for nid, _ in sorted(
                        text_scores.items(),
                        key=lambda kv: (-kv[1], kv[0]),
                    )[: min(query.k * 2, len(text_scores))]
                    if _ > 0
                ]
            if not seeds:
                seeds = list(vertices.keys())[: budget.max_nodes]
            if query.graph.max_hops > 0 and seeds:
                graph_hops = self._expand_graph(
                    seeds, edges, query.graph, tracker, vertices
                )
            else:
                graph_hops = {s: 0 for s in seeds if s in vertices}

        # Candidate universe (native set union).
        candidate_ids = set(vector_scores) | set(text_scores) | set(graph_hops)
        if not candidate_ids and vertices:
            # Graph-only filter path: all matching vertices at hop 0.
            candidate_ids = set(vertices)
            graph_hops = {nid: 0 for nid in candidate_ids}

        # Weights
        vw = float(query.vector.weight) if query.vector is not None else 0.0
        tw = float(query.text.weight) if query.text is not None else 0.0
        gw = float(query.graph_weight) if query.graph is not None else 0.0
        # If only one modality active, give it full weight.
        active = []
        if query.vector is not None:
            active.append("v")
        if query.text is not None:
            active.append("t")
        if query.graph is not None:
            active.append("g")
        if len(active) == 1:
            if "v" in active:
                vw, tw, gw = 1.0, 0.0, 0.0
            elif "t" in active:
                vw, tw, gw = 0.0, 1.0, 0.0
            else:
                vw, tw, gw = 0.0, 0.0, 1.0
        total_w = vw + tw + gw
        if total_w <= 0:
            vw = tw = gw = 0.0
        else:
            vw, tw, gw = vw / total_w, tw / total_w, gw / total_w

        max_hop = max(graph_hops.values()) if graph_hops else 0
        hits: List[HybridHit] = []
        bound_graph_revision = ""
        bound_graph_generation = 0

        for node_id in candidate_ids:
            tracker.check_time()
            row = vertices.get(node_id)
            if row is None and node_id not in vector_scores:
                continue
            v_score = float(vector_scores.get(node_id, 0.0))
            t_score = float(text_scores.get(node_id, 0.0))
            if node_id in graph_hops:
                hop = int(graph_hops[node_id])
                g_score = 1.0 - (hop / (max_hop + 1)) if max_hop >= 0 else 1.0
            else:
                hop = 0
                g_score = 0.0
            score = vw * v_score + tw * t_score + gw * g_score

            v_hit = vector_hits.get(node_id)
            content_digest = v_hit.content_digest if v_hit else ""
            v_gen = int(v_hit.generation_id) if v_hit else vector_generation_id

            if row is not None:
                g_rev = row["graph_revision"]
                g_gen = int(row["graph_generation_id"])
                if not bound_graph_revision:
                    bound_graph_revision = g_rev
                    bound_graph_generation = g_gen
                source_cid = row["source_cid"]
                tenant = row["tenant"]
                prov_kind = row["provenance_kind"]
                node_type = row["node_type"]
                name = row["name"]
            else:
                g_rev = ""
                g_gen = 0
                source_cid = tenant = prov_kind = node_type = name = ""

            # Generation binding requirement
            if revision and revision.require_bound_generations:
                if row is not None and (not g_rev or g_gen < 1):
                    raise DuckDBHybridSearchError(
                        "GENERATION",
                        "graph generation binding missing",
                        node_id=node_id,
                    )
                if query.vector is not None and node_id in vector_scores:
                    if v_gen < 1:
                        raise DuckDBHybridSearchError(
                            "GENERATION",
                            "vector generation binding missing",
                            node_id=node_id,
                        )

            hits.append(
                HybridHit(
                    node_id=node_id,
                    score=float(score),
                    vector_score=v_score,
                    graph_score=g_score,
                    text_score=t_score,
                    hop_distance=hop,
                    graph_revision=g_rev,
                    graph_generation_id=g_gen,
                    vector_generation_id=v_gen,
                    vector_collection_id=vector_collection_id,
                    content_digest=content_digest,
                    source_cid=source_cid,
                    tenant=tenant,
                    provenance_kind=prov_kind,
                    node_type=node_type,
                    name=name,
                    used_approx_vector=used_approx and node_id in vector_scores,
                )
            )

        # Deterministic ranking: score desc, node_id asc.
        hits.sort(key=lambda h: (-h.score, h.node_id))
        # Enforce max_rows / k.
        limit = min(query.k, budget.max_rows)
        hits = hits[:limit]

        differential: Optional[DifferentialReport] = None
        if query.measure_legacy_differential:
            # Build legacy vector scores on the same candidate set.
            # Prefer similarity scores already computed (native).
            legacy_vector = dict(vector_scores)
            if not legacy_vector and text_scores:
                # Text-only: treat text scores as the "vector" channel for legacy.
                legacy_vector = dict(text_scores)
            legacy_graph = dict(graph_hops) if graph_hops else {
                h.node_id: h.hop_distance for h in hits
            }
            legacy_ranked = legacy_hybrid_fuse(
                legacy_vector,
                legacy_graph,
                vector_weight=vw if query.vector is not None else (
                    tw if query.text is not None else 0.6
                ),
                graph_weight=gw if query.graph is not None else 0.4,
                k=query.k,
            )
            # When text is active, fold text into hybrid ranking already done;
            # differential compares our top-k ids to legacy vector+graph fusion.
            differential = compare_legacy_hybrid_results(
                [h.node_id for h in hits],
                [item[0] for item in legacy_ranked],
                k=query.k,
                overlap_threshold=self._diff_overlap,
                rank_agreement_threshold=self._diff_rank,
            )

        if hits and not bound_graph_revision:
            # Prefer first hit with a revision.
            for h in hits:
                if h.graph_revision:
                    bound_graph_revision = h.graph_revision
                    bound_graph_generation = h.graph_generation_id
                    break

        tracker.check_time()
        return HybridSearchResponse(
            hits=hits,
            graph_revision=bound_graph_revision,
            graph_generation_id=bound_graph_generation,
            vector_collection_id=vector_collection_id,
            vector_generation_id=vector_generation_id,
            used_approx_vector=used_approx,
            budget=budget,
            elapsed_ms=tracker.elapsed_ms(),
            analytical_time_ms=budget.analytical_time_ms,
            reserved_control_plane_ms=budget.reserved_control_plane_ms,
            nodes_scanned=tracker.nodes_scanned,
            edges_scanned=tracker.edges_scanned,
            vector_candidates=tracker.vector_candidates,
            budget_exhausted=tracker.exhausted,
            differential=differential,
        )

    def search_simple(
        self,
        *,
        k: int = 10,
        query_vector: Optional[Sequence[float]] = None,
        collection_id: Optional[str] = None,
        text: Optional[str] = None,
        graph_revision: Optional[str] = None,
        node_types: Optional[Sequence[str]] = None,
        max_hops: int = 1,
        budget: Optional[HybridQueryBudget] = None,
    ) -> HybridSearchResponse:
        """Convenience wrapper building a :class:`HybridQuery` from kwargs."""

        vector = None
        if query_vector is not None:
            if not collection_id:
                raise DuckDBHybridSearchError(
                    "VECTOR", "collection_id required with query_vector"
                )
            vector = VectorQuery(
                collection_id=collection_id,
                query_vector=tuple(float(x) for x in query_vector),
                k=max(k * 2, k),
            )
        text_q = TextQuery(query=text) if text else None
        graph = GraphPredicate(
            node_types=tuple(node_types or ()),
            max_hops=max_hops,
        )
        revision = (
            RevisionFilter(graph_revisions=(graph_revision,))
            if graph_revision
            else RevisionFilter()
        )
        return self.search(
            HybridQuery(
                k=k,
                graph=graph,
                vector=vector,
                text=text_q,
                revision=revision,
                budget=budget,
                measure_legacy_differential=True,
            )
        )

    def result_digest(self, response: HybridSearchResponse) -> str:
        """Stable content digest over ranked ids + bound generations.

        Digests are computed from native fields with a deterministic binary
        packing — not by serializing intermediate search state as JSON.
        """

        parts: List[bytes] = [DUCKDB_HYBRID_SEARCH_SCHEMA.encode("utf-8"), b"\0"]
        parts.append(response.graph_revision.encode("utf-8"))
        parts.append(b"\0")
        parts.append(str(response.graph_generation_id).encode("ascii"))
        parts.append(b"\0")
        parts.append(response.vector_collection_id.encode("utf-8"))
        parts.append(b"\0")
        parts.append(str(response.vector_generation_id).encode("ascii"))
        parts.append(b"\0")
        for hit in response.hits:
            parts.append(hit.node_id.encode("utf-8"))
            parts.append(b"\0")
            parts.append(f"{hit.score:.12f}".encode("ascii"))
            parts.append(b"\0")
            parts.append(str(hit.graph_generation_id).encode("ascii"))
            parts.append(b"\0")
            parts.append(str(hit.vector_generation_id).encode("ascii"))
            parts.append(b"\0")
        return "sha256:" + hashlib.sha256(b"".join(parts)).hexdigest()


def create_duckdb_hybrid_search(
    path: Union[str, Path, None] = None,
    **kwargs: Any,
) -> DuckDBHybridSearch:
    """Factory matching sibling DuckDB module conventions."""

    return DuckDBHybridSearch(path, **kwargs)
