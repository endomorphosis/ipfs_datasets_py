"""Bounded remote query engine for Hugging Face GraphRAG releases (USCIR-025).

Domain-neutral orchestration that:

* resolves an immutable revision through :class:`ImmutableHubResolver`;
* fetches **only** route-justified, descriptor-verified artifacts;
* enforces explicit budgets for bytes / shards / rows / nodes / edges /
  depth / wall time;
* routes BM25 terms by lexicographic term ranges, scores vector centroids,
  exact-scores selected vector shards, hydrates final corpus hits, and
  fetches bounded adjacency pages;
* emits typed partial results on budget exhaustion (never silent truncation);
* produces credential-safe fetch traces suitable for offline replay proofs.

Public BM25/vector mode packaging remains domain-owned.  This module owns
generic budgets, routing, manifest-selected injected query analyzers,
named-field scoring, result/explain/fetch-trace contracts, and partial-result
semantics.
"""

from __future__ import annotations

import heapq
import json
import math
import time
from collections import defaultdict
from collections.abc import Callable, Mapping, MutableMapping, MutableSet, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from .bm25 import (
    DEFAULT_BM25_TOKENIZER_ID,
    bm25_term_score,
    tokenize_bm25_text,
)
from .locators import KeyLocatorIndex
from .resolver import (
    ArtifactDescriptor,
    ImmutableHubResolver,
    ResolvedArtifact,
    ResolverError,
    build_descriptor_for_bytes,
    safe_relative_path,
)
from .schema import (
    DEFAULT_CANDIDATE_CENTROIDS,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    canonical_json_dumps,
    content_sha256,
)
from .vectors import VectorShardRoute, route_vector_shards

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

TASK_ID: Final = "USCIR-025"
GOAL_ID: Final = "USCIR-G070"
QUERY_ENGINE_SCHEMA_VERSION: Final = "hf-graphrag-query-engine/v1"
QUERY_FETCH_TRACE_SCHEMA_VERSION: Final = "hf-graphrag-query-fetch-trace/v1"
QUERY_FETCH_TRACES_FIXTURE_SCHEMA: Final = "hf-graphrag-query-fetch-traces/v1"
DEFAULT_MANIFEST_NAME: Final = "manifest.json"

# Default budgets (tight enough for unit tests; callers may widen).
DEFAULT_MAX_BYTES: Final = 64 * 1024 * 1024
DEFAULT_MAX_SHARDS: Final = 64
DEFAULT_MAX_ROWS: Final = 65_536
DEFAULT_MAX_NODES: Final = 1_024
DEFAULT_MAX_EDGES: Final = 4_096
DEFAULT_MAX_DEPTH: Final = 8
DEFAULT_MAX_TIME_MS: Final = 30_000
DEFAULT_TOP_K: Final = 10
MAX_TOP_K: Final = 1_000
MAX_QUERY_TERMS: Final = 64

Bm25QueryAnalyzer = Callable[[str], Sequence[str]]

BUDGET_DIMENSIONS: Final = (
    "bytes",
    "shards",
    "rows",
    "nodes",
    "edges",
    "depth",
    "time",
)

ROUTE_REASONS: Final = frozenset(
    {
        "manifest",
        "control_plane",
        "routing_index",
        "term_range",
        "centroid_probe",
        "exact_vector_score",
        "hydrate_hit",
        "adjacency_range",
        "graph_node",
        "replay",
    }
)

ROUTE_FAMILIES: Final = frozenset(
    {
        "control_plane",
        "routing_index",
        "bm25_postings",
        "vectors",
        "corpus",
        "graph_nodes",
        "graph_adjacency",
        "graph_edges",
    }
)

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class QueryEngineError(RuntimeError):
    """Base error for bounded remote query failures."""


class UnjustifiedFetchError(QueryEngineError):
    """Raised when a fetch is attempted without a valid route justification."""


class DescriptorRequiredError(QueryEngineError):
    """Raised when a data-plane fetch lacks a verified descriptor."""


class QueryBudgetExhausted(QueryEngineError):
    """Typed budget exhaustion — never a silent truncation.

    Carries the exhausted dimension, current usage, configured limits, and any
    partial payload already materialised so callers can surface a partial
    result rather than inventing completeness.
    """

    def __init__(
        self,
        dimension: str,
        *,
        usage: Mapping[str, Any],
        limits: Mapping[str, Any],
        partial: Mapping[str, Any] | None = None,
        message: str | None = None,
    ) -> None:
        dim = str(dimension or "").strip()
        if dim not in BUDGET_DIMENSIONS:
            dim = dim or "unknown"
        self.dimension = dim
        self.usage = dict(usage)
        self.limits = dict(limits)
        self.partial = dict(partial) if partial is not None else None
        text = message or f"query budget exhausted: {dim}"
        super().__init__(text)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "dimension": self.dimension,
            "limits": dict(self.limits),
            "message": str(self),
            "usage": dict(self.usage),
        }
        if self.partial is not None:
            payload["partial"] = dict(self.partial)
        return payload


class QueryInputError(QueryEngineError):
    """Raised when query inputs or release metadata are malformed."""


class QueryIntegrityError(QueryEngineError):
    """Raised when release indexes or shards fail integrity checks."""


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise QueryInputError(f"{name} must be a positive integer")
    return value


def _non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise QueryInputError(f"{name} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class QueryLimits:
    """Hard per-query budgets covering every acceptance dimension."""

    max_bytes: int = DEFAULT_MAX_BYTES
    max_shards: int = DEFAULT_MAX_SHARDS
    max_rows: int = DEFAULT_MAX_ROWS
    max_nodes: int = DEFAULT_MAX_NODES
    max_edges: int = DEFAULT_MAX_EDGES
    max_depth: int = DEFAULT_MAX_DEPTH
    max_time_ms: int = DEFAULT_MAX_TIME_MS

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "max_bytes", _positive_int(self.max_bytes, "max_bytes")
        )
        object.__setattr__(
            self, "max_shards", _positive_int(self.max_shards, "max_shards")
        )
        object.__setattr__(self, "max_rows", _positive_int(self.max_rows, "max_rows"))
        object.__setattr__(
            self, "max_nodes", _positive_int(self.max_nodes, "max_nodes")
        )
        object.__setattr__(
            self, "max_edges", _positive_int(self.max_edges, "max_edges")
        )
        object.__setattr__(
            self, "max_depth", _non_negative_int(self.max_depth, "max_depth")
        )
        object.__setattr__(
            self,
            "max_time_ms",
            _positive_int(self.max_time_ms, "max_time_ms"),
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "max_bytes": self.max_bytes,
            "max_depth": self.max_depth,
            "max_edges": self.max_edges,
            "max_nodes": self.max_nodes,
            "max_rows": self.max_rows,
            "max_shards": self.max_shards,
            "max_time_ms": self.max_time_ms,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None = None) -> "QueryLimits":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise QueryInputError("limits must be a mapping")
        known = {
            "max_bytes",
            "max_shards",
            "max_rows",
            "max_nodes",
            "max_edges",
            "max_depth",
            "max_time_ms",
        }
        kwargs = {
            key: int(value[key])
            for key in known
            if key in value and value[key] is not None
        }
        # Accept wall-clock aliases.
        if "time_ms" in value and "max_time_ms" not in kwargs:
            kwargs["max_time_ms"] = int(value["time_ms"])
        if "timeout_ms" in value and "max_time_ms" not in kwargs:
            kwargs["max_time_ms"] = int(value["timeout_ms"])
        return cls(**kwargs)


@dataclass
class BudgetUsage:
    """Mutable consumption counters for one query session."""

    bytes: int = 0
    shards: int = 0
    rows: int = 0
    nodes: int = 0
    edges: int = 0
    depth: int = 0
    time_ms: float = 0.0
    started_at: float = field(default_factory=time.perf_counter)

    def elapsed_ms(self) -> float:
        return (time.perf_counter() - self.started_at) * 1000.0

    def snapshot(self) -> dict[str, Any]:
        return {
            "bytes": self.bytes,
            "depth": self.depth,
            "edges": self.edges,
            "nodes": self.nodes,
            "rows": self.rows,
            "shards": self.shards,
            "time_ms": round(max(self.time_ms, self.elapsed_ms()), 3),
        }

    def check(
        self,
        limits: QueryLimits,
        *,
        extra_bytes: int = 0,
        extra_shards: int = 0,
        extra_rows: int = 0,
        extra_nodes: int = 0,
        extra_edges: int = 0,
        projected_depth: int | None = None,
        partial: Mapping[str, Any] | None = None,
        raise_on_exhaustion: bool = True,
    ) -> str | None:
        """Return the exhausted dimension or raise :class:`QueryBudgetExhausted`.

        Returns ``None`` when the projected consumption still fits.
        """

        self.time_ms = self.elapsed_ms()
        checks: list[tuple[str, float | int, float | int]] = [
            ("bytes", self.bytes + extra_bytes, limits.max_bytes),
            ("shards", self.shards + extra_shards, limits.max_shards),
            ("rows", self.rows + extra_rows, limits.max_rows),
            ("nodes", self.nodes + extra_nodes, limits.max_nodes),
            ("edges", self.edges + extra_edges, limits.max_edges),
            (
                "depth",
                projected_depth if projected_depth is not None else self.depth,
                limits.max_depth,
            ),
            ("time", self.time_ms, limits.max_time_ms),
        ]
        for dimension, used, limit in checks:
            if used > limit:
                if raise_on_exhaustion:
                    raise QueryBudgetExhausted(
                        dimension,
                        usage=self.snapshot(),
                        limits=limits.to_dict(),
                        partial=partial,
                    )
                return dimension
        return None

    def charge(
        self,
        *,
        bytes_: int = 0,
        shards: int = 0,
        rows: int = 0,
        nodes: int = 0,
        edges: int = 0,
        depth: int | None = None,
    ) -> None:
        self.bytes += max(0, int(bytes_))
        self.shards += max(0, int(shards))
        self.rows += max(0, int(rows))
        self.nodes += max(0, int(nodes))
        self.edges += max(0, int(edges))
        if depth is not None:
            self.depth = max(self.depth, int(depth))
        self.time_ms = self.elapsed_ms()


# ---------------------------------------------------------------------------
# Route justification + fetch records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RouteJustification:
    """Why a specific release-relative artifact may be fetched."""

    family: str
    reason: str
    relative_path: str
    keys: tuple[str, ...] = ()
    score: float | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        family = str(self.family or "").strip().lower().replace("-", "_")
        if family not in ROUTE_FAMILIES:
            raise UnjustifiedFetchError(f"unknown route family: {self.family!r}")
        reason = str(self.reason or "").strip().lower().replace("-", "_")
        if reason not in ROUTE_REASONS:
            raise UnjustifiedFetchError(f"unknown route reason: {self.reason!r}")
        path = safe_relative_path(self.relative_path).as_posix()
        keys = tuple(str(item) for item in self.keys if str(item))
        score = self.score
        if score is not None:
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise QueryInputError("route score must be numeric")
            score = float(score)
            if not math.isfinite(score):
                raise QueryInputError("route score must be finite")
        if not isinstance(self.metadata, Mapping):
            raise QueryInputError("route metadata must be a mapping")
        object.__setattr__(self, "family", family)
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "relative_path", path)
        object.__setattr__(self, "keys", keys)
        object.__setattr__(self, "score", score)
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "family": self.family,
            "keys": list(self.keys),
            "reason": self.reason,
            "relative_path": self.relative_path,
        }
        if self.score is not None:
            payload["score"] = self.score
        if self.metadata:
            payload["metadata"] = dict(self.metadata)
        return payload


@dataclass(frozen=True, slots=True)
class JustifiedFetchRecord:
    """One descriptor-verified, route-justified artifact fetch."""

    relative_path: str
    sha256: str
    size_bytes: int
    verified: bool
    cache_hit: bool
    route: RouteJustification
    row_count: int | None = None
    duration_ms: float = 0.0
    schema_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "cache_hit": self.cache_hit,
            "duration_ms": round(self.duration_ms, 3),
            "relative_path": self.relative_path,
            "route": self.route.to_dict(),
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "verified": self.verified,
        }
        if self.row_count is not None:
            payload["row_count"] = self.row_count
        if self.schema_id:
            payload["schema_id"] = self.schema_id
        return payload


@dataclass(frozen=True, slots=True)
class QueryEngineResult:
    """Typed query result with explicit completeness and budget state."""

    mode: str
    results: tuple[dict[str, Any], ...]
    diagnostics: Mapping[str, Any]
    fetch_trace: Mapping[str, Any]
    complete: bool
    stop_reason: str | None
    usage: Mapping[str, Any]
    limits: Mapping[str, Any]
    query: str = ""
    explain: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "diagnostics", MappingProxyType(dict(self.diagnostics))
        )
        object.__setattr__(
            self, "fetch_trace", MappingProxyType(dict(self.fetch_trace))
        )
        object.__setattr__(self, "usage", MappingProxyType(dict(self.usage)))
        object.__setattr__(self, "limits", MappingProxyType(dict(self.limits)))
        object.__setattr__(self, "explain", MappingProxyType(dict(self.explain)))
        object.__setattr__(
            self,
            "results",
            tuple(dict(item) for item in self.results),
        )

    @property
    def result_count(self) -> int:
        return len(self.results)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "complete": self.complete,
            "diagnostics": dict(self.diagnostics),
            "fetch_trace": dict(self.fetch_trace),
            "limits": dict(self.limits),
            "mode": self.mode,
            "query": self.query,
            "result_count": self.result_count,
            "results": [dict(item) for item in self.results],
            "stop_reason": self.stop_reason,
            "usage": dict(self.usage),
        }
        if self.explain:
            payload["explain"] = dict(self.explain)
        return payload

    def ordered_result_cids(self) -> tuple[str, ...]:
        """Stable ordered identity list for offline replay comparison."""

        ordered: list[str] = []
        for item in self.results:
            for key in ("entry_cid", "node_cid", "edge_cid", "document_index"):
                if key in item and item[key] is not None:
                    ordered.append(str(item[key]))
                    break
        return tuple(ordered)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise QueryInputError(f"{name} must be a mapping")
    return value


