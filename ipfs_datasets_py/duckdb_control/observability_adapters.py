"""Typed observability producer adapters with shadow authority (DQK-077).

Routes audit, security, GraphRAG, structured-log, MCP, alert, and provenance
event producers through the DQK-052 :class:`ObservabilityCatalog` while
**legacy file sinks remain the selected authority** under
:class:`~ipfs_datasets_py.duckdb_control.authority_transition.AuthorityMode.SHADOW`.

Acceptance properties enforced by construction:

* Every mutable log/audit/alert record carries a typed schema, stable event
  ID, sensitivity classification, source revision, and parity receipt
* Retries and restarts with the same event/operation ID do not duplicate
* Secrets and unrestricted SQL are redacted before persistence or publication
* Immutable evidence blobs stay content-addressed **outside** DuckDB; the
  catalog and authority projection hold only digests / content references

Importing this module is inert: no DuckDB, network, or filesystem I/O until
an explicit configure / record call.
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
    ClassVar,
    Final,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
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
    ContentMediaType,
    ContentReference,
    SourceDigest,
    canonical_json_bytes,
    content_identity,
    normalize_timestamp,
)
from ipfs_datasets_py.duckdb_control.observability import (
    AUDIT_RECORD_SCHEMA,
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
    "OBSERVABILITY_ADAPTER_SCHEMA",
    "OBSERVABILITY_EVENT_RECEIPT_SCHEMA",
    "OBSERVABILITY_SHADOW_DOMAIN",
    "OBSERVABILITY_SHADOW_OWNER_TASK",
    "OBSERVABILITY_SOURCE_REVISION",
    "PRODUCER_SCHEMAS",
    "EvidenceBlobStore",
    "MemoryEvidenceBlobStore",
    "ObservabilityEventReceipt",
    "ObservabilityProducer",
    "ObservabilityShadowError",
    "ObservabilityShadowRepository",
    "build_observability_shadow_repository",
    "clear_observability_shadow",
    "configure_observability_shadow",
    "derive_stable_event_id",
    "get_observability_shadow",
    "record_observability_event",
    "redact_event_payload",
    "reset_observability_shadow",
    "sanitize_action_token",
    "sanitize_actor_token",
]


# ---------------------------------------------------------------------------
# Schema / domain pins
# ---------------------------------------------------------------------------

OBSERVABILITY_SHADOW_OWNER_TASK: Final[str] = "DQK-077"
OBSERVABILITY_SHADOW_DOMAIN: Final[str] = "observability"
OBSERVABILITY_ADAPTER_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-observability-adapters@1"
)
OBSERVABILITY_EVENT_RECEIPT_SCHEMA: Final[str] = (
    "ipfs_datasets_py/duckdb-control-observability-event-receipt@1"
)
OBSERVABILITY_SOURCE_REVISION: Final[str] = (
    "dqk-077-lane0-attempt1-20260811"
)
OBSERVABILITY_SHADOW_INTERFACE: Final[str] = "ObservabilityShadowRepository@1"

# Closed set of admitted producer module identities (expected outputs).
class ObservabilityProducer(str, Enum):
    """Closed set of event producers routed through the shadow repository."""

    AUDIT_LOGGER = "audit.audit_logger"
    LOGIC_SECURITY_AUDIT = "logic.security.audit_log"
    STRUCTURED_LOGGING = "logic.observability.structured_logging"
    GRAPHRAG_AUDIT = "optimizers.graphrag.audit_logger"
    PIPELINE_JSON = "optimizers.graphrag.pipeline_json_logger"
    LOGGING_AUDIT = "optimizers.common.logging_audit"
    ALERT_MANAGER = "alerts.alert_manager"
    MCP_LOGGER = "mcp_server.logger"


PRODUCER_SCHEMAS: Final[Mapping[str, str]] = MappingProxyType(
    {
        ObservabilityProducer.AUDIT_LOGGER.value: (
            "ipfs_datasets_py/audit-event@1"
        ),
        ObservabilityProducer.LOGIC_SECURITY_AUDIT.value: (
            "ipfs_datasets_py/logic-security-audit-event@1"
        ),
        ObservabilityProducer.STRUCTURED_LOGGING.value: (
            "ipfs_datasets_py/structured-log-event@1"
        ),
        ObservabilityProducer.GRAPHRAG_AUDIT.value: (
            "ipfs_datasets_py/graphrag-audit-event@1"
        ),
        ObservabilityProducer.PIPELINE_JSON.value: (
            "ipfs_datasets_py/pipeline-json-log-event@1"
        ),
        ObservabilityProducer.LOGGING_AUDIT.value: (
            "ipfs_datasets_py/optimizer-logging-audit@1"
        ),
        ObservabilityProducer.ALERT_MANAGER.value: (
            "ipfs_datasets_py/alert-event@1"
        ),
        ObservabilityProducer.MCP_LOGGER.value: (
            "ipfs_datasets_py/mcp-log-event@1"
        ),
    }
)

# Unrestricted / free-form SQL patterns that must not be stored as plaintext.
_UNRESTRICTED_SQL_RE: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(?is)\bSELECT\b.+\bFROM\b"),
    re.compile(r"(?is)\bINSERT\s+INTO\b"),
    re.compile(r"(?is)\bUPDATE\b.+\bSET\b"),
    re.compile(r"(?is)\bDELETE\s+FROM\b"),
    re.compile(r"(?is)\bDROP\s+(TABLE|VIEW|SCHEMA|DATABASE)\b"),
    re.compile(r"(?is)\bALTER\s+TABLE\b"),
    re.compile(r"(?is)\bCREATE\s+(TABLE|VIEW|INDEX|SCHEMA)\b"),
    re.compile(r"(?is)\bCOPY\s+"),
    re.compile(r"(?is)\bATTACH\b"),
    re.compile(r"(?is)\bPRAGMA\b"),
    re.compile(r"(?is)\bEXECUTE\b"),
    re.compile(r"(?is)\bCALL\b"),
)

_SECRET_KEY_RE: Final[re.Pattern[str]] = re.compile(
    r"(?i)^(password|passwd|pwd|secret|token|api[_-]?key|authorization|"
    r"private[_-]?key|mnemonic|seed|signing|credential|bearer)$"
)

_SAFE_TOKEN_RE: Final[re.Pattern[str]] = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9_.:/@+-]{0,127}$"
)

_REDACTION_MARKER: Final[str] = "***REDACTED***"
_MAX_DETAIL_BYTES: Final[int] = 1024
_MAX_ATTR_KEYS: Final[int] = 64

_ALLOWED_OUTCOMES: Final[frozenset[str]] = frozenset(
    {
        "allowed",
        "denied",
        "succeeded",
        "failed",
        "error",
        "info",
    }
)


class ObservabilityShadowError(ValueError):
    """Fail-closed rejection for observability adapter inputs or routing."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _normalize_recorded_at(value: str | None) -> str:
    """Normalize producer timestamps to UTC ``...Z`` form.

    Legacy producers often emit naive ISO timestamps via ``datetime.utcnow()``.
    The typed catalog requires timezone-aware UTC; we coerce rather than fail.
    """

    if value is None or not str(value).strip():
        return _utc_now()
    text = str(value).strip()
    try:
        return normalize_timestamp(text)
    except Exception:
        pass
    # Append Z for naive ISO-like strings (legacy utcnow().isoformat()).
    if text.endswith("Z") or "+" in text[10:] or text.endswith("UTC"):
        try:
            return normalize_timestamp(text.replace("UTC", "+00:00"))
        except Exception:
            return _utc_now()
    try:
        return normalize_timestamp(text + "Z")
    except Exception:
        return _utc_now()


