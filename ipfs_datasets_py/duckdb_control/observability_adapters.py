"""Shadow-mode adapters for audit/log/alert/MCP producers (DQK-077).

Routes existing audit, security, GraphRAG, observability, MCP, alert, and
provenance event producers through the typed :class:`ObservabilityCatalog`
while legacy file / stderr sinks remain the explicitly selected authority
(:class:`~ipfs_datasets_py.duckdb_control.authority_transition.AuthorityMode.SHADOW`).

Acceptance properties:

* Every mutable log/audit/alert record has a typed schema, stable event ID,
  classification, source revision, and parity receipt
* Retries and restarts do not duplicate events (operation_id / event_id)
* Secrets and unrestricted SQL are redacted before persistence or publication
* Immutable evidence blobs remain content-addressed outside DuckDB

Importing this module is inert: no DuckDB, network, or filesystem I/O until an
explicit adapter method is called.
"""

from __future__ import annotations

import hashlib
import re
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Final,
    Mapping,
    MutableMapping,
    Optional,
    Protocol,
)

from ipfs_datasets_py.duckdb_control.authority_transition import (
    AuthorityBackend,
    AuthorityMode,
    AuthorityTransitionPort,
    MemoryAuthorityBackend,
    ParityReceipt,
    build_authority_port,
    compute_payload_digest,
)
from ipfs_datasets_py.duckdb_control.contracts import (
    canonical_json_bytes,
    content_identity,
)
from ipfs_datasets_py.duckdb_control.observability import (
    AUDIT_RECORD_SCHEMA,
    LIFECYCLE_EVENT_SCHEMA,
    OBSERVABILITY_SCHEMA,
    QUERY_PROFILE_SCHEMA,
    REDACTION_MARKER,
    CatalogFamily,
    CorrelationIds,
    ObservabilityCatalog,
    ObservabilityError,
    SensitivityClass,
    TraceDomain,
    classify_and_redact_query_text,
    open_memory_catalog,
    redact_sensitive_text,
)

__all__ = [
    "EVIDENCE_BLOB_SCHEMA",
    "OBSERVABILITY_ADAPTER_SCHEMA",
    "OBSERVABILITY_EVENT_RECEIPT_SCHEMA",
    "OBSERVABILITY_SHADOW_DOMAIN",
    "OBSERVABILITY_SHADOW_OWNER_TASK",
    "OBSERVABILITY_SOURCE_REVISION",
    "ContentAddressedEvidenceStore",
    "EvidenceBlobRef",
    "MemoryEvidenceBlobStore",
    "ObservabilityEventReceipt",
    "ObservabilityProducer",
    "ObservabilityShadowRepository",
    "configure_observability_shadow",
    "get_observability_shadow",
    "new_observability_event_id",
    "new_observability_operation_id",
    "redact_event_payload",
    "reset_observability_shadow",
    "route_alert_event",
    "route_audit_logger_event",
    "route_graphrag_audit_event",
    "route_logging_audit_result",
    "route_mcp_log_event",
    "route_pipeline_json_event",
    "route_producer_event",
    "route_security_audit_event",
    "route_structured_log_event",
    "stable_event_id",
]


# ---------------------------------------------------------------------------
# Schemas / constants
# ---------------------------------------------------------------------------

OBSERVABILITY_ADAPTER_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-observability-adapter@1"
)
OBSERVABILITY_EVENT_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-observability-event-receipt@1"
)
EVIDENCE_BLOB_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-observability-evidence-blob@1"
)

OBSERVABILITY_SHADOW_DOMAIN: Final[str] = "observability"
OBSERVABILITY_SHADOW_OWNER_TASK: Final[str] = "DQK-077"
OBSERVABILITY_SOURCE_REVISION: Final[str] = "dqk-077-1"

_MAX_DETAIL_BYTES: Final[int] = 1024
_MAX_EVIDENCE_BYTES: Final[int] = 262144

_SAFE_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,127}$")
_UNSAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9_.:/@+-]+")

_SECRET_KEY_MARKERS: Final[tuple[str, ...]] = (
    "password",
    "passwd",
    "pwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
    "private_key",
    "privatekey",
    "mnemonic",
    "seed_phrase",
    "signing_key",
    "bearer",
    "credential",
    "plaintext",
)
_SQL_FIELD_MARKERS: Final[tuple[str, ...]] = (
    "sql",
    "query_text",
    "query",
    "statement",
    "raw_sql",
    "unrestricted_sql",
)


# ---------------------------------------------------------------------------
# Producer taxonomy
# ---------------------------------------------------------------------------


class ObservabilityProducer(str, Enum):
    """Closed set of producers routed by the shadow adapter."""

    AUDIT = "audit"
    SECURITY_AUDIT = "security_audit"
    STRUCTURED_LOG = "structured_log"
    GRAPHRAG_AUDIT = "graphrag_audit"
    PIPELINE_JSON = "pipeline_json"
    LOGGING_AUDIT = "logging_audit"
    ALERT = "alert"
    MCP = "mcp"
    PROVENANCE = "provenance"
    LIFECYCLE = "lifecycle"
    METRIC = "metric"
    QUERY_PROFILE = "query_profile"


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


def _digest_bytes(data: bytes) -> str:
    return f"sha256:{_sha256_hex(data)}"


def _digest_mapping(value: Mapping[str, Any]) -> str:
    return content_identity(dict(value))


def sanitize_token(
    value: Any,
    field_name: str = "token",
    default: str = "unknown",
    max_len: int = 128,
) -> str:
    """Coerce arbitrary text into a catalog-safe id token."""

    raw = str(value if value is not None else "").strip()
    if not raw:
        raw = default
    cleaned = _UNSAFE_CHARS_RE.sub("_", raw)
    cleaned = cleaned.strip("._-")
    if not cleaned:
        cleaned = "x"
    if cleaned[0].isdigit() or not cleaned[0].isalnum():
        cleaned = f"x{cleaned}"
    cleaned = cleaned[:max_len]
    if _SAFE_TOKEN_RE.fullmatch(cleaned) is None:
        digest = _sha256_hex(raw.encode("utf-8"))[:16]
        cleaned = f"{default}-{digest}"
        if _SAFE_TOKEN_RE.fullmatch(cleaned) is None:
            raise ObservabilityError(
                f"{field_name} cannot be sanitized: {value!r}"
            )
    return cleaned