def _json_value(value: Any) -> Any:
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    if hasattr(value, "tolist"):
        try:
            return value.tolist()
        except Exception:
            return value
    return value


# ---------------------------------------------------------------------------
# Domain-neutral hybrid / locator / semantic-walk primitives
# ---------------------------------------------------------------------------


FUSION_WEIGHTED: Final = "weighted"
FUSION_RRF: Final = "rrf"
FUSION_METHODS: Final = frozenset({FUSION_WEIGHTED, FUSION_RRF})
FUSION_STAGE: Final = "late"


def cosine_similarity(
    left: Sequence[float] | None,
    right: Sequence[float] | None,
) -> float:
    """Return dependency-free cosine similarity for two finite vectors.

    Invalid, empty, mismatched, or zero-norm vectors deliberately score zero.
    This is the common query-time behavior; embedding model identity remains a
    responsibility of the caller's domain adapter / remote-search client.
    """

    if left is None or right is None:
        return 0.0
    try:
        a = tuple(float(value) for value in left)
        b = tuple(float(value) for value in right)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not a or len(a) != len(b):
        return 0.0
    if not all(math.isfinite(value) for value in a + b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    left_norm = math.sqrt(sum(value * value for value in a))
    right_norm = math.sqrt(sum(value * value for value in b))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (left_norm * right_norm)))


def ranking_identity(
    hit: Mapping[str, Any],
    *,
    identity_fields: Sequence[str] = (
        "chunk_cid",
        "entry_cid",
        "node_cid",
        "document_index",
    ),
) -> str | None:
    """Return the first populated, field-qualified identity for a result hit."""

    for key in identity_fields:
        if key in hit and hit[key] is not None and hit[key] != "":
            return f"{key}:{hit[key]}"
    return None


def rankings_are_compatible(
    left: Sequence[Mapping[str, Any]],
    right: Sequence[Mapping[str, Any]],
    *,
    identity_fields: Sequence[str] = (
        "chunk_cid",
        "entry_cid",
        "node_cid",
        "document_index",
    ),
) -> bool:
    """Return whether two rankings expose at least one shared identity field."""

    def _fields(hits: Sequence[Mapping[str, Any]]) -> set[str]:
        found: set[str] = set()
        for hit in hits:
            if not isinstance(hit, Mapping):
                continue
            identity = ranking_identity(hit, identity_fields=identity_fields)
            if identity is not None:
                found.add(identity.split(":", 1)[0])
        return found

    left_fields = _fields(left)
    right_fields = _fields(right)
    if not left_fields or not right_fields:
        return True
    return bool(left_fields & right_fields)


def _finite_component_score(hit: Mapping[str, Any]) -> float:
    for key in ("normalized_score", "score"):
        raw = hit.get(key)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            continue
        score = float(raw)
        if math.isfinite(score):
            return score
    return 0.0


def _query_ranking_key(hit: Mapping[str, Any]) -> tuple[Any, ...]:
    raw_score = hit.get("score")
    if isinstance(raw_score, bool) or not isinstance(raw_score, (int, float)):
        score = float("-inf")
    else:
        score = float(raw_score)
        if not math.isfinite(score):
            score = float("-inf")
    raw_document_index = hit.get("document_index")
    document_index = (
        int(raw_document_index)
        if isinstance(raw_document_index, int)
        and not isinstance(raw_document_index, bool)
        else 2**62
    )
    return (-score, str(hit.get("entry_cid") or ""), document_index)


