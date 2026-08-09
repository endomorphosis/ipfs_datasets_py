"""Direct remote BM25 and vector search modes for HF GraphRAG (USCIR-026).

Public packaging of generic BM25 / vector modes on top of the bounded remote
query engine (USCIR-025):

* ``bm25_search`` — term-range routing only, field-weighted scoring, stable
  ranking, filters, selective hydration, and explanations;
* ``vector_search`` — centroid routing plus exact cosine scoring only, with an
  exact model-space query embedding hook that fails closed on mutable or
  mismatched model space;
* ranking normalization and stable ``(score desc, entry_cid, document_index)``
  tie-breaks;
* sparse I/O proven by compact fetch-trace fixtures.

Legal-domain weighting and hybrid/graph fusion belong to USCIR-027.  This
module owns generic public BM25/vector modes and ranking normalization only.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import json
import math
import re
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final

from .query import (
    DEFAULT_CANDIDATE_CENTROIDS,
    DEFAULT_TOP_K,
    MAX_TOP_K,
    BoundedRemoteQueryEngine,
    QueryBudgetExhausted,
    QueryEngineError,
    QueryEngineResult,
    QueryInputError,
    QueryIntegrityError,
    QueryLimits,
    ROUTE_FAMILIES,
    ROUTE_REASONS,
    RouteJustification,
    select_document_index_shards,
)
from .resolver import ImmutableHubResolver
from .schema import (
    DEFAULT_CANDIDATE_CENTROIDS as SCHEMA_DEFAULT_CANDIDATE_CENTROIDS,
    canonical_json_dumps,
    content_sha256,
)

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

TASK_ID: Final = "USCIR-026"
GOAL_ID: Final = "USCIR-G070"
REMOTE_SEARCH_SCHEMA_VERSION: Final = "hf-graphrag-remote-search/v1"
REMOTE_SEARCH_RESULTS_FIXTURE_SCHEMA: Final = (
    "hf-graphrag-remote-search-results/v1"
)
DEFAULT_MANIFEST_NAME: Final = "manifest.json"

# BM25 data-plane fetches must only use term-range routes.
BM25_ALLOWED_DATA_REASONS: Final = frozenset({"term_range"})
# Vector data-plane fetches must only use exact scoring of centroid-selected
# shards (centroid_probe is informational and does not download).
VECTOR_ALLOWED_DATA_REASONS: Final = frozenset({"exact_vector_score"})
# Shared non-data-plane reasons that both modes may emit.
CONTROL_ROUTE_REASONS: Final = frozenset(
    {"manifest", "routing_index", "control_plane", "hydrate_hit", "replay"}
)

# Mutable / placeholder tokens rejected for model space pins.
_MUTABLE_REVISION_RE: Final = re.compile(
    r"^(?:latest|main|master|head|default|current|tip|trunk|dev|develop|"
    r"development|staging|prod|production|release|stable|nightly|canary|"
    r"refs/.+|origin/.+)$",
    re.IGNORECASE,
)
_PLACEHOLDER_MODEL_RE: Final = re.compile(
    r"^(?:placeholder|unknown|none|null|n/?a|na|mock|dummy|todo|tbd|"
    r"example|test|fake|unset|missing|unspecified|default|auto|"
    r"changeme|replace.?me|your.?model|model.?name)$",
    re.IGNORECASE,
)
_SHA1_HEX_RE: Final = re.compile(r"^[0-9a-f]{40}$")
_SHA256_HEX_RE: Final = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")

# Filter field aliases accepted from hit metadata / corpus rows.
_FILTER_FIELD_ALIASES: Final = MappingProxyType(
    {
        "title": ("title", "title_number", "uscode_title"),
        "chapter": ("chapter", "chapter_number", "uscode_chapter"),
        "section": ("section", "section_number", "uscode_section"),
        "source": ("source", "source_id", "source_package", "corpus_source"),
        "release_point": (
            "release_point",
            "release_point_id",
            "release",
            "usc_release_point",
        ),
        "entry_cid": ("entry_cid",),
        "document_index": ("document_index",),
        "node_type": ("node_type", "type"),
        "edge_type": ("edge_type",),
    }
)

QueryEmbedder = Callable[["str", "ModelSpace"], Sequence[float]]


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class RemoteSearchError(QueryEngineError):
    """Base error for direct remote BM25 / vector search modes."""


class RemoteSearchInputError(RemoteSearchError, QueryInputError):
    """Raised when search inputs or filters are malformed."""


class RemoteSearchIntegrityError(RemoteSearchError, QueryIntegrityError):
    """Raised when release metadata fails integrity checks for search modes."""


class ModelSpaceError(RemoteSearchError):
    """Raised when model-space identity is missing, mutable, or mismatched."""

    code: str = "model_space_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class MutableModelSpaceError(ModelSpaceError):
    """Raised when a model/revision/space pin is mutable or a placeholder."""

    code = "mutable_model_space"


class ModelSpaceMismatchError(ModelSpaceError):
    """Raised when the query model space does not match the release pin."""

    code = "model_space_mismatch"


class SparseIoContractError(RemoteSearchError):
    """Raised when a search fetch-trace violates the sparse I/O contract."""

    code = "sparse_io_violation"


# ---------------------------------------------------------------------------
# Model space
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RemoteSearchInputError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise RemoteSearchInputError(f"{name} must not contain NUL")
    if len(text) > maximum:
        raise RemoteSearchInputError(f"{name} exceeds maximum length {maximum}")
    return text


def _require_positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise RemoteSearchInputError(f"{name} must be a positive integer")
    return value


def is_mutable_revision_token(value: Any) -> bool:
    """Return True when *value* is a known mutable / branch-like revision."""

    if not isinstance(value, str) or not value.strip():
        return True
    text = value.strip()
    if _MUTABLE_REVISION_RE.fullmatch(text):
        return True
    lowered = text.lower()
    if "/resolve/main/" in lowered or "/tree/main/" in lowered:
        return True
    return False


def is_placeholder_model_token(value: Any) -> bool:
    """Return True when *value* is a known placeholder model identity."""

    if not isinstance(value, str) or not value.strip():
        return True
    text = value.strip()
    if _PLACEHOLDER_MODEL_RE.fullmatch(text):
        return True
    tail = text.rsplit("/", 1)[-1]
    return bool(_PLACEHOLDER_MODEL_RE.fullmatch(tail))


def is_immutable_model_revision(value: Any) -> bool:
    """Accept 40-hex git SHA or SHA-256 digest pins only."""

    if not isinstance(value, str) or not value.strip():
        return False
    text = value.strip().lower()
    if is_mutable_revision_token(text):
        return False
    if _SHA1_HEX_RE.fullmatch(text):
        return True
    if _SHA256_HEX_RE.fullmatch(text):
        return True
    return False


def require_immutable_model_revision(
    value: Any, *, name: str = "model_revision"
) -> str:
    """Fail closed unless *value* is an immutable model revision pin."""

    if is_mutable_revision_token(value) or not is_immutable_model_revision(value):
        raise MutableModelSpaceError(
            f"{name} must be an immutable git SHA or SHA-256 pin, not "
            f"{value!r}"
        )
    text = str(value).strip().lower()
    if text.startswith("sha256:"):
        return text
    return text


@dataclass(frozen=True, slots=True)
class ModelSpace:
    """Exact vector model-space identity for query/release matching.

    Query-time embeddings must bind the same model pin, dimension, and
    normalization policy as the release.  Cross-space vectors fail closed.
    """

    model_id: str
    model_revision: str
    vector_space_id: str
    dimension: int
    normalization: str = "l2"
    pooling: str = ""
    model_name: str = ""

    def __post_init__(self) -> None:
        model_id = _require_non_empty_str(self.model_id, "model_id")
        if is_placeholder_model_token(model_id):
            raise MutableModelSpaceError(
                f"model_id must not be a placeholder: {self.model_id!r}"
            )
        if is_mutable_revision_token(model_id):
            raise MutableModelSpaceError(
                f"model_id must not be a mutable token: {self.model_id!r}"
            )
        revision = require_immutable_model_revision(
            self.model_revision, name="model_revision"
        )
        space = _require_non_empty_str(
            self.vector_space_id, "vector_space_id", maximum=512
        )
        if is_placeholder_model_token(space) or is_mutable_revision_token(space):
            raise MutableModelSpaceError(
                f"vector_space_id must not be a mutable/placeholder token: "
                f"{self.vector_space_id!r}"
            )
        dimension = _require_positive_int(self.dimension, "dimension")
        if dimension > 8192:
            raise RemoteSearchInputError("dimension exceeds hard bound 8192")
        normalization = _require_non_empty_str(
            self.normalization, "normalization", maximum=64
        ).lower()
        pooling = str(self.pooling or "").strip().lower()
        model_name = str(self.model_name or "").strip()
        object.__setattr__(self, "model_id", model_id)
        object.__setattr__(self, "model_revision", revision)
        object.__setattr__(self, "vector_space_id", space)
        object.__setattr__(self, "dimension", dimension)
        object.__setattr__(self, "normalization", normalization)
        object.__setattr__(self, "pooling", pooling)
        object.__setattr__(self, "model_name", model_name)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "dimension": self.dimension,
            "model_id": self.model_id,
            "model_revision": self.model_revision,
            "normalization": self.normalization,
            "vector_space_id": self.vector_space_id,
        }
        if self.pooling:
            payload["pooling"] = self.pooling
        if self.model_name:
            payload["model_name"] = self.model_name
        return payload

    def matches(self, other: "ModelSpace") -> bool:
        """Return True when both spaces share exact query-critical identity."""

        if not isinstance(other, ModelSpace):
            return False
        return (
            self.model_id == other.model_id
            and self.model_revision == other.model_revision
            and self.vector_space_id == other.vector_space_id
            and self.dimension == other.dimension
            and self.normalization == other.normalization
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "ModelSpace":
        if not isinstance(value, Mapping):
            raise RemoteSearchInputError("model space must be a mapping")
        model_id = (
            value.get("model_id")
            or value.get("model_name")
            or value.get("model")
        )
        revision = (
            value.get("model_revision")
            or value.get("revision")
            or value.get("model_sha")
        )
        space = (
            value.get("vector_space_id")
            or value.get("model_space")
            or value.get("space_id")
        )
        dimension = value.get("dimension")
        if dimension is None:
            dimension = value.get("dims")
        normalization = value.get("normalization") or value.get("norm") or "l2"
        pooling = value.get("pooling") or ""
        model_name = str(value.get("model_name") or model_id or "")
        if space is None or space == "":
            # Synthesize a stable space id when the release only pin-binds
            # model + revision + dimension (common in compact fixtures).
            if model_id and revision and dimension is not None:
                short = str(model_id).rsplit("/", 1)[-1].lower()
                short = re.sub(r"[^a-z0-9._-]+", "-", short)
                space = (
                    f"{short}@{str(revision).strip().lower()}"
                    f":d{int(dimension)}:norm={str(normalization).lower()}"
                )
        return cls(
            model_id=str(model_id or ""),
            model_revision=str(revision or ""),
            vector_space_id=str(space or ""),
            dimension=int(dimension) if dimension is not None else 0,
            normalization=str(normalization),
            pooling=str(pooling),
            model_name=model_name,
        )


def extract_release_model_space(manifest: Mapping[str, Any]) -> ModelSpace:
    """Extract and validate the release vector model space from *manifest*."""

    if not isinstance(manifest, Mapping):
        raise RemoteSearchIntegrityError("manifest must be a mapping")
    vector = manifest.get("vector")
    if not isinstance(vector, Mapping):
        # Fall back to top-level keys used by some compact manifests.
        vector = {
            key: manifest[key]
            for key in (
                "model_id",
                "model_name",
                "model_revision",
                "vector_space_id",
                "dimension",
                "normalization",
                "pooling",
            )
            if key in manifest
        }
    if not vector:
        raise ModelSpaceError(
            "release manifest is missing vector model-space metadata",
            code="missing_model_space",
        )
    try:
        return ModelSpace.from_mapping(vector)
    except ModelSpaceError:
        raise
    except RemoteSearchError:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        raise ModelSpaceError(
            f"release model space is invalid: {exc}",
            code="invalid_model_space",
        ) from exc


def assert_model_space_compatible(
    release: ModelSpace,
    query: ModelSpace | Mapping[str, Any] | None,
    *,
    query_vector: Sequence[float] | None = None,
) -> ModelSpace:
    """Fail closed on mutable or mismatched query/release model spaces.

    Returns the validated release space.  When *query* is provided it must
    match the release exactly on model pin, vector_space_id, dimension, and
    normalization.  Query vector length must equal the release dimension.
    """

    if not isinstance(release, ModelSpace):
        raise ModelSpaceError("release model space is required")
    # Release itself was already validated by ModelSpace.__post_init__.
    if query is not None:
        query_space = (
            query
            if isinstance(query, ModelSpace)
            else ModelSpace.from_mapping(query)
        )
        if not release.matches(query_space):
            raise ModelSpaceMismatchError(
                "query model space does not match release pin: "
                f"release={release.to_dict()!r} query={query_space.to_dict()!r}"
            )
    if query_vector is not None:
        if not isinstance(query_vector, Sequence) or isinstance(
            query_vector, (str, bytes, bytearray)
        ):
            raise RemoteSearchInputError(
                "query_vector must be a finite numeric sequence"
            )
        if len(query_vector) != release.dimension:
            raise ModelSpaceMismatchError(
                f"query_vector dimension {len(query_vector)} does not match "
                f"release dimension {release.dimension}"
            )
        for offset, value in enumerate(query_vector):
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise RemoteSearchInputError(
                    f"query_vector[{offset}] must be numeric"
                )
            if not math.isfinite(float(value)):
                raise RemoteSearchInputError(
                    f"query_vector[{offset}] must be finite"
                )
    return release


# ---------------------------------------------------------------------------
# Filters + ranking
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SearchFilters:
    """Optional post-score filters applied to hydrated or score-only hits.

    Domain-neutral field names; legal adapters (USCIR-027) may map richer
    ontology onto these keys.  Empty filters match everything.
    """

    title: str | None = None
    chapter: str | None = None
    section: str | None = None
    source: str | None = None
    release_point: str | None = None
    entry_cids: tuple[str, ...] = ()
    document_indexes: tuple[int, ...] = ()
    node_types: tuple[str, ...] = ()
    edge_types: tuple[str, ...] = ()
    metadata_equals: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        def _opt(value: Any, name: str) -> str | None:
            if value is None or value == "":
                return None
            return _require_non_empty_str(value, name, maximum=256)

        object.__setattr__(self, "title", _opt(self.title, "title"))
        object.__setattr__(self, "chapter", _opt(self.chapter, "chapter"))
        object.__setattr__(self, "section", _opt(self.section, "section"))
        object.__setattr__(self, "source", _opt(self.source, "source"))
        object.__setattr__(
            self, "release_point", _opt(self.release_point, "release_point")
        )
        entry_cids = tuple(
            _require_non_empty_str(item, "entry_cids[]", maximum=256)
            for item in (self.entry_cids or ())
        )
        object.__setattr__(self, "entry_cids", entry_cids)
        indexes: list[int] = []
        for item in self.document_indexes or ():
            if isinstance(item, bool) or not isinstance(item, int):
                raise RemoteSearchInputError(
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
            raise RemoteSearchInputError("metadata_equals must be a mapping")
        object.__setattr__(
            self, "metadata_equals", MappingProxyType(dict(self.metadata_equals))
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
                self.entry_cids,
                self.document_indexes,
                self.node_types,
                self.edge_types,
                self.metadata_equals,
            )
        )

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for key in (
            "title",
            "chapter",
            "section",
            "source",
            "release_point",
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
        cls, value: Mapping[str, Any] | None = None
    ) -> "SearchFilters":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise RemoteSearchInputError("filters must be a mapping")
        kwargs: dict[str, Any] = {}
        for key in (
            "title",
            "chapter",
            "section",
            "source",
            "release_point",
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


def _hit_field(hit: Mapping[str, Any], logical: str) -> Any:
    aliases = _FILTER_FIELD_ALIASES.get(logical, (logical,))
    for name in aliases:
        if name in hit and hit[name] not in (None, ""):
            return hit[name]
    return None


def hit_matches_filters(
    hit: Mapping[str, Any],
    filters: SearchFilters | Mapping[str, Any] | None,
) -> bool:
    """Return True when *hit* satisfies all declared filters."""

    filt = (
        filters
        if isinstance(filters, SearchFilters)
        else SearchFilters.from_mapping(filters)
    )
    if filt.is_empty:
        return True
    if not isinstance(hit, Mapping):
        return False

    def _eq(expected: str | None, logical: str) -> bool:
        if expected is None:
            return True
        actual = _hit_field(hit, logical)
        if actual is None:
            return False
        return str(actual).strip().lower() == expected.strip().lower()

    if not _eq(filt.title, "title"):
        return False
    if not _eq(filt.chapter, "chapter"):
        return False
    if not _eq(filt.section, "section"):
        return False
    if not _eq(filt.source, "source"):
        return False
    if not _eq(filt.release_point, "release_point"):
        return False
    if filt.entry_cids:
        cid = str(hit.get("entry_cid") or "")
        if cid not in filt.entry_cids:
            return False
    if filt.document_indexes:
        doc = hit.get("document_index")
        if doc is None or int(doc) not in filt.document_indexes:
            return False
    if filt.node_types:
        node_type = str(_hit_field(hit, "node_type") or "")
        if node_type not in filt.node_types:
            return False
    if filt.edge_types:
        edge_type = str(_hit_field(hit, "edge_type") or "")
        if edge_type not in filt.edge_types:
            return False
    for key, expected in filt.metadata_equals.items():
        if hit.get(key) != expected:
            return False
    return True


def apply_filters(
    hits: Sequence[Mapping[str, Any]],
    filters: SearchFilters | Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    """Filter hits while preserving input order."""

    return [
        dict(hit)
        for hit in hits
        if hit_matches_filters(hit, filters)
    ]


def ranking_key(hit: Mapping[str, Any]) -> tuple[Any, ...]:
    """Stable ranking key: score desc, entry_cid asc, document_index asc."""

    score = hit.get("score")
    if score is None or not isinstance(score, (int, float)) or isinstance(
        score, bool
    ):
        score_key = float("-inf")
    else:
        score_key = float(score)
        if not math.isfinite(score_key):
            score_key = float("-inf")
    entry_cid = str(hit.get("entry_cid") or "")
    doc = hit.get("document_index")
    if isinstance(doc, bool) or not isinstance(doc, int):
        doc_key = 2**62
    else:
        doc_key = int(doc)
    return (-score_key, entry_cid, doc_key)


def stable_rank(
    hits: Sequence[Mapping[str, Any]],
    *,
    top_k: int | None = None,
) -> list[dict[str, Any]]:
    """Sort hits with stable tie-breaks; optionally truncate to *top_k*."""

    ordered = sorted((dict(hit) for hit in hits), key=ranking_key)
    if top_k is not None:
        limit = _require_positive_int(top_k, "top_k")
        if limit > MAX_TOP_K:
            raise RemoteSearchInputError(f"top_k must be <= {MAX_TOP_K}")
        ordered = ordered[:limit]
    return ordered


def normalize_scores(
    hits: Sequence[Mapping[str, Any]],
    *,
    method: str = "minmax",
) -> list[dict[str, Any]]:
    """Attach ``normalized_score`` without changing rank order.

    Methods:
    * ``minmax`` — scale to ``[0, 1]`` (constant scores become ``1.0``);
    * ``none`` — copy raw score into ``normalized_score``.
    """

    method_norm = str(method or "minmax").strip().lower()
    if method_norm not in {"minmax", "none"}:
        raise RemoteSearchInputError(
            f"unknown score normalization method: {method!r}"
        )
    rows = [dict(hit) for hit in hits]
    if not rows:
        return rows
    scores = [
        float(row["score"])
        if isinstance(row.get("score"), (int, float))
        and not isinstance(row.get("score"), bool)
        and math.isfinite(float(row["score"]))
        else 0.0
        for row in rows
    ]
    if method_norm == "none":
        for row, score in zip(rows, scores):
            row["normalized_score"] = score
        return rows
    lo = min(scores)
    hi = max(scores)
    span = hi - lo
    for row, score in zip(rows, scores):
        if span <= 0.0:
            row["normalized_score"] = 1.0
        else:
            row["normalized_score"] = (score - lo) / span
    return rows


# ---------------------------------------------------------------------------
# Sparse I/O contract
# ---------------------------------------------------------------------------


def _trace_files(fetch_trace: Mapping[str, Any]) -> list[dict[str, Any]]:
    files = fetch_trace.get("files") if isinstance(fetch_trace, Mapping) else None
    if not isinstance(files, list):
        return []
    return [dict(item) for item in files if isinstance(item, Mapping)]


def assert_bm25_sparse_io(fetch_trace: Mapping[str, Any]) -> None:
    """Prove BM25 data-plane fetches use only term-range routes."""

    for item in _trace_files(fetch_trace):
        route = item.get("route") or {}
        if not isinstance(route, Mapping):
            raise SparseIoContractError("fetch-trace route must be a mapping")
        family = str(route.get("family") or "")
        reason = str(route.get("reason") or "")
        if family == "bm25_postings" and reason not in BM25_ALLOWED_DATA_REASONS:
            raise SparseIoContractError(
                f"BM25 data-plane fetch used non-term-range reason {reason!r} "
                f"for {route.get('relative_path')!r}"
            )
        if family == "vectors":
            raise SparseIoContractError(
                "BM25 search must not fetch vector shards"
            )


def assert_vector_sparse_io(fetch_trace: Mapping[str, Any]) -> None:
    """Prove vector data-plane fetches use only centroid exact-score routes."""

    for item in _trace_files(fetch_trace):
        route = item.get("route") or {}
        if not isinstance(route, Mapping):
            raise SparseIoContractError("fetch-trace route must be a mapping")
        family = str(route.get("family") or "")
        reason = str(route.get("reason") or "")
        if family == "vectors" and reason not in VECTOR_ALLOWED_DATA_REASONS:
            raise SparseIoContractError(
                f"vector data-plane fetch used non-exact-score reason "
                f"{reason!r} for {route.get('relative_path')!r}"
            )
        if family == "bm25_postings":
            raise SparseIoContractError(
                "vector search must not fetch BM25 posting shards"
            )


def sparse_io_summary(fetch_trace: Mapping[str, Any]) -> dict[str, Any]:
    """Compact sparse-I/O summary for fixtures and diagnostics."""

    families: set[str] = set()
    reasons: set[str] = set()
    paths: list[str] = []
    data_plane_paths: list[str] = []
    for item in _trace_files(fetch_trace):
        route = item.get("route") or {}
        family = str(route.get("family") or "")
        reason = str(route.get("reason") or "")
        path = str(item.get("relative_path") or route.get("relative_path") or "")
        if family:
            families.add(family)
        if reason:
            reasons.add(reason)
        if path:
            paths.append(path)
            if family in {"bm25_postings", "vectors", "corpus"}:
                data_plane_paths.append(path)
    return {
        "data_plane_paths": sorted(set(data_plane_paths)),
        "families": sorted(families),
        "file_count": len(_trace_files(fetch_trace)),
        "paths": sorted(set(paths)),
        "reasons": sorted(reasons),
        "total_file_bytes": int(
            (fetch_trace or {}).get("total_file_bytes") or 0
        ),
    }


# ---------------------------------------------------------------------------
# Result packaging
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RemoteSearchResult:
    """Public BM25 / vector search result with sparse-I/O diagnostics."""

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
    sparse_io: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = REMOTE_SEARCH_SCHEMA_VERSION
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
        return payload

    @classmethod
    def from_engine_result(
        cls,
        engine_result: QueryEngineResult,
        *,
        mode: str,
        query: str,
        filters: SearchFilters | Mapping[str, Any] | None = None,
        model_space: ModelSpace | Mapping[str, Any] | None = None,
        results: Sequence[Mapping[str, Any]] | None = None,
        explain: Mapping[str, Any] | None = None,
        diagnostics_extra: Mapping[str, Any] | None = None,
    ) -> "RemoteSearchResult":
        filt = (
            filters
            if isinstance(filters, SearchFilters)
            else SearchFilters.from_mapping(filters)
        )
        space_payload: dict[str, Any] = {}
        if isinstance(model_space, ModelSpace):
            space_payload = model_space.to_dict()
        elif isinstance(model_space, Mapping):
            space_payload = dict(model_space)
        hits = (
            [dict(item) for item in results]
            if results is not None
            else [dict(item) for item in engine_result.results]
        )
        diagnostics = dict(engine_result.diagnostics)
        if diagnostics_extra:
            diagnostics.update(dict(diagnostics_extra))
        explain_payload = dict(engine_result.explain)
        if explain:
            explain_payload.update(dict(explain))
        sparse = sparse_io_summary(engine_result.fetch_trace)
        return cls(
            mode=mode,
            query=query,
            results=tuple(hits),
            diagnostics=diagnostics,
            fetch_trace=dict(engine_result.fetch_trace),
            complete=engine_result.complete,
            stop_reason=engine_result.stop_reason,
            usage=dict(engine_result.usage),
            limits=dict(engine_result.limits),
            explain=explain_payload,
            filters=filt.to_dict(),
            model_space=space_payload,
            sparse_io=sparse,
        )


def remote_replay_fingerprint(result: RemoteSearchResult | Mapping[str, Any]) -> str:
    """Stable fingerprint for offline replay of public search modes."""

    if isinstance(result, RemoteSearchResult):
        payload = {
            "complete": result.complete,
            "filters": dict(result.filters),
            "mode": result.mode,
            "model_space": dict(result.model_space),
            "ordered_result_cids": list(result.ordered_result_cids()),
            "query": result.query,
            "result_count": result.result_count,
            "stop_reason": result.stop_reason,
        }
    else:
        if not isinstance(result, Mapping):
            raise RemoteSearchInputError("result must be a mapping")
        payload = {
            "complete": bool(result.get("complete")),
            "filters": dict(result.get("filters") or {}),
            "mode": result.get("mode"),
            "model_space": dict(result.get("model_space") or {}),
            "ordered_result_cids": list(result.get("ordered_result_cids") or []),
            "query": result.get("query"),
            "result_count": result.get("result_count"),
            "stop_reason": result.get("stop_reason"),
        }
    return content_sha256(canonical_json_dumps(payload))


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class RemoteSearchClient:
    """Direct remote BM25 and vector search over a pinned HF GraphRAG release.

    Parameters
    ----------
    resolver:
        Pinned :class:`ImmutableHubResolver` (immutable revision required).
    limits:
        Optional per-query budgets forwarded to the bounded engine.
    engine:
        Optional pre-built :class:`BoundedRemoteQueryEngine`.  When omitted a
        new engine is constructed from *resolver* / *limits*.
    query_embedder:
        Optional exact model-space embedding hook.  Called as
        ``embedder(query_text, release_model_space) -> vector``.  The returned
        vector must match the release dimension; the declared query model
        space (when provided) must match the release pin.
    score_normalization:
        Ranking score normalization method (``minmax`` or ``none``).
    """

    def __init__(
        self,
        resolver: ImmutableHubResolver | None = None,
        *,
        limits: QueryLimits | Mapping[str, Any] | None = None,
        engine: BoundedRemoteQueryEngine | None = None,
        query_embedder: QueryEmbedder | None = None,
        score_normalization: str = "minmax",
        manifest_path: str = DEFAULT_MANIFEST_NAME,
    ) -> None:
        if engine is not None:
            if not isinstance(engine, BoundedRemoteQueryEngine):
                raise RemoteSearchInputError(
                    "engine must be a BoundedRemoteQueryEngine instance"
                )
            self.engine = engine
        else:
            if not isinstance(resolver, ImmutableHubResolver):
                raise RemoteSearchInputError(
                    "resolver must be an ImmutableHubResolver instance"
                )
            self.engine = BoundedRemoteQueryEngine(
                resolver,
                limits=limits,
                manifest_path=manifest_path,
            )
        if query_embedder is not None and not callable(query_embedder):
            raise RemoteSearchInputError("query_embedder must be callable")
        self.query_embedder = query_embedder
        method = str(score_normalization or "minmax").strip().lower()
        if method not in {"minmax", "none"}:
            raise RemoteSearchInputError(
                f"score_normalization must be 'minmax' or 'none', got "
                f"{score_normalization!r}"
            )
        self.score_normalization = method
        self._release_model_space: ModelSpace | None = None

    @property
    def resolver(self) -> ImmutableHubResolver:
        return self.engine.resolver

    def reset_session(
        self,
        *,
        limits: QueryLimits | Mapping[str, Any] | None = None,
        keep_manifest: bool = True,
    ) -> None:
        """Start a fresh budget/trace session on the underlying engine."""

        self.engine.reset_session(limits=limits, keep_manifest=keep_manifest)
        if not keep_manifest:
            self._release_model_space = None

    def load_manifest(self) -> dict[str, Any]:
        """Load the release manifest through the justified control plane."""

        return self.engine.load_manifest()

    def release_model_space(self, *, force: bool = False) -> ModelSpace:
        """Return the validated release vector model space (cached)."""

        if self._release_model_space is not None and not force:
            return self._release_model_space
        manifest = self.engine.load_manifest()
        space = extract_release_model_space(manifest)
        self._release_model_space = space
        return space

    def _hydrate_hits(
        self,
        hits: Sequence[Mapping[str, Any]],
        *,
        include_content: bool = False,
    ) -> list[dict[str, Any]]:
        """Hydrate hits with corpus fields (handles document_index 0).

        The engine's document-index hydration path uses
        ``int(document_index or -1)``, which drops legitimate index 0 and
        leaves title/section/etc. missing for the first corpus row.  This
        client path treats 0 as a real document index.
        """

        if not hits:
            return []

        document_indexes = [
            int(hit["document_index"])
            for hit in hits
            if hit.get("document_index") is not None
        ]
        if not document_indexes:
            # No document indexes — fall back to engine path (entry_cid only).
            return self.engine.hydrate_hits(
                hits, include_content=include_content
            )

        meta = self.engine.load_routing_index(
            "corpus_chunks", reason="routing_index"
        )
        selected = select_document_index_shards(meta, document_indexes)
        by_path: dict[str, list[int]] = defaultdict(list)
        descriptors: dict[str, Mapping[str, Any]] = {}
        for doc_id, row in selected.items():
            path = str(row["relative_path"])
            by_path[path].append(doc_id)
            descriptors[path] = row

        hydrated_by_doc: dict[int, dict[str, Any]] = {}
        hydrated_by_cid: dict[str, dict[str, Any]] = {}
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
            wanted = set(wanted_ids)
            for corp in self.engine._read_rows(artifact, descriptor=descriptor):
                raw_doc = corp.get("document_index")
                if raw_doc is None:
                    continue
                # Do not use ``or -1``: document_index 0 is a valid primary key.
                doc_id = int(raw_doc)
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
            extra: Mapping[str, Any] | None = None
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

    def _finalize_hits(
        self,
        hits: Sequence[Mapping[str, Any]],
        *,
        filters: SearchFilters,
        top_k: int,
        hydrate: bool,
        include_content: bool,
    ) -> list[dict[str, Any]]:
        # Filters that depend on corpus fields require hydration first.
        needs_hydration_fields = any(
            (
                filters.title,
                filters.chapter,
                filters.section,
                filters.source,
                filters.release_point,
                filters.node_types,
                filters.edge_types,
                filters.metadata_equals,
            )
        )
        working = [dict(item) for item in hits]
        if hydrate or needs_hydration_fields:
            if working:
                working = self._hydrate_hits(
                    working, include_content=include_content
                )
        working = apply_filters(working, filters)
        working = stable_rank(working, top_k=top_k)
        working = normalize_scores(working, method=self.score_normalization)
        return working

    def bm25_search(
        self,
        query: str,
        *,
        top_k: int = DEFAULT_TOP_K,
        filters: SearchFilters | Mapping[str, Any] | None = None,
        hydrate: bool = True,
        include_content: bool = False,
        enforce_sparse_io: bool = True,
        reset_session: bool = True,
    ) -> RemoteSearchResult:
        """Public BM25 search: term-range routes only, stable ranking, filters.

        Fetches only the posting shards covering query terms (via the
        inclusive term-range index), exact-scores those postings, optionally
        hydrates final hits, applies filters, and re-ranks with stable
        tie-breaks.  Vector shards are never fetched.
        """

        if reset_session:
            # Fresh budget + fetch-trace per public search; keep warm indexes.
            self.engine.reset_session(keep_manifest=True)
        filt = (
            filters
            if isinstance(filters, SearchFilters)
            else SearchFilters.from_mapping(filters)
        )
        top_k = _require_positive_int(top_k, "top_k")
        if top_k > MAX_TOP_K:
            raise RemoteSearchInputError(f"top_k must be <= {MAX_TOP_K}")

        # Engine scores with a wider window so post-filter still fills top_k.
        score_window = top_k if filt.is_empty else min(MAX_TOP_K, max(top_k * 4, top_k))
        engine_result = self.engine.run_bm25(
            str(query or ""),
            top_k=score_window,
            hydrate=False,
            include_content=False,
        )
        try:
            hits = self._finalize_hits(
                engine_result.results,
                filters=filt,
                top_k=top_k,
                hydrate=hydrate,
                include_content=include_content,
            )
        except QueryBudgetExhausted as exc:
            partial = list((exc.partial or {}).get("results") or [])
            packaged = RemoteSearchResult.from_engine_result(
                engine_result,
                mode="bm25",
                query=str(query or ""),
                filters=filt,
                results=stable_rank(partial, top_k=top_k),
                diagnostics_extra={
                    "budget_exhausted": exc.to_dict(),
                    "public_mode": "bm25_search",
                },
                explain={"ranking": "score_desc_entry_cid_document_index"},
            )
            if enforce_sparse_io:
                assert_bm25_sparse_io(packaged.fetch_trace)
            return packaged

        # Rebuild result with post-processed hits and refreshed fetch trace
        # (hydration may have appended justified corpus fetches).
        rebuilt = QueryEngineResult(
            mode="bm25",
            results=tuple(hits),
            diagnostics=dict(engine_result.diagnostics),
            fetch_trace=self.engine.fetch_trace(),
            complete=engine_result.complete and self.engine._stop_reason is None,
            stop_reason=self.engine._stop_reason or engine_result.stop_reason,
            usage=self.engine.usage.snapshot(),
            limits=self.engine.limits.to_dict(),
            query=str(query or ""),
            explain=dict(engine_result.explain),
        )
        packaged = RemoteSearchResult.from_engine_result(
            rebuilt,
            mode="bm25",
            query=str(query or ""),
            filters=filt,
            results=hits,
            diagnostics_extra={
                "public_mode": "bm25_search",
                "score_normalization": self.score_normalization,
                "sparse_route_policy": "term_range_only",
            },
            explain={
                "ranking": "score_desc_entry_cid_document_index",
                "route_policy": "term_range_only",
                "score_normalization": self.score_normalization,
            },
        )
        if enforce_sparse_io:
            assert_bm25_sparse_io(packaged.fetch_trace)
        return packaged

    def resolve_query_vector(
        self,
        *,
        query: str = "",
        query_vector: Sequence[float] | None = None,
        model_space: ModelSpace | Mapping[str, Any] | None = None,
        query_embedder: QueryEmbedder | None = None,
    ) -> tuple[tuple[float, ...], ModelSpace]:
        """Resolve a query vector under exact model-space matching.

        Either *query_vector* or a query embedder (instance or argument) must
        be provided.  Mutable and mismatched model spaces fail closed.
        """

        release = self.release_model_space()
        assert_model_space_compatible(release, model_space)

        if query_vector is not None:
            assert_model_space_compatible(
                release, model_space, query_vector=query_vector
            )
            return tuple(float(value) for value in query_vector), release

        embedder = query_embedder if query_embedder is not None else self.query_embedder
        if embedder is None:
            raise RemoteSearchInputError(
                "vector_search requires query_vector or a query_embedder hook"
            )
        if not str(query or "").strip():
            raise RemoteSearchInputError(
                "query text is required when using the query embedding hook"
            )
        raw = embedder(str(query), release)
        if not isinstance(raw, Sequence) or isinstance(
            raw, (str, bytes, bytearray)
        ):
            raise RemoteSearchInputError(
                "query_embedder must return a numeric sequence"
            )
        vector = tuple(float(value) for value in raw)
        assert_model_space_compatible(
            release, model_space, query_vector=vector
        )
        return vector, release

    def vector_search(
        self,
        query: str = "",
        *,
        query_vector: Sequence[float] | None = None,
        model_space: ModelSpace | Mapping[str, Any] | None = None,
        query_embedder: QueryEmbedder | None = None,
        top_k: int = DEFAULT_TOP_K,
        candidate_centroids: int = DEFAULT_CANDIDATE_CENTROIDS,
        filters: SearchFilters | Mapping[str, Any] | None = None,
        hydrate: bool = True,
        include_content: bool = False,
        enforce_sparse_io: bool = True,
        reset_session: bool = True,
    ) -> RemoteSearchResult:
        """Public vector search: centroid routes + exact scoring only.

        Probes the compact centroid routing index, downloads only selected
        vector shards, exact-scores rows, optionally hydrates, filters, and
        re-ranks with stable tie-breaks.  BM25 posting shards are never
        fetched.  Mutable or mismatched model space fails closed before any
        data-plane vector fetch.
        """

        if reset_session:
            self.engine.reset_session(keep_manifest=True)
        filt = (
            filters
            if isinstance(filters, SearchFilters)
            else SearchFilters.from_mapping(filters)
        )
        top_k = _require_positive_int(top_k, "top_k")
        if top_k > MAX_TOP_K:
            raise RemoteSearchInputError(f"top_k must be <= {MAX_TOP_K}")
        centroids = _require_positive_int(
            candidate_centroids, "candidate_centroids"
        )

        # Fail closed on model space **before** data-plane work.
        vector, release = self.resolve_query_vector(
            query=query,
            query_vector=query_vector,
            model_space=model_space,
            query_embedder=query_embedder,
        )

        score_window = top_k if filt.is_empty else min(MAX_TOP_K, max(top_k * 4, top_k))
        engine_result = self.engine.run_vector(
            vector,
            query=str(query or ""),
            top_k=score_window,
            candidate_centroids=centroids,
            hydrate=False,
            include_content=False,
        )
        try:
            hits = self._finalize_hits(
                engine_result.results,
                filters=filt,
                top_k=top_k,
                hydrate=hydrate,
                include_content=include_content,
            )
        except QueryBudgetExhausted as exc:
            packaged = RemoteSearchResult.from_engine_result(
                engine_result,
                mode="vector",
                query=str(query or ""),
                filters=filt,
                model_space=release,
                results=stable_rank(
                    list((exc.partial or {}).get("results") or []),
                    top_k=top_k,
                ),
                diagnostics_extra={
                    "budget_exhausted": exc.to_dict(),
                    "public_mode": "vector_search",
                },
                explain={
                    "ranking": "score_desc_entry_cid_document_index",
                    "route_policy": "centroid_plus_exact_score",
                },
            )
            if enforce_sparse_io:
                assert_vector_sparse_io(packaged.fetch_trace)
            return packaged

        rebuilt = QueryEngineResult(
            mode="vector",
            results=tuple(hits),
            diagnostics=dict(engine_result.diagnostics),
            fetch_trace=self.engine.fetch_trace(),
            complete=engine_result.complete and self.engine._stop_reason is None,
            stop_reason=self.engine._stop_reason or engine_result.stop_reason,
            usage=self.engine.usage.snapshot(),
            limits=self.engine.limits.to_dict(),
            query=str(query or ""),
            explain=dict(engine_result.explain),
        )
        packaged = RemoteSearchResult.from_engine_result(
            rebuilt,
            mode="vector",
            query=str(query or ""),
            filters=filt,
            model_space=release,
            results=hits,
            diagnostics_extra={
                "candidate_centroids": centroids,
                "public_mode": "vector_search",
                "score_normalization": self.score_normalization,
                "sparse_route_policy": "centroid_plus_exact_score",
            },
            explain={
                "ranking": "score_desc_entry_cid_document_index",
                "route_policy": "centroid_plus_exact_score",
                "score_normalization": self.score_normalization,
                "vector_space_id": release.vector_space_id,
            },
        )
        if enforce_sparse_io:
            assert_vector_sparse_io(packaged.fetch_trace)
        return packaged


# Module-level convenience wrappers -----------------------------------------


def bm25_search(
    engine_or_client: BoundedRemoteQueryEngine | RemoteSearchClient,
    query: str,
    **kwargs: Any,
) -> RemoteSearchResult:
    """Module-level BM25 search entry point."""

    if isinstance(engine_or_client, RemoteSearchClient):
        return engine_or_client.bm25_search(query, **kwargs)
    client = RemoteSearchClient(engine=engine_or_client)
    return client.bm25_search(query, **kwargs)


def vector_search(
    engine_or_client: BoundedRemoteQueryEngine | RemoteSearchClient,
    query: str = "",
    **kwargs: Any,
) -> RemoteSearchResult:
    """Module-level vector search entry point."""

    if isinstance(engine_or_client, RemoteSearchClient):
        return engine_or_client.vector_search(query, **kwargs)
    client = RemoteSearchClient(engine=engine_or_client)
    return client.vector_search(query, **kwargs)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------


def default_remote_search_results_fixture_path() -> Path:
    """Repository path for the sealed remote-search results fixture."""

    return (
        Path(__file__).resolve().parents[3]
        / "tests"
        / "fixtures"
        / "hf_graphrag"
        / "remote_search_results.json"
    )


def build_remote_search_results_fixture_payload() -> dict[str, Any]:
    """Compact deterministic recipes for USCIR-026 unit tests.

    A miniature offline release is regenerated at test time; expected sparse
    route families/reasons, model-space failure modes, and ranking semantics
    are asserted without bulk golden dumps.
    """

    return {
        "acceptance": {
            "bm25_term_range_only": True,
            "mutable_mismatched_model_space_fails": True,
            "sparse_io_trace_proven": True,
            "vectors_centroid_plus_exact_score": True,
        },
        "bounds": {
            "default_candidate_centroids": int(
                SCHEMA_DEFAULT_CANDIDATE_CENTROIDS
            ),
            "default_top_k": DEFAULT_TOP_K,
            "max_top_k": MAX_TOP_K,
        },
        "cases": [
            {
                "expected_data_plane_paths": [
                    "data/bm25/postings/part-000000.parquet",
                    "data/corpus/part-000000.parquet",
                ],
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
                "expected_top_entry_cid": "entry-a",
                "forbidden_families": ["vectors"],
                "forbidden_paths": [
                    "data/bm25/postings/part-000001.parquet",
                ],
                "id": "bm25_term_range_sparse_io",
                "mode": "bm25",
                "query": "foia agency",
                "top_k": 3,
            },
            {
                "candidate_centroids": 1,
                "expected_data_plane_paths": [
                    "data/vectors/centroid-000000-part-000000.parquet",
                    "data/corpus/part-000000.parquet",
                ],
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
                "expected_top_entry_cid": "entry-a",
                "forbidden_families": ["bm25_postings"],
                "forbidden_paths": [
                    "data/vectors/centroid-000001-part-000000.parquet",
                ],
                "id": "vector_centroid_exact_sparse_io",
                "mode": "vector",
                "query": "near entry-a",
                "query_vector": [1.0, 0.0],
                "top_k": 2,
            },
            {
                "expected_error": "mutable_model_space",
                "id": "mutable_model_space_fails",
                "mode": "vector",
                "mutate_manifest": {
                    "vector.model_revision": "latest",
                },
                "query_vector": [1.0, 0.0],
            },
            {
                "expected_error": "model_space_mismatch",
                "id": "mismatched_model_space_fails",
                "mode": "vector",
                "query_model_space": {
                    "dimension": 2,
                    "model_id": "fixture-other-model",
                    "model_revision": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                    "normalization": "l2",
                    "vector_space_id": "other@aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa:d2:norm=l2",
                },
                "query_vector": [1.0, 0.0],
            },
            {
                "expected_order": ["entry-a", "entry-b"],
                "filter_entry_cid": "entry-a",
                "id": "bm25_filter_and_stable_rank",
                "mode": "bm25",
                "query": "agency",
                "top_k": 5,
            },
        ],
        "description": (
            "Compact deterministic recipes for USCIR-026 direct remote BM25 "
            "and vector search unit tests.  A miniature offline release is "
            "regenerated at test time; sparse I/O, model-space fail-closed "
            "behavior, filters, and stable ranking are asserted without bulk "
            "golden dumps."
        ),
        "goal_id": GOAL_ID,
        "remote_search_schema_version": REMOTE_SEARCH_SCHEMA_VERSION,
        "route_families": sorted(ROUTE_FAMILIES),
        "route_reasons": sorted(ROUTE_REASONS),
        "schema_version": REMOTE_SEARCH_RESULTS_FIXTURE_SCHEMA,
        "task_id": TASK_ID,
    }


def load_remote_search_results_fixture(
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Load and lightly validate the sealed remote-search results fixture."""

    target = (
        Path(path)
        if path is not None
        else default_remote_search_results_fixture_path()
    )
    payload = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise RemoteSearchInputError(
            "remote_search_results fixture must be an object"
        )
    if payload.get("schema_version") != REMOTE_SEARCH_RESULTS_FIXTURE_SCHEMA:
        raise RemoteSearchInputError(
            "remote_search_results fixture schema_version mismatch"
        )
    if payload.get("task_id") != TASK_ID:
        raise RemoteSearchInputError(
            "remote_search_results fixture task_id mismatch"
        )
    cases = payload.get("cases")
    if not isinstance(cases, list) or not cases:
        raise RemoteSearchInputError(
            "remote_search_results fixture has no cases"
        )
    return dict(payload)


