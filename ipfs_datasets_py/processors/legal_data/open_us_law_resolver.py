"""Content-addressed Bucket and immutable Dataset resolution (OUL-033).

Fail-closed dual-transport resolver for Open US Law sparse GraphRAG releases:

* **Dataset** queries pin ``justicedao/open-us-law-sparse-graphrag`` to an
  exact 40-hex Hub commit SHA. Mutable refs (``main``, ``latest``,
  ``HEAD``, ``refs/...``) are refused before any fetch.
* **Bucket** queries pin ``justicedao/open-us-law-bucket`` to
  ``releases/<manifest_sha256>/`` and verify the sealed manifest digest
  plus every advertised descriptor. ``LATEST.json`` and other mutable
  pointers are never trusted.
* Both transports fetch **only** route-justified, release-relative
  artifacts and charge explicit byte, shard, row, time, graph, and
  centroid budgets. Drift, traversal, symlinks, unauthorized targets,
  and budget overrun fail closed.

Unit tests inject a fake transport. Credentials are never required
offline and never appear in traces, representations, or public errors.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tempfile
import time
from types import MappingProxyType
from typing import Any, Final, Literal, Optional, Protocol, runtime_checkable

from ipfs_datasets_py.processors.legal_data.open_us_law_publication_gate import (
    AUTHORIZED_BUCKET_ID,
    AUTHORIZED_DATASET_REPO_ID,
    BUCKET_POINTER_PATH,
    MutableQueryPinError,
    PublicationGateDeniedError,
    PublicationGateError,
    PublicationRequest,
    TargetUnauthorizedError,
    parse_release_prefix_path,
    release_prefix_for,
    require_immutable_revision,
    require_publication_gate,
)
from ipfs_datasets_py.processors.legal_data.open_us_law_schema import (
    DEFAULT_CANDIDATE_CENTROIDS,
    MAX_ROWS_PER_PHYSICAL_SHARD,
    RELEASE_PROFILE,
    digest_mapping,
)
from ipfs_datasets_py.retrieval.hf_graphrag.resolver import (
    DEFAULT_MAX_ARTIFACT_BYTES,
    ArtifactDescriptor,
    CacheCollisionError,
    CredentialLeakageError,
    DigestDriftError,
    HuggingFaceHubTransport,
    ImmutableHubResolver,
    LocalRootTransport,
    MappingTransport,
    MissingArtifactError,
    MutableRevisionError,
    OversizedArtifactError,
    ResolvedArtifact,
    ResolverError,
    SchemaMismatchError,
    SymlinkRejectedError,
    TransportError,
    UnsafePathError,
    _assert_no_credential_payload,
    _redact_secrets,
    _TOKEN_LIKE_RE,
    file_sha256_and_size,
    normalize_sha256,
    raw_sha256_cid,
    safe_relative_path,
    validate_immutable_revision,
    validate_repo_id,
)

# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------

RESOLVER_SCHEMA_VERSION: Final = "open-us-law-resolver/v1"
FETCH_TRACE_SCHEMA_VERSION: Final = "open-us-law-resolver-fetch-trace/v1"
CACHE_ALIAS_SCHEMA_VERSION: Final = "open-us-law-resolver-cache-alias/v1"
TASK_ID: Final = "OUL-033"
GOAL_ID: Final = "OUL-G050"
PRODUCER: Final = "open_us_law_resolver.py"
PROGRAM_ID: Final = "open-us-law-reindex-v1"

DEFAULT_MANIFEST_NAME: Final = "manifest.json"
DEFAULT_DATASET_REPO_ID: Final = AUTHORIZED_DATASET_REPO_ID
DEFAULT_BUCKET_ID: Final = AUTHORIZED_BUCKET_ID

DEFAULT_CACHE_DIR: Final = Path(
    "~/.cache/ipfs_datasets_py/open-us-law-resolver"
).expanduser()

DEFAULT_SUPPORTED_RELEASE_SCHEMAS: Final = frozenset(
    {
        RELEASE_PROFILE,
        "open-us-law-hf-release/v1",
        "open-us-law-identity-schema-v1",
        "publicus-ir-graphrag/v2",
        "hf-graphrag-release/v1",
        "uscode-sparse-graphrag-release-schema-v2",
    }
)

TransportKind = Literal["dataset", "bucket"]

# Default session budgets (tight enough for unit tests; callers may widen).
DEFAULT_MAX_BYTES: Final = 64 * 1024 * 1024
DEFAULT_MAX_SHARDS: Final = 64
DEFAULT_MAX_ROWS: Final = 65_536
DEFAULT_MAX_TIME_MS: Final = 30_000
DEFAULT_MAX_GRAPH_NODES: Final = 1_024
DEFAULT_MAX_GRAPH_EDGES: Final = 4_096
DEFAULT_MAX_GRAPH_DEPTH: Final = 8
DEFAULT_MAX_CENTROIDS: Final = DEFAULT_CANDIDATE_CENTROIDS

BUDGET_DIMENSIONS: Final = (
    "bytes",
    "shards",
    "rows",
    "time",
    "graph",
    "centroids",
)

ROUTE_FAMILIES: Final = frozenset(
    {
        "control_plane",
        "routing_index",
        "bm25_documents",
        "bm25_postings",
        "vectors",
        "centroids",
        "vector_locator",
        "corpus",
        "graph_nodes",
        "graph_edges",
        "graph_adjacency",
        "graph_adjacency_out",
        "graph_adjacency_in",
        "source_receipts",
    }
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
        "graph_edge",
        "locator_lookup",
        "replay",
    }
)

CONTROL_PLANE_FAMILIES: Final = frozenset({"control_plane", "routing_index"})
GRAPH_NODE_FAMILIES: Final = frozenset({"graph_nodes"})
GRAPH_EDGE_FAMILIES: Final = frozenset(
    {"graph_edges", "graph_adjacency", "graph_adjacency_out", "graph_adjacency_in"}
)
CENTROID_FAMILIES: Final = frozenset({"centroids"})
CENTROID_REASONS: Final = frozenset({"centroid_probe"})
MUTABLE_POINTER_NAMES: Final = frozenset(
    {
        BUCKET_POINTER_PATH.casefold(),
        "latest.json",
        "latest",
        "main",
        "master",
        "head",
        "releases/latest",
        "releases/latest.json",
        "releases/main",
    }
)
_READ_CHUNK: Final = 8 * 1024 * 1024


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class OpenUsLawResolverError(ResolverError):
    """Base class for fail-closed Open US Law resolver failures."""


class MutablePointerError(OpenUsLawResolverError, MutableQueryPinError):
    """Raised when a query pin is mutable (``main``, ``latest``, pointer)."""


class UnjustifiedFetchError(OpenUsLawResolverError):
    """Raised when a fetch is attempted without a valid route justification."""


class DescriptorRequiredError(OpenUsLawResolverError):
    """Raised when a data-plane fetch lacks a verified descriptor."""


class UnauthorizedTargetError(OpenUsLawResolverError, TargetUnauthorizedError):
    """Raised when the dataset or bucket identity is outside sealed authority."""


class BucketPrefixError(OpenUsLawResolverError):
    """Raised when a bucket pin is not ``releases/<manifest_sha256>/``."""


class ResolverBudgetExhausted(OpenUsLawResolverError):
    """Typed budget exhaustion — never a silent truncation."""

    def __init__(
        self,
        dimension: str,
        *,
        usage: Mapping[str, Any],
        limits: Mapping[str, Any],
        message: str | None = None,
    ) -> None:
        dim = str(dimension or "").strip()
        if dim not in BUDGET_DIMENSIONS:
            dim = dim or "unknown"
        self.dimension = dim
        self.usage = dict(usage)
        self.limits = dict(limits)
        text = message or f"resolver budget exhausted: {dim}"
        super().__init__(text)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dimension": self.dimension,
            "limits": dict(self.limits),
            "message": str(self),
            "usage": dict(self.usage),
        }


# ---------------------------------------------------------------------------
# Primitive helpers
# ---------------------------------------------------------------------------


def _require_positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise OpenUsLawResolverError(f"{name} must be a positive integer")
    return value


def _require_non_negative_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OpenUsLawResolverError(f"{name} must be a non-negative integer")
    return value


def _normalize_transport_kind(value: Any) -> TransportKind:
    text = str(value or "").strip().lower().replace("-", "_")
    if text in {"dataset", "hub", "hf_dataset", "dataset_query"}:
        return "dataset"
    if text in {"bucket", "hf_bucket", "bucket_query"}:
        return "bucket"
    raise OpenUsLawResolverError(
        "transport must be 'dataset' or 'bucket', "
        f"got {value!r}"
    )


def is_mutable_pointer(value: Any) -> bool:
    """Return True when *value* names a mutable revision or bucket pointer."""

    if not isinstance(value, str) or not value.strip():
        return True
    text = value.strip().strip("/").casefold()
    if text in MUTABLE_POINTER_NAMES:
        return True
    if text.endswith("/latest") or text.endswith("/latest.json"):
        return True
    if text.startswith("refs/"):
        return True
    if "/resolve/main/" in text or "/tree/main/" in text:
        return True
    basename = PurePosixPath(text).name.casefold()
    if basename in {BUCKET_POINTER_PATH.casefold(), "latest.json", "latest"}:
        return True
    return False


def reject_mutable_pointer(value: Any, *, name: str = "pin") -> str:
    """Refuse mutable Dataset revisions and Bucket pointer aliases."""

    if not isinstance(value, str) or not value.strip():
        raise MutablePointerError(
            f"{name} must be an immutable Dataset 40-hex revision or "
            "releases/<manifest_sha256>/ prefix"
        )
    text = value.strip()
    if is_mutable_pointer(text):
        raise MutablePointerError(
            f"{name} must not be a mutable pointer ({value!r})"
        )
    return text


def require_dataset_revision(value: Any, *, name: str = "revision") -> str:
    """Require an immutable 40-hex Hub commit SHA for Dataset queries."""

    reject_mutable_pointer(value, name=name)
    try:
        return require_immutable_revision(value, name=name)
    except MutableQueryPinError as exc:
        raise MutablePointerError(str(exc)) from exc
    except PublicationGateError as exc:
        raise MutablePointerError(str(exc)) from exc


def require_bucket_release_prefix(
    value: Any, *, name: str = "bucket_prefix"
) -> tuple[str, str]:
    """Return ``(manifest_sha256, releases/<digest>/)`` for a bucket pin."""

    if value is None or (isinstance(value, str) and not value.strip()):
        raise MutablePointerError(
            f"{name} is required: bucket queries need releases/<manifest_sha256>/"
        )
    text = reject_mutable_pointer(value, name=name)
    stripped = text.strip().strip("/")
    if not stripped.startswith("releases/"):
        try:
            digest = normalize_sha256(text, name=name)
        except (DigestDriftError, ResolverError, PublicationGateError):
            digest = None
        if digest is not None:
            return digest, release_prefix_for(digest)
    try:
        digest, _suffix = parse_release_prefix_path(text, name=name)
    except PublicationGateError as exc:
        raise BucketPrefixError(
            f"{name} must be releases/<manifest_sha256>/, got {value!r}"
        ) from exc
    return digest, release_prefix_for(digest)


def authorize_query_pin(
    *,
    transport: TransportKind,
    revision: str | None = None,
    bucket_prefix: str | None = None,
    manifest_sha256: str | None = None,
    dataset_repo_id: str = DEFAULT_DATASET_REPO_ID,
    bucket_id: str = DEFAULT_BUCKET_ID,
) -> Mapping[str, Any]:
    """Evaluate the publication gate for an immutable query pin."""

    if dataset_repo_id != AUTHORIZED_DATASET_REPO_ID:
        raise UnauthorizedTargetError(
            f"dataset_repo_id must be {AUTHORIZED_DATASET_REPO_ID!r}"
        )
    if bucket_id != AUTHORIZED_BUCKET_ID:
        raise UnauthorizedTargetError(
            f"bucket_id must be {AUTHORIZED_BUCKET_ID!r}"
        )
    if transport == "dataset":
        pin = require_dataset_revision(revision, name="revision")
        request = PublicationRequest(
            phase="query",
            operation="dataset_query",
            dataset_repo_id=dataset_repo_id,
            bucket_id=bucket_id,
            query_revision=pin,
            authorize_mutation=False,
            sealed=False,
            credentials_environment_only=True,
            secret_redacted=True,
        )
    else:
        digest = (
            normalize_sha256(manifest_sha256, name="manifest_sha256")
            if manifest_sha256
            else None
        )
        prefix = bucket_prefix
        if prefix:
            parsed_digest, parsed_prefix = require_bucket_release_prefix(
                prefix, name="bucket_prefix"
            )
            if digest is not None and parsed_digest != digest:
                raise DigestDriftError(
                    "bucket prefix digest drifts from manifest_sha256"
                )
            digest = parsed_digest
            prefix = parsed_prefix
        elif digest is not None:
            prefix = release_prefix_for(digest)
        else:
            raise MutablePointerError(
                "bucket query requires releases/<manifest_sha256>/"
            )
        request = PublicationRequest(
            phase="query",
            operation="bucket_query",
            dataset_repo_id=dataset_repo_id,
            bucket_id=bucket_id,
            query_bucket_prefix=prefix,
            object_path=f"{prefix}{DEFAULT_MANIFEST_NAME}",
            final_manifest_digest=digest,
            authorize_mutation=False,
            sealed=False,
            credentials_environment_only=True,
            secret_redacted=True,
        )
    try:
        decision = require_publication_gate(request)
    except MutableQueryPinError as exc:
        raise MutablePointerError(str(exc)) from exc
    except TargetUnauthorizedError as exc:
        raise UnauthorizedTargetError(str(exc)) from exc
    except PublicationGateDeniedError as exc:
        message = str(exc)
        lowered = message.casefold()
        if "mutable" in lowered or "latest" in lowered or "40-hex" in lowered:
            raise MutablePointerError(message) from exc
        if "authorized" in lowered or "target" in lowered:
            raise UnauthorizedTargetError(message) from exc
        raise OpenUsLawResolverError(message) from exc
    payload = decision.to_dict()
    _assert_no_credential_payload(payload, surface="publication_gate_decision")
    return MappingProxyType(payload)


# ---------------------------------------------------------------------------
# Budgets
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResolverLimits:
    """Hard per-session budgets covering every acceptance dimension."""

    max_bytes: int = DEFAULT_MAX_BYTES
    max_shards: int = DEFAULT_MAX_SHARDS
    max_rows: int = DEFAULT_MAX_ROWS
    max_time_ms: int = DEFAULT_MAX_TIME_MS
    max_graph_nodes: int = DEFAULT_MAX_GRAPH_NODES
    max_graph_edges: int = DEFAULT_MAX_GRAPH_EDGES
    max_graph_depth: int = DEFAULT_MAX_GRAPH_DEPTH
    max_centroids: int = DEFAULT_MAX_CENTROIDS
    max_artifact_bytes: int = DEFAULT_MAX_ARTIFACT_BYTES
    max_rows_per_artifact: int = MAX_ROWS_PER_PHYSICAL_SHARD

    def __post_init__(self) -> None:
        object.__setattr__(self, "max_bytes", _require_positive_int(self.max_bytes, "max_bytes"))
        object.__setattr__(
            self, "max_shards", _require_positive_int(self.max_shards, "max_shards")
        )
        object.__setattr__(self, "max_rows", _require_positive_int(self.max_rows, "max_rows"))
        object.__setattr__(
            self, "max_time_ms", _require_positive_int(self.max_time_ms, "max_time_ms")
        )
        object.__setattr__(
            self,
            "max_graph_nodes",
            _require_positive_int(self.max_graph_nodes, "max_graph_nodes"),
        )
        object.__setattr__(
            self,
            "max_graph_edges",
            _require_positive_int(self.max_graph_edges, "max_graph_edges"),
        )
        object.__setattr__(
            self,
            "max_graph_depth",
            _require_non_negative_int(self.max_graph_depth, "max_graph_depth"),
        )
        object.__setattr__(
            self,
            "max_centroids",
            _require_positive_int(self.max_centroids, "max_centroids"),
        )
        object.__setattr__(
            self,
            "max_artifact_bytes",
            _require_positive_int(self.max_artifact_bytes, "max_artifact_bytes"),
        )
        object.__setattr__(
            self,
            "max_rows_per_artifact",
            _require_positive_int(self.max_rows_per_artifact, "max_rows_per_artifact"),
        )

    def to_dict(self) -> dict[str, int]:
        return {
            "max_artifact_bytes": self.max_artifact_bytes,
            "max_bytes": self.max_bytes,
            "max_centroids": self.max_centroids,
            "max_graph_depth": self.max_graph_depth,
            "max_graph_edges": self.max_graph_edges,
            "max_graph_nodes": self.max_graph_nodes,
            "max_rows": self.max_rows,
            "max_rows_per_artifact": self.max_rows_per_artifact,
            "max_shards": self.max_shards,
            "max_time_ms": self.max_time_ms,
        }

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None = None) -> "ResolverLimits":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise OpenUsLawResolverError("limits must be a mapping")
        known = {
            "max_bytes",
            "max_shards",
            "max_rows",
            "max_time_ms",
            "max_graph_nodes",
            "max_graph_edges",
            "max_graph_depth",
            "max_centroids",
            "max_artifact_bytes",
            "max_rows_per_artifact",
        }
        kwargs = {
            key: int(value[key])
            for key in known
            if key in value and value[key] is not None
        }
        if "time_ms" in value and "max_time_ms" not in kwargs:
            kwargs["max_time_ms"] = int(value["time_ms"])
        if "timeout_ms" in value and "max_time_ms" not in kwargs:
            kwargs["max_time_ms"] = int(value["timeout_ms"])
        return cls(**kwargs)


@dataclass
class ResolverBudgetUsage:
    """Mutable consumption counters for one resolver session."""

    bytes: int = 0
    shards: int = 0
    rows: int = 0
    graph_nodes: int = 0
    graph_edges: int = 0
    graph_depth: int = 0
    centroids: int = 0
    time_ms: float = 0.0
    clock: Callable[[], float] = field(default=time.perf_counter, repr=False)
    started_at: float = field(default=0.0)

    def __post_init__(self) -> None:
        if not self.started_at:
            self.started_at = float(self.clock())

    def elapsed_ms(self) -> float:
        return (float(self.clock()) - self.started_at) * 1000.0

    def snapshot(self) -> dict[str, Any]:
        return {
            "bytes": self.bytes,
            "centroids": self.centroids,
            "graph_depth": self.graph_depth,
            "graph_edges": self.graph_edges,
            "graph_nodes": self.graph_nodes,
            "rows": self.rows,
            "shards": self.shards,
            "time_ms": round(max(self.time_ms, self.elapsed_ms()), 3),
        }

    def check(
        self,
        limits: ResolverLimits,
        *,
        extra_bytes: int = 0,
        extra_shards: int = 0,
        extra_rows: int = 0,
        extra_graph_nodes: int = 0,
        extra_graph_edges: int = 0,
        extra_centroids: int = 0,
        projected_depth: int | None = None,
        raise_on_exhaustion: bool = True,
    ) -> str | None:
        """Return the exhausted dimension or raise :class:`ResolverBudgetExhausted`."""

        self.time_ms = self.elapsed_ms()
        graph_nodes = self.graph_nodes + extra_graph_nodes
        graph_edges = self.graph_edges + extra_graph_edges
        graph_depth = (
            projected_depth if projected_depth is not None else self.graph_depth
        )
        checks: list[tuple[str, float | int, float | int]] = [
            ("bytes", self.bytes + extra_bytes, limits.max_bytes),
            ("shards", self.shards + extra_shards, limits.max_shards),
            ("rows", self.rows + extra_rows, limits.max_rows),
            ("time", self.time_ms, limits.max_time_ms),
            ("centroids", self.centroids + extra_centroids, limits.max_centroids),
        ]
        for dimension, used, limit in checks:
            if used > limit:
                if raise_on_exhaustion:
                    raise ResolverBudgetExhausted(
                        dimension,
                        usage=self.snapshot(),
                        limits=limits.to_dict(),
                    )
                return dimension
        if (
            graph_nodes > limits.max_graph_nodes
            or graph_edges > limits.max_graph_edges
            or graph_depth > limits.max_graph_depth
        ):
            if raise_on_exhaustion:
                raise ResolverBudgetExhausted(
                    "graph",
                    usage=self.snapshot(),
                    limits=limits.to_dict(),
                )
            return "graph"
        return None

    def charge(
        self,
        *,
        bytes_: int = 0,
        shards: int = 0,
        rows: int = 0,
        graph_nodes: int = 0,
        graph_edges: int = 0,
        graph_depth: int | None = None,
        centroids: int = 0,
    ) -> None:
        self.bytes += max(0, int(bytes_))
        self.shards += max(0, int(shards))
        self.rows += max(0, int(rows))
        self.graph_nodes += max(0, int(graph_nodes))
        self.graph_edges += max(0, int(graph_edges))
        self.centroids += max(0, int(centroids))
        if graph_depth is not None:
            self.graph_depth = max(self.graph_depth, int(graph_depth))
        self.time_ms = self.elapsed_ms()


# ---------------------------------------------------------------------------
# Route justification
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
        _reject_mutable_or_raw_path(path, name="route.relative_path")
        keys = tuple(str(item) for item in self.keys if str(item))
        score = self.score
        if score is not None:
            if isinstance(score, bool) or not isinstance(score, (int, float)):
                raise OpenUsLawResolverError("route score must be numeric")
            score = float(score)
            if score != score or score in {float("inf"), float("-inf")}:
                raise OpenUsLawResolverError("route score must be finite")
        if not isinstance(self.metadata, Mapping):
            raise OpenUsLawResolverError("route metadata must be a mapping")
        _assert_no_credential_payload(self.metadata, surface="route.metadata")
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

    @classmethod
    def from_mapping(
        cls, value: "RouteJustification | Mapping[str, Any]", *, relative_path: str
    ) -> "RouteJustification":
        if isinstance(value, RouteJustification):
            return value
        if not isinstance(value, Mapping):
            raise UnjustifiedFetchError("route justification must be a mapping")
        return cls(
            family=str(value.get("family") or ""),
            reason=str(value.get("reason") or ""),
            relative_path=str(value.get("relative_path") or relative_path),
            keys=tuple(value.get("keys") or ()),
            score=value.get("score"),
            metadata=value.get("metadata") or {},
        )


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
    remote_path: str = ""

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
        if self.remote_path:
            payload["remote_path"] = self.remote_path
        return payload


def _reject_mutable_or_raw_path(path: str, *, name: str) -> None:
    if is_mutable_pointer(path):
        raise MutablePointerError(
            f"{name} must not address a mutable pointer ({path!r})"
        )
    text = path.strip().lstrip("/")
    # Only bare bucket-root objects are forbidden. Release-relative
    # ``data/**/*.parquet`` paths are the legitimate query surface.
    if "/" not in text.rstrip("/") and text.casefold().endswith(".parquet"):
        raise UnsafePathError(
            f"{name} must not address a protected raw bucket-root object: {path!r}"
        )
    if text.casefold() in {"sha256sums.json", "sha256sums"}:
        raise UnsafePathError(
            f"{name} must not address a protected raw bucket-root object: {path!r}"
        )


# ---------------------------------------------------------------------------
# Transport adapters
# ---------------------------------------------------------------------------


@runtime_checkable
class ArtifactTransport(Protocol):
    """Materialize one pinned artifact to a caller-owned destination path."""

    def fetch(
        self,
        *,
        repo_id: str,
        revision: str,
        relative_path: str,
        destination: Path,
        token: str | None = None,
    ) -> Path:
        """Write bytes to *destination* (regular file) and return it."""


class PrefixConfinedTransport:
    """Confine fetches to ``releases/<manifest_sha256>/`` (no raw-root fallback)."""

    def __init__(self, inner: ArtifactTransport, *, prefix: str) -> None:
        digest, normalized = require_bucket_release_prefix(prefix, name="path_prefix")
        self.inner = inner
        self.manifest_sha256 = digest
        self.prefix = normalized

    def fetch(
        self,
        *,
        repo_id: str,
        revision: str,
        relative_path: str,
        destination: Path,
        token: str | None = None,
    ) -> Path:
        remote = self.remote_path(relative_path)
        return self.inner.fetch(
            repo_id=repo_id,
            revision=revision,
            relative_path=remote,
            destination=destination,
            token=token,
        )

    def remote_path(self, relative_path: str) -> str:
        safe = safe_relative_path(relative_path).as_posix()
        _reject_mutable_or_raw_path(safe, name="relative_path")
        if safe.startswith("releases/"):
            try:
                digest, suffix = parse_release_prefix_path(safe, name="relative_path")
            except PublicationGateError as exc:
                raise BucketPrefixError(
                    "artifact path is outside the pinned releases/<manifest_sha256>/ prefix"
                ) from exc
            if digest != self.manifest_sha256:
                raise BucketPrefixError(
                    "artifact path is outside the pinned releases/<manifest_sha256>/ prefix"
                )
            if not suffix:
                raise UnsafePathError(
                    "bucket fetch must name a file under the release prefix"
                )
            safe = suffix
        remote = f"{self.prefix}{safe}"
        remote_path = PurePosixPath(remote)
        if ".." in remote_path.parts or not remote.startswith(self.prefix):
            raise UnsafePathError(
                "bucket fetch escaped the pinned releases/<manifest_sha256>/ prefix"
            )
        return remote


class BucketObjectTransport:
    """Adapt :class:`HuggingFaceBucketTransport.range_read` to artifact fetch."""

    def __init__(self, bucket_transport: Any, *, bucket_id: str) -> None:
        if bucket_transport is None:
            raise OpenUsLawResolverError("bucket transport must be injected")
        self.inner = bucket_transport
        self.bucket_id = validate_repo_id(bucket_id, name="bucket_id")

    def fetch(
        self,
        *,
        repo_id: str,
        revision: str,
        relative_path: str,
        destination: Path,
        token: str | None = None,
    ) -> Path:
        del repo_id, revision, token
        safe = safe_relative_path(relative_path).as_posix()
        _reject_mutable_or_raw_path(safe, name="relative_path")
        uri = f"hf://buckets/{self.bucket_id}/{safe}"
        try:
            listed_size = _bucket_object_size(self.inner, safe)
            end = listed_size if listed_size is not None else getattr(
                getattr(self.inner, "budgets", None), "max_object_bytes", DEFAULT_MAX_ARTIFACT_BYTES
            )
            result = self.inner.range_read(uri, start=0, end=int(end), destination=destination)
        except OpenUsLawResolverError:
            raise
        except Exception:
            raise TransportError(f"failed to fetch pinned bucket artifact: {safe}") from None
        payload = getattr(result, "data", None)
        if payload is not None and not destination.exists():
            try:
                destination.write_bytes(bytes(payload))
            except OSError as exc:
                raise TransportError(f"failed to stage bucket artifact: {safe}") from exc
        return destination


def _bucket_object_size(transport: Any, relative_path: str) -> int | None:
    listing = getattr(transport, "expected_listing", None)
    if listing is None:
        return None
    objects = getattr(listing, "objects", ())
    for item in objects:
        if getattr(item, "path", None) == relative_path:
            size = getattr(item, "size_bytes", None)
            if isinstance(size, int) and not isinstance(size, bool) and size >= 0:
                return size
    return None


def prefix_bucket_files(
    manifest_sha256: str, files: Mapping[str, bytes]
) -> dict[str, bytes]:
    """Rewrite release-relative fixture keys under ``releases/<digest>/``."""

    digest = normalize_sha256(manifest_sha256, name="manifest_sha256")
    prefix = release_prefix_for(digest)
    prefixed: dict[str, bytes] = {}
    for key, value in files.items():
        safe = safe_relative_path(key).as_posix()
        if safe.startswith("releases/"):
            parsed, _suffix = require_bucket_release_prefix(safe, name="relative_path")
            if parsed != digest:
                raise BucketPrefixError(
                    "fixture path is outside the pinned releases/<manifest_sha256>/ prefix"
                )
            prefixed[safe] = value
        else:
            prefixed[f"{prefix}{safe}"] = value
    return prefixed


# ---------------------------------------------------------------------------
# Content-addressed cache (dataset 40-hex or bucket 64-hex identity)
# ---------------------------------------------------------------------------


class ReleaseScopedCache:
    """Content-addressed cache scoped by immutable Dataset or Bucket identity."""

    def __init__(self, root: str | Path) -> None:
        root_path = Path(root).expanduser()
        try:
            root_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise OpenUsLawResolverError("cache root must be creatable") from exc
        if root_path.is_symlink() or not root_path.is_dir():
            raise OpenUsLawResolverError("cache root must be a real directory")
        self.root = root_path.resolve()
        self._ensure_directory(self.root / "objects")
        self._ensure_directory(self.root / "aliases")
        self._ensure_directory(self.root / "locks")

    def object_path(self, sha256: str) -> Path:
        digest = normalize_sha256(sha256)
        return self.root / "objects" / "sha256" / digest[:2] / digest

    def alias_path(self, *, identity: str, relative_path: str) -> Path:
        rel = safe_relative_path(relative_path).as_posix()
        identity_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        path_key = hashlib.sha256(rel.encode("utf-8")).hexdigest()
        return self.root / "aliases" / identity_key[:16] / identity_key[16:32] / f"{path_key}.json"

    def lookup(
        self,
        *,
        identity: str,
        relative_path: str,
        expected_sha256: str | None = None,
    ) -> Path | None:
        alias = self.alias_path(identity=identity, relative_path=relative_path)
        if alias.is_symlink():
            raise SymlinkRejectedError("cache alias must not be a symlink")
        if not alias.is_file():
            return None
        try:
            payload = json.loads(alias.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CacheCollisionError("cache alias is unreadable") from exc
        if not isinstance(payload, Mapping):
            raise CacheCollisionError("cache alias is malformed")
        if payload.get("schema_version") != CACHE_ALIAS_SCHEMA_VERSION:
            raise CacheCollisionError("cache alias schema is unsupported")
        stored_identity = str(payload.get("identity") or "")
        stored_path = str(payload.get("relative_path") or "")
        stored_digest = str(payload.get("sha256") or "")
        if stored_identity != identity or stored_path != safe_relative_path(relative_path).as_posix():
            raise CacheCollisionError("cache alias identity drifted")
        digest = normalize_sha256(stored_digest)
        if expected_sha256 is not None and digest != normalize_sha256(expected_sha256):
            raise CacheCollisionError("cache alias digest disagrees with descriptor")
        target = self.object_path(digest)
        if target.is_symlink():
            raise SymlinkRejectedError("cache object must not be a symlink")
        if not target.is_file():
            return None
        actual, size = file_sha256_and_size(target)
        if actual != digest:
            raise DigestDriftError("cached object digest drifted")
        expected_size = payload.get("size_bytes")
        if expected_size is not None and int(expected_size) != size:
            raise DigestDriftError("cached object size drifted")
        return target

    def store(
        self,
        *,
        identity: str,
        relative_path: str,
        source: Path,
        sha256: str,
        size_bytes: int,
        move: bool = True,
    ) -> Path:
        digest = normalize_sha256(sha256)
        rel = safe_relative_path(relative_path).as_posix()
        target = self.object_path(digest)
        self._ensure_directory(target.parent)
        if target.exists():
            if target.is_symlink():
                raise SymlinkRejectedError("cache object must not be a symlink")
            existing, existing_size = file_sha256_and_size(target)
            if existing != digest or existing_size != size_bytes:
                raise CacheCollisionError("content-addressed cache collision")
        else:
            self._promote(source, target, move=move)
            stored, stored_size = file_sha256_and_size(target)
            if stored != digest or stored_size != size_bytes:
                try:
                    target.unlink()
                except OSError:
                    pass
                raise DigestDriftError("promoted cache object drifted")
        alias = self.alias_path(identity=identity, relative_path=rel)
        self._ensure_directory(alias.parent)
        record = {
            "identity": identity,
            "relative_path": rel,
            "schema_version": CACHE_ALIAS_SCHEMA_VERSION,
            "sha256": digest,
            "size_bytes": size_bytes,
        }
        if alias.exists():
            if alias.is_symlink():
                raise SymlinkRejectedError("cache alias must not be a symlink")
            try:
                existing_payload = json.loads(alias.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise CacheCollisionError("cache alias is unreadable") from exc
            if (
                not isinstance(existing_payload, Mapping)
                or existing_payload.get("sha256") != digest
                or existing_payload.get("identity") != identity
                or existing_payload.get("relative_path") != rel
            ):
                raise CacheCollisionError("cache alias collision")
            return target
        fd, temporary_name = tempfile.mkstemp(
            prefix=".alias.", suffix=".partial", dir=self.root / "locks"
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            temporary.write_text(
                json.dumps(record, sort_keys=True, separators=(",", ":")),
                encoding="utf-8",
            )
            os.replace(temporary, alias)
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)
        return target

    def _promote(self, source: Path, destination: Path, *, move: bool = True) -> None:
        if source.is_symlink() or destination.is_symlink():
            raise SymlinkRejectedError("cache promotion rejects symlinks")
        if move:
            try:
                os.replace(source, destination)
                return
            except OSError:
                pass
        try:
            destination.write_bytes(source.read_bytes())
        except OSError as exc:
            raise OpenUsLawResolverError("cannot promote cache object") from exc

    def _ensure_directory(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise OpenUsLawResolverError("cannot create cache directory") from exc
        if path.is_symlink():
            raise SymlinkRejectedError("cache directory must not be a symlink")


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


@dataclass
class OpenUsLawResolver:
    """Fail-closed Dataset (40-hex) and Bucket (``releases/<sha256>/``) resolver."""

    transport: TransportKind
    revision: str | None = None
    bucket_prefix: str | None = None
    manifest_sha256: str | None = None
    dataset_repo_id: str = DEFAULT_DATASET_REPO_ID
    bucket_id: str = DEFAULT_BUCKET_ID
    cache_dir: Path | str | None = None
    artifact_transport: ArtifactTransport | None = None
    local_root: Path | str | None = None
    token: str | None = field(default=None, repr=False)
    limits: ResolverLimits | Mapping[str, Any] | None = None
    supported_schemas: frozenset[str] | set[str] | Sequence[str] = field(
        default_factory=lambda: set(DEFAULT_SUPPORTED_RELEASE_SCHEMAS)
    )
    require_descriptors: bool = True
    clock: Callable[[], float] = field(default=time.perf_counter, repr=False)

    def __post_init__(self) -> None:
        kind = _normalize_transport_kind(self.transport)
        object.__setattr__(self, "transport", kind)
        object.__setattr__(
            self,
            "dataset_repo_id",
            validate_repo_id(self.dataset_repo_id, name="dataset_repo_id"),
        )
        object.__setattr__(
            self, "bucket_id", validate_repo_id(self.bucket_id, name="bucket_id")
        )
        if self.dataset_repo_id != AUTHORIZED_DATASET_REPO_ID:
            raise UnauthorizedTargetError(
                f"dataset_repo_id must be {AUTHORIZED_DATASET_REPO_ID!r}"
            )
        if self.bucket_id != AUTHORIZED_BUCKET_ID:
            raise UnauthorizedTargetError(
                f"bucket_id must be {AUTHORIZED_BUCKET_ID!r}"
            )

        limits = (
            self.limits
            if isinstance(self.limits, ResolverLimits)
            else ResolverLimits.from_mapping(self.limits)
        )
        object.__setattr__(self, "limits", limits)

        schemas = frozenset(
            str(item).strip() for item in self.supported_schemas if str(item).strip()
        )
        if not schemas:
            raise SchemaMismatchError("supported_schemas must not be empty")
        object.__setattr__(self, "supported_schemas", schemas)

        pin_revision: str | None = None
        pin_prefix: str | None = None
        pin_digest: str | None = None
        if kind == "dataset":
            if self.bucket_prefix:
                raise MutablePointerError(
                    "dataset queries require a 40-hex revision, not a bucket prefix"
                )
            pin_revision = require_dataset_revision(self.revision, name="revision")
            try:
                pin_revision = validate_immutable_revision(pin_revision, name="revision")
            except MutableRevisionError as exc:
                raise MutablePointerError(str(exc)) from exc
        else:
            if self.revision and not self.bucket_prefix and not self.manifest_sha256:
                # A 40-hex Dataset SHA is not a Bucket identity.
                raise MutablePointerError(
                    "bucket queries require releases/<manifest_sha256>/, "
                    "not a Dataset revision"
                )
            if self.revision:
                reject_mutable_pointer(self.revision, name="revision")
            pin_digest, pin_prefix = require_bucket_release_prefix(
                self.bucket_prefix or self.manifest_sha256,
                name="bucket_prefix",
            )
            if self.manifest_sha256:
                declared = normalize_sha256(self.manifest_sha256, name="manifest_sha256")
                if declared != pin_digest:
                    raise DigestDriftError(
                        "bucket prefix digest drifts from manifest_sha256"
                    )

        gate = authorize_query_pin(
            transport=kind,
            revision=pin_revision,
            bucket_prefix=pin_prefix,
            manifest_sha256=pin_digest,
            dataset_repo_id=self.dataset_repo_id,
            bucket_id=self.bucket_id,
        )
        object.__setattr__(self, "revision", pin_revision)
        object.__setattr__(self, "bucket_prefix", pin_prefix)
        object.__setattr__(self, "manifest_sha256", pin_digest)
        object.__setattr__(self, "_gate", gate)

        cache_root = Path(self.cache_dir or DEFAULT_CACHE_DIR).expanduser()
        object.__setattr__(self, "cache_dir", cache_root)
        object.__setattr__(self, "_cache", ReleaseScopedCache(cache_root))

        local: Path | None
        if self.local_root is not None:
            local = Path(self.local_root).expanduser().resolve()
            if local.is_symlink() or not local.is_dir():
                raise OpenUsLawResolverError("local_root must be a real directory")
        else:
            local = None
        object.__setattr__(self, "local_root", local)

        artifact_transport = self._coerce_transport(self.artifact_transport, local=local)
        object.__setattr__(self, "artifact_transport", artifact_transport)

        hub: ImmutableHubResolver | None = None
        if kind == "dataset":
            hub = ImmutableHubResolver(
                repo_id=self.dataset_repo_id,
                revision=pin_revision or "",
                cache_dir=cache_root / "dataset",
                transport=artifact_transport,
                token=self.token,
                max_artifact_bytes=limits.max_artifact_bytes,
                max_rows_per_artifact=limits.max_rows_per_artifact,
                supported_schemas=schemas,
                require_descriptor=False,
            )
        object.__setattr__(self, "_hub", hub)
        object.__setattr__(self, "_token", self.token)
        object.__setattr__(self, "token", None)
        object.__setattr__(self, "_justified", [])
        object.__setattr__(self, "_descriptors", {})
        object.__setattr__(self, "_manifest", None)
        object.__setattr__(self, "_manifest_schema", None)
        object.__setattr__(self, "_stop_reason", None)
        object.__setattr__(
            self, "usage", ResolverBudgetUsage(clock=self.clock)
        )

    @classmethod
    def for_dataset(
        cls,
        revision: str,
        *,
        artifact_transport: ArtifactTransport | None = None,
        cache_dir: Path | str | None = None,
        local_root: Path | str | None = None,
        token: str | None = None,
        limits: ResolverLimits | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> "OpenUsLawResolver":
        return cls(
            transport="dataset",
            revision=revision,
            artifact_transport=artifact_transport,
            cache_dir=cache_dir,
            local_root=local_root,
            token=token,
            limits=limits,
            **kwargs,
        )

    @classmethod
    def for_bucket(
        cls,
        manifest_sha256: str | None = None,
        *,
        bucket_prefix: str | None = None,
        artifact_transport: ArtifactTransport | None = None,
        cache_dir: Path | str | None = None,
        local_root: Path | str | None = None,
        token: str | None = None,
        limits: ResolverLimits | Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> "OpenUsLawResolver":
        return cls(
            transport="bucket",
            manifest_sha256=manifest_sha256,
            bucket_prefix=bucket_prefix or (
                release_prefix_for(manifest_sha256) if manifest_sha256 else None
            ),
            artifact_transport=artifact_transport,
            cache_dir=cache_dir,
            local_root=local_root,
            token=token,
            limits=limits,
            **kwargs,
        )

    # -- public API ---------------------------------------------------------

    @property
    def identity(self) -> str:
        if self.transport == "dataset":
            return f"dataset:{self.dataset_repo_id}:{self.revision}"
        return f"bucket:{self.bucket_id}:{self.manifest_sha256}"

    @property
    def hub_resolver(self) -> ImmutableHubResolver | None:
        return self._hub

    def reset_session(
        self,
        *,
        limits: ResolverLimits | Mapping[str, Any] | None = None,
        keep_manifest: bool = True,
    ) -> None:
        if limits is not None:
            object.__setattr__(
                self,
                "limits",
                limits if isinstance(limits, ResolverLimits) else ResolverLimits.from_mapping(limits),
            )
        object.__setattr__(self, "usage", ResolverBudgetUsage(clock=self.clock))
        self._justified.clear()
        object.__setattr__(self, "_stop_reason", None)
        if not keep_manifest:
            object.__setattr__(self, "_manifest", None)
            object.__setattr__(self, "_manifest_schema", None)
            self._descriptors.clear()

    def resolve(
        self,
        relative_path: str,
        *,
        route: RouteJustification | Mapping[str, Any],
        descriptor: ArtifactDescriptor | Mapping[str, Any] | None = None,
        charge_shard: bool | None = None,
        charge_rows: int | None = None,
    ) -> ResolvedArtifact:
        """Fetch one artifact only when route-justified and budget-safe."""

        started = time.perf_counter()
        rel = self._release_relative_path(relative_path)
        justification = RouteJustification.from_mapping(route, relative_path=rel)
        if justification.relative_path != rel:
            raise UnjustifiedFetchError(
                f"route path {justification.relative_path!r} does not match "
                f"fetch path {rel!r}"
            )

        desc = self._resolve_descriptor(rel, descriptor, justification)
        extras = self._projected_charges(
            justification, desc, charge_shard=charge_shard, charge_rows=charge_rows
        )
        try:
            self.usage.check(self.limits, **extras)
        except ResolverBudgetExhausted as exc:
            object.__setattr__(self, "_stop_reason", exc.dimension)
            raise

        artifact = self._materialize(rel, desc)
        rows = (
            charge_rows
            if charge_rows is not None
            else (artifact.row_count if artifact.row_count is not None else 0)
        )
        shard = extras["extra_shards"]
        self.usage.charge(
            bytes_=artifact.size_bytes,
            shards=shard,
            rows=int(rows or 0),
            graph_nodes=extras["extra_graph_nodes"],
            graph_edges=extras["extra_graph_edges"],
            graph_depth=justification.metadata.get("depth"),
            centroids=extras["extra_centroids"],
        )
        duration_ms = (time.perf_counter() - started) * 1000.0
        record = JustifiedFetchRecord(
            relative_path=artifact.relative_path,
            sha256=artifact.sha256,
            size_bytes=artifact.size_bytes,
            verified=artifact.verified,
            cache_hit=artifact.cache_hit,
            route=justification,
            row_count=artifact.row_count,
            duration_ms=duration_ms or artifact.duration_ms,
            schema_id=artifact.schema_id,
            remote_path=self._remote_path(rel),
        )
        self._justified.append(record)
        return artifact

    def resolve_bytes(
        self,
        relative_path: str,
        *,
        route: RouteJustification | Mapping[str, Any],
        descriptor: ArtifactDescriptor | Mapping[str, Any] | None = None,
    ) -> bytes:
        artifact = self.resolve(relative_path, route=route, descriptor=descriptor)
        try:
            return artifact.path.read_bytes()
        except OSError as exc:
            raise OpenUsLawResolverError(
                f"cannot read verified artifact: {artifact.relative_path}"
            ) from exc

    def resolve_json(
        self,
        relative_path: str,
        *,
        route: RouteJustification | Mapping[str, Any],
        descriptor: ArtifactDescriptor | Mapping[str, Any] | None = None,
        expect_object: bool = True,
    ) -> Any:
        raw = self.resolve_bytes(relative_path, route=route, descriptor=descriptor)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SchemaMismatchError(
                f"JSON artifact is malformed: {relative_path}"
            ) from exc
        if expect_object and not isinstance(value, Mapping):
            raise SchemaMismatchError(
                f"JSON artifact must be an object: {relative_path}"
            )
        return value

    def load_manifest(
        self,
        relative_path: str = DEFAULT_MANIFEST_NAME,
        *,
        descriptor: ArtifactDescriptor | Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Load, schema-check, and index verified release descriptors."""

        route = RouteJustification(
            family="control_plane",
            reason="manifest",
            relative_path=self._release_relative_path(relative_path),
        )
        raw = self.resolve_bytes(relative_path, route=route, descriptor=descriptor)
        try:
            manifest = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SchemaMismatchError("manifest is malformed JSON") from exc
        if not isinstance(manifest, Mapping):
            raise SchemaMismatchError("manifest must be a JSON object")
        payload = dict(manifest)
        schema_version = (
            payload.get("schema_version")
            or payload.get("release_profile")
            or payload.get("hf_release_schema_version")
        )
        if not isinstance(schema_version, str) or not schema_version.strip():
            raise SchemaMismatchError("manifest is missing schema_version")
        schema_version = schema_version.strip()
        profile = payload.get("release_profile")
        accepted = {schema_version}
        if isinstance(profile, str) and profile.strip():
            accepted.add(profile.strip())
        if accepted.isdisjoint(self.supported_schemas):
            raise SchemaMismatchError(
                f"unsupported release schema_version: {schema_version!r}"
            )
        if self.transport == "bucket":
            self._verify_bucket_manifest_digest(payload, raw)
        primary_key = payload.get("primary_key")
        if primary_key is not None and primary_key != "entry_cid":
            raise SchemaMismatchError(
                "manifest primary_key must be 'entry_cid' when provided"
            )
        self._index_descriptors(payload)
        object.__setattr__(self, "_manifest", payload)
        object.__setattr__(self, "_manifest_schema", schema_version)
        return dict(payload)

    def descriptor_for(self, relative_path: str) -> ArtifactDescriptor | None:
        rel = self._release_relative_path(relative_path)
        return self._descriptors.get(rel)

    def fetch_trace(self) -> dict[str, Any]:
        """Return a credential-safe, path-safe justified fetch trace."""

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
            item
            for item in files
            if not item.get("route") or not item.get("verified")
        ]
        gate = dict(self._gate)
        trace: dict[str, Any] = {
            "budget_usage": self.usage.snapshot(),
            "bucket_id": self.bucket_id,
            "bucket_prefix": self.bucket_prefix,
            "cache_hits": cache_hits,
            "dataset_repo_id": self.dataset_repo_id,
            "file_count": len(files),
            "files": files,
            "goal_id": GOAL_ID,
            "limits": self.limits.to_dict(),
            "manifest_sha256": self.manifest_sha256,
            "network_mutation_permitted": False,
            "producer": PRODUCER,
            "program_id": PROGRAM_ID,
            "publication_gate": {
                "authorized": bool(gate.get("authorized")),
                "network_mutation_permitted": bool(
                    gate.get("network_mutation_permitted")
                ),
                "operation": gate.get("operation"),
                "phase": gate.get("phase"),
            },
            "repo_id": (
                self.dataset_repo_id if self.transport == "dataset" else self.bucket_id
            ),
            "resolver_schema_version": RESOLVER_SCHEMA_VERSION,
            "revision": self.revision,
            "route_justified": len(unjustified) == 0,
            "schema_version": FETCH_TRACE_SCHEMA_VERSION,
            "stop_reason": self._stop_reason,
            "task_id": TASK_ID,
            "total_file_bytes": total_bytes,
            "transport": self.transport,
            "verification_state": (
                "verified"
                if files and not unjustified
                else ("empty" if not files else "unverified")
            ),
        }
        if self._manifest_schema is not None:
            trace["manifest_schema_version"] = self._manifest_schema
        _assert_no_credential_payload(trace, surface="fetch_trace")
        rendered = json.dumps(trace, sort_keys=True)
        if _TOKEN_LIKE_RE.search(rendered):
            raise CredentialLeakageError("fetch_trace would leak credentials")
        if self._token and self._token in rendered:
            raise CredentialLeakageError("fetch_trace would leak credentials")
        cache_root = str(self.cache_dir)
        if cache_root and cache_root in rendered:
            raise CredentialLeakageError("fetch_trace would leak local cache paths")
        return trace

    def trace(self) -> dict[str, Any]:
        return self.fetch_trace()

    def __repr__(self) -> str:
        if self.transport == "dataset":
            return (
                f"OpenUsLawResolver(transport='dataset', "
                f"repo_id={self.dataset_repo_id!r}, revision={self.revision!r})"
            )
        return (
            f"OpenUsLawResolver(transport='bucket', "
            f"bucket_id={self.bucket_id!r}, prefix={self.bucket_prefix!r})"
        )

    # -- internals ----------------------------------------------------------

    def _coerce_transport(
        self,
        transport: ArtifactTransport | None,
        *,
        local: Path | None,
    ) -> ArtifactTransport:
        if transport is None:
            if local is not None:
                transport = LocalRootTransport(local)
            elif self.transport == "dataset":
                transport = HuggingFaceHubTransport()
            else:
                raise OpenUsLawResolverError(
                    "bucket queries require an injected artifact transport; "
                    "refusing an implicit fetch from a mutable Bucket root"
                )
        if self.transport == "bucket":
            module_name = type(transport).__module__
            type_name = type(transport).__name__
            if type_name == "HuggingFaceBucketTransport" or module_name.endswith(
                "hf_bucket_transport"
            ) and hasattr(transport, "range_read"):
                transport = BucketObjectTransport(
                    transport, bucket_id=self.bucket_id
                )
            if not isinstance(transport, PrefixConfinedTransport):
                transport = PrefixConfinedTransport(
                    transport, prefix=self.bucket_prefix or ""
                )
        return transport

    def _release_relative_path(self, relative_path: str) -> str:
        text = reject_mutable_pointer(relative_path, name="relative_path")
        if self.transport == "bucket" and text.startswith("releases/"):
            try:
                digest, suffix = parse_release_prefix_path(text, name="relative_path")
            except PublicationGateError as exc:
                raise BucketPrefixError(
                    "artifact path is outside the pinned releases/<manifest_sha256>/ prefix"
                ) from exc
            if digest != self.manifest_sha256:
                raise BucketPrefixError(
                    "artifact path is outside the pinned releases/<manifest_sha256>/ prefix"
                )
            if not suffix:
                raise UnsafePathError(
                    "bucket fetch must name a file under the release prefix"
                )
            text = suffix
        safe = safe_relative_path(text).as_posix()
        _reject_mutable_or_raw_path(safe, name="relative_path")
        return safe

    def _remote_path(self, relative_path: str) -> str:
        if self.transport == "bucket":
            assert isinstance(self.artifact_transport, PrefixConfinedTransport)
            return self.artifact_transport.remote_path(relative_path)
        return relative_path

    def _resolve_descriptor(
        self,
        relative_path: str,
        descriptor: ArtifactDescriptor | Mapping[str, Any] | None,
        justification: RouteJustification,
    ) -> ArtifactDescriptor | None:
        provided: ArtifactDescriptor | None = None
        if descriptor is not None:
            provided = (
                descriptor
                if isinstance(descriptor, ArtifactDescriptor)
                else ArtifactDescriptor.from_mapping(descriptor)
            )
            if provided.relative_path != relative_path:
                raise UnsafePathError(
                    f"descriptor path {provided.relative_path!r} does not match "
                    f"{relative_path!r}"
                )
            self._enforce_descriptor_bounds(provided)
        indexed = self._descriptors.get(relative_path)
        if provided is not None and indexed is not None:
            if (
                provided.sha256 != indexed.sha256
                or provided.size_bytes != indexed.size_bytes
            ):
                raise DigestDriftError(
                    f"descriptor drifted from verified inventory: {relative_path}"
                )
        chosen = provided or indexed
        is_control = justification.family in CONTROL_PLANE_FAMILIES
        if self.require_descriptors and chosen is None and not is_control:
            raise DescriptorRequiredError(
                f"descriptor required for data-plane fetch: {relative_path}"
            )
        if self.transport == "bucket" and not is_control and chosen is None:
            raise DescriptorRequiredError(
                f"bucket queries require a verified descriptor: {relative_path}"
            )
        return chosen

    def _enforce_descriptor_bounds(self, descriptor: ArtifactDescriptor) -> None:
        if descriptor.size_bytes > self.limits.max_artifact_bytes:
            raise OversizedArtifactError(
                f"descriptor size_bytes {descriptor.size_bytes} exceeds "
                f"max_artifact_bytes {self.limits.max_artifact_bytes}"
            )
        if (
            descriptor.row_count is not None
            and descriptor.row_count > self.limits.max_rows_per_artifact
        ):
            raise OversizedArtifactError(
                f"descriptor row_count {descriptor.row_count} exceeds "
                f"max_rows_per_artifact {self.limits.max_rows_per_artifact}"
            )

    def _projected_charges(
        self,
        justification: RouteJustification,
        descriptor: ArtifactDescriptor | None,
        *,
        charge_shard: bool | None,
        charge_rows: int | None,
    ) -> dict[str, int]:
        is_control = justification.family in CONTROL_PLANE_FAMILIES
        shard = (
            0
            if charge_shard is False or (charge_shard is None and is_control)
            else 1
        )
        rows = 0
        if charge_rows is not None:
            rows = int(charge_rows)
        elif descriptor is not None and descriptor.row_count is not None:
            rows = int(descriptor.row_count)
        extra_nodes = rows if justification.family in GRAPH_NODE_FAMILIES else 0
        extra_edges = rows if justification.family in GRAPH_EDGE_FAMILIES else 0
        extra_centroids = (
            1
            if (
                justification.family in CENTROID_FAMILIES
                or justification.reason in CENTROID_REASONS
            )
            else 0
        )
        depth = justification.metadata.get("depth")
        projected_depth = int(depth) if depth is not None else None
        extra_bytes = int(descriptor.size_bytes) if descriptor is not None else 0
        return {
            "extra_bytes": extra_bytes,
            "extra_shards": shard,
            "extra_rows": rows,
            "extra_graph_nodes": extra_nodes,
            "extra_graph_edges": extra_edges,
            "extra_centroids": extra_centroids,
            "projected_depth": projected_depth,
        }

    def _materialize(
        self,
        relative_path: str,
        descriptor: ArtifactDescriptor | None,
    ) -> ResolvedArtifact:
        expected_sha = descriptor.sha256 if descriptor is not None else None
        cached = self._cache.lookup(
            identity=self.identity,
            relative_path=relative_path,
            expected_sha256=expected_sha,
        )
        if cached is not None:
            digest, size = file_sha256_and_size(cached)
            if descriptor is not None:
                self._verify_against_descriptor(cached, descriptor)
            elif size > self.limits.max_artifact_bytes:
                raise OversizedArtifactError(
                    f"artifact exceeds max_artifact_bytes: {relative_path}"
                )
            return ResolvedArtifact(
                relative_path=relative_path,
                path=cached,
                size_bytes=size,
                sha256=digest,
                cache_hit=True,
                verified=True,
                row_count=descriptor.row_count if descriptor is not None else None,
                schema_id=descriptor.schema_id if descriptor is not None else "",
            )

        if self._hub is not None:
            artifact = self._hub.resolve(relative_path, descriptor=descriptor)
            # Mirror into the dual-identity cache so traces stay consistent.
            self._cache.store(
                identity=self.identity,
                relative_path=relative_path,
                source=artifact.path,
                sha256=artifact.sha256,
                size_bytes=artifact.size_bytes,
                move=False,
            )
            return artifact

        staging_dir = self._cache.root / "locks"
        self._cache._ensure_directory(staging_dir)
        fd, temporary_name = tempfile.mkstemp(
            prefix=".fetch.", suffix=".partial", dir=staging_dir
        )
        os.close(fd)
        temporary = Path(temporary_name)
        try:
            try:
                self.artifact_transport.fetch(
                    repo_id=self.bucket_id,
                    revision=self.manifest_sha256 or "",
                    relative_path=relative_path,
                    destination=temporary,
                    token=self._token,
                )
            except ResolverError as exc:
                message = _redact_secrets(str(exc))
                if self._token and self._token in message:
                    message = "failed to fetch pinned artifact"
                raise type(exc)(message) from None
            except Exception:
                raise TransportError(
                    f"failed to fetch pinned artifact: {relative_path}"
                ) from None
            if temporary.is_symlink():
                raise SymlinkRejectedError(f"symlinks are rejected: {relative_path}")
            digest, size = file_sha256_and_size(temporary)
            if size > self.limits.max_artifact_bytes:
                raise OversizedArtifactError(
                    f"artifact exceeds max_artifact_bytes: {relative_path}"
                )
            if descriptor is not None:
                if size != descriptor.size_bytes or digest != descriptor.sha256:
                    raise DigestDriftError(
                        f"artifact digest or size differs: {relative_path}"
                    )
                if descriptor.cid is not None:
                    actual_cid = raw_sha256_cid(bytes.fromhex(digest))
                    if actual_cid != descriptor.cid:
                        raise DigestDriftError(
                            f"artifact CID differs: {relative_path}"
                        )
            stored = self._cache.store(
                identity=self.identity,
                relative_path=relative_path,
                source=temporary,
                sha256=digest,
                size_bytes=size,
            )
            return ResolvedArtifact(
                relative_path=relative_path,
                path=stored,
                size_bytes=size,
                sha256=digest,
                cache_hit=False,
                verified=True,
                row_count=descriptor.row_count if descriptor is not None else None,
                schema_id=descriptor.schema_id if descriptor is not None else "",
            )
        finally:
            if temporary.exists():
                temporary.unlink(missing_ok=True)

    def _verify_against_descriptor(
        self, path: Path, descriptor: ArtifactDescriptor
    ) -> None:
        if path.is_symlink():
            raise SymlinkRejectedError(
                f"symlinks are rejected: {descriptor.relative_path}"
            )
        if not path.is_file():
            raise MissingArtifactError(
                f"artifact is missing: {descriptor.relative_path}"
            )
        digest, size = file_sha256_and_size(path)
        if size != descriptor.size_bytes or digest != descriptor.sha256:
            raise DigestDriftError(
                f"artifact digest or size differs: {descriptor.relative_path}"
            )

    def _verify_bucket_manifest_digest(
        self, payload: Mapping[str, Any], raw: bytes
    ) -> None:
        declared = payload.get("manifest_digest")
        if not isinstance(declared, str) or not declared.strip():
            raise DigestDriftError(
                "bucket manifest is missing manifest_digest; refusing unverified prefix"
            )
        declared_digest = normalize_sha256(declared, name="manifest_digest")
        if declared_digest != self.manifest_sha256:
            raise DigestDriftError(
                "manifest_digest drifted from the pinned releases/<manifest_sha256>/ prefix"
            )
        recomputed = digest_mapping(
            {key: value for key, value in payload.items() if key != "manifest_digest"}
        )
        if recomputed != declared_digest:
            raise DigestDriftError(
                "recomputed manifest digest drifted from the sealed manifest_digest"
            )
        del raw  # file bytes include the digest field and are not the prefix identity

    def _index_descriptors(self, manifest: Mapping[str, Any]) -> None:
        inventory = manifest.get("artifacts")
        if inventory is None:
            return
        if not isinstance(inventory, Sequence) or isinstance(inventory, (str, bytes)):
            raise SchemaMismatchError("manifest artifacts must be a list")
        indexed: dict[str, ArtifactDescriptor] = {}
        for item in inventory:
            if not isinstance(item, Mapping):
                raise SchemaMismatchError("artifact descriptor must be a mapping")
            descriptor = ArtifactDescriptor.from_mapping(item)
            self._enforce_descriptor_bounds(descriptor)
            if descriptor.relative_path in indexed:
                raise SchemaMismatchError(
                    f"duplicate artifact descriptor: {descriptor.relative_path}"
                )
            indexed[descriptor.relative_path] = descriptor
        self._descriptors.clear()
        self._descriptors.update(indexed)


