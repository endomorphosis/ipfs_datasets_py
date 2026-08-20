"""Typed append-only observability catalog (DQK-052).

Stores lifecycle events, trace/span correlation, health samples, query
profiles, blocker transitions, dead letters, and audit records in a single
typed catalog with bounded retention and deterministic export.

Authority rules (fail-closed):

* Progress is sequence / event-id based — **file mtimes are never progress
  authority**.
* Sensitive query text is redacted and classified before persistence; secret
  material is refused, not stored.
* Control, query, proof, graph, vector, AST, and wallet domains correlate by
  explicit IDs on every record (via :class:`CorrelationIds` and shared
  ``trace_id`` / ``span_id``).

Catalog families (logical tables):

* ``lifecycle_events``
* ``traces``
* ``spans``
* ``health_samples``
* ``query_profiles``
* ``blocker_transitions``
* ``dead_letters``
* ``audit_events``

Importing this module is inert: no DuckDB, network, or filesystem I/O.
"""

from __future__ import annotations

import hashlib
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    ClassVar,
    Final,
    Iterable,
    Mapping,
    Protocol,
    Sequence,
)

from ipfs_datasets_py.duckdb_control.contracts import (
    ContractError,
    ContentMediaType,
    ContentReference,
    ExportReceipt,
    SnapshotId,
    canonical_json_bytes,
    content_identity,
    normalize_timestamp,
    parse_snapshot_id,
)

__all__ = [
    "OBSERVABILITY_SCHEMA",
    "LIFECYCLE_EVENT_SCHEMA",
    "TRACE_SCHEMA",
    "SPAN_SCHEMA",
    "HEALTH_SAMPLE_SCHEMA",
    "QUERY_PROFILE_SCHEMA",
    "BLOCKER_TRANSITION_SCHEMA",
    "DEAD_LETTER_SCHEMA",
    "AUDIT_RECORD_SCHEMA",
    "CORRELATION_SCHEMA",
    "RETENTION_POLICY_SCHEMA",
    "PROGRESS_CURSOR_SCHEMA",
    "EXPORT_BUNDLE_SCHEMA",
    "CATALOG_FAMILIES",
    "TRACE_DOMAINS",
    "REDACTION_MARKER",
    "DEFAULT_RETENTION_POLICY",
    "MAX_PAYLOAD_BYTES",
    "MAX_QUERY_TEXT_BYTES",
    "MAX_FAMILY_DEFAULT",
    "AuditRecord",
    "BlockerTransition",
    "CatalogFamily",
    "CorrelationIds",
    "DeadLetter",
    "HealthSample",
    "LifecycleEvent",
    "MemoryObservabilityBackend",
    "ObservabilityBackend",
    "ObservabilityCatalog",
    "ObservabilityError",
    "ObservabilityExport",
    "PayloadClassification",
    "ProgressAuthority",
    "ProgressCursor",
    "QueryProfile",
    "RetentionPolicy",
    "RetentionReceipt",
    "SensitivityClass",
    "SpanRecord",
    "TraceDomain",
    "TraceRecord",
    "classify_and_redact_query_text",
    "default_retention_policy",
    "open_memory_catalog",
    "progress_cursor_from_sequence",
    "refuse_mtime_progress_authority",
    "redact_sensitive_text",
]


# ---------------------------------------------------------------------------
# Schemas / constants
# ---------------------------------------------------------------------------

OBSERVABILITY_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-observability@1"
)
LIFECYCLE_EVENT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-observability-lifecycle-event@1"
)
TRACE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-observability-trace@1"
)
SPAN_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-observability-span@1"
)
HEALTH_SAMPLE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-observability-health-sample@1"
)
QUERY_PROFILE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-observability-query-profile@1"
)
BLOCKER_TRANSITION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-observability-blocker-transition@1"
)
DEAD_LETTER_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-observability-dead-letter@1"
)
AUDIT_RECORD_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-observability-audit-record@1"
)
CORRELATION_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-observability-correlation@1"
)
RETENTION_POLICY_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-observability-retention@1"
)
PROGRESS_CURSOR_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-observability-progress-cursor@1"
)
EXPORT_BUNDLE_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-observability-export-bundle@1"
)

_IMPLEMENTATION_GENERATION: Final[str] = "dqk-052-lane0-attempt1-20260810"

REDACTION_MARKER: Final[str] = "***REDACTED***"
MAX_PAYLOAD_BYTES: Final[int] = 64 * 1024
MAX_QUERY_TEXT_BYTES: Final[int] = 16 * 1024
MAX_FAMILY_DEFAULT: Final[int] = 50_000
MAX_EXPORT_RECORDS: Final[int] = 100_000
MAX_ATTR_KEYS: Final[int] = 64
MAX_ATTR_VALUE_BYTES: Final[int] = 1024

_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,255}$")
_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,127}$")

# Patterns that imply sensitive query / credential content and force redaction.
_SENSITIVE_QUERY_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(?i)\b(password|passwd|pwd)\b\s*="),
    re.compile(r"(?i)\b(api[_-]?key|secret|token|authorization)\b\s*="),
    re.compile(r"(?i)\b(private[_-]?key|mnemonic|seed|signing)\b"),
    re.compile(r"(?i)\b(bearer\s+[A-Za-z0-9\-._~+/]+=*)"),
    re.compile(r"(?i)(-----BEGIN[ A-Z]*PRIVATE KEY-----)"),
    re.compile(r"(?i)\bINSERT\s+INTO\b.+\bVALUES\b"),
)

# Tokens redacted inline when classification is REDACTED (not SECRET).
_INLINE_SECRET_RE = re.compile(
    r"(?i)(\b(?:password|passwd|pwd|secret|token|api[_-]?key|authorization)"
    r"\b\s*[=:]\s*)(['\"]?)([^'\"\s,;)]+)(\2)"
)


class ObservabilityError(ValueError):
    """Fail-closed observability catalog rejection."""


class CatalogFamily(str, Enum):
    """Logical table families in the observability catalog."""

    LIFECYCLE_EVENTS = "lifecycle_events"
    TRACES = "traces"
    SPANS = "spans"
    HEALTH_SAMPLES = "health_samples"
    QUERY_PROFILES = "query_profiles"
    BLOCKER_TRANSITIONS = "blocker_transitions"
    DEAD_LETTERS = "dead_letters"
    AUDIT_EVENTS = "audit_events"


CATALOG_FAMILIES: Final[frozenset[str]] = frozenset(
    family.value for family in CatalogFamily
)


class TraceDomain(str, Enum):
    """Cross-domain correlation namespaces.

    Acceptance requires control, query, proof, graph, vector, AST, and wallet
    traces to correlate by IDs. Additional domains are allowed for catalog-
    internal and system events.
    """

    CONTROL = "control"
    QUERY = "query"
    PROOF = "proof"
    GRAPH = "graph"
    VECTOR = "vector"
    AST = "ast"
    WALLET = "wallet"
    OBSERVABILITY = "observability"
    SYSTEM = "system"


TRACE_DOMAINS: Final[frozenset[str]] = frozenset(
    domain.value for domain in TraceDomain
)

# Domains that must be able to join via correlation IDs (acceptance).
REQUIRED_CORRELATION_DOMAINS: Final[frozenset[str]] = frozenset(
    {
        TraceDomain.CONTROL.value,
        TraceDomain.QUERY.value,
        TraceDomain.PROOF.value,
        TraceDomain.GRAPH.value,
        TraceDomain.VECTOR.value,
        TraceDomain.AST.value,
        TraceDomain.WALLET.value,
    }
)


class SensitivityClass(str, Enum):
    """Payload sensitivity classification (fail-closed for SECRET storage)."""

    PUBLIC = "public"
    INTERNAL = "internal"
    REDACTED = "redacted"
    SECRET = "secret"


# Alias used by adapters / docs interchangeably with SensitivityClass.
PayloadClassification = SensitivityClass