def normalize_late_fusion_settings(
    *,
    method: str = FUSION_WEIGHTED,
    bm25_weight: float = 0.5,
    vector_weight: float = 0.5,
    rrf_k: int = 60,
    stage: str = FUSION_STAGE,
) -> dict[str, Any]:
    """Validate and normalize ontology-free late-fusion settings."""

    normalized_method = str(method or FUSION_WEIGHTED).strip().lower()
    if normalized_method not in FUSION_METHODS:
        raise QueryInputError(f"fusion method must be one of {sorted(FUSION_METHODS)}")
    normalized_stage = str(stage or FUSION_STAGE).strip().lower()
    if normalized_stage != FUSION_STAGE:
        raise QueryInputError("hybrid fusion must be late")
    weights: list[float] = []
    for value, name in (
        (bm25_weight, "bm25_weight"),
        (vector_weight, "vector_weight"),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise QueryInputError(f"{name} must be a finite number")
        normalized = float(value)
        if not math.isfinite(normalized) or normalized < 0.0:
            raise QueryInputError(f"{name} must be a non-negative finite number")
        weights.append(normalized)
    normalized_bm25_weight, normalized_vector_weight = weights
    if (
        normalized_method == FUSION_WEIGHTED
        and normalized_bm25_weight + normalized_vector_weight <= 0
    ):
        raise QueryInputError("weighted fusion requires at least one positive weight")
    if isinstance(rrf_k, bool) or not isinstance(rrf_k, int) or rrf_k <= 0:
        raise QueryInputError("rrf_k must be a positive integer")
    if rrf_k > 10_000:
        raise QueryInputError("rrf_k exceeds hard bound 10000")
    return {
        "bm25_weight": normalized_bm25_weight,
        "method": normalized_method,
        "rrf_k": rrf_k,
        "stage": normalized_stage,
        "vector_weight": normalized_vector_weight,
    }


def late_fuse_rankings(
    bm25_hits: Sequence[Mapping[str, Any]],
    vector_hits: Sequence[Mapping[str, Any]],
    *,
    method: str = FUSION_WEIGHTED,
    bm25_weight: float = 0.5,
    vector_weight: float = 0.5,
    rrf_k: int = 60,
    top_k: int = DEFAULT_TOP_K,
    stage: str = FUSION_STAGE,
    identity_fields: Sequence[str] = (
        "chunk_cid",
        "entry_cid",
        "node_cid",
        "document_index",
    ),
) -> list[dict[str, Any]]:
    """Late-fuse lexical and vector rankings, preserving component scores.

    The primitive is intentionally ontology-free.  Legal filters and edge
    authority annotations belong to a domain adapter.
    """

    settings = normalize_late_fusion_settings(
        method=method,
        bm25_weight=bm25_weight,
        vector_weight=vector_weight,
        rrf_k=rrf_k,
        stage=stage,
    )
    normalized_method = str(settings["method"])
    bm25_weight = float(settings["bm25_weight"])
    vector_weight = float(settings["vector_weight"])
    rrf_k = int(settings["rrf_k"])
    if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
        raise QueryInputError("top_k must be a positive integer")
    if top_k > MAX_TOP_K:
        raise QueryInputError(f"top_k must be <= {MAX_TOP_K}")

    merged: dict[str, dict[str, Any]] = {}
    bm25_ranks: dict[str, int] = {}
    vector_ranks: dict[str, int] = {}

    def _merge(
        hits: Sequence[Mapping[str, Any]],
        *,
        component: str,
        ranks: MutableMapping[str, int],
    ) -> None:
        for rank, hit in enumerate(hits, start=1):
            if not isinstance(hit, Mapping):
                continue
            identity = (
                ranking_identity(hit, identity_fields=identity_fields)
                or f"row:{id(hit)}"
            )
            row = merged.setdefault(
                identity,
                {
                    "chunk_cid": hit.get("chunk_cid"),
                    "entry_cid": hit.get("entry_cid"),
                },
            )
            for field_name, value in hit.items():
                if field_name in {"score", "normalized_score"}:
                    continue
                if field_name not in row or row[field_name] in (None, ""):
                    row[field_name] = value
            row[f"{component}_score"] = _finite_component_score(hit)
            ranks[identity] = rank

    _merge(bm25_hits, component="bm25", ranks=bm25_ranks)
    _merge(vector_hits, component="vector", ranks=vector_ranks)

    fused: list[dict[str, Any]] = []
    for identity, row in merged.items():
        bm25_score = float(row.get("bm25_score") or 0.0)
        vector_score = float(row.get("vector_score") or 0.0)
        if normalized_method == FUSION_RRF:
            score = 0.0
            if identity in bm25_ranks:
                score += bm25_weight / (rrf_k + bm25_ranks[identity])
            if identity in vector_ranks:
                score += vector_weight / (rrf_k + vector_ranks[identity])
        else:
            score = (bm25_weight * bm25_score + vector_weight * vector_score) / (
                bm25_weight + vector_weight
            )
        payload = dict(row)
        payload.update(
            {
                "bm25_score": bm25_score,
                "component_scores": {
                    "bm25": bm25_score,
                    "vector": vector_score,
                },
                "fusion_method": normalized_method,
                "fusion_stage": FUSION_STAGE,
                "score": score,
                "sources": sorted(
                    {
                        *(["bm25"] if identity in bm25_ranks else []),
                        *(["vector"] if identity in vector_ranks else []),
                    }
                ),
                "vector_score": vector_score,
            }
        )
        if identity in bm25_ranks:
            payload["bm25_rank"] = bm25_ranks[identity]
        if identity in vector_ranks:
            payload["vector_rank"] = vector_ranks[identity]
        fused.append(payload)
    return sorted(fused, key=_query_ranking_key)[:top_k]


def select_entry_locator_pages_for_keys(
    meta_rows: Sequence[Mapping[str, Any]],
    keys: Sequence[str],
) -> dict[str, Mapping[str, Any]]:
    """Map keys to their inclusive lexicographic locator-page descriptors."""

    if not isinstance(meta_rows, Sequence) or isinstance(
        meta_rows, (str, bytes, bytearray)
    ):
        raise QueryInputError("meta_rows must be a sequence")
    selected: dict[str, Mapping[str, Any]] = {}
    for key in keys:
        text = str(key or "").strip()
        if not text:
            continue
        matches = [
            dict(row)
            for row in meta_rows
            if isinstance(row, Mapping)
            and str(row.get("first_key") or "")
            <= text
            <= str(row.get("last_key") or "")
        ]
        if not matches:
            continue
        matches.sort(
            key=lambda row: (
                int(row.get("shard_id", 0)),
                str(row.get("relative_path") or ""),
            )
        )
        selected[text] = matches[0]
    return selected


def parse_entry_locator_locations(
    rows: Sequence[Mapping[str, Any]],
    keys: Sequence[str],
    *,
    locator_key_fields: Sequence[str] = ("entry_cid", "key"),
) -> dict[str, list[dict[str, Any]]]:
    """Extract key-to-physical-shard locations from locator page rows."""

    wanted = {str(key).strip() for key in keys if str(key or "").strip()}
    resolved: dict[str, list[dict[str, Any]]] = {key: [] for key in wanted}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        locator_key = ""
        for field_name in locator_key_fields:
            locator_key = str(row.get(field_name) or "").strip()
            if locator_key:
                break
        if locator_key not in wanted:
            continue
        locations = row.get("locations")
        parsed: list[dict[str, Any]] = []
        if isinstance(locations, str) and locations.strip():
            try:
                loaded = json.loads(locations)
            except json.JSONDecodeError:
                loaded = None
            if isinstance(loaded, Mapping):
                loaded = [loaded]
            if isinstance(loaded, Sequence):
                locations = loaded
        if isinstance(locations, Sequence) and not isinstance(
            locations, (str, bytes, bytearray)
        ):
            parsed.extend(
                dict(item)
                for item in locations
                if isinstance(item, Mapping) and item.get("relative_path")
            )
        relative_path = str(row.get("relative_path") or "").strip()
        if relative_path:
            parsed.append(
                {
                    "cluster_id": row.get("cluster_id"),
                    "entry_cid": locator_key,
                    "global_shard_id": row.get("global_shard_id", row.get("shard_id")),
                    "relative_path": relative_path,
                    "row_offset": row.get("row_offset", 0),
                }
            )
        for item in parsed:
            if str(item.get("relative_path") or "").strip():
                resolved[locator_key].append(dict(item))
    return {key: value for key, value in resolved.items() if value}


def lexical_ranges_would_miss_keys(
    meta_rows: Sequence[Mapping[str, Any]],
    keys: Sequence[str],
    *,
    ranges_are_lexical: bool,
) -> bool:
    """Return whether non-lexical shard bounds fail to cover requested keys."""

    if ranges_are_lexical:
        return False
    hits = select_entry_locator_pages_for_keys(meta_rows, keys)
    return any(str(key).strip() and str(key).strip() not in hits for key in keys)


def descriptor_for_relative_path(
    descriptors: Sequence[Mapping[str, Any]], relative_path: str
) -> Mapping[str, Any] | None:
    """Return the first descriptor matching a relative artifact path."""

    path = str(relative_path or "")
    return next(
        (row for row in descriptors if str(row.get("relative_path") or "") == path),
        None,
    )


def route_centroid_paths(
    engine: Any,
    query_vector: Sequence[float],
    *,
    candidate_centroids: int,
) -> set[str]:
    """Route evaluated centroids and return their physical vector paths."""

    routes = engine.route_vector_centroids(
        query_vector, candidate_centroids=candidate_centroids
    )
    return {str(route.relative_path) for route in routes}


def bounded_edge_weight(
    edge: Mapping[str, Any],
    *,
    authoritative_default: bool,
) -> float:
    """Normalize a graph-edge score to ``[0, 1]`` with a typed default."""

    raw = edge.get("score")
    if raw is None:
        raw = edge.get("weight")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return 1.0 if authoritative_default else 0.5
    score = float(raw)
    if not math.isfinite(score):
        return 1.0 if authoritative_default else 0.5
    return max(0.0, min(1.0, score))


def normalize_semantic_beam_settings(
    *,
    max_depth: int,
    max_nodes: int | None,
    max_edges: int | None,
    per_node_limit: int,
    beam_width: int,
    proximity_weight: float,
    edge_weight: float,
    path_penalty: float,
    candidate_centroids: int,
) -> dict[str, Any]:
    """Validate and normalize domain-neutral semantic beam settings."""

    def _positive(value: Any, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise QueryInputError(f"{name} must be a positive integer")
        return value

    if isinstance(max_depth, bool) or not isinstance(max_depth, int) or max_depth < 0:
        raise QueryInputError("max_depth must be a non-negative integer")
    normalized: dict[str, Any] = {
        "beam_width": _positive(beam_width, "beam_width"),
        "candidate_centroids": _positive(candidate_centroids, "candidate_centroids"),
        "max_depth": max_depth,
        "max_edges": None if max_edges is None else _positive(max_edges, "max_edges"),
        "max_nodes": None if max_nodes is None else _positive(max_nodes, "max_nodes"),
        "per_node_limit": _positive(per_node_limit, "per_node_limit"),
    }
    for value, name in (
        (proximity_weight, "proximity_weight"),
        (edge_weight, "edge_weight"),
        (path_penalty, "path_penalty"),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise QueryInputError(f"{name} must be a finite number")
        number = float(value)
        if not math.isfinite(number) or number < 0.0:
            raise QueryInputError(f"{name} must be a non-negative finite number")
        normalized[name] = number
    if (
        normalized["proximity_weight"]
        + normalized["edge_weight"]
        + normalized["path_penalty"]
        <= 0.0
    ):
        raise QueryInputError(
            "semantic beam requires at least one positive blend weight"
        )
    return normalized


def hydrate_frontier_vectors(
    engine: Any,
    node_keys: Sequence[str],
    *,
    vector_cache: MutableMapping[str, tuple[float, ...]],
    vector_descriptors: Sequence[Mapping[str, Any]],
    locator_meta_rows: Sequence[Mapping[str, Any]],
    centroid_routed_paths: set[str],
    locator_page_paths: MutableSet[str],
    frontier_fetch_paths: MutableSet[str],
    off_centroid_fetch_paths: MutableSet[str],
    locator_key: str = "entry_cid",
    frontier_policy: str = "entry_locator",
    vector_shard_keys_are_lexical_ranges: bool = False,
    vector_key_fields: Sequence[str] = ("entry_cid", "node_cid", "chunk_cid"),
    descriptor_error: Callable[[str], Exception] = QueryIntegrityError,
) -> dict[str, tuple[float, ...]]:
    """Hydrate graph-frontier embeddings only through a locator index.

    The caller supplies tracking sets so diagnostics remain adapter-owned.
    No edge ontology, legal filtering, or release policy is embedded here.
    """

    requested = [str(key).strip() for key in node_keys if str(key or "").strip()]
    wanted = [key for key in requested if key not in vector_cache]
    if not wanted:
        return {key: vector_cache[key] for key in requested if key in vector_cache}

    key_to_page = select_entry_locator_pages_for_keys(locator_meta_rows, wanted)
    pages_by_path: dict[str, list[str]] = defaultdict(list)
    page_descriptors: dict[str, Mapping[str, Any]] = {}
    for key, descriptor in key_to_page.items():
        path = str(descriptor.get("relative_path") or "")
        if path:
            pages_by_path[path].append(key)
            page_descriptors[path] = descriptor

    locations_by_key: dict[str, list[dict[str, Any]]] = {}
    for path, keys in sorted(pages_by_path.items()):
        descriptor = page_descriptors[path]
        locator_page_paths.add(path)
        route = RouteJustification(
            family="routing_index",
            reason="hydrate_hit",
            relative_path=path,
            keys=tuple(sorted(keys)),
            metadata={
                "fetch_policy": frontier_policy,
                "locator_key": locator_key,
                "shard_id": descriptor.get("shard_id"),
                "vector_shard_keys_are_lexical_ranges": (
                    vector_shard_keys_are_lexical_ranges
                ),
            },
        )
        try:
            artifact = engine.fetch(
                path,
                route=route,
                descriptor=descriptor,
                charge_shard=True,
                charge_rows=int(descriptor.get("row_count") or 0),
            )
        except QueryBudgetExhausted as exc:
            engine._stop_reason = exc.dimension
            break
        rows = engine._read_rows(artifact, descriptor=descriptor)
        parsed = parse_entry_locator_locations(
            rows,
            keys,
            locator_key_fields=(locator_key, "entry_cid", "key"),
        )
        for key, locations in parsed.items():
            locations_by_key.setdefault(key, []).extend(locations)

    keys_by_vector_path: dict[str, list[str]] = defaultdict(list)
    for key, locations in locations_by_key.items():
        for location in locations:
            path = str(location.get("relative_path") or "")
            if path:
                keys_by_vector_path[path].append(key)

    for path, keys in sorted(keys_by_vector_path.items()):
        descriptor = descriptor_for_relative_path(vector_descriptors, path)
        if descriptor is None:
            raise descriptor_error(
                f"entry locator pointed at unknown vector shard {path}"
            )
        off_centroid = path not in centroid_routed_paths
        frontier_fetch_paths.add(path)
        if off_centroid:
            off_centroid_fetch_paths.add(path)
        route = RouteJustification(
            family="vectors",
            reason="exact_vector_score",
            relative_path=path,
            keys=tuple(sorted(set(keys))),
            metadata={
                "fetch_policy": frontier_policy,
                "locator_key": locator_key,
                "off_centroid": off_centroid,
                "shard_id": descriptor.get("shard_id"),
                "vector_shard_keys_are_lexical_ranges": (
                    vector_shard_keys_are_lexical_ranges
                ),
            },
        )
        try:
            artifact = engine.fetch(
                path,
                route=route,
                descriptor=descriptor,
                charge_shard=True,
                charge_rows=int(descriptor.get("row_count") or 0),
            )
        except QueryBudgetExhausted as exc:
            engine._stop_reason = exc.dimension
            break
        rows = engine._read_rows(artifact, descriptor=descriptor)
        wanted_set = set(keys)
        for row in rows:
            matched_key = ""
            for field_name in vector_key_fields:
                candidate = str(row.get(field_name) or "")
                if candidate in wanted_set:
                    matched_key = candidate
                    break
            if not matched_key:
                continue
            embedding = row.get("embedding")
            if embedding is None:
                continue
            try:
                vector = tuple(float(value) for value in embedding)
            except (TypeError, ValueError, OverflowError):
                continue
            vector_cache[matched_key] = vector
            engine.usage.charge(rows=1)

    return {key: vector_cache[key] for key in requested if key in vector_cache}


@dataclass(frozen=True, slots=True)
class SemanticBeamWalkResult:
    """Domain-neutral materialized result of a bounded semantic beam walk."""

    nodes: tuple[dict[str, Any], ...]
    edges: tuple[dict[str, Any], ...]
    stop_reason: str | None
    depth_limit: int
    node_limit: int
    edge_limit: int
    beam_width: int

    @property
    def complete(self) -> bool:
        return self.stop_reason is None


def semantic_beam_walk(
    engine: Any,
    start_node_key: str,
    query_vector: Sequence[float],
    *,
    vector_cache: Mapping[str, Sequence[float]],
    fetch_frontier_vectors: Callable[[Sequence[str]], Mapping[str, Sequence[float]]],
    annotate_edge: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    is_similarity_edge: Callable[[str], bool],
    is_authoritative_edge: Callable[[str], bool],
    max_depth: int,
    max_nodes: int | None,
    max_edges: int | None,
    per_node_limit: int,
    beam_width: int,
    proximity_weight: float,
    edge_weight: float,
    path_penalty: float,
    direction: str = "out",
    wanted_edge_types: Sequence[str] = (),
    include_similarity: bool = True,
) -> SemanticBeamWalkResult:
    """Run an embedding-guided bounded graph walk using adapter callbacks."""

    depth_limit = min(max_depth, engine.limits.max_depth)
    node_limit = min(max_nodes or engine.limits.max_nodes, engine.limits.max_nodes)
    edge_limit = min(max_edges or engine.limits.max_edges, engine.limits.max_edges)
    effective_beam_width = min(beam_width, node_limit)
    wanted_types = {
        str(value).strip() for value in wanted_edge_types if str(value).strip()
    }
    total_weight = proximity_weight + edge_weight + path_penalty

    engine.usage.charge(nodes=1, depth=0)
    fetch_frontier_vectors([start_node_key])
    seed_embedding = vector_cache.get(start_node_key)
    seed_proximity = cosine_similarity(seed_embedding, query_vector)
    seed_score = (
        proximity_weight * max(0.0, seed_proximity) + edge_weight + path_penalty
    ) / total_weight
    visited: dict[str, dict[str, Any]] = {
        start_node_key: {
            "depth": 0,
            "edge_weight": 1.0,
            "edge_type": None,
            "from_node_cid": None,
            "has_embedding": seed_embedding is not None,
            "node_cid": start_node_key,
            "score": seed_score,
            "semantic_proximity": seed_proximity,
        }
    }
    traversed: list[dict[str, Any]] = []
    frontier = [start_node_key]
    stop_reason: str | None = "depth" if depth_limit == 0 else None

    try:
        for depth in range(depth_limit):
            projected_depth = depth + 1
            exhausted = engine.usage.check(
                engine.limits,
                projected_depth=projected_depth,
                raise_on_exhaustion=False,
            )
            if exhausted is not None:
                stop_reason = exhausted
                break
            candidates: list[tuple[float, str, dict[str, Any], dict[str, Any]]] = []
            for node_key in frontier:
                try:
                    edges = engine.fetch_adjacency(
                        node_key,
                        direction=direction,
                        limit=per_node_limit,
                        edge_types=tuple(sorted(wanted_types)) if wanted_types else (),
                    )
                except QueryBudgetExhausted as exc:
                    stop_reason = exc.dimension
                    frontier = []
                    break
                if engine._stop_reason is not None:
                    stop_reason = engine._stop_reason
                    frontier = []
                    break
                neighbor_keys = [
                    str(edge.get("neighbor_cid") or "")
                    for edge in edges
                    if edge.get("neighbor_cid")
                ]
                if neighbor_keys:
                    fetch_frontier_vectors(neighbor_keys)
                if engine._stop_reason is not None:
                    stop_reason = engine._stop_reason
                    frontier = []
                    break
                for edge in edges:
                    neighbor = str(edge.get("neighbor_cid") or "")
                    if not neighbor:
                        continue
                    edge_type = str(edge.get("edge_type") or "")
                    if not include_similarity and is_similarity_edge(edge_type):
                        continue
                    if wanted_types and edge_type not in wanted_types:
                        continue
                    embedding = vector_cache.get(neighbor)
                    proximity = cosine_similarity(embedding, query_vector)
                    normalized_proximity = (proximity + 1.0) / 2.0
                    normalized_edge_weight = bounded_edge_weight(
                        edge,
                        authoritative_default=is_authoritative_edge(edge_type),
                    )
                    depth_factor = 1.0 / (1.0 + projected_depth)
                    score = (
                        proximity_weight * normalized_proximity
                        + edge_weight * normalized_edge_weight
                        + path_penalty * depth_factor
                    ) / total_weight
                    annotated = dict(
                        annotate_edge(
                            {
                                **edge,
                                "depth": projected_depth,
                                "from_node_cid": node_key,
                                "semantic_proximity": proximity,
                                "semantic_score": score,
                            }
                        )
                    )
                    candidates.append(
                        (
                            score,
                            neighbor,
                            {
                                "depth": projected_depth,
                                "edge_weight": normalized_edge_weight,
                                "edge_type": edge_type,
                                "from_node_cid": node_key,
                                "has_embedding": embedding is not None,
                                "node_cid": neighbor,
                                "score": score,
                                "semantic_proximity": proximity,
                            },
                            annotated,
                        )
                    )
            if stop_reason is not None:
                break
            candidates.sort(
                key=lambda item: (
                    -item[0],
                    item[1],
                    str(item[3].get("edge_cid") or ""),
                )
            )
            next_frontier: list[str] = []
            for score, neighbor, node_payload, edge_payload in candidates:
                if len(traversed) >= edge_limit:
                    stop_reason = "edges"
                    break
                if neighbor not in visited:
                    if len(visited) >= node_limit:
                        stop_reason = "nodes"
                        break
                    visited[neighbor] = node_payload
                    next_frontier.append(neighbor)
                    engine.usage.charge(nodes=1, depth=projected_depth)
                elif score > float(visited[neighbor].get("score") or 0.0):
                    visited[neighbor] = {**visited[neighbor], **node_payload}
                traversed.append(edge_payload)
                if len(next_frontier) >= effective_beam_width:
                    break
            if stop_reason is not None:
                break
            frontier = next_frontier[:effective_beam_width]
            if not frontier:
                stop_reason = None
                break
            engine.usage.charge(depth=projected_depth)
        else:
            if stop_reason is None and depth_limit > 0 and frontier:
                stop_reason = "depth"
    except QueryBudgetExhausted as exc:
        stop_reason = exc.dimension

    nodes = tuple(
        dict(payload)
        for _, payload in sorted(
            visited.items(),
            key=lambda item: (
                int(item[1].get("depth") or 0),
                -float(item[1].get("score") or 0.0),
                item[0],
            ),
        )
    )
    return SemanticBeamWalkResult(
        nodes=nodes,
        edges=tuple(traversed),
        stop_reason=stop_reason,
        depth_limit=depth_limit,
        node_limit=node_limit,
        edge_limit=edge_limit,
        beam_width=effective_beam_width,
    )


def _pyarrow() -> tuple[Any, Any]:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise QueryEngineError(
            "pyarrow is required for bounded remote query parquet reads"
        ) from exc
    return pa, pq


def select_term_range_shards(
    meta_rows: Sequence[Mapping[str, Any]],
    terms: Sequence[str],
) -> dict[str, Mapping[str, Any]]:
    """Map each query term to its inclusive term-range posting shard.

    Overlapping ranges fail closed.  Terms with no covering range are omitted
    (absent terms contribute zero score, matching BM25 semantics).
    """

    if not isinstance(meta_rows, Sequence) or isinstance(
        meta_rows, (str, bytes, bytearray)
    ):
        raise QueryInputError("meta_rows must be a sequence")
    selected: dict[str, Mapping[str, Any]] = {}
    for term in terms:
        token = str(term)
        if not token:
            continue
        matches = [
            row
            for row in meta_rows
            if isinstance(row, Mapping)
            and str(row.get("first_key") or "")
            <= token
            <= str(row.get("last_key") or "")
        ]
        if len(matches) > 1:
            raise QueryIntegrityError(
                f"overlapping BM25 term-range shards for {token!r}"
            )
        if matches:
            selected[token] = dict(matches[0])
    return selected


def select_adjacency_shards(
    meta_rows: Sequence[Mapping[str, Any]],
    node_cid: str,
) -> tuple[Mapping[str, Any], ...]:
    """Return ordered adjacency-page descriptors covering *node_cid*."""

    key = str(node_cid or "").strip()
    if not key:
        raise QueryInputError("node_cid must be a non-empty string")
    matches = [
        dict(row)
        for row in meta_rows
        if isinstance(row, Mapping)
        and str(row.get("first_key") or "") <= key <= str(row.get("last_key") or "")
    ]
    matches.sort(
        key=lambda row: (
            int(row.get("shard_id", 0)),
            str(row.get("relative_path") or ""),
        )
    )
    return tuple(matches)


def select_document_index_shards(
    meta_rows: Sequence[Mapping[str, Any]],
    document_indexes: Sequence[int],
) -> dict[int, Mapping[str, Any]]:
    """Map each document index to its corpus shard descriptor."""

    selected: dict[int, Mapping[str, Any]] = {}
    for document_index in document_indexes:
        doc_id = int(document_index)
        matches = [
            row
            for row in meta_rows
            if isinstance(row, Mapping)
            and int(row.get("start_document_index", -1))
            <= doc_id
            <= int(row.get("end_document_index", -1))
        ]
        if len(matches) > 1:
            raise QueryIntegrityError(
                f"overlapping corpus ranges for document_index={doc_id}"
            )
        if not matches:
            raise QueryIntegrityError(
                f"no corpus shard contains document_index={doc_id}"
            )
        selected[doc_id] = dict(matches[0])
    return selected


def replay_fingerprint(result: QueryEngineResult | Mapping[str, Any]) -> str:
    """Stable digest over ordered result identities and stop semantics.

    Omits wall-clock timings, absolute paths, and per-session fetch-trace
    cardinality (warm caches may skip re-recording control-plane routes) so
    offline replay of a pinned revision yields the same fingerprint.
    """

    if isinstance(result, QueryEngineResult):
        payload = {
            "complete": result.complete,
            "mode": result.mode,
            "ordered_result_cids": list(result.ordered_result_cids()),
            "query": result.query,
            "result_count": result.result_count,
            "stop_reason": result.stop_reason,
        }
    else:
        mapping = _require_mapping(result, "result")
        payload = {
            "complete": bool(mapping.get("complete")),
            "mode": mapping.get("mode"),
            "ordered_result_cids": list(mapping.get("ordered_result_cids") or []),
            "query": mapping.get("query"),
            "result_count": mapping.get("result_count"),
            "stop_reason": mapping.get("stop_reason"),
        }
    return content_sha256(canonical_json_dumps(payload))


@dataclass(frozen=True, slots=True)
class _ExactBm25FieldProfile:
    """Validated manifest contract for exact named-field BM25 scoring."""

    fields: tuple[str, ...]
    field_weights: Mapping[str, float]
    average_field_lengths: Mapping[str, float]
    title_fields: tuple[str, ...]
    body_fields: tuple[str, ...]
    exact_field_prefix: str


def _exact_bm25_field_profile(
    config: Mapping[str, Any],
) -> _ExactBm25FieldProfile | None:
    projection = config.get("query_field_projection")
    if projection is None:
        return None
    if not isinstance(projection, Mapping):
        raise QueryIntegrityError("bm25.query_field_projection must be a mapping")
    exact_lengths = projection.get("exact_field_lengths", False)
    if not isinstance(exact_lengths, bool):
        raise QueryIntegrityError(
            "bm25.query_field_projection.exact_field_lengths must be a boolean"
        )
    if not exact_lengths:
        return None

    def string_tuple(value: Any, name: str) -> tuple[str, ...]:
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            raise QueryIntegrityError(f"{name} must be a string sequence")
        result = tuple(str(item or "").strip() for item in value)
        if (
            not result
            or any(not item for item in result)
            or len(set(result)) != len(result)
        ):
            raise QueryIntegrityError(f"{name} must be non-empty and unique")
        return result

    fields = string_tuple(config.get("fields"), "bm25.fields")
    title_fields = string_tuple(
        projection.get("title_frequencies"),
        "bm25.query_field_projection.title_frequencies",
    )
    body_fields = string_tuple(
        projection.get("body_frequencies"),
        "bm25.query_field_projection.body_frequencies",
    )
    projected_fields = set(title_fields) | set(body_fields)
    if set(title_fields) & set(body_fields) or projected_fields != set(fields):
        raise QueryIntegrityError(
            "BM25 title/body projections must partition the exact fields"
        )
    prefix = str(projection.get("exact_field_prefix") or "").strip()
    if not prefix:
        raise QueryIntegrityError(
            "bm25.query_field_projection.exact_field_prefix must be non-empty"
        )

    raw_weights = config.get("field_weights")
    raw_averages = config.get("average_field_lengths")
    if not isinstance(raw_weights, Mapping):
        raise QueryIntegrityError("bm25.field_weights must be a mapping")
    if not isinstance(raw_averages, Mapping):
        raise QueryIntegrityError("bm25.average_field_lengths must be a mapping")
    if set(raw_weights) != set(fields):
        raise QueryIntegrityError("bm25.field_weights must exactly cover bm25.fields")
    if set(raw_averages) != set(fields):
        raise QueryIntegrityError(
            "bm25.average_field_lengths must exactly cover bm25.fields"
        )
    weights: dict[str, float] = {}
    averages: dict[str, float] = {}
    for field_name in fields:
        raw_weight = raw_weights[field_name]
        raw_average = raw_averages[field_name]
        if isinstance(raw_weight, bool) or isinstance(raw_average, bool):
            raise QueryIntegrityError("BM25 field statistics must be numeric")
        try:
            weight = float(raw_weight)
            average = float(raw_average)
        except (TypeError, ValueError) as exc:
            raise QueryIntegrityError("BM25 field statistics must be numeric") from exc
        if not math.isfinite(weight) or weight <= 0.0:
            raise QueryIntegrityError("BM25 field weights must be positive and finite")
        if not math.isfinite(average) or average < 0.0:
            raise QueryIntegrityError(
                "BM25 average field lengths must be non-negative and finite"
            )
        weights[field_name] = weight
        averages[field_name] = average
    return _ExactBm25FieldProfile(
        fields=fields,
        field_weights=MappingProxyType(weights),
        average_field_lengths=MappingProxyType(averages),
        title_fields=title_fields,
        body_fields=body_fields,
        exact_field_prefix=prefix,
    )


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class BoundedRemoteQueryEngine:
    """Route-justified, descriptor-verified, budgeted remote query orchestrator.

    Parameters
    ----------
    resolver:
        Pinned :class:`ImmutableHubResolver` (immutable revision required).
    limits:
        Per-query budgets.  Defaults cover all seven acceptance dimensions.
    manifest_path:
        Release-relative manifest path (default ``manifest.json``).
    require_descriptors:
        When true (default), every data-plane fetch requires a descriptor.
    bm25_query_analyzers:
        Optional tokenizer-id keyed query analyzers.  A release can require
        one through ``bm25.query_analyzer`` without coupling this shared
        engine to a domain-specific tokenizer implementation.
    """

    def __init__(
        self,
        resolver: ImmutableHubResolver,
        *,
        limits: QueryLimits | Mapping[str, Any] | None = None,
        manifest_path: str = DEFAULT_MANIFEST_NAME,
        require_descriptors: bool = True,
        bm25_query_analyzers: Mapping[str, Bm25QueryAnalyzer] | None = None,
    ) -> None:
        if not isinstance(resolver, ImmutableHubResolver):
            raise QueryInputError("resolver must be an ImmutableHubResolver instance")
        self.resolver = resolver
        self.limits = (
            limits
            if isinstance(limits, QueryLimits)
            else QueryLimits.from_mapping(limits)
        )
        self.manifest_path = safe_relative_path(manifest_path).as_posix()
        self.require_descriptors = bool(require_descriptors)
        self.usage = BudgetUsage()
        self._justified: list[JustifiedFetchRecord] = []
        self._manifest: dict[str, Any] | None = None
        self._index_cache: dict[str, list[dict[str, Any]]] = {}
        self._row_cache: dict[str, list[dict[str, Any]]] = {}
        self._parquet_cache: dict[str, Any] = {}
        self._stop_reason: str | None = None
        self._bm25_query_analyzers: dict[str, Bm25QueryAnalyzer] = {}
        if bm25_query_analyzers is not None:
            self.register_bm25_query_analyzers(bm25_query_analyzers)

    def register_bm25_query_analyzers(
        self,
        analyzers: Mapping[str, Bm25QueryAnalyzer],
    ) -> None:
        """Register injected query analyzers by their manifest tokenizer ID."""

        if not isinstance(analyzers, Mapping):
            raise QueryInputError("bm25_query_analyzers must be a mapping")
        normalized: dict[str, Bm25QueryAnalyzer] = {}
        for raw_id, analyzer in analyzers.items():
            tokenizer_id = str(raw_id or "").strip()
            if not tokenizer_id:
                raise QueryInputError("BM25 query analyzer IDs must be non-empty")
            if not callable(analyzer):
                raise QueryInputError(
                    f"BM25 query analyzer {tokenizer_id!r} must be callable"
                )
            normalized[tokenizer_id] = analyzer
        self._bm25_query_analyzers.update(normalized)

    def _resolve_bm25_query_analyzer(
        self,
        config: Mapping[str, Any],
    ) -> tuple[str, Bm25QueryAnalyzer, bool]:
        """Resolve the manifest tokenizer to an injected analyzer or fallback."""

        tokenizer_id = str(
            config.get("tokenizer") or DEFAULT_BM25_TOKENIZER_ID
        ).strip()
        if not tokenizer_id:
            raise QueryIntegrityError("bm25.tokenizer must be non-empty")
        analyzer_contract = config.get("query_analyzer")
        required = False
        if analyzer_contract is not None:
            if not isinstance(analyzer_contract, Mapping):
                raise QueryIntegrityError("bm25.query_analyzer must be a mapping")
            declared_id = str(
                analyzer_contract.get("tokenizer_id") or tokenizer_id
            ).strip()
            if not declared_id:
                raise QueryIntegrityError(
                    "bm25.query_analyzer.tokenizer_id must be non-empty"
                )
            if declared_id != tokenizer_id:
                raise QueryIntegrityError(
                    "bm25.query_analyzer.tokenizer_id does not match bm25.tokenizer"
                )
            required_value = analyzer_contract.get("required", False)
            if not isinstance(required_value, bool):
                raise QueryIntegrityError(
                    "bm25.query_analyzer.required must be a boolean"
                )
            required = required_value

        analyzer = self._bm25_query_analyzers.get(tokenizer_id)
        if analyzer is not None:
            return tokenizer_id, analyzer, True
        if required:
            raise QueryIntegrityError(
                "release requires an injected BM25 query analyzer for "
                f"tokenizer {tokenizer_id!r}"
            )
        return DEFAULT_BM25_TOKENIZER_ID, tokenize_bm25_text, False

    @staticmethod
    def _analyze_bm25_query(
        query: str,
        *,
        tokenizer_id: str,
        analyzer: Bm25QueryAnalyzer,
    ) -> list[str]:
        try:
            analyzed = analyzer(query)
        except Exception as exc:
            raise QueryInputError(
                f"BM25 query analyzer {tokenizer_id!r} rejected the query"
            ) from exc
        if isinstance(analyzed, (str, bytes)) or not isinstance(analyzed, Sequence):
            raise QueryIntegrityError(
                f"BM25 query analyzer {tokenizer_id!r} must return a term sequence"
            )
        ordered_terms: list[str] = []
        seen: set[str] = set()
        for raw_term in analyzed:
            if not isinstance(raw_term, str):
                raise QueryIntegrityError(
                    f"BM25 query analyzer {tokenizer_id!r} returned a non-string term"
                )
            term = raw_term.strip()
            if not term or term in seen:
                continue
            seen.add(term)
            ordered_terms.append(term)
            if len(ordered_terms) >= MAX_QUERY_TERMS:
                break
        return ordered_terms

    # -- session control ----------------------------------------------------

    def reset_session(
        self,
        *,
        limits: QueryLimits | Mapping[str, Any] | None = None,
        keep_manifest: bool = True,
    ) -> None:
        """Start a fresh budget/trace session (optional limit override)."""

        if limits is not None:
            self.limits = (
                limits
                if isinstance(limits, QueryLimits)
                else QueryLimits.from_mapping(limits)
            )
        self.usage = BudgetUsage()
        self._justified.clear()
        self._stop_reason = None
        if not keep_manifest:
            self._manifest = None
            self._index_cache.clear()
            self._row_cache.clear()
            self._parquet_cache.clear()

    # -- justified fetch core -----------------------------------------------

    def fetch(
        self,
        relative_path: str,
        *,
        route: RouteJustification | Mapping[str, Any],
        descriptor: ArtifactDescriptor | Mapping[str, Any] | None = None,
        charge_shard: bool = True,
        charge_rows: int | None = None,
        raise_on_budget: bool = True,
    ) -> ResolvedArtifact:
        """Fetch one artifact only when route-justified and descriptor-verified.

        Control-plane fetches (manifest / routing indexes) still require a
        route justification.  Data-plane families require a descriptor when
        ``require_descriptors`` is true.
        """

        path = safe_relative_path(relative_path).as_posix()
        justification = (
            route
            if isinstance(route, RouteJustification)
            else RouteJustification(
                family=str(route.get("family") or ""),
                reason=str(route.get("reason") or ""),
                relative_path=str(route.get("relative_path") or path),
                keys=tuple(route.get("keys") or ()),
                score=route.get("score"),
                metadata=route.get("metadata") or {},
            )
        )
        if justification.relative_path != path:
            raise UnjustifiedFetchError(
                f"route path {justification.relative_path!r} does not match "
                f"fetch path {path!r}"
            )

        is_control = justification.family in {"control_plane", "routing_index"}
        if self.require_descriptors and descriptor is None and not is_control:
            # Control plane may bootstrap without a pre-known descriptor when
            # the transport is a trusted offline fixture; data plane never may.
            raise DescriptorRequiredError(
                f"descriptor required for data-plane fetch: {path}"
            )

        desc: ArtifactDescriptor | None
        if descriptor is None:
            desc = None
        elif isinstance(descriptor, ArtifactDescriptor):
            desc = descriptor
        else:
            desc = ArtifactDescriptor.from_mapping(descriptor)

        extra_bytes = int(desc.size_bytes) if desc is not None else 0
        exhausted = self.usage.check(
            self.limits,
            extra_bytes=extra_bytes,
            extra_shards=1 if charge_shard else 0,
            extra_rows=int(charge_rows or 0),
            raise_on_exhaustion=raise_on_budget,
        )
        if exhausted is not None:
            self._stop_reason = exhausted
            raise QueryBudgetExhausted(
                exhausted,
                usage=self.usage.snapshot(),
                limits=self.limits.to_dict(),
            )

        try:
            artifact = self.resolver.resolve(path, descriptor=desc)
        except ResolverError as exc:
            raise QueryIntegrityError(
                f"descriptor verification or fetch failed for {path}: {exc}"
            ) from exc

        if not artifact.verified:
            raise QueryIntegrityError(f"artifact was not verified: {path}")

        rows = (
            charge_rows
            if charge_rows is not None
            else (artifact.row_count if artifact.row_count is not None else 0)
        )
        self.usage.charge(
            bytes_=artifact.size_bytes,
            shards=1 if charge_shard else 0,
            rows=int(rows or 0),
        )
        record = JustifiedFetchRecord(
            relative_path=artifact.relative_path,
            sha256=artifact.sha256,
            size_bytes=artifact.size_bytes,
            verified=artifact.verified,
            cache_hit=artifact.cache_hit,
            route=justification,
            row_count=artifact.row_count,
            duration_ms=artifact.duration_ms,
            schema_id=artifact.schema_id,
        )
        self._justified.append(record)
        return artifact

    def fetch_trace(self) -> dict[str, Any]:
        """Credential-safe justified fetch trace for this session."""

        files = [record.to_dict() for record in self._justified]
        files.sort(
            key=lambda item: (
                str(item.get("relative_path") or ""),
                str((item.get("route") or {}).get("reason") or ""),
            )
        )
        total_bytes = sum(int(item.get("size_bytes") or 0) for item in files)
        cache_hits = sum(1 for item in files if item.get("cache_hit"))
        unjustified = [
            item for item in files if not item.get("route") or not item.get("verified")
        ]
        trace: dict[str, Any] = {
            "budget_usage": self.usage.snapshot(),
            "cache_hits": cache_hits,
            "file_count": len(files),
            "files": files,
            "limits": self.limits.to_dict(),
            "query_engine_schema_version": QUERY_ENGINE_SCHEMA_VERSION,
            "repo_id": self.resolver.repo_id,
            "revision": self.resolver.revision,
            "route_justified": len(unjustified) == 0,
            "schema_version": QUERY_FETCH_TRACE_SCHEMA_VERSION,
            "stop_reason": self._stop_reason,
            "total_file_bytes": total_bytes,
            "verification_state": (
                "verified"
                if files and not unjustified
                else ("empty" if not files else "unverified")
            ),
        }
        # Merge resolver-level trace metadata without absolute paths.
        try:
            resolver_trace = self.resolver.fetch_trace()
        except Exception:
            resolver_trace = {}
        if resolver_trace.get("manifest_schema_version"):
            trace["manifest_schema_version"] = resolver_trace["manifest_schema_version"]
        return trace

    # -- control plane ------------------------------------------------------

    def load_manifest(
        self,
        *,
        descriptor: ArtifactDescriptor | Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Load and cache the release manifest via a justified control fetch."""

        if self._manifest is not None:
            return dict(self._manifest)
        route = RouteJustification(
            family="control_plane",
            reason="manifest",
            relative_path=self.manifest_path,
            keys=(),
        )
        artifact = self.fetch(
            self.manifest_path,
            route=route,
            descriptor=descriptor,
            charge_shard=True,
            charge_rows=0,
        )
        try:
            payload = json.loads(artifact.path.read_bytes().decode("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise QueryIntegrityError(
                f"manifest is not valid JSON: {self.manifest_path}"
            ) from exc
        if not isinstance(payload, Mapping):
            raise QueryIntegrityError("manifest must be a JSON object")
        schema_version = payload.get("schema_version") or payload.get("release_profile")
        if not isinstance(schema_version, str) or not schema_version.strip():
            raise QueryIntegrityError("manifest is missing schema_version")
        primary_key = payload.get("primary_key")
        if primary_key is not None and primary_key != "entry_cid":
            raise QueryIntegrityError(
                "manifest primary_key must be 'entry_cid' when provided"
            )
        self._manifest = dict(payload)
        return dict(self._manifest)

    def _manifest_required(self) -> dict[str, Any]:
        if self._manifest is None:
            return self.load_manifest()
        return dict(self._manifest)

    def _index_descriptor(self, name: str) -> dict[str, Any]:
        manifest = self._manifest_required()
        indexes = manifest.get("indexes")
        if not isinstance(indexes, Mapping):
            raise QueryIntegrityError("manifest indexes are missing")
        descriptor = indexes.get(name)
        if not isinstance(descriptor, Mapping):
            raise QueryIntegrityError(f"release index is missing: {name}")
        return dict(descriptor)

    def load_routing_index(
        self,
        name: str,
        *,
        family: str = "routing_index",
        reason: str = "routing_index",
        keys: Sequence[str] = (),
    ) -> list[dict[str, Any]]:
        """Load a compact routing/meta index with route justification."""

        cached = self._index_cache.get(name)
        if cached is not None:
            return [dict(row) for row in cached]
        descriptor = self._index_descriptor(name)
        relative_path = str(
            descriptor.get("relative_path") or descriptor.get("path") or ""
        )
        if not relative_path:
            raise QueryIntegrityError(f"index {name!r} lacks relative_path")
        route = RouteJustification(
            family=family,
            reason=reason,
            relative_path=relative_path,
            keys=tuple(str(item) for item in keys),
            metadata={"index_name": name},
        )
        artifact = self.fetch(
            relative_path,
            route=route,
            descriptor=descriptor,
            charge_shard=True,
            charge_rows=int(descriptor.get("row_count") or 0),
        )
        rows = self._read_rows(artifact, descriptor=descriptor)
        if not rows:
            raise QueryIntegrityError(f"release index is empty: {name}")
        self._index_cache[name] = [dict(row) for row in rows]
        return [dict(row) for row in rows]

    def _read_rows(
        self,
        artifact: ResolvedArtifact,
        *,
        descriptor: Mapping[str, Any] | ArtifactDescriptor | None = None,
        columns: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        cache_key = artifact.relative_path
        if cache_key in self._row_cache and columns is None:
            return [dict(row) for row in self._row_cache[cache_key]]
        path = artifact.path
        media = ""
        if isinstance(descriptor, ArtifactDescriptor):
            media = descriptor.media_type
        elif isinstance(descriptor, Mapping):
            media = str(descriptor.get("media_type") or "")
        suffix = path.suffix.lower()
        if media.endswith("json") or suffix == ".json" or media == "application/json":
            payload = json.loads(path.read_bytes().decode("utf-8"))
            if isinstance(payload, list):
                rows = [dict(item) for item in payload if isinstance(item, Mapping)]
            elif isinstance(payload, Mapping) and isinstance(payload.get("rows"), list):
                rows = [
                    dict(item) for item in payload["rows"] if isinstance(item, Mapping)
                ]
            else:
                raise QueryIntegrityError(
                    f"JSON artifact is not a row list: {artifact.relative_path}"
                )
        else:
            _, pq = _pyarrow()
            table = pq.read_table(
                path,
                columns=list(columns) if columns is not None else None,
            )
            if table.num_rows > MAX_ROWS_PER_PHYSICAL_SHARD:
                raise QueryIntegrityError(
                    f"artifact exceeds physical row bound: {artifact.relative_path}"
                )
            rows = [
                {key: _json_value(value) for key, value in row.items()}
                for row in table.to_pylist()
            ]
        if columns is None:
            self._row_cache[cache_key] = [dict(row) for row in rows]
        return rows

    # -- BM25 routing + scoring ---------------------------------------------

    def route_bm25_terms(
        self,
        terms: Sequence[str],
        *,
        index_name: str = "bm25_keyword_shards",
    ) -> dict[str, RouteJustification]:
        """Select posting shards for *terms* via inclusive term-range routes."""

        unique_terms: list[str] = []
        seen: set[str] = set()
        for term in terms:
            token = str(term)
            if not token or token in seen:
                continue
            seen.add(token)
            unique_terms.append(token)
            if len(unique_terms) >= MAX_QUERY_TERMS:
                break
        meta = self.load_routing_index(
            index_name,
            keys=unique_terms,
            reason="routing_index",
        )
        selected = select_term_range_shards(meta, unique_terms)
        routes: dict[str, RouteJustification] = {}
        for term, row in selected.items():
            path = str(row.get("relative_path") or "")
            routes[term] = RouteJustification(
                family="bm25_postings",
                reason="term_range",
                relative_path=path,
                keys=(term,),
                metadata={
                    "first_key": row.get("first_key"),
                    "last_key": row.get("last_key"),
                    "shard_id": row.get("shard_id"),
                },
            )
        return routes

    def fetch_bm25_postings(
        self,
        term_routes: Mapping[str, RouteJustification],
        *,
        descriptors_by_path: Mapping[str, Mapping[str, Any]] | None = None,
        index_name: str = "bm25_keyword_shards",
    ) -> dict[str, list[dict[str, Any]]]:
        """Fetch justified posting shards and return rows grouped by term."""

        if descriptors_by_path is None:
            meta = self.load_routing_index(index_name)
            descriptors_by_path = {str(row["relative_path"]): dict(row) for row in meta}
        by_path: dict[str, list[str]] = defaultdict(list)
        for term, route in term_routes.items():
            by_path[route.relative_path].append(term)

        postings_by_term: dict[str, list[dict[str, Any]]] = {
            term: [] for term in term_routes
        }
        for path, terms in sorted(by_path.items()):
            descriptor = descriptors_by_path.get(path)
            if descriptor is None:
                raise QueryIntegrityError(f"missing descriptor for BM25 shard {path}")
            # One justification covering all terms routed to this shard.
            route = RouteJustification(
                family="bm25_postings",
                reason="term_range",
                relative_path=path,
                keys=tuple(sorted(terms)),
                metadata={"shard_id": descriptor.get("shard_id")},
            )
            try:
                artifact = self.fetch(
                    path,
                    route=route,
                    descriptor=descriptor,
                    charge_shard=True,
                    charge_rows=int(descriptor.get("row_count") or 0),
                    raise_on_budget=True,
                )
            except QueryBudgetExhausted as exc:
                self._stop_reason = exc.dimension
                raise
            rows = self._read_rows(artifact, descriptor=descriptor)
            wanted = set(terms)
            for row in rows:
                term = str(row.get("term") or "")
                if term in wanted:
                    postings_by_term[term].append(dict(row))
        return postings_by_term

    def score_bm25_postings(
        self,
        postings_by_term: Mapping[str, Sequence[Mapping[str, Any]]],
        *,
        top_k: int = DEFAULT_TOP_K,
        bm25_config: Mapping[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Exact BM25 scoring over already-fetched posting rows."""

        top_k = _positive_int(top_k, "top_k")
        if top_k > MAX_TOP_K:
            raise QueryInputError(f"top_k must be <= {MAX_TOP_K}")
        manifest = self._manifest_required()
        config = dict(bm25_config or manifest.get("bm25") or {})
        k1 = float(config.get("k1", 1.2))
        b = float(config.get("b", 0.75))
        title_weight = float(config.get("title_weight", 5.0))
        body_weight = float(config.get("body_weight", 1.0))
        avg_dl = float(config.get("average_document_length") or 0.0)
        if avg_dl <= 0.0:
            raise QueryIntegrityError("bm25.average_document_length must be positive")
        exact_profile = _exact_bm25_field_profile(config)

        scores: dict[int, float] = defaultdict(float)
        matched: dict[int, set[str]] = defaultdict(set)
        entry_by_doc: dict[int, str] = {}
        explanations: dict[int, list[dict[str, Any]]] = defaultdict(list)

        for term, rows in postings_by_term.items():
            for row in rows:
                document_ids = [
                    int(value) for value in (row.get("document_indices") or [])
                ]
                title_frequencies = [
                    int(value) for value in (row.get("title_frequencies") or [])
                ]
                body_frequencies = [
                    int(value) for value in (row.get("body_frequencies") or [])
                ]
                document_lengths = [
                    int(value) for value in (row.get("document_lengths") or [])
                ]
                entry_cids = [str(value) for value in (row.get("entry_cids") or [])]
                idf = float(row.get("idf") or 0.0)
                if not document_ids:
                    continue
                # Align optional parallel arrays; pad missing fields with zeros.
                n = len(document_ids)
                if not title_frequencies:
                    title_frequencies = [0] * n
                if not body_frequencies:
                    body_frequencies = [0] * n
                if not document_lengths:
                    document_lengths = [int(avg_dl)] * n
                if len(title_frequencies) != n or len(body_frequencies) != n:
                    raise QueryIntegrityError(
                        f"unaligned BM25 posting arrays for term {term!r}"
                    )
                if len(document_lengths) != n:
                    raise QueryIntegrityError(
                        f"unaligned document_lengths for term {term!r}"
                    )
                exact_frequencies: dict[str, list[int]] = {}
                exact_lengths: dict[str, list[int]] = {}
                if exact_profile is not None:
                    for field_name in exact_profile.fields:
                        frequency_column = (
                            f"{exact_profile.exact_field_prefix}"
                            f"{field_name}_frequencies"
                        )
                        length_column = (
                            f"{exact_profile.exact_field_prefix}{field_name}_lengths"
                        )
                        raw_frequencies = row.get(frequency_column)
                        raw_lengths = row.get(length_column)
                        if not isinstance(raw_frequencies, Sequence) or isinstance(
                            raw_frequencies, (str, bytes)
                        ):
                            raise QueryIntegrityError(
                                "missing exact BM25 posting column "
                                f"{frequency_column!r}"
                            )
                        if not isinstance(raw_lengths, Sequence) or isinstance(
                            raw_lengths, (str, bytes)
                        ):
                            raise QueryIntegrityError(
                                f"missing exact BM25 posting column {length_column!r}"
                            )
                        try:
                            field_frequencies = [
                                int(value) for value in raw_frequencies
                            ]
                            field_lengths = [int(value) for value in raw_lengths]
                        except (TypeError, ValueError) as exc:
                            raise QueryIntegrityError(
                                "non-integer exact BM25 arrays for field "
                                f"{field_name!r}"
                            ) from exc
                        if len(field_frequencies) != n or len(field_lengths) != n:
                            raise QueryIntegrityError(
                                f"unaligned exact BM25 arrays for field {field_name!r}"
                            )
                        if any(value < 0 for value in field_frequencies) or any(
                            value < 0 for value in field_lengths
                        ):
                            raise QueryIntegrityError(
                                f"negative exact BM25 values for field {field_name!r}"
                            )
                        exact_frequencies[field_name] = field_frequencies
                        exact_lengths[field_name] = field_lengths
                for offset, document_id in enumerate(document_ids):
                    title_tf = title_frequencies[offset]
                    body_tf = body_frequencies[offset]
                    doc_len = document_lengths[offset]
                    field_contributions: list[dict[str, Any]] = []
                    if exact_profile is not None:
                        title_tf = sum(
                            exact_frequencies[field_name][offset]
                            for field_name in exact_profile.title_fields
                        )
                        body_tf = sum(
                            exact_frequencies[field_name][offset]
                            for field_name in exact_profile.body_fields
                        )
                        title_score = 0.0
                        body_score = 0.0
                        for field_name in exact_profile.fields:
                            field_tf = exact_frequencies[field_name][offset]
                            field_length = exact_lengths[field_name][offset]
                            if field_tf > field_length:
                                raise QueryIntegrityError(
                                    "exact BM25 field length is smaller than term "
                                    f"frequency for {field_name!r}"
                                )
                            if field_tf <= 0:
                                continue
                            weight = exact_profile.field_weights[field_name]
                            field_score = bm25_term_score(
                                tf=float(field_tf),
                                idf=idf,
                                doc_length=float(field_length),
                                avg_doc_length=max(
                                    exact_profile.average_field_lengths[field_name],
                                    1e-12,
                                ),
                                k1=k1,
                                b=b,
                                field_weight=weight,
                            )
                            if field_name in exact_profile.title_fields:
                                title_score += field_score
                            else:
                                body_score += field_score
                            field_contributions.append(
                                {
                                    "field": field_name,
                                    "field_length": field_length,
                                    "score": field_score,
                                    "tf": field_tf,
                                    "weight": weight,
                                }
                            )
                        contribution = title_score + body_score
                    else:
                        title_score = bm25_term_score(
                            tf=float(title_tf),
                            idf=idf,
                            doc_length=float(doc_len),
                            avg_doc_length=avg_dl,
                            k1=k1,
                            b=b,
                            field_weight=title_weight,
                        )
                        body_score = bm25_term_score(
                            tf=float(body_tf),
                            idf=idf,
                            doc_length=float(doc_len),
                            avg_doc_length=avg_dl,
                            k1=k1,
                            b=b,
                            field_weight=body_weight,
                        )
                        # Prefer field-split scores; fall back to weighted TF cell.
                        if title_tf == 0 and body_tf == 0:
                            weighted_tf = float(row.get("weighted_tf") or 0.0)
                            contribution = bm25_term_score(
                                tf=weighted_tf,
                                idf=idf,
                                doc_length=float(doc_len),
                                avg_doc_length=avg_dl,
                                k1=k1,
                                b=b,
                                field_weight=1.0,
                            )
                        else:
                            contribution = title_score + body_score
                    scores[document_id] += contribution
                    matched[document_id].add(str(term))
                    if entry_cids and offset < len(entry_cids):
                        entry_by_doc[document_id] = entry_cids[offset]
                    explanation = {
                        "body_score": body_score,
                        "body_tf": body_tf,
                        "idf": idf,
                        "term": str(term),
                        "title_score": title_score,
                        "title_tf": title_tf,
                        "total_score": contribution,
                    }
                    if exact_profile is not None:
                        explanation.update(
                            {
                                "field_contributions": field_contributions,
                                "scorer": "exact_multifield",
                            }
                        )
                    explanations[document_id].append(explanation)
                    # Row budget: each posting pointer counts as one row unit.
                    self.usage.charge(rows=1)
                    exhausted = self.usage.check(self.limits, raise_on_exhaustion=False)
                    if exhausted is not None:
                        self._stop_reason = exhausted
                        break
                if self._stop_reason is not None:
                    break
            if self._stop_reason is not None:
                break

        ranked = heapq.nlargest(
            top_k,
            scores.items(),
            key=lambda item: (item[1], -item[0]),
        )
        results: list[dict[str, Any]] = []
        for document_id, score in ranked:
            results.append(
                {
                    "document_index": document_id,
                    "entry_cid": entry_by_doc.get(document_id),
                    "explain": sorted(
                        explanations[document_id],
                        key=lambda item: item["term"],
                    ),
                    "matched_terms": sorted(matched[document_id]),
                    "score": float(score),
                }
            )
        return results

    def run_bm25(
        self,
        query: str,
        *,
        top_k: int = DEFAULT_TOP_K,
        hydrate: bool = True,
        include_content: bool = False,
    ) -> QueryEngineResult:
        """Route BM25 terms, score postings, optionally hydrate corpus hits."""

        self._stop_reason = None
        ordered_terms: list[str] = []
        tokenizer_id = DEFAULT_BM25_TOKENIZER_ID
        analyzer_injected = False
        analyzer_contract_active = False

        try:
            manifest = self._manifest_required()
            bm25_config = manifest.get("bm25") or {}
            if not isinstance(bm25_config, Mapping):
                raise QueryIntegrityError("manifest bm25 configuration is malformed")
            analyzer_contract_active = bm25_config.get("query_analyzer") is not None
            tokenizer_id, analyzer, analyzer_injected = (
                self._resolve_bm25_query_analyzer(bm25_config)
            )
            analyzer_contract_active = analyzer_contract_active or analyzer_injected
            ordered_terms = self._analyze_bm25_query(
                str(query or ""),
                tokenizer_id=tokenizer_id,
                analyzer=analyzer,
            )
            if not ordered_terms:
                return self._result(
                    mode="bm25",
                    query=str(query or ""),
                    results=(),
                    diagnostics={
                        **(
                            {"query_analyzer_injected": analyzer_injected}
                            if analyzer_contract_active
                            else {}
                        ),
                        "query_terms": [],
                    },
                    complete=True,
                    stop_reason=None,
                    explain=(
                        {
                            "query_analyzer_injected": analyzer_injected,
                            "tokenizer": tokenizer_id,
                        }
                        if analyzer_contract_active
                        else None
                    ),
                )
            routes = self.route_bm25_terms(ordered_terms)
            postings = self.fetch_bm25_postings(routes)
            hits = self.score_bm25_postings(postings, top_k=top_k)
            if hydrate and hits:
                hits = self.hydrate_hits(
                    hits,
                    include_content=include_content,
                )
        except QueryBudgetExhausted as exc:
            partial_hits = list((exc.partial or {}).get("results") or [])
            return self._result(
                mode="bm25",
                query=str(query or ""),
                results=tuple(partial_hits),
                diagnostics={
                    "budget_exhausted": exc.to_dict(),
                    **(
                        {"query_analyzer_injected": analyzer_injected}
                        if analyzer_contract_active
                        else {}
                    ),
                    "query_terms": ordered_terms,
                },
                complete=False,
                stop_reason=exc.dimension,
            )

        return self._result(
            mode="bm25",
            query=str(query or ""),
            results=tuple(hits),
            diagnostics={
                "keyword_shards_fetched": len(
                    {route.relative_path for route in routes.values()}
                ),
                **(
                    {"query_analyzer_injected": analyzer_injected}
                    if analyzer_contract_active
                    else {}
                ),
                "query_terms": ordered_terms,
                "routed_terms": sorted(routes),
            },
            complete=self._stop_reason is None,
            stop_reason=self._stop_reason,
            explain={
                **(
                    {"query_analyzer_injected": analyzer_injected}
                    if analyzer_contract_active
                    else {}
                ),
                "tokenizer": tokenizer_id,
                "routed_shards": sorted(
                    {route.relative_path for route in routes.values()}
                ),
            },
        )

    # -- Vector routing + exact scoring -------------------------------------

    def route_vector_centroids(
        self,
        query_vector: Sequence[float],
        *,
        candidate_centroids: int = DEFAULT_CANDIDATE_CENTROIDS,
        max_shards: int | None = None,
        index_name: str = "vector_chunks",
    ) -> tuple[VectorShardRoute, ...]:
        """Score centroids and return selected physical shard routes."""

        meta = self.load_routing_index(index_name, reason="routing_index")
        return route_vector_shards(
            meta,
            query_vector,
            candidate_centroids=candidate_centroids,
            max_shards=max_shards,
        )

    def score_vector_shards(
        self,
        routes: Sequence[VectorShardRoute | Mapping[str, Any]],
        query_vector: Sequence[float],
        *,
        top_k: int = DEFAULT_TOP_K,
        descriptors_by_path: Mapping[str, Mapping[str, Any]] | None = None,
        index_name: str = "vector_chunks",
    ) -> list[dict[str, Any]]:
        """Exact cosine scoring inside centroid-selected vector shards."""

        top_k = _positive_int(top_k, "top_k")
        if top_k > MAX_TOP_K:
            raise QueryInputError(f"top_k must be <= {MAX_TOP_K}")
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover
            raise QueryEngineError(
                "numpy is required for vector exact scoring"
            ) from exc

        if descriptors_by_path is None:
            meta = self.load_routing_index(index_name)
            descriptors_by_path = {str(row["relative_path"]): dict(row) for row in meta}

        query = np.asarray(list(query_vector), dtype=np.float64)
        if query.ndim != 1 or not np.isfinite(query).all():
            raise QueryInputError("query_vector must be a finite 1-D sequence")
        norm = float(np.linalg.norm(query))
        if not math.isfinite(norm) or norm == 0.0:
            raise QueryInputError("query_vector must be non-zero")
        query = (query / norm).astype(np.float32)
        dimension = int(query.shape[0])

        heap: list[tuple[float, str, dict[str, Any]]] = []
        candidate_rows = 0
        for item in routes:
            if isinstance(item, VectorShardRoute):
                path = item.relative_path
                score_hint = item.score
                cluster_id = item.cluster_id
            else:
                path = str(item.get("relative_path") or "")
                score_hint = float(item.get("score") or 0.0)
                cluster_id = int(item.get("cluster_id") or 0)
            descriptor = descriptors_by_path.get(path)
            if descriptor is None:
                raise QueryIntegrityError(f"missing descriptor for vector shard {path}")
            route = RouteJustification(
                family="vectors",
                reason="exact_vector_score",
                relative_path=path,
                keys=(f"cluster:{cluster_id}",),
                score=float(score_hint),
                metadata={
                    "cluster_id": cluster_id,
                    "shard_id": descriptor.get("shard_id"),
                },
            )
            try:
                artifact = self.fetch(
                    path,
                    route=route,
                    descriptor=descriptor,
                    charge_shard=True,
                    charge_rows=int(descriptor.get("row_count") or 0),
                )
            except QueryBudgetExhausted as exc:
                self._stop_reason = exc.dimension
                break
            rows = self._read_rows(artifact, descriptor=descriptor)
            candidate_rows += len(rows)
            for row in rows:
                embedding = row.get("embedding")
                if embedding is None:
                    continue
                vector = np.asarray(list(embedding), dtype=np.float32)
                if vector.shape != (dimension,):
                    raise QueryIntegrityError(f"vector dimension mismatch in {path}")
                cosine = float(vector @ query)
                entry_cid = str(row.get("entry_cid") or "")
                document_index = int(row.get("document_index") or 0)
                payload = {
                    "cluster_id": cluster_id,
                    "document_index": document_index,
                    "entry_cid": entry_cid,
                    "score": cosine,
                }
                heap_item = (cosine, entry_cid, payload)
                if len(heap) < top_k:
                    heapq.heappush(heap, heap_item)
                elif heap_item[:2] > heap[0][:2]:
                    heapq.heapreplace(heap, heap_item)
                self.usage.charge(rows=1)
                exhausted = self.usage.check(self.limits, raise_on_exhaustion=False)
                if exhausted is not None:
                    self._stop_reason = exhausted
                    break
            if self._stop_reason is not None:
                break

        selected = sorted(heap, key=lambda item: (-item[0], item[1]))
        results = [dict(item[2]) for item in selected]
        for item in results:
            item["candidate_rows"] = candidate_rows
        return results

    def run_vector(
        self,
        query_vector: Sequence[float],
        *,
        query: str = "",
        top_k: int = DEFAULT_TOP_K,
        candidate_centroids: int = DEFAULT_CANDIDATE_CENTROIDS,
        hydrate: bool = True,
        include_content: bool = False,
    ) -> QueryEngineResult:
        """Centroid-route, exact-score, and optionally hydrate vector hits."""

        self._stop_reason = None
        try:
            self._manifest_required()
            routes = self.route_vector_centroids(
                query_vector,
                candidate_centroids=candidate_centroids,
            )
            # Record centroid_probe justifications for the selected routes
            # (exact scoring records the data-plane fetches themselves).
            for route in routes:
                # Probe is informational; the actual fetch is charged later.
                _ = RouteJustification(
                    family="vectors",
                    reason="centroid_probe",
                    relative_path=route.relative_path,
                    keys=(f"cluster:{route.cluster_id}",),
                    score=route.score,
                )
            hits = self.score_vector_shards(routes, query_vector, top_k=top_k)
            if hydrate and hits:
                hits = self.hydrate_hits(hits, include_content=include_content)
        except QueryBudgetExhausted as exc:
            return self._result(
                mode="vector",
                query=str(query or ""),
                results=(),
                diagnostics={"budget_exhausted": exc.to_dict()},
                complete=False,
                stop_reason=exc.dimension,
            )

        return self._result(
            mode="vector",
            query=str(query or ""),
            results=tuple(hits),
            diagnostics={
                "candidate_centroids": candidate_centroids,
                "candidate_shards": len(routes),
                "routed_clusters": sorted({int(route.cluster_id) for route in routes}),
                "routed_paths": [route.relative_path for route in routes],
            },
            complete=self._stop_reason is None,
            stop_reason=self._stop_reason,
            explain={
                "routing": "normalized_embedding_centroids",
                "routed_shards": [route.relative_path for route in routes],
            },
        )

    # -- Corpus hydration ---------------------------------------------------

    def hydrate_hits(
        self,
        hits: Sequence[Mapping[str, Any]],
        *,
        include_content: bool = False,
        index_name: str = "corpus_chunks",
        locator: KeyLocatorIndex | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch only corpus shards required for final hits and merge fields."""

        if not hits:
            return []
        # Prefer entry_cid locator when available; else document_index ranges.
        entry_cids = [str(hit["entry_cid"]) for hit in hits if hit.get("entry_cid")]
        document_indexes = [
            int(hit["document_index"])
            for hit in hits
            if hit.get("document_index") is not None
        ]

        hydrated_by_doc: dict[int, dict[str, Any]] = {}
        hydrated_by_cid: dict[str, dict[str, Any]] = {}

        if locator is not None and entry_cids:
            artifacts = locator.containing_artifacts(entry_cids, strict=False)
            for row in artifacts:
                route = RouteJustification(
                    family="corpus",
                    reason="hydrate_hit",
                    relative_path=row.relative_path,
                    keys=tuple(cid for cid in entry_cids if row.contains(cid)),
                    metadata={"shard_id": row.shard_id},
                )
                descriptor = {
                    "relative_path": row.relative_path,
                    "sha256": row.sha256,
                    "size_bytes": row.size_bytes,
                    "row_count": row.row_count,
                    "media_type": "application/vnd.apache.parquet",
                }
                if row.content_cid:
                    descriptor["cid"] = row.content_cid
                try:
                    artifact = self.fetch(
                        row.relative_path,
                        route=route,
                        descriptor=descriptor,
                        charge_shard=True,
                        charge_rows=row.row_count,
                    )
                except QueryBudgetExhausted as exc:
                    self._stop_reason = exc.dimension
                    break
                for corp in self._read_rows(artifact, descriptor=descriptor):
                    cid = str(corp.get("entry_cid") or "")
                    if cid:
                        hydrated_by_cid[cid] = dict(corp)
                    if corp.get("document_index") is not None:
                        hydrated_by_doc[int(corp["document_index"])] = dict(corp)
        elif document_indexes:
            meta = self.load_routing_index(index_name, reason="routing_index")
            selected = select_document_index_shards(meta, document_indexes)
            by_path: dict[str, list[int]] = defaultdict(list)
            descriptors: dict[str, Mapping[str, Any]] = {}
            for doc_id, row in selected.items():
                path = str(row["relative_path"])
                by_path[path].append(doc_id)
                descriptors[path] = row
            for path, wanted_ids in sorted(by_path.items()):
                descriptor = descriptors[path]
                route = RouteJustification(
                    family="corpus",
                    reason="hydrate_hit",
                    relative_path=path,
                    keys=tuple(str(item) for item in sorted(wanted_ids)),
                    metadata={"shard_id": descriptor.get("shard_id")},
                )
                try:
                    artifact = self.fetch(
                        path,
                        route=route,
                        descriptor=descriptor,
                        charge_shard=True,
                        charge_rows=int(descriptor.get("row_count") or 0),
                    )
                except QueryBudgetExhausted as exc:
                    self._stop_reason = exc.dimension
                    break
                wanted = set(wanted_ids)
                for corp in self._read_rows(artifact, descriptor=descriptor):
                    raw_doc_id = corp.get("document_index")
                    doc_id = int(raw_doc_id) if raw_doc_id is not None else -1
                    if doc_id in wanted:
                        hydrated_by_doc[doc_id] = dict(corp)
                        cid = str(corp.get("entry_cid") or "")
                        if cid:
                            hydrated_by_cid[cid] = dict(corp)

        merged: list[dict[str, Any]] = []
        for hit in hits:
            row = dict(hit)
            doc_id = row.get("document_index")
            cid = row.get("entry_cid")
            extra: dict[str, Any] | None = None
            if doc_id is not None and int(doc_id) in hydrated_by_doc:
                extra = hydrated_by_doc[int(doc_id)]
            elif cid and str(cid) in hydrated_by_cid:
                extra = hydrated_by_cid[str(cid)]
            if extra is not None:
                for key, value in extra.items():
                    if key == "embedding":
                        continue
                    if key == "text" and not include_content:
                        continue
                    if key not in row or row[key] in (None, ""):
                        row[key] = value
            merged.append(row)
        return merged

    # -- Graph adjacency + walk ---------------------------------------------

    def fetch_adjacency(
        self,
        node_cid: str,
        *,
        direction: str = "out",
        limit: int = 25,
        edge_types: Sequence[str] = (),
        index_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch bounded adjacency pages for *node_cid* with budgets."""

        key = str(node_cid or "").strip()
        if not key:
            raise QueryInputError("node_cid must be a non-empty string")
        limit = _positive_int(limit, "limit")
        direction_norm = str(direction or "out").strip().lower()
        if direction_norm in {"out", "outgoing", "forward"}:
            direction_norm = "out"
            default_index = "graph_out_adjacency"
        elif direction_norm in {"in", "incoming", "reverse", "inverse"}:
            direction_norm = "in"
            default_index = "graph_in_adjacency"
        else:
            raise QueryInputError("direction must be out/in/outgoing/incoming")
        index = index_name or default_index
        wanted_types = {
            str(value).strip() for value in edge_types if str(value).strip()
        }
        meta = self.load_routing_index(
            index,
            keys=(key,),
            reason="routing_index",
        )
        shards = select_adjacency_shards(meta, key)
        edges: list[dict[str, Any]] = []
        for descriptor in shards:
            path = str(descriptor.get("relative_path") or "")
            route = RouteJustification(
                family="graph_adjacency",
                reason="adjacency_range",
                relative_path=path,
                keys=(key,),
                metadata={
                    "direction": direction_norm,
                    "shard_id": descriptor.get("shard_id"),
                },
            )
            try:
                artifact = self.fetch(
                    path,
                    route=route,
                    descriptor=descriptor,
                    charge_shard=True,
                    charge_rows=int(descriptor.get("row_count") or 0),
                    raise_on_budget=True,
                )
            except QueryBudgetExhausted as exc:
                self._stop_reason = exc.dimension
                break
            rows = self._read_rows(artifact, descriptor=descriptor)
            for row in rows:
                if str(row.get("node_cid") or "") != key:
                    continue
                # Support both expanded edge rows and pointer-cell layouts.
                if "neighbor_cid" in row or "neighbor_cids" in row:
                    if "neighbor_cids" in row:
                        arrays = self._expand_adjacency_row(
                            row, direction=direction_norm
                        )
                        for edge in arrays:
                            if (
                                wanted_types
                                and edge.get("edge_type") not in wanted_types
                            ):
                                continue
                            edges.append(edge)
                            self.usage.charge(edges=1)
                            if len(edges) >= limit:
                                return edges[:limit]
                            exhausted = self.usage.check(
                                self.limits, raise_on_exhaustion=False
                            )
                            if exhausted is not None:
                                self._stop_reason = exhausted
                                return edges[:limit]
                    else:
                        edge_type = str(row.get("edge_type") or "")
                        if wanted_types and edge_type not in wanted_types:
                            continue
                        edge = {
                            "direction": direction_norm,
                            "edge_cid": str(row.get("edge_cid") or ""),
                            "edge_type": edge_type,
                            "neighbor_cid": str(row.get("neighbor_cid") or ""),
                            "score": row.get("score"),
                            "source_cid": (
                                key
                                if direction_norm == "out"
                                else str(row.get("neighbor_cid") or "")
                            ),
                            "target_cid": (
                                str(row.get("neighbor_cid") or "")
                                if direction_norm == "out"
                                else key
                            ),
                        }
                        edges.append(edge)
                        self.usage.charge(edges=1)
                        if len(edges) >= limit:
                            return edges[:limit]
                        exhausted = self.usage.check(
                            self.limits, raise_on_exhaustion=False
                        )
                        if exhausted is not None:
                            self._stop_reason = exhausted
                            return edges[:limit]
            if self._stop_reason is not None:
                break
        return edges[:limit]

    def _expand_adjacency_row(
        self,
        row: Mapping[str, Any],
        *,
        direction: str,
    ) -> list[dict[str, Any]]:
        node_cid = str(row.get("node_cid") or "")
        edge_cids = [str(value) for value in (row.get("edge_cids") or [])]
        edge_types = [str(value) for value in (row.get("edge_types") or [])]
        neighbor_cids = [str(value) for value in (row.get("neighbor_cids") or [])]
        scores = list(row.get("scores") or [None] * len(neighbor_cids))
        count = len(neighbor_cids)
        if not (
            len(edge_cids) == count
            and len(edge_types) == count
            and len(scores) == count
        ):
            raise QueryIntegrityError(
                f"malformed adjacency pointer cell for {node_cid!r}"
            )
        edges: list[dict[str, Any]] = []
        for edge_cid, edge_type, neighbor_cid, score in zip(
            edge_cids, edge_types, neighbor_cids, scores
        ):
            edges.append(
                {
                    "direction": direction,
                    "edge_cid": edge_cid,
                    "edge_type": edge_type,
                    "neighbor_cid": neighbor_cid,
                    "score": (
                        float(score)
                        if score is not None
                        and not isinstance(score, bool)
                        and isinstance(score, (int, float))
                        else None
                    ),
                    "source_cid": (node_cid if direction == "out" else neighbor_cid),
                    "target_cid": (neighbor_cid if direction == "out" else node_cid),
                }
            )
        return edges

    def graph_walk(
        self,
        start_node_cid: str,
        *,
        direction: str = "out",
        max_depth: int | None = None,
        max_nodes: int | None = None,
        max_edges: int | None = None,
        per_node_limit: int = 25,
        edge_types: Sequence[str] = (),
    ) -> QueryEngineResult:
        """Bounded structural walk with explicit budget exhaustion."""

        self._stop_reason = None
        start = str(start_node_cid or "").strip()
        if not start:
            raise QueryInputError("start_node_cid must be a non-empty string")
        depth_limit = (
            self.limits.max_depth
            if max_depth is None
            else _non_negative_int(max_depth, "max_depth")
        )
        node_limit = (
            self.limits.max_nodes
            if max_nodes is None
            else _positive_int(max_nodes, "max_nodes")
        )
        edge_limit = (
            self.limits.max_edges
            if max_edges is None
            else _positive_int(max_edges, "max_edges")
        )
        per_node_limit = _positive_int(per_node_limit, "per_node_limit")

        # Charge the start node.
        self.usage.charge(nodes=1, depth=0)
        visited: dict[str, int] = {start: 0}
        traversed: list[dict[str, Any]] = []
        frontier = [start]
        stop_reason: str | None = "depth" if depth_limit == 0 else None
        if depth_limit == 0:
            stop_reason = "depth"

        try:
            self._manifest_required()
            for depth in range(depth_limit):
                next_frontier: list[str] = []
                projected = depth + 1
                exhausted = self.usage.check(
                    self.limits,
                    projected_depth=projected,
                    raise_on_exhaustion=False,
                )
                if exhausted is not None:
                    stop_reason = exhausted
                    break
                for node_cid in frontier:
                    try:
                        edges = self.fetch_adjacency(
                            node_cid,
                            direction=direction,
                            limit=per_node_limit,
                            edge_types=edge_types,
                        )
                    except QueryBudgetExhausted as exc:
                        stop_reason = exc.dimension
                        frontier = []
                        next_frontier = []
                        break
                    if self._stop_reason is not None:
                        stop_reason = self._stop_reason
                        frontier = []
                        next_frontier = []
                        break
                    # Deterministic order: score desc, edge_cid, neighbor.
                    edges.sort(
                        key=lambda edge: (
                            1 if edge.get("score") is None else 0,
                            -(
                                edge.get("score")
                                if edge.get("score") is not None
                                else 0.0
                            ),
                            str(edge.get("edge_type") or ""),
                            str(edge.get("neighbor_cid") or ""),
                            str(edge.get("edge_cid") or ""),
                        )
                    )
                    for edge in edges:
                        if len(traversed) >= edge_limit:
                            stop_reason = "edges"
                            break
                        neighbor = str(edge.get("neighbor_cid") or "")
                        if not neighbor:
                            continue
                        if neighbor not in visited:
                            if len(visited) >= node_limit:
                                stop_reason = "nodes"
                                break
                            visited[neighbor] = projected
                            next_frontier.append(neighbor)
                            self.usage.charge(nodes=1, depth=projected)
                        traversed.append(
                            {
                                **edge,
                                "depth": projected,
                                "from_node_cid": node_cid,
                            }
                        )
                        # edges already charged in fetch_adjacency
                    if stop_reason is not None:
                        break
                if stop_reason is not None:
                    break
                frontier = next_frontier
                if not frontier:
                    stop_reason = None  # frontier exhausted = complete
                    break
                self.usage.charge(depth=depth + 1)
            else:
                if stop_reason is None and depth_limit > 0:
                    # Completed all depth iterations with remaining frontier.
                    if frontier:
                        stop_reason = "depth"
        except QueryBudgetExhausted as exc:
            stop_reason = exc.dimension

        complete = stop_reason is None
        if complete and not frontier and depth_limit > 0:
            complete = True
        self._stop_reason = stop_reason

        nodes = [
            {"depth": depth, "node_cid": node_cid}
            for node_cid, depth in sorted(
                visited.items(), key=lambda item: (item[1], item[0])
            )
        ]
        return self._result(
            mode="graph_walk",
            query=start,
            results=tuple(nodes),
            diagnostics={
                "complete": complete,
                "direction": direction,
                "edge_count": len(traversed),
                "edges": traversed,
                "max_depth": depth_limit,
                "max_edges": edge_limit,
                "max_nodes": node_limit,
                "node_count": len(visited),
                "per_node_limit": per_node_limit,
                "start_node_cid": start,
                "stop_reason": stop_reason,
            },
            complete=complete,
            stop_reason=stop_reason,
        )

    # -- result packaging ---------------------------------------------------

    def _result(
        self,
        *,
        mode: str,
        query: str,
        results: Sequence[Mapping[str, Any]],
        diagnostics: Mapping[str, Any],
        complete: bool,
        stop_reason: str | None,
        explain: Mapping[str, Any] | None = None,
    ) -> QueryEngineResult:
        self.usage.time_ms = self.usage.elapsed_ms()
        return QueryEngineResult(
            mode=mode,
            results=tuple(dict(item) for item in results),
            diagnostics=dict(diagnostics),
            fetch_trace=self.fetch_trace(),
            complete=complete,
            stop_reason=stop_reason,
            usage=self.usage.snapshot(),
            limits=self.limits.to_dict(),
            query=query,
            explain=dict(explain or {}),
        )


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def default_query_fetch_traces_fixture_path() -> Path:
    """Repository path for the sealed query fetch-trace fixture."""

    return (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "hf_graphrag"
        / "query_fetch_traces.json"
    )


def build_query_fetch_traces_fixture_payload() -> dict[str, Any]:
    """Compact deterministic recipe for USCIR-025 fetch-trace unit tests."""

    return {
        "acceptance": {
            "budget_exhaustion_explicit": True,
            "descriptor_verified": True,
            "limits_cover": list(BUDGET_DIMENSIONS),
            "offline_replay_stable": True,
            "route_justified": True,
        },
        "bounds": {
            "default_candidate_centroids": DEFAULT_CANDIDATE_CENTROIDS,
            "default_max_bytes": DEFAULT_MAX_BYTES,
            "default_max_depth": DEFAULT_MAX_DEPTH,
            "default_max_edges": DEFAULT_MAX_EDGES,
            "default_max_nodes": DEFAULT_MAX_NODES,
            "default_max_rows": DEFAULT_MAX_ROWS,
            "default_max_shards": DEFAULT_MAX_SHARDS,
            "default_max_time_ms": DEFAULT_MAX_TIME_MS,
            "max_rows_per_physical_shard": MAX_ROWS_PER_PHYSICAL_SHARD,
        },
        "budget_dimensions": list(BUDGET_DIMENSIONS),
        "cases": [
            {
                "expected_families": [
                    "control_plane",
                    "routing_index",
                    "bm25_postings",
                    "corpus",
                ],
                "expected_reasons": [
                    "manifest",
                    "routing_index",
                    "term_range",
                    "hydrate_hit",
                ],
                "id": "bm25_term_route",
                "mode": "bm25",
                "query": "foia agency",
                "top_k": 3,
            },
            {
                "candidate_centroids": 1,
                "expected_families": [
                    "control_plane",
                    "routing_index",
                    "vectors",
                    "corpus",
                ],
                "expected_reasons": [
                    "manifest",
                    "routing_index",
                    "exact_vector_score",
                    "hydrate_hit",
                ],
                "id": "vector_centroid_route",
                "mode": "vector",
                "top_k": 2,
            },
            {
                "direction": "out",
                "expected_stop_reason": "nodes",
                "id": "graph_walk_budget_nodes",
                "max_depth": 3,
                "max_nodes": 2,
                "mode": "graph_walk",
                "start_node_cid": "node-a",
            },
            {
                "expected_stop_reason": "shards",
                "id": "bm25_budget_shards",
                "max_shards": 2,
                "mode": "bm25",
                "query": "foia agency privacy",
            },
        ],
        "description": (
            "Compact deterministic recipes for USCIR-025 bounded remote query "
            "engine unit tests.  A miniature offline release is regenerated "
            "at test time; expected route families/reasons and budget stop "
            "semantics are asserted without bulk golden dumps."
        ),
        "goal_id": GOAL_ID,
        "query_engine_schema_version": QUERY_ENGINE_SCHEMA_VERSION,
        "route_families": sorted(ROUTE_FAMILIES),
        "route_reasons": sorted(ROUTE_REASONS),
        "schema_version": QUERY_FETCH_TRACES_FIXTURE_SCHEMA,
        "task_id": TASK_ID,
    }


def load_query_fetch_traces_fixture(
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Load and lightly validate the sealed fetch-trace fixture."""

    target = (
        Path(path) if path is not None else default_query_fetch_traces_fixture_path()
    )
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise QueryInputError("query_fetch_traces fixture must be an object")
    if payload.get("schema_version") != QUERY_FETCH_TRACES_FIXTURE_SCHEMA:
        raise QueryInputError("query_fetch_traces fixture schema_version mismatch")
    if payload.get("task_id") != TASK_ID:
        raise QueryInputError("query_fetch_traces fixture task_id mismatch")
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise QueryInputError("query_fetch_traces fixture has no cases")
    return dict(payload)


def write_query_fetch_traces_fixture(
    path: str | Path | None = None,
) -> Path:
    """Write the sealed compact fixture (deterministic, no timestamps)."""

    target = (
        Path(path) if path is not None else default_query_fetch_traces_fixture_path()
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_query_fetch_traces_fixture_payload()
    target.write_text(
        canonical_json_dumps(payload) + "\n",
        encoding="utf-8",
    )
    return target


def descriptor_from_path(
    relative_path: str,
    content: bytes,
    *,
    row_count: int | None = None,
    media_type: str = "application/octet-stream",
    schema_id: str = "",
) -> dict[str, Any]:
    """Build a resolver-compatible descriptor mapping for *content*."""

    desc = build_descriptor_for_bytes(
        relative_path,
        content,
        schema_id=schema_id,
        row_count=row_count,
        media_type=media_type,
    )
    return desc.to_dict()


__all__ = [
    "BUDGET_DIMENSIONS",
    "DEFAULT_CANDIDATE_CENTROIDS",
    "DEFAULT_MANIFEST_NAME",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_EDGES",
    "DEFAULT_MAX_NODES",
    "DEFAULT_MAX_ROWS",
    "DEFAULT_MAX_SHARDS",
    "DEFAULT_MAX_TIME_MS",
    "DEFAULT_TOP_K",
    "FUSION_METHODS",
    "FUSION_RRF",
    "FUSION_STAGE",
    "FUSION_WEIGHTED",
    "GOAL_ID",
    "MAX_TOP_K",
    "QUERY_ENGINE_SCHEMA_VERSION",
    "QUERY_FETCH_TRACES_FIXTURE_SCHEMA",
    "QUERY_FETCH_TRACE_SCHEMA_VERSION",
    "ROUTE_FAMILIES",
    "ROUTE_REASONS",
    "TASK_ID",
    "BoundedRemoteQueryEngine",
    "BudgetUsage",
    "DescriptorRequiredError",
    "JustifiedFetchRecord",
    "QueryBudgetExhausted",
    "QueryEngineError",
    "QueryEngineResult",
    "QueryInputError",
    "QueryIntegrityError",
    "QueryLimits",
    "RouteJustification",
    "SemanticBeamWalkResult",
    "UnjustifiedFetchError",
    "build_query_fetch_traces_fixture_payload",
    "bounded_edge_weight",
    "cosine_similarity",
    "default_query_fetch_traces_fixture_path",
    "descriptor_from_path",
    "descriptor_for_relative_path",
    "hydrate_frontier_vectors",
    "late_fuse_rankings",
    "lexical_ranges_would_miss_keys",
    "load_query_fetch_traces_fixture",
    "normalize_late_fusion_settings",
    "normalize_semantic_beam_settings",
    "parse_entry_locator_locations",
    "ranking_identity",
    "rankings_are_compatible",
    "replay_fingerprint",
    "select_adjacency_shards",
    "select_document_index_shards",
    "select_entry_locator_pages_for_keys",
    "select_term_range_shards",
    "semantic_beam_walk",
    "route_centroid_paths",
    "write_query_fetch_traces_fixture",
]