def sanitize_action_token(value: Any, *, default: str = "event") -> str:
    """Coerce free-form action text into a safe audit action token."""

    text = str(value if value is not None else default).strip()
    if not text:
        text = default
    # Collapse whitespace and unsafe characters.
    cleaned = re.sub(r"[^A-Za-z0-9_.:/@+-]+", "_", text)
    cleaned = cleaned.strip("._-") or default
    if len(cleaned) > 128:
        cleaned = cleaned[:128]
    if not _SAFE_TOKEN_RE.fullmatch(cleaned):
        # Fallback: content-hash token.
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:24]
        cleaned = f"act-{digest}"
    return cleaned


def sanitize_actor_token(value: Any, *, default: str = "system") -> str:
    """Coerce actor identifiers into safe tokens."""

    return sanitize_action_token(value, default=default)


def _is_unrestricted_sql(text: str) -> bool:
    if not text or not isinstance(text, str):
        return False
    return any(pat.search(text) for pat in _UNRESTRICTED_SQL_RE)


def _looks_like_secret_key(key: str) -> bool:
    return bool(_SECRET_KEY_RE.fullmatch(str(key).strip()))


def redact_event_payload(
    payload: Mapping[str, Any] | None,
    *,
    classification: SensitivityClass | str | None = None,
) -> tuple[dict[str, Any], SensitivityClass]:
    """Redact secrets and unrestricted SQL from a producer payload.

    Returns ``(redacted_payload, effective_classification)``. SECRET material
    is refused for persistence of plaintext values (keys replaced with marker
    and classification escalated to REDACTED for the stored projection).
    """

    klass = SensitivityClass.INTERNAL
    if classification is not None:
        if isinstance(classification, SensitivityClass):
            klass = classification
        else:
            try:
                klass = SensitivityClass(str(classification).strip().lower())
            except ValueError as exc:
                raise ObservabilityShadowError(
                    f"invalid sensitivity classification {classification!r}"
                ) from exc

    if payload is None:
        return {}, klass

    if not isinstance(payload, Mapping):
        raise ObservabilityShadowError("payload must be a mapping")

    redacted: dict[str, Any] = {}
    escalated = klass

    for key, value in payload.items():
        name = str(key)
        if _looks_like_secret_key(name):
            redacted[name] = _REDACTION_MARKER
            if escalated is not SensitivityClass.SECRET:
                escalated = SensitivityClass.REDACTED
            continue

        if isinstance(value, str):
            text = value
            if _is_unrestricted_sql(text):
                # Unrestricted SQL is never retained as plaintext — only a
                # digest of the original text and a redaction marker.
                _, _, digest = classify_and_redact_query_text(
                    text, classification=SensitivityClass.REDACTED
                )
                redacted[name] = f"[sql-redacted:{digest}]"
                redacted[f"{name}__sql_digest"] = digest
                if escalated in {
                    SensitivityClass.PUBLIC,
                    SensitivityClass.INTERNAL,
                    SensitivityClass.SECRET,
                }:
                    escalated = SensitivityClass.REDACTED
            else:
                cleaned = redact_sensitive_text(text)
                if cleaned != text and escalated is SensitivityClass.INTERNAL:
                    escalated = SensitivityClass.REDACTED
                redacted[name] = cleaned
        elif isinstance(value, Mapping):
            nested, nested_klass = redact_event_payload(
                value, classification=escalated
            )
            redacted[name] = nested
            if nested_klass is SensitivityClass.REDACTED and escalated in {
                SensitivityClass.PUBLIC,
                SensitivityClass.INTERNAL,
            }:
                escalated = SensitivityClass.REDACTED
        elif isinstance(value, (list, tuple)):
            items: list[Any] = []
            for item in value:
                if isinstance(item, str):
                    if _is_unrestricted_sql(item):
                        _, _, digest = classify_and_redact_query_text(
                            item, classification=SensitivityClass.REDACTED
                        )
                        items.append(
                            {
                                "sql_redacted": f"[sql-redacted:{digest}]",
                                "sql_digest": digest,
                            }
                        )
                        if escalated in {
                            SensitivityClass.PUBLIC,
                            SensitivityClass.INTERNAL,
                        }:
                            escalated = SensitivityClass.REDACTED
                    else:
                        cleaned = redact_sensitive_text(item)
                        if cleaned != item and escalated is SensitivityClass.INTERNAL:
                            escalated = SensitivityClass.REDACTED
                        items.append(cleaned)
                elif isinstance(item, Mapping):
                    nested, nested_klass = redact_event_payload(
                        item, classification=escalated
                    )
                    items.append(nested)
                    if nested_klass is SensitivityClass.REDACTED and escalated in {
                        SensitivityClass.PUBLIC,
                        SensitivityClass.INTERNAL,
                    }:
                        escalated = SensitivityClass.REDACTED
                else:
                    items.append(item)
            redacted[name] = items
        else:
            redacted[name] = value

    # Catalog refuses SECRET plaintext — never publish SECRET classification.
    if escalated is SensitivityClass.SECRET:
        escalated = SensitivityClass.REDACTED

    return redacted, escalated