class ProgressAuthority(str, Enum):
    """Closed set of accepted progress authorities.

    ``FILE_MTIME`` is listed only so it can be *explicitly rejected*.
    """

    SEQUENCE = "sequence"
    EVENT_ID = "event_id"
    CURSOR = "cursor"
    FILE_MTIME = "file_mtime"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _require_id(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ObservabilityError(f"{field_name} is required")
    text = value.strip()
    if "\x00" in text or "\n" in text or "\r" in text:
        raise ObservabilityError(f"{field_name} must be single-line text")
    if _ID_RE.fullmatch(text) is None:
        raise ObservabilityError(f"{field_name} is not a safe token: {value!r}")
    return text


def _optional_id(value: Any, field_name: str) -> str:
    if value is None or value == "":
        return ""
    return _require_id(value, field_name)


def _normalize_ts(value: Any, field_name: str = "recorded_at") -> str:
    if value is None or value == "":
        return _utc_now()
    try:
        return normalize_timestamp(value)
    except ContractError as exc:
        raise ObservabilityError(f"{field_name}: {exc}") from exc


def _freeze_attrs(attrs: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if attrs is None:
        return MappingProxyType({})
    if not isinstance(attrs, Mapping):
        raise ObservabilityError("attributes must be a mapping")
    if len(attrs) > MAX_ATTR_KEYS:
        raise ObservabilityError(
            f"attributes exceed {MAX_ATTR_KEYS}-key bound"
        )
    plain: dict[str, Any] = {}
    for key, item in attrs.items():
        if not isinstance(key, str) or not key.strip():
            raise ObservabilityError("attribute keys must be non-empty text")
        name = key.strip()
        if not _SAFE_TOKEN.fullmatch(name):
            raise ObservabilityError(f"unsafe attribute key {key!r}")
        if isinstance(item, (str, int, float, bool)) or item is None:
            if isinstance(item, str) and len(item.encode("utf-8")) > MAX_ATTR_VALUE_BYTES:
                raise ObservabilityError(
                    f"attribute {name!r} exceeds value byte bound"
                )
            if isinstance(item, float) and (
                item != item or item in (float("inf"), float("-inf"))
            ):
                raise ObservabilityError(
                    f"attribute {name!r} must be finite"
                )
            plain[name] = item
        else:
            raise ObservabilityError(
                f"attribute {name!r} must be a JSON scalar or null"
            )
    # Size bound over canonical form.
    raw = canonical_json_bytes(plain)
    if len(raw) > MAX_PAYLOAD_BYTES:
        raise ObservabilityError("attributes exceed payload byte bound")
    return MappingProxyType(plain)


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def refuse_mtime_progress_authority(
    authority: ProgressAuthority | str | None = None,
    *,
    mtime: float | int | None = None,
    path: str | None = None,
) -> None:
    """Reject file-mtime based progress claims (acceptance criterion).

    Progress in this catalog is sequence/event-id/cursor based. Callers that
    attempt to derive progress from filesystem modification times fail closed
    here — including bare ``mtime`` / ``path`` arguments without an authority
    label.
    """

    if mtime is not None or path is not None:
        raise ObservabilityError(
            "file mtimes are not progress authority; "
            "use sequence, event_id, or cursor"
        )
    if authority is None:
        return
    if isinstance(authority, ProgressAuthority):
        value = authority
    else:
        try:
            value = ProgressAuthority(str(authority).strip().lower())
        except ValueError as exc:
            raise ObservabilityError(
                f"unknown progress authority {authority!r}"
            ) from exc
    if value is ProgressAuthority.FILE_MTIME:
        raise ObservabilityError(
            "file mtimes are not progress authority; "
            "use sequence, event_id, or cursor"
        )


def progress_cursor_from_sequence(
    sequence: int,
    *,
    event_id: str = "",
    family: CatalogFamily | str | None = None,
    recorded_at: str | None = None,
) -> "ProgressCursor":
    """Build a progress cursor from catalog sequence authority only."""

    refuse_mtime_progress_authority(ProgressAuthority.SEQUENCE)
    return ProgressCursor(
        sequence=sequence,
        event_id=event_id,
        family=str(family.value if isinstance(family, CatalogFamily) else family or ""),
        recorded_at=_normalize_ts(recorded_at),
        authority=ProgressAuthority.SEQUENCE,
    )


def redact_sensitive_text(text: str) -> str:
    """Inline-redact credential-like assignments in free text."""

    if not isinstance(text, str):
        return REDACTION_MARKER
    return _INLINE_SECRET_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}{REDACTION_MARKER}{m.group(4)}",
        text,
    )


def classify_and_redact_query_text(
    query_text: str | None,
    *,
    classification: SensitivityClass | str | None = None,
    allow_secret_storage: bool = False,
) -> tuple[str, SensitivityClass, str]:
    """Classify query text and return ``(stored_text, class, digest)``.

    * ``SECRET`` material is refused unless ``allow_secret_storage`` (which
      still never stores the raw bytes — only a digest marker).
    * Patterns that look like credentials force at least ``REDACTED``.
    * Returned digest is always over the *original* exact text so operators
      can match without retaining plaintext.
    """

    if query_text is None:
        text = ""
    elif not isinstance(query_text, str):
        raise ObservabilityError("query_text must be text or null")
    else:
        text = query_text

    if "\x00" in text:
        raise ObservabilityError("query_text must not contain NUL")

    raw_bytes = text.encode("utf-8")
    if len(raw_bytes) > MAX_QUERY_TEXT_BYTES:
        raise ObservabilityError(
            f"query_text exceeds {MAX_QUERY_TEXT_BYTES}-byte bound"
        )
    digest = f"sha256:{_sha256_hex(raw_bytes)}" if raw_bytes else ""

    if classification is None:
        klass = SensitivityClass.INTERNAL
    elif isinstance(classification, SensitivityClass):
        klass = classification
    else:
        try:
            klass = SensitivityClass(str(classification).strip().lower())
        except ValueError as exc:
            raise ObservabilityError(
                f"invalid sensitivity classification {classification!r}"
            ) from exc

    # Escalate classification when sensitive patterns are present.
    if text and any(p.search(text) for p in _SENSITIVE_QUERY_PATTERNS):
        if klass in (SensitivityClass.PUBLIC, SensitivityClass.INTERNAL):
            klass = SensitivityClass.REDACTED

    if klass is SensitivityClass.SECRET:
        if not allow_secret_storage:
            raise ObservabilityError(
                "secret query text cannot be stored in the observability "
                "catalog; pass classification=redacted or omit plaintext"
            )
        return REDACTION_MARKER, SensitivityClass.SECRET, digest

    if klass is SensitivityClass.REDACTED:
        return redact_sensitive_text(text) if text else "", klass, digest

    if klass is SensitivityClass.PUBLIC:
        # Public still gets inline credential scrubbing as defense in depth.
        return redact_sensitive_text(text) if text else "", klass, digest

    # INTERNAL: store as-is after size/NUL checks (no secret patterns matched
    # or caller already classified higher).
    return text, klass, digest


# ---------------------------------------------------------------------------
# Correlation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CorrelationIds:
    """Cross-domain correlation bundle shared by observability records.

    Domains control / query / proof / graph / vector / ast / wallet join by
    the corresponding id field. Empty strings mean "not bound". A shared
    ``trace_id`` (and optional ``span_id``) is the primary join key.
    """

    SCHEMA: ClassVar[str] = CORRELATION_SCHEMA

    trace_id: str = ""
    span_id: str = ""
    parent_span_id: str = ""
    control_task_id: str = ""
    control_goal_id: str = ""
    query_receipt_id: str = ""
    query_template_id: str = ""
    proof_key_id: str = ""
    proof_entry_id: str = ""
    graph_id: str = ""
    graph_revision_id: str = ""
    vector_collection_id: str = ""
    vector_generation_id: str = ""
    ast_source_revision_id: str = ""
    ast_blob_id: str = ""
    wallet_chain_id: str = ""
    wallet_cursor_id: str = ""
    tenant_id: str = ""
    request_id: str = ""

    def __post_init__(self) -> None:
        for name in (
            "trace_id",
            "span_id",
            "parent_span_id",
            "control_task_id",
            "control_goal_id",
            "query_receipt_id",
            "query_template_id",
            "proof_key_id",
            "proof_entry_id",
            "graph_id",
            "graph_revision_id",
            "vector_collection_id",
            "vector_generation_id",
            "ast_source_revision_id",
            "ast_blob_id",
            "wallet_chain_id",
            "wallet_cursor_id",
            "tenant_id",
            "request_id",
        ):
            object.__setattr__(
                self, name, _optional_id(getattr(self, name), name)
            )

    def domain_id(self, domain: TraceDomain | str) -> str:
        """Return the primary correlation id for ``domain`` if set."""

        if isinstance(domain, TraceDomain):
            key = domain
        else:
            try:
                key = TraceDomain(str(domain).strip().lower())
            except ValueError as exc:
                raise ObservabilityError(
                    f"unknown trace domain {domain!r}"
                ) from exc
        mapping = {
            TraceDomain.CONTROL: self.control_task_id or self.control_goal_id,
            TraceDomain.QUERY: self.query_receipt_id or self.query_template_id,
            TraceDomain.PROOF: self.proof_key_id or self.proof_entry_id,
            TraceDomain.GRAPH: self.graph_revision_id or self.graph_id,
            TraceDomain.VECTOR: self.vector_generation_id
            or self.vector_collection_id,
            TraceDomain.AST: self.ast_source_revision_id or self.ast_blob_id,
            TraceDomain.WALLET: self.wallet_cursor_id or self.wallet_chain_id,
            TraceDomain.OBSERVABILITY: self.trace_id,
            TraceDomain.SYSTEM: self.request_id or self.trace_id,
        }
        return mapping[key]

    def bound_domains(self) -> tuple[str, ...]:
        """Domains with a non-empty primary correlation id (required set only)."""

        bound: list[str] = []
        for domain in (
            TraceDomain.CONTROL,
            TraceDomain.QUERY,
            TraceDomain.PROOF,
            TraceDomain.GRAPH,
            TraceDomain.VECTOR,
            TraceDomain.AST,
            TraceDomain.WALLET,
        ):
            if self.domain_id(domain):
                bound.append(domain.value)
        return tuple(bound)

    def merge(self, other: "CorrelationIds") -> "CorrelationIds":
        """Return a new bundle preferring non-empty fields from ``other``."""

        if not isinstance(other, CorrelationIds):
            raise ObservabilityError("merge requires CorrelationIds")
        kwargs: dict[str, str] = {}
        for name in self.__slots__:
            left = getattr(self, name)
            right = getattr(other, name)
            if right:
                if left and left != right:
                    raise ObservabilityError(
                        f"correlation conflict on {name}: {left!r} vs {right!r}"
                    )
                kwargs[name] = right
            else:
                kwargs[name] = left
        return CorrelationIds(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CORRELATION_SCHEMA,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "control_task_id": self.control_task_id,
            "control_goal_id": self.control_goal_id,
            "query_receipt_id": self.query_receipt_id,
            "query_template_id": self.query_template_id,
            "proof_key_id": self.proof_key_id,
            "proof_entry_id": self.proof_entry_id,
            "graph_id": self.graph_id,
            "graph_revision_id": self.graph_revision_id,
            "vector_collection_id": self.vector_collection_id,
            "vector_generation_id": self.vector_generation_id,
            "ast_source_revision_id": self.ast_source_revision_id,
            "ast_blob_id": self.ast_blob_id,
            "wallet_chain_id": self.wallet_chain_id,
            "wallet_cursor_id": self.wallet_cursor_id,
            "tenant_id": self.tenant_id,
            "request_id": self.request_id,
            "bound_domains": list(self.bound_domains()),
        }

    @property
    def identity_id(self) -> str:
        return content_identity(self.to_dict())


EMPTY_CORRELATION: Final[CorrelationIds] = CorrelationIds()


