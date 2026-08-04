"""Runtime public-sink enforcement for USPTO privacy and export-control assurance.

Hardens the isolation boundary beyond classification alone: every dispatch to a
public surface (IPFS DHT/gateway/pin, public datasets, embedding indexes,
remote models, caches, logs, traces, telemetry, and error surfaces) is gated
by disclosure classification, tenant policy, publication state, and
export-control / secrecy-order state.

Fail-closed defaults:

* unknown publication or export-control state quarantines and denies dispatch;
* restricted export-review and secrecy-order material is denied until human
  clearance is recorded;
* external-model use over private material is denied by default;
* audit, log, telemetry, and error surfaces carry digests and reason codes
  only — never private bytes, text, embeddings, or CIDs.

This module is the enforcement adapter. The classification policy engine lives
in :mod:`ipfs_datasets_py.processors.domains.uspto.privacy`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Final, Iterable, Mapping, Sequence

from .contracts import (
    DisclosureClassification,
    is_private_classification,
    is_public_classification,
)
from .privacy import (
    DEFAULT_PRIVACY_POLICY,
    ContentKind,
    PrivacyBoundaryError,
    PublicSink,
    QuarantineRecord,
    SinkAdmissionDecision,
    SinkDecisionCode,
    UsptoPrivacyPolicy,
)

PRIVACY_SINKS_SCHEMA_VERSION: Final = "uspto.privacy_sinks.v1"
PRIVACY_SINKS_INTERFACE: Final = "UsptoPublicSinkEnforcer@1"


# ---------------------------------------------------------------------------
# Fine-grained public channels reachable from USPTO processors
# ---------------------------------------------------------------------------


class SinkChannel(str, Enum):
    """Enumerated public surfaces that must never receive private substance.

    Coarser :class:`PublicSink` values from the privacy policy are reused for
    admission; channels record the exact surface under test (DHT vs gateway vs
    pin, error vs log, embedding index, etc.).
    """

    PUBLIC_IPFS_DHT = "public_ipfs_dht"
    PUBLIC_IPFS_GATEWAY = "public_ipfs_gateway"
    PUBLIC_IPFS_PIN = "public_ipfs_pin"
    PUBLIC_DATASET = "public_dataset"
    JUSTICE_DAO = "justice_dao_hugging_face"
    PUBLIC_CACHE = "public_cache"
    EMBEDDING_INDEX = "embedding_index"
    REMOTE_MODEL = "remote_model"
    LOGS = "logs"
    TELEMETRY = "telemetry"
    TRACE = "trace"
    ERROR_SURFACE = "error_surface"


class PublicationState(str, Enum):
    """Declared publication / 35 USC 122 confidentiality state."""

    PUBLIC = "public"
    PRIVATE_UNPUBLISHED = "private_unpublished"
    EXPORT_REVIEW_PENDING = "export_review_pending"
    SECRECY_ORDER = "secrecy_order"
    UNKNOWN = "unknown"


class ExportControlState(str, Enum):
    """Export-control / secrecy-order review disposition."""

    CLEARED = "cleared"
    RESTRICTED = "restricted"
    SECRECY_ORDER = "secrecy_order"
    PENDING_REVIEW = "pending_review"
    UNKNOWN = "unknown"


class EnforcementDecisionCode(str, Enum):
    """High-level enforcement outcomes for sink dispatch and export gates."""

    ALLOWED = "allowed"
    DENIED_PRIVATE = "denied_private"
    DENIED_QUARANTINE = "denied_quarantine"
    DENIED_EXPORT_CONTROL = "denied_export_control"
    DENIED_SECRECY_ORDER = "denied_secrecy_order"
    DENIED_EXTERNAL_MODEL = "denied_external_model"
    DENIED_TENANT_ISOLATION = "denied_tenant_isolation"
    DENIED_UNKNOWN_PUBLICATION = "denied_unknown_publication"
    DENIED_UNKNOWN_EXPORT_STATE = "denied_unknown_export_state"
    DENIED_CREDENTIAL = "denied_credential"
    DENIED_CHANNEL = "denied_channel"
    DENIED_CONTENT_KIND = "denied_content_kind"


# Map fine-grained channels onto the privacy-policy PublicSink surface.
_CHANNEL_TO_PUBLIC_SINK: Final[Mapping[SinkChannel, PublicSink]] = MappingProxyType(
    {
        SinkChannel.PUBLIC_IPFS_DHT: PublicSink.PUBLIC_IPFS,
        SinkChannel.PUBLIC_IPFS_GATEWAY: PublicSink.PUBLIC_IPFS,
        SinkChannel.PUBLIC_IPFS_PIN: PublicSink.PUBLIC_IPFS,
        SinkChannel.PUBLIC_DATASET: PublicSink.PUBLIC_DATASET,
        SinkChannel.JUSTICE_DAO: PublicSink.JUSTICE_DAO,
        SinkChannel.PUBLIC_CACHE: PublicSink.PUBLIC_CACHE,
        SinkChannel.EMBEDDING_INDEX: PublicSink.PUBLIC_DATASET,
        SinkChannel.REMOTE_MODEL: PublicSink.REMOTE_PROMPT,
        SinkChannel.LOGS: PublicSink.LOGS,
        SinkChannel.TELEMETRY: PublicSink.TELEMETRY,
        SinkChannel.TRACE: PublicSink.TELEMETRY,
        SinkChannel.ERROR_SURFACE: PublicSink.LOGS,
    }
)

_IPFS_CHANNELS: Final[frozenset[SinkChannel]] = frozenset(
    {
        SinkChannel.PUBLIC_IPFS_DHT,
        SinkChannel.PUBLIC_IPFS_GATEWAY,
        SinkChannel.PUBLIC_IPFS_PIN,
    }
)

_OBSERVABILITY_CHANNELS: Final[frozenset[SinkChannel]] = frozenset(
    {
        SinkChannel.LOGS,
        SinkChannel.TELEMETRY,
        SinkChannel.TRACE,
        SinkChannel.ERROR_SURFACE,
    }
)

_SUBSTANTIVE_KINDS: Final[frozenset[ContentKind]] = frozenset(
    {
        ContentKind.DOCUMENT_BYTES,
        ContentKind.EXTRACTED_TEXT,
        ContentKind.EMBEDDING,
        ContentKind.CONTENT_IDENTIFIER,
        ContentKind.GRAPH_CONTENT,
        ContentKind.CREDENTIAL_SECRET,
    }
)

# Payload keys that must never appear in audit/log/telemetry/error projections.
_FORBIDDEN_PAYLOAD_KEYS: Final[frozenset[str]] = frozenset(
    {
        "bytes",
        "raw_bytes",
        "payload",
        "body",
        "content",
        "text",
        "extracted_text",
        "embedding",
        "embeddings",
        "vector",
        "vectors",
        "cid",
        "private_cid",
        "content_id",
        "prompt",
        "password",
        "api_key",
        "token",
        "secret",
        "ciphertext",
    }
)


def channel_to_public_sink(channel: SinkChannel | str) -> PublicSink:
    """Resolve a fine-grained channel to the privacy-policy PublicSink."""
    ch = channel if isinstance(channel, SinkChannel) else SinkChannel(str(channel))
    try:
        return _CHANNEL_TO_PUBLIC_SINK[ch]
    except KeyError as exc:  # pragma: no cover - enum exhaustiveness
        raise ValueError(f"unmapped sink channel: {ch!r}") from exc


def all_sink_channels() -> tuple[SinkChannel, ...]:
    """Return every enumerated public channel (stable order)."""
    return tuple(SinkChannel)


def all_ipfs_public_channels() -> tuple[SinkChannel, ...]:
    """Public IPFS DHT, gateway, and pin announcement surfaces."""
    return (
        SinkChannel.PUBLIC_IPFS_DHT,
        SinkChannel.PUBLIC_IPFS_GATEWAY,
        SinkChannel.PUBLIC_IPFS_PIN,
    )


# ---------------------------------------------------------------------------
# Request / result records
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SinkDispatchRequest:
    """A proposed dispatch of material to a public channel.

    The *payload* may hold private substance for the enforcer to refuse; it is
    never copied into audit, log, or telemetry records.
    """

    tenant_id: str
    classification: DisclosureClassification | str
    channel: SinkChannel | str
    content_kind: ContentKind | str
    publication_state: PublicationState | str = PublicationState.UNKNOWN
    export_control_state: ExportControlState | str = ExportControlState.UNKNOWN
    payload: Any = None
    matter_id: str | None = None
    artifact_id: str | None = None
    digest: str | None = None
    source_classifications: tuple[DisclosureClassification | str, ...] = ()
    secrecy_order_indicator: bool | None = None
    labels: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.tenant_id or not str(self.tenant_id).strip():
            raise ValueError("tenant_id must be non-empty")


@dataclass(frozen=True, slots=True)
class SinkEnforcementResult:
    """Outcome of evaluating or attempting a public-sink dispatch."""

    allowed: bool
    code: EnforcementDecisionCode
    channel: SinkChannel
    public_sink: PublicSink
    content_kind: ContentKind
    classification: DisclosureClassification
    publication_state: PublicationState
    export_control_state: ExportControlState
    tenant_id: str
    quarantined: bool
    reason: str
    policy_decision: SinkAdmissionDecision | None
    audit_event: Mapping[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "audit_event": dict(self.audit_event),
            "channel": self.channel.value,
            "classification": self.classification.value,
            "code": self.code.value,
            "content_kind": self.content_kind.value,
            "export_control_state": self.export_control_state.value,
            "policy_decision": (
                self.policy_decision.to_dict() if self.policy_decision else None
            ),
            "public_sink": self.public_sink.value,
            "publication_state": self.publication_state.value,
            "quarantined": self.quarantined,
            "reason": self.reason,
            "tenant_id": self.tenant_id,
        }


@dataclass(frozen=True, slots=True)
class ExportControlDecision:
    """Result of the export-control / secrecy-order gate."""

    allowed: bool
    code: EnforcementDecisionCode
    export_control_state: ExportControlState
    publication_state: PublicationState
    classification: DisclosureClassification
    quarantined: bool
    reason: str
    requires_human_clearance: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "classification": self.classification.value,
            "code": self.code.value,
            "export_control_state": self.export_control_state.value,
            "publication_state": self.publication_state.value,
            "quarantined": self.quarantined,
            "reason": self.reason,
            "requires_human_clearance": self.requires_human_clearance,
        }


@dataclass(frozen=True, slots=True)
class TenantPolicy:
    """Minimal tenant isolation policy for public-sink enforcement."""

    tenant_id: str
    allow_external_models: bool = False
    allow_cross_tenant_read: bool = False

    def __post_init__(self) -> None:
        if not self.tenant_id or not str(self.tenant_id).strip():
            raise ValueError("tenant_id must be non-empty")
        if not isinstance(self.allow_external_models, bool):
            raise TypeError("allow_external_models must be bool")
        if not isinstance(self.allow_cross_tenant_read, bool):
            raise TypeError("allow_cross_tenant_read must be bool")


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


def _coerce_channel(value: SinkChannel | str) -> SinkChannel:
    if isinstance(value, SinkChannel):
        return value
    return SinkChannel(str(value).strip())


def _coerce_publication(value: PublicationState | str | None) -> PublicationState:
    if value is None:
        return PublicationState.UNKNOWN
    if isinstance(value, PublicationState):
        return value
    try:
        return PublicationState(str(value).strip())
    except ValueError:
        return PublicationState.UNKNOWN


def _coerce_export_state(
    value: ExportControlState | str | None,
) -> ExportControlState:
    if value is None:
        return ExportControlState.UNKNOWN
    if isinstance(value, ExportControlState):
        return value
    try:
        return ExportControlState(str(value).strip())
    except ValueError:
        return ExportControlState.UNKNOWN


def _coerce_kind(value: ContentKind | str) -> ContentKind:
    if isinstance(value, ContentKind):
        return value
    return ContentKind(str(value).strip())


def _safe_audit_payload_marker(payload: Any) -> Mapping[str, Any]:
    """Describe payload type/size without retaining substance."""
    if payload is None:
        return MappingProxyType({"present": False})
    if isinstance(payload, (bytes, bytearray, memoryview)):
        return MappingProxyType(
            {
                "present": True,
                "type": "bytes",
                "size": len(payload),
            }
        )
    if isinstance(payload, str):
        return MappingProxyType(
            {
                "present": True,
                "type": "str",
                "size": len(payload),
            }
        )
    if isinstance(payload, (list, tuple)):
        return MappingProxyType(
            {
                "present": True,
                "type": type(payload).__name__,
                "size": len(payload),
            }
        )
    if isinstance(payload, Mapping):
        return MappingProxyType(
            {
                "present": True,
                "type": "mapping",
                "keys": sorted(
                    str(k)
                    for k in payload.keys()
                    if str(k) not in _FORBIDDEN_PAYLOAD_KEYS
                )[:16],
            }
        )
    return MappingProxyType(
        {
            "present": True,
            "type": type(payload).__name__,
        }
    )


def build_audit_event(
    *,
    code: EnforcementDecisionCode,
    allowed: bool,
    channel: SinkChannel,
    content_kind: ContentKind,
    classification: DisclosureClassification,
    publication_state: PublicationState,
    export_control_state: ExportControlState,
    tenant_id: str,
    quarantined: bool,
    reason: str,
    matter_id: str | None = None,
    artifact_id: str | None = None,
    digest: str | None = None,
    payload: Any = None,
    extra: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    """Build a log/telemetry-safe audit event (no private substance)."""
    event: dict[str, Any] = {
        "allowed": allowed,
        "channel": channel.value,
        "classification": classification.value,
        "code": code.value,
        "content_kind": content_kind.value,
        "export_control_state": export_control_state.value,
        "payload_marker": dict(_safe_audit_payload_marker(payload)),
        "publication_state": publication_state.value,
        "quarantined": quarantined,
        "reason": reason,
        "schema_version": PRIVACY_SINKS_SCHEMA_VERSION,
        "tenant_id": tenant_id,
    }
    if matter_id is not None:
        event["matter_id"] = str(matter_id)
    if artifact_id is not None:
        event["artifact_id"] = str(artifact_id)
    if digest is not None:
        event["digest"] = str(digest)
    if extra:
        for key, value in extra.items():
            sk = str(key)
            if sk in _FORBIDDEN_PAYLOAD_KEYS:
                continue
            if sk in event:
                continue
            event[sk] = value
    # Defensive: ensure no forbidden key slipped in.
    for forbidden in _FORBIDDEN_PAYLOAD_KEYS:
        event.pop(forbidden, None)
    return MappingProxyType(event)


def redact_for_observability(
    classification: DisclosureClassification | str | None,
    payload: Mapping[str, Any],
    *,
    policy: UsptoPrivacyPolicy | None = None,
) -> Mapping[str, Any]:
    """Project a mapping for logs/telemetry/errors without private substance."""
    pol = policy or DEFAULT_PRIVACY_POLICY
    base = dict(
        pol.redact_for_logs(
            classification,
            payload,
            allowed_keys=(
                "artifact_id",
                "matter_id",
                "classification",
                "digest",
                "tenant_id",
                "channel",
                "code",
                "reason",
            ),
        )
    )
    # Extra scrub of nested private markers.
    for key in list(base.keys()):
        if str(key) in _FORBIDDEN_PAYLOAD_KEYS:
            base.pop(key, None)
    base.setdefault("redacted", True)
    return MappingProxyType(base)


def payload_contains_canary(surface: str, canaries: Sequence[Any]) -> list[str]:
    """Return string forms of canaries found in *surface* (for tests/probes)."""
    found: list[str] = []
    for canary in canaries:
        if canary is None:
            continue
        if isinstance(canary, (bytes, bytearray)):
            try:
                text = canary.decode("utf-8")
            except UnicodeDecodeError:
                text = canary.decode("latin-1")
            hexed = canary.hex()
            if text and text in surface:
                found.append(text)
            if hexed and hexed in surface:
                found.append(hexed)
        else:
            text = str(canary)
            if text and text in surface:
                found.append(text)
    return found


# ---------------------------------------------------------------------------
# Export-control / secrecy-order gate
# ---------------------------------------------------------------------------


class ExportControlGate:
    """Fail-closed gate for export-control review and secrecy-order state.

    Unknown publication or export-control state quarantines. Secrecy-order and
    restricted material require explicit human clearance (``CLEARED``) before
    any public-sink dispatch is even considered.
    """

    def __init__(self, policy: UsptoPrivacyPolicy | None = None) -> None:
        self._policy = policy or DEFAULT_PRIVACY_POLICY

    @property
    def policy(self) -> UsptoPrivacyPolicy:
        return self._policy

    def coerce_publication(
        self, value: PublicationState | str | None
    ) -> PublicationState:
        return _coerce_publication(value)

    def coerce_export_state(
        self, value: ExportControlState | str | None
    ) -> ExportControlState:
        return _coerce_export_state(value)

    def evaluate(
        self,
        *,
        classification: DisclosureClassification | str | None,
        publication_state: PublicationState | str | None = None,
        export_control_state: ExportControlState | str | None = None,
        secrecy_order_indicator: bool | None = None,
        source_classifications: Sequence[DisclosureClassification | str] = (),
    ) -> ExportControlDecision:
        """Evaluate whether export/publication state permits public dispatch.

        Does not admit material by itself — only clears the export-control
        pre-gate. Sink classification still applies via :class:`PublicSinkEnforcer`.
        """
        parts: list[DisclosureClassification | str] = []
        if classification is not None:
            parts.append(classification)
        parts.extend(source_classifications)
        if parts:
            cls = self._policy.classify_before_dispatch(
                parts[0],
                source_classifications=tuple(parts[1:]),
            )
        else:
            cls = DisclosureClassification.UNKNOWN

        pub = self.coerce_publication(publication_state)
        exp = self.coerce_export_state(export_control_state)

        # Explicit secrecy-order indicator forces the most restrictive state.
        if secrecy_order_indicator is True:
            pub = PublicationState.SECRECY_ORDER
            exp = ExportControlState.SECRECY_ORDER

        # Classification RESTRICTED_EXPORT_REVIEW forces export gate even if
        # publication was declared public (fail closed on conflict).
        if cls is DisclosureClassification.RESTRICTED_EXPORT_REVIEW:
            if exp is ExportControlState.CLEARED and pub is PublicationState.PUBLIC:
                # Still denied: classification itself requires export clearance
                # workflow; "cleared" alone is insufficient without reclass.
                return ExportControlDecision(
                    allowed=False,
                    code=EnforcementDecisionCode.DENIED_EXPORT_CONTROL,
                    export_control_state=exp,
                    publication_state=pub,
                    classification=cls,
                    quarantined=False,
                    reason=(
                        "restricted_export_review classification requires "
                        "reclassification after human export clearance"
                    ),
                    requires_human_clearance=True,
                )
            if exp is ExportControlState.UNKNOWN or pub is PublicationState.UNKNOWN:
                return ExportControlDecision(
                    allowed=False,
                    code=EnforcementDecisionCode.DENIED_UNKNOWN_EXPORT_STATE,
                    export_control_state=exp,
                    publication_state=pub,
                    classification=cls,
                    quarantined=True,
                    reason=(
                        "export-review classification with unknown "
                        "publication/export state is quarantined"
                    ),
                    requires_human_clearance=True,
                )
            return ExportControlDecision(
                allowed=False,
                code=EnforcementDecisionCode.DENIED_EXPORT_CONTROL,
                export_control_state=exp,
                publication_state=pub,
                classification=cls,
                quarantined=False,
                reason="export-review material is denied until human clearance and reclassification",
                requires_human_clearance=True,
            )

        if pub is PublicationState.SECRECY_ORDER or exp is ExportControlState.SECRECY_ORDER:
            return ExportControlDecision(
                allowed=False,
                code=EnforcementDecisionCode.DENIED_SECRECY_ORDER,
                export_control_state=ExportControlState.SECRECY_ORDER,
                publication_state=PublicationState.SECRECY_ORDER,
                classification=cls,
                quarantined=False,
                reason=(
                    "secrecy-order material (35 USC 181-188) is denied from "
                    "all public sinks until order is lifted and reclassified"
                ),
                requires_human_clearance=True,
            )

        if pub is PublicationState.UNKNOWN:
            return ExportControlDecision(
                allowed=False,
                code=EnforcementDecisionCode.DENIED_UNKNOWN_PUBLICATION,
                export_control_state=exp,
                publication_state=pub,
                classification=cls,
                quarantined=True,
                reason="unknown publication state quarantines; public sinks denied",
                requires_human_clearance=True,
            )

        if exp is ExportControlState.UNKNOWN:
            return ExportControlDecision(
                allowed=False,
                code=EnforcementDecisionCode.DENIED_UNKNOWN_EXPORT_STATE,
                export_control_state=exp,
                publication_state=pub,
                classification=cls,
                quarantined=True,
                reason="unknown export-control state quarantines; public sinks denied",
                requires_human_clearance=True,
            )

        if exp is ExportControlState.RESTRICTED or exp is ExportControlState.PENDING_REVIEW:
            return ExportControlDecision(
                allowed=False,
                code=EnforcementDecisionCode.DENIED_EXPORT_CONTROL,
                export_control_state=exp,
                publication_state=pub,
                classification=cls,
                quarantined=False,
                reason=(
                    f"export-control state {exp.value!r} requires human "
                    "clearance before any public-sink dispatch"
                ),
                requires_human_clearance=True,
            )

        if pub is PublicationState.EXPORT_REVIEW_PENDING:
            return ExportControlDecision(
                allowed=False,
                code=EnforcementDecisionCode.DENIED_EXPORT_CONTROL,
                export_control_state=exp,
                publication_state=pub,
                classification=cls,
                quarantined=False,
                reason="publication state export_review_pending denies public sinks",
                requires_human_clearance=True,
            )

        if pub is PublicationState.PRIVATE_UNPUBLISHED:
            # Private unpublished may live in the private store but never
            # clears the public-sink gate via export control alone.
            return ExportControlDecision(
                allowed=False,
                code=EnforcementDecisionCode.DENIED_PRIVATE,
                export_control_state=exp,
                publication_state=pub,
                classification=cls,
                quarantined=False,
                reason="private_unpublished material is not export-cleared for public sinks",
                requires_human_clearance=False,
            )

        if self._policy.must_quarantine(cls):
            return ExportControlDecision(
                allowed=False,
                code=EnforcementDecisionCode.DENIED_QUARANTINE,
                export_control_state=exp,
                publication_state=pub,
                classification=cls,
                quarantined=True,
                reason="unknown classification quarantines; export gate closed",
                requires_human_clearance=True,
            )

        # CLEARED + PUBLIC publication + non-private classification → export gate open.
        if (
            exp is ExportControlState.CLEARED
            and pub is PublicationState.PUBLIC
            and is_public_classification(cls)
        ):
            return ExportControlDecision(
                allowed=True,
                code=EnforcementDecisionCode.ALLOWED,
                export_control_state=exp,
                publication_state=pub,
                classification=cls,
                quarantined=False,
                reason="export-control cleared for public classification",
                requires_human_clearance=False,
            )

        # Private classification never passes the export gate for public sinks.
        if is_private_classification(cls):
            return ExportControlDecision(
                allowed=False,
                code=EnforcementDecisionCode.DENIED_PRIVATE,
                export_control_state=exp,
                publication_state=pub,
                classification=cls,
                quarantined=False,
                reason="private classification fails export-control public-sink gate",
                requires_human_clearance=False,
            )

        # Fail closed.
        return ExportControlDecision(
            allowed=False,
            code=EnforcementDecisionCode.DENIED_QUARANTINE,
            export_control_state=exp,
            publication_state=pub,
            classification=cls,
            quarantined=True,
            reason="unhandled export-control combination fails closed",
            requires_human_clearance=True,
        )

    def must_quarantine(
        self,
        *,
        classification: DisclosureClassification | str | None = None,
        publication_state: PublicationState | str | None = None,
        export_control_state: ExportControlState | str | None = None,
        secrecy_order_indicator: bool | None = None,
    ) -> bool:
        decision = self.evaluate(
            classification=classification,
            publication_state=publication_state,
            export_control_state=export_control_state,
            secrecy_order_indicator=secrecy_order_indicator,
        )
        return decision.quarantined

    def quarantine(
        self,
        *,
        quarantine_id: str,
        classification: DisclosureClassification | str | None = None,
        publication_state: PublicationState | str | None = None,
        export_control_state: ExportControlState | str | None = None,
        secrecy_order_indicator: bool | None = None,
        related_artifact_ids: Sequence[str] = (),
        content_kinds: Sequence[ContentKind | str] = (),
    ) -> QuarantineRecord:
        decision = self.evaluate(
            classification=classification,
            publication_state=publication_state,
            export_control_state=export_control_state,
            secrecy_order_indicator=secrecy_order_indicator,
        )
        reasons = [decision.code.value, decision.reason]
        if decision.quarantined and "unknown" not in decision.code.value:
            reasons.insert(0, "forced_quarantine")
        return self._policy.quarantine(
            quarantine_id=quarantine_id,
            classification=(
                DisclosureClassification.UNKNOWN
                if decision.quarantined
                else decision.classification
            ),
            reason_codes=tuple(reasons),
            related_artifact_ids=related_artifact_ids,
            content_kinds=content_kinds,
        )


# ---------------------------------------------------------------------------
# Public sink enforcer
# ---------------------------------------------------------------------------


class PublicSinkEnforcer:
    """Enforce classification, tenant, and export-control policy at all sinks.

    :meth:`evaluate` never mutates sinks. :meth:`dispatch` evaluates then
    either records an admission (public-only) or a denial audit event — private
    payloads are never written to capture surfaces.
    """

    def __init__(
        self,
        *,
        policy: UsptoPrivacyPolicy | None = None,
        export_gate: ExportControlGate | None = None,
        tenant_policy: TenantPolicy | None = None,
        allow_external_models_for_private: bool | None = None,
    ) -> None:
        self._policy = policy or DEFAULT_PRIVACY_POLICY
        self._export_gate = export_gate or ExportControlGate(self._policy)
        self._tenant_policy = tenant_policy
        # External models: default deny. Explicit True only when both the
        # privacy policy and tenant policy allow it.
        if allow_external_models_for_private is None:
            self._allow_external_models = bool(
                self._policy.allow_external_models_for_private
            )
        else:
            self._allow_external_models = bool(allow_external_models_for_private)
        self._admitted: list[Mapping[str, Any]] = []
        self._denied: list[Mapping[str, Any]] = []
        self._audit_log: list[Mapping[str, Any]] = []
        self._telemetry: list[Mapping[str, Any]] = []
        self._error_surfaces: list[Mapping[str, Any]] = []
        self._channel_payloads: dict[str, list[Any]] = {
            ch.value: [] for ch in SinkChannel
        }

    @property
    def policy(self) -> UsptoPrivacyPolicy:
        return self._policy

    @property
    def export_gate(self) -> ExportControlGate:
        return self._export_gate

    @property
    def tenant_policy(self) -> TenantPolicy | None:
        return self._tenant_policy

    @property
    def admitted(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._admitted)

    @property
    def denied(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._denied)

    @property
    def audit_log(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._audit_log)

    @property
    def telemetry(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._telemetry)

    @property
    def error_surfaces(self) -> tuple[Mapping[str, Any], ...]:
        return tuple(self._error_surfaces)

    def channel_payloads(self, channel: SinkChannel | str) -> tuple[Any, ...]:
        ch = _coerce_channel(channel)
        return tuple(self._channel_payloads.get(ch.value, ()))

    def all_captured_surface_text(self) -> str:
        """Serialize admitted channel payloads + observability for probes."""
        import json

        parts: list[str] = []
        for ch, items in self._channel_payloads.items():
            for item in items:
                if isinstance(item, (bytes, bytearray)):
                    parts.append(item.decode("latin-1", errors="replace"))
                else:
                    try:
                        parts.append(json.dumps(item, default=str))
                    except TypeError:
                        parts.append(str(item))
        for bucket in (self._audit_log, self._telemetry, self._error_surfaces):
            for event in bucket:
                try:
                    parts.append(json.dumps(dict(event), default=str, sort_keys=True))
                except TypeError:
                    parts.append(str(event))
        return "\n".join(parts)

    def bind_tenant(self, tenant_policy: TenantPolicy) -> "PublicSinkEnforcer":
        """Return a new enforcer bound to *tenant_policy* (shared policy/gate)."""
        return PublicSinkEnforcer(
            policy=self._policy,
            export_gate=self._export_gate,
            tenant_policy=tenant_policy,
            allow_external_models_for_private=self._allow_external_models,
        )

    def assert_tenant_isolation(
        self,
        request_tenant_id: str,
        *,
        resource_tenant_id: str,
    ) -> None:
        """Raise if a request attempts cross-tenant access."""
        req = str(request_tenant_id).strip()
        res = str(resource_tenant_id).strip()
        if not req or not res:
            raise PrivacyBoundaryError(
                "tenant identifiers must be non-empty",
                code=EnforcementDecisionCode.DENIED_TENANT_ISOLATION.value,
            )
        if req != res:
            allow_cross = bool(
                self._tenant_policy and self._tenant_policy.allow_cross_tenant_read
            )
            if not allow_cross:
                raise PrivacyBoundaryError(
                    "cross-tenant access denied",
                    code=EnforcementDecisionCode.DENIED_TENANT_ISOLATION.value,
                )

    def evaluate(self, request: SinkDispatchRequest) -> SinkEnforcementResult:
        """Evaluate whether *request* may enter the target public channel."""
        channel = _coerce_channel(request.channel)
        kind = _coerce_kind(request.content_kind)
        public_sink = channel_to_public_sink(channel)
        tenant_id = str(request.tenant_id).strip()

        # Effective classification inherits most restrictive sources.
        cls = self._policy.classify_before_dispatch(
            request.classification,
            source_classifications=request.source_classifications,
        )
        pub = _coerce_publication(request.publication_state)
        exp = _coerce_export_state(request.export_control_state)

        # Tenant binding: if enforcer is tenant-bound, request must match.
        if self._tenant_policy is not None:
            try:
                self.assert_tenant_isolation(
                    tenant_id, resource_tenant_id=self._tenant_policy.tenant_id
                )
            except PrivacyBoundaryError as exc:
                audit = build_audit_event(
                    code=EnforcementDecisionCode.DENIED_TENANT_ISOLATION,
                    allowed=False,
                    channel=channel,
                    content_kind=kind,
                    classification=cls,
                    publication_state=pub,
                    export_control_state=exp,
                    tenant_id=tenant_id,
                    quarantined=False,
                    reason=str(exc),
                    matter_id=request.matter_id,
                    artifact_id=request.artifact_id,
                    digest=request.digest,
                    payload=request.payload,
                )
                return SinkEnforcementResult(
                    allowed=False,
                    code=EnforcementDecisionCode.DENIED_TENANT_ISOLATION,
                    channel=channel,
                    public_sink=public_sink,
                    content_kind=kind,
                    classification=cls,
                    publication_state=pub,
                    export_control_state=exp,
                    tenant_id=tenant_id,
                    quarantined=False,
                    reason=str(exc),
                    policy_decision=None,
                    audit_event=audit,
                )

        # Export-control / publication-state pre-gate.
        export_decision = self._export_gate.evaluate(
            classification=cls,
            publication_state=pub,
            export_control_state=exp,
            secrecy_order_indicator=request.secrecy_order_indicator,
            source_classifications=request.source_classifications,
        )
        # Align states with any secrecy-order forcing.
        pub = export_decision.publication_state
        exp = export_decision.export_control_state
        cls = export_decision.classification

        if not export_decision.allowed:
            audit = build_audit_event(
                code=export_decision.code,
                allowed=False,
                channel=channel,
                content_kind=kind,
                classification=cls,
                publication_state=pub,
                export_control_state=exp,
                tenant_id=tenant_id,
                quarantined=export_decision.quarantined,
                reason=export_decision.reason,
                matter_id=request.matter_id,
                artifact_id=request.artifact_id,
                digest=request.digest,
                payload=request.payload,
                extra={"requires_human_clearance": export_decision.requires_human_clearance},
            )
            return SinkEnforcementResult(
                allowed=False,
                code=export_decision.code,
                channel=channel,
                public_sink=public_sink,
                content_kind=kind,
                classification=cls,
                publication_state=pub,
                export_control_state=exp,
                tenant_id=tenant_id,
                quarantined=export_decision.quarantined,
                reason=export_decision.reason,
                policy_decision=None,
                audit_event=audit,
            )

        # External-model default deny (even if export gate somehow cleared).
        if channel is SinkChannel.REMOTE_MODEL:
            tenant_allows = bool(
                self._tenant_policy and self._tenant_policy.allow_external_models
            )
            if is_private_classification(cls) or self._policy.must_quarantine(cls):
                if not (self._allow_external_models and tenant_allows):
                    reason = (
                        "external model use over private material is denied by default"
                    )
                    audit = build_audit_event(
                        code=EnforcementDecisionCode.DENIED_EXTERNAL_MODEL,
                        allowed=False,
                        channel=channel,
                        content_kind=kind,
                        classification=cls,
                        publication_state=pub,
                        export_control_state=exp,
                        tenant_id=tenant_id,
                        quarantined=self._policy.must_quarantine(cls),
                        reason=reason,
                        matter_id=request.matter_id,
                        artifact_id=request.artifact_id,
                        digest=request.digest,
                        payload=request.payload,
                    )
                    return SinkEnforcementResult(
                        allowed=False,
                        code=EnforcementDecisionCode.DENIED_EXTERNAL_MODEL,
                        channel=channel,
                        public_sink=public_sink,
                        content_kind=kind,
                        classification=cls,
                        publication_state=pub,
                        export_control_state=exp,
                        tenant_id=tenant_id,
                        quarantined=self._policy.must_quarantine(cls),
                        reason=reason,
                        policy_decision=None,
                        audit_event=audit,
                    )

        # Delegate to classification privacy policy.
        policy_decision = self._policy.evaluate_sink(cls, public_sink, kind)
        if not policy_decision.allowed:
            code = _map_policy_code(policy_decision.code)
            audit = build_audit_event(
                code=code,
                allowed=False,
                channel=channel,
                content_kind=kind,
                classification=cls,
                publication_state=pub,
                export_control_state=exp,
                tenant_id=tenant_id,
                quarantined=policy_decision.quarantined,
                reason=policy_decision.reason,
                matter_id=request.matter_id,
                artifact_id=request.artifact_id,
                digest=request.digest,
                payload=request.payload,
                extra={"policy_code": policy_decision.code.value},
            )
            return SinkEnforcementResult(
                allowed=False,
                code=code,
                channel=channel,
                public_sink=public_sink,
                content_kind=kind,
                classification=cls,
                publication_state=pub,
                export_control_state=exp,
                tenant_id=tenant_id,
                quarantined=policy_decision.quarantined,
                reason=policy_decision.reason,
                policy_decision=policy_decision,
                audit_event=audit,
            )

        # Final admission — public classification + cleared export gate only.
        audit = build_audit_event(
            code=EnforcementDecisionCode.ALLOWED,
            allowed=True,
            channel=channel,
            content_kind=kind,
            classification=cls,
            publication_state=pub,
            export_control_state=exp,
            tenant_id=tenant_id,
            quarantined=False,
            reason="public classification admitted to public sink under cleared export state",
            matter_id=request.matter_id,
            artifact_id=request.artifact_id,
            digest=request.digest,
            payload=request.payload,
        )
        return SinkEnforcementResult(
            allowed=True,
            code=EnforcementDecisionCode.ALLOWED,
            channel=channel,
            public_sink=public_sink,
            content_kind=kind,
            classification=cls,
            publication_state=pub,
            export_control_state=exp,
            tenant_id=tenant_id,
            quarantined=False,
            reason=audit["reason"],
            policy_decision=policy_decision,
            audit_event=audit,
        )

    def dispatch(self, request: SinkDispatchRequest) -> SinkEnforcementResult:
        """Evaluate and either admit a public payload or record a denial.

        On denial, private payloads are **not** written to any channel capture,
        audit log, telemetry, or error surface. Denial audits contain reason
        codes and digests only.
        """
        result = self.evaluate(request)
        audit = dict(result.audit_event)
        self._audit_log.append(MappingProxyType(audit))
        # Telemetry always records the decision envelope, never the payload.
        self._telemetry.append(
            MappingProxyType(
                {
                    "event": "sink_dispatch",
                    "allowed": result.allowed,
                    "code": result.code.value,
                    "channel": result.channel.value,
                    "classification": result.classification.value,
                    "content_kind": result.content_kind.value,
                    "tenant_id": result.tenant_id,
                    "quarantined": result.quarantined,
                    "digest": request.digest,
                    "artifact_id": request.artifact_id,
                    "matter_id": request.matter_id,
                }
            )
        )

        if not result.allowed:
            self._denied.append(MappingProxyType(result.to_dict()))
            # Error surface gets a redacted message only.
            self._error_surfaces.append(
                MappingProxyType(
                    {
                        "event": "sink_denied",
                        "code": result.code.value,
                        "channel": result.channel.value,
                        "classification": result.classification.value,
                        "reason": result.reason,
                        "tenant_id": result.tenant_id,
                        "digest": request.digest,
                        "artifact_id": request.artifact_id,
                    }
                )
            )
            return result

        # Admitted: only public substance may be recorded on the channel.
        self._admitted.append(MappingProxyType(result.to_dict()))
        self._channel_payloads[result.channel.value].append(request.payload)
        return result

    def assert_dispatch_allowed(
        self, request: SinkDispatchRequest
    ) -> SinkEnforcementResult:
        """Dispatch and raise :class:`PrivacyBoundaryError` when denied."""
        result = self.dispatch(request)
        if not result.allowed:
            raise PrivacyBoundaryError(
                result.reason,
                code=result.code.value,
                classification=result.classification.value,
                sink=result.channel.value,
                content_kind=result.content_kind.value,
            )
        return result

    def deny_matrix(
        self,
        *,
        tenant_id: str,
        classification: DisclosureClassification | str,
        publication_state: PublicationState | str = PublicationState.PRIVATE_UNPUBLISHED,
        export_control_state: ExportControlState | str = ExportControlState.CLEARED,
        content_kinds: Sequence[ContentKind | str] | None = None,
        channels: Sequence[SinkChannel | str] | None = None,
        payload: Any = None,
        secrecy_order_indicator: bool | None = None,
    ) -> list[SinkEnforcementResult]:
        """Evaluate every channel × kind combination; return denial results."""
        kinds: Sequence[ContentKind | str] = content_kinds or (
            ContentKind.DOCUMENT_BYTES,
            ContentKind.EXTRACTED_TEXT,
            ContentKind.EMBEDDING,
            ContentKind.CONTENT_IDENTIFIER,
        )
        ch_list: Sequence[SinkChannel | str] = channels or all_sink_channels()
        denials: list[SinkEnforcementResult] = []
        for channel in ch_list:
            for kind in kinds:
                req = SinkDispatchRequest(
                    tenant_id=tenant_id,
                    classification=classification,
                    channel=channel,
                    content_kind=kind,
                    publication_state=publication_state,
                    export_control_state=export_control_state,
                    payload=payload,
                    secrecy_order_indicator=secrecy_order_indicator,
                )
                result = self.evaluate(req)
                if not result.allowed:
                    denials.append(result)
        return denials


def _map_policy_code(code: SinkDecisionCode) -> EnforcementDecisionCode:
    mapping = {
        SinkDecisionCode.ALLOWED: EnforcementDecisionCode.ALLOWED,
        SinkDecisionCode.DENIED_PRIVATE: EnforcementDecisionCode.DENIED_PRIVATE,
        SinkDecisionCode.DENIED_QUARANTINE: EnforcementDecisionCode.DENIED_QUARANTINE,
        SinkDecisionCode.DENIED_CREDENTIAL: EnforcementDecisionCode.DENIED_CREDENTIAL,
        SinkDecisionCode.DENIED_EXPORT_REVIEW: EnforcementDecisionCode.DENIED_EXPORT_CONTROL,
        SinkDecisionCode.DENIED_CONTENT_KIND: EnforcementDecisionCode.DENIED_CONTENT_KIND,
        SinkDecisionCode.DENIED_UNKNOWN_SINK: EnforcementDecisionCode.DENIED_CHANNEL,
    }
    return mapping.get(code, EnforcementDecisionCode.DENIED_QUARANTINE)


def deny_private_substance_from_all_channels(
    *,
    tenant_id: str,
    classification: DisclosureClassification | str = (
        DisclosureClassification.CONFIDENTIAL_APPLICATION
    ),
    enforcer: PublicSinkEnforcer | None = None,
    payloads: Mapping[ContentKind, Any] | None = None,
) -> list[SinkEnforcementResult]:
    """Adversarial helper: attempt private substance on every channel.

    Returns denial results. Callers should also inspect the enforcer's
    observability surfaces to prove canaries never landed.
    """
    eng = enforcer or PublicSinkEnforcer()
    default_payloads: dict[ContentKind, Any] = {
        ContentKind.DOCUMENT_BYTES: b"",
        ContentKind.EXTRACTED_TEXT: "",
        ContentKind.EMBEDDING: [],
        ContentKind.CONTENT_IDENTIFIER: "",
    }
    use_payloads = dict(default_payloads)
    if payloads:
        use_payloads.update(payloads)
    results: list[SinkEnforcementResult] = []
    for channel in all_sink_channels():
        for kind, payload in use_payloads.items():
            req = SinkDispatchRequest(
                tenant_id=tenant_id,
                classification=classification,
                channel=channel,
                content_kind=kind,
                publication_state=PublicationState.PRIVATE_UNPUBLISHED,
                export_control_state=ExportControlState.CLEARED,
                payload=payload,
            )
            results.append(eng.dispatch(req))
    return results


__all__ = [
    "PRIVACY_SINKS_INTERFACE",
    "PRIVACY_SINKS_SCHEMA_VERSION",
    "EnforcementDecisionCode",
    "ExportControlDecision",
    "ExportControlGate",
    "ExportControlState",
    "PublicationState",
    "PublicSinkEnforcer",
    "SinkChannel",
    "SinkDispatchRequest",
    "SinkEnforcementResult",
    "TenantPolicy",
    "all_ipfs_public_channels",
    "all_sink_channels",
    "build_audit_event",
    "channel_to_public_sink",
    "deny_private_substance_from_all_channels",
    "payload_contains_canary",
    "redact_for_observability",
]
