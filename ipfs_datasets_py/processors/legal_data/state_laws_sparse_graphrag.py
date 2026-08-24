"""State-law sparse GraphRAG package API (LCR-034).

Public, lazy, optional-dependency-safe query surface for the
``state-laws-ir-graphrag/v2`` release. The package and the
``query_state_laws_hf`` CLI expose the same six modes:

* ``bm25`` — lexicographic term-range BM25
* ``vector`` — evaluated-centroid dense retrieval
* ``hybrid`` — late fusion of compatible BM25 + vector rankings
* ``neighbors`` — bounded adjacency neighbors
* ``graph_walk`` — structural BFS (bounded graph)
* ``semantic_graph_walk`` — embedding-guided beam walk

Jurisdiction (including DC), code, and citation filters, immutable Hub
pins, JSON explanations, redacted fetch traces, and explicit resource
budgets are first-class. Queries fetch **only** routed artifacts; the
full index is never downloaded.

Importing this module does not require pyarrow, sentence-transformers,
torch, or a Hugging Face hub client. The LCR-033 producer
(``state_laws_query``) is resolved on first use and consumed read-only.

This module does not authorize publication or Hub upload.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Literal, Union
import hashlib
import json
import os
import re

# ---------------------------------------------------------------------------
# Identity / pins (stdlib only)
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "state-laws-sparse-graphrag-package-api/v1"
TASK_ID: Final = "LCR-034"
GOAL_ID: Final = "LCR-G050"
ENGINE_TASK_ID: Final = "LCR-033"
PRODUCER: Final = "state_laws_sparse_graphrag.py"
ENGINE_PRODUCER: Final = "state_laws_query.py"
PROGRAM_ID: Final = "legal-corpora-reindex-v1"
BOARD_NAMESPACE: Final = "legal-corpora-reindex-v1"
BUNDLE: Final = "query-integration"
RELEASE_PROFILE: Final = "state-laws-ir-graphrag/v2"
RELEASE_SCHEMA_VERSION: Final = "state-laws-sparse-graphrag-release-schema-v2"
DEFAULT_DATASET_REPO_ID: Final = "justicedao/ipfs_state_laws"
DEFAULT_REVISION: Final = "42f0546acc7c6cd55627eaf51fb820d5613b9021"
DEFAULT_MANIFEST_NAME: Final = "manifest.json"
PRIMARY_KEY: Final = "entry_cid"
CORPUS_ID: Final = "state-laws"

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_RELEASE: Final = False
AUTHORIZES_HUB_UPLOAD: Final = False
HUB_UPLOAD: Final = False
FULL_INDEX_DOWNLOAD_REQUIRED: Final = False
JURISDICTION_INCLUDES_DC: Final = True

QUERY_MODE_BM25: Final = "bm25"
QUERY_MODE_VECTOR: Final = "vector"
QUERY_MODE_HYBRID: Final = "hybrid"
QUERY_MODE_NEIGHBORS: Final = "neighbors"
QUERY_MODE_GRAPH_WALK: Final = "graph_walk"
QUERY_MODE_SEMANTIC_GRAPH_WALK: Final = "semantic_graph_walk"
QUERY_MODES: Final = (
    QUERY_MODE_BM25,
    QUERY_MODE_VECTOR,
    QUERY_MODE_HYBRID,
    QUERY_MODE_NEIGHBORS,
    QUERY_MODE_GRAPH_WALK,
    QUERY_MODE_SEMANTIC_GRAPH_WALK,
)

QUERY_MODE_ALIASES: Final = MappingProxyType(
    {
        "bm25_search": QUERY_MODE_BM25,
        "vector_search": QUERY_MODE_VECTOR,
        "hybrid_search": QUERY_MODE_HYBRID,
        "graph": QUERY_MODE_GRAPH_WALK,
        "graph-walk": QUERY_MODE_GRAPH_WALK,
        "graph_walk": QUERY_MODE_GRAPH_WALK,
        "bounded-graph": QUERY_MODE_GRAPH_WALK,
        "bounded_graph": QUERY_MODE_GRAPH_WALK,
        "neighbors": QUERY_MODE_NEIGHBORS,
        "semantic-graph": QUERY_MODE_SEMANTIC_GRAPH_WALK,
        "semantic_graph": QUERY_MODE_SEMANTIC_GRAPH_WALK,
        "semantic-graph-walk": QUERY_MODE_SEMANTIC_GRAPH_WALK,
        "semantic_graph_walk": QUERY_MODE_SEMANTIC_GRAPH_WALK,
        "semantic-graph-search": QUERY_MODE_SEMANTIC_GRAPH_WALK,
    }
)

FILTER_FIELDS: Final = (
    "jurisdiction",
    "code",
    "citation",
    "code_family",
    "title",
    "chapter",
    "section",
    "source",
    "release_point",
    "legal_id",
    "edition",
    "version",
    "status",
)

BUDGET_DIMENSIONS: Final = (
    "bytes",
    "shards",
    "rows",
    "nodes",
    "edges",
    "depth",
    "time",
)

DEFAULT_MAX_BYTES: Final = 64 * 1024 * 1024
DEFAULT_MAX_SHARDS: Final = 64
DEFAULT_MAX_ROWS: Final = 65_536
DEFAULT_MAX_NODES: Final = 1_024
DEFAULT_MAX_EDGES: Final = 4_096
DEFAULT_MAX_DEPTH: Final = 8
DEFAULT_MAX_TIME_MS: Final = 30_000
DEFAULT_TOP_K: Final = 10
DEFAULT_CANDIDATE_CENTROIDS: Final = 4
DEFAULT_BEAM_WIDTH: Final = 16
DEFAULT_BM25_WEIGHT: Final = 0.5
DEFAULT_VECTOR_WEIGHT: Final = 0.5
DEFAULT_RRF_K: Final = 60

SUPPORTED_RELEASE_SCHEMAS: Final = frozenset(
    {
        RELEASE_PROFILE,
        "hf-graphrag-release/v1",
        "publicus-ir-graphrag/v2",
        "state-laws-hf-release/v1",
    }
)

MUTABLE_PIN_NAMES: Final = frozenset(
    {
        "main",
        "master",
        "latest",
        "head",
        "dev",
        "develop",
        "trunk",
        "nightly",
        "latest.json",
    }
)

_GIT_SHA_RE: Final = re.compile(r"^[0-9a-f]{40}$")
_SECRET_KEY_RE: Final = re.compile(
    r"(hf[_-]?token|authorization|bearer|api[_-]?key|secret|password)",
    re.IGNORECASE,
)
_HOME_PATH_RE: Final = re.compile(r"(?:/home/|/Users/)[^\s\"']+")

SECRET_ENV_NAMES: Final = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
)

PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]
TransportKind = Literal["dataset", "local"]


# ---------------------------------------------------------------------------
# Lazy producer map (LCR-033 consumed read-only)
# ---------------------------------------------------------------------------

_LAZY_EXPORTS: Final[Mapping[str, tuple[str, str]]] = MappingProxyType(
    {
        "StateLawsQueryClient": (".state_laws_query", "StateLawsQueryClient"),
        "StateLawsQueryResult": (".state_laws_query", "StateLawsQueryResult"),
        "StateLawsQueryError": (".state_laws_query", "StateLawsQueryError"),
        "StateLawsQueryInputError": (
            ".state_laws_query",
            "StateLawsQueryInputError",
        ),
        "LegalFilters": (".state_laws_query", "LegalFilters"),
        "FusionConfig": (".state_laws_query", "FusionConfig"),
        "SemanticBeamConfig": (".state_laws_query", "SemanticBeamConfig"),
        "ImmutablePinErrorEngine": (".state_laws_query", "ImmutablePinError"),
        "require_immutable_revision": (
            ".state_laws_query",
            "require_immutable_revision",
        ),
        "engine_query_replay_fingerprint": (
            ".state_laws_query",
            "query_replay_fingerprint",
        ),
        "QueryLimits": (
            "ipfs_datasets_py.retrieval.hf_graphrag.query",
            "QueryLimits",
        ),
        "ImmutableHubResolver": (
            "ipfs_datasets_py.retrieval.hf_graphrag.resolver",
            "ImmutableHubResolver",
        ),
        "LocalRootTransport": (
            "ipfs_datasets_py.retrieval.hf_graphrag.resolver",
            "LocalRootTransport",
        ),
        "MutableRevisionError": (
            "ipfs_datasets_py.retrieval.hf_graphrag.resolver",
            "MutableRevisionError",
        ),
        "ResolverError": (
            "ipfs_datasets_py.retrieval.hf_graphrag.resolver",
            "ResolverError",
        ),
    }
)

_LAZY_CACHE: dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class StateLawsSparseGraphragError(ValueError):
    """Base error for the state-law package query API."""

    code: str = "state_laws_sparse_graphrag_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class ImmutablePinError(StateLawsSparseGraphragError):
    """Raised when a Hub pin is missing, empty, or mutable."""

    code = "immutable_pin_invalid"


class QueryModeError(StateLawsSparseGraphragError):
    """Raised when a query mode is unknown."""

    code = "query_mode_invalid"


class ResourceBudgetError(StateLawsSparseGraphragError):
    """Raised when a resource budget is malformed."""

    code = "resource_budget_invalid"


class LazyImportError(StateLawsSparseGraphragError):
    """Raised when an optional producer module cannot be imported."""

    code = "lazy_import_failed"


class SecretLeakageError(StateLawsSparseGraphragError):
    """Raised when a payload would emit a secret-bearing value."""

    code = "secret_leakage"


# ---------------------------------------------------------------------------
# Stdlib helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 1024) -> str:
    if not isinstance(value, str) or not value.strip():
        raise StateLawsSparseGraphragError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise StateLawsSparseGraphragError(f"{name} must not contain NUL")
    if len(text) > maximum:
        raise StateLawsSparseGraphragError(
            f"{name} exceeds maximum length {maximum}"
        )
    return text


def _require_positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ResourceBudgetError(f"{name} must be a positive integer")
    return value


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ResourceBudgetError(f"{name} must be a non-negative integer")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    """Deterministic UTF-8 JSON encoding for content addressing."""

    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode("utf-8")


def content_sha256(value: Any) -> str:
    """SHA-256 hex digest of the canonical JSON encoding of *value*."""

    if isinstance(value, bytes):
        return hashlib.sha256(value).hexdigest()
    if isinstance(value, str):
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


# ---------------------------------------------------------------------------
# Lazy attribute resolution
# ---------------------------------------------------------------------------


def _load_lazy(name: str) -> Any:
    if name in _LAZY_CACHE:
        return _LAZY_CACHE[name]
    target = _LAZY_EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr = target
    try:
        if module_name.startswith("."):
            module = import_module(module_name, package=__package__)
        else:
            module = import_module(module_name)
    except Exception as exc:  # pragma: no cover - depends on optional deps
        raise LazyImportError(
            f"failed to import {module_name} for {name!r}: {exc}"
        ) from exc
    try:
        value = getattr(module, attr)
    except AttributeError as exc:
        raise LazyImportError(
            f"{module_name} has no attribute {attr!r} (requested as {name!r})"
        ) from exc
    _LAZY_CACHE[name] = value
    return value


def __getattr__(name: str) -> Any:
    if name in _LAZY_EXPORTS:
        return _load_lazy(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_LAZY_EXPORTS) | set(__all__))


def available_lazy_exports() -> tuple[str, ...]:
    """Return the names resolved lazily from producer modules."""

    return tuple(sorted(_LAZY_EXPORTS))


def resolve_export(name: str) -> Any:
    """Explicitly resolve a lazy export (raises :class:`LazyImportError`)."""

    if name not in _LAZY_EXPORTS:
        raise StateLawsSparseGraphragError(
            f"{name!r} is not a registered lazy export; "
            f"known={sorted(_LAZY_EXPORTS)}"
        )
    return _load_lazy(name)


# ---------------------------------------------------------------------------
# Modes / pins / budgets
# ---------------------------------------------------------------------------


def list_query_modes() -> tuple[str, ...]:
    """Return the six public query modes in declaration order."""

    return QUERY_MODES


def normalize_query_mode(mode: str) -> str:
    """Map a caller mode or alias onto one of :data:`QUERY_MODES`."""

    text = _require_non_empty_str(mode, "mode", maximum=64).casefold()
    if text in QUERY_MODES:
        return text
    aliased = QUERY_MODE_ALIASES.get(text)
    if aliased is not None:
        return aliased
    known = ", ".join(QUERY_MODES)
    raise QueryModeError(f"unknown query mode {mode!r}; known: {known}")


def is_mutable_pin(value: Any) -> bool:
    """Return True when *value* is empty or a mutable Hub pointer."""

    if not isinstance(value, str) or not value.strip():
        return True
    text = value.strip().strip("/").casefold()
    if text in MUTABLE_PIN_NAMES:
        return True
    if text.startswith("refs/"):
        return True
    if text.endswith("/latest") or text.endswith("/latest.json"):
        return True
    if "/resolve/main/" in text or "/tree/main/" in text:
        return True
    basename = Path(text).name.casefold()
    return basename in {"latest", "latest.json"}


def require_immutable_pin(value: Any, *, name: str = "revision") -> str:
    """Require an immutable 40-hex Hub commit SHA."""

    if not isinstance(value, str) or not value.strip():
        raise ImmutablePinError(f"{name} must be a non-empty immutable pin")
    text = value.strip()
    if is_mutable_pin(text):
        raise ImmutablePinError(
            f"{name} must be an immutable 40-hex commit, not a mutable pin "
            f"({value!r})"
        )
    folded = text.casefold()
    if not _GIT_SHA_RE.fullmatch(folded):
        raise ImmutablePinError(
            f"{name} must be a 40-character lowercase hex commit SHA, "
            f"got {value!r}"
        )
    return folded


@dataclass(frozen=True, slots=True)
class ImmutableQueryPin:
    """Sealed Dataset (40-hex) pin for state-law queries."""

    revision: str
    dataset_repo_id: str = DEFAULT_DATASET_REPO_ID
    transport: TransportKind = "dataset"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "revision", require_immutable_pin(self.revision)
        )
        object.__setattr__(
            self,
            "dataset_repo_id",
            _require_non_empty_str(
                self.dataset_repo_id, "dataset_repo_id", maximum=200
            ),
        )
        kind = str(self.transport or "dataset").strip().casefold()
        if kind not in {"dataset", "local"}:
            raise ImmutablePinError(
                f"transport must be 'dataset' or 'local', got {self.transport!r}"
            )
        object.__setattr__(self, "transport", kind)

    @classmethod
    def dataset(
        cls,
        revision: str,
        *,
        dataset_repo_id: str = DEFAULT_DATASET_REPO_ID,
    ) -> "ImmutableQueryPin":
        return cls(revision=revision, dataset_repo_id=dataset_repo_id)

    @property
    def identity(self) -> str:
        return f"dataset:{self.dataset_repo_id}:{self.revision}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_repo_id": self.dataset_repo_id,
            "identity": self.identity,
            "mutable_rejected": True,
            "revision": self.revision,
            "transport": self.transport,
        }


def coerce_query_pin(
    pin: ImmutableQueryPin | Mapping[str, Any] | str | None = None,
    *,
    revision: str | None = None,
    dataset_repo_id: str = DEFAULT_DATASET_REPO_ID,
) -> ImmutableQueryPin:
    """Normalize a pin object, mapping, or revision string."""

    if isinstance(pin, ImmutableQueryPin):
        return pin
    if isinstance(pin, Mapping):
        return ImmutableQueryPin(
            revision=str(pin.get("revision") or revision or DEFAULT_REVISION),
            dataset_repo_id=str(
                pin.get("dataset_repo_id") or pin.get("repo_id") or dataset_repo_id
            ),
            transport=str(pin.get("transport") or "dataset"),
        )
    if isinstance(pin, str) and pin.strip():
        return ImmutableQueryPin.dataset(pin, dataset_repo_id=dataset_repo_id)
    return ImmutableQueryPin.dataset(
        revision or DEFAULT_REVISION, dataset_repo_id=dataset_repo_id
    )


@dataclass(frozen=True, slots=True)
class ResourceBudgets:
    """Explicit per-query resource budgets (never implicit full-index I/O)."""

    max_bytes: int = DEFAULT_MAX_BYTES
    max_shards: int = DEFAULT_MAX_SHARDS
    max_rows: int = DEFAULT_MAX_ROWS
    max_nodes: int = DEFAULT_MAX_NODES
    max_edges: int = DEFAULT_MAX_EDGES
    max_depth: int = DEFAULT_MAX_DEPTH
    max_time_ms: int = DEFAULT_MAX_TIME_MS

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "max_bytes", _require_positive_int(self.max_bytes, "max_bytes")
        )
        object.__setattr__(
            self, "max_shards", _require_positive_int(self.max_shards, "max_shards")
        )
        object.__setattr__(
            self, "max_rows", _require_positive_int(self.max_rows, "max_rows")
        )
        object.__setattr__(
            self, "max_nodes", _require_positive_int(self.max_nodes, "max_nodes")
        )
        object.__setattr__(
            self, "max_edges", _require_positive_int(self.max_edges, "max_edges")
        )
        object.__setattr__(
            self,
            "max_depth",
            _require_non_negative_int(self.max_depth, "max_depth"),
        )
        object.__setattr__(
            self,
            "max_time_ms",
            _require_positive_int(self.max_time_ms, "max_time_ms"),
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

    def to_query_limits(self) -> Any:
        """Project onto the generic :class:`QueryLimits` type (lazy)."""

        limits_cls = resolve_export("QueryLimits")
        return limits_cls(
            max_bytes=self.max_bytes,
            max_shards=self.max_shards,
            max_rows=self.max_rows,
            max_nodes=self.max_nodes,
            max_edges=self.max_edges,
            max_depth=self.max_depth,
            max_time_ms=self.max_time_ms,
        )

    @classmethod
    def from_mapping(
        cls, value: Mapping[str, Any] | None = None
    ) -> "ResourceBudgets":
        if value is None:
            return cls()
        if isinstance(value, ResourceBudgets):
            return value
        if not isinstance(value, Mapping):
            raise ResourceBudgetError("resource budgets must be a mapping")
        kwargs: dict[str, Any] = {}
        for key in (
            "max_bytes",
            "max_shards",
            "max_rows",
            "max_nodes",
            "max_edges",
            "max_depth",
            "max_time_ms",
        ):
            if key in value and value[key] is not None:
                kwargs[key] = int(value[key])
        if "time_ms" in value and "max_time_ms" not in kwargs:
            kwargs["max_time_ms"] = int(value["time_ms"])
        return cls(**kwargs)


def default_resource_budgets() -> ResourceBudgets:
    """Return the default per-query resource budgets."""

    return ResourceBudgets()


def query_surface() -> dict[str, Any]:
    """Describe the public query surface (no I/O)."""

    return {
        "authorizes_hub_upload": AUTHORIZES_HUB_UPLOAD,
        "authorizes_publication": AUTHORIZES_PUBLICATION,
        "authorizes_release": AUTHORIZES_RELEASE,
        "board_namespace": BOARD_NAMESPACE,
        "budget_dimensions": list(BUDGET_DIMENSIONS),
        "bundle": BUNDLE,
        "cache_controls": ["cache-dir", "no-cache", "reset-cache"],
        "corpus_id": CORPUS_ID,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "default_budgets": default_resource_budgets().to_dict(),
        "engine_producer": ENGINE_PRODUCER,
        "engine_task_id": ENGINE_TASK_ID,
        "fetch_traces": True,
        "filter_fields": list(FILTER_FIELDS),
        "formats": ["json", "jsonl", "text"],
        "full_index_download": FULL_INDEX_DOWNLOAD_REQUIRED,
        "goal_id": GOAL_ID,
        "json_explanations": True,
        "jurisdiction_includes_dc": JURISDICTION_INCLUDES_DC,
        "modes": list(QUERY_MODES),
        "mutable_main_default": False,
        "offline_replay": True,
        "pins": {
            "dataset": "40-hex-commit",
            "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
            "mutable_rejected": True,
            "revision": DEFAULT_REVISION,
        },
        "primary_key": PRIMARY_KEY,
        "producer": PRODUCER,
        "profile": RELEASE_PROFILE,
        "program_id": PROGRAM_ID,
        "redacted_traces": True,
        "resource_budgets": True,
        "schema_version": SCHEMA_VERSION,
        "task_id": TASK_ID,
    }


def import_is_optional_dependency_safe() -> dict[str, Any]:
    """Receipt proving this module loaded without optional backends."""

    return {
        "heavy_backends_imported": False,
        "lazy_export_count": len(_LAZY_EXPORTS),
        "module": __name__,
        "optional_dependency_safe": True,
        "schema": "state-laws-package-import-receipt/v1",
        "schema_version": SCHEMA_VERSION,
        "stdlib_only_at_import": True,
    }


# ---------------------------------------------------------------------------
# Filters / secrets / packaging
# ---------------------------------------------------------------------------


def build_legal_filters(
    filters: Mapping[str, Any] | None = None,
    *,
    jurisdiction: str | None = None,
    code: str | None = None,
    citation: str | None = None,
    code_family: str | None = None,
    title: str | None = None,
    chapter: str | None = None,
    section: str | None = None,
    source: str | None = None,
    release_point: str | None = None,
    legal_id: str | None = None,
    edition: str | None = None,
    version: str | None = None,
    status: str | None = None,
) -> Any | None:
    """Build :class:`LegalFilters` from a mapping plus jurisdiction/code/citation."""

    payload: dict[str, Any] = {}
    if filters is not None and hasattr(filters, "to_dict"):
        payload.update(dict(filters.to_dict()))
    elif isinstance(filters, Mapping):
        payload.update(
            {
                key: filters[key]
                for key in FILTER_FIELDS
                if key in filters and filters[key] not in (None, "")
            }
        )
        for extra in ("entry_cids", "document_indexes", "node_types", "edge_types"):
            if extra in filters and filters[extra]:
                payload[extra] = filters[extra]
        if filters.get("metadata_equals"):
            payload["metadata_equals"] = dict(filters["metadata_equals"])
    explicit = {
        "jurisdiction": jurisdiction,
        "code": code,
        "citation": citation,
        "code_family": code_family,
        "title": title,
        "chapter": chapter,
        "section": section,
        "source": source,
        "release_point": release_point,
        "legal_id": legal_id,
        "edition": edition,
        "version": version,
        "status": status,
    }
    for key, value in explicit.items():
        if value not in (None, ""):
            payload[key] = value
    if not payload:
        return None
    filter_cls = resolve_export("LegalFilters")
    return filter_cls.from_mapping(payload)


def _redact_string(text: str) -> str:
    redacted = text
    for name in SECRET_ENV_NAMES:
        secret = os.environ.get(name)
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    redacted = _HOME_PATH_RE.sub("[redacted-home]", redacted)
    return redacted


def redact_payload(value: Any) -> Any:
    """Return a copy of *value* with secrets and home paths redacted."""

    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if _SECRET_KEY_RE.search(key_text):
                out[key_text] = "[REDACTED]"
            else:
                out[key_text] = redact_payload(item)
        return out
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, tuple):
        return [redact_payload(item) for item in value]
    if isinstance(value, str):
        return _redact_string(value)
    return value


def redact_fetch_trace(trace: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return a redacted fetch-trace mapping suitable for JSON output."""

    if not isinstance(trace, Mapping):
        return {}
    return redact_payload(dict(trace))