# ---------------------------------------------------------------------------
# Progress cursor
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProgressCursor:
    """Catalog-authoritative progress marker (never file mtime)."""

    SCHEMA: ClassVar[str] = PROGRESS_CURSOR_SCHEMA

    sequence: int
    event_id: str = ""
    family: str = ""
    recorded_at: str = ""
    authority: ProgressAuthority = ProgressAuthority.SEQUENCE

    def __post_init__(self) -> None:
        if (
            not isinstance(self.sequence, int)
            or isinstance(self.sequence, bool)
            or self.sequence < 0
        ):
            raise ObservabilityError("sequence must be a non-negative int")
        object.__setattr__(
            self, "event_id", _optional_id(self.event_id, "event_id")
        )
        family = str(self.family or "").strip()
        if family and family not in CATALOG_FAMILIES:
            raise ObservabilityError(f"unknown catalog family {family!r}")
        object.__setattr__(self, "family", family)
        object.__setattr__(
            self, "recorded_at", _normalize_ts(self.recorded_at or None)
        )
        if isinstance(self.authority, ProgressAuthority):
            authority = self.authority
        else:
            try:
                authority = ProgressAuthority(str(self.authority).strip().lower())
            except ValueError as exc:
                raise ObservabilityError(
                    f"invalid progress authority {self.authority!r}"
                ) from exc
        if authority is ProgressAuthority.FILE_MTIME:
            raise ObservabilityError(
                "file mtimes are not progress authority"
            )
        object.__setattr__(self, "authority", authority)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": PROGRESS_CURSOR_SCHEMA,
            "sequence": self.sequence,
            "event_id": self.event_id,
            "family": self.family,
            "recorded_at": self.recorded_at,
            "authority": self.authority.value,
        }

    @property
    def identity_id(self) -> str:
        return content_identity(self.to_dict())


# ---------------------------------------------------------------------------
# Retention
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RetentionPolicy:
    """Bounded retention per catalog family (count + optional age)."""

    SCHEMA: ClassVar[str] = RETENTION_POLICY_SCHEMA

    max_records_per_family: Mapping[str, int] = field(default_factory=dict)
    max_age_seconds: int | None = None
    default_max_records: int = MAX_FAMILY_DEFAULT

    def __post_init__(self) -> None:
        if (
            not isinstance(self.default_max_records, int)
            or isinstance(self.default_max_records, bool)
            or self.default_max_records < 1
        ):
            raise ObservabilityError("default_max_records must be positive")
        limits: dict[str, int] = {}
        source = self.max_records_per_family or {}
        if not isinstance(source, Mapping):
            raise ObservabilityError("max_records_per_family must be a mapping")
        for key, value in source.items():
            name = str(key).strip()
            if name not in CATALOG_FAMILIES:
                raise ObservabilityError(f"unknown catalog family {name!r}")
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 1
            ):
                raise ObservabilityError(
                    f"max records for {name} must be a positive int"
                )
            limits[name] = value
        object.__setattr__(
            self, "max_records_per_family", MappingProxyType(limits)
        )
        if self.max_age_seconds is not None:
            if (
                not isinstance(self.max_age_seconds, int)
                or isinstance(self.max_age_seconds, bool)
                or self.max_age_seconds < 1
            ):
                raise ObservabilityError(
                    "max_age_seconds must be a positive int or None"
                )

    def limit_for(self, family: CatalogFamily | str) -> int:
        name = family.value if isinstance(family, CatalogFamily) else str(family)
        return int(
            self.max_records_per_family.get(name, self.default_max_records)
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": RETENTION_POLICY_SCHEMA,
            "max_records_per_family": dict(self.max_records_per_family),
            "max_age_seconds": self.max_age_seconds,
            "default_max_records": self.default_max_records,
        }


def default_retention_policy(
    *,
    default_max_records: int = MAX_FAMILY_DEFAULT,
    max_age_seconds: int | None = None,
    per_family: Mapping[str, int] | None = None,
) -> RetentionPolicy:
    return RetentionPolicy(
        max_records_per_family=dict(per_family or {}),
        max_age_seconds=max_age_seconds,
        default_max_records=default_max_records,
    )


DEFAULT_RETENTION_POLICY: Final[RetentionPolicy] = default_retention_policy()


@dataclass(frozen=True, slots=True)
class RetentionReceipt:
    """Immutable receipt for one retention application."""

    family: str
    removed_count: int
    retained_count: int
    max_sequence_removed: int
    applied_at: str
    policy_identity: str
    dry_run: bool = False

    def __post_init__(self) -> None:
        if self.family not in CATALOG_FAMILIES:
            raise ObservabilityError(f"unknown family {self.family!r}")
        if (
            not isinstance(self.removed_count, int)
            or isinstance(self.removed_count, bool)
            or self.removed_count < 0
        ):
            raise ObservabilityError("removed_count must be non-negative")
        if (
            not isinstance(self.retained_count, int)
            or isinstance(self.retained_count, bool)
            or self.retained_count < 0
        ):
            raise ObservabilityError("retained_count must be non-negative")
        object.__setattr__(self, "applied_at", _normalize_ts(self.applied_at))

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "removed_count": self.removed_count,
            "retained_count": self.retained_count,
            "max_sequence_removed": self.max_sequence_removed,
            "applied_at": self.applied_at,
            "policy_identity": self.policy_identity,
            "dry_run": self.dry_run,
        }


# ---------------------------------------------------------------------------
# Record types
# ---------------------------------------------------------------------------


def _require_correlation(
    correlation: CorrelationIds | Mapping[str, Any] | None,
) -> CorrelationIds:
    if correlation is None:
        return EMPTY_CORRELATION
    if isinstance(correlation, CorrelationIds):
        return correlation
    if isinstance(correlation, Mapping):
        allowed = {s for s in CorrelationIds.__slots__}
        kwargs = {k: v for k, v in correlation.items() if k in allowed}
        return CorrelationIds(**kwargs)
    raise ObservabilityError("correlation must be CorrelationIds or mapping")


def _require_domain(domain: TraceDomain | str) -> TraceDomain:
    if isinstance(domain, TraceDomain):
        return domain
    try:
        return TraceDomain(str(domain).strip().lower())
    except ValueError as exc:
        raise ObservabilityError(f"unknown trace domain {domain!r}") from exc


def _require_sensitivity(
    value: SensitivityClass | str,
) -> SensitivityClass:
    if isinstance(value, SensitivityClass):
        return value
    try:
        return SensitivityClass(str(value).strip().lower())
    except ValueError as exc:
        raise ObservabilityError(
            f"invalid sensitivity classification {value!r}"
        ) from exc


@dataclass(frozen=True, slots=True)
class LifecycleEvent:
    """Append-only lifecycle event (start/stop/transition of a component)."""

    SCHEMA: ClassVar[str] = LIFECYCLE_EVENT_SCHEMA
    FAMILY: ClassVar[CatalogFamily] = CatalogFamily.LIFECYCLE_EVENTS

    event_id: str
    event_type: str
    component: str
    domain: TraceDomain
    recorded_at: str
    correlation: CorrelationIds = field(default_factory=CorrelationIds)
    status: str = "ok"
    detail: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    sequence: int = 0
    previous_event_id: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _require_id(self.event_id, "event_id"))
        object.__setattr__(
            self, "event_type", _require_id(self.event_type, "event_type")
        )
        object.__setattr__(
            self, "component", _require_id(self.component, "component")
        )
        object.__setattr__(self, "domain", _require_domain(self.domain))
        object.__setattr__(self, "recorded_at", _normalize_ts(self.recorded_at))
        object.__setattr__(
            self, "correlation", _require_correlation(self.correlation)
        )
        status = str(self.status or "ok").strip().lower()
        if not status or not _SAFE_TOKEN.fullmatch(status):
            raise ObservabilityError(f"invalid status {self.status!r}")
        object.__setattr__(self, "status", status)
        detail = str(self.detail or "")
        if len(detail.encode("utf-8")) > MAX_ATTR_VALUE_BYTES:
            detail = detail.encode("utf-8")[:MAX_ATTR_VALUE_BYTES].decode(
                "utf-8", errors="ignore"
            )
        object.__setattr__(self, "detail", redact_sensitive_text(detail))
        object.__setattr__(self, "attributes", _freeze_attrs(self.attributes))
        if (
            not isinstance(self.sequence, int)
            or isinstance(self.sequence, bool)
            or self.sequence < 0
        ):
            raise ObservabilityError("sequence must be a non-negative int")
        object.__setattr__(
            self,
            "previous_event_id",
            _optional_id(self.previous_event_id, "previous_event_id"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": LIFECYCLE_EVENT_SCHEMA,
            "family": self.FAMILY.value,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "component": self.component,
            "domain": self.domain.value,
            "recorded_at": self.recorded_at,
            "correlation": self.correlation.to_dict(),
            "status": self.status,
            "detail": self.detail,
            "attributes": dict(self.attributes),
            "sequence": self.sequence,
            "previous_event_id": self.previous_event_id,
        }

    @property
    def identity_id(self) -> str:
        return content_identity(self.to_dict())


@dataclass(frozen=True, slots=True)
class TraceRecord:
    """Root trace that binds a cross-domain correlation bundle."""

    SCHEMA: ClassVar[str] = TRACE_SCHEMA
    FAMILY: ClassVar[CatalogFamily] = CatalogFamily.TRACES

    trace_id: str
    root_domain: TraceDomain
    name: str
    recorded_at: str
    correlation: CorrelationIds = field(default_factory=CorrelationIds)
    status: str = "started"
    attributes: Mapping[str, Any] = field(default_factory=dict)
    sequence: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "trace_id", _require_id(self.trace_id, "trace_id"))
        object.__setattr__(self, "root_domain", _require_domain(self.root_domain))
        object.__setattr__(self, "name", _require_id(self.name, "name"))
        object.__setattr__(self, "recorded_at", _normalize_ts(self.recorded_at))
        corr = _require_correlation(self.correlation)
        if corr.trace_id and corr.trace_id != self.trace_id:
            raise ObservabilityError(
                f"correlation.trace_id {corr.trace_id!r} disagrees with "
                f"trace_id {self.trace_id!r}"
            )
        if not corr.trace_id:
            corr = CorrelationIds(
                trace_id=self.trace_id,
                span_id=corr.span_id,
                parent_span_id=corr.parent_span_id,
                control_task_id=corr.control_task_id,
                control_goal_id=corr.control_goal_id,
                query_receipt_id=corr.query_receipt_id,
                query_template_id=corr.query_template_id,
                proof_key_id=corr.proof_key_id,
                proof_entry_id=corr.proof_entry_id,
                graph_id=corr.graph_id,
                graph_revision_id=corr.graph_revision_id,
                vector_collection_id=corr.vector_collection_id,
                vector_generation_id=corr.vector_generation_id,
                ast_source_revision_id=corr.ast_source_revision_id,
                ast_blob_id=corr.ast_blob_id,
                wallet_chain_id=corr.wallet_chain_id,
                wallet_cursor_id=corr.wallet_cursor_id,
                tenant_id=corr.tenant_id,
                request_id=corr.request_id,
            )
        object.__setattr__(self, "correlation", corr)
        status = str(self.status or "started").strip().lower()
        if not _SAFE_TOKEN.fullmatch(status):
            raise ObservabilityError(f"invalid status {self.status!r}")
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "attributes", _freeze_attrs(self.attributes))
        if (
            not isinstance(self.sequence, int)
            or isinstance(self.sequence, bool)
            or self.sequence < 0
        ):
            raise ObservabilityError("sequence must be a non-negative int")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": TRACE_SCHEMA,
            "family": self.FAMILY.value,
            "trace_id": self.trace_id,
            "root_domain": self.root_domain.value,
            "name": self.name,
            "recorded_at": self.recorded_at,
            "correlation": self.correlation.to_dict(),
            "status": self.status,
            "attributes": dict(self.attributes),
            "sequence": self.sequence,
        }

    @property
    def identity_id(self) -> str:
        return content_identity(self.to_dict())


