"""Legal hybrid and embedding-guided graph queries for U.S. Code (USCIR-027).

Domain adapter over the generic remote GraphRAG substrate:

* :mod:`ipfs_datasets_py.retrieval.hf_graphrag.remote_search` (USCIR-026)
  for BM25 / vector public modes;
* :mod:`ipfs_datasets_py.retrieval.hf_graphrag.query` (USCIR-025) for
  budgets, adjacency, and structural walks;
* :mod:`ipfs_datasets_py.processors.legal_data.uscode_graph` (USCIR-021)
  for legal vs similarity edge authority.

Public operations
-----------------
* ``bm25_search`` / ``vector_search`` — legal filter overlay on remote modes;
* ``hybrid_search`` — weighted and reciprocal-rank fusion that **preserves
  component scores** in every hit and explanation;
* ``neighbors`` — bounded adjacency with explicit authority labels;
* ``graph_walk`` — structural BFS enforcing all budgets;
* ``semantic_graph_walk`` — embedding-guided beam walk that selectively
  fetches **off-centroid** frontier vectors via direct CID-to-vector routes.

Design invariants
-----------------
* Similarity edges (``BM25_NEIGHBOR_OF``, ``SIMILAR_TO``) are retrieval hints
  only: ``legal_authority=False``, ``proof_authority=False``, never labeled
  as legal citation or authority.
* Hybrid explanations retain per-component BM25 and vector scores.
* Graph walks charge and stop on every budget dimension (bytes / shards /
  rows / nodes / edges / depth / time).
* Frontier embeddings use direct CID-range locator routes; shards outside
  the query centroid set are fetched only when a frontier node requires them.

No network I/O in unit tests; compact sealed recipes regenerate miniature
offline releases at test time.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import heapq
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Optional

from ipfs_datasets_py.processors.legal_data import (
    legal_query_authority_core as _authority_core,
)
from ipfs_datasets_py.processors.legal_data.uscode_graph import (
    DEFAULT_EDGE_CLASS,
    LEGAL_EDGE_TYPES,
    SIMILARITY_EDGE_TYPES,
    GraphEdgeClass,
    GraphEdgeType,
)
from ipfs_datasets_py.retrieval.hf_graphrag.query import (
    BUDGET_DIMENSIONS,
    DEFAULT_TOP_K,
    MAX_TOP_K,
    BoundedRemoteQueryEngine,
    QueryBudgetExhausted,
    QueryEngineError,
    QueryEngineResult,
    QueryInputError,
    QueryLimits,
    ROUTE_FAMILIES,
    ROUTE_REASONS,
    RouteJustification,
    select_adjacency_shards,
)
from ipfs_datasets_py.retrieval.hf_graphrag.remote_search import (
    DEFAULT_CANDIDATE_CENTROIDS,
    ModelSpace,
    QueryEmbedder,
    RemoteSearchClient,
    RemoteSearchError,
    RemoteSearchInputError,
    RemoteSearchResult,
    SearchFilters,
    apply_filters,
    normalize_scores,
    sparse_io_summary,
    stable_rank,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import ImmutableHubResolver
from ipfs_datasets_py.retrieval.hf_graphrag.schema import (
    canonical_json_dumps,
    content_sha256,
)

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "uscode-query-v1"
FIXTURE_SCHEMA_VERSION: Final = "uscode-query-expected-v1"
TASK_ID: Final = "USCIR-027"
GOAL_ID: Final = "USCIR-G070"
PRODUCER: Final = "uscode_query.py"
RELEASE_PROFILE: Final = "publicus-ir-graphrag/v2"
DEFAULT_MANIFEST_NAME: Final = "manifest.json"

# Fusion
FUSION_WEIGHTED: Final = "weighted"
FUSION_RRF: Final = "rrf"
FUSION_METHODS: Final = frozenset({FUSION_WEIGHTED, FUSION_RRF})
DEFAULT_BM25_WEIGHT: Final = 0.5
DEFAULT_VECTOR_WEIGHT: Final = 0.5
DEFAULT_RRF_K: Final = 60

# Semantic beam defaults
DEFAULT_BEAM_WIDTH: Final = 16
DEFAULT_MAX_DEPTH: Final = 2
DEFAULT_PER_NODE_LIMIT: Final = 16
DEFAULT_SEMANTIC_PROXIMITY_WEIGHT: Final = 0.55
DEFAULT_EDGE_WEIGHT: Final = 0.30
DEFAULT_PATH_PENALTY: Final = 0.15

# Edge authority
AUTHORITY_LEGAL: Final = "legal"
AUTHORITY_NON_AUTHORITATIVE: Final = "non_authoritative"
SIMILARITY_EDGE_TYPE_NAMES: Final = frozenset(
    item.value for item in SIMILARITY_EDGE_TYPES
)
LEGAL_EDGE_TYPE_NAMES: Final = frozenset(item.value for item in LEGAL_EDGE_TYPES)

PathLike = str | Path
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class UscodeQueryError(RemoteSearchError):
    """Base error for legal hybrid / graph query failures."""

    code: str = "uscode_query_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class UscodeQueryInputError(UscodeQueryError, RemoteSearchInputError):
    """Raised when legal query inputs are malformed."""

    code = "query_input_invalid"


class LegalAuthorityCollisionError(UscodeQueryError):
    """Raised when a similarity edge is labeled as legal authority."""

    code = "legal_authority_collision"


_EDGE_AUTHORITY_BINDINGS: Final = _authority_core.LegalQueryAuthorityBindings(
    edge_type=GraphEdgeType,
    edge_class=GraphEdgeClass,
    default_edge_class=DEFAULT_EDGE_CLASS,
    legal_edge_types=LEGAL_EDGE_TYPES,
    similarity_edge_types=SIMILARITY_EDGE_TYPES,
    legal_edge_type_names=LEGAL_EDGE_TYPE_NAMES,
    similarity_edge_type_names=SIMILARITY_EDGE_TYPE_NAMES,
    input_error=UscodeQueryInputError,
    collision_error=LegalAuthorityCollisionError,
    coerce_errors=(Exception,),
    authority_legal=AUTHORITY_LEGAL,
    authority_non_authoritative=AUTHORITY_NON_AUTHORITATIVE,
    similarity_proof_authority=False,
    similarity_notes=_authority_core.SIMILARITY_NOTES_BM25_AMENDMENT,
)


class FusionConfigError(UscodeQueryError):
    """Raised when hybrid fusion configuration is invalid."""

    code = "fusion_config_invalid"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip():
        raise UscodeQueryInputError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise UscodeQueryInputError(f"{name} must not contain NUL")
    if len(text) > maximum:
        raise UscodeQueryInputError(f"{name} exceeds maximum length {maximum}")
    return text


def _require_positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise UscodeQueryInputError(f"{name} must be a positive integer")
    return value


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise UscodeQueryInputError(f"{name} must be a non-negative integer")
    return value


def _require_weight(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise FusionConfigError(f"{name} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or number < 0.0:
        raise FusionConfigError(f"{name} must be a non-negative finite number")
    return number


def _finite_score(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def cosine_similarity(
    left: Sequence[float] | None,
    right: Sequence[float] | None,
) -> float:
    """Cosine similarity without a NumPy dependency."""

    if left is None or right is None:
        return 0.0
    try:
        a = tuple(float(x) for x in left)
        b = tuple(float(x) for x in right)
    except (TypeError, ValueError, OverflowError):
        return 0.0
    if not a or len(a) != len(b):
        return 0.0
    if not all(math.isfinite(x) for x in a) or not all(
        math.isfinite(x) for x in b
    ):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / (na * nb)))


# ---------------------------------------------------------------------------
# Edge authority (similarity never legal authority)
# ---------------------------------------------------------------------------


def edge_class_for_type(edge_type: str | GraphEdgeType) -> GraphEdgeClass:
    """Return the sealed edge class for a legal/similarity edge type."""

    return _authority_core.edge_class_for_type(
        edge_type,
        bindings=_EDGE_AUTHORITY_BINDINGS,
    )


def is_similarity_edge_type(edge_type: str | GraphEdgeType | None) -> bool:
    """Return True when *edge_type* is a non-authoritative similarity edge."""

    return _authority_core.is_similarity_edge_type(
        edge_type,
        bindings=_EDGE_AUTHORITY_BINDINGS,
    )


def is_legal_edge_type(edge_type: str | GraphEdgeType | None) -> bool:
    """Return True when *edge_type* is a legal/structural/provenance edge."""

    return _authority_core.is_legal_edge_type(
        edge_type,
        bindings=_EDGE_AUTHORITY_BINDINGS,
    )


def classify_edge_authority(edge_type: str | GraphEdgeType | None) -> dict[str, Any]:
    """Classify an edge type for query result packaging.

    Similarity edges are **never** legal authority.  Unknown types fail soft
    toward non-authoritative so retrieval noise cannot claim legal force.
    """

    return _authority_core.classify_edge_authority(
        edge_type,
        bindings=_EDGE_AUTHORITY_BINDINGS,
    )


def annotate_edge_authority(edge: Mapping[str, Any]) -> dict[str, Any]:
    """Return a copy of *edge* with sealed authority fields.

    Raises :class:`LegalAuthorityCollisionError` if a similarity edge already
    claims legal authority.
    """

    return _authority_core.annotate_edge_authority(
        edge,
        bindings=_EDGE_AUTHORITY_BINDINGS,
    )


def assert_no_similarity_as_legal_authority(
    edges: Sequence[Mapping[str, Any]],
) -> None:
    """Fail closed when any edge packages similarity as legal authority."""

    _authority_core.assert_no_similarity_as_legal_authority(
        edges,
        bindings=_EDGE_AUTHORITY_BINDINGS,
    )


def similarity_edge_semantics() -> dict[str, Any]:
    """Sealed non-authoritative semantics for similarity edges in queries."""

    return _authority_core.similarity_edge_semantics(
        bindings=_EDGE_AUTHORITY_BINDINGS,
    )


# ---------------------------------------------------------------------------
# Legal filters
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LegalFilters:
    """US Code citation / title / version filters over remote search hits.

    Extends domain-neutral :class:`SearchFilters` with legal identity fields
    (``legal_id``, ``citation``, ``version``) while preserving title / chapter
    / section / source / release_point filters.
    """

    title: str | None = None
    chapter: str | None = None
    section: str | None = None
    source: str | None = None
    release_point: str | None = None
    citation: str | None = None
    legal_id: str | None = None
    version: str | None = None
    entry_cids: tuple[str, ...] = ()
    document_indexes: tuple[int, ...] = ()
    node_types: tuple[str, ...] = ()
    edge_types: tuple[str, ...] = ()
    metadata_equals: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        def _opt(value: Any, name: str) -> str | None:
            if value is None or value == "":
                return None
            return _require_non_empty_str(value, name, maximum=512)

        object.__setattr__(self, "title", _opt(self.title, "title"))
        object.__setattr__(self, "chapter", _opt(self.chapter, "chapter"))
        object.__setattr__(self, "section", _opt(self.section, "section"))
        object.__setattr__(self, "source", _opt(self.source, "source"))
        object.__setattr__(
            self, "release_point", _opt(self.release_point, "release_point")
        )
        object.__setattr__(self, "citation", _opt(self.citation, "citation"))
        object.__setattr__(self, "legal_id", _opt(self.legal_id, "legal_id"))
        object.__setattr__(self, "version", _opt(self.version, "version"))
        object.__setattr__(
            self,
            "entry_cids",
            tuple(
                _require_non_empty_str(item, "entry_cids[]", maximum=256)
                for item in (self.entry_cids or ())
            ),
        )
        indexes: list[int] = []
        for item in self.document_indexes or ():
            if isinstance(item, bool) or not isinstance(item, int):
                raise UscodeQueryInputError(
                    "document_indexes must contain integers"
                )
            indexes.append(item)
        object.__setattr__(self, "document_indexes", tuple(indexes))
        object.__setattr__(
            self,
            "node_types",
            tuple(
                _require_non_empty_str(item, "node_types[]", maximum=128)
                for item in (self.node_types or ())
            ),
        )
        object.__setattr__(
            self,
            "edge_types",
            tuple(
                _require_non_empty_str(item, "edge_types[]", maximum=128)
                for item in (self.edge_types or ())
            ),
        )
        if not isinstance(self.metadata_equals, Mapping):
            raise UscodeQueryInputError("metadata_equals must be a mapping")
        object.__setattr__(
            self,
            "metadata_equals",
            MappingProxyType(dict(self.metadata_equals)),
        )

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.title,
                self.chapter,
                self.section,
                self.source,
                self.release_point,
                self.citation,
                self.legal_id,
                self.version,
                self.entry_cids,
                self.document_indexes,
                self.node_types,
                self.edge_types,
                self.metadata_equals,
            )
        )

    def to_search_filters(self) -> SearchFilters:
        """Project onto domain-neutral search filters (shared fields only)."""

        meta = dict(self.metadata_equals)
        if self.citation is not None:
            meta.setdefault("citation", self.citation)
        if self.legal_id is not None:
            meta.setdefault("legal_id", self.legal_id)
        if self.version is not None:
            meta.setdefault("version", self.version)
        return SearchFilters(
            title=self.title,
            chapter=self.chapter,
            section=self.section,
            source=self.source,
            release_point=self.release_point,
            entry_cids=self.entry_cids,
            document_indexes=self.document_indexes,
            node_types=self.node_types,
            edge_types=self.edge_types,
            metadata_equals=meta,
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key in (
            "title",
            "chapter",
            "section",
            "source",
            "release_point",
            "citation",
            "legal_id",
            "version",
        ):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        if self.entry_cids:
            payload["entry_cids"] = list(self.entry_cids)
        if self.document_indexes:
            payload["document_indexes"] = list(self.document_indexes)
        if self.node_types:
            payload["node_types"] = list(self.node_types)
        if self.edge_types:
            payload["edge_types"] = list(self.edge_types)
        if self.metadata_equals:
            payload["metadata_equals"] = dict(self.metadata_equals)
        return payload

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any] | SearchFilters | None = None
    ) -> "LegalFilters":
        if value is None:
            return cls()
        if isinstance(value, LegalFilters):
            return value
        if isinstance(value, SearchFilters):
            return cls(
                title=value.title,
                chapter=value.chapter,
                section=value.section,
                source=value.source,
                release_point=value.release_point,
                entry_cids=value.entry_cids,
                document_indexes=value.document_indexes,
                node_types=value.node_types,
                edge_types=value.edge_types,
                metadata_equals=dict(value.metadata_equals),
            )
        if not isinstance(value, Mapping):
            raise UscodeQueryInputError("filters must be a mapping")
        kwargs: dict[str, Any] = {}
        for key in (
            "title",
            "chapter",
            "section",
            "source",
            "release_point",
            "citation",
            "legal_id",
            "version",
        ):
            if key in value and value[key] is not None:
                kwargs[key] = value[key]
        if "entry_cids" in value and value["entry_cids"] is not None:
            kwargs["entry_cids"] = tuple(value["entry_cids"])
        if "entry_cid" in value and value["entry_cid"] is not None:
            kwargs["entry_cids"] = (value["entry_cid"],) + tuple(
                kwargs.get("entry_cids") or ()
            )
        if "document_indexes" in value and value["document_indexes"] is not None:
            kwargs["document_indexes"] = tuple(value["document_indexes"])
        if "node_types" in value and value["node_types"] is not None:
            kwargs["node_types"] = tuple(value["node_types"])
        if "edge_types" in value and value["edge_types"] is not None:
            kwargs["edge_types"] = tuple(value["edge_types"])
        if "metadata_equals" in value and value["metadata_equals"] is not None:
            kwargs["metadata_equals"] = dict(value["metadata_equals"])
        return cls(**kwargs)


def _hit_legal_field(hit: Mapping[str, Any], logical: str) -> Any:
    aliases = {
        "citation": ("citation", "bluebook", "usc_citation"),
        "legal_id": ("legal_id", "legalId", "usc_legal_id"),
        "version": ("version", "version_id", "usc_version", "edition"),
        "title": ("title", "title_number", "uscode_title"),
        "chapter": ("chapter", "chapter_number", "uscode_chapter"),
        "section": ("section", "section_number", "uscode_section"),
        "release_point": (
            "release_point",
            "release_point_id",
            "release",
            "usc_release_point",
        ),
    }
    for name in aliases.get(logical, (logical,)):
        if name in hit and hit[name] not in (None, ""):
            return hit[name]
    return None


def hit_matches_legal_filters(
    hit: Mapping[str, Any],
    filters: LegalFilters | Mapping[str, Any] | SearchFilters | None,
) -> bool:
    """Return True when *hit* satisfies all legal filters."""

    filt = (
        filters
        if isinstance(filters, LegalFilters)
        else LegalFilters.from_mapping(filters)
    )
    if filt.is_empty:
        return True
    if not isinstance(hit, Mapping):
        return False
    # Shared filters via SearchFilters projection (includes metadata_equals
    # for citation/legal_id/version when set through to_search_filters).
    base = filt.to_search_filters()
    # Evaluate base without the legal metadata keys first so equality is
    # case-insensitive for citation/legal_id/version.
    base_meta = {
        key: value
        for key, value in base.metadata_equals.items()
        if key not in {"citation", "legal_id", "version"}
    }
    base_plain = SearchFilters(
        title=base.title,
        chapter=base.chapter,
        section=base.section,
        source=base.source,
        release_point=base.release_point,
        entry_cids=base.entry_cids,
        document_indexes=base.document_indexes,
        node_types=base.node_types,
        edge_types=base.edge_types,
        metadata_equals=base_meta,
    )
    from ipfs_datasets_py.retrieval.hf_graphrag.remote_search import (
        hit_matches_filters,
    )

    if not hit_matches_filters(hit, base_plain):
        return False

    def _eq(expected: str | None, logical: str) -> bool:
        if expected is None:
            return True
        actual = _hit_legal_field(hit, logical)
        if actual is None:
            return False
        return str(actual).strip().lower() == expected.strip().lower()

    if not _eq(filt.citation, "citation"):
        return False
    if not _eq(filt.legal_id, "legal_id"):
        return False
    if not _eq(filt.version, "version"):
        return False
    return True


def apply_legal_filters(
    hits: Sequence[Mapping[str, Any]],
    filters: LegalFilters | Mapping[str, Any] | SearchFilters | None,
) -> list[dict[str, Any]]:
    """Filter hits with legal filters while preserving input order."""

    return [
        dict(hit)
        for hit in hits
        if hit_matches_legal_filters(hit, filters)
    ]


# ---------------------------------------------------------------------------
# Fusion (component scores preserved)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class FusionConfig:
    """Hybrid fusion policy with explicit component weights."""

    method: str = FUSION_WEIGHTED
    bm25_weight: float = DEFAULT_BM25_WEIGHT
    vector_weight: float = DEFAULT_VECTOR_WEIGHT
    rrf_k: int = DEFAULT_RRF_K

    def __post_init__(self) -> None:
        method = str(self.method or FUSION_WEIGHTED).strip().lower()
        if method not in FUSION_METHODS:
            raise FusionConfigError(
                f"fusion method must be one of {sorted(FUSION_METHODS)}, "
                f"got {self.method!r}"
            )
        bm25_w = _require_weight(self.bm25_weight, "bm25_weight")
        vector_w = _require_weight(self.vector_weight, "vector_weight")
        if method == FUSION_WEIGHTED and bm25_w + vector_w <= 0.0:
            raise FusionConfigError(
                "weighted fusion requires at least one positive weight"
            )
        rrf_k = _require_positive_int(self.rrf_k, "rrf_k")
        if rrf_k > 10_000:
            raise FusionConfigError("rrf_k exceeds hard bound 10000")
        object.__setattr__(self, "method", method)
        object.__setattr__(self, "bm25_weight", bm25_w)
        object.__setattr__(self, "vector_weight", vector_w)
        object.__setattr__(self, "rrf_k", rrf_k)

    def to_dict(self) -> dict[str, Any]:
        return {
            "bm25_weight": self.bm25_weight,
            "method": self.method,
            "rrf_k": self.rrf_k,
            "vector_weight": self.vector_weight,
        }

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any] | None = None
    ) -> "FusionConfig":
        if value is None:
            return cls()
        if isinstance(value, FusionConfig):
            return value
        if not isinstance(value, Mapping):
            raise FusionConfigError("fusion config must be a mapping")
        kwargs: dict[str, Any] = {}
        if "method" in value:
            kwargs["method"] = value["method"]
        if "bm25_weight" in value:
            kwargs["bm25_weight"] = value["bm25_weight"]
        if "vector_weight" in value:
            kwargs["vector_weight"] = value["vector_weight"]
        if "rrf_k" in value:
            kwargs["rrf_k"] = value["rrf_k"]
        return cls(**kwargs)


def _hit_identity(hit: Mapping[str, Any]) -> str:
    for key in ("entry_cid", "node_cid", "document_index"):
        if key in hit and hit[key] is not None and hit[key] != "":
            return f"{key}:{hit[key]}"
    return f"row:{id(hit)}"


def _component_score(hit: Mapping[str, Any]) -> float:
    for key in ("normalized_score", "score"):
        score = _finite_score(hit.get(key))
        if score is not None:
            return score
    return 0.0


def fuse_hybrid_results(
    bm25_hits: Sequence[Mapping[str, Any]],
    vector_hits: Sequence[Mapping[str, Any]],
    *,
    config: FusionConfig | Mapping[str, Any] | None = None,
    top_k: int = DEFAULT_TOP_K,
) -> list[dict[str, Any]]:
    """Fuse BM25 and vector hits while preserving component scores.

    Every fused hit carries:

    * ``bm25_score`` / ``vector_score`` — raw component scores (0 when absent);
    * ``component_scores`` — structured map of the same;
    * ``score`` — fused ranking score;
    * ``fusion_method`` — ``weighted`` or ``rrf``.

    Ranking uses stable ``(score desc, entry_cid, document_index)`` tie-breaks.
    """

    fusion = (
        config
        if isinstance(config, FusionConfig)
        else FusionConfig.from_mapping(config)
    )
    top_k = _require_positive_int(top_k, "top_k")
    if top_k > MAX_TOP_K:
        raise UscodeQueryInputError(f"top_k must be <= {MAX_TOP_K}")

    # Identity → accumulated fields + component scores.
    merged: dict[str, dict[str, Any]] = {}
    bm25_rank: dict[str, int] = {}
    vector_rank: dict[str, int] = {}

    for rank, hit in enumerate(bm25_hits, start=1):
        if not isinstance(hit, Mapping):
            continue
        key = _hit_identity(hit)
        row = merged.setdefault(key, {"entry_cid": hit.get("entry_cid")})
        for field_name, value in hit.items():
            if field_name in {"score", "normalized_score"}:
                continue
            if field_name not in row or row[field_name] in (None, ""):
                row[field_name] = value
        row["bm25_score"] = _component_score(hit)
        bm25_rank[key] = rank

    for rank, hit in enumerate(vector_hits, start=1):
        if not isinstance(hit, Mapping):
            continue
        key = _hit_identity(hit)
        row = merged.setdefault(key, {"entry_cid": hit.get("entry_cid")})
        for field_name, value in hit.items():
            if field_name in {"score", "normalized_score"}:
                continue
            if field_name not in row or row[field_name] in (None, ""):
                row[field_name] = value
        row["vector_score"] = _component_score(hit)
        vector_rank[key] = rank

    fused: list[dict[str, Any]] = []
    for key, row in merged.items():
        bm25_score = float(row.get("bm25_score") or 0.0)
        vector_score = float(row.get("vector_score") or 0.0)
        if fusion.method == FUSION_RRF:
            score = 0.0
            if key in bm25_rank:
                score += fusion.bm25_weight / (fusion.rrf_k + bm25_rank[key])
            if key in vector_rank:
                score += fusion.vector_weight / (
                    fusion.rrf_k + vector_rank[key]
                )
        else:
            # Weighted sum of component scores (already minmax-normalized
            # by public BM25/vector modes when score_normalization=minmax).
            total_w = fusion.bm25_weight + fusion.vector_weight
            score = (
                fusion.bm25_weight * bm25_score
                + fusion.vector_weight * vector_score
            ) / total_w
        payload = dict(row)
        payload["bm25_score"] = bm25_score
        payload["vector_score"] = vector_score
        payload["component_scores"] = {
            "bm25": bm25_score,
            "vector": vector_score,
        }
        payload["score"] = score
        payload["fusion_method"] = fusion.method
        payload["sources"] = sorted(
            {
                *(["bm25"] if key in bm25_rank else []),
                *(["vector"] if key in vector_rank else []),
            }
        )
        if key in bm25_rank:
            payload["bm25_rank"] = bm25_rank[key]
        if key in vector_rank:
            payload["vector_rank"] = vector_rank[key]
        fused.append(payload)

    return stable_rank(fused, top_k=top_k)


# ---------------------------------------------------------------------------
# Result packaging
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UscodeQueryResult:
    """Legal hybrid / graph query result with authority-safe packaging."""

    mode: str
    query: str
    results: tuple[dict[str, Any], ...]
    diagnostics: Mapping[str, Any]
    fetch_trace: Mapping[str, Any]
    complete: bool
    stop_reason: str | None
    usage: Mapping[str, Any]
    limits: Mapping[str, Any]
    explain: Mapping[str, Any] = field(default_factory=dict)
    filters: Mapping[str, Any] = field(default_factory=dict)
    model_space: Mapping[str, Any] = field(default_factory=dict)
    edges: tuple[dict[str, Any], ...] = ()
    sparse_io: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    task_id: str = TASK_ID
    goal_id: str = GOAL_ID

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "diagnostics", MappingProxyType(dict(self.diagnostics))
        )
        object.__setattr__(
            self, "fetch_trace", MappingProxyType(dict(self.fetch_trace))
        )
        object.__setattr__(self, "usage", MappingProxyType(dict(self.usage)))
        object.__setattr__(self, "limits", MappingProxyType(dict(self.limits)))
        object.__setattr__(
            self, "explain", MappingProxyType(dict(self.explain))
        )
        object.__setattr__(
            self, "filters", MappingProxyType(dict(self.filters))
        )
        object.__setattr__(
            self, "model_space", MappingProxyType(dict(self.model_space))
        )
        object.__setattr__(
            self, "sparse_io", MappingProxyType(dict(self.sparse_io))
        )
        object.__setattr__(
            self, "results", tuple(dict(item) for item in self.results)
        )
        object.__setattr__(
            self, "edges", tuple(dict(item) for item in self.edges)
        )
        # Enforce similarity-never-authority on packaged edges.
        assert_no_similarity_as_legal_authority(self.edges)

    @property
    def result_count(self) -> int:
        return len(self.results)

    def ordered_result_cids(self) -> tuple[str, ...]:
        ordered: list[str] = []
        for item in self.results:
            for key in ("entry_cid", "node_cid", "document_index"):
                if key in item and item[key] is not None:
                    ordered.append(str(item[key]))
                    break
        return tuple(ordered)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "complete": self.complete,
            "diagnostics": dict(self.diagnostics),
            "fetch_trace": dict(self.fetch_trace),
            "filters": dict(self.filters),
            "goal_id": self.goal_id,
            "limits": dict(self.limits),
            "mode": self.mode,
            "query": self.query,
            "result_count": self.result_count,
            "results": [dict(item) for item in self.results],
            "schema_version": self.schema_version,
            "sparse_io": dict(self.sparse_io),
            "stop_reason": self.stop_reason,
            "task_id": self.task_id,
            "usage": dict(self.usage),
        }
        if self.explain:
            payload["explain"] = dict(self.explain)
        if self.model_space:
            payload["model_space"] = dict(self.model_space)
        if self.edges:
            payload["edges"] = [dict(item) for item in self.edges]
        return payload


def query_replay_fingerprint(
    result: UscodeQueryResult | Mapping[str, Any],
) -> str:
    """Stable fingerprint for offline replay of legal query modes."""

    if isinstance(result, UscodeQueryResult):
        payload = {
            "complete": result.complete,
            "filters": dict(result.filters),
            "mode": result.mode,
            "ordered_result_cids": list(result.ordered_result_cids()),
            "query": result.query,
            "result_count": result.result_count,
            "stop_reason": result.stop_reason,
        }
    else:
        if not isinstance(result, Mapping):
            raise UscodeQueryInputError("result must be a mapping")
        payload = {
            "complete": bool(result.get("complete")),
            "filters": dict(result.get("filters") or {}),
            "mode": result.get("mode"),
            "ordered_result_cids": list(result.get("ordered_result_cids") or []),
            "query": result.get("query"),
            "result_count": result.get("result_count"),
            "stop_reason": result.get("stop_reason"),
        }
    return content_sha256(canonical_json_dumps(payload))


# ---------------------------------------------------------------------------
# Semantic beam helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SemanticBeamConfig:
    """Budgets and blend weights for embedding-guided graph walks."""

    max_depth: int = DEFAULT_MAX_DEPTH
    max_nodes: int | None = None
    max_edges: int | None = None
    per_node_limit: int = DEFAULT_PER_NODE_LIMIT
    beam_width: int = DEFAULT_BEAM_WIDTH
    proximity_weight: float = DEFAULT_SEMANTIC_PROXIMITY_WEIGHT
    edge_weight: float = DEFAULT_EDGE_WEIGHT
    path_penalty: float = DEFAULT_PATH_PENALTY
    candidate_centroids: int = DEFAULT_CANDIDATE_CENTROIDS

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "max_depth",
            _require_non_negative_int(self.max_depth, "max_depth"),
        )
        if self.max_nodes is not None:
            object.__setattr__(
                self,
                "max_nodes",
                _require_positive_int(self.max_nodes, "max_nodes"),
            )
        if self.max_edges is not None:
            object.__setattr__(
                self,
                "max_edges",
                _require_positive_int(self.max_edges, "max_edges"),
            )
        object.__setattr__(
            self,
            "per_node_limit",
            _require_positive_int(self.per_node_limit, "per_node_limit"),
        )
        object.__setattr__(
            self,
            "beam_width",
            _require_positive_int(self.beam_width, "beam_width"),
        )
        object.__setattr__(
            self,
            "proximity_weight",
            _require_weight(self.proximity_weight, "proximity_weight"),
        )
        object.__setattr__(
            self,
            "edge_weight",
            _require_weight(self.edge_weight, "edge_weight"),
        )
        object.__setattr__(
            self,
            "path_penalty",
            _require_weight(self.path_penalty, "path_penalty"),
        )
        object.__setattr__(
            self,
            "candidate_centroids",
            _require_positive_int(
                self.candidate_centroids, "candidate_centroids"
            ),
        )
        total = (
            self.proximity_weight + self.edge_weight + self.path_penalty
        )
        if total <= 0.0:
            raise UscodeQueryInputError(
                "semantic beam requires at least one positive blend weight"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "beam_width": self.beam_width,
            "candidate_centroids": self.candidate_centroids,
            "edge_weight": self.edge_weight,
            "max_depth": self.max_depth,
            "max_edges": self.max_edges,
            "max_nodes": self.max_nodes,
            "path_penalty": self.path_penalty,
            "per_node_limit": self.per_node_limit,
            "proximity_weight": self.proximity_weight,
        }


def _edge_weight_score(edge: Mapping[str, Any]) -> float:
    raw = edge.get("score")
    if raw is None:
        raw = edge.get("weight")
    score = _finite_score(raw)
    if score is None:
        # Legal structural edges without scores still participate at unit weight.
        return 1.0 if is_legal_edge_type(str(edge.get("edge_type") or "")) else 0.5
    # Clamp to [0, 1] for blend stability.
    if score < 0.0:
        return 0.0
    if score > 1.0:
        # Treat large scores as already-strong edges.
        return 1.0
    return score


def select_vector_shards_for_keys(
    meta_rows: Sequence[Mapping[str, Any]],
    keys: Sequence[str],
) -> dict[str, Mapping[str, Any]]:
    """Map each key to its inclusive first_key/last_key vector shard.

    This is the direct CID-to-vector route used for graph-frontier nodes that
    may lie outside the query-selected centroid set.
    """

    if not isinstance(meta_rows, Sequence) or isinstance(
        meta_rows, (str, bytes, bytearray)
    ):
        raise UscodeQueryInputError("meta_rows must be a sequence")
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


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class UscodeQueryClient:
    """Legal hybrid and embedding-guided graph queries over a pinned release.

    Parameters
    ----------
    resolver:
        Pinned :class:`ImmutableHubResolver`.
    limits:
        Optional per-query budgets.
    search:
        Optional pre-built :class:`RemoteSearchClient`.
    engine:
        Optional pre-built :class:`BoundedRemoteQueryEngine`.
    query_embedder:
        Exact model-space embedding hook for vector/hybrid/semantic modes.
    fusion:
        Default hybrid fusion configuration.
    score_normalization:
        Forwarded to the remote search client (``minmax`` / ``none``).
    """

    def __init__(
        self,
        resolver: ImmutableHubResolver | None = None,
        *,
        limits: QueryLimits | Mapping[str, Any] | None = None,
        search: RemoteSearchClient | None = None,
        engine: BoundedRemoteQueryEngine | None = None,
        query_embedder: QueryEmbedder | None = None,
        fusion: FusionConfig | Mapping[str, Any] | None = None,
        score_normalization: str = "minmax",
        manifest_path: str = DEFAULT_MANIFEST_NAME,
    ) -> None:
        if search is not None:
            if not isinstance(search, RemoteSearchClient):
                raise UscodeQueryInputError(
                    "search must be a RemoteSearchClient instance"
                )
            self.search = search
        else:
            self.search = RemoteSearchClient(
                resolver,
                limits=limits,
                engine=engine,
                query_embedder=query_embedder,
                score_normalization=score_normalization,
                manifest_path=manifest_path,
            )
        self.engine = self.search.engine
        self.fusion = (
            fusion
            if isinstance(fusion, FusionConfig)
            else FusionConfig.from_mapping(fusion)
        )
        self._vector_cache: dict[str, tuple[float, ...]] = {}
        self._vector_meta: list[dict[str, Any]] | None = None
        self._centroid_routed_paths: set[str] = set()
        self._frontier_fetch_paths: set[str] = set()
        self._off_centroid_fetch_paths: set[str] = set()

    @property
    def resolver(self) -> ImmutableHubResolver:
        return self.engine.resolver

    def reset_session(
        self,
        *,
        limits: QueryLimits | Mapping[str, Any] | None = None,
        keep_manifest: bool = True,
    ) -> None:
        """Start a fresh budget/trace session."""

        self.search.reset_session(limits=limits, keep_manifest=keep_manifest)
        self._vector_cache.clear()
        if not keep_manifest:
            self._vector_meta = None
        self._centroid_routed_paths.clear()
        self._frontier_fetch_paths.clear()
        self._off_centroid_fetch_paths.clear()

    def _coerce_filters(
        self,
        filters: LegalFilters | SearchFilters | Mapping[str, Any] | None,
    ) -> LegalFilters:
        return LegalFilters.from_mapping(filters)

    def _package_from_remote(
        self,
        remote: RemoteSearchResult,
        *,
        mode: str | None = None,
        filters: LegalFilters | None = None,
        explain_extra: Mapping[str, Any] | None = None,
        diagnostics_extra: Mapping[str, Any] | None = None,
        results: Sequence[Mapping[str, Any]] | None = None,
        edges: Sequence[Mapping[str, Any]] = (),
    ) -> UscodeQueryResult:
        explain = dict(remote.explain)
        if explain_extra:
            explain.update(dict(explain_extra))
        diagnostics = dict(remote.diagnostics)
        if diagnostics_extra:
            diagnostics.update(dict(diagnostics_extra))
        hits = (
            [dict(item) for item in results]
            if results is not None
            else [dict(item) for item in remote.results]
        )
        annotated_edges = tuple(
            annotate_edge_authority(edge) for edge in edges
        )
        return UscodeQueryResult(
            mode=mode or remote.mode,
            query=remote.query,
            results=tuple(hits),
            diagnostics=diagnostics,
            fetch_trace=dict(remote.fetch_trace),
            complete=remote.complete,
            stop_reason=remote.stop_reason,
            usage=dict(remote.usage),
            limits=dict(remote.limits),
            explain=explain,
            filters=(filters or LegalFilters()).to_dict(),
            model_space=dict(remote.model_space),
            edges=annotated_edges,
            sparse_io=dict(remote.sparse_io) or sparse_io_summary(
                remote.fetch_trace
            ),
        )

    def _package_from_engine(
        self,
        engine_result: QueryEngineResult,
        *,
        mode: str,
        query: str = "",
        filters: LegalFilters | None = None,
        results: Sequence[Mapping[str, Any]] | None = None,
        edges: Sequence[Mapping[str, Any]] = (),
        explain: Mapping[str, Any] | None = None,
        diagnostics_extra: Mapping[str, Any] | None = None,
        model_space: Mapping[str, Any] | None = None,
    ) -> UscodeQueryResult:
        diagnostics = dict(engine_result.diagnostics)
        if diagnostics_extra:
            diagnostics.update(dict(diagnostics_extra))
        explain_payload = dict(engine_result.explain)
        if explain:
            explain_payload.update(dict(explain))
        hits = (
            [dict(item) for item in results]
            if results is not None
            else [dict(item) for item in engine_result.results]
        )
        annotated_edges = tuple(
            annotate_edge_authority(edge) for edge in edges
        )
        fetch_trace = self.engine.fetch_trace()
        return UscodeQueryResult(
            mode=mode,
            query=query or engine_result.query,
            results=tuple(hits),
            diagnostics=diagnostics,
            fetch_trace=fetch_trace,
            complete=engine_result.complete
            and self.engine._stop_reason is None,
            stop_reason=self.engine._stop_reason or engine_result.stop_reason,
            usage=self.engine.usage.snapshot(),
            limits=self.engine.limits.to_dict(),
            explain=explain_payload,
            filters=(filters or LegalFilters()).to_dict(),
            model_space=dict(model_space or {}),
            edges=annotated_edges,
            sparse_io=sparse_io_summary(fetch_trace),
        )

    # -- public BM25 / vector (legal filters) --------------------------------

    def bm25_search(
        self,
        query: str,
        *,
        top_k: int = DEFAULT_TOP_K,
        filters: LegalFilters | SearchFilters | Mapping[str, Any] | None = None,
        hydrate: bool = True,
        include_content: bool = False,
        reset_session: bool = True,
    ) -> UscodeQueryResult:
        """BM25 search with legal citation/title/version filters."""

        filt = self._coerce_filters(filters)
        remote = self.search.bm25_search(
            query,
            top_k=top_k if filt.is_empty else min(MAX_TOP_K, max(top_k * 4, top_k)),
            filters=filt.to_search_filters(),
            hydrate=hydrate,
            include_content=include_content,
            reset_session=reset_session,
        )
        hits = apply_legal_filters(remote.results, filt)
        hits = stable_rank(hits, top_k=top_k)
        return self._package_from_remote(
            remote,
            mode="bm25",
            filters=filt,
            results=hits,
            explain_extra={"legal_filters": filt.to_dict()},
        )

    def vector_search(
        self,
        query: str = "",
        *,
        query_vector: Sequence[float] | None = None,
        model_space: ModelSpace | Mapping[str, Any] | None = None,
        query_embedder: QueryEmbedder | None = None,
        top_k: int = DEFAULT_TOP_K,
        candidate_centroids: int = DEFAULT_CANDIDATE_CENTROIDS,
        filters: LegalFilters | SearchFilters | Mapping[str, Any] | None = None,
        hydrate: bool = True,
        include_content: bool = False,
        reset_session: bool = True,
    ) -> UscodeQueryResult:
        """Vector search with legal citation/title/version filters."""

        filt = self._coerce_filters(filters)
        remote = self.search.vector_search(
            query,
            query_vector=query_vector,
            model_space=model_space,
            query_embedder=query_embedder,
            top_k=top_k if filt.is_empty else min(MAX_TOP_K, max(top_k * 4, top_k)),
            candidate_centroids=candidate_centroids,
            filters=filt.to_search_filters(),
            hydrate=hydrate,
            include_content=include_content,
            reset_session=reset_session,
        )
        hits = apply_legal_filters(remote.results, filt)
        hits = stable_rank(hits, top_k=top_k)
        return self._package_from_remote(
            remote,
            mode="vector",
            filters=filt,
            results=hits,
            explain_extra={"legal_filters": filt.to_dict()},
        )

    # -- hybrid --------------------------------------------------------------

    def hybrid_search(
        self,
        query: str,
        *,
        query_vector: Sequence[float] | None = None,
        model_space: ModelSpace | Mapping[str, Any] | None = None,
        query_embedder: QueryEmbedder | None = None,
        top_k: int = DEFAULT_TOP_K,
        candidate_centroids: int = DEFAULT_CANDIDATE_CENTROIDS,
        filters: LegalFilters | SearchFilters | Mapping[str, Any] | None = None,
        fusion: FusionConfig | Mapping[str, Any] | None = None,
        hydrate: bool = True,
        include_content: bool = False,
        reset_session: bool = True,
    ) -> UscodeQueryResult:
        """Hybrid BM25 + vector search with component-score-preserving fusion.

        Runs BM25 and vector modes in one shared budget session, fuses with
        weighted sum or reciprocal-rank fusion, applies legal filters, and
        returns hits whose explanations retain ``bm25_score`` and
        ``vector_score`` component scores.
        """

        if reset_session:
            self.reset_session(keep_manifest=True)
        filt = self._coerce_filters(filters)
        fusion_cfg = (
            fusion
            if isinstance(fusion, FusionConfig)
            else FusionConfig.from_mapping(fusion)
            if fusion is not None
            else self.fusion
        )
        top_k = _require_positive_int(top_k, "top_k")
        if top_k > MAX_TOP_K:
            raise UscodeQueryInputError(f"top_k must be <= {MAX_TOP_K}")

        # Wider window so post-fusion filters still fill top_k.
        window = (
            top_k
            if filt.is_empty
            else min(MAX_TOP_K, max(top_k * 4, top_k))
        )

        bm25_result = self.search.bm25_search(
            query,
            top_k=window,
            filters=filt.to_search_filters(),
            hydrate=hydrate,
            include_content=include_content,
            reset_session=False,
            enforce_sparse_io=False,
        )
        vector_result = self.search.vector_search(
            query,
            query_vector=query_vector,
            model_space=model_space,
            query_embedder=query_embedder,
            top_k=window,
            candidate_centroids=candidate_centroids,
            filters=filt.to_search_filters(),
            hydrate=hydrate,
            include_content=include_content,
            reset_session=False,
            enforce_sparse_io=False,
        )

        fused = fuse_hybrid_results(
            bm25_result.results,
            vector_result.results,
            config=fusion_cfg,
            top_k=window,
        )
        fused = apply_legal_filters(fused, filt)
        fused = stable_rank(fused, top_k=top_k)

        # Component scores must survive packaging for every hit.
        for hit in fused:
            if "component_scores" not in hit:
                hit["component_scores"] = {
                    "bm25": float(hit.get("bm25_score") or 0.0),
                    "vector": float(hit.get("vector_score") or 0.0),
                }
            if "bm25_score" not in hit:
                hit["bm25_score"] = hit["component_scores"]["bm25"]
            if "vector_score" not in hit:
                hit["vector_score"] = hit["component_scores"]["vector"]

        complete = bm25_result.complete and vector_result.complete
        stop_reason = (
            self.engine._stop_reason
            or bm25_result.stop_reason
            or vector_result.stop_reason
        )
        fetch_trace = self.engine.fetch_trace()
        model_space_payload = dict(vector_result.model_space)
        explain = {
            "component_scores_preserved": True,
            "fusion": fusion_cfg.to_dict(),
            "legal_filters": filt.to_dict(),
            "ranking": "score_desc_entry_cid_document_index",
            "bm25_result_count": bm25_result.result_count,
            "vector_result_count": vector_result.result_count,
        }
        # Attach per-hit component score map into explain for auditability.
        explain["hit_component_scores"] = [
            {
                "entry_cid": hit.get("entry_cid"),
                "bm25_score": hit.get("bm25_score"),
                "vector_score": hit.get("vector_score"),
                "component_scores": dict(hit.get("component_scores") or {}),
                "score": hit.get("score"),
            }
            for hit in fused
        ]
        diagnostics = {
            "bm25": {
                "complete": bm25_result.complete,
                "result_count": bm25_result.result_count,
                "stop_reason": bm25_result.stop_reason,
            },
            "vector": {
                "complete": vector_result.complete,
                "result_count": vector_result.result_count,
                "stop_reason": vector_result.stop_reason,
            },
            "fusion": fusion_cfg.to_dict(),
            "public_mode": "hybrid_search",
        }
        return UscodeQueryResult(
            mode="hybrid",
            query=str(query or ""),
            results=tuple(fused),
            diagnostics=diagnostics,
            fetch_trace=fetch_trace,
            complete=complete and stop_reason is None,
            stop_reason=stop_reason,
            usage=self.engine.usage.snapshot(),
            limits=self.engine.limits.to_dict(),
            explain=explain,
            filters=filt.to_dict(),
            model_space=model_space_payload,
            edges=(),
            sparse_io=sparse_io_summary(fetch_trace),
        )

    # -- neighbors / graph_walk ----------------------------------------------

    def neighbors(
        self,
        node_cid: str,
        *,
        direction: str = "out",
        limit: int = 25,
        edge_types: Sequence[str] = (),
        include_similarity: bool = True,
        reset_session: bool = True,
    ) -> UscodeQueryResult:
        """Bounded neighbors with sealed legal/similarity authority labels."""

        if reset_session:
            self.reset_session(keep_manifest=True)
        start = _require_non_empty_str(node_cid, "node_cid")
        limit = _require_positive_int(limit, "limit")
        wanted = tuple(
            str(value).strip()
            for value in edge_types
            if str(value).strip()
        )
        if not include_similarity and not wanted:
            wanted = tuple(sorted(LEGAL_EDGE_TYPE_NAMES))

        try:
            self.engine._manifest_required()
            raw_edges = self.engine.fetch_adjacency(
                start,
                direction=direction,
                limit=limit,
                edge_types=wanted,
            )
        except QueryBudgetExhausted as exc:
            return UscodeQueryResult(
                mode="neighbors",
                query=start,
                results=(),
                diagnostics={"budget_exhausted": exc.to_dict()},
                fetch_trace=self.engine.fetch_trace(),
                complete=False,
                stop_reason=exc.dimension,
                usage=self.engine.usage.snapshot(),
                limits=self.engine.limits.to_dict(),
                explain={"similarity_edge_semantics": similarity_edge_semantics()},
                edges=(),
                sparse_io=sparse_io_summary(self.engine.fetch_trace()),
            )

        annotated: list[dict[str, Any]] = []
        for edge in raw_edges:
            if not include_similarity and is_similarity_edge_type(
                str(edge.get("edge_type") or "")
            ):
                continue
            annotated.append(annotate_edge_authority(edge))
        assert_no_similarity_as_legal_authority(annotated)

        # Results are neighbor nodes with depth 1; edges carry authority.
        neighbor_nodes: list[dict[str, Any]] = []
        seen: set[str] = set()
        for edge in annotated:
            neighbor = str(edge.get("neighbor_cid") or "")
            if not neighbor or neighbor in seen:
                continue
            seen.add(neighbor)
            neighbor_nodes.append(
                {
                    "depth": 1,
                    "edge_type": edge.get("edge_type"),
                    "legal_authority": edge.get("legal_authority"),
                    "node_cid": neighbor,
                    "score": edge.get("score"),
                }
            )

        stop_reason = self.engine._stop_reason
        return UscodeQueryResult(
            mode="neighbors",
            query=start,
            results=tuple(neighbor_nodes),
            diagnostics={
                "direction": direction,
                "edge_count": len(annotated),
                "include_similarity": include_similarity,
                "limit": limit,
                "node_cid": start,
                "stop_reason": stop_reason,
            },
            fetch_trace=self.engine.fetch_trace(),
            complete=stop_reason is None,
            stop_reason=stop_reason,
            usage=self.engine.usage.snapshot(),
            limits=self.engine.limits.to_dict(),
            explain={
                "similarity_edge_semantics": similarity_edge_semantics(),
                "similarity_never_legal_authority": True,
            },
            edges=tuple(annotated),
            sparse_io=sparse_io_summary(self.engine.fetch_trace()),
        )

    def graph_walk(
        self,
        start_node_cid: str,
        *,
        direction: str = "out",
        max_depth: int | None = None,
        max_nodes: int | None = None,
        max_edges: int | None = None,
        per_node_limit: int = DEFAULT_PER_NODE_LIMIT,
        edge_types: Sequence[str] = (),
        include_similarity: bool = True,
        reset_session: bool = True,
    ) -> UscodeQueryResult:
        """Bounded structural walk enforcing every budget dimension.

        Delegates routing/budget charging to the generic engine, then seals
        edge authority so similarity edges cannot appear as legal authority.
        """

        if reset_session:
            self.reset_session(keep_manifest=True)
        start = _require_non_empty_str(start_node_cid, "start_node_cid")
        wanted = [
            str(value).strip()
            for value in edge_types
            if str(value).strip()
        ]
        if not include_similarity and not wanted:
            wanted = sorted(LEGAL_EDGE_TYPE_NAMES)

        engine_result = self.engine.graph_walk(
            start,
            direction=direction,
            max_depth=max_depth,
            max_nodes=max_nodes,
            max_edges=max_edges,
            per_node_limit=per_node_limit,
            edge_types=wanted,
        )
        raw_edges = list(engine_result.diagnostics.get("edges") or [])
        annotated: list[dict[str, Any]] = []
        for edge in raw_edges:
            if not include_similarity and is_similarity_edge_type(
                str(edge.get("edge_type") or "")
            ):
                continue
            annotated.append(annotate_edge_authority(edge))
        assert_no_similarity_as_legal_authority(annotated)

        # Recompute completeness against all budget dimensions.
        usage = self.engine.usage.snapshot()
        limits = self.engine.limits.to_dict()
        stop_reason = engine_result.stop_reason
        for dimension in BUDGET_DIMENSIONS:
            limit_key = f"max_{dimension}" if dimension != "time" else "max_time_ms"
            usage_key = dimension if dimension != "time" else "time_ms"
            if usage_key not in usage or limit_key not in limits:
                continue
            if int(usage.get(usage_key) or 0) > int(limits[limit_key]):
                stop_reason = stop_reason or dimension

        diagnostics = dict(engine_result.diagnostics)
        diagnostics["edges"] = annotated
        diagnostics["edge_count"] = len(annotated)
        diagnostics["budgets_enforced"] = list(BUDGET_DIMENSIONS)
        diagnostics["include_similarity"] = include_similarity
        diagnostics["similarity_edge_semantics"] = similarity_edge_semantics()

        return UscodeQueryResult(
            mode="graph_walk",
            query=start,
            results=tuple(dict(item) for item in engine_result.results),
            diagnostics=diagnostics,
            fetch_trace=self.engine.fetch_trace(),
            complete=stop_reason is None,
            stop_reason=stop_reason,
            usage=usage,
            limits=limits,
            explain={
                "budgets_enforced": list(BUDGET_DIMENSIONS),
                "similarity_edge_semantics": similarity_edge_semantics(),
                "similarity_never_legal_authority": True,
                "walk_strategy": "structural_bfs",
            },
            edges=tuple(annotated),
            sparse_io=sparse_io_summary(self.engine.fetch_trace()),
        )

    # -- frontier vector fetch (direct CID) ----------------------------------

    def _load_vector_meta(self) -> list[dict[str, Any]]:
        if self._vector_meta is not None:
            return self._vector_meta
        meta = self.engine.load_routing_index(
            "vector_chunks", reason="routing_index"
        )
        self._vector_meta = [dict(row) for row in meta]
        return self._vector_meta

    def _probe_centroid_paths(
        self,
        query_vector: Sequence[float],
        *,
        candidate_centroids: int,
    ) -> set[str]:
        """Record centroid-selected paths without downloading vector data."""

        routes = self.engine.route_vector_centroids(
            query_vector,
            candidate_centroids=candidate_centroids,
        )
        paths = {route.relative_path for route in routes}
        self._centroid_routed_paths = set(paths)
        for route in routes:
            _ = RouteJustification(
                family="vectors",
                reason="centroid_probe",
                relative_path=route.relative_path,
                keys=(f"cluster:{route.cluster_id}",),
                score=route.score,
                metadata={"fetch_policy": "centroid_probe_only"},
            )
        return paths

    def fetch_frontier_vectors(
        self,
        node_cids: Sequence[str],
        *,
        query_vector: Sequence[float] | None = None,
        candidate_centroids: int = DEFAULT_CANDIDATE_CENTROIDS,
    ) -> dict[str, tuple[float, ...]]:
        """Selectively fetch embeddings for frontier nodes by direct CID.

        Uses the vector routing index's inclusive ``first_key``/``last_key``
        ranges as CID-to-shard locators.  Shards outside the query centroid
        set are recorded as off-centroid selective fetches.
        """

        wanted = [
            str(cid).strip()
            for cid in node_cids
            if str(cid or "").strip() and str(cid).strip() not in self._vector_cache
        ]
        if not wanted:
            return {
                cid: self._vector_cache[cid]
                for cid in node_cids
                if str(cid).strip() in self._vector_cache
            }

        if query_vector is not None and not self._centroid_routed_paths:
            self._probe_centroid_paths(
                query_vector, candidate_centroids=candidate_centroids
            )

        meta = self._load_vector_meta()
        key_to_shard = select_vector_shards_for_keys(meta, wanted)
        by_path: dict[str, list[str]] = defaultdict(list)
        descriptors: dict[str, Mapping[str, Any]] = {}
        for key, descriptor in key_to_shard.items():
            path = str(descriptor.get("relative_path") or "")
            if not path:
                continue
            by_path[path].append(key)
            descriptors[path] = descriptor

        for path, keys in sorted(by_path.items()):
            descriptor = descriptors[path]
            off_centroid = path not in self._centroid_routed_paths
            self._frontier_fetch_paths.add(path)
            if off_centroid:
                self._off_centroid_fetch_paths.add(path)
            route = RouteJustification(
                family="vectors",
                reason="exact_vector_score",
                relative_path=path,
                keys=tuple(sorted(keys)),
                metadata={
                    "fetch_policy": "direct_cid_frontier",
                    "off_centroid": off_centroid,
                    "shard_id": descriptor.get("shard_id"),
                },
            )
            try:
                artifact = self.engine.fetch(
                    path,
                    route=route,
                    descriptor=descriptor,
                    charge_shard=True,
                    charge_rows=int(descriptor.get("row_count") or 0),
                )
            except QueryBudgetExhausted as exc:
                self.engine._stop_reason = exc.dimension
                break
            rows = self.engine._read_rows(artifact, descriptor=descriptor)
            wanted_set = set(keys)
            for row in rows:
                entry_cid = str(row.get("entry_cid") or "")
                if entry_cid not in wanted_set:
                    # Also accept node_cid field when present.
                    entry_cid = str(row.get("node_cid") or entry_cid)
                if entry_cid not in wanted_set and entry_cid not in set(wanted):
                    # Match any requested key present in the row.
                    for candidate_key in (
                        "entry_cid",
                        "node_cid",
                        "chunk_cid",
                    ):
                        value = str(row.get(candidate_key) or "")
                        if value in wanted_set:
                            entry_cid = value
                            break
                if entry_cid not in wanted_set:
                    continue
                embedding = row.get("embedding")
                if embedding is None:
                    continue
                try:
                    vector = tuple(float(x) for x in embedding)
                except (TypeError, ValueError):
                    continue
                self._vector_cache[entry_cid] = vector
                self.engine.usage.charge(rows=1)

        return {
            cid: self._vector_cache[cid]
            for cid in node_cids
            if str(cid).strip() in self._vector_cache
        }

    # -- semantic graph walk -------------------------------------------------

    def semantic_graph_walk(
        self,
        start_node_cid: str,
        *,
        query: str = "",
        query_vector: Sequence[float] | None = None,
        model_space: ModelSpace | Mapping[str, Any] | None = None,
        query_embedder: QueryEmbedder | None = None,
        direction: str = "out",
        edge_types: Sequence[str] = (),
        include_similarity: bool = True,
        beam: SemanticBeamConfig | Mapping[str, Any] | None = None,
        reset_session: bool = True,
    ) -> UscodeQueryResult:
        """Embedding-guided beam walk with selective off-centroid vector fetch.

        Starts at *start_node_cid*, expands routed adjacency pages, fetches
        frontier embeddings via **direct CID-to-vector** routes (not only
        centroid-selected shards), and ranks candidates with a declared blend
        of semantic proximity, edge weight, and path-depth penalty.
        """

        if reset_session:
            self.reset_session(keep_manifest=True)
        start = _require_non_empty_str(start_node_cid, "start_node_cid")
        if isinstance(beam, SemanticBeamConfig):
            beam_cfg = beam
        elif beam is None:
            beam_cfg = SemanticBeamConfig()
        else:
            if not isinstance(beam, Mapping):
                raise UscodeQueryInputError("beam config must be a mapping")
            beam_cfg = SemanticBeamConfig(
                **{
                    key: beam[key]
                    for key in (
                        "max_depth",
                        "max_nodes",
                        "max_edges",
                        "per_node_limit",
                        "beam_width",
                        "proximity_weight",
                        "edge_weight",
                        "path_penalty",
                        "candidate_centroids",
                    )
                    if key in beam
                }
            )

        # Resolve query vector under exact model-space matching.
        vector, release = self.search.resolve_query_vector(
            query=query,
            query_vector=query_vector,
            model_space=model_space,
            query_embedder=query_embedder,
        )

        depth_limit = beam_cfg.max_depth
        if depth_limit > self.engine.limits.max_depth:
            depth_limit = self.engine.limits.max_depth
        node_limit = beam_cfg.max_nodes or self.engine.limits.max_nodes
        edge_limit = beam_cfg.max_edges or self.engine.limits.max_edges
        node_limit = min(node_limit, self.engine.limits.max_nodes)
        edge_limit = min(edge_limit, self.engine.limits.max_edges)
        beam_width = min(beam_cfg.beam_width, node_limit)

        wanted_types = {
            str(value).strip()
            for value in edge_types
            if str(value).strip()
        }
        if not include_similarity and not wanted_types:
            wanted_types = set(LEGAL_EDGE_TYPE_NAMES)

        # Probe centroid set so off-centroid frontier fetches are detectable.
        try:
            self.engine._manifest_required()
            self._probe_centroid_paths(
                vector,
                candidate_centroids=beam_cfg.candidate_centroids,
            )
        except QueryBudgetExhausted as exc:
            return UscodeQueryResult(
                mode="semantic_graph_walk",
                query=str(query or start),
                results=(),
                diagnostics={"budget_exhausted": exc.to_dict()},
                fetch_trace=self.engine.fetch_trace(),
                complete=False,
                stop_reason=exc.dimension,
                usage=self.engine.usage.snapshot(),
                limits=self.engine.limits.to_dict(),
                explain={"traversal_strategy": "semantic_beam"},
                model_space=release.to_dict(),
                edges=(),
                sparse_io=sparse_io_summary(self.engine.fetch_trace()),
            )

        # Seed node.
        self.engine.usage.charge(nodes=1, depth=0)
        # Fetch seed embedding (may be on or off centroid).
        self.fetch_frontier_vectors(
            [start],
            query_vector=vector,
            candidate_centroids=beam_cfg.candidate_centroids,
        )
        seed_embedding = self._vector_cache.get(start)
        seed_proximity = cosine_similarity(seed_embedding, vector)

        total_w = (
            beam_cfg.proximity_weight
            + beam_cfg.edge_weight
            + beam_cfg.path_penalty
        )
        # Seed score: pure proximity (no edge, depth 0).
        seed_score = (
            beam_cfg.proximity_weight * max(0.0, seed_proximity)
            + beam_cfg.edge_weight * 1.0
            + beam_cfg.path_penalty * 1.0
        ) / total_w

        visited: dict[str, dict[str, Any]] = {
            start: {
                "depth": 0,
                "edge_weight": 1.0,
                "edge_type": None,
                "from_node_cid": None,
                "has_embedding": seed_embedding is not None,
                "node_cid": start,
                "score": seed_score,
                "semantic_proximity": seed_proximity,
            }
        }
        traversed: list[dict[str, Any]] = []
        # Beam frontier: list of (score, node_cid) sorted desc each depth.
        frontier: list[str] = [start]
        stop_reason: str | None = "depth" if depth_limit == 0 else None

        try:
            for depth in range(depth_limit):
                projected = depth + 1
                exhausted = self.engine.usage.check(
                    self.engine.limits,
                    projected_depth=projected,
                    raise_on_exhaustion=False,
                )
                if exhausted is not None:
                    stop_reason = exhausted
                    break

                candidates: list[tuple[float, str, dict[str, Any], dict[str, Any]]] = []
                for node_cid in frontier:
                    try:
                        edges = self.engine.fetch_adjacency(
                            node_cid,
                            direction=direction,
                            limit=beam_cfg.per_node_limit,
                            edge_types=tuple(sorted(wanted_types))
                            if wanted_types
                            else (),
                        )
                    except QueryBudgetExhausted as exc:
                        stop_reason = exc.dimension
                        frontier = []
                        break
                    if self.engine._stop_reason is not None:
                        stop_reason = self.engine._stop_reason
                        frontier = []
                        break

                    # Collect neighbor ids for batch frontier vector fetch.
                    neighbor_ids = [
                        str(edge.get("neighbor_cid") or "")
                        for edge in edges
                        if edge.get("neighbor_cid")
                    ]
                    if neighbor_ids:
                        self.fetch_frontier_vectors(
                            neighbor_ids,
                            query_vector=vector,
                            candidate_centroids=beam_cfg.candidate_centroids,
                        )
                    if self.engine._stop_reason is not None:
                        stop_reason = self.engine._stop_reason
                        frontier = []
                        break

                    for edge in edges:
                        neighbor = str(edge.get("neighbor_cid") or "")
                        if not neighbor:
                            continue
                        edge_type = str(edge.get("edge_type") or "")
                        if (
                            not include_similarity
                            and is_similarity_edge_type(edge_type)
                        ):
                            continue
                        if wanted_types and edge_type not in wanted_types:
                            continue
                        emb = self._vector_cache.get(neighbor)
                        proximity = cosine_similarity(emb, vector)
                        # Map cosine [-1,1] → [0,1] for blend.
                        proximity_unit = (proximity + 1.0) / 2.0
                        e_weight = _edge_weight_score(edge)
                        depth_factor = 1.0 / (1.0 + projected)
                        score = (
                            beam_cfg.proximity_weight * proximity_unit
                            + beam_cfg.edge_weight * e_weight
                            + beam_cfg.path_penalty * depth_factor
                        ) / total_w
                        annotated = annotate_edge_authority(
                            {
                                **edge,
                                "depth": projected,
                                "from_node_cid": node_cid,
                                "semantic_proximity": proximity,
                                "semantic_score": score,
                            }
                        )
                        candidates.append(
                            (
                                score,
                                neighbor,
                                {
                                    "depth": projected,
                                    "edge_weight": e_weight,
                                    "edge_type": edge_type,
                                    "from_node_cid": node_cid,
                                    "has_embedding": emb is not None,
                                    "node_cid": neighbor,
                                    "score": score,
                                    "semantic_proximity": proximity,
                                },
                                annotated,
                            )
                        )

                if stop_reason is not None:
                    break

                # Deterministic beam selection: score desc, neighbor_cid asc.
                candidates.sort(
                    key=lambda item: (-item[0], item[1], str(item[3].get("edge_cid") or ""))
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
                        self.engine.usage.charge(nodes=1, depth=projected)
                    elif score > float(visited[neighbor].get("score") or 0.0):
                        # Keep best score path but do not re-expand.
                        visited[neighbor] = {
                            **visited[neighbor],
                            **node_payload,
                        }
                    traversed.append(edge_payload)
                    if len(next_frontier) >= beam_width:
                        # Beam filled for this depth; continue charging edges
                        # already accepted above only for selected beam.
                        break

                if stop_reason is not None:
                    break
                # Trim frontier to beam width (already limited while filling).
                frontier = next_frontier[:beam_width]
                if not frontier:
                    stop_reason = None  # complete: frontier exhausted
                    break
                self.engine.usage.charge(depth=projected)
            else:
                if stop_reason is None and depth_limit > 0 and frontier:
                    stop_reason = "depth"
        except QueryBudgetExhausted as exc:
            stop_reason = exc.dimension

        assert_no_similarity_as_legal_authority(traversed)

        nodes = [
            dict(payload)
            for _, payload in sorted(
                visited.items(),
                key=lambda item: (
                    int(item[1].get("depth") or 0),
                    -float(item[1].get("score") or 0.0),
                    item[0],
                ),
            )
        ]
        complete = stop_reason is None
        usage = self.engine.usage.snapshot()
        limits = self.engine.limits.to_dict()
        diagnostics = {
            "beam_width": beam_width,
            "budgets_enforced": list(BUDGET_DIMENSIONS),
            "candidate_centroids": beam_cfg.candidate_centroids,
            "centroid_routed_paths": sorted(self._centroid_routed_paths),
            "complete": complete,
            "direction": direction,
            "edge_count": len(traversed),
            "frontier_fetch_paths": sorted(self._frontier_fetch_paths),
            "include_similarity": include_similarity,
            "max_depth": depth_limit,
            "max_edges": edge_limit,
            "max_nodes": node_limit,
            "node_count": len(visited),
            "off_centroid_fetch_paths": sorted(self._off_centroid_fetch_paths),
            "off_centroid_frontier_vectors_fetched": bool(
                self._off_centroid_fetch_paths
            ),
            "per_node_limit": beam_cfg.per_node_limit,
            "start_node_cid": start,
            "stop_reason": stop_reason,
            "traversal_strategy": "semantic_beam",
            "vector_cache_size": len(self._vector_cache),
        }
        explain = {
            "beam": beam_cfg.to_dict(),
            "blend": {
                "edge_weight": beam_cfg.edge_weight,
                "path_penalty": beam_cfg.path_penalty,
                "proximity_weight": beam_cfg.proximity_weight,
            },
            "budgets_enforced": list(BUDGET_DIMENSIONS),
            "direct_cid_frontier_fetch": True,
            "off_centroid_selective_fetch": True,
            "similarity_edge_semantics": similarity_edge_semantics(),
            "similarity_never_legal_authority": True,
            "traversal_strategy": "semantic_beam",
            "vector_space_id": release.vector_space_id,
        }
        return UscodeQueryResult(
            mode="semantic_graph_walk",
            query=str(query or start),
            results=tuple(nodes),
            diagnostics=diagnostics,
            fetch_trace=self.engine.fetch_trace(),
            complete=complete,
            stop_reason=stop_reason,
            usage=usage,
            limits=limits,
            explain=explain,
            model_space=release.to_dict(),
            edges=tuple(traversed),
            sparse_io=sparse_io_summary(self.engine.fetch_trace()),
        )


# ---------------------------------------------------------------------------
# Module-level convenience wrappers
# ---------------------------------------------------------------------------


def hybrid_search(
    client: UscodeQueryClient,
    query: str,
    **kwargs: Any,
) -> UscodeQueryResult:
    """Module-level hybrid search entry point."""

    return client.hybrid_search(query, **kwargs)


def neighbors(
    client: UscodeQueryClient,
    node_cid: str,
    **kwargs: Any,
) -> UscodeQueryResult:
    """Module-level neighbors entry point."""

    return client.neighbors(node_cid, **kwargs)


def graph_walk(
    client: UscodeQueryClient,
    start_node_cid: str,
    **kwargs: Any,
) -> UscodeQueryResult:
    """Module-level structural graph walk entry point."""

    return client.graph_walk(start_node_cid, **kwargs)


def semantic_graph_walk(
    client: UscodeQueryClient,
    start_node_cid: str,
    **kwargs: Any,
) -> UscodeQueryResult:
    """Module-level semantic beam walk entry point."""

    return client.semantic_graph_walk(start_node_cid, **kwargs)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def default_uscode_query_expected_fixture_path() -> Path:
    """Repository path for the sealed US Code query fixture."""

    return (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "legal_ir"
        / "uscode_query_expected.json"
    )


def build_default_uscode_query_expected_fixture_payload() -> dict[str, Any]:
    """Compact deterministic recipes for USCIR-027 unit tests.

    A miniature offline release is regenerated at test time; expected fusion
    component-score preservation, budget stop semantics, off-centroid frontier
    fetch, and similarity-never-authority rules are asserted without bulk
    golden dumps.
    """

    return {
        "acceptance": {
            "graph_walks_enforce_all_budgets": True,
            "hybrid_explanations_preserve_component_scores": True,
            "off_centroid_frontier_vectors_selectively_fetched": True,
            "similarity_edges_never_legal_authority": True,
        },
        "bounds": {
            "budget_dimensions": list(BUDGET_DIMENSIONS),
            "default_beam_width": DEFAULT_BEAM_WIDTH,
            "default_bm25_weight": DEFAULT_BM25_WEIGHT,
            "default_rrf_k": DEFAULT_RRF_K,
            "default_top_k": DEFAULT_TOP_K,
            "default_vector_weight": DEFAULT_VECTOR_WEIGHT,
            "fusion_methods": sorted(FUSION_METHODS),
            "max_top_k": MAX_TOP_K,
        },
        "cases": [
            {
                "expected_component_score_keys": ["bm25", "vector"],
                "expected_top_entry_cid": "entry-a",
                "fusion": {
                    "bm25_weight": 0.5,
                    "method": "weighted",
                    "vector_weight": 0.5,
                },
                "id": "hybrid_weighted_preserves_component_scores",
                "mode": "hybrid",
                "query": "foia agency",
                "query_vector": [1.0, 0.0],
                "top_k": 3,
            },
            {
                "expected_component_score_keys": ["bm25", "vector"],
                "fusion": {
                    "bm25_weight": 1.0,
                    "method": "rrf",
                    "rrf_k": 60,
                    "vector_weight": 1.0,
                },
                "id": "hybrid_rrf_preserves_component_scores",
                "mode": "hybrid",
                "query": "agency privacy",
                "query_vector": [1.0, 0.0],
                "top_k": 3,
            },
            {
                "expected_stop_reason": "nodes",
                "id": "graph_walk_enforces_node_budget",
                "max_depth": 3,
                "max_nodes": 2,
                "mode": "graph_walk",
                "start_node_cid": "node-a",
            },
            {
                "expected_off_centroid_fetch": True,
                "id": "semantic_beam_off_centroid_frontier_fetch",
                "max_depth": 2,
                "mode": "semantic_graph_walk",
                "query": "foia",
                "query_vector": [1.0, 0.0],
                "start_node_cid": "node-a",
            },
            {
                "edge_type": "BM25_NEIGHBOR_OF",
                "expected_legal_authority": False,
                "expected_proof_authority": False,
                "id": "similarity_edge_never_legal_authority",
                "mode": "authority",
            },
            {
                "filter_title": "5",
                "id": "legal_title_filter",
                "mode": "hybrid",
                "query": "agency",
                "query_vector": [1.0, 0.0],
                "top_k": 5,
            },
        ],
        "description": (
            "Compact deterministic recipes for USCIR-027 legal hybrid and "
            "embedding-guided graph query unit tests. A miniature offline "
            "release is regenerated at test time; hybrid component scores, "
            "budget enforcement, off-centroid frontier vector fetch, and "
            "similarity-never-authority rules are asserted without bulk "
            "golden dumps."
        ),
        "goal_id": GOAL_ID,
        "producer": PRODUCER,
        "query_schema_version": SCHEMA_VERSION,
        "release_profile": RELEASE_PROFILE,
        "route_families": sorted(ROUTE_FAMILIES),
        "route_reasons": sorted(ROUTE_REASONS),
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "similarity_edge_semantics": similarity_edge_semantics(),
        "task_id": TASK_ID,
    }


def load_uscode_query_expected_fixture(
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Load and lightly validate the sealed query expected fixture."""

    target = (
        Path(path)
        if path is not None
        else default_uscode_query_expected_fixture_path()
    )
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise UscodeQueryInputError(
            "uscode_query_expected fixture must be an object"
        )
    if payload.get("schema_version") != FIXTURE_SCHEMA_VERSION:
        raise UscodeQueryInputError(
            "uscode_query_expected fixture schema_version mismatch"
        )
    if payload.get("task_id") != TASK_ID:
        raise UscodeQueryInputError(
            "uscode_query_expected fixture task_id mismatch"
        )
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise UscodeQueryInputError(
            "uscode_query_expected fixture has no cases"
        )
    return dict(payload)