def derive_stable_event_id(
    *,
    producer: str,
    action: str,
    actor: str = "system",
    resource: str = "",
    detail: str = "",
    source_revision: str = OBSERVABILITY_SOURCE_REVISION,
    seed: str | None = None,
) -> str:
    """Derive a deterministic, retry-stable event ID.

    When ``seed`` is provided it is the sole identity input (callers that
    already hold a UUID / operation id should pass it as seed so restarts
    reuse the same event).
    """

    if seed is not None and str(seed).strip():
        text = str(seed).strip()
        # Prefer caller-provided IDs when already safe tokens.
        if _SAFE_TOKEN_RE.fullmatch(text) and len(text) <= 128:
            return text
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:28]
        return f"evt-{digest}"

    material = {
        "producer": str(producer),
        "action": str(action),
        "actor": str(actor),
        "resource": str(resource or ""),
        "detail": str(detail or ""),
        "source_revision": str(source_revision),
    }
    digest = hashlib.sha256(canonical_json_bytes(material)).hexdigest()[:28]
    return f"evt-{digest}"


def _flatten_attributes(
    payload: Mapping[str, Any],
    *,
    prefix: str = "",
    out: MutableMapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Flatten nested maps to scalar attributes for AuditRecord storage."""

    result: dict[str, Any] = out if out is not None else {}
    for key, value in payload.items():
        name = f"{prefix}{key}" if not prefix else f"{prefix}.{key}"
        # Attribute keys must be safe tokens (no dots in catalog keys).
        safe_name = re.sub(r"[^A-Za-z0-9_.:/@+-]+", "_", name)
        safe_name = safe_name.strip("._-") or "attr"
        if len(safe_name) > 128:
            safe_name = safe_name[:128]
        if isinstance(value, Mapping):
            _flatten_attributes(value, prefix=safe_name, out=result)
        elif isinstance(value, (list, tuple)):
            # Store count + compact JSON digest rather than nested lists.
            try:
                result[f"{safe_name}_count"] = len(value)
                result[f"{safe_name}_digest"] = content_identity(list(value))
            except Exception:  # noqa: BLE001 — best-effort scalar projection
                result[f"{safe_name}_count"] = len(value)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            if isinstance(value, str) and len(value.encode("utf-8")) > 1024:
                result[safe_name] = value.encode("utf-8")[:1024].decode(
                    "utf-8", errors="ignore"
                )
            elif isinstance(value, float) and (
                value != value or value in (float("inf"), float("-inf"))
            ):
                continue
            else:
                result[safe_name] = value
        else:
            result[safe_name] = str(value)[:256]
        if len(result) >= _MAX_ATTR_KEYS:
            break
    # Cap key count.
    if len(result) > _MAX_ATTR_KEYS:
        keys = sorted(result.keys())[:_MAX_ATTR_KEYS]
        result = {k: result[k] for k in keys}
    return result


def _normalize_outcome(value: Any) -> str:
    text = str(value or "info").strip().lower()
    mapping = {
        "success": "succeeded",
        "ok": "succeeded",
        "true": "succeeded",
        "failure": "failed",
        "fail": "failed",
        "false": "failed",
        "reject": "denied",
        "rejected": "denied",
        "allow": "allowed",
        "deny": "denied",
        "triggered": "info",
        "warning": "info",
        "critical": "error",
    }
    text = mapping.get(text, text)
    if text not in _ALLOWED_OUTCOMES:
        return "info"
    return text


def _producer_value(producer: ObservabilityProducer | str) -> str:
    if isinstance(producer, ObservabilityProducer):
        return producer.value
    text = str(producer).strip()
    # Accept enum names or values.
    for member in ObservabilityProducer:
        if text == member.value or text == member.name:
            return member.value
    if text in PRODUCER_SCHEMAS:
        return text
    raise ObservabilityShadowError(
        f"unknown observability producer {producer!r}; "
        f"expected one of {sorted(PRODUCER_SCHEMAS)}"
    )


def _domain_for_producer(producer: str) -> TraceDomain:
    if "graphrag" in producer or "pipeline" in producer:
        return TraceDomain.GRAPH
    if "security" in producer or "audit" in producer:
        return TraceDomain.SYSTEM
    if "mcp" in producer:
        return TraceDomain.CONTROL
    if "alert" in producer:
        return TraceDomain.SYSTEM
    if "structured" in producer:
        return TraceDomain.OBSERVABILITY
    return TraceDomain.OBSERVABILITY


# ---------------------------------------------------------------------------
# Evidence blob store (outside DuckDB)
# ---------------------------------------------------------------------------


class EvidenceBlobStore:
    """Protocol-like base for content-addressed evidence outside DuckDB."""

    def put(self, data: bytes, *, media_type: ContentMediaType = ContentMediaType.JSON) -> ContentReference:
        raise NotImplementedError

    def get(self, content_id: str) -> bytes | None:
        raise NotImplementedError

    def contains(self, content_id: str) -> bool:
        raise NotImplementedError

    def __len__(self) -> int:
        raise NotImplementedError


class MemoryEvidenceBlobStore(EvidenceBlobStore):
    """Hermetic in-process content-addressed evidence store.

    Bytes live only in this map — never inside the observability catalog or
    authority-transition DuckDB projection.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._blobs: dict[str, bytes] = {}
        self._refs: dict[str, ContentReference] = {}

    def put(
        self,
        data: bytes,
        *,
        media_type: ContentMediaType = ContentMediaType.JSON,
    ) -> ContentReference:
        if not isinstance(data, (bytes, bytearray)):
            raise ObservabilityShadowError("evidence blob must be bytes")
        raw = bytes(data)
        ref = ContentReference.from_bytes(raw, media_type=media_type)
        with self._lock:
            self._blobs[ref.content_id] = raw
            self._refs[ref.content_id] = ref
        return ref

    def get(self, content_id: str) -> bytes | None:
        with self._lock:
            return self._blobs.get(content_id)

    def contains(self, content_id: str) -> bool:
        with self._lock:
            return content_id in self._blobs

    def __len__(self) -> int:
        with self._lock:
            return len(self._blobs)

    def reference(self, content_id: str) -> ContentReference | None:
        with self._lock:
            return self._refs.get(content_id)


# ---------------------------------------------------------------------------
# Event receipt
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ObservabilityEventReceipt:
    """Receipt for one routed producer event (typed + parity + evidence)."""

    SCHEMA: ClassVar[str] = OBSERVABILITY_EVENT_RECEIPT_SCHEMA

    event_id: str
    operation_id: str
    producer: str
    producer_schema: str
    catalog_schema: str
    classification: str
    source_revision: str
    parity_receipt_cid: str
    parity_matched: bool
    evidence_cid: str
    evidence_digest: str
    catalog_family: str
    sequence: int
    action: str
    actor: str
    outcome: str
    mode: str
    idempotent_replay: bool
    authority: str
    recorded_at: str
    detail: str = ""
    resource: str = ""
    payload_digest: str = ""
    outbox_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": OBSERVABILITY_EVENT_RECEIPT_SCHEMA,
            "event_id": self.event_id,
            "operation_id": self.operation_id,
            "producer": self.producer,
            "producer_schema": self.producer_schema,
            "catalog_schema": self.catalog_schema,
            "classification": self.classification,
            "source_revision": self.source_revision,
            "parity_receipt_cid": self.parity_receipt_cid,
            "parity_matched": self.parity_matched,
            "evidence_cid": self.evidence_cid,
            "evidence_digest": self.evidence_digest,
            "catalog_family": self.catalog_family,
            "sequence": self.sequence,
            "action": self.action,
            "actor": self.actor,
            "outcome": self.outcome,
            "mode": self.mode,
            "idempotent_replay": self.idempotent_replay,
            "authority": self.authority,
            "recorded_at": self.recorded_at,
            "detail": self.detail,
            "resource": self.resource,
            "payload_digest": self.payload_digest,
            "outbox_id": self.outbox_id,
        }

    @property
    def identity_id(self) -> str:
        return content_identity(self.to_dict())