@dataclass(frozen=True, slots=True)
class SpanRecord:
    """Span within a trace; carries domain + parent linkage."""

    SCHEMA: ClassVar[str] = SPAN_SCHEMA
    FAMILY: ClassVar[CatalogFamily] = CatalogFamily.SPANS

    span_id: str
    trace_id: str
    name: str
    domain: TraceDomain
    recorded_at: str
    parent_span_id: str = ""
    correlation: CorrelationIds = field(default_factory=CorrelationIds)
    status: str = "ok"
    duration_ms: int = 0
    attributes: Mapping[str, Any] = field(default_factory=dict)
    sequence: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "span_id", _require_id(self.span_id, "span_id"))
        object.__setattr__(self, "trace_id", _require_id(self.trace_id, "trace_id"))
        object.__setattr__(self, "name", _require_id(self.name, "name"))
        object.__setattr__(self, "domain", _require_domain(self.domain))
        object.__setattr__(self, "recorded_at", _normalize_ts(self.recorded_at))
        object.__setattr__(
            self,
            "parent_span_id",
            _optional_id(self.parent_span_id, "parent_span_id"),
        )
        corr = _require_correlation(self.correlation)
        # Mirror span/trace ids into correlation.
        corr = CorrelationIds(
            trace_id=self.trace_id,
            span_id=self.span_id,
            parent_span_id=self.parent_span_id or corr.parent_span_id,
            control_task_id=corr.control_task_id,
            control_goal_id=corr.control_goal_id,
            query_receipt_id=corr.query_receipt_id,
            query_template_id=corr.query_template_id,
            proof_key_id=corr.proof_key_id,
            proof_entry_id=corr.proof_entry_id,
            graph_id=corr.graph_id,
            graph_revision_id=corr.graph_revision_id,
            vector_collection_id=corr.vector_collection_id,
            vector_generation_id=corr.vector_generation_id,
            ast_source_revision_id=corr.ast_source_revision_id,
            ast_blob_id=corr.ast_blob_id,
            wallet_chain_id=corr.wallet_chain_id,
            wallet_cursor_id=corr.wallet_cursor_id,
            tenant_id=corr.tenant_id,
            request_id=corr.request_id,
        )
        object.__setattr__(self, "correlation", corr)
        status = str(self.status or "ok").strip().lower()
        if not _SAFE_TOKEN.fullmatch(status):
            raise ObservabilityError(f"invalid status {self.status!r}")
        object.__setattr__(self, "status", status)
        if (
            not isinstance(self.duration_ms, int)
            or isinstance(self.duration_ms, bool)
            or self.duration_ms < 0
        ):
            raise ObservabilityError("duration_ms must be a non-negative int")
        object.__setattr__(self, "attributes", _freeze_attrs(self.attributes))
        if (
            not isinstance(self.sequence, int)
            or isinstance(self.sequence, bool)
            or self.sequence < 0
        ):
            raise ObservabilityError("sequence must be a non-negative int")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": SPAN_SCHEMA,
            "family": self.FAMILY.value,
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "domain": self.domain.value,
            "recorded_at": self.recorded_at,
            "correlation": self.correlation.to_dict(),
            "status": self.status,
            "duration_ms": self.duration_ms,
            "attributes": dict(self.attributes),
            "sequence": self.sequence,
        }

    @property
    def identity_id(self) -> str:
        return content_identity(self.to_dict())


@dataclass(frozen=True, slots=True)
class HealthSample:
    """Point-in-time health / SLO sample for a component."""

    SCHEMA: ClassVar[str] = HEALTH_SAMPLE_SCHEMA
    FAMILY: ClassVar[CatalogFamily] = CatalogFamily.HEALTH_SAMPLES

    sample_id: str
    component: str
    domain: TraceDomain
    status: str
    recorded_at: str
    correlation: CorrelationIds = field(default_factory=CorrelationIds)
    latency_ms: int = 0
    error_rate_bps: int = 0
    attributes: Mapping[str, Any] = field(default_factory=dict)
    sequence: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "sample_id", _require_id(self.sample_id, "sample_id")
        )
        object.__setattr__(
            self, "component", _require_id(self.component, "component")
        )
        object.__setattr__(self, "domain", _require_domain(self.domain))
        status = str(self.status or "").strip().lower()
        if status not in {"healthy", "degraded", "unhealthy", "unknown"}:
            raise ObservabilityError(
                "health status must be healthy|degraded|unhealthy|unknown"
            )
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "recorded_at", _normalize_ts(self.recorded_at))
        object.__setattr__(
            self, "correlation", _require_correlation(self.correlation)
        )
        for name in ("latency_ms", "error_rate_bps", "sequence"):
            value = getattr(self, name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ObservabilityError(f"{name} must be a non-negative int")
        if self.error_rate_bps > 10_000:
            raise ObservabilityError("error_rate_bps must be <= 10000")
        object.__setattr__(self, "attributes", _freeze_attrs(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": HEALTH_SAMPLE_SCHEMA,
            "family": self.FAMILY.value,
            "sample_id": self.sample_id,
            "component": self.component,
            "domain": self.domain.value,
            "status": self.status,
            "recorded_at": self.recorded_at,
            "correlation": self.correlation.to_dict(),
            "latency_ms": self.latency_ms,
            "error_rate_bps": self.error_rate_bps,
            "attributes": dict(self.attributes),
            "sequence": self.sequence,
        }

    @property
    def identity_id(self) -> str:
        return content_identity(self.to_dict())


@dataclass(frozen=True, slots=True)
class QueryProfile:
    """Query execution profile with classified / redacted query text."""

    SCHEMA: ClassVar[str] = QUERY_PROFILE_SCHEMA
    FAMILY: ClassVar[CatalogFamily] = CatalogFamily.QUERY_PROFILES

    profile_id: str
    template_id: str
    recorded_at: str
    query_text: str
    query_text_classification: SensitivityClass
    query_text_digest: str
    correlation: CorrelationIds = field(default_factory=CorrelationIds)
    status: str = "succeeded"
    duration_ms: int = 0
    row_count: int = 0
    byte_count: int = 0
    snapshot_id: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    sequence: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "profile_id", _require_id(self.profile_id, "profile_id")
        )
        object.__setattr__(
            self, "template_id", _require_id(self.template_id, "template_id")
        )
        object.__setattr__(self, "recorded_at", _normalize_ts(self.recorded_at))
        klass = _require_sensitivity(self.query_text_classification)
        if klass is SensitivityClass.SECRET and self.query_text not in (
            "",
            REDACTION_MARKER,
        ):
            raise ObservabilityError(
                "secret query profiles must not retain plaintext"
            )
        # Re-run classification to ensure stored text is safe.
        stored, klass, digest = classify_and_redact_query_text(
            self.query_text if klass is not SensitivityClass.SECRET else "",
            classification=klass,
            allow_secret_storage=(klass is SensitivityClass.SECRET),
        )
        if self.query_text_digest:
            # Caller-supplied digest of original text is authoritative when set.
            dig = str(self.query_text_digest).strip().lower()
            if not dig.startswith("sha256:") or len(dig) != len("sha256:") + 64:
                raise ObservabilityError("query_text_digest must be sha256:<hex>")
            object.__setattr__(self, "query_text_digest", dig)
        else:
            object.__setattr__(self, "query_text_digest", digest)
        object.__setattr__(self, "query_text", stored)
        object.__setattr__(self, "query_text_classification", klass)
        object.__setattr__(
            self, "correlation", _require_correlation(self.correlation)
        )
        status = str(self.status or "succeeded").strip().lower()
        if not _SAFE_TOKEN.fullmatch(status):
            raise ObservabilityError(f"invalid status {self.status!r}")
        object.__setattr__(self, "status", status)
        for name in ("duration_ms", "row_count", "byte_count", "sequence"):
            value = getattr(self, name)
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ObservabilityError(f"{name} must be a non-negative int")
        snap = str(self.snapshot_id or "").strip()
        if snap:
            try:
                snap = parse_snapshot_id(snap)
            except ContractError as exc:
                raise ObservabilityError(str(exc)) from exc
        object.__setattr__(self, "snapshot_id", snap)
        object.__setattr__(self, "attributes", _freeze_attrs(self.attributes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": QUERY_PROFILE_SCHEMA,
            "family": self.FAMILY.value,
            "profile_id": self.profile_id,
            "template_id": self.template_id,
            "recorded_at": self.recorded_at,
            "query_text": self.query_text,
            "query_text_classification": self.query_text_classification.value,
            "query_text_digest": self.query_text_digest,
            "correlation": self.correlation.to_dict(),
            "status": self.status,
            "duration_ms": self.duration_ms,
            "row_count": self.row_count,
            "byte_count": self.byte_count,
            "snapshot_id": self.snapshot_id,
            "attributes": dict(self.attributes),
            "sequence": self.sequence,
        }

    @property
    def identity_id(self) -> str:
        return content_identity(self.to_dict())


@dataclass(frozen=True, slots=True)
class BlockerTransition:
    """Typed blocker state transition (opened / resolved / escalated)."""

    SCHEMA: ClassVar[str] = BLOCKER_TRANSITION_SCHEMA
    FAMILY: ClassVar[CatalogFamily] = CatalogFamily.BLOCKER_TRANSITIONS

    transition_id: str
    blocker_id: str
    blocker_type: str
    from_state: str
    to_state: str
    recorded_at: str
    correlation: CorrelationIds = field(default_factory=CorrelationIds)
    reason: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    sequence: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "transition_id",
            _require_id(self.transition_id, "transition_id"),
        )
        object.__setattr__(
            self, "blocker_id", _require_id(self.blocker_id, "blocker_id")
        )
        object.__setattr__(
            self, "blocker_type", _require_id(self.blocker_type, "blocker_type")
        )
        for name in ("from_state", "to_state"):
            value = str(getattr(self, name) or "").strip().lower()
            if not value or not _SAFE_TOKEN.fullmatch(value):
                raise ObservabilityError(f"invalid {name}")
            object.__setattr__(self, name, value)
        if self.from_state == self.to_state:
            raise ObservabilityError("blocker transition must change state")
        object.__setattr__(self, "recorded_at", _normalize_ts(self.recorded_at))
        object.__setattr__(
            self, "correlation", _require_correlation(self.correlation)
        )
        reason = redact_sensitive_text(str(self.reason or ""))
        if len(reason.encode("utf-8")) > MAX_ATTR_VALUE_BYTES:
            reason = reason.encode("utf-8")[:MAX_ATTR_VALUE_BYTES].decode(
                "utf-8", errors="ignore"
            )
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "attributes", _freeze_attrs(self.attributes))
        if (
            not isinstance(self.sequence, int)
            or isinstance(self.sequence, bool)
            or self.sequence < 0
        ):
            raise ObservabilityError("sequence must be a non-negative int")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": BLOCKER_TRANSITION_SCHEMA,
            "family": self.FAMILY.value,
            "transition_id": self.transition_id,
            "blocker_id": self.blocker_id,
            "blocker_type": self.blocker_type,
            "from_state": self.from_state,
            "to_state": self.to_state,
            "recorded_at": self.recorded_at,
            "correlation": self.correlation.to_dict(),
            "reason": self.reason,
            "attributes": dict(self.attributes),
            "sequence": self.sequence,
        }

    @property
    def identity_id(self) -> str:
        return content_identity(self.to_dict())