def write_uscode_query_expected_fixture(
    path: str | Path | None = None,
) -> Path:
    """Write the sealed compact fixture (deterministic, no timestamps)."""

    target = (
        Path(path)
        if path is not None
        else default_uscode_query_expected_fixture_path()
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_default_uscode_query_expected_fixture_payload()
    target.write_text(
        canonical_json_dumps(payload) + "\n",
        encoding="utf-8",
    )
    return target


__all__ = [
    "AUTHORITY_LEGAL",
    "AUTHORITY_NON_AUTHORITATIVE",
    "DEFAULT_BEAM_WIDTH",
    "DEFAULT_BM25_WEIGHT",
    "DEFAULT_RRF_K",
    "DEFAULT_VECTOR_WEIGHT",
    "FIXTURE_SCHEMA_VERSION",
    "FUSION_METHODS",
    "FUSION_RRF",
    "FUSION_WEIGHTED",
    "GOAL_ID",
    "LEGAL_EDGE_TYPE_NAMES",
    "SCHEMA_VERSION",
    "SIMILARITY_EDGE_TYPE_NAMES",
    "TASK_ID",
    "FusionConfig",
    "FusionConfigError",
    "LegalAuthorityCollisionError",
    "LegalFilters",
    "SemanticBeamConfig",
    "UscodeQueryClient",
    "UscodeQueryError",
    "UscodeQueryInputError",
    "UscodeQueryResult",
    "annotate_edge_authority",
    "apply_legal_filters",
    "assert_no_similarity_as_legal_authority",
    "build_default_uscode_query_expected_fixture_payload",
    "classify_edge_authority",
    "cosine_similarity",
    "default_uscode_query_expected_fixture_path",
    "edge_class_for_type",
    "fuse_hybrid_results",
    "graph_walk",
    "hit_matches_legal_filters",
    "hybrid_search",
    "is_legal_edge_type",
    "is_similarity_edge_type",
    "load_uscode_query_expected_fixture",
    "neighbors",
    "query_replay_fingerprint",
    "select_vector_shards_for_keys",
    "semantic_graph_walk",
    "similarity_edge_semantics",
    "write_uscode_query_expected_fixture",
]