# ---------------------------------------------------------------------------
# Shadow repository
# ---------------------------------------------------------------------------


class ObservabilityShadowRepository:
    """Route producer events through typed catalog + shadow authority.

    Authority model (default :attr:`AuthorityMode.SHADOW`):

    * **Legacy authority** — redacted event projections written via the
      authority port's legacy surface (file-sink stand-in in hermetic tests).
    * **Typed catalog shadow** — :class:`ObservabilityCatalog` audit family
      holds the same redacted projection with sequence authority.
    * **Evidence** — immutable raw (or already-redacted) blobs are content-
      addressed only in :class:`EvidenceBlobStore`, never DuckDB.
    * **Parity** — every mutation emits a :class:`ParityReceipt` comparing
      legacy and DB digests of the redacted projection.
    """

    def __init__(
        self,
        *,
        mode: AuthorityMode | str = AuthorityMode.SHADOW,
        backend: AuthorityBackend | None = None,
        catalog: ObservabilityCatalog | None = None,
        evidence_store: EvidenceBlobStore | None = None,
        source_revision: str = OBSERVABILITY_SOURCE_REVISION,
        domain: str = OBSERVABILITY_SHADOW_DOMAIN,
        writer_id: str = "writer:observability-shadow",
        clock: Callable[[], str] | None = None,
        enabled: bool = True,
    ) -> None:
        self._enabled = bool(enabled)
        self._source_revision = str(source_revision or OBSERVABILITY_SOURCE_REVISION)
        self._clock = clock or _utc_now
        self._lock = threading.RLock()
        self._receipts: dict[str, ObservabilityEventReceipt] = {}
        self._event_index: dict[str, ObservabilityEventReceipt] = {}

        mode_enum = (
            mode
            if isinstance(mode, AuthorityMode)
            else AuthorityMode.parse(str(mode))
        )
        # Shadow mode is the only admitted default for DQK-077; promote later.
        if mode_enum not in {
            AuthorityMode.LEGACY,
            AuthorityMode.SHADOW,
            AuthorityMode.DUAL,
        }:
            raise ObservabilityShadowError(
                f"DQK-077 admits only legacy|shadow|dual; got {mode_enum.value!r}"
            )
        self._mode = mode_enum
        self._backend = backend if backend is not None else MemoryAuthorityBackend()
        self._port = build_authority_port(
            self._backend,
            domain=domain,
            initial_mode=mode_enum,
            writer_id=writer_id,
        )
        self._catalog = catalog if catalog is not None else open_memory_catalog(clock=self._clock)
        self._evidence = (
            evidence_store
            if evidence_store is not None
            else MemoryEvidenceBlobStore()
        )
        self._domain = domain

    # -- properties ---------------------------------------------------------

    @property
    def interface(self) -> str:
        return OBSERVABILITY_SHADOW_INTERFACE

    @property
    def schema(self) -> str:
        return OBSERVABILITY_ADAPTER_SCHEMA

    @property
    def owner_task(self) -> str:
        return OBSERVABILITY_SHADOW_OWNER_TASK

    @property
    def source_revision(self) -> str:
        return self._source_revision

    @property
    def mode(self) -> AuthorityMode:
        return self._port.mode

    @property
    def enabled(self) -> bool:
        return self._enabled

    @property
    def authority_port(self) -> AuthorityTransitionPort:
        return self._port

    @property
    def catalog(self) -> ObservabilityCatalog:
        return self._catalog

    @property
    def evidence_store(self) -> EvidenceBlobStore:
        return self._evidence

    @property
    def domain(self) -> str:
        return self._domain

    def list_receipts(self) -> tuple[ObservabilityEventReceipt, ...]:
        with self._lock:
            return tuple(self._receipts.values())

    def get_receipt(self, event_id: str) -> ObservabilityEventReceipt | None:
        with self._lock:
            return self._event_index.get(event_id) or self._receipts.get(event_id)

    # -- core write path ----------------------------------------------------

    def record_event(
        self,
        *,
        producer: ObservabilityProducer | str,
        action: str,
        actor: str = "system",
        outcome: str = "info",
        detail: str = "",
        attributes: Mapping[str, Any] | None = None,
        event_id: str | None = None,
        operation_id: str | None = None,
        classification: SensitivityClass | str | None = None,
        resource: str = "",
        domain: TraceDomain | str | None = None,
        raw_payload: Mapping[str, Any] | bytes | str | None = None,
        recorded_at: str | None = None,
        correlation: CorrelationIds | Mapping[str, Any] | None = None,
        source_revision: str | None = None,
    ) -> ObservabilityEventReceipt:
        """Record one producer event with typed schema + parity + evidence.

        Idempotent: the same ``event_id`` / ``operation_id`` returns the prior
        receipt without appending a second catalog row.
        """

        if not self._enabled:
            raise ObservabilityShadowError("observability shadow repository is disabled")

        producer_key = _producer_value(producer)
        producer_schema = PRODUCER_SCHEMAS[producer_key]
        rev = str(source_revision or self._source_revision)
        action_token = sanitize_action_token(action)
        actor_token = sanitize_actor_token(actor)
        outcome_token = _normalize_outcome(outcome)
        resource_token = (
            sanitize_action_token(resource, default="") if resource else ""
        )

        # Merge attributes + detail for redaction.
        attr_map: dict[str, Any] = dict(attributes or {})
        if detail:
            attr_map.setdefault("detail_text", str(detail))

        redacted_attrs, klass = redact_event_payload(
            attr_map, classification=classification
        )
        detail_text = str(redacted_attrs.pop("detail_text", detail or ""))
        detail_text = redact_sensitive_text(detail_text)
        # Re-check original detail for unrestricted SQL (redact_sensitive_text
        # may leave SQL structure intact).
        if _is_unrestricted_sql(detail) or _is_unrestricted_sql(detail_text):
            original_for_digest = str(detail or detail_text)
            _, _, qdigest = classify_and_redact_query_text(
                original_for_digest, classification=SensitivityClass.REDACTED
            )
            detail_text = f"[sql-redacted:{qdigest}]"
            redacted_attrs["detail_sql_digest"] = qdigest
            if klass in {
                SensitivityClass.PUBLIC,
                SensitivityClass.INTERNAL,
                SensitivityClass.SECRET,
            }:
                klass = SensitivityClass.REDACTED
        if len(detail_text.encode("utf-8")) > _MAX_DETAIL_BYTES:
            detail_text = detail_text.encode("utf-8")[:_MAX_DETAIL_BYTES].decode(
                "utf-8", errors="ignore"
            )

        stable_id = derive_stable_event_id(
            producer=producer_key,
            action=action_token,
            actor=actor_token,
            resource=resource_token,
            detail=detail_text,
            source_revision=rev,
            seed=event_id,
        )
        op_id = (
            sanitize_action_token(operation_id, default=f"op-{stable_id}")
            if operation_id
            else f"op-{stable_id}"
        )

        with self._lock:
            prior = self._event_index.get(stable_id) or self._receipts.get(op_id)
            if prior is not None:
                return ObservabilityEventReceipt(
                    event_id=prior.event_id,
                    operation_id=prior.operation_id,
                    producer=prior.producer,
                    producer_schema=prior.producer_schema,
                    catalog_schema=prior.catalog_schema,
                    classification=prior.classification,
                    source_revision=prior.source_revision,
                    parity_receipt_cid=prior.parity_receipt_cid,
                    parity_matched=prior.parity_matched,
                    evidence_cid=prior.evidence_cid,
                    evidence_digest=prior.evidence_digest,
                    catalog_family=prior.catalog_family,
                    sequence=prior.sequence,
                    action=prior.action,
                    actor=prior.actor,
                    outcome=prior.outcome,
                    mode=prior.mode,
                    idempotent_replay=True,
                    authority=prior.authority,
                    recorded_at=prior.recorded_at,
                    detail=prior.detail,
                    resource=prior.resource,
                    payload_digest=prior.payload_digest,
                    outbox_id=prior.outbox_id,
                )

            # Evidence blob: content-addressed outside DuckDB.
            evidence_bytes = self._serialize_evidence(
                raw_payload=raw_payload,
                producer=producer_key,
                action=action_token,
                actor=actor_token,
                detail=detail,
                attributes=dict(attributes or {}),
                event_id=stable_id,
                source_revision=rev,
            )
            evidence_ref = self._evidence.put(
                evidence_bytes, media_type=ContentMediaType.JSON
            )

            # Projection written to authority port (legacy + shadow DB).
            # Never embeds raw secret/SQL plaintext — only redacted fields +
            # evidence content reference.
            flat_attrs = _flatten_attributes(redacted_attrs)
            flat_attrs["source_revision"] = rev
            flat_attrs["producer"] = producer_key
            flat_attrs["producer_schema"] = producer_schema
            flat_attrs["evidence_cid"] = evidence_ref.content_id
            flat_attrs["evidence_digest"] = evidence_ref.source_digest
            flat_attrs["evidence_byte_size"] = evidence_ref.byte_size

            projection = {
                "schema": producer_schema,
                "adapter_schema": OBSERVABILITY_ADAPTER_SCHEMA,
                "event_id": stable_id,
                "operation_id": op_id,
                "producer": producer_key,
                "action": action_token,
                "actor": actor_token,
                "outcome": outcome_token,
                "resource": resource_token,
                "classification": klass.value,
                "source_revision": rev,
                "detail": detail_text,
                "attributes": flat_attrs,
                "evidence_cid": evidence_ref.content_id,
                "evidence_digest": evidence_ref.source_digest,
                "evidence_byte_size": evidence_ref.byte_size,
                "recorded_at": _normalize_recorded_at(
                    recorded_at if recorded_at is not None else self._clock()
                ),
                "owner_task": OBSERVABILITY_SHADOW_OWNER_TASK,
            }
            # Defense in depth: never allow secret-bearing keys into projection.
            projection, proj_klass = redact_event_payload(
                projection, classification=klass
            )
            if proj_klass is SensitivityClass.REDACTED:
                klass = SensitivityClass.REDACTED
                projection["classification"] = klass.value

            payload_digest = compute_payload_digest(projection)
            key = f"obs:{producer_key}:{stable_id}"

            write_result = self._port.write(key, projection, operation_id=op_id)
            parity = self._port.emit_parity_receipt(key, operation_id=op_id)

            # Typed catalog append (idempotent via natural event_id).
            existing = self._catalog.get(CatalogFamily.AUDIT_EVENTS, stable_id)
            if existing is not None:
                sequence = int(getattr(existing, "sequence", 0) or 0)
            else:
                corr = self._build_correlation(
                    correlation, event_id=stable_id, producer=producer_key
                )
                try:
                    record = self._catalog.record_audit(
                        action=action_token,
                        actor=actor_token,
                        outcome=outcome_token,
                        event_id=stable_id,
                        correlation=corr,
                        resource=resource_token,
                        domain=domain or _domain_for_producer(producer_key),
                        classification=klass,
                        detail=detail_text,
                        attributes=flat_attrs,
                        recorded_at=projection.get("recorded_at") or self._clock(),
                    )
                    sequence = int(record.sequence)
                except ObservabilityError as exc:
                    # Duplicate after concurrent insert — treat as replay.
                    existing = self._catalog.get(
                        CatalogFamily.AUDIT_EVENTS, stable_id
                    )
                    if existing is None:
                        raise ObservabilityShadowError(
                            f"catalog append failed: {exc}"
                        ) from exc
                    sequence = int(getattr(existing, "sequence", 0) or 0)

            receipt = ObservabilityEventReceipt(
                event_id=stable_id,
                operation_id=op_id,
                producer=producer_key,
                producer_schema=producer_schema,
                catalog_schema=AUDIT_RECORD_SCHEMA,
                classification=klass.value,
                source_revision=rev,
                parity_receipt_cid=parity.receipt_cid,
                parity_matched=bool(parity.matched),
                evidence_cid=evidence_ref.content_id,
                evidence_digest=evidence_ref.source_digest,
                catalog_family=CatalogFamily.AUDIT_EVENTS.value,
                sequence=sequence,
                action=action_token,
                actor=actor_token,
                outcome=outcome_token,
                mode=str(write_result.get("mode") or self._port.mode.value),
                idempotent_replay=bool(write_result.get("idempotent_replay")),
                authority=str(write_result.get("authority") or "legacy"),
                recorded_at=str(projection.get("recorded_at") or self._clock()),
                detail=detail_text,
                resource=resource_token,
                payload_digest=str(
                    write_result.get("payload_digest") or payload_digest
                ),
                outbox_id=str(write_result.get("outbox_id") or ""),
            )
            self._receipts[op_id] = receipt
            self._event_index[stable_id] = receipt
            return receipt

    def _serialize_evidence(
        self,
        *,
        raw_payload: Mapping[str, Any] | bytes | str | None,
        producer: str,
        action: str,
        actor: str,
        detail: str,
        attributes: Mapping[str, Any],
        event_id: str,
        source_revision: str,
    ) -> bytes:
        """Serialize evidence for content-addressed storage.

        Secrets and unrestricted SQL are redacted *before* the blob is sealed
        so publication surfaces never re-expose them via the evidence store
        either. The blob remains immutable and content-addressed outside DuckDB.
        """

        if isinstance(raw_payload, (bytes, bytearray)):
            # Treat as opaque bytes; still scrub inline secrets when UTF-8 text.
            try:
                text = bytes(raw_payload).decode("utf-8")
            except UnicodeDecodeError:
                return bytes(raw_payload)
            cleaned = redact_sensitive_text(text)
            if _is_unrestricted_sql(text) or _is_unrestricted_sql(cleaned):
                _, _, digest = classify_and_redact_query_text(
                    text, classification=SensitivityClass.REDACTED
                )
                cleaned = f"[sql-redacted:{digest}]"
            return cleaned.encode("utf-8")

        if isinstance(raw_payload, str):
            cleaned = redact_sensitive_text(raw_payload)
            if _is_unrestricted_sql(raw_payload) or _is_unrestricted_sql(cleaned):
                _, _, digest = classify_and_redact_query_text(
                    raw_payload, classification=SensitivityClass.REDACTED
                )
                cleaned = f"[sql-redacted:{digest}]"
            return cleaned.encode("utf-8")

        body: dict[str, Any] = {
            "event_id": event_id,
            "producer": producer,
            "action": action,
            "actor": actor,
            "source_revision": source_revision,
            "detail": detail,
            "attributes": dict(attributes),
        }
        if isinstance(raw_payload, Mapping):
            body["payload"] = dict(raw_payload)
        redacted, _ = redact_event_payload(body)
        return canonical_json_bytes(redacted)

    def _build_correlation(
        self,
        correlation: CorrelationIds | Mapping[str, Any] | None,
        *,
        event_id: str,
        producer: str,
    ) -> CorrelationIds:
        if isinstance(correlation, CorrelationIds):
            return correlation
        if isinstance(correlation, Mapping) and correlation:
            try:
                return CorrelationIds(**dict(correlation))  # type: ignore[arg-type]
            except TypeError:
                # Best-effort: only pass known fields.
                known = {
                    k: v
                    for k, v in correlation.items()
                    if k in CorrelationIds.__dataclass_fields__  # type: ignore[attr-defined]
                }
                if known:
                    return CorrelationIds(**known)  # type: ignore[arg-type]
        return CorrelationIds(
            trace_id=f"trace-{event_id}"[:128],
            control_task_id=OBSERVABILITY_SHADOW_OWNER_TASK,
            control_goal_id="DQK-G1000",
        )

    # -- recovery / parity --------------------------------------------------

    def recover(self) -> dict[str, Any]:
        """Idempotently recover incomplete authority outbox entries."""

        return self._port.recover_outbox()

    def emit_parity(
        self, event_id: str, *, operation_id: str = ""
    ) -> ParityReceipt:
        """Re-emit parity for a previously recorded event projection key."""

        receipt = self.get_receipt(event_id)
        if receipt is None:
            raise ObservabilityShadowError(f"unknown event_id {event_id!r}")
        key = f"obs:{receipt.producer}:{receipt.event_id}"
        return self._port.emit_parity_receipt(
            key, operation_id=operation_id or receipt.operation_id
        )

    def counts(self) -> Mapping[str, int]:
        with self._lock:
            return MappingProxyType(
                {
                    "receipts": len(self._receipts),
                    "catalog_audit_events": len(
                        self._catalog.list_family(CatalogFamily.AUDIT_EVENTS)
                    ),
                    "evidence_blobs": len(self._evidence),
                }
            )