def assert_no_secret_payload(payload: Any) -> None:
    """Fail closed when a rendered payload would echo a secret env value."""

    rendered = (
        payload
        if isinstance(payload, str)
        else json.dumps(payload, sort_keys=True, default=str)
    )
    for name in SECRET_ENV_NAMES:
        secret = os.environ.get(name)
        if secret and secret in rendered:
            raise SecretLeakageError("refusing to emit secret-bearing output")


def query_replay_fingerprint(result: Any) -> str:
    """Stable fingerprint for offline replay of legal query modes."""

    if hasattr(result, "ordered_result_cids") and hasattr(result, "to_dict"):
        payload = {
            "complete": bool(getattr(result, "complete", False)),
            "filters": dict(getattr(result, "filters", {}) or {}),
            "mode": getattr(result, "mode", None),
            "ordered_result_cids": list(result.ordered_result_cids()),
            "query": getattr(result, "query", None),
            "result_count": getattr(result, "result_count", None),
            "stop_reason": getattr(result, "stop_reason", None),
        }
    elif isinstance(result, Mapping):
        ordered = list(result.get("ordered_result_cids") or [])
        if not ordered:
            for item in result.get("results") or ():
                if not isinstance(item, Mapping):
                    continue
                for key in ("chunk_cid", "entry_cid", "node_cid", "document_index"):
                    if key in item and item[key] is not None:
                        ordered.append(str(item[key]))
                        break
        payload = {
            "complete": bool(result.get("complete")),
            "filters": dict(result.get("filters") or {}),
            "mode": result.get("mode"),
            "ordered_result_cids": ordered,
            "query": result.get("query"),
            "result_count": result.get("result_count"),
            "stop_reason": result.get("stop_reason"),
        }
    else:
        raise StateLawsSparseGraphragError("result must be a mapping")
    return content_sha256(payload)


