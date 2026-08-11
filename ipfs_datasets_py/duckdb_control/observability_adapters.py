"""Route audit / log / alert producers through typed observability (DQK-077).

Producers continue writing to their legacy file sinks, which remain the
**explicitly selected shadow authority** (``AuthorityMode.SHADOW``).  The
typed :class:`~ipfs_datasets_py.duckdb_control.observability.ObservabilityCatalog`
receives a redacted, schema-bound projection of every mutable event so that:

* every record carries a typed schema, stable event ID, classification,
  source revision, and parity receipt;
* retries and restarts are idempotent (stable event IDs + operation keys);
* secrets and unrestricted SQL are redacted before persistence/publication;
* immutable evidence blobs stay content-addressed **outside** DuckDB.

Importing this module is inert: no DuckDB, network, or filesystem I/O until an
adapter is constructed and :meth:`ObservabilityShadowAdapter.emit` is called.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    ClassVar,
    Final,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
)

from ipfs_datasets_py.duckdb_control.authority_transition import (
    AuthorityMode,
    AuthorityTransitionPort,
    MemoryAuthorityBackend,
    ParityReceipt,
    build_authority_port,
    compute_payload_digest,
)
from ipfs_datasets_py.duckdb_control.contracts import (
    ContentMediaType,
    ContentReference,
    canonical_json_bytes,
    content_identity,
)
from ipfs_datasets_py.duckdb_control.observability import (
    AUDIT_RECORD_SCHEMA,
    LIFECYCLE_EVENT_SCHEMA,
    OBSERVABILITY_SCHEMA,
    AuditRecord,
    CatalogFamily,
    CorrelationIds,
    LifecycleEvent,
    ObservabilityCatalog,
    ObservabilityError,
    SensitivityClass,
    TraceDomain,
    classify_and_redact_query_text,
    open_memory_catalog,
    redact_sensitive_text,
)

__all__ = [
    "OBSERVABILITY_ADAPTER_SCHEMA",
    "OBSERVABILITY_DOMAIN",
    "SOURCE_REVISION",
    "ADAPTER_PRODUCERS",
    "EmitResult",
    "EvidenceBlob",
    "LegacyFileSink",
    "ObservabilityAdapterError",
    "ObservabilityShadowAdapter",
    "ProducerKind",
    "TypedEventEnvelope",
    "configure_global_adapter",
    "ensure_shadow_adapter",
    "get_global_adapter",
    "open_shadow_adapter",
    "reset_global_adapter",
    "stable_event_id",
]


# ---------------------------------------------------------------------------
# Schemas / constants
# ---------------------------------------------------------------------------

OBSERVABILITY_ADAPTER_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-observability-adapters@1"
)
OBSERVABILITY_DOMAIN: Final[str] = "observability"
SOURCE_REVISION: Final[str] = "dqk-077-lane1-attempt1-20260811"

# Bound large free-text fields before they reach the catalog attributes surface.
_MAX_DETAIL_CHARS: Final[int] = 512
_MAX_ATTR_SCALAR_CHARS: Final[int] = 256
_MAX_EVIDENCE_INLINE_BYTES: Final[int] = 4_096
_MAX_LEGACY_LINE_BYTES: Final[int] = 256 * 1024

# Unrestricted / multi-statement SQL patterns that must never persist raw.
_UNRESTRICTED_SQL_RE: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(?i)\b(DROP|TRUNCATE|ALTER)\s+(TABLE|DATABASE|SCHEMA)\b"),
    re.compile(r"(?i)\bGRANT\b.+\bTO\b"),
    re.compile(r"(?i);\s*(SELECT|INSERT|UPDATE|DELETE|DROP)\b"),
    re.compile(r"(?i)\bCOPY\s+.+\bFROM\b"),
    re.compile(r"(?i)\bATTACH\b.+\bAS\b"),
    re.compile(r"(?i)\bPRAGMA\b"),
    re.compile(r"(?i)\bLOAD\s+EXTENSION\b"),
)

_SECRET_KEY_RE: Final[re.Pattern[str]] = re.compile(
    r"(?i)^(password|passwd|pwd|secret|token|api[_-]?key|authorization|"
    r"private[_-]?key|mnemonic|seed|signing|access[_-]?token|"
    r"refresh[_-]?token|client[_-]?secret|bearer)$"
)

_SAFE_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,127}$"
)


class ObservabilityAdapterError(ValueError):
    """Fail-closed rejection from the observability shadow adapter."""


class ProducerKind(str, Enum):
    """Closed set of event producers integrated in DQK-077."""

    AUDIT_LOGGER = "audit.audit_logger"
    LOGIC_SECURITY_AUDIT = "logic.security.audit_log"
    STRUCTURED_LOGGING = "logic.observability.structured_logging"
    GRAPHRAG_AUDIT = "optimizers.graphrag.audit_logger"
    GRAPHRAG_PIPELINE = "optimizers.graphrag.pipeline_json_logger"
    OPTIMIZER_LOGGING_AUDIT = "optimizers.common.logging_audit"
    ALERT_MANAGER = "alerts.alert_manager"
    MCP_LOGGER = "mcp_server.logger"


ADAPTER_PRODUCERS: Final[frozenset[str]] = frozenset(
    kind.value for kind in ProducerKind
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_token(value: Any, *, field_name: str, default: str = "unknown") -> str:
    """Coerce free text into a catalog-safe identifier token."""

    if value is None:
        text = default
    else:
        text = str(value).strip()
    if not text:
        text = default
    # Replace whitespace and unsafe punctuation with underscores.
    cleaned = re.sub(r"[^A-Za-z0-9_.:/@+-]+", "_", text)
    cleaned = cleaned.strip("._") or default
    if len(cleaned) > 128:
        cleaned = cleaned[:128]
    if not cleaned[0].isalnum():
        cleaned = f"x{cleaned}"
    if _SAFE_TOKEN_RE.fullmatch(cleaned) is None:
        digest = _sha256_hex(text.encode("utf-8"))[:24]
        cleaned = f"{field_name}-{digest}"
    return cleaned


def stable_event_id(
    *,
    producer: str | ProducerKind,
    action: str,
    body: Mapping[str, Any] | None = None,
    seed: str | None = None,
) -> str:
    """Derive a stable, idempotent event ID for retries and restarts.

    When ``seed`` is provided it is used as the sole identity input (after
    sanitization).  Otherwise the ID is a digest of producer, action, and a
    canonical subset of the body so replaying the same logical event yields
    the same ID.
    """

    if seed:
        token = _safe_token(seed, field_name="evt")
        if token.startswith("evt-") or token.startswith("audit-"):
            return token[:128]
        return f"evt-{token}"[:128]

    producer_s = (
        producer.value if isinstance(producer, ProducerKind) else str(producer)
    )
    action_s = _safe_token(action, field_name="action")
    # Only stable, non-volatile fields participate in identity.
    identity_body: dict[str, Any] = {
        "producer": producer_s,
        "action": action_s,
        "source_revision": SOURCE_REVISION,
    }
    if body:
        for key in sorted(body.keys()):
            if key in {
                "timestamp",
                "recorded_at",
                "created_at",
                "hostname",
                "process_id",
                "duration_ms",
                "elapsed_ms",
            }:
                continue
            value = body[key]
            if isinstance(value, (str, int, float, bool)) or value is None:
                identity_body[key] = value
            elif isinstance(value, Mapping):
                # Nested scalars only.
                nested = {
                    str(k): v
                    for k, v in value.items()
                    if isinstance(v, (str, int, float, bool)) or v is None
                }
                identity_body[key] = nested
    digest = _sha256_hex(canonical_json_bytes(identity_body))[:32]
    return f"evt-{digest}"


def _looks_like_unrestricted_sql(text: str) -> bool:
    if not text or not isinstance(text, str):
        return False
    return any(p.search(text) for p in _UNRESTRICTED_SQL_RE)


def _classify_payload_text(text: str) -> SensitivityClass:
    """Classify free text; escalate when secrets or unrestricted SQL appear."""

    if not text:
        return SensitivityClass.INTERNAL
    stored, klass, _digest = classify_and_redact_query_text(text)
    del stored
    if _looks_like_unrestricted_sql(text):
        if klass in (SensitivityClass.PUBLIC, SensitivityClass.INTERNAL):
            return SensitivityClass.REDACTED
    return klass


def redact_event_payload(
    payload: Mapping[str, Any] | None,
    *,
    classification: SensitivityClass | str | None = None,
) -> tuple[dict[str, Any], SensitivityClass]:
    """Deep-redact secrets and unrestricted SQL from a JSON-like payload.

    Returns ``(redacted_dict, effective_classification)``.  SECRET plaintext is
    never retained — only markers and digests.
    """

    if classification is None:
        klass = SensitivityClass.INTERNAL
    elif isinstance(classification, SensitivityClass):
        klass = classification
    else:
        try:
            klass = SensitivityClass(str(classification).strip().lower())
        except ValueError as exc:
            raise ObservabilityAdapterError(
                f"invalid classification {classification!r}"
            ) from exc

    if klass is SensitivityClass.SECRET:
        raise ObservabilityAdapterError(
            "secret classification cannot persist plaintext; "
            "classify as redacted and supply digests only"
        )

    escalated = klass

    def _walk(value: Any, *, key_hint: str = "") -> Any:
        nonlocal escalated
        if value is None or isinstance(value, (bool, int)):
            return value
        if isinstance(value, float):
            if value != value or value in (float("inf"), float("-inf")):
                return None
            return value
        if isinstance(value, str):
            if _SECRET_KEY_RE.match(key_hint or ""):
                escalated = SensitivityClass.REDACTED
                return "***REDACTED***"
            if _looks_like_unrestricted_sql(value):
                escalated = SensitivityClass.REDACTED
                digest = f"sha256:{_sha256_hex(value.encode('utf-8'))}"
                return {
                    "redacted": True,
                    "reason": "unrestricted_sql",
                    "digest": digest,
                    "preview": "***REDACTED***",
                }
            stored, detected, digest = classify_and_redact_query_text(value)
            if detected is SensitivityClass.REDACTED:
                escalated = SensitivityClass.REDACTED
                return stored
            if detected is SensitivityClass.SECRET:
                escalated = SensitivityClass.REDACTED
                return {
                    "redacted": True,
                    "reason": "secret",
                    "digest": digest,
                    "preview": "***REDACTED***",
                }
            # Defense in depth: always scrub inline credential assignments.
            scrubbed = redact_sensitive_text(value)
            if scrubbed != value:
                escalated = SensitivityClass.REDACTED
            if len(scrubbed) > _MAX_DETAIL_CHARS:
                scrubbed = scrubbed[:_MAX_DETAIL_CHARS]
            return scrubbed
        if isinstance(value, Mapping):
            return {
                str(k): _walk(v, key_hint=str(k)) for k, v in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [_walk(item, key_hint=key_hint) for item in value]
        # Non-JSON types → string form then redact.
        return _walk(str(value), key_hint=key_hint)

    redacted = _walk(dict(payload or {}))
    if not isinstance(redacted, dict):
        redacted = {"value": redacted}
    if escalated is SensitivityClass.SECRET:
        escalated = SensitivityClass.REDACTED
    return redacted, escalated


def _scalar_attrs(
    payload: Mapping[str, Any],
    *,
    max_keys: int = 32,
) -> dict[str, Any]:
    """Flatten payload to catalog-safe scalar attributes."""

    attrs: dict[str, Any] = {}
    for key in sorted(payload.keys()):
        if len(attrs) >= max_keys:
            break
        name = _safe_token(key, field_name="attr")
        value = payload[key]
        if isinstance(value, bool) or value is None:
            attrs[name] = value
        elif isinstance(value, int) and not isinstance(value, bool):
            attrs[name] = value
        elif isinstance(value, float):
            if value == value and value not in (float("inf"), float("-inf")):
                attrs[name] = value
        elif isinstance(value, str):
            text = value if len(value) <= _MAX_ATTR_SCALAR_CHARS else value[:_MAX_ATTR_SCALAR_CHARS]
            attrs[name] = text
        elif isinstance(value, Mapping):
            # Nesting not allowed in catalog attrs — store digest only.
            attrs[name] = f"sha256:{_sha256_hex(canonical_json_bytes(dict(value)))[:16]}"
        # lists / other types skipped
    return attrs


# ---------------------------------------------------------------------------
# Typed envelope / emit result
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TypedEventEnvelope:
    """Schema-bound mutable event before dual-write / catalog projection."""

    SCHEMA: ClassVar[str] = OBSERVABILITY_ADAPTER_SCHEMA

    event_id: str
    producer: str
    action: str
    classification: SensitivityClass
    source_revision: str
    recorded_at: str
    actor: str = "system"
    outcome: str = "info"
    resource: str = ""
    domain: TraceDomain = TraceDomain.OBSERVABILITY
    detail: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    evidence_cid: str = ""
    correlation: CorrelationIds = field(default_factory=CorrelationIds)
    family: CatalogFamily = CatalogFamily.AUDIT_EVENTS

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "event_id", _safe_token(self.event_id, field_name="evt")
        )
        producer = (
            self.producer.value
            if isinstance(self.producer, ProducerKind)
            else str(self.producer)
        )
        if producer not in ADAPTER_PRODUCERS:
            # Allow extension producers in tests while preferring closed set.
            producer = _safe_token(producer, field_name="producer")
        object.__setattr__(self, "producer", producer)
        object.__setattr__(
            self, "action", _safe_token(self.action, field_name="action")
        )
        object.__setattr__(
            self, "actor", _safe_token(self.actor, field_name="actor", default="system")
        )
        object.__setattr__(
            self,
            "resource",
            _safe_token(self.resource, field_name="resource", default="")
            if self.resource
            else "",
        )
        if not self.source_revision:
            object.__setattr__(self, "source_revision", SOURCE_REVISION)
        if not self.recorded_at:
            object.__setattr__(self, "recorded_at", _utc_now())
        if isinstance(self.classification, str):
            object.__setattr__(
                self,
                "classification",
                SensitivityClass(self.classification.strip().lower()),
            )
        if self.classification is SensitivityClass.SECRET:
            raise ObservabilityAdapterError(
                "envelope classification cannot be secret with plaintext payload"
            )
        outcome = str(self.outcome or "info").strip().lower()
        if outcome not in {
            "allowed",
            "denied",
            "succeeded",
            "failed",
            "error",
            "info",
        }:
            # Map common producer statuses.
            mapping = {
                "success": "succeeded",
                "ok": "succeeded",
                "failure": "failed",
                "fail": "failed",
                "triggered": "info",
                "warning": "info",
                "critical": "failed",
            }
            outcome = mapping.get(outcome, "info")
        object.__setattr__(self, "outcome", outcome)
        if not isinstance(self.payload, Mapping):
            raise ObservabilityAdapterError("payload must be a mapping")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
        if isinstance(self.domain, str):
            object.__setattr__(self, "domain", TraceDomain(self.domain))
        if isinstance(self.family, str):
            object.__setattr__(self, "family", CatalogFamily(self.family))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "event_id": self.event_id,
            "producer": self.producer,
            "action": self.action,
            "classification": self.classification.value,
            "source_revision": self.source_revision,
            "recorded_at": self.recorded_at,
            "actor": self.actor,
            "outcome": self.outcome,
            "resource": self.resource,
            "domain": self.domain.value,
            "detail": self.detail,
            "payload": dict(self.payload),
            "evidence_cid": self.evidence_cid,
            "family": self.family.value,
            "correlation": self.correlation.to_dict()
            if hasattr(self.correlation, "to_dict")
            else {},
        }

    @property
    def identity_id(self) -> str:
        return content_identity(self.to_dict())


@dataclass(frozen=True, slots=True)
class EvidenceBlob:
    """Content-addressed immutable evidence stored outside DuckDB."""

    SCHEMA: ClassVar[str] = (
        "ipfs_datasets_py/duckdb-control-observability-evidence@1"
    )

    cid: str
    media_type: ContentMediaType
    size_bytes: int
    digest: str
    stored_outside_duckdb: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "cid": self.cid,
            "media_type": self.media_type.value,
            "size_bytes": self.size_bytes,
            "digest": self.digest,
            "stored_outside_duckdb": True,
        }

    def to_content_reference(self) -> ContentReference:
        return ContentReference(
            media_type=self.media_type,
            content_id=self.digest,
            byte_size=self.size_bytes,
            source_digest=self.digest,
        )


@dataclass(frozen=True, slots=True)
class EmitResult:
    """Receipt returned after a successful (or idempotent) emit."""

    SCHEMA: ClassVar[str] = (
        "ipfs_datasets_py/duckdb-control-observability-emit-result@1"
    )

    event_id: str
    schema: str
    classification: str
    source_revision: str
    parity_receipt_cid: str
    catalog_sequence: int
    authority_mode: str
    producer: str
    action: str
    outcome: str
    idempotent_replay: bool = False
    evidence_cid: str = ""
    legacy_digest: str = ""
    catalog_digest: str = ""
    family: str = CatalogFamily.AUDIT_EVENTS.value
    matched: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.SCHEMA,
            "event_id": self.event_id,
            "record_schema": self.schema,
            "classification": self.classification,
            "source_revision": self.source_revision,
            "parity_receipt_cid": self.parity_receipt_cid,
            "catalog_sequence": self.catalog_sequence,
            "authority_mode": self.authority_mode,
            "producer": self.producer,
            "action": self.action,
            "outcome": self.outcome,
            "idempotent_replay": self.idempotent_replay,
            "evidence_cid": self.evidence_cid,
            "legacy_digest": self.legacy_digest,
            "catalog_digest": self.catalog_digest,
            "family": self.family,
            "matched": self.matched,
        }


# ---------------------------------------------------------------------------
# Legacy file sink (explicit shadow authority)
# ---------------------------------------------------------------------------


class LegacyFileSink:
    """JSONL file sink retained as the shadow-mode authority surface.

    Authority during DQK-077 remains on these files; the DuckDB / catalog path
    is a projection.  Construction is the only place a path is selected —
    producers never invent undeclared sinks through this adapter.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        enabled: bool = True,
        memory_only: bool = False,
    ) -> None:
        self.enabled = bool(enabled)
        self.memory_only = bool(memory_only) or path is None
        self.path: Path | None = None if self.memory_only else Path(path)  # type: ignore[arg-type]
        self._lock = threading.RLock()
        self._lines: list[str] = []
        self._digests: dict[str, str] = {}

    def write(self, envelope: TypedEventEnvelope) -> str:
        """Append one redacted envelope line; return sha256 digest of the line."""

        if not self.enabled:
            # Still compute digest for parity even when writes are suppressed.
            line = canonical_json_bytes(envelope.to_dict())
            digest = f"sha256:{_sha256_hex(line)}"
            with self._lock:
                self._digests[envelope.event_id] = digest
            return digest

        body = envelope.to_dict()
        raw = canonical_json_bytes(body)
        if len(raw) > _MAX_LEGACY_LINE_BYTES:
            raise ObservabilityAdapterError(
                f"legacy line exceeds {_MAX_LEGACY_LINE_BYTES}-byte bound"
            )
        digest = f"sha256:{_sha256_hex(raw)}"
        text = raw.decode("utf-8")
        with self._lock:
            # Idempotent: same event_id keeps first line.
            if envelope.event_id in self._digests:
                return self._digests[envelope.event_id]
            self._lines.append(text)
            self._digests[envelope.event_id] = digest
            if not self.memory_only and self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with open(self.path, "a", encoding="utf-8") as handle:
                    handle.write(text)
                    handle.write("\n")
        return digest

    def get_digest(self, event_id: str) -> str | None:
        with self._lock:
            return self._digests.get(event_id)

    def lines(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._lines)

    def count(self) -> int:
        with self._lock:
            return len(self._lines)