def new_observability_event_id(prefix: str = "evt") -> str:
    return f"{sanitize_token(prefix, default='evt')}-{uuid.uuid4().hex[:16]}"


def new_observability_operation_id(prefix: str = "op") -> str:
    return f"{sanitize_token(prefix, default='op')}:{uuid.uuid4().hex[:16]}"


def stable_event_id(
    producer: str | ObservabilityProducer,
    kind: str,
    payload: Mapping[str, Any] | None = None,
    *,
    explicit: str | None = None,
) -> str:
    """Return a stable event id (explicit or content-derived).

    Content-derived IDs make pure retries of the same producer payload
    idempotent without requiring the caller to allocate an ID.
    """

    if explicit:
        return sanitize_token(explicit, field_name="event_id", default="evt")
    producer_s = (
        producer.value
        if isinstance(producer, ObservabilityProducer)
        else str(producer)
    )
    kind_s = sanitize_token(kind, field_name="kind", default="event")
    body = {
        "producer": producer_s,
        "kind": kind_s,
        "payload": dict(payload or {}),
    }
    digest = _sha256_hex(canonical_json_bytes(body))[:24]
    return f"evt-{sanitize_token(producer_s, default='p')}-{kind_s}-{digest}"


def _is_secret_key(name: str) -> bool:
    lower = name.lower().replace("-", "_")
    return any(marker in lower for marker in _SECRET_KEY_MARKERS)


def _is_sql_field(name: str) -> bool:
    lower = name.lower().replace("-", "_")
    return lower in _SQL_FIELD_MARKERS


def redact_event_payload(value: Any, _path: str = "") -> Any:
    """Deep-redact secrets and unrestricted SQL before persistence/publication.

    * Secret-bearing keys are replaced with :data:`REDACTION_MARKER`.
    * Query/SQL fields are classified and redacted via the observability
      catalog helpers (never store unrestricted ad-hoc SQL plaintext).
    * Nested structures are walked; bytes are refused (use evidence digests).
    """

    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            key_s = str(key)
            child_path = f"{_path}.{key_s}" if _path else key_s
            if _is_secret_key(key_s):
                out[key_s] = REDACTION_MARKER
                continue
            if _is_sql_field(key_s):
                stored, klass, digest = classify_and_redact_query_text(
                    str(item) if item is not None else ""
                )
                out[key_s] = stored
                out[f"{key_s}_classification"] = (
                    klass.value if hasattr(klass, "value") else str(klass)
                )
                out[f"{key_s}_digest"] = digest
                continue
            out[key_s] = redact_event_payload(item, child_path)
        return out
    if isinstance(value, list):
        return [redact_event_payload(item, _path) for item in value]
    if isinstance(value, tuple):
        return [redact_event_payload(item, _path) for item in value]
    if isinstance(value, (bytes, bytearray)):
        return {
            "_digest": _digest_bytes(bytes(value)),
            "_classification": SensitivityClass.REDACTED.value,
            "len": len(value),
        }
    if isinstance(value, str):
        text = value
        if any(marker in text.lower() for marker in _SECRET_KEY_MARKERS):
            text = redact_sensitive_text(text)
        if len(text.encode("utf-8")) > _MAX_DETAIL_BYTES:
            text = text.encode("utf-8")[:_MAX_DETAIL_BYTES].decode(
                "utf-8", errors="ignore"
            )
        return text
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)[:_MAX_DETAIL_BYTES]


def _scalar_attrs(
    payload: Mapping[str, Any], max_keys: int = 48
) -> dict[str, Any]:
    """Project a mapping into catalog-safe scalar attributes."""

    out: dict[str, Any] = {}
    for idx, (key, value) in enumerate(payload.items()):
        if idx >= max_keys:
            break
        key_s = sanitize_token(key, default="k", max_len=64)
        if isinstance(value, bool):
            out[key_s] = value
        elif isinstance(value, int) and not isinstance(value, bool):
            out[key_s] = value
        elif isinstance(value, float):
            out[key_s] = value
        elif value is None:
            out[key_s] = ""
        elif isinstance(value, str):
            text = value
            if len(text.encode("utf-8")) > _MAX_DETAIL_BYTES:
                text = text.encode("utf-8")[:_MAX_DETAIL_BYTES].decode(
                    "utf-8", errors="ignore"
                )
            out[key_s] = text
        else:
            out[key_s] = str(value)[:_MAX_DETAIL_BYTES]
    return out


def _map_outcome(status: Any) -> str:
    text = str(status or "info").strip().lower()
    mapping = {
        "success": "succeeded",
        "succeeded": "succeeded",
        "ok": "succeeded",
        "allowed": "allowed",
        "permit": "allowed",
        "denied": "denied",
        "reject": "denied",
        "rejected": "denied",
        "failure": "failed",
        "failed": "failed",
        "fail": "failed",
        "error": "error",
        "exception": "error",
        "info": "info",
        "triggered": "info",
        "warning": "info",
        "started": "info",
        "completed": "succeeded",
    }
    # partial contains
    if text in mapping:
        return mapping[text]
    for key, outcome in mapping.items():
        if key in text:
            return outcome
    return "info"


def _map_domain(producer: ObservabilityProducer | str) -> TraceDomain:
    name = (
        producer.value
        if isinstance(producer, ObservabilityProducer)
        else str(producer)
    )
    if name in {
        ObservabilityProducer.GRAPHRAG_AUDIT.value,
        ObservabilityProducer.PIPELINE_JSON.value,
    }:
        return TraceDomain.GRAPH
    if name == ObservabilityProducer.QUERY_PROFILE.value:
        return TraceDomain.QUERY
    if name in {
        ObservabilityProducer.AUDIT.value,
        ObservabilityProducer.SECURITY_AUDIT.value,
        ObservabilityProducer.ALERT.value,
    }:
        return TraceDomain.SYSTEM
    if name == ObservabilityProducer.MCP.value:
        return TraceDomain.CONTROL
    return TraceDomain.OBSERVABILITY