def control_plane_route(relative_path: str = DEFAULT_MANIFEST_NAME) -> RouteJustification:
    """Route justification for the sealed control-plane manifest."""

    return RouteJustification(
        family="control_plane",
        reason="manifest",
        relative_path=relative_path,
    )


__all__ = [
    "AUTHORIZED_BUCKET_ID",
    "AUTHORIZED_DATASET_REPO_ID",
    "BUDGET_DIMENSIONS",
    "DEFAULT_BUCKET_ID",
    "DEFAULT_DATASET_REPO_ID",
    "DEFAULT_MANIFEST_NAME",
    "DEFAULT_SUPPORTED_RELEASE_SCHEMAS",
    "FETCH_TRACE_SCHEMA_VERSION",
    "GOAL_ID",
    "PROGRAM_ID",
    "RESOLVER_SCHEMA_VERSION",
    "TASK_ID",
    "ArtifactDescriptor",
    "ArtifactTransport",
    "BucketObjectTransport",
    "BucketPrefixError",
    "CacheCollisionError",
    "CredentialLeakageError",
    "DescriptorRequiredError",
    "DigestDriftError",
    "JustifiedFetchRecord",
    "MappingTransport",
    "MissingArtifactError",
    "MutablePointerError",
    "MutableRevisionError",
    "OpenUsLawResolver",
    "OpenUsLawResolverError",
    "OversizedArtifactError",
    "PrefixConfinedTransport",
    "ResolvedArtifact",
    "ResolverBudgetExhausted",
    "ResolverLimits",
    "RouteJustification",
    "SchemaMismatchError",
    "SymlinkRejectedError",
    "TransportError",
    "UnauthorizedTargetError",
    "UnjustifiedFetchError",
    "UnsafePathError",
    "authorize_query_pin",
    "control_plane_route",
    "is_mutable_pointer",
    "prefix_bucket_files",
    "reject_mutable_pointer",
    "require_bucket_release_prefix",
    "require_dataset_revision",
]