# ---------------------------------------------------------------------------
# Content-addressed evidence store (outside DuckDB)
# ---------------------------------------------------------------------------


class _EvidenceStore:
    """In-process content-addressed blob store (never DuckDB-backed)."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._blobs: dict[str, bytes] = {}
        self._meta: dict[str, EvidenceBlob] = {}

    def put(
        self,
        data: bytes | str | Mapping[str, Any],
        *,
        media_type: ContentMediaType = ContentMediaType.JSON,
    ) -> EvidenceBlob:
        if isinstance(data, Mapping):
            raw = canonical_json_bytes(dict(data))
            media_type = ContentMediaType.JSON
        elif isinstance(data, str):
            raw = data.encode("utf-8")
        elif isinstance(data, (bytes, bytearray)):
            raw = bytes(data)
        else:
            raise ObservabilityAdapterError("evidence data must be bytes/text/mapping")
        digest = f"sha256:{_sha256_hex(raw)}"
        # CIDv1-like content identity: use content_identity over a fixed body.
        cid = content_identity(
            {
                "schema": "ipfs_datasets_py/duckdb-control-observability-evidence-body@1",
                "digest": digest,
                "size_bytes": len(raw),
                "media_type": media_type.value,
            }
        )
        blob = EvidenceBlob(
            cid=cid,
            media_type=media_type,
            size_bytes=len(raw),
            digest=digest,
            stored_outside_duckdb=True,
        )
        with self._lock:
            self._blobs[cid] = raw
            self._meta[cid] = blob
        return blob

    def get(self, cid: str) -> bytes | None:
        with self._lock:
            return self._blobs.get(cid)

    def meta(self, cid: str) -> EvidenceBlob | None:
        with self._lock:
            return self._meta.get(cid)

    def __contains__(self, cid: str) -> bool:
        with self._lock:
            return cid in self._blobs


# ---------------------------------------------------------------------------
# Shadow adapter
# ---------------------------------------------------------------------------


class ObservabilityShadowAdapter:
    """Dual-path router: legacy file authority + typed catalog projection.

    Default mode is :attr:`AuthorityMode.SHADOW` so legacy sinks remain the
    selected authority while the observability catalog and authority-port DB
    surface receive shadow projections with parity receipts.
    """

    SCHEMA: ClassVar[str] = OBSERVABILITY_ADAPTER_SCHEMA
    DOMAIN: ClassVar[str] = OBSERVABILITY_DOMAIN
    SOURCE_REVISION: ClassVar[str] = SOURCE_REVISION

    def __init__(
        self,
        *,
        catalog: ObservabilityCatalog | None = None,
        authority: AuthorityTransitionPort | None = None,
        authority_backend: MemoryAuthorityBackend | None = None,
        legacy_sink: LegacyFileSink | None = None,
        mode: AuthorityMode | str = AuthorityMode.SHADOW,
        clock: Callable[[], str] | None = None,
        evidence_store: _EvidenceStore | None = None,
    ) -> None:
        self._clock = clock or _utc_now
        self._lock = threading.RLock()
        self._catalog = catalog or open_memory_catalog(clock=self._clock)
        self._authority_backend = authority_backend or MemoryAuthorityBackend()
        initial_mode = (
            mode
            if isinstance(mode, AuthorityMode)
            else AuthorityMode.parse(str(mode))
        )
        if initial_mode not in {
            AuthorityMode.LEGACY,
            AuthorityMode.SHADOW,
            AuthorityMode.DUAL,
        }:
            # DQK-077 is the shadow-integration step; cutover modes are DQK-078+.
            raise ObservabilityAdapterError(
                f"observability adapters only admit legacy|shadow|dual during "
                f"DQK-077; got {initial_mode.value!r}"
            )
        self._authority = authority or build_authority_port(
            self._authority_backend,
            domain=self.DOMAIN,
            initial_mode=initial_mode,
        )
        self._legacy = legacy_sink or LegacyFileSink(memory_only=True)
        self._evidence = evidence_store or _EvidenceStore()
        # event_id -> EmitResult for restart-safe idempotency without catalog dup.
        self._emitted: dict[str, EmitResult] = {}

    # -- public accessors ---------------------------------------------------

    @property
    def catalog(self) -> ObservabilityCatalog:
        return self._catalog

    @property
    def authority(self) -> AuthorityTransitionPort:
        return self._authority

    @property
    def legacy_sink(self) -> LegacyFileSink:
        return self._legacy

    @property
    def evidence_store(self) -> _EvidenceStore:
        return self._evidence

    @property
    def mode(self) -> AuthorityMode:
        return self._authority.state().mode

    @property
    def source_revision(self) -> str:
        return self.SOURCE_REVISION

    # -- emit ---------------------------------------------------------------

    def emit(
        self,
        *,
        producer: str | ProducerKind,
        action: str,
        payload: Mapping[str, Any] | None = None,
        event_id: str | None = None,
        actor: str = "system",
        outcome: str = "info",
        resource: str = "",
        domain: TraceDomain | str = TraceDomain.OBSERVABILITY,
        classification: SensitivityClass | str | None = None,
        detail: str = "",
        correlation: CorrelationIds | Mapping[str, Any] | None = None,
        family: CatalogFamily | str = CatalogFamily.AUDIT_EVENTS,
        evidence: bytes | str | Mapping[str, Any] | None = None,
        seed: str | None = None,
        recorded_at: str | None = None,
    ) -> EmitResult:
        """Emit one typed event through legacy authority + catalog shadow.

        Retries with the same ``event_id`` (or the same stable seed/body) return
        the prior :class:`EmitResult` without duplicating catalog rows.
        """

        producer_s = (
            producer.value if isinstance(producer, ProducerKind) else str(producer)
        )
        raw_payload = dict(payload or {})
        redacted_payload, effective_class = redact_event_payload(
            raw_payload, classification=classification
        )
        detail_text = detail or ""
        if detail_text:
            detail_redacted, detail_class = redact_event_payload(
                {"detail": detail_text}, classification=effective_class
            )
            detail_value = detail_redacted.get("detail", "")
            if isinstance(detail_value, str):
                detail_text = detail_value
            else:
                detail_text = "***REDACTED***"
            if detail_class is SensitivityClass.REDACTED:
                effective_class = SensitivityClass.REDACTED

        eid = event_id or stable_event_id(
            producer=producer_s,
            action=action,
            body=redacted_payload,
            seed=seed,
        )
        eid = _safe_token(eid, field_name="evt")

        with self._lock:
            prior = self._emitted.get(eid)
            if prior is not None:
                return EmitResult(
                    event_id=prior.event_id,
                    schema=prior.schema,
                    classification=prior.classification,
                    source_revision=prior.source_revision,
                    parity_receipt_cid=prior.parity_receipt_cid,
                    catalog_sequence=prior.catalog_sequence,
                    authority_mode=prior.authority_mode,
                    producer=prior.producer,
                    action=prior.action,
                    outcome=prior.outcome,
                    idempotent_replay=True,
                    evidence_cid=prior.evidence_cid,
                    legacy_digest=prior.legacy_digest,
                    catalog_digest=prior.catalog_digest,
                    family=prior.family,
                    matched=prior.matched,
                )

            # Catalog-level duplicate protection (restart after process death
            # that lost _emitted but retained the catalog backend).
            existing = self._catalog.get(CatalogFamily.AUDIT_EVENTS, eid)
            if existing is None and family != CatalogFamily.AUDIT_EVENTS:
                try:
                    fam = (
                        family
                        if isinstance(family, CatalogFamily)
                        else CatalogFamily(str(family))
                    )
                except ValueError:
                    fam = CatalogFamily.AUDIT_EVENTS
                existing = self._catalog.get(fam, eid)
            if existing is not None:
                result = EmitResult(
                    event_id=eid,
                    schema=getattr(existing, "SCHEMA", AUDIT_RECORD_SCHEMA),
                    classification=effective_class.value,
                    source_revision=self.SOURCE_REVISION,
                    parity_receipt_cid="",
                    catalog_sequence=int(getattr(existing, "sequence", 0)),
                    authority_mode=self.mode.value,
                    producer=producer_s,
                    action=_safe_token(action, field_name="action"),
                    outcome=str(getattr(existing, "outcome", outcome)),
                    idempotent_replay=True,
                    family=str(
                        getattr(
                            getattr(existing, "FAMILY", None),
                            "value",
                            CatalogFamily.AUDIT_EVENTS.value,
                        )
                    ),
                    matched=True,
                )
                self._emitted[eid] = result
                return result

            evidence_cid = ""
            if evidence is not None:
                blob = self._evidence.put(evidence)
                evidence_cid = blob.cid
                redacted_payload = dict(redacted_payload)
                redacted_payload["evidence_cid"] = evidence_cid
                redacted_payload["evidence_outside_duckdb"] = True
            elif self._payload_needs_external_evidence(redacted_payload):
                blob = self._evidence.put(redacted_payload)
                evidence_cid = blob.cid
                # Replace heavy body with digest reference in the dual-write payload.
                redacted_payload = {
                    "evidence_cid": evidence_cid,
                    "evidence_outside_duckdb": True,
                    "evidence_digest": blob.digest,
                    "producer": producer_s,
                    "action": _safe_token(action, field_name="action"),
                }

            corr = self._coerce_correlation(correlation, event_id=eid)

            envelope = TypedEventEnvelope(
                event_id=eid,
                producer=producer_s,
                action=action,
                classification=effective_class,
                source_revision=self.SOURCE_REVISION,
                recorded_at=recorded_at or self._clock(),
                actor=actor,
                outcome=outcome,
                resource=resource,
                domain=domain
                if isinstance(domain, TraceDomain)
                else TraceDomain(str(domain)),
                detail=detail_text[:_MAX_DETAIL_CHARS],
                payload=redacted_payload,
                evidence_cid=evidence_cid,
                correlation=corr,
                family=family
                if isinstance(family, CatalogFamily)
                else CatalogFamily(str(family)),
            )

            # 1) Legacy file sink — explicit shadow authority.
            legacy_digest = self._legacy.write(envelope)

            # 2) Authority port dual-write (legacy KV + DB projection + outbox).
            authority_payload = envelope.to_dict()
            write_result = self._authority.write(
                envelope.event_id,
                authority_payload,
                operation_id=envelope.event_id,
            )
            if write_result.get("idempotent_replay"):
                # Race with concurrent emit of same operation_id.
                prior = self._emitted.get(eid)
                if prior is not None:
                    return EmitResult(
                        event_id=prior.event_id,
                        schema=prior.schema,
                        classification=prior.classification,
                        source_revision=prior.source_revision,
                        parity_receipt_cid=prior.parity_receipt_cid,
                        catalog_sequence=prior.catalog_sequence,
                        authority_mode=prior.authority_mode,
                        producer=prior.producer,
                        action=prior.action,
                        outcome=prior.outcome,
                        idempotent_replay=True,
                        evidence_cid=prior.evidence_cid,
                        legacy_digest=prior.legacy_digest,
                        catalog_digest=prior.catalog_digest,
                        family=prior.family,
                        matched=prior.matched,
                    )

            # 3) Typed catalog projection.
            catalog_record = self._project_to_catalog(envelope)
            catalog_digest = f"sha256:{_sha256_hex(canonical_json_bytes(catalog_record.to_dict()))}"

            # 4) Parity receipt (legacy authority vs DB projection).
            parity = self._authority.emit_parity_receipt(
                envelope.event_id, operation_id=envelope.event_id
            )

            result = EmitResult(
                event_id=envelope.event_id,
                schema=catalog_record.SCHEMA,
                classification=envelope.classification.value,
                source_revision=envelope.source_revision,
                parity_receipt_cid=parity.receipt_cid,
                catalog_sequence=int(catalog_record.sequence),
                authority_mode=self.mode.value,
                producer=envelope.producer,
                action=envelope.action,
                outcome=envelope.outcome,
                idempotent_replay=False,
                evidence_cid=evidence_cid,
                legacy_digest=legacy_digest,
                catalog_digest=catalog_digest,
                family=envelope.family.value,
                matched=bool(parity.matched),
            )
            self._emitted[eid] = result
            return result

    # -- producer-specific convenience APIs ---------------------------------

    def emit_audit_event(
        self,
        *,
        action: str,
        actor: str = "system",
        outcome: str = "info",
        details: Mapping[str, Any] | None = None,
        event_id: str | None = None,
        resource: str = "",
        level: str = "INFO",
        category: str = "OPERATIONAL",
        producer: ProducerKind = ProducerKind.AUDIT_LOGGER,
        **extra: Any,
    ) -> EmitResult:
        payload = {
            "level": level,
            "category": category,
            **dict(details or {}),
            **extra,
        }
        return self.emit(
            producer=producer,
            action=action,
            payload=payload,
            event_id=event_id,
            actor=actor,
            outcome=outcome,
            resource=resource,
            domain=TraceDomain.SYSTEM,
            family=CatalogFamily.AUDIT_EVENTS,
        )

    def emit_security_event(
        self,
        *,
        event_type: str,
        user_id: str,
        success: bool,
        details: Mapping[str, Any] | None = None,
        event_id: str | None = None,
        seed: str | None = None,
        **extra: Any,
    ) -> EmitResult:
        payload = {
            "event_type": event_type,
            "success": success,
            **dict(details or {}),
            **extra,
        }
        return self.emit(
            producer=ProducerKind.LOGIC_SECURITY_AUDIT,
            action=event_type,
            payload=payload,
            event_id=event_id,
            seed=seed,
            actor=user_id or "system",
            outcome="succeeded" if success else "failed",
            domain=TraceDomain.PROOF,
            family=CatalogFamily.AUDIT_EVENTS,
        )

    def emit_structured_log(
        self,
        *,
        event_type: str,
        message: str = "",
        level: str = "INFO",
        fields: Mapping[str, Any] | None = None,
        event_id: str | None = None,
        seed: str | None = None,
        **extra: Any,
    ) -> EmitResult:
        payload = {
            "message": message,
            "level": level,
            **dict(fields or {}),
            **extra,
        }
        return self.emit(
            producer=ProducerKind.STRUCTURED_LOGGING,
            action=event_type,
            payload=payload,
            event_id=event_id,
            seed=seed,
            detail=message,
            domain=TraceDomain.OBSERVABILITY,
            family=CatalogFamily.LIFECYCLE_EVENTS
            if str(event_type).startswith(("system.", "component."))
            else CatalogFamily.AUDIT_EVENTS,
        )

    def emit_graphrag_audit(
        self,
        *,
        event_type: str,
        session_id: str = "",
        round_num: int = 0,
        event_data: Mapping[str, Any] | None = None,
        event_id: str | None = None,
        **extra: Any,
    ) -> EmitResult:
        payload = {
            "session_id": session_id,
            "round_num": round_num,
            **dict(event_data or {}),
            **extra,
        }
        seed = event_id or (
            f"{session_id}:{event_type}:{round_num}" if session_id else None
        )
        return self.emit(
            producer=ProducerKind.GRAPHRAG_AUDIT,
            action=event_type,
            payload=payload,
            event_id=event_id,
            seed=seed,
            actor=session_id or "graphrag",
            domain=TraceDomain.GRAPH,
            family=CatalogFamily.AUDIT_EVENTS,
            correlation=CorrelationIds(
                graph_id=_safe_token(session_id, field_name="graph")
                if session_id
                else "",
            ),
        )

    def emit_pipeline_log(
        self,
        *,
        event_type: str,
        domain: str = "graphrag",
        run_id: str = "",
        data: Mapping[str, Any] | None = None,
        event_id: str | None = None,
        **extra: Any,
    ) -> EmitResult:
        payload = {
            "pipeline_domain": domain,
            "run_id": run_id,
            **dict(data or {}),
            **extra,
        }
        seed = event_id or (f"{run_id}:{event_type}" if run_id else None)
        return self.emit(
            producer=ProducerKind.GRAPHRAG_PIPELINE,
            action=event_type,
            payload=payload,
            event_id=event_id,
            seed=seed,
            actor=run_id or "pipeline",
            domain=TraceDomain.GRAPH,
            family=CatalogFamily.LIFECYCLE_EVENTS,
        )

    def emit_logging_audit_report(
        self,
        *,
        report_summary: Mapping[str, Any],
        event_id: str | None = None,
        seed: str | None = None,
        **extra: Any,
    ) -> EmitResult:
        payload = {**dict(report_summary), **extra}
        return self.emit(
            producer=ProducerKind.OPTIMIZER_LOGGING_AUDIT,
            action="logging_audit.report",
            payload=payload,
            event_id=event_id,
            seed=seed,
            domain=TraceDomain.OBSERVABILITY,
            family=CatalogFamily.AUDIT_EVENTS,
            # Full report body is evidence outside DuckDB when large.
            evidence=dict(report_summary)
            if len(canonical_json_bytes(dict(report_summary)))
            > _MAX_EVIDENCE_INLINE_BYTES
            else None,
        )

    def emit_alert(
        self,
        *,
        rule_id: str,
        rule_name: str = "",
        severity: str = "info",
        status: str = "triggered",
        message: str = "",
        event_payload: Mapping[str, Any] | None = None,
        event_id: str | None = None,
        seed: str | None = None,
        **extra: Any,
    ) -> EmitResult:
        payload = {
            "rule_id": rule_id,
            "rule_name": rule_name,
            "severity": severity,
            "status": status,
            "message": message,
            **dict(event_payload or {}),
            **extra,
        }
        outcome = "info"
        if severity == "critical" or status == "error":
            outcome = "failed"
        resolved_seed = seed or event_id or f"alert:{rule_id}:{status}"
        return self.emit(
            producer=ProducerKind.ALERT_MANAGER,
            action=f"alert.{status}",
            payload=payload,
            event_id=event_id,
            seed=resolved_seed,
            actor=_safe_token(rule_id, field_name="rule"),
            outcome=outcome,
            resource=_safe_token(rule_id, field_name="rule"),
            domain=TraceDomain.SYSTEM,
            family=CatalogFamily.AUDIT_EVENTS,
            detail=message,
        )

    def emit_mcp_log(
        self,
        *,
        message: str,
        level: str = "INFO",
        logger_name: str = "ipfs_datasets.mcp_server",
        event_id: str | None = None,
        seed: str | None = None,
        **extra: Any,
    ) -> EmitResult:
        payload = {
            "message": message,
            "level": level,
            "logger_name": logger_name,
            **extra,
        }
        return self.emit(
            producer=ProducerKind.MCP_LOGGER,
            action=f"mcp.log.{level.lower()}",
            payload=payload,
            event_id=event_id,
            seed=seed,
            detail=message,
            domain=TraceDomain.CONTROL,
            family=CatalogFamily.AUDIT_EVENTS,
        )

    # -- internals ----------------------------------------------------------

    def _payload_needs_external_evidence(self, payload: Mapping[str, Any]) -> bool:
        try:
            return len(canonical_json_bytes(dict(payload))) > _MAX_EVIDENCE_INLINE_BYTES
        except Exception:
            return True

    def _coerce_correlation(
        self,
        correlation: CorrelationIds | Mapping[str, Any] | None,
        *,
        event_id: str,
    ) -> CorrelationIds:
        if correlation is None:
            return CorrelationIds(trace_id=event_id, request_id=event_id)
        if isinstance(correlation, CorrelationIds):
            if not correlation.trace_id:
                return CorrelationIds(
                    trace_id=event_id,
                    span_id=correlation.span_id,
                    parent_span_id=correlation.parent_span_id,
                    control_task_id=correlation.control_task_id,
                    control_goal_id=correlation.control_goal_id,
                    query_receipt_id=correlation.query_receipt_id,
                    query_template_id=correlation.query_template_id,
                    proof_key_id=correlation.proof_key_id,
                    proof_entry_id=correlation.proof_entry_id,
                    graph_id=correlation.graph_id,
                    graph_revision_id=correlation.graph_revision_id,
                    vector_collection_id=correlation.vector_collection_id,
                    vector_generation_id=correlation.vector_generation_id,
                    ast_source_revision_id=correlation.ast_source_revision_id,
                    ast_blob_id=correlation.ast_blob_id,
                    wallet_chain_id=correlation.wallet_chain_id,
                    wallet_cursor_id=correlation.wallet_cursor_id,
                    tenant_id=correlation.tenant_id,
                    request_id=correlation.request_id or event_id,
                )
            return correlation
        data = dict(correlation)
        if not data.get("trace_id"):
            data["trace_id"] = event_id
        return CorrelationIds(**{
            k: v
            for k, v in data.items()
            if k
            in {
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
            }
        })

    def _project_to_catalog(
        self, envelope: TypedEventEnvelope
    ) -> AuditRecord | LifecycleEvent:
        attrs = _scalar_attrs(envelope.payload)
        attrs["producer"] = envelope.producer
        attrs["source_revision"] = envelope.source_revision
        attrs["adapter_schema"] = self.SCHEMA
        if envelope.evidence_cid:
            attrs["evidence_cid"] = envelope.evidence_cid
            attrs["evidence_outside_duckdb"] = True

        if envelope.family is CatalogFamily.LIFECYCLE_EVENTS:
            try:
                record = self._catalog.record_lifecycle_event(
                    event_type=envelope.action,
                    component=envelope.producer,
                    domain=envelope.domain,
                    event_id=envelope.event_id,
                    correlation=envelope.correlation,
                    attributes=attrs,
                    recorded_at=envelope.recorded_at,
                )
                return record
            except ObservabilityError:
                # Fall back to audit family if lifecycle rejects the shape.
                pass

        record = self._catalog.record_audit(
            action=envelope.action,
            actor=envelope.actor,
            outcome=envelope.outcome,
            event_id=envelope.event_id,
            correlation=envelope.correlation,
            resource=envelope.resource,
            domain=envelope.domain,
            classification=envelope.classification,
            detail=envelope.detail,
            attributes=attrs,
            recorded_at=envelope.recorded_at,
        )
        return record


# ---------------------------------------------------------------------------
# Module-level singleton for producer wiring
# ---------------------------------------------------------------------------

_GLOBAL_ADAPTER: ObservabilityShadowAdapter | None = None
_GLOBAL_LOCK = threading.RLock()


def open_shadow_adapter(
    *,
    legacy_path: str | Path | None = None,
    memory_legacy: bool = True,
    mode: AuthorityMode | str = AuthorityMode.SHADOW,
    clock: Callable[[], str] | None = None,
) -> ObservabilityShadowAdapter:
    """Construct a hermetic shadow adapter (tests / explicit wiring)."""

    sink = LegacyFileSink(
        path=legacy_path,
        memory_only=memory_legacy or legacy_path is None,
    )
    return ObservabilityShadowAdapter(
        legacy_sink=sink,
        mode=mode,
        clock=clock,
    )


def configure_global_adapter(
    adapter: ObservabilityShadowAdapter | None = None,
    **kwargs: Any,
) -> ObservabilityShadowAdapter:
    """Install the process-global adapter used by producer modules."""

    global _GLOBAL_ADAPTER
    with _GLOBAL_LOCK:
        if adapter is None:
            adapter = open_shadow_adapter(**kwargs)
        _GLOBAL_ADAPTER = adapter
        return adapter


def get_global_adapter() -> ObservabilityShadowAdapter | None:
    """Return the process-global adapter, or ``None`` if not configured.

    Producers call this on every emit so unconfigured processes retain their
    pre-DQK-077 behavior (legacy sinks only, no catalog projection).
    """

    return _GLOBAL_ADAPTER


def reset_global_adapter() -> None:
    """Clear the process-global adapter (tests)."""

    global _GLOBAL_ADAPTER
    with _GLOBAL_LOCK:
        _GLOBAL_ADAPTER = None


def ensure_shadow_adapter() -> ObservabilityShadowAdapter:
    """Return the global adapter, creating a default shadow one if needed.

    Used by producers that must always dual-write once DQK-077 is present
    without requiring an explicit configure step in every test process.
    """

    global _GLOBAL_ADAPTER
    with _GLOBAL_LOCK:
        if _GLOBAL_ADAPTER is None:
            _GLOBAL_ADAPTER = open_shadow_adapter(memory_legacy=True)
        return _GLOBAL_ADAPTER