def _map_family(
    producer: ObservabilityProducer | str, kind: str
) -> CatalogFamily:
    name = (
        producer.value
        if isinstance(producer, ObservabilityProducer)
        else str(producer)
    )
    kind_l = str(kind or "").lower()
    if name == ObservabilityProducer.QUERY_PROFILE.value or "query" in kind_l:
        return CatalogFamily.QUERY_PROFILES
    if name == ObservabilityProducer.LIFECYCLE.value or kind_l.startswith(
        "system."
    ) or kind_l.startswith("component.") or kind_l.startswith("lifecycle"):
        return CatalogFamily.LIFECYCLE_EVENTS
    if name == ObservabilityProducer.METRIC.value or "health" in kind_l:
        return CatalogFamily.HEALTH_SAMPLES
    return CatalogFamily.AUDIT_EVENTS


def _schema_for_family(family: CatalogFamily) -> str:
    if family is CatalogFamily.QUERY_PROFILES:
        return QUERY_PROFILE_SCHEMA
    if family is CatalogFamily.LIFECYCLE_EVENTS:
        return LIFECYCLE_EVENT_SCHEMA
    if family is CatalogFamily.HEALTH_SAMPLES:
        return OBSERVABILITY_SCHEMA
    return AUDIT_RECORD_SCHEMA


def _classify_payload(payload: Mapping[str, Any]) -> SensitivityClass:
    """Infer sensitivity class from redacted payload markers."""

    raw = canonical_json_bytes(dict(payload)).decode("utf-8", errors="ignore")
    if REDACTION_MARKER in raw:
        return SensitivityClass.REDACTED
    lower = raw.lower()
    if any(marker in lower for marker in _SECRET_KEY_MARKERS):
        return SensitivityClass.REDACTED
    return SensitivityClass.INTERNAL


# ---------------------------------------------------------------------------
# Evidence store (outside DuckDB)
# ---------------------------------------------------------------------------


class ContentAddressedEvidenceStore(Protocol):
    """Immutable evidence blob store living outside DuckDB."""

    def put(
        self, data: bytes, *, media_type: str = "application/json"
    ) -> str:
        """Store bytes; return content identity (``sha256:...``)."""
        ...

    def get(self, cid: str) -> bytes | None:
        """Return blob bytes for *cid*, or ``None`` if missing."""
        ...

    def has(self, cid: str) -> bool:
        """Return whether *cid* is present."""
        ...


class MemoryEvidenceBlobStore:
    """Hermetic in-process evidence store (never DuckDB-backed)."""

    def __init__(self) -> None:
        self._blobs: dict[str, bytes] = {}
        self._lock = threading.RLock()

    def put(
        self, data: bytes, *, media_type: str = "application/json"
    ) -> str:
        if not isinstance(data, (bytes, bytearray)):
            raise ObservabilityError("evidence blob must be bytes")
        raw = bytes(data)
        if len(raw) > _MAX_EVIDENCE_BYTES:
            raise ObservabilityError(
                f"evidence blob exceeds {_MAX_EVIDENCE_BYTES}-byte bound"
            )
        cid = _digest_bytes(raw)
        with self._lock:
            self._blobs.setdefault(cid, raw)
        return cid

    def get(self, cid: str) -> bytes | None:
        with self._lock:
            return self._blobs.get(cid)

    def has(self, cid: str) -> bool:
        with self._lock:
            return cid in self._blobs

    def count(self) -> int:
        with self._lock:
            return len(self._blobs)


@dataclass(frozen=True, slots=True)
class EvidenceBlobRef:
    """Content-addressed pointer kept in catalog attributes (not the bytes)."""

    cid: str
    media_type: str = "application/json"
    byte_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "cid": self.cid,
            "media_type": self.media_type,
            "byte_count": self.byte_count,
            "content_addressed_outside_duckdb": True,
        }


# ---------------------------------------------------------------------------
# Receipts
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ObservabilityEventReceipt:
    """Idempotent producer receipt bound to typed catalog + parity."""

    event_id: str
    operation_id: str
    producer: str
    kind: str
    family: str
    record_schema: str
    classification: str
    source_revision: str
    parity_receipt_cid: str
    parity_matched: bool
    mode: str
    authority: str
    payload_digest: str
    evidence_cid: str
    sequence: int = 0
    idempotent_replay: bool = False
    outbox_id: str = ""
    error: str = ""
    recorded_at: str = ""
    schema: str = OBSERVABILITY_EVENT_RECEIPT_SCHEMA
    adapter_schema: str = OBSERVABILITY_ADAPTER_SCHEMA
    owner_task: str = OBSERVABILITY_SHADOW_OWNER_TASK

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "adapter_schema": self.adapter_schema,
            "owner_task": self.owner_task,
            "event_id": self.event_id,
            "operation_id": self.operation_id,
            "producer": self.producer,
            "kind": self.kind,
            "family": self.family,
            "record_schema": self.record_schema,
            "classification": self.classification,
            "source_revision": self.source_revision,
            "parity_receipt_cid": self.parity_receipt_cid,
            "parity_matched": self.parity_matched,
            "mode": self.mode,
            "authority": self.authority,
            "payload_digest": self.payload_digest,
            "evidence_cid": self.evidence_cid,
            "sequence": self.sequence,
            "idempotent_replay": self.idempotent_replay,
            "outbox_id": self.outbox_id,
            "error": self.error,
            "recorded_at": self.recorded_at,
        }


# ---------------------------------------------------------------------------
# Shadow repository
# ---------------------------------------------------------------------------