def write_remote_search_results_fixture(
    path: str | Path | None = None,
) -> Path:
    """Write the sealed compact fixture (deterministic, no timestamps)."""

    target = (
        Path(path)
        if path is not None
        else default_remote_search_results_fixture_path()
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_remote_search_results_fixture_payload()
    target.write_text(
        canonical_json_dumps(payload) + "\n",
        encoding="utf-8",
    )
    return target


__all__ = [
    "BM25_ALLOWED_DATA_REASONS",
    "CONTROL_ROUTE_REASONS",
    "DEFAULT_CANDIDATE_CENTROIDS",
    "DEFAULT_MANIFEST_NAME",
    "DEFAULT_TOP_K",
    "GOAL_ID",
    "MAX_TOP_K",
    "REMOTE_SEARCH_RESULTS_FIXTURE_SCHEMA",
    "REMOTE_SEARCH_SCHEMA_VERSION",
    "TASK_ID",
    "VECTOR_ALLOWED_DATA_REASONS",
    "ModelSpace",
    "ModelSpaceError",
    "ModelSpaceMismatchError",
    "MutableModelSpaceError",
    "QueryEmbedder",
    "RemoteSearchClient",
    "RemoteSearchError",
    "RemoteSearchInputError",
    "RemoteSearchIntegrityError",
    "RemoteSearchResult",
    "SearchFilters",
    "SparseIoContractError",
    "apply_filters",
    "assert_bm25_sparse_io",
    "assert_model_space_compatible",
    "assert_vector_sparse_io",
    "bm25_search",
    "build_remote_search_results_fixture_payload",
    "default_remote_search_results_fixture_path",
    "extract_release_model_space",
    "hit_matches_filters",
    "is_immutable_model_revision",
    "is_mutable_revision_token",
    "is_placeholder_model_token",
    "load_remote_search_results_fixture",
    "normalize_scores",
    "ranking_key",
    "remote_replay_fingerprint",
    "require_immutable_model_revision",
    "sparse_io_summary",
    "stable_rank",
    "vector_search",
    "write_remote_search_results_fixture",
]