@dataclass(frozen=True, slots=True)
class DeadLetter:
    """Failed / abandoned work item retained for operator recovery."""

    SCHEMA: ClassVar[str] = DEAD_LETTER_SCHEMA
    FAMILY: ClassVar[CatalogFamily] = CatalogFamily.DEAD_LETTERS

    letter_id: str
    source: str
    domain: TraceDomain
    reason: str
    recorded_at: str
    correlation: CorrelationIds = field(default_factory=CorrelationIds)
    payload_classification: SensitivityClass = SensitivityClass.INTERNAL
    payload_digest: str = ""
    payload_preview: str = ""
    attempt_count: int = 1
    attributes: Mapping[str, Any] = field(default_factory=dict)
    sequence: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "letter_id", _require_id(self.letter_id, "letter_id")
        )
        object.__setattr__(self, "source", _require_id(self.source, "source"))
        object.__setattr__(self, "domain", _require_domain(self.domain))
        reason = redact_sensitive_text(str(self.reason or "").strip())
        if not reason:
            raise ObservabilityError("dead letter reason is required")
        if len(reason.encode("utf-8")) > MAX_ATTR_VALUE_BYTES:
            reason = reason.encode("utf-8")[:MAX_ATTR_VALUE_BYTES].decode(
                "utf-8", errors="ignore"
            )
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "recorded_at", _normalize_ts(self.recorded_at))
        object.__setattr__(
            self, "correlation", _require_correlation(self.correlation)
        )
        klass = _require_sensitivity(self.payload_classification)
        if klass is SensitivityClass.SECRET:
            raise ObservabilityError(
                "dead letter payloads must not be classified secret; "
                "store a content digest only"
            )
        object.__setattr__(self, "payload_classification", klass)
        preview = str(self.payload_preview or "")
        if klass is SensitivityClass.REDACTED:
            preview = redact_sensitive_text(preview)
        if len(preview.encode("utf-8")) > MAX_ATTR_VALUE_BYTES:
            preview = preview.encode("utf-8")[:MAX_ATTR_VALUE_BYTES].decode(
                "utf-8", errors="ignore"
            )
        object.__setattr__(self, "payload_preview", preview)
        dig = str(self.payload_digest or "").strip().lower()
        if dig:
            if not dig.startswith("sha256:") or len(dig) != len("sha256:") + 64:
                raise ObservabilityError("payload_digest must be sha256:<hex>")
        object.__setattr__(self, "payload_digest", dig)
        if (
            not isinstance(self.attempt_count, int)
            or isinstance(self.attempt_count, bool)
            or self.attempt_count < 1
        ):
            raise ObservabilityError("attempt_count must be a positive int")
        object.__setattr__(self, "attributes", _freeze_attrs(self.attributes))
        if (
            not isinstance(self.sequence, int)
            or isinstance(self.sequence, bool)
            or self.sequence < 0
        ):
            raise ObservabilityError("sequence must be a non-negative int")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": DEAD_LETTER_SCHEMA,
            "family": self.FAMILY.value,
            "letter_id": self.letter_id,
            "source": self.source,
            "domain": self.domain.value,
            "reason": self.reason,
            "recorded_at": self.recorded_at,
            "correlation": self.correlation.to_dict(),
            "payload_classification": self.payload_classification.value,
            "payload_digest": self.payload_digest,
            "payload_preview": self.payload_preview,
            "attempt_count": self.attempt_count,
            "attributes": dict(self.attributes),
            "sequence": self.sequence,
        }

    @property
    def identity_id(self) -> str:
        return content_identity(self.to_dict())


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """Append-only security / compliance audit event."""

    SCHEMA: ClassVar[str] = AUDIT_RECORD_SCHEMA
    FAMILY: ClassVar[CatalogFamily] = CatalogFamily.AUDIT_EVENTS

    event_id: str
    action: str
    actor: str
    outcome: str
    recorded_at: str
    correlation: CorrelationIds = field(default_factory=CorrelationIds)
    resource: str = ""
    domain: TraceDomain = TraceDomain.SYSTEM
    classification: SensitivityClass = SensitivityClass.INTERNAL
    detail: str = ""
    attributes: Mapping[str, Any] = field(default_factory=dict)
    sequence: int = 0

    def __post_init__(self) -> None:
        object.__setattr__(self, "event_id", _require_id(self.event_id, "event_id"))
        object.__setattr__(self, "action", _require_id(self.action, "action"))
        object.__setattr__(self, "actor", _require_id(self.actor, "actor"))
        outcome = str(self.outcome or "").strip().lower()
        if outcome not in {
            "allowed",
            "denied",
            "succeeded",
            "failed",
            "error",
            "info",
        }:
            raise ObservabilityError(
                "audit outcome must be allowed|denied|succeeded|failed|error|info"
            )
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(self, "recorded_at", _normalize_ts(self.recorded_at))
        object.__setattr__(
            self, "correlation", _require_correlation(self.correlation)
        )
        object.__setattr__(
            self, "resource", _optional_id(self.resource, "resource")
        )
        object.__setattr__(self, "domain", _require_domain(self.domain))
        klass = _require_sensitivity(self.classification)
        if klass is SensitivityClass.SECRET:
            raise ObservabilityError(
                "audit records cannot store secret classification plaintext"
            )
        object.__setattr__(self, "classification", klass)
        detail = str(self.detail or "")
        if klass is SensitivityClass.REDACTED:
            detail = redact_sensitive_text(detail)
        if len(detail.encode("utf-8")) > MAX_ATTR_VALUE_BYTES:
            detail = detail.encode("utf-8")[:MAX_ATTR_VALUE_BYTES].decode(
                "utf-8", errors="ignore"
            )
        object.__setattr__(self, "detail", detail)
        object.__setattr__(self, "attributes", _freeze_attrs(self.attributes))
        if (
            not isinstance(self.sequence, int)
            or isinstance(self.sequence, bool)
            or self.sequence < 0
        ):
            raise ObservabilityError("sequence must be a non-negative int")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": AUDIT_RECORD_SCHEMA,
            "family": self.FAMILY.value,
            "event_id": self.event_id,
            "action": self.action,
            "actor": self.actor,
            "outcome": self.outcome,
            "recorded_at": self.recorded_at,
            "correlation": self.correlation.to_dict(),
            "resource": self.resource,
            "domain": self.domain.value,
            "classification": self.classification.value,
            "detail": self.detail,
            "attributes": dict(self.attributes),
            "sequence": self.sequence,
        }

    @property
    def identity_id(self) -> str:
        return content_identity(self.to_dict())