# ---------------------------------------------------------------------------
# Process-global registry
# ---------------------------------------------------------------------------

_GLOBAL_LOCK = threading.RLock()
_GLOBAL_SHADOW: ObservabilityShadowRepository | None = None


def build_observability_shadow_repository(
    *,
    mode: AuthorityMode | str = AuthorityMode.SHADOW,
    backend: AuthorityBackend | None = None,
    catalog: ObservabilityCatalog | None = None,
    evidence_store: EvidenceBlobStore | None = None,
    source_revision: str = OBSERVABILITY_SOURCE_REVISION,
    set_global: bool = False,
    enabled: bool = True,
    clock: Callable[[], str] | None = None,
) -> ObservabilityShadowRepository:
    """Construct a shadow repository; optionally install as process global."""

    repo = ObservabilityShadowRepository(
        mode=mode,
        backend=backend,
        catalog=catalog,
        evidence_store=evidence_store,
        source_revision=source_revision,
        enabled=enabled,
        clock=clock,
    )
    if set_global:
        with _GLOBAL_LOCK:
            global _GLOBAL_SHADOW
            _GLOBAL_SHADOW = repo
    return repo


def configure_observability_shadow(
    *,
    mode: AuthorityMode | str = AuthorityMode.SHADOW,
    backend: AuthorityBackend | None = None,
    catalog: ObservabilityCatalog | None = None,
    evidence_store: EvidenceBlobStore | None = None,
    source_revision: str = OBSERVABILITY_SOURCE_REVISION,
    enabled: bool = True,
    clock: Callable[[], str] | None = None,
) -> ObservabilityShadowRepository:
    """Install (or replace) the process-global observability shadow repository."""

    return build_observability_shadow_repository(
        mode=mode,
        backend=backend,
        catalog=catalog,
        evidence_store=evidence_store,
        source_revision=source_revision,
        set_global=True,
        enabled=enabled,
        clock=clock,
    )


