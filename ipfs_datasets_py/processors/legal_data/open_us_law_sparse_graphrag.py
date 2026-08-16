"""Open US Law sparse GraphRAG package API (OUL-035).

Public, lazy, optional-dependency-safe query surface for the
``open-us-law-sparse-graphrag/v1`` release. The package and the
``query_open_us_law_hf`` CLI expose the same five modes:

* ``bm25`` — lexicographic term-range BM25
* ``vector`` — evaluated-centroid dense retrieval
* ``hybrid`` — late fusion of compatible BM25 + vector rankings
* ``graph`` — bounded structural walk / neighbors
* ``semantic-graph`` — embedding-guided beam walk

Jurisdiction and status filters, immutable Dataset/Bucket pins, fetch
traces, and explicit resource budgets are first-class. Queries fetch
**only** routed artifacts; the full index is never downloaded.

Importing this module does not require pyarrow, sentence-transformers,
torch, or a Hugging Face hub client. Producer modules
(``open_us_law_query``, ``open_us_law_resolver``, generic GraphRAG
resolver/query types) are resolved on first use.

This module does not authorize publication or a live exact-51 query.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from importlib import import_module
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Literal, Optional, Union
import hashlib
import json
import os
import re

# ---------------------------------------------------------------------------
# Identity / pins (stdlib only)
# ---------------------------------------------------------------------------

SCHEMA_VERSION: Final = "open-us-law-sparse-graphrag-package-api/v1"
TASK_ID: Final = "OUL-035"
GOAL_ID: Final = "OUL-G050"
PRODUCER: Final = "open_us_law_sparse_graphrag.py"
PROGRAM_ID: Final = "open-us-law-reindex-v1"
BOARD_NAMESPACE: Final = "open-us-law-reindex-v1"
BUNDLE: Final = "query-cli"
RELEASE_PROFILE: Final = "open-us-law-sparse-graphrag/v1"
RELEASE_SCHEMA_VERSION: Final = "open-us-law-hf-release/v1"
DEFAULT_DATASET_REPO_ID: Final = "justicedao/open-us-law-sparse-graphrag"
DEFAULT_BUCKET_ID: Final = "justicedao/open-us-law-bucket"
DEFAULT_REVISION: Final = "75cfc5982dc3a6808614cd4eb9b4238f8f9308b8"
DEFAULT_MANIFEST_NAME: Final = "manifest.json"
PRIMARY_KEY: Final = "entry_cid"
CORPUS_ID: Final = "open-us-law"

AUTHORIZES_PUBLICATION: Final = False
AUTHORIZES_RELEASE: Final = False
FULL_INDEX_DOWNLOAD_REQUIRED: Final = False

# Five public modes required by OUL-035 acceptance.
QUERY_MODE_BM25: Final = "bm25"
QUERY_MODE_VECTOR: Final = "vector"
QUERY_MODE_HYBRID: Final = "hybrid"
QUERY_MODE_GRAPH: Final = "graph"
QUERY_MODE_SEMANTIC_GRAPH: Final = "semantic-graph"
QUERY_MODES: Final = (
    QUERY_MODE_BM25,
    QUERY_MODE_VECTOR,
    QUERY_MODE_HYBRID,
    QUERY_MODE_GRAPH,
    QUERY_MODE_SEMANTIC_GRAPH,
)

# CLI / caller aliases mapped onto the five public modes.
QUERY_MODE_ALIASES: Final = MappingProxyType(
    {
        "bm25_search": QUERY_MODE_BM25,
        "vector_search": QUERY_MODE_VECTOR,
        "hybrid_search": QUERY_MODE_HYBRID,
        "graph-walk": QUERY_MODE_GRAPH,
        "graph_walk": QUERY_MODE_GRAPH,
        "graph-search": QUERY_MODE_GRAPH,
        "neighbors": QUERY_MODE_GRAPH,
        "semantic-graph-walk": QUERY_MODE_SEMANTIC_GRAPH,
        "semantic_graph_walk": QUERY_MODE_SEMANTIC_GRAPH,
        "semantic_graph": QUERY_MODE_SEMANTIC_GRAPH,
        "semantic-graph-search": QUERY_MODE_SEMANTIC_GRAPH,
    }
)

FILTER_FIELDS: Final = (
    "jurisdiction",
    "status",
    "edition",
    "code_family",
    "title",
    "chapter",
    "section",
    "source",
    "release_point",
    "citation",
    "legal_id",
    "version",
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

DEFAULT_MAX_BYTES: Final = 50_000_000
DEFAULT_MAX_SHARDS: Final = 64
DEFAULT_MAX_ROWS: Final = 50_000
DEFAULT_MAX_NODES: Final = 256
DEFAULT_MAX_EDGES: Final = 1_024
DEFAULT_MAX_DEPTH: Final = 8
DEFAULT_MAX_TIME_MS: Final = 60_000
DEFAULT_TOP_K: Final = 5
DEFAULT_CANDIDATE_CENTROIDS: Final = 4

SUPPORTED_RELEASE_SCHEMAS: Final = frozenset(
    {
        RELEASE_PROFILE,
        "open-us-law-hf-release/v1",
        "open-us-law-identity-schema-v1",
        "hf-graphrag-release/v1",
        "publicus-ir-graphrag/v2",
        "uscode-sparse-graphrag-release-schema-v2",
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
_SHA256_RE: Final = re.compile(r"^[0-9a-f]{64}$")

SECRET_ENV_NAMES: Final = (
    "HF_TOKEN",
    "HUGGING_FACE_HUB_TOKEN",
    "HUGGINGFACE_TOKEN",
    "HUGGINGFACEHUB_API_TOKEN",
)

TransportKind = Literal["dataset", "bucket"]
PathLike = Union[str, Path]
JsonMapping = Mapping[str, Any]


# ---------------------------------------------------------------------------
# Lazy producer map
# ---------------------------------------------------------------------------

_LAZY_EXPORTS: Final[Mapping[str, tuple[str, str]]] = MappingProxyType(
    {
        "OpenUsLawQueryClient": (".open_us_law_query", "OpenUsLawQueryClient"),
        "OpenUsLawQueryResult": (".open_us_law_query", "OpenUsLawQueryResult"),
        "OpenUsLawQueryError": (".open_us_law_query", "OpenUsLawQueryError"),
        "OpenUsLawQueryInputError": (
            ".open_us_law_query",
            "OpenUsLawQueryInputError",
        ),
        "LegalFilters": (".open_us_law_query", "LegalFilters"),
        "FusionConfig": (".open_us_law_query", "FusionConfig"),
        "SemanticBeamConfig": (".open_us_law_query", "SemanticBeamConfig"),
        "OpenUsLawResolver": (".open_us_law_resolver", "OpenUsLawResolver"),
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


class OpenUsLawSparseGraphragError(ValueError):
    """Base error for the Open US Law package query API."""

    code: str = "open_us_law_sparse_graphrag_error"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "kind": "error", "message": str(self)}


class ImmutablePinError(OpenUsLawSparseGraphragError):
    """Raised when a Dataset/Bucket pin is missing, empty, or mutable."""

    code = "immutable_pin_invalid"


class QueryModeError(OpenUsLawSparseGraphragError):
    """Raised when a query mode is unknown."""

    code = "query_mode_invalid"


class ResourceBudgetError(OpenUsLawSparseGraphragError):
    """Raised when a resource budget is malformed."""

    code = "resource_budget_invalid"


class LazyImportError(OpenUsLawSparseGraphragError):
    """Raised when an optional producer module cannot be imported."""

    code = "lazy_import_failed"


class SecretLeakageError(OpenUsLawSparseGraphragError):
    """Raised when a payload would emit a secret-bearing value."""

    code = "secret_leakage"


# ---------------------------------------------------------------------------
# Stdlib helpers
# ---------------------------------------------------------------------------


def _require_non_empty_str(value: Any, name: str, *, maximum: int = 1024) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OpenUsLawSparseGraphragError(f"{name} must be a non-empty string")
    text = value.strip()
    if "\x00" in text:
        raise OpenUsLawSparseGraphragError(f"{name} must not contain NUL")
    if len(text) > maximum:
        raise OpenUsLawSparseGraphragError(
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
        raise OpenUsLawSparseGraphragError(
            f"{name!r} is not a registered lazy export; "
            f"known={sorted(_LAZY_EXPORTS)}"
        )
    return _load_lazy(name)


# ---------------------------------------------------------------------------
# Modes / pins / budgets
# ---------------------------------------------------------------------------


def list_query_modes() -> tuple[str, ...]:
    """Return the five public query modes in declaration order."""

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
    """Return True when *value* is empty or a mutable Dataset/Bucket pointer."""

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
    """Require an immutable 40-hex Hub commit SHA for Dataset queries."""

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


def require_bucket_pin(value: Any, *, name: str = "bucket_prefix") -> tuple[str, str]:
    """Return ``(manifest_sha256, releases/<digest>/)`` for a Bucket pin."""

    if not isinstance(value, str) or not value.strip():
        raise ImmutablePinError(
            f"{name} is required: bucket queries need releases/<manifest_sha256>/"
        )
    text = value.strip().strip("/")
    if is_mutable_pin(text):
        raise ImmutablePinError(
            f"{name} must not be a mutable pointer ({value!r})"
        )
    if text.casefold().startswith("sha256:"):
        digest = text.split(":", 1)[1].strip().casefold()
    elif text.casefold().startswith("releases/"):
        digest = text.split("/", 1)[1].strip().strip("/").casefold()
    else:
        digest = text.casefold()
    if not _SHA256_RE.fullmatch(digest):
        raise ImmutablePinError(
            f"{name} must be releases/<64-hex sha256>/, got {value!r}"
        )
    return digest, f"releases/{digest}/"


@dataclass(frozen=True, slots=True)
class ImmutableQueryPin:
    """Sealed Dataset (40-hex) or Bucket (``releases/<sha256>/``) pin."""

    transport: TransportKind
    revision: str | None = None
    bucket_prefix: str | None = None
    manifest_sha256: str | None = None
    dataset_repo_id: str = DEFAULT_DATASET_REPO_ID
    bucket_id: str = DEFAULT_BUCKET_ID

    def __post_init__(self) -> None:
        kind = str(self.transport or "").strip().casefold()
        if kind not in {"dataset", "bucket"}:
            raise ImmutablePinError(
                f"transport must be 'dataset' or 'bucket', got {self.transport!r}"
            )
        object.__setattr__(self, "transport", kind)
        repo = _require_non_empty_str(
            self.dataset_repo_id, "dataset_repo_id", maximum=200
        )
        bucket = _require_non_empty_str(self.bucket_id, "bucket_id", maximum=200)
        object.__setattr__(self, "dataset_repo_id", repo)
        object.__setattr__(self, "bucket_id", bucket)
        if kind == "dataset":
            object.__setattr__(
                self, "revision", require_immutable_pin(self.revision)
            )
            object.__setattr__(self, "bucket_prefix", None)
            object.__setattr__(self, "manifest_sha256", None)
        else:
            digest, prefix = require_bucket_pin(
                self.bucket_prefix or self.manifest_sha256 or ""
            )
            object.__setattr__(self, "revision", None)
            object.__setattr__(self, "bucket_prefix", prefix)
            object.__setattr__(self, "manifest_sha256", digest)

    @classmethod
    def dataset(
        cls,
        revision: str,
        *,
        dataset_repo_id: str = DEFAULT_DATASET_REPO_ID,
    ) -> "ImmutableQueryPin":
        return cls(
            transport="dataset",
            revision=revision,
            dataset_repo_id=dataset_repo_id,
        )

    @classmethod
    def bucket(
        cls,
        manifest_sha256: str,
        *,
        bucket_id: str = DEFAULT_BUCKET_ID,
    ) -> "ImmutableQueryPin":
        return cls(
            transport="bucket",
            manifest_sha256=manifest_sha256,
            bucket_id=bucket_id,
        )

    @property
    def identity(self) -> str:
        if self.transport == "dataset":
            return f"dataset:{self.dataset_repo_id}:{self.revision}"
        return f"bucket:{self.bucket_id}:{self.manifest_sha256}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "bucket_id": self.bucket_id,
            "bucket_prefix": self.bucket_prefix,
            "dataset_repo_id": self.dataset_repo_id,
            "identity": self.identity,
            "manifest_sha256": self.manifest_sha256,
            "revision": self.revision,
            "transport": self.transport,
        }


def coerce_query_pin(
    pin: ImmutableQueryPin | Mapping[str, Any] | str | None = None,
    *,
    revision: str | None = None,
    transport: TransportKind = "dataset",
    bucket_prefix: str | None = None,
    dataset_repo_id: str = DEFAULT_DATASET_REPO_ID,
    bucket_id: str = DEFAULT_BUCKET_ID,
) -> ImmutableQueryPin:
    """Normalize a pin object, mapping, or revision string."""

    if isinstance(pin, ImmutableQueryPin):
        return pin
    if isinstance(pin, Mapping):
        return ImmutableQueryPin(
            transport=str(pin.get("transport") or transport),
            revision=pin.get("revision") if "revision" in pin else revision,
            bucket_prefix=pin.get("bucket_prefix", bucket_prefix),
            manifest_sha256=pin.get("manifest_sha256"),
            dataset_repo_id=str(pin.get("dataset_repo_id") or dataset_repo_id),
            bucket_id=str(pin.get("bucket_id") or bucket_id),
        )
    if isinstance(pin, str) and pin.strip():
        if transport == "bucket" or pin.strip().casefold().startswith("releases/"):
            return ImmutableQueryPin.bucket(pin, bucket_id=bucket_id)
        return ImmutableQueryPin.dataset(pin, dataset_repo_id=dataset_repo_id)
    if transport == "bucket":
        return ImmutableQueryPin(
            transport="bucket",
            bucket_prefix=bucket_prefix,
            dataset_repo_id=dataset_repo_id,
            bucket_id=bucket_id,
        )
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
        "authorizes_publication": AUTHORIZES_PUBLICATION,
        "authorizes_release": AUTHORIZES_RELEASE,
        "board_namespace": BOARD_NAMESPACE,
        "budget_dimensions": list(BUDGET_DIMENSIONS),
        "bundle": BUNDLE,
        "corpus_id": CORPUS_ID,
        "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
        "default_budgets": default_resource_budgets().to_dict(),
        "fetch_traces": True,
        "filter_fields": list(FILTER_FIELDS),
        "full_index_download": FULL_INDEX_DOWNLOAD_REQUIRED,
        "goal_id": GOAL_ID,
        "modes": list(QUERY_MODES),
        "pins": {
            "bucket": "releases/<manifest_sha256>/",
            "bucket_id": DEFAULT_BUCKET_ID,
            "dataset": "40-hex-commit",
            "dataset_repo_id": DEFAULT_DATASET_REPO_ID,
            "mutable_rejected": True,
        },
        "primary_key": PRIMARY_KEY,
        "producer": PRODUCER,
        "profile": RELEASE_PROFILE,
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
        "schema": "open-us-law-package-import-receipt/v1",
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
    status: str | None = None,
    edition: str | None = None,
    code_family: str | None = None,
    title: str | None = None,
    chapter: str | None = None,
    section: str | None = None,
    source: str | None = None,
    release_point: str | None = None,
    citation: str | None = None,
    legal_id: str | None = None,
    version: str | None = None,
) -> Any | None:
    """Build :class:`LegalFilters` from a mapping plus jurisdiction/status."""

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
        "status": status,
        "edition": edition,
        "code_family": code_family,
        "title": title,
        "chapter": chapter,
        "section": section,
        "source": source,
        "release_point": release_point,
        "citation": citation,
        "legal_id": legal_id,
        "version": version,
    }
    for key, value in explicit.items():
        if value not in (None, ""):
            payload[key] = value
    if not payload:
        return None
    filter_cls = resolve_export("LegalFilters")
    return filter_cls.from_mapping(payload)


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


def package_query_result(
    result: Any,
    *,
    pin: ImmutableQueryPin | None = None,
    include_trace: bool = True,
    mode: str | None = None,
) -> dict[str, Any]:
    """Render a query result with pin, budgets, and optional fetch trace."""

    if hasattr(result, "to_dict"):
        payload = dict(result.to_dict())
    elif isinstance(result, Mapping):
        payload = dict(result)
    else:
        raise OpenUsLawSparseGraphragError("query result must be a mapping")
    if mode:
        payload["mode"] = normalize_query_mode(mode)
    elif payload.get("mode"):
        try:
            payload["mode"] = normalize_query_mode(str(payload["mode"]))
        except QueryModeError:
            pass
    payload["full_index_downloaded"] = False
    payload["schema_version"] = payload.get("schema_version") or SCHEMA_VERSION
    payload["task_id"] = TASK_ID
    payload["goal_id"] = GOAL_ID
    if pin is not None:
        payload["pin"] = pin.to_dict()
    if not include_trace:
        payload.pop("fetch_trace", None)
    else:
        payload.setdefault("fetch_trace", {})
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
        "revision": pin.revision or DEFAULT_REVISION,
        "cache_dir": cache_dir,
        "supported_schemas": set(SUPPORTED_RELEASE_SCHEMAS),
    }
    if local_root is not None:
        root = Path(local_root).expanduser().resolve()
        if not root.is_dir():
            raise OpenUsLawSparseGraphragError(
                f"local_root is not a directory: {root}"
            )
        transport_cls = resolve_export("LocalRootTransport")
        kwargs["transport"] = transport_cls(root)
        kwargs["local_root"] = root
        return resolver_cls(**kwargs)

    if pin.transport == "bucket":
        raise OpenUsLawSparseGraphragError(
            "live bucket queries require OpenUsLawResolver; "
            "pass local_root for offline fixtures"
        )
    # Live Dataset: go through the fail-closed OUL resolver (publication gate).
    oul_cls = resolve_export("OpenUsLawResolver")
    oul = oul_cls.for_dataset(
        pin.revision or DEFAULT_REVISION,
        cache_dir=cache_dir,
    )
    hub = oul.hub_resolver
    if hub is None:
        raise OpenUsLawSparseGraphragError(
            "OpenUsLawResolver did not produce a Dataset hub resolver"
        )
    return hub


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
    client_cls = resolve_export("OpenUsLawQueryClient")
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
class OpenUsLawSparseGraphragClient:
    """Pinned, budgeted query client for the five public modes.

    Instantiation is cheap until the first query: the inner
    :class:`OpenUsLawQueryClient` is built lazily. Offline
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
        status: str | None = None,
        **filter_kwargs: Any,
    ) -> Any:
        """BM25 search routed exclusively by lexicographic term ranges."""

        filt = self._filters(
            filters, jurisdiction=jurisdiction, status=status, **filter_kwargs
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
        status: str | None = None,
        **filter_kwargs: Any,
    ) -> Any:
        """Dense retrieval that probes evaluated centroids then exact-scores."""

        filt = self._filters(
            filters, jurisdiction=jurisdiction, status=status, **filter_kwargs
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
        status: str | None = None,
        **filter_kwargs: Any,
    ) -> Any:
        """Late-fuse compatible BM25 and vector rankings."""

        filt = self._filters(
            filters, jurisdiction=jurisdiction, status=status, **filter_kwargs
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

    def semantic_graph_search(
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

    def query(
        self,
        mode: str,
        *,
        query: str = "",
        start_node_cid: str | None = None,
        **kwargs: Any,
    ) -> Any:
        """Dispatch a query to one of the five public modes."""

        resolved = normalize_query_mode(mode)
        if resolved == QUERY_MODE_BM25:
            return self.bm25_search(query, **kwargs)
        if resolved == QUERY_MODE_VECTOR:
            return self.vector_search(query, **kwargs)
        if resolved == QUERY_MODE_HYBRID:
            return self.hybrid_search(query, **kwargs)
        if resolved == QUERY_MODE_GRAPH:
            if not start_node_cid:
                raise QueryModeError("graph mode requires start_node_cid")
            return self.graph_search(start_node_cid, **kwargs)
        if resolved == QUERY_MODE_SEMANTIC_GRAPH:
            if not start_node_cid:
                raise QueryModeError(
                    "semantic-graph mode requires start_node_cid"
                )
            return self.semantic_graph_search(
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
    query_embedder: Callable[..., Any] | None = None,
    fusion: Mapping[str, Any] | None = None,
    transport: TransportKind = "dataset",
    bucket_prefix: str | None = None,
    pin: ImmutableQueryPin | Mapping[str, Any] | str | None = None,
) -> OpenUsLawSparseGraphragClient:
    """Open a pinned, budgeted query client (no I/O until the first query)."""

    resolved = coerce_query_pin(
        pin,
        revision=revision,
        transport=transport,
        bucket_prefix=bucket_prefix,
        dataset_repo_id=repo_id,
    )
    return OpenUsLawSparseGraphragClient(
        pin=resolved,
        local_root=Path(local_root) if local_root is not None else None,
        cache_dir=cache_dir,
        budgets=ResourceBudgets.from_mapping(
            budgets.to_dict() if isinstance(budgets, ResourceBudgets) else budgets
        ),
        query_embedder=query_embedder,
        fusion=fusion,
    )


def bm25_search(
    query: str,
    *,
    client: OpenUsLawSparseGraphragClient | None = None,
    **kwargs: Any,
) -> Any:
    """Module-level BM25 entry point."""

    return (client or open_query_client()).bm25_search(query, **kwargs)


def vector_search(
    query: str = "",
    *,
    client: OpenUsLawSparseGraphragClient | None = None,
    **kwargs: Any,
) -> Any:
    """Module-level vector entry point."""

    return (client or open_query_client()).vector_search(query, **kwargs)


def hybrid_search(
    query: str,
    *,
    client: OpenUsLawSparseGraphragClient | None = None,
    **kwargs: Any,
) -> Any:
    """Module-level hybrid entry point."""

    return (client or open_query_client()).hybrid_search(query, **kwargs)


def graph_search(
    start_node_cid: str,
    *,
    client: OpenUsLawSparseGraphragClient | None = None,
    **kwargs: Any,
) -> Any:
    """Module-level graph entry point."""

    return (client or open_query_client()).graph_search(start_node_cid, **kwargs)


def semantic_graph_search(
    start_node_cid: str,
    *,
    client: OpenUsLawSparseGraphragClient | None = None,
    **kwargs: Any,
) -> Any:
    """Module-level semantic-graph entry point."""

    return (client or open_query_client()).semantic_graph_search(
        start_node_cid, **kwargs
    )


# ---------------------------------------------------------------------------
# Package facade
# ---------------------------------------------------------------------------


@dataclass
class OpenUsLawSparseGraphragAPI:
    """Cohesive package facade for the query surface (OUL-035).

    Instantiation is cheap and dependency-free. Producer modules load
    only when a query client is opened.
    """

    dataset_repo_id: str = DEFAULT_DATASET_REPO_ID
    revision: str = DEFAULT_REVISION
    profile: str = RELEASE_PROFILE
    _client: OpenUsLawSparseGraphragClient | None = field(
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
            "full_index_download": FULL_INDEX_DOWNLOAD_REQUIRED,
            "goal_id": GOAL_ID,
            "modes": list(QUERY_MODES),
            "primary_key": PRIMARY_KEY,
            "producer": PRODUCER,
            "profile": self.profile,
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

    def open_query_client(self, **kwargs: Any) -> OpenUsLawSparseGraphragClient:
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

    def graph_search(self, start_node_cid: str, **kwargs: Any) -> Any:
        return self.open_query_client().graph_search(start_node_cid, **kwargs)

    def semantic_graph_search(self, start_node_cid: str, **kwargs: Any) -> Any:
        return self.open_query_client().semantic_graph_search(
            start_node_cid, **kwargs
        )


def open_api(
    *,
    dataset_repo_id: str = DEFAULT_DATASET_REPO_ID,
    revision: str = DEFAULT_REVISION,
) -> OpenUsLawSparseGraphragAPI:
    """Construct the package facade (import-safe, no I/O)."""

    return OpenUsLawSparseGraphragAPI(
        dataset_repo_id=dataset_repo_id, revision=revision
    )


__all__ = [
    "AUTHORIZES_PUBLICATION",
    "AUTHORIZES_RELEASE",
    "BUDGET_DIMENSIONS",
    "CORPUS_ID",
    "DEFAULT_BUCKET_ID",
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
    "DEFAULT_TOP_K",
    "FILTER_FIELDS",
    "FULL_INDEX_DOWNLOAD_REQUIRED",
    "GOAL_ID",
    "PRIMARY_KEY",
    "PRODUCER",
    "QUERY_MODES",
    "QUERY_MODE_ALIASES",
    "QUERY_MODE_BM25",
    "QUERY_MODE_GRAPH",
    "QUERY_MODE_HYBRID",
    "QUERY_MODE_SEMANTIC_GRAPH",
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
    "OpenUsLawSparseGraphragAPI",
    "OpenUsLawSparseGraphragClient",
    "OpenUsLawSparseGraphragError",
    "QueryModeError",
    "ResourceBudgetError",
    "ResourceBudgets",
    "SecretLeakageError",
    "assert_no_secret_payload",
    "available_lazy_exports",
    "bm25_search",
    "build_legal_filters",
    "canonical_json_bytes",
    "coerce_query_pin",
    "content_sha256",
    "default_resource_budgets",
    "fetched_relative_paths",
    "graph_search",
    "hybrid_search",
    "import_is_optional_dependency_safe",
    "is_mutable_pin",
    "list_query_modes",
    "normalize_query_mode",
    "open_api",
    "open_query_client",
    "package_query_result",
    "proves_sparse_io",
    "query_surface",
    "require_bucket_pin",
    "require_immutable_pin",
    "resolve_export",
    "semantic_graph_search",
    "vector_search",
]