ObservabilityRecord = (
    LifecycleEvent
    | TraceRecord
    | SpanRecord
    | HealthSample
    | QueryProfile
    | BlockerTransition
    | DeadLetter
    | AuditRecord
)

_FAMILY_TYPE: Final[dict[CatalogFamily, type]] = {
    CatalogFamily.LIFECYCLE_EVENTS: LifecycleEvent,
    CatalogFamily.TRACES: TraceRecord,
    CatalogFamily.SPANS: SpanRecord,
    CatalogFamily.HEALTH_SAMPLES: HealthSample,
    CatalogFamily.QUERY_PROFILES: QueryProfile,
    CatalogFamily.BLOCKER_TRANSITIONS: BlockerTransition,
    CatalogFamily.DEAD_LETTERS: DeadLetter,
    CatalogFamily.AUDIT_EVENTS: AuditRecord,
}


def _record_event_id(record: ObservabilityRecord) -> str:
    if isinstance(record, LifecycleEvent):
        return record.event_id
    if isinstance(record, TraceRecord):
        return record.trace_id
    if isinstance(record, SpanRecord):
        return record.span_id
    if isinstance(record, HealthSample):
        return record.sample_id
    if isinstance(record, QueryProfile):
        return record.profile_id
    if isinstance(record, BlockerTransition):
        return record.transition_id
    if isinstance(record, DeadLetter):
        return record.letter_id
    if isinstance(record, AuditRecord):
        return record.event_id
    raise ObservabilityError(f"unknown record type {type(record)!r}")


def _record_family(record: ObservabilityRecord) -> CatalogFamily:
    return record.FAMILY  # type: ignore[attr-defined]


def _record_correlation(record: ObservabilityRecord) -> CorrelationIds:
    return record.correlation  # type: ignore[attr-defined]


def _record_sequence(record: ObservabilityRecord) -> int:
    return int(record.sequence)  # type: ignore[attr-defined]


def _with_sequence(record: ObservabilityRecord, sequence: int) -> ObservabilityRecord:
    """Return a copy of ``record`` with ``sequence`` assigned (dataclasses)."""

    data = {slot: getattr(record, slot) for slot in record.__slots__}  # type: ignore[attr-defined]
    data["sequence"] = sequence
    return type(record)(**data)


# ---------------------------------------------------------------------------
# Backend
# ---------------------------------------------------------------------------


class ObservabilityBackend(Protocol):
    """Storage protocol for the append-only observability catalog."""

    def next_sequence(self) -> int:
        """Allocate and return the next global sequence number."""

    def append(self, family: CatalogFamily, record: ObservabilityRecord) -> None:
        """Persist an already-sequenced record. Must not mutate prior rows."""

    def list_family(
        self, family: CatalogFamily
    ) -> tuple[ObservabilityRecord, ...]:
        """Return all records for ``family`` in sequence order."""

    def get_by_event_id(
        self, family: CatalogFamily, event_id: str
    ) -> ObservabilityRecord | None:
        """Return a record by natural id within ``family``, if present."""

    def truncate_family(
        self,
        family: CatalogFamily,
        *,
        keep_from_sequence: int,
    ) -> int:
        """Drop records with sequence < keep_from_sequence; return removed count."""

    def highest_sequence(self) -> int:
        """Return the highest allocated sequence (0 if empty)."""