@dataclass
class ObservabilityShadowRepository:
    """Typed observability repository with legacy file sinks as authority.

    In **shadow** mode (default):

    * Legacy file / JSONL / stderr sinks remain the restorable authority for
      producer-visible behaviour (selected explicitly via
      :class:`AuthorityMode.SHADOW`).
    * The typed :class:`ObservabilityCatalog` receives a redacted projection
      of every routed event with stable IDs and classifications.
    * Every mutation is bound to an operation ID and parity receipt.
    * Evidence blobs are content-addressed outside DuckDB.

    Parameters
    ----------
    mode:
        Authority mode; defaults to ``shadow``.
    catalog:
        Optional shared catalog (defaults to an in-memory catalog).
    backend:
        Optional shared authority backend.
    evidence_store:
        Content-addressed evidence store outside DuckDB.
    enabled:
        When false, routing is a no-op that still returns structured receipts
        marked ``mode=disabled`` (legacy-only).
    source_revision:
        Revision label stamped on every receipt (acceptance field).
    """

    mode: AuthorityMode | str = AuthorityMode.SHADOW
    catalog: ObservabilityCatalog | None = None
    backend: AuthorityBackend | None = None
    evidence_store: ContentAddressedEvidenceStore | None = None
    enabled: bool = True
    domain: str = OBSERVABILITY_SHADOW_DOMAIN
    writer_id: str = "writer:observability-shadow"
    source_revision: str = OBSERVABILITY_SOURCE_REVISION
    owner_task: str = OBSERVABILITY_SHADOW_OWNER_TASK
    _port: AuthorityTransitionPort = field(init=False, repr=False)
    _catalog: ObservabilityCatalog = field(init=False, repr=False)
    _evidence: ContentAddressedEvidenceStore = field(init=False, repr=False)
    _lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )
    _receipts: dict[str, ObservabilityEventReceipt] = field(
        default_factory=dict, init=False, repr=False
    )
    _event_index: dict[str, str] = field(
        default_factory=dict, init=False, repr=False
    )
    _source_revisions: dict[str, int] = field(
        default_factory=dict, init=False, repr=False
    )
    _legacy_sinks: dict[str, list[dict[str, Any]]] = field(
        default_factory=dict, init=False, repr=False
    )
    _parity_receipts: list[ParityReceipt] = field(
        default_factory=list, init=False, repr=False
    )

    def __post_init__(self) -> None:
        backend = self.backend if self.backend is not None else MemoryAuthorityBackend()
        object.__setattr__(self, "backend", backend)
        mode = self.mode
        if not isinstance(mode, AuthorityMode):
            mode = AuthorityMode.parse(str(mode))
            object.__setattr__(self, "mode", mode)
        port = build_authority_port(
            backend,
            domain=self.domain,
            initial_mode=mode,
            writer_id=self.writer_id,
        )
        object.__setattr__(self, "_port", port)
        catalog = self.catalog if self.catalog is not None else open_memory_catalog()
        object.__setattr__(self, "_catalog", catalog)
        object.__setattr__(self, "catalog", catalog)
        evidence = (
            self.evidence_store
            if self.evidence_store is not None
            else MemoryEvidenceBlobStore()
        )
        object.__setattr__(self, "_evidence", evidence)
        object.__setattr__(self, "evidence_store", evidence)

    @property
    def interface(self) -> str:
        return OBSERVABILITY_ADAPTER_SCHEMA

    @property
    def authority_port(self) -> AuthorityTransitionPort:
        return self._port

    @property
    def authority_mode(self) -> AuthorityMode:
        return self._port.mode

    @property
    def observability_catalog(self) -> ObservabilityCatalog:
        return self._catalog

    @property
    def evidence(self) -> ContentAddressedEvidenceStore:
        return self._evidence

    def _next_source_revision(self, producer: str) -> str:
        with self._lock:
            n = self._source_revisions.get(producer, 0) + 1
            self._source_revisions[producer] = n
            p = sanitize_token(producer, default="producer")
            return f"{self.source_revision}:{p}:{n}"

    def record_event(
        self,
        producer: ObservabilityProducer | str,
        kind: str,
        *,
        payload: Mapping[str, Any] | None = None,
        event_id: str | None = None,
        operation_id: str | None = None,
        actor: str = "system",
        resource: str = "",
        outcome: str = "info",
        domain: TraceDomain | str | None = None,
        family: CatalogFamily | str | None = None,
        correlation: CorrelationIds | Mapping[str, Any] | None = None,
        detail: str = "",
        classification: SensitivityClass | str | None = None,
        query_text: str | None = None,
        recorded_at: str | None = None,
        legacy_sink_key: str | None = None,
    ) -> ObservabilityEventReceipt:
        """Record one producer event with typed schema + parity + evidence.

        Legacy sinks remain authority under shadow mode. Callers that still
        write JSONL/files should do so as today; this path projects a redacted
        dual of that event into the typed catalog and authority port.
        """

        if isinstance(producer, ObservabilityProducer):
            producer_enum = producer
            producer_s = producer.value
        else:
            try:
                producer_enum = ObservabilityProducer(str(producer))
                producer_s = producer_enum.value
            except ValueError:
                producer_enum = ObservabilityProducer.PROVENANCE
                producer_s = sanitize_token(producer, default="producer")

        kind_s = sanitize_token(kind, field_name="kind", default="event")
        raw_payload = dict(payload or {})
        redacted = redact_event_payload(raw_payload)
        if not isinstance(redacted, Mapping):
            redacted = {"value": redacted}

        eid = stable_event_id(
            producer_s,
            kind_s,
            redacted,
            explicit=event_id,
        )
        if operation_id:
            op_id = sanitize_token(
                operation_id, field_name="operation_id", default="op"
            )
            if ":" not in op_id and not op_id.startswith("op"):
                op_id = f"op:{op_id}"
        else:
            # Derive stable operation id from event so pure retries collide.
            op_id = f"op:{eid}"

        with self._lock:
            prior = self._receipts.get(op_id)
            if prior is None:
                indexed = self._event_index.get(eid)
                if indexed:
                    prior = self._receipts.get(indexed)
            if prior is not None:
                return ObservabilityEventReceipt(
                    event_id=prior.event_id,
                    operation_id=prior.operation_id,
                    producer=prior.producer,
                    kind=prior.kind,
                    family=prior.family,
                    record_schema=prior.record_schema,
                    classification=prior.classification,
                    source_revision=prior.source_revision,
                    parity_receipt_cid=prior.parity_receipt_cid,
                    parity_matched=prior.parity_matched,
                    mode=prior.mode,
                    authority=prior.authority,
                    payload_digest=prior.payload_digest,
                    evidence_cid=prior.evidence_cid,
                    sequence=prior.sequence,
                    idempotent_replay=True,
                    outbox_id=prior.outbox_id,
                    error=prior.error,
                    recorded_at=prior.recorded_at,
                )

            source_rev = self._next_source_revision(producer_s)

            if family is None:
                fam = _map_family(producer_enum, kind_s)
            elif isinstance(family, CatalogFamily):
                fam = family
            else:
                fam = CatalogFamily(str(family).strip())
            record_schema = _schema_for_family(fam)

            if domain is None:
                dom = _map_domain(producer_enum)
            elif isinstance(domain, TraceDomain):
                dom = domain
            else:
                dom = TraceDomain(str(domain).strip().lower())

            if classification is None:
                klass = _classify_payload(redacted)
            elif isinstance(classification, SensitivityClass):
                klass = classification
            else:
                klass = SensitivityClass(str(classification).strip().lower())
            if klass is SensitivityClass.SECRET:
                klass = SensitivityClass.REDACTED

            detail_text = str(detail or "")
            if not detail_text:
                detail_text = str(
                    redacted.get("message")
                    or redacted.get("action")
                    or kind_s
                )
            if klass is SensitivityClass.REDACTED:
                detail_text = redact_sensitive_text(detail_text)
            if len(detail_text.encode("utf-8")) > _MAX_DETAIL_BYTES:
                detail_text = detail_text.encode("utf-8")[:_MAX_DETAIL_BYTES].decode(
                    "utf-8", errors="ignore"
                )

            actor_s = sanitize_token(actor, field_name="actor", default="system")
            resource_s = (
                sanitize_token(resource, field_name="resource", default="resource")
                if resource
                else ""
            )
            outcome_s = _map_outcome(outcome)

            evidence_body = {
                "schema": EVIDENCE_BLOB_SCHEMA,
                "owner_task": self.owner_task,
                "domain": self.domain,
                "event_id": eid,
                "operation_id": op_id,
                "producer": producer_s,
                "kind": kind_s,
                "actor": actor_s,
                "resource": resource_s,
                "outcome": outcome_s,
                "detail": detail_text,
                "payload": dict(redacted),
                "source_revision": source_rev,
                "evidence_storage": "content_addressed_outside_duckdb",
            }
            evidence_bytes = canonical_json_bytes(evidence_body)
            evidence_cid = self._evidence.put(
                evidence_bytes, media_type="application/json"
            )

            attrs = _scalar_attrs(redacted)
            attrs["evidence_cid"] = evidence_cid
            attrs["source_revision"] = source_rev
            attrs["producer"] = producer_s
            attrs["adapter_schema"] = OBSERVABILITY_ADAPTER_SCHEMA
            attrs["content_addressed_outside_duckdb"] = True

            projection = {
                "schema": OBSERVABILITY_ADAPTER_SCHEMA,
                "event_id": eid,
                "operation_id": op_id,
                "producer": producer_s,
                "kind": kind_s,
                "family": fam.value,
                "record_schema": record_schema,
                "classification": klass.value,
                "source_revision": source_rev,
                "actor": actor_s,
                "resource": resource_s,
                "outcome": outcome_s,
                "detail": detail_text,
                "domain": dom.value,
                "payload_digest": _digest_mapping(redacted),
                "evidence_cid": evidence_cid,
            }
            projection_digest = _digest_mapping(projection)
            key = f"obs:{producer_s}:{eid}"
            ts = recorded_at or _utc_now()

            if not self.enabled:
                receipt = ObservabilityEventReceipt(
                    event_id=eid,
                    operation_id=op_id,
                    producer=producer_s,
                    kind=kind_s,
                    family=fam.value,
                    record_schema=record_schema,
                    classification=klass.value,
                    source_revision=source_rev,
                    parity_receipt_cid="",
                    parity_matched=False,
                    mode="disabled",
                    authority="legacy",
                    payload_digest=projection_digest,
                    evidence_cid=evidence_cid,
                    sequence=0,
                    idempotent_replay=False,
                    recorded_at=ts,
                )
                self._receipts[op_id] = receipt
                self._event_index[eid] = op_id
                self._append_legacy_sink(key, projection)
                return receipt

            self._append_legacy_sink(key, projection)

            try:
                write_result = self._port.write(
                    key, projection, operation_id=op_id
                )
                sequence = self._write_catalog_record(
                    family=fam,
                    event_id=eid,
                    producer=producer_s,
                    kind=kind_s,
                    actor=actor_s,
                    resource=resource_s,
                    outcome=outcome_s,
                    domain=dom,
                    classification=klass,
                    detail=detail_text,
                    attributes=attrs,
                    correlation=correlation,
                    query_text=query_text
                    if query_text is not None
                    else (
                        str(redacted.get("query_text") or redacted.get("sql") or "")
                        or None
                    ),
                    recorded_at=ts,
                )
                parity = self._port.emit_parity_receipt(
                    key, operation_id=op_id
                )
                parity_cid = parity.receipt_cid
                matched = bool(parity.matched)
                self._parity_receipts.append(parity)

                receipt = ObservabilityEventReceipt(
                    event_id=eid,
                    operation_id=op_id,
                    producer=producer_s,
                    kind=kind_s,
                    family=fam.value,
                    record_schema=record_schema,
                    classification=klass.value,
                    source_revision=source_rev,
                    parity_receipt_cid=parity_cid,
                    parity_matched=matched,
                    mode=self._port.mode.value,
                    authority=str(write_result.get("authority") or "legacy"),
                    payload_digest=projection_digest,
                    evidence_cid=evidence_cid,
                    sequence=sequence,
                    idempotent_replay=bool(
                        write_result.get("idempotent_replay")
                    ),
                    outbox_id=str(write_result.get("outbox_id") or ""),
                    recorded_at=ts,
                )
            except Exception as exc:  # fail-soft: never break producers
                receipt = ObservabilityEventReceipt(
                    event_id=eid,
                    operation_id=op_id,
                    producer=producer_s,
                    kind=kind_s,
                    family=fam.value,
                    record_schema=record_schema,
                    classification=klass.value,
                    source_revision=source_rev,
                    parity_receipt_cid="",
                    parity_matched=False,
                    mode=self._port.mode.value
                    if hasattr(self, "_port")
                    else "shadow",
                    authority="legacy",
                    payload_digest=projection_digest,
                    evidence_cid=evidence_cid,
                    sequence=0,
                    error=str(exc)[:_MAX_DETAIL_BYTES],
                    recorded_at=ts,
                )

            self._receipts[op_id] = receipt
            self._event_index[eid] = op_id
            return receipt

    def _append_legacy_sink(
        self, key: str, projection: Mapping[str, Any]
    ) -> None:
        """Track the legacy-authority projection for parity / restart tests."""

        self._legacy_sinks.setdefault(key, []).append(dict(projection))

    def _write_catalog_record(
        self,
        *,
        family: CatalogFamily,
        event_id: str,
        producer: str,
        kind: str,
        actor: str,
        resource: str,
        outcome: str,
        domain: TraceDomain,
        classification: SensitivityClass,
        detail: str,
        attributes: Mapping[str, Any],
        correlation: CorrelationIds | Mapping[str, Any] | None,
        query_text: str | None,
        recorded_at: str,
    ) -> int:
        """Append a typed catalog record; return its sequence number."""

        existing = self._catalog.get(family, event_id)
        if existing is not None:
            return int(getattr(existing, "sequence", 0) or 0)

        corr = correlation
        if family is CatalogFamily.QUERY_PROFILES:
            text = query_text if query_text is not None else detail
            record = self._catalog.record_query_profile(
                template_id=sanitize_token(kind, default="query"),
                query_text=text,
                classification=classification,
                profile_id=event_id,
                correlation=corr,
                status=outcome if outcome in {"succeeded", "failed", "error"} else "succeeded",
                attributes=attributes,
                recorded_at=recorded_at,
            )
            return int(record.sequence)
        if family is CatalogFamily.LIFECYCLE_EVENTS:
            record = self._catalog.record_lifecycle_event(
                event_type=kind,
                component=sanitize_token(
                    attributes.get("component") or producer,
                    default="component",
                ),
                domain=domain,
                event_id=event_id,
                correlation=corr,
                status="ok" if outcome in {"succeeded", "info", "allowed"} else outcome,
                detail=detail,
                attributes=attributes,
                recorded_at=recorded_at,
            )
            return int(record.sequence)
        if family is CatalogFamily.HEALTH_SAMPLES:
            record = self._catalog.record_health_sample(
                component=sanitize_token(producer, default="component"),
                domain=domain,
                status=outcome if outcome else "ok",
                sample_id=event_id,
                correlation=corr,
                attributes=attributes,
                recorded_at=recorded_at,
            )
            return int(record.sequence)

        record = self._catalog.record_audit(
            action=kind,
            actor=actor,
            outcome=outcome,
            event_id=event_id,
            correlation=corr,
            resource=resource,
            domain=domain,
            classification=classification,
            detail=detail,
            attributes=attributes,
            recorded_at=recorded_at,
        )
        return int(record.sequence)

    def get_receipt(
        self, *, event_id: str | None = None, operation_id: str | None = None
    ) -> ObservabilityEventReceipt | None:
        with self._lock:
            if operation_id and operation_id in self._receipts:
                return self._receipts[operation_id]
            if event_id:
                op = self._event_index.get(event_id)
                if op:
                    return self._receipts.get(op)
            return None

    def list_receipts(
        self, producer: str | ObservabilityProducer | None = None
    ) -> list[ObservabilityEventReceipt]:
        with self._lock:
            rows = list(self._receipts.values())
        if producer is None:
            return rows
        name = (
            producer.value
            if isinstance(producer, ObservabilityProducer)
            else str(producer)
        )
        return [r for r in rows if r.producer == name]

    def list_parity_receipts(self) -> list[ParityReceipt]:
        with self._lock:
            return list(self._parity_receipts)

    def legacy_sink_records(
        self, key: str | None = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            if key is None:
                out: list[dict[str, Any]] = []
                for rows in self._legacy_sinks.values():
                    out.extend(dict(r) for r in rows)
                return out
            return [dict(r) for r in self._legacy_sinks.get(key, [])]

    def evidence_blob(self, cid: str) -> bytes | None:
        return self._evidence.get(cid)

    def catalog_record(
        self, family: CatalogFamily | str, event_id: str
    ) -> Any:
        return self._catalog.get(family, event_id)

    def progress(self) -> Any:
        return self._catalog.progress()


# ---------------------------------------------------------------------------
# Process-local registry
# ---------------------------------------------------------------------------

_process_shadow: ObservabilityShadowRepository | None = None
_process_shadow_lock = threading.RLock()


def configure_observability_shadow(
    mode: AuthorityMode | str = AuthorityMode.SHADOW,
    catalog: ObservabilityCatalog | None = None,
    backend: AuthorityBackend | None = None,
    evidence_store: ContentAddressedEvidenceStore | None = None,
    enabled: bool = True,
    source_revision: str = OBSERVABILITY_SOURCE_REVISION,
    writer_id: str = "writer:observability-shadow",
) -> ObservabilityShadowRepository:
    """Install a process-local observability shadow repository (DQK-077)."""

    with _process_shadow_lock:
        global _process_shadow
        auth = ObservabilityShadowRepository(
            mode=mode,
            catalog=catalog,
            backend=backend,
            evidence_store=evidence_store,
            enabled=enabled,
            source_revision=source_revision,
            writer_id=writer_id,
        )
        _process_shadow = auth
        return auth


def get_observability_shadow() -> ObservabilityShadowRepository | None:
    with _process_shadow_lock:
        return _process_shadow


def reset_observability_shadow() -> None:
    with _process_shadow_lock:
        global _process_shadow
        _process_shadow = None


def _active_shadow(
    shadow: ObservabilityShadowRepository | None = None,
) -> ObservabilityShadowRepository | None:
    if shadow is not None:
        return shadow
    return get_observability_shadow()


# ---------------------------------------------------------------------------
# Producer routers (fail-soft when shadow not configured)
# ---------------------------------------------------------------------------


def route_producer_event(
    producer: ObservabilityProducer | str,
    kind: str,
    *,
    payload: Mapping[str, Any] | None = None,
    event_id: str | None = None,
    operation_id: str | None = None,
    actor: str = "system",
    resource: str = "",
    outcome: str = "info",
    domain: TraceDomain | str | None = None,
    family: CatalogFamily | str | None = None,
    correlation: CorrelationIds | Mapping[str, Any] | None = None,
    detail: str = "",
    classification: SensitivityClass | str | None = None,
    query_text: str | None = None,
    recorded_at: str | None = None,
    shadow: ObservabilityShadowRepository | None = None,
) -> ObservabilityEventReceipt | None:
    """Route a generic producer event when shadow is configured."""

    repo = _active_shadow(shadow)
    if repo is None:
        return None
    return repo.record_event(
        producer,
        kind,
        payload=payload,
        event_id=event_id,
        operation_id=operation_id,
        actor=actor,
        resource=resource,
        outcome=outcome,
        domain=domain,
        family=family,
        correlation=correlation,
        detail=detail,
        classification=classification,
        query_text=query_text,
        recorded_at=recorded_at,
    )


def route_audit_logger_event(
    event: Any,
    *,
    shadow: ObservabilityShadowRepository | None = None,
    operation_id: str | None = None,
) -> ObservabilityEventReceipt | None:
    """Route an ``ipfs_datasets_py.audit.audit_logger.AuditEvent``."""

    repo = _active_shadow(shadow)
    if repo is None:
        return None
    if hasattr(event, "to_dict"):
        data = event.to_dict()
    elif isinstance(event, Mapping):
        data = dict(event)
    else:
        data = {
            "event_id": getattr(event, "event_id", ""),
            "action": getattr(event, "action", "audit"),
            "user": getattr(event, "user", "system"),
            "status": getattr(event, "status", "info"),
            "details": getattr(event, "details", {}) or {},
            "level": str(getattr(event, "level", "")),
            "category": str(getattr(event, "category", "")),
            "resource_id": getattr(event, "resource_id", ""),
            "resource_type": getattr(event, "resource_type", ""),
            "session_id": getattr(event, "session_id", ""),
            "application": getattr(event, "application", ""),
            "tags": getattr(event, "tags", []),
            "timestamp": getattr(event, "timestamp", ""),
        }
    details = data.get("details") if isinstance(data.get("details"), Mapping) else {}
    payload = {
        "level": data.get("level"),
        "category": data.get("category"),
        "resource_id": data.get("resource_id"),
        "resource_type": data.get("resource_type"),
        "session_id": data.get("session_id"),
        "application": data.get("application"),
        "tags": data.get("tags"),
        "details": details,
    }
    resource = str(
        data.get("resource_id") or data.get("resource_type") or ""
    )
    return repo.record_event(
        ObservabilityProducer.AUDIT,
        str(data.get("action") or "audit"),
        payload=payload,
        event_id=str(data.get("event_id") or "") or None,
        operation_id=operation_id,
        actor=str(data.get("user") or "system"),
        resource=resource,
        outcome=str(data.get("status") or "info"),
        recorded_at=str(data.get("timestamp") or "") or None,
    )


def route_security_audit_event(
    event_type: str,
    user_id: str,
    success: bool,
    details: Mapping[str, Any] | None = None,
    *,
    event_id: str | None = None,
    operation_id: str | None = None,
    shadow: ObservabilityShadowRepository | None = None,
    **kwargs: Any,
) -> ObservabilityEventReceipt | None:
    """Route a logic security audit log event."""

    repo = _active_shadow(shadow)
    if repo is None:
        return None
    payload: dict[str, Any] = dict(details or {})
    payload.update(kwargs)
    payload["success"] = bool(success)
    return repo.record_event(
        ObservabilityProducer.SECURITY_AUDIT,
        event_type,
        payload=payload,
        event_id=event_id,
        operation_id=operation_id,
        actor=user_id or "system",
        outcome="succeeded" if success else "failed",
    )


def route_structured_log_event(
    event_type: str,
    fields: Mapping[str, Any] | None = None,
    *,
    level: str = "INFO",
    event_id: str | None = None,
    operation_id: str | None = None,
    shadow: ObservabilityShadowRepository | None = None,
) -> ObservabilityEventReceipt | None:
    """Route a structured JSON log event."""

    repo = _active_shadow(shadow)
    if repo is None:
        return None
    payload = dict(fields or {})
    payload["level"] = level
    kind = str(event_type)
    family = None
    if kind.startswith("system.") or kind.startswith("component."):
        family = CatalogFamily.LIFECYCLE_EVENTS
    else:
        family = CatalogFamily.AUDIT_EVENTS
    return repo.record_event(
        ObservabilityProducer.STRUCTURED_LOG,
        kind,
        payload=payload,
        event_id=event_id,
        operation_id=operation_id,
        actor=str(payload.get("user_id") or "system"),
        resource=str(payload.get("component") or ""),
        outcome="info",
        family=family,
    )


def route_graphrag_audit_event(
    event: Any,
    *,
    session_id: str = "",
    shadow: ObservabilityShadowRepository | None = None,
    event_id: str | None = None,
    operation_id: str | None = None,
) -> ObservabilityEventReceipt | None:
    """Route a GraphRAG refinement audit event."""

    repo = _active_shadow(shadow)
    if repo is None:
        return None
    if hasattr(event, "to_dict"):
        data = event.to_dict()
    elif isinstance(event, Mapping):
        data = dict(event)
    else:
        data = {
            "event_type": str(getattr(event, "event_type", "graphrag")),
            "round_num": getattr(event, "round_num", 0),
            "event_data": getattr(event, "event_data", {}) or {},
            "metadata": getattr(event, "metadata", {}) or {},
            "timestamp": getattr(event, "timestamp", ""),
        }
    kind = str(data.get("event_type") or "graphrag")
    payload = {
        "round_num": data.get("round_num"),
        "event_data": data.get("event_data") or {},
        "metadata": data.get("metadata") or {},
        "session_id": session_id,
    }
    return repo.record_event(
        ObservabilityProducer.GRAPHRAG_AUDIT,
        kind,
        payload=payload,
        event_id=event_id,
        operation_id=operation_id,
        actor=sanitize_token(session_id or "graphrag_audit", default="graphrag"),
        outcome="info",
        domain=TraceDomain.GRAPH,
        recorded_at=str(data.get("timestamp") or "") or None,
    )


def route_pipeline_json_event(
    event_type: str,
    data: Mapping[str, Any] | None = None,
    *,
    domain: str = "graphrag",
    run_id: str = "",
    event_id: str | None = None,
    operation_id: str | None = None,
    shadow: ObservabilityShadowRepository | None = None,
) -> ObservabilityEventReceipt | None:
    """Route a GraphRAG pipeline JSON log event."""

    repo = _active_shadow(shadow)
    if repo is None:
        return None
    payload = dict(data or {})
    payload["domain"] = domain
    if run_id:
        payload["run_id"] = run_id
    status = str(payload.get("status") or "info")
    return repo.record_event(
        ObservabilityProducer.PIPELINE_JSON,
        event_type,
        payload=payload,
        event_id=event_id,
        operation_id=operation_id,
        actor=sanitize_token(run_id or "pipeline", default="pipeline"),
        resource=sanitize_token(domain, default="graphrag"),
        outcome=status,
        domain=TraceDomain.GRAPH,
    )


def route_logging_audit_result(
    result: Any,
    *,
    event_id: str | None = None,
    operation_id: str | None = None,
    shadow: ObservabilityShadowRepository | None = None,
) -> ObservabilityEventReceipt | None:
    """Route an optimizer logging-audit result as a provenance/audit event."""

    repo = _active_shadow(shadow)
    if repo is None:
        return None
    if hasattr(result, "__dict__") and not isinstance(result, Mapping):
        payload = {
            "file_path": str(getattr(result, "file_path", "") or ""),
            "class_name": str(getattr(result, "class_name", "") or ""),
            "methods_with_logging": list(
                getattr(result, "methods_with_logging", []) or []
            ),
            "methods_without_logging": list(
                getattr(result, "methods_without_logging", []) or []
            ),
            "has_logger_init": bool(getattr(result, "has_logger_init", False)),
            "issues": list(getattr(result, "issues", []) or []),
            "logging_patterns": dict(
                getattr(result, "logging_patterns", {}) or {}
            ),
        }
    elif isinstance(result, Mapping):
        payload = dict(result)
    else:
        payload = {"result": str(result)}
    path = str(payload.get("file_path") or "logging_audit")
    return repo.record_event(
        ObservabilityProducer.LOGGING_AUDIT,
        "logging_audit.result",
        payload=payload,
        event_id=event_id,
        operation_id=operation_id,
        actor="logging_auditor",
        resource=sanitize_token(path, default="file", max_len=96),
        outcome="info",
        domain=TraceDomain.OBSERVABILITY,
    )


def route_alert_event(
    rule_id: str,
    rule_name: str,
    severity: str,
    status: str = "triggered",
    message: str = "",
    event_payload: Mapping[str, Any] | None = None,
    *,
    event_id: str | None = None,
    operation_id: str | None = None,
    shadow: ObservabilityShadowRepository | None = None,
) -> ObservabilityEventReceipt | None:
    """Route an alert-manager trigger / evaluation result."""

    repo = _active_shadow(shadow)
    if repo is None:
        return None
    payload = {
        "rule_id": rule_id,
        "rule_name": rule_name,
        "severity": severity,
        "status": status,
        "message": message,
        "event": dict(event_payload or {}),
    }
    return repo.record_event(
        ObservabilityProducer.ALERT,
        f"alert.{sanitize_token(rule_id, default='rule')}",
        payload=payload,
        event_id=event_id,
        operation_id=operation_id,
        actor="alert_manager",
        resource=sanitize_token(rule_id, default="rule"),
        outcome=status,
        detail=message,
        domain=TraceDomain.SYSTEM,
    )


def route_mcp_log_event(
    message: str,
    *,
    level: str = "INFO",
    logger_name: str = "ipfs_datasets.mcp_server",
    extra: Mapping[str, Any] | None = None,
    event_id: str | None = None,
    operation_id: str | None = None,
    shadow: ObservabilityShadowRepository | None = None,
) -> ObservabilityEventReceipt | None:
    """Route an MCP server log event."""

    repo = _active_shadow(shadow)
    if repo is None:
        return None
    payload = dict(extra or {})
    payload["logger_name"] = logger_name
    payload["level"] = level
    payload["message"] = message[:_MAX_DETAIL_BYTES]
    level_l = str(level).lower()
    return repo.record_event(
        ObservabilityProducer.MCP,
        f"mcp.{sanitize_token(level_l, default='info')}",
        payload=payload,
        event_id=event_id,
        operation_id=operation_id,
        actor="mcp_server",
        outcome="info" if level_l not in {"error", "critical"} else "error",
        detail=message[:_MAX_DETAIL_BYTES],
        domain=TraceDomain.CONTROL,
    )