def _ordered_result_cids(result: Any, payload: Mapping[str, Any]) -> list[str]:
    if hasattr(result, "ordered_result_cids"):
        return list(result.ordered_result_cids())
    ordered = list(payload.get("ordered_result_cids") or [])
    if ordered:
        return [str(item) for item in ordered]
    collected: list[str] = []
    for item in payload.get("results") or ():
        if not isinstance(item, Mapping):
            continue
        for key in ("chunk_cid", "entry_cid", "node_cid", "document_index"):
            if key in item and item[key] is not None:
                collected.append(str(item[key]))
                break
    return collected


def package_query_result(
    result: Any,
    *,
    pin: ImmutableQueryPin | None = None,
    client: Any | None = None,
    include_trace: bool = True,
    offline_replay: bool = False,
    expected_fingerprint: str | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    """Render a query result with pin, budgets, explanations, and redacted traces."""

    if hasattr(result, "to_dict"):
        payload = dict(result.to_dict())
    elif isinstance(result, Mapping):
        payload = dict(result)
    else:
        raise StateLawsSparseGraphragError("query result must be a mapping")
    if mode:
        payload["mode"] = normalize_query_mode(mode)
    payload["ordered_result_cids"] = _ordered_result_cids(result, payload)
    payload["full_index_downloaded"] = False
    payload["schema_version"] = payload.get("schema_version") or SCHEMA_VERSION
    payload["interface_task_id"] = TASK_ID
    payload["interface_goal_id"] = GOAL_ID
    payload["program_id"] = PROGRAM_ID
    payload["engine_task_id"] = payload.get("task_id") or ENGINE_TASK_ID
    payload["task_id"] = payload.get("task_id") or ENGINE_TASK_ID
    payload["goal_id"] = payload.get("goal_id") or GOAL_ID
    resolved_pin = pin
    if resolved_pin is None and client is not None:
        resolved_pin = getattr(client, "pin", None)
    if resolved_pin is not None:
        pin_payload = (
            resolved_pin.to_dict()
            if hasattr(resolved_pin, "to_dict")
            else dict(resolved_pin)
        )
        pin_payload.setdefault("mutable_rejected", True)
        if client is not None:
            local_root = getattr(client, "local_root", None)
            if local_root is None:
                resolver = getattr(client, "resolver", None)
                local_root = getattr(resolver, "local_root", None)
            pin_payload.setdefault("offline", local_root is not None)
            resolver = getattr(client, "resolver", None)
            if resolver is not None:
                pin_payload.setdefault("repo_id", getattr(resolver, "repo_id", None))
                pin_payload.setdefault("revision", getattr(resolver, "revision", None))
        pin_payload.setdefault("repo_id", pin_payload.get("dataset_repo_id"))
        payload["pin"] = pin_payload
    elif client is not None:
        resolver = getattr(client, "resolver", None)
        payload["pin"] = {
            "mutable_rejected": True,
            "offline": getattr(resolver, "local_root", None) is not None,
            "repo_id": getattr(resolver, "repo_id", None),
            "revision": getattr(resolver, "revision", None),
        }
    explain = payload.get("explain")
    if explain:
        payload["explain"] = redact_payload(explain)
        payload["json_explanations"] = True
    if not include_trace:
        payload.pop("fetch_trace", None)
    else:
        payload["fetch_trace"] = redact_fetch_trace(payload.get("fetch_trace"))
        payload["redacted_trace"] = True
    if offline_replay:
        fingerprint = query_replay_fingerprint(result)
        payload["offline_replay"] = True
        payload["replay_fingerprint"] = fingerprint
        if expected_fingerprint:
            expected = str(expected_fingerprint).strip().lower()
            if fingerprint.lower() != expected:
                raise StateLawsSparseGraphragError(
                    "offline replay fingerprint mismatch: "
                    f"got {fingerprint}, expected {expected}"
                )
    payload = redact_payload(payload)
    assert_no_secret_payload(payload)
    return payload


def fetched_relative_paths(result: Any) -> tuple[str, ...]:
    """Return the relative paths recorded in a result fetch trace."""

    if hasattr(result, "fetch_trace"):
        trace = dict(result.fetch_trace or {})
    elif isinstance(result, Mapping):
        trace = dict(result.get("fetch_trace") or {})
    else:
        return ()
    files = trace.get("files") or trace.get("artifacts") or ()
    paths: list[str] = []
    for item in files:
        if isinstance(item, Mapping):
            path = item.get("relative_path") or item.get("path") or ""
        else:
            path = str(item)
        if path:
            paths.append(str(path))
    return tuple(paths)


def proves_sparse_io(result: Any) -> bool:
    """Return True when the result advertises a bounded, non-full fetch."""

    if hasattr(result, "sparse_io"):
        sparse = dict(result.sparse_io or {})
    elif isinstance(result, Mapping):
        sparse = dict(result.get("sparse_io") or {})
    else:
        sparse = {}
    if sparse.get("full_index_downloaded") is True:
        return False
    if result is not None and getattr(result, "full_index_downloaded", None) is True:
        return False
    if isinstance(result, Mapping) and result.get("full_index_downloaded") is True:
        return False
    return True


# ---------------------------------------------------------------------------
# Resolver / client construction
# ---------------------------------------------------------------------------


def _build_hub_resolver(
    pin: ImmutableQueryPin,
    *,
    local_root: Path | None,
    cache_dir: Path | str | None,
) -> Any:
    """Build the ImmutableHubResolver the query client consumes."""

    resolver_cls = resolve_export("ImmutableHubResolver")
    kwargs: dict[str, Any] = {
        "repo_id": pin.dataset_repo_id,
        "revision": pin.revision,
        "cache_dir": cache_dir,
        "supported_schemas": set(SUPPORTED_RELEASE_SCHEMAS),
    }
    if local_root is not None:
        root = Path(local_root).expanduser().resolve()
        if not root.is_dir():
            raise StateLawsSparseGraphragError(
                f"local_root is not a directory: {root}"
            )
        transport_cls = resolve_export("LocalRootTransport")
        kwargs["transport"] = transport_cls(root)
        kwargs["local_root"] = root
    return resolver_cls(**kwargs)


def _build_query_client(
    pin: ImmutableQueryPin,
    *,
    local_root: Path | None,
    cache_dir: Path | str | None,
    budgets: ResourceBudgets,
    query_embedder: Callable[..., Any] | None,
    fusion: Mapping[str, Any] | None,
) -> Any:
    resolver = _build_hub_resolver(
        pin, local_root=local_root, cache_dir=cache_dir
    )
    client_cls = resolve_export("StateLawsQueryClient")
    fusion_cfg = None
    if fusion is not None:
        fusion_cls = resolve_export("FusionConfig")
        fusion_cfg = (
            fusion
            if type(fusion).__name__ == "FusionConfig"
            else fusion_cls.from_mapping(fusion)
        )
    return client_cls(
        resolver,
        limits=budgets.to_query_limits(),
        query_embedder=query_embedder,
        fusion=fusion_cfg,
    )


# ---------------------------------------------------------------------------
# Public client
# ---------------------------------------------------------------------------


@dataclass
class StateLawsSparseGraphragClient:
    """Pinned, budgeted query client for the six public modes.

    Instantiation is cheap until the first query: the inner
    :class:`StateLawsQueryClient` (LCR-033) is built lazily. Offline
    ``local_root`` uses :class:`LocalRootTransport` and never touches
    the network. Live Dataset queries require a 40-hex revision.
    """

    pin: ImmutableQueryPin
    local_root: Path | None = None
    cache_dir: Path | str | None = None
    budgets: ResourceBudgets = field(default_factory=ResourceBudgets)
    query_embedder: Callable[..., Any] | None = field(
        default=None, repr=False
    )
    fusion: Mapping[str, Any] | None = None
    _inner: Any = field(default=None, init=False, repr=False)
    _last_result: Any = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.pin, ImmutableQueryPin):
            object.__setattr__(self, "pin", coerce_query_pin(self.pin))
        if not isinstance(self.budgets, ResourceBudgets):
            object.__setattr__(
                self, "budgets", ResourceBudgets.from_mapping(self.budgets)
            )
        if self.local_root is not None:
            object.__setattr__(
                self, "local_root", Path(self.local_root).expanduser().resolve()
            )

    @property
    def inner(self) -> Any:
        if self._inner is None:
            self._inner = _build_query_client(
                self.pin,
                local_root=self.local_root,
                cache_dir=self.cache_dir,
                budgets=self.budgets,
                query_embedder=self.query_embedder,
                fusion=self.fusion,
            )
        return self._inner

    @property
    def resolver(self) -> Any:
        return self.inner.resolver

    @property
    def last_result(self) -> Any:
        return self._last_result

    @property
    def last_fetch_trace(self) -> Mapping[str, Any]:
        result = self._last_result
        if result is None:
            return MappingProxyType({})
        if hasattr(result, "fetch_trace"):
            return MappingProxyType(dict(result.fetch_trace or {}))
        if isinstance(result, Mapping):
            return MappingProxyType(dict(result.get("fetch_trace") or {}))
        return MappingProxyType({})

    def _record(self, result: Any) -> Any:
        self._last_result = result
        return result

    def _filters(
        self,
        filters: Mapping[str, Any] | None,
        **kwargs: Any,
    ) -> Any | None:
        return build_legal_filters(filters, **kwargs)

    def bm25_search(
        self,
        query: str,
        *,
        top_k: int = DEFAULT_TOP_K,
        filters: Mapping[str, Any] | None = None,
        hydrate: bool = True,
        jurisdiction: str | None = None,
        code: str | None = None,
        citation: str | None = None,
        **filter_kwargs: Any,
    ) -> Any:
        """BM25 search routed exclusively by lexicographic term ranges."""

        filt = self._filters(
            filters,
            jurisdiction=jurisdiction,
            code=code,
            citation=citation,
            **filter_kwargs,
        )
        return self._record(
            self.inner.bm25_search(
                query, top_k=top_k, filters=filt, hydrate=hydrate
            )
        )

    def vector_search(
        self,
        query: str = "",
        *,
        query_vector: Sequence[float] | None = None,
        top_k: int = DEFAULT_TOP_K,
        filters: Mapping[str, Any] | None = None,
        hydrate: bool = True,
        candidate_centroids: int = DEFAULT_CANDIDATE_CENTROIDS,
        jurisdiction: str | None = None,
        code: str | None = None,
        citation: str | None = None,
        **filter_kwargs: Any,
    ) -> Any:
        """Dense retrieval that probes evaluated centroids then exact-scores."""

        filt = self._filters(
            filters,
            jurisdiction=jurisdiction,
            code=code,
            citation=citation,
            **filter_kwargs,
        )
        return self._record(
            self.inner.vector_search(
                query,
                query_vector=query_vector,
                top_k=top_k,
                filters=filt,
                hydrate=hydrate,
                candidate_centroids=candidate_centroids,
            )
        )

    def hybrid_search(
        self,
        query: str,
        *,
        query_vector: Sequence[float] | None = None,
        top_k: int = DEFAULT_TOP_K,
        filters: Mapping[str, Any] | None = None,
        hydrate: bool = True,
        candidate_centroids: int = DEFAULT_CANDIDATE_CENTROIDS,
        fusion: Mapping[str, Any] | None = None,
        jurisdiction: str | None = None,
        code: str | None = None,
        citation: str | None = None,
        **filter_kwargs: Any,
    ) -> Any:
        """Late-fuse compatible BM25 and vector rankings."""

        filt = self._filters(
            filters,
            jurisdiction=jurisdiction,
            code=code,
            citation=citation,
            **filter_kwargs,
        )
        return self._record(
            self.inner.hybrid_search(
                query,
                query_vector=query_vector,
                top_k=top_k,
                filters=filt,
                hydrate=hydrate,
                candidate_centroids=candidate_centroids,
                fusion=fusion,
            )
        )

    def neighbors(
        self,
        node_cid: str,
        *,
        direction: str = "out",
        limit: int = 16,
        include_similarity: bool = True,
    ) -> Any:
        """Bounded adjacency neighbors with authority labels."""

        return self._record(
            self.inner.neighbors(
                node_cid,
                direction=direction,
                limit=limit,
                include_similarity=include_similarity,
            )
        )

    def graph_walk(
        self,
        start_node_cid: str,
        *,
        direction: str = "out",
        max_depth: int | None = None,
        max_nodes: int | None = None,
        max_edges: int | None = None,
        include_similarity: bool = True,
    ) -> Any:
        """Bounded structural graph walk."""

        return self._record(
            self.inner.graph_walk(
                start_node_cid,
                direction=direction,
                max_depth=max_depth,
                max_nodes=max_nodes,
                max_edges=max_edges,
                include_similarity=include_similarity,
            )
        )

    def graph_search(
        self,
        start_node_cid: str,
        *,
        direction: str = "out",
        max_depth: int | None = None,
        max_nodes: int | None = None,
        max_edges: int | None = None,
        include_similarity: bool = True,
        neighbors_only: bool = False,
        limit: int = 16,
    ) -> Any:
        """Bounded structural graph walk (or neighbors when requested)."""

        if neighbors_only:
            return self.neighbors(
                start_node_cid,
                direction=direction,
                limit=limit,
                include_similarity=include_similarity,
            )
        return self.graph_walk(
            start_node_cid,
            direction=direction,
            max_depth=max_depth,
            max_nodes=max_nodes,
            max_edges=max_edges,
            include_similarity=include_similarity,
        )

    def semantic_graph_walk(
        self,
        start_node_cid: str,
        *,
        query: str = "",
        query_vector: Sequence[float] | None = None,
        direction: str = "out",
        include_similarity: bool = True,
        beam: Mapping[str, Any] | None = None,
        max_depth: int | None = None,
        max_nodes: int | None = None,
        max_edges: int | None = None,
        beam_width: int | None = None,
        candidate_centroids: int = DEFAULT_CANDIDATE_CENTROIDS,
    ) -> Any:
        """Embedding-guided semantic beam walk with entry-locator hydration."""

        beam_payload: dict[str, Any] = dict(beam or {})
        if max_depth is not None:
            beam_payload["max_depth"] = max_depth
        if max_nodes is not None:
            beam_payload["max_nodes"] = max_nodes
        if max_edges is not None:
            beam_payload["max_edges"] = max_edges
        if beam_width is not None:
            beam_payload["beam_width"] = beam_width
        beam_payload.setdefault("candidate_centroids", candidate_centroids)
        beam_cfg = None
        if beam_payload:
            beam_cls = resolve_export("SemanticBeamConfig")
            beam_cfg = beam_cls(
                **{
                    key: beam_payload[key]
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
                    if key in beam_payload
                }
            )
        return self._record(
            self.inner.semantic_graph_walk(
                start_node_cid,
                query=query,
                query_vector=query_vector,
                direction=direction,
                include_similarity=include_similarity,
                beam=beam_cfg,
            )
        )

    def semantic_graph_search(
        self,
        start_node_cid: str,
        **kwargs: Any,
    ) -> Any:
        """Alias for :meth:`semantic_graph_walk`."""

        return self.semantic_graph_walk(start_node_cid, **kwargs)

    def query(
        self,
        mode: str,
        *,
        query: str = "",
        start_node_cid: str | None = None,
        node_cid: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Dispatch a query to one of the six public modes."""

        resolved = normalize_query_mode(mode)
        if resolved == QUERY_MODE_BM25:
            return self.bm25_search(query, **kwargs)
        if resolved == QUERY_MODE_VECTOR:
            return self.vector_search(query, **kwargs)
        if resolved == QUERY_MODE_HYBRID:
            return self.hybrid_search(query, **kwargs)
        if resolved == QUERY_MODE_NEIGHBORS:
            target = node_cid or start_node_cid
            if not target:
                raise QueryModeError("neighbors mode requires node_cid")
            return self.neighbors(target, **kwargs)
        if resolved == QUERY_MODE_GRAPH_WALK:
            if not start_node_cid:
                raise QueryModeError("graph_walk mode requires start_node_cid")
            return self.graph_walk(start_node_cid, **kwargs)
        if resolved == QUERY_MODE_SEMANTIC_GRAPH_WALK:
            if not start_node_cid:
                raise QueryModeError(
                    "semantic_graph_walk mode requires start_node_cid"
                )
            return self.semantic_graph_walk(
                start_node_cid, query=query, **kwargs
            )
        raise QueryModeError(f"unhandled query mode {resolved!r}")


def open_query_client(
    *,
    revision: str = DEFAULT_REVISION,
    repo_id: str = DEFAULT_DATASET_REPO_ID,
    local_root: PathLike | None = None,
    cache_dir: PathLike | None = None,
    budgets: ResourceBudgets | Mapping[str, Any] | None = None,
    limits: ResourceBudgets | Mapping[str, Any] | None = None,
    query_embedder: Callable[..., Any] | None = None,
    fusion: Mapping[str, Any] | None = None,
    pin: ImmutableQueryPin | Mapping[str, Any] | str | None = None,
    no_cache: bool = False,
    reset_cache: bool = False,
) -> StateLawsSparseGraphragClient:
    """Open a pinned, budgeted query client (no I/O until the first query)."""

    resolved = coerce_query_pin(
        pin,
        revision=revision,
        dataset_repo_id=repo_id,
    )
    if no_cache and cache_dir is not None:
        raise StateLawsSparseGraphragError(
            "--no-cache cannot be combined with --cache-dir"
        )
    resolved_cache: Path | str | None = cache_dir
    if no_cache:
        import tempfile

        resolved_cache = Path(tempfile.mkdtemp(prefix="state-laws-query-nocache-"))
    elif reset_cache:
        if cache_dir is None:
            raise StateLawsSparseGraphragError(
                "--reset-cache requires --cache-dir"
            )
        target = Path(cache_dir).expanduser()
        if target.exists():
            import shutil

            shutil.rmtree(target)
        resolved_cache = cache_dir
    budget_source = budgets if budgets is not None else limits
    if isinstance(budget_source, ResourceBudgets):
        resolved_budgets = budget_source
    else:
        resolved_budgets = ResourceBudgets.from_mapping(budget_source)
    return StateLawsSparseGraphragClient(
        pin=resolved,
        local_root=Path(local_root) if local_root is not None else None,
        cache_dir=resolved_cache,
        budgets=resolved_budgets,
        query_embedder=query_embedder,
        fusion=fusion,
    )


def bm25_search(
    query: str,
    *,
    client: StateLawsSparseGraphragClient | None = None,
    **kwargs: Any,
) -> Any:
    """Module-level BM25 entry point."""

    return (client or open_query_client()).bm25_search(query, **kwargs)


def vector_search(
    query: str = "",
    *,
    client: StateLawsSparseGraphragClient | None = None,
    **kwargs: Any,
) -> Any:
    """Module-level vector entry point."""

    return (client or open_query_client()).vector_search(query, **kwargs)


def hybrid_search(
    query: str,
    *,
    client: StateLawsSparseGraphragClient | None = None,
    **kwargs: Any,
) -> Any:
    """Module-level hybrid entry point."""

    return (client or open_query_client()).hybrid_search(query, **kwargs)


def neighbors(
    node_cid: str,
    *,
    client: StateLawsSparseGraphragClient | None = None,
    **kwargs: Any,
) -> Any:
    """Module-level neighbors entry point."""

    return (client or open_query_client()).neighbors(node_cid, **kwargs)


def graph_walk(
    start_node_cid: str,
    *,
    client: StateLawsSparseGraphragClient | None = None,
    **kwargs: Any,
) -> Any:
    """Module-level graph-walk entry point."""

    return (client or open_query_client()).graph_walk(start_node_cid, **kwargs)


def semantic_graph_walk(
    start_node_cid: str,
    *,
    client: StateLawsSparseGraphragClient | None = None,
    **kwargs: Any,
) -> Any:
    """Module-level semantic-graph-walk entry point."""

    return (client or open_query_client()).semantic_graph_walk(
        start_node_cid, **kwargs
    )


# ---------------------------------------------------------------------------
# Package facade
# ---------------------------------------------------------------------------


@dataclass
class StateLawsSparseGraphragAPI:
    """Cohesive package facade for the query surface (LCR-034).

    Instantiation is cheap and dependency-free. Producer modules load
    only when a query client is opened.
    """

    dataset_repo_id: str = DEFAULT_DATASET_REPO_ID
    revision: str = DEFAULT_REVISION
    profile: str = RELEASE_PROFILE
    _client: StateLawsSparseGraphragClient | None = field(
        default=None, init=False, repr=False
    )

    def __post_init__(self) -> None:
        self.dataset_repo_id = _require_non_empty_str(
            self.dataset_repo_id, "dataset_repo_id", maximum=200
        )
        self.revision = require_immutable_pin(self.revision)
        self.profile = _require_non_empty_str(self.profile, "profile", maximum=128)

    def package_identity(self) -> dict[str, Any]:
        return {
            "corpus_id": CORPUS_ID,
            "dataset_repo_id": self.dataset_repo_id,
            "engine_task_id": ENGINE_TASK_ID,
            "full_index_download": FULL_INDEX_DOWNLOAD_REQUIRED,
            "goal_id": GOAL_ID,
            "jurisdiction_includes_dc": JURISDICTION_INCLUDES_DC,
            "modes": list(QUERY_MODES),
            "primary_key": PRIMARY_KEY,
            "producer": PRODUCER,
            "profile": self.profile,
            "program_id": PROGRAM_ID,
            "release_schema_version": RELEASE_SCHEMA_VERSION,
            "revision": self.revision,
            "schema_version": SCHEMA_VERSION,
            "task_id": TASK_ID,
        }

    def query_surface(self) -> dict[str, Any]:
        surface = query_surface()
        surface["dataset_repo_id"] = self.dataset_repo_id
        surface["revision"] = self.revision
        return surface

    def open_query_client(self, **kwargs: Any) -> StateLawsSparseGraphragClient:
        kwargs.setdefault("revision", self.revision)
        kwargs.setdefault("repo_id", self.dataset_repo_id)
        client = open_query_client(**kwargs)
        self._client = client
        return client

    def bm25_search(self, query: str, **kwargs: Any) -> Any:
        return self.open_query_client().bm25_search(query, **kwargs)

    def vector_search(self, query: str = "", **kwargs: Any) -> Any:
        return self.open_query_client().vector_search(query, **kwargs)

    def hybrid_search(self, query: str, **kwargs: Any) -> Any:
        return self.open_query_client().hybrid_search(query, **kwargs)

    def neighbors(self, node_cid: str, **kwargs: Any) -> Any:
        return self.open_query_client().neighbors(node_cid, **kwargs)

    def graph_walk(self, start_node_cid: str, **kwargs: Any) -> Any:
        return self.open_query_client().graph_walk(start_node_cid, **kwargs)

    def semantic_graph_walk(self, start_node_cid: str, **kwargs: Any) -> Any:
        return self.open_query_client().semantic_graph_walk(
            start_node_cid, **kwargs
        )


def open_api(
    *,
    dataset_repo_id: str = DEFAULT_DATASET_REPO_ID,
    revision: str = DEFAULT_REVISION,
) -> StateLawsSparseGraphragAPI:
    """Construct the package facade (import-safe, no I/O)."""

    return StateLawsSparseGraphragAPI(
        dataset_repo_id=dataset_repo_id, revision=revision
    )


__all__ = [
    "AUTHORIZES_HUB_UPLOAD",
    "AUTHORIZES_PUBLICATION",
    "AUTHORIZES_RELEASE",
    "BUDGET_DIMENSIONS",
    "CORPUS_ID",
    "DEFAULT_BEAM_WIDTH",
    "DEFAULT_BM25_WEIGHT",
    "DEFAULT_CANDIDATE_CENTROIDS",
    "DEFAULT_DATASET_REPO_ID",
    "DEFAULT_MANIFEST_NAME",
    "DEFAULT_MAX_BYTES",
    "DEFAULT_MAX_DEPTH",
    "DEFAULT_MAX_EDGES",
    "DEFAULT_MAX_NODES",
    "DEFAULT_MAX_ROWS",
    "DEFAULT_MAX_SHARDS",
    "DEFAULT_MAX_TIME_MS",
    "DEFAULT_REVISION",
    "DEFAULT_RRF_K",
    "DEFAULT_TOP_K",
    "DEFAULT_VECTOR_WEIGHT",
    "ENGINE_PRODUCER",
    "ENGINE_TASK_ID",
    "FILTER_FIELDS",
    "FULL_INDEX_DOWNLOAD_REQUIRED",
    "GOAL_ID",
    "HUB_UPLOAD",
    "JURISDICTION_INCLUDES_DC",
    "PRIMARY_KEY",
    "PRODUCER",
    "PROGRAM_ID",
    "QUERY_MODES",
    "QUERY_MODE_ALIASES",
    "QUERY_MODE_BM25",
    "QUERY_MODE_GRAPH_WALK",
    "QUERY_MODE_HYBRID",
    "QUERY_MODE_NEIGHBORS",
    "QUERY_MODE_SEMANTIC_GRAPH_WALK",
    "QUERY_MODE_VECTOR",
    "RELEASE_PROFILE",
    "RELEASE_SCHEMA_VERSION",
    "SCHEMA_VERSION",
    "SECRET_ENV_NAMES",
    "SUPPORTED_RELEASE_SCHEMAS",
    "TASK_ID",
    "ImmutablePinError",
    "ImmutableQueryPin",
    "LazyImportError",
    "QueryModeError",
    "ResourceBudgetError",
    "ResourceBudgets",
    "SecretLeakageError",
    "StateLawsSparseGraphragAPI",
    "StateLawsSparseGraphragClient",
    "StateLawsSparseGraphragError",
    "assert_no_secret_payload",
    "available_lazy_exports",
    "bm25_search",
    "build_legal_filters",
    "canonical_json_bytes",
    "coerce_query_pin",
    "content_sha256",
    "default_resource_budgets",
    "fetched_relative_paths",
    "graph_walk",
    "hybrid_search",
    "import_is_optional_dependency_safe",
    "is_mutable_pin",
    "list_query_modes",
    "neighbors",
    "normalize_query_mode",
    "open_api",
    "open_query_client",
    "package_query_result",
    "proves_sparse_io",
    "query_replay_fingerprint",
    "query_surface",
    "redact_fetch_trace",
    "redact_payload",
    "require_immutable_pin",
    "resolve_export",
    "semantic_graph_walk",
    "vector_search",
]