def get_observability_shadow() -> ObservabilityShadowRepository | None:
    """Return the process-global shadow repository, if configured."""

    with _GLOBAL_LOCK:
        return _GLOBAL_SHADOW


def clear_observability_shadow() -> None:
    """Clear the process-global shadow repository (test / shutdown)."""

    with _GLOBAL_LOCK:
        global _GLOBAL_SHADOW
        _GLOBAL_SHADOW = None


def reset_observability_shadow() -> None:
    """Alias for :func:`clear_observability_shadow`."""

    clear_observability_shadow()


def record_observability_event(
    *,
    producer: ObservabilityProducer | str,
    action: str,
    actor: str = "system",
    outcome: str = "info",
    detail: str = "",
    attributes: Mapping[str, Any] | None = None,
    event_id: str | None = None,
    operation_id: str | None = None,
    classification: SensitivityClass | str | None = None,
    resource: str = "",
    domain: TraceDomain | str | None = None,
    raw_payload: Mapping[str, Any] | bytes | str | None = None,
    recorded_at: str | None = None,
    correlation: CorrelationIds | Mapping[str, Any] | None = None,
    source_revision: str | None = None,
) -> ObservabilityEventReceipt | None:
    """Route an event through the global shadow repository when configured.

    Returns ``None`` when shadow mode is not configured (producers keep their
    legacy sinks as sole authority). Never raises for routing failures from
    producers — errors are swallowed after best-effort logging so legacy
    sinks remain operational.
    """

    repo = get_observability_shadow()
    if repo is None or not repo.enabled:
        return None
    try:
        return repo.record_event(
            producer=producer,
            action=action,
            actor=actor,
            outcome=outcome,
            detail=detail,
            attributes=attributes,
            event_id=event_id,
            operation_id=operation_id,
            classification=classification,
            resource=resource,
            domain=domain,
            raw_payload=raw_payload,
            recorded_at=recorded_at,
            correlation=correlation,
            source_revision=source_revision,
        )
    except Exception:  # noqa: BLE001 — never break legacy producers
        return None