class MemoryObservabilityBackend:
    """Hermetic in-process backend for unit tests and local development."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._seq = 0
        self._rows: dict[CatalogFamily, list[ObservabilityRecord]] = {
            family: [] for family in CatalogFamily
        }
        self._ids: dict[CatalogFamily, dict[str, ObservabilityRecord]] = {
            family: {} for family in CatalogFamily
        }

    def next_sequence(self) -> int:
        with self._lock:
            self._seq += 1
            return self._seq

    def append(self, family: CatalogFamily, record: ObservabilityRecord) -> None:
        if not isinstance(family, CatalogFamily):
            raise ObservabilityError("family must be CatalogFamily")
        if not isinstance(record, _FAMILY_TYPE[family]):
            raise ObservabilityError(
                f"record type {type(record).__name__} does not match "
                f"family {family.value}"
            )
        event_id = _record_event_id(record)
        with self._lock:
            if event_id in self._ids[family]:
                raise ObservabilityError(
                    f"duplicate {family.value} id {event_id!r} "
                    "(append-only; updates are forbidden)"
                )
            self._rows[family].append(record)
            self._ids[family][event_id] = record

    def list_family(
        self, family: CatalogFamily
    ) -> tuple[ObservabilityRecord, ...]:
        with self._lock:
            return tuple(self._rows[family])

    def get_by_event_id(
        self, family: CatalogFamily, event_id: str
    ) -> ObservabilityRecord | None:
        with self._lock:
            return self._ids[family].get(event_id)

    def truncate_family(
        self,
        family: CatalogFamily,
        *,
        keep_from_sequence: int,
    ) -> int:
        with self._lock:
            rows = self._rows[family]
            kept = [
                row for row in rows if _record_sequence(row) >= keep_from_sequence
            ]
            removed = len(rows) - len(kept)
            self._rows[family] = kept
            self._ids[family] = {
                _record_event_id(row): row for row in kept
            }
            return removed

    def highest_sequence(self) -> int:
        with self._lock:
            return self._seq


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ObservabilityExport:
    """Deterministic, non-authoritative export of catalog records."""

    SCHEMA: ClassVar[str] = EXPORT_BUNDLE_SCHEMA

    export_id: str
    snapshot: SnapshotId
    families: tuple[str, ...]
    record_count: int
    content: ContentReference
    created_at: str
    progress: ProgressCursor
    non_authoritative: bool = True
    renderer_version: str = _IMPLEMENTATION_GENERATION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "export_id", _require_id(self.export_id, "export_id")
        )
        if not isinstance(self.snapshot, SnapshotId):
            raise ObservabilityError("snapshot must be SnapshotId")
        if not isinstance(self.content, ContentReference):
            raise ObservabilityError("content must be ContentReference")
        if not self.non_authoritative:
            raise ObservabilityError(
                "observability exports must declare non_authoritative=true"
            )
        object.__setattr__(self, "created_at", _normalize_ts(self.created_at))
        if not isinstance(self.progress, ProgressCursor):
            raise ObservabilityError("progress must be ProgressCursor")
        if self.progress.authority is ProgressAuthority.FILE_MTIME:
            raise ObservabilityError(
                "export progress cannot use file mtime authority"
            )
        families = tuple(str(f) for f in self.families)
        for name in families:
            if name not in CATALOG_FAMILIES:
                raise ObservabilityError(f"unknown family in export: {name!r}")
        object.__setattr__(self, "families", families)
        if (
            not isinstance(self.record_count, int)
            or isinstance(self.record_count, bool)
            or self.record_count < 0
        ):
            raise ObservabilityError("record_count must be non-negative")

    def to_export_receipt(self) -> ExportReceipt:
        return ExportReceipt(
            export_id=self.export_id,
            snapshot=self.snapshot,
            content=self.content,
            created_at=self.created_at,
            renderer_version=self.renderer_version,
            non_authoritative=True,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": EXPORT_BUNDLE_SCHEMA,
            "export_id": self.export_id,
            "snapshot": self.snapshot.to_dict(),
            "families": list(self.families),
            "record_count": self.record_count,
            "content": self.content.to_dict(),
            "created_at": self.created_at,
            "progress": self.progress.to_dict(),
            "non_authoritative": True,
            "renderer_version": self.renderer_version,
            "identity_id": self.identity_id,
        }

    @property
    def identity_id(self) -> str:
        return content_identity(
            {
                "export_id": self.export_id,
                "snapshot": self.snapshot.to_dict(),
                "families": list(self.families),
                "record_count": self.record_count,
                "content_identity_id": self.content.identity_id,
                "created_at": self.created_at,
                "progress": self.progress.to_dict(),
                "non_authoritative": True,
                "renderer_version": self.renderer_version,
            }
        )


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


class ObservabilityCatalog:
    """Typed append-only observability catalog with retention and export.

    All write paths assign a global sequence and refuse in-place mutation.
    Progress is always sequence/event-id based; file mtimes are rejected.
    """

    SCHEMA: ClassVar[str] = OBSERVABILITY_SCHEMA

    def __init__(
        self,
        backend: ObservabilityBackend | None = None,
        *,
        retention: RetentionPolicy | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self._backend: ObservabilityBackend = (
            backend if backend is not None else MemoryObservabilityBackend()
        )
        self._retention = retention or DEFAULT_RETENTION_POLICY
        if not isinstance(self._retention, RetentionPolicy):
            raise ObservabilityError("retention must be RetentionPolicy")
        self._clock = clock or _utc_now
        self._lock = threading.RLock()
        self._last_event_id_by_family: dict[CatalogFamily, str] = {}

    @property
    def retention(self) -> RetentionPolicy:
        return self._retention

    def progress(self) -> ProgressCursor:
        """Return the current progress cursor (sequence authority)."""

        with self._lock:
            seq = self._backend.highest_sequence()
            refuse_mtime_progress_authority(ProgressAuthority.SEQUENCE)
            return ProgressCursor(
                sequence=seq,
                recorded_at=self._clock(),
                authority=ProgressAuthority.SEQUENCE,
            )

    def _append(
        self,
        family: CatalogFamily,
        record: ObservabilityRecord,
        *,
        apply_retention: bool = True,
    ) -> ObservabilityRecord:
        with self._lock:
            sequence = self._backend.next_sequence()
            sequenced = _with_sequence(record, sequence)
            # Wire previous_event_id for lifecycle events when empty.
            if isinstance(sequenced, LifecycleEvent) and not sequenced.previous_event_id:
                prev = self._last_event_id_by_family.get(family, "")
                if prev:
                    data = {
                        slot: getattr(sequenced, slot)
                        for slot in sequenced.__slots__
                    }
                    data["previous_event_id"] = prev
                    sequenced = LifecycleEvent(**data)
            self._backend.append(family, sequenced)
            self._last_event_id_by_family[family] = _record_event_id(sequenced)
            if apply_retention:
                self._apply_retention_family(family, dry_run=False)
            return sequenced

    # -- writers -------------------------------------------------------------

    def record_lifecycle_event(
        self,
        *,
        event_type: str,
        component: str,
        domain: TraceDomain | str,
        event_id: str | None = None,
        correlation: CorrelationIds | Mapping[str, Any] | None = None,
        status: str = "ok",
        detail: str = "",
        attributes: Mapping[str, Any] | None = None,
        recorded_at: str | None = None,
    ) -> LifecycleEvent:
        record = LifecycleEvent(
            event_id=event_id or _new_id("life"),
            event_type=event_type,
            component=component,
            domain=_require_domain(domain),
            recorded_at=recorded_at or self._clock(),
            correlation=_require_correlation(correlation),
            status=status,
            detail=detail,
            attributes=attributes or {},
        )
        return self._append(CatalogFamily.LIFECYCLE_EVENTS, record)  # type: ignore[return-value]

    def start_trace(
        self,
        *,
        name: str,
        root_domain: TraceDomain | str,
        trace_id: str | None = None,
        correlation: CorrelationIds | Mapping[str, Any] | None = None,
        status: str = "started",
        attributes: Mapping[str, Any] | None = None,
        recorded_at: str | None = None,
    ) -> TraceRecord:
        corr = _require_correlation(correlation)
        # Prefer an explicit trace_id, then correlation.trace_id, then allocate.
        if trace_id:
            tid = _require_id(trace_id, "trace_id")
        elif corr.trace_id:
            tid = corr.trace_id
        else:
            tid = _new_id("trace")
        if not corr.trace_id:
            corr = CorrelationIds(
                trace_id=tid,
                span_id=corr.span_id,
                parent_span_id=corr.parent_span_id,
                control_task_id=corr.control_task_id,
                control_goal_id=corr.control_goal_id,
                query_receipt_id=corr.query_receipt_id,
                query_template_id=corr.query_template_id,
                proof_key_id=corr.proof_key_id,
                proof_entry_id=corr.proof_entry_id,
                graph_id=corr.graph_id,
                graph_revision_id=corr.graph_revision_id,
                vector_collection_id=corr.vector_collection_id,
                vector_generation_id=corr.vector_generation_id,
                ast_source_revision_id=corr.ast_source_revision_id,
                ast_blob_id=corr.ast_blob_id,
                wallet_chain_id=corr.wallet_chain_id,
                wallet_cursor_id=corr.wallet_cursor_id,
                tenant_id=corr.tenant_id,
                request_id=corr.request_id,
            )
        elif corr.trace_id != tid:
            raise ObservabilityError(
                f"correlation.trace_id {corr.trace_id!r} disagrees with "
                f"trace_id {tid!r}"
            )
        record = TraceRecord(
            trace_id=tid,
            root_domain=_require_domain(root_domain),
            name=name,
            recorded_at=recorded_at or self._clock(),
            correlation=corr,
            status=status,
            attributes=attributes or {},
        )
        return self._append(CatalogFamily.TRACES, record)  # type: ignore[return-value]

    def record_span(
        self,
        *,
        trace_id: str,
        name: str,
        domain: TraceDomain | str,
        span_id: str | None = None,
        parent_span_id: str = "",
        correlation: CorrelationIds | Mapping[str, Any] | None = None,
        status: str = "ok",
        duration_ms: int = 0,
        attributes: Mapping[str, Any] | None = None,
        recorded_at: str | None = None,
    ) -> SpanRecord:
        record = SpanRecord(
            span_id=span_id or _new_id("span"),
            trace_id=trace_id,
            name=name,
            domain=_require_domain(domain),
            recorded_at=recorded_at or self._clock(),
            parent_span_id=parent_span_id,
            correlation=_require_correlation(correlation),
            status=status,
            duration_ms=duration_ms,
            attributes=attributes or {},
        )
        return self._append(CatalogFamily.SPANS, record)  # type: ignore[return-value]

    def record_health_sample(
        self,
        *,
        component: str,
        domain: TraceDomain | str,
        status: str,
        sample_id: str | None = None,
        correlation: CorrelationIds | Mapping[str, Any] | None = None,
        latency_ms: int = 0,
        error_rate_bps: int = 0,
        attributes: Mapping[str, Any] | None = None,
        recorded_at: str | None = None,
    ) -> HealthSample:
        record = HealthSample(
            sample_id=sample_id or _new_id("health"),
            component=component,
            domain=_require_domain(domain),
            status=status,
            recorded_at=recorded_at or self._clock(),
            correlation=_require_correlation(correlation),
            latency_ms=latency_ms,
            error_rate_bps=error_rate_bps,
            attributes=attributes or {},
        )
        return self._append(CatalogFamily.HEALTH_SAMPLES, record)  # type: ignore[return-value]

    def record_query_profile(
        self,
        *,
        template_id: str,
        query_text: str | None = None,
        classification: SensitivityClass | str | None = None,
        profile_id: str | None = None,
        correlation: CorrelationIds | Mapping[str, Any] | None = None,
        status: str = "succeeded",
        duration_ms: int = 0,
        row_count: int = 0,
        byte_count: int = 0,
        snapshot_id: str = "",
        attributes: Mapping[str, Any] | None = None,
        recorded_at: str | None = None,
    ) -> QueryProfile:
        stored, klass, digest = classify_and_redact_query_text(
            query_text,
            classification=classification,
        )
        record = QueryProfile(
            profile_id=profile_id or _new_id("qprof"),
            template_id=template_id,
            recorded_at=recorded_at or self._clock(),
            query_text=stored,
            query_text_classification=klass,
            query_text_digest=digest,
            correlation=_require_correlation(correlation),
            status=status,
            duration_ms=duration_ms,
            row_count=row_count,
            byte_count=byte_count,
            snapshot_id=snapshot_id,
            attributes=attributes or {},
        )
        return self._append(CatalogFamily.QUERY_PROFILES, record)  # type: ignore[return-value]

    def record_blocker_transition(
        self,
        *,
        blocker_id: str,
        blocker_type: str,
        from_state: str,
        to_state: str,
        transition_id: str | None = None,
        correlation: CorrelationIds | Mapping[str, Any] | None = None,
        reason: str = "",
        attributes: Mapping[str, Any] | None = None,
        recorded_at: str | None = None,
    ) -> BlockerTransition:
        record = BlockerTransition(
            transition_id=transition_id or _new_id("block"),
            blocker_id=blocker_id,
            blocker_type=blocker_type,
            from_state=from_state,
            to_state=to_state,
            recorded_at=recorded_at or self._clock(),
            correlation=_require_correlation(correlation),
            reason=reason,
            attributes=attributes or {},
        )
        return self._append(CatalogFamily.BLOCKER_TRANSITIONS, record)  # type: ignore[return-value]

    def record_dead_letter(
        self,
        *,
        source: str,
        domain: TraceDomain | str,
        reason: str,
        letter_id: str | None = None,
        correlation: CorrelationIds | Mapping[str, Any] | None = None,
        payload: bytes | str | None = None,
        payload_classification: SensitivityClass | str = SensitivityClass.INTERNAL,
        payload_preview: str = "",
        attempt_count: int = 1,
        attributes: Mapping[str, Any] | None = None,
        recorded_at: str | None = None,
    ) -> DeadLetter:
        klass = _require_sensitivity(payload_classification)
        digest = ""
        preview = payload_preview
        if payload is not None:
            if isinstance(payload, str):
                raw = payload.encode("utf-8")
                if not preview:
                    preview = payload[:256]
            elif isinstance(payload, (bytes, bytearray)):
                raw = bytes(payload)
                if not preview:
                    preview = raw[:64].hex()
            else:
                raise ObservabilityError("payload must be bytes or text")
            digest = f"sha256:{_sha256_hex(raw)}"
            if klass is SensitivityClass.SECRET:
                raise ObservabilityError(
                    "dead letter secret payloads cannot be stored; "
                    "classify as redacted and pass digest-only"
                )
            if klass is SensitivityClass.REDACTED:
                preview = redact_sensitive_text(preview)
        record = DeadLetter(
            letter_id=letter_id or _new_id("dead"),
            source=source,
            domain=_require_domain(domain),
            reason=reason,
            recorded_at=recorded_at or self._clock(),
            correlation=_require_correlation(correlation),
            payload_classification=klass,
            payload_digest=digest,
            payload_preview=preview,
            attempt_count=attempt_count,
            attributes=attributes or {},
        )
        return self._append(CatalogFamily.DEAD_LETTERS, record)  # type: ignore[return-value]

    def record_audit(
        self,
        *,
        action: str,
        actor: str,
        outcome: str,
        event_id: str | None = None,
        correlation: CorrelationIds | Mapping[str, Any] | None = None,
        resource: str = "",
        domain: TraceDomain | str = TraceDomain.SYSTEM,
        classification: SensitivityClass | str = SensitivityClass.INTERNAL,
        detail: str = "",
        attributes: Mapping[str, Any] | None = None,
        recorded_at: str | None = None,
    ) -> AuditRecord:
        record = AuditRecord(
            event_id=event_id or _new_id("audit"),
            action=action,
            actor=actor,
            outcome=outcome,
            recorded_at=recorded_at or self._clock(),
            correlation=_require_correlation(correlation),
            resource=resource,
            domain=_require_domain(domain),
            classification=_require_sensitivity(classification),
            detail=detail,
            attributes=attributes or {},
        )
        return self._append(CatalogFamily.AUDIT_EVENTS, record)  # type: ignore[return-value]

    # -- readers -------------------------------------------------------------

    def list_family(
        self, family: CatalogFamily | str
    ) -> tuple[ObservabilityRecord, ...]:
        if isinstance(family, CatalogFamily):
            fam = family
        else:
            try:
                fam = CatalogFamily(str(family).strip())
            except ValueError as exc:
                raise ObservabilityError(
                    f"unknown catalog family {family!r}"
                ) from exc
        return self._backend.list_family(fam)

    def get(
        self, family: CatalogFamily | str, event_id: str
    ) -> ObservabilityRecord | None:
        if isinstance(family, CatalogFamily):
            fam = family
        else:
            fam = CatalogFamily(str(family).strip())
        return self._backend.get_by_event_id(fam, _require_id(event_id, "event_id"))

    def records_for_trace(self, trace_id: str) -> tuple[ObservabilityRecord, ...]:
        """Return all catalog records that share ``trace_id`` (all families)."""

        tid = _require_id(trace_id, "trace_id")
        found: list[ObservabilityRecord] = []
        for family in CatalogFamily:
            for record in self._backend.list_family(family):
                corr = _record_correlation(record)
                if corr.trace_id == tid:
                    found.append(record)
                elif isinstance(record, TraceRecord) and record.trace_id == tid:
                    found.append(record)
                elif isinstance(record, SpanRecord) and record.trace_id == tid:
                    found.append(record)
        found.sort(key=_record_sequence)
        return tuple(found)

    def correlate_by_domain_id(
        self,
        domain: TraceDomain | str,
        domain_id: str,
    ) -> tuple[ObservabilityRecord, ...]:
        """Find records whose correlation bundle binds ``domain``/``domain_id``."""

        dom = _require_domain(domain)
        did = _require_id(domain_id, "domain_id")
        found: list[ObservabilityRecord] = []
        for family in CatalogFamily:
            for record in self._backend.list_family(family):
                corr = _record_correlation(record)
                if corr.domain_id(dom) == did or (
                    dom is TraceDomain.CONTROL
                    and (
                        corr.control_task_id == did
                        or corr.control_goal_id == did
                    )
                ):
                    found.append(record)
                    continue
                # Direct field checks for non-primary aliases.
                field_map = {
                    TraceDomain.QUERY: (
                        corr.query_receipt_id,
                        corr.query_template_id,
                    ),
                    TraceDomain.PROOF: (corr.proof_key_id, corr.proof_entry_id),
                    TraceDomain.GRAPH: (corr.graph_revision_id, corr.graph_id),
                    TraceDomain.VECTOR: (
                        corr.vector_generation_id,
                        corr.vector_collection_id,
                    ),
                    TraceDomain.AST: (
                        corr.ast_source_revision_id,
                        corr.ast_blob_id,
                    ),
                    TraceDomain.WALLET: (
                        corr.wallet_cursor_id,
                        corr.wallet_chain_id,
                    ),
                }
                if dom in field_map and did in field_map[dom]:
                    if record not in found:
                        found.append(record)
        found.sort(key=_record_sequence)
        return tuple(found)

    def correlation_coverage(self, trace_id: str) -> frozenset[str]:
        """Return the set of required domains bound on any record for a trace."""

        bound: set[str] = set()
        for record in self.records_for_trace(trace_id):
            bound.update(_record_correlation(record).bound_domains())
            if isinstance(record, SpanRecord):
                if record.domain.value in REQUIRED_CORRELATION_DOMAINS:
                    # Span domain counts when it carries its own domain id or
                    # when the shared correlation already bound it above.
                    if _record_correlation(record).domain_id(record.domain):
                        bound.add(record.domain.value)
        return frozenset(bound)

    def counts(self) -> Mapping[str, int]:
        return MappingProxyType(
            {
                family.value: len(self._backend.list_family(family))
                for family in CatalogFamily
            }
        )

    # -- retention -----------------------------------------------------------

    def _apply_retention_family(
        self,
        family: CatalogFamily,
        *,
        dry_run: bool,
        now_epoch: float | None = None,
    ) -> RetentionReceipt:
        rows = list(self._backend.list_family(family))
        limit = self._retention.limit_for(family)
        remove_ids: set[int] = set()

        # Age-based eviction uses recorded_at (logical time), never mtime.
        if self._retention.max_age_seconds is not None:
            now = now_epoch if now_epoch is not None else time.time()
            cutoff = now - self._retention.max_age_seconds
            for row in rows:
                recorded = getattr(row, "recorded_at", "")
                try:
                    moment = datetime.fromisoformat(
                        str(recorded).replace("Z", "+00:00")
                    )
                    if moment.timestamp() < cutoff:
                        remove_ids.add(_record_sequence(row))
                except ValueError:
                    continue

        # Count-based: keep the newest ``limit`` rows by sequence.
        survivors = [
            row for row in rows if _record_sequence(row) not in remove_ids
        ]
        if len(survivors) > limit:
            survivors_sorted = sorted(survivors, key=_record_sequence)
            overflow = survivors_sorted[: len(survivors_sorted) - limit]
            for row in overflow:
                remove_ids.add(_record_sequence(row))

        removed_count = len(remove_ids)
        retained = len(rows) - removed_count
        max_removed = max(remove_ids) if remove_ids else 0
        policy_id = content_identity(self._retention.to_dict())

        if not dry_run and remove_ids:
            # Keep from the minimum sequence that should survive.
            keep_sequences = {
                _record_sequence(row)
                for row in rows
                if _record_sequence(row) not in remove_ids
            }
            if keep_sequences:
                # Selective drop: rebuild by truncating nothing then re-check.
                # Memory backend only supports truncate-by-floor; drop one by
                # one via truncate of everything then we need selective API.
                # Implement selective keep through truncate of prefix when
                # removals are a pure prefix; otherwise rebuild via internal API.
                self._selective_drop(family, remove_ids)
            else:
                # Everything removed.
                self._backend.truncate_family(family, keep_from_sequence=10**18)

        return RetentionReceipt(
            family=family.value,
            removed_count=removed_count,
            retained_count=max(retained, 0),
            max_sequence_removed=max_removed,
            applied_at=self._clock(),
            policy_identity=policy_id,
            dry_run=dry_run,
        )

    def _selective_drop(
        self, family: CatalogFamily, remove_sequences: set[int]
    ) -> None:
        """Drop specific sequences from a family (append-only exception: retention)."""

        backend = self._backend
        if isinstance(backend, MemoryObservabilityBackend):
            with backend._lock:  # noqa: SLF001 — retention path for hermetic backend
                rows = [
                    row
                    for row in backend._rows[family]
                    if _record_sequence(row) not in remove_sequences
                ]
                backend._rows[family] = rows
                backend._ids[family] = {
                    _record_event_id(row): row for row in rows
                }
            return
        # Generic path: if removals form a pure low-sequence prefix, truncate.
        rows = list(backend.list_family(family))
        sequences = sorted(_record_sequence(r) for r in rows)
        if not sequences:
            return
        # Find the first sequence not in remove set; require all lower removed.
        keep = [s for s in sequences if s not in remove_sequences]
        if not keep:
            backend.truncate_family(family, keep_from_sequence=sequences[-1] + 1)
            return
        floor = keep[0]
        prefix = [s for s in sequences if s < floor]
        if set(prefix) <= remove_sequences and not (
            remove_sequences - set(prefix)
        ):
            backend.truncate_family(family, keep_from_sequence=floor)
            return
        raise ObservabilityError(
            "backend cannot selectively drop non-prefix sequences; "
            "use MemoryObservabilityBackend or a prefix-aligned policy"
        )

    def apply_retention(
        self, *, dry_run: bool = False
    ) -> tuple[RetentionReceipt, ...]:
        """Apply configured retention to every catalog family."""

        with self._lock:
            return tuple(
                self._apply_retention_family(family, dry_run=dry_run)
                for family in CatalogFamily
            )

    # -- export --------------------------------------------------------------

    def export(
        self,
        *,
        snapshot: SnapshotId | str,
        families: Sequence[CatalogFamily | str] | None = None,
        export_id: str | None = None,
        max_records: int = MAX_EXPORT_RECORDS,
    ) -> ObservabilityExport:
        """Export selected families as a content-addressed, non-authoritative bundle."""

        if max_records < 1:
            raise ObservabilityError("max_records must be positive")
        if isinstance(snapshot, SnapshotId):
            snap = snapshot
        else:
            snap = SnapshotId(value=str(snapshot))

        if families is None:
            fam_list = list(CatalogFamily)
        else:
            fam_list = []
            for item in families:
                if isinstance(item, CatalogFamily):
                    fam_list.append(item)
                else:
                    fam_list.append(CatalogFamily(str(item).strip()))

        body: dict[str, Any] = {
            "schema": EXPORT_BUNDLE_SCHEMA,
            "snapshot": snap.to_dict(),
            "families": {},
        }
        total = 0
        for family in fam_list:
            rows = [
                r.to_dict()  # type: ignore[attr-defined]
                for r in self._backend.list_family(family)
            ]
            if total + len(rows) > max_records:
                rows = rows[: max(0, max_records - total)]
            body["families"][family.value] = rows
            total += len(rows)
            if total >= max_records:
                break

        raw = canonical_json_bytes(body)
        content = ContentReference.from_bytes(
            raw, media_type=ContentMediaType.JSON
        )
        # Bind exact bytes so export is tamper-evident.
        content.verify_bytes(raw)

        progress = self.progress()
        return ObservabilityExport(
            export_id=export_id or _new_id("export"),
            snapshot=snap,
            families=tuple(f.value for f in fam_list),
            record_count=total,
            content=content,
            created_at=self._clock(),
            progress=progress,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": OBSERVABILITY_SCHEMA,
            "implementation_generation": _IMPLEMENTATION_GENERATION,
            "counts": dict(self.counts()),
            "progress": self.progress().to_dict(),
            "retention": self._retention.to_dict(),
            "families": sorted(CATALOG_FAMILIES),
            "required_correlation_domains": sorted(REQUIRED_CORRELATION_DOMAINS),
        }


def open_memory_catalog(
    *,
    retention: RetentionPolicy | None = None,
    clock: Callable[[], str] | None = None,
) -> ObservabilityCatalog:
    """Open a hermetic in-memory observability catalog (no I/O)."""

    return ObservabilityCatalog(
        MemoryObservabilityBackend(),
        retention=retention,
        clock=clock,
    )
