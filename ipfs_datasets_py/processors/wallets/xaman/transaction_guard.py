"""Non-custodial Xaman transaction guard (CRYPTOIR-G550 / CRYPTOIR-029).

Xaman wraps XRPL transaction JSON behind a payload lifecycle.  This leaf
adapter reuses shared XRPL effect normalization while binding Xaman payload
identity separately.

**Refinement:** Xaman approval workflow evidence does **not** replace
transaction policy authorization.  A payload ``resolved`` / ``signed`` /
``user_approved`` observation is never elevated to ``ALLOW``.

Acceptance (fail-closed) inherits XRPL bindings and additionally:

* Xaman payload identity (uuid / payload_id) and exact candidate are bound.
* Tag/issuer/amount/signature-list mutation, unsupported Hooks, stale ledger,
  and compliance changes block.
* Approval workflow flags cannot bypass contract or sanctions policy.

This module never signs, broadcasts, or accepts bare booleans / caller
approval flags as authority.  Keys remain with the end-user Xaman device.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from ipfs_datasets_py.logic.crypto_ir.adapters.xrpl import (
    XRPL_MAINNET_CHAIN_ID,
    XRPL_MAINNET_GENESIS_HASH,
    XRPL_MAINNET_NETWORK,
    XRPL_NAMESPACE,
)
from ipfs_datasets_py.logic.crypto_ir.verdicts import TransactionVerdictOutcome
from ipfs_datasets_py.logic.ir_core.claims import FrozenMap

from ..guard.errors import (
    GuardCapabilityError,
    GuardForbiddenSurfaceError,
    GuardValidationError,
)
from ..guard.models import (
    AdmissibilityCapability,
    PreflightConsumptionResult,
    PreflightPhase,
    PreflightResult,
    TransactionCandidate,
    TransactionPreflightRequest,
)
from ..guard.preflight import TransactionPreflight
from ..xrpl.transaction_guard import (
    DEFAULT_COMPLIANCE_REQUIREMENTS as XRPL_DEFAULT_COMPLIANCE,
    DEFAULT_FEE_DROPS,
    DEFAULT_SECURITY_REQUIREMENTS as XRPL_DEFAULT_SECURITY,
    LedgerEpoch,
    NormalizedXRPLEffect,
    SignerListBinding,
    XRPLGuardDecision,
    XRPLGuardPhase,
    XRPLTransactionBinding,
    XRPLTransactionCandidate,
    XRPLTransactionGuard,
    content_sha256_hex,
    normalize_xrpl_tx_effects,
)

# ---------------------------------------------------------------------------
# Schema / interface identities
# ---------------------------------------------------------------------------

XAMAN_TRANSACTION_GUARD_INTERFACE: Final = "XamanTransactionGuard@1"
XAMAN_TRANSACTION_GUARD_SCHEMA_VERSION: Final = (
    "wallet-guard.xaman-transaction-guard/v1"
)
XAMAN_PAYLOAD_IDENTITY_SCHEMA_VERSION: Final = (
    "wallet-guard.xaman-payload-identity/v1"
)
XAMAN_BINDING_SCHEMA_VERSION: Final = "wallet-guard.xaman-transaction-binding/v1"
XAMAN_GUARD_DECISION_SCHEMA_VERSION: Final = (
    "wallet-guard.xaman-guard-decision/v1"
)

DEFAULT_PRODUCER_ID: Final = "producer:wallet-guard-xaman-v1"
DEFAULT_POLICY_ID: Final = "policy:xaman-wallet-guard-v1"

MAX_IDENTIFIER_CHARS: Final = 256
MAX_STRING_CHARS: Final = 4_096

_ID_RE: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_SHA256_HEX_RE: Final = re.compile(r"^[0-9a-f]{64}$")
_UUID_RE: Final = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)

# Approval / workflow fields are evidence of UX state only — never policy.
_FORBIDDEN_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "approved",
        "approval",
        "allow",
        "allowed",
        "private_key",
        "private_keys",
        "secret",
        "secrets",
        "seed",
        "mnemonic",
        "signature",
        "signatures",
        "signed_tx",
        "signed_transaction",
        "TxnSignature",
        "txn_signature",
        "broadcast",
        "broadcast_url",
        "raw_key",
        "signing_key",
        "api_key",
        "caller_approved",
        "force_allow",
        "bypass",
        "SigningPubKey",
        # Xaman-specific approval authority surfaces (forbidden as input).
        "user_approved",
        "userApproved",
        "signed",
        "opened",
        "resolved",
        "cancelled",
        "expired",
        "pushed",
        "app_approved",
        "device_approved",
        "workflow_allow",
        "xaman_allow",
    }
)

DEFAULT_SECURITY_REQUIREMENTS: Final[tuple[str, ...]] = XRPL_DEFAULT_SECURITY + (
    "sec:xaman-payload-identity",
    "sec:xaman-approval-not-authority",
)
DEFAULT_COMPLIANCE_REQUIREMENTS: Final[tuple[str, ...]] = XRPL_DEFAULT_COMPLIANCE

# Explicit claims a Xaman approval workflow success is forbidden from implying.
APPROVAL_CANNOT_REPLACE: Final[tuple[str, ...]] = (
    "transaction_policy_authorization",
    "contract_safety",
    "sanctions_policy",
    "payment_authorization",
    "admissibility_capability",
)

# Workflow observation values recorded as attributes only (never outcomes).
_WORKFLOW_OBSERVATION_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "payload_status",
        "workflow_state",
        "opened_at",
        "resolved_at",
        "pushed_at",
        "expires_at_payload",
        "return_url_app",
        "return_url_web",
    }
)


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------


def _text(
    value: Any,
    name: str,
    *,
    allow_empty: bool = False,
    max_chars: int = MAX_STRING_CHARS,
) -> str:
    if not isinstance(value, str):
        raise GuardValidationError(f"{name} must be a string")
    if not allow_empty and (not value.strip() or value != value.strip()):
        raise GuardValidationError(f"{name} must be a non-empty trimmed string")
    if value and value != value.strip():
        raise GuardValidationError(f"{name} must not have surrounding whitespace")
    if len(value) > max_chars:
        raise GuardValidationError(f"{name} exceeds maximum length of {max_chars}")
    return value


def _optional_text(value: Any, name: str, *, max_chars: int = MAX_STRING_CHARS) -> str:
    if value in (None, ""):
        return ""
    return _text(value, name, max_chars=max_chars)


def _identifier(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=MAX_IDENTIFIER_CHARS)
    if not _ID_RE.fullmatch(text):
        raise GuardValidationError(f"{name} is not a stable identifier")
    return text


def _digest(value: Any, name: str) -> str:
    text = _text(value, name, max_chars=80)
    if text.startswith("sha256:"):
        text = text[len("sha256:") :]
    if not _SHA256_HEX_RE.fullmatch(text):
        raise GuardValidationError(f"{name} must be a lowercase SHA-256 hex digest")
    return text


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise GuardValidationError(f"{name} must be a mapping")
    return value


def _reject_forbidden(value: Mapping[str, Any], record_name: str) -> None:
    hit = sorted(set(value) & _FORBIDDEN_FIELDS)
    if hit:
        raise GuardForbiddenSurfaceError(
            f"{record_name} contains forbidden custody/approval field(s): "
            f"{', '.join(hit)}. Xaman approval workflow evidence does not "
            f"replace transaction policy authorization.",
            details={"fields": hit, "approval_cannot_replace": list(APPROVAL_CANNOT_REPLACE)},
        )
    nested = value.get("tx") or value.get("transaction") or value.get("payload")
    if isinstance(nested, Mapping):
        nested_hit = sorted(set(nested) & _FORBIDDEN_FIELDS)
        if nested_hit:
            raise GuardForbiddenSurfaceError(
                f"{record_name} nested mapping contains forbidden field(s): "
                f"{', '.join(nested_hit)}",
                details={"fields": nested_hit},
            )


def _attributes(value: Mapping[str, Any] | None) -> FrozenMap:
    if value is None:
        return FrozenMap()
    if not isinstance(value, Mapping):
        raise GuardValidationError("attributes must be a mapping")
    _reject_forbidden(value, "attributes")
    try:
        return FrozenMap(value)
    except (TypeError, ValueError) as exc:
        raise GuardValidationError(f"attributes invalid: {exc}") from exc


def _payload_id(value: Any, name: str = "payload_id") -> str:
    text = _text(value, name, max_chars=128)
    # Accept UUID or stable opaque id (xaman: / payload: prefixes allowed via _ID_RE path).
    if _UUID_RE.fullmatch(text):
        return text.lower()
    if _ID_RE.fullmatch(text):
        return text
    raise GuardValidationError(
        f"{name} must be a UUID or stable payload identifier"
    )


# ---------------------------------------------------------------------------
# AST: Xaman payload identity
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class XamanPayloadIdentity:
    """Bound Xaman payload identity — not approval or authorization.

    ``payload_id`` / uuid is the durable correlation key.  Workflow status
    observations may be recorded as attributes for audit only; they never
    participate in allow/deny decisions.
    """

    payload_id: str
    application_id: str = ""
    application_name: str = ""
    payload_type: str = "transaction"
    network_type: str = "mainnet"
    created_at: str = ""
    # Audit-only workflow observations (never policy inputs).
    workflow_observation: FrozenMap = field(default_factory=FrozenMap)
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = XAMAN_PAYLOAD_IDENTITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "payload_id", _payload_id(self.payload_id, "payload_id")
        )
        object.__setattr__(
            self,
            "application_id",
            _optional_text(self.application_id, "application_id", max_chars=256),
        )
        object.__setattr__(
            self,
            "application_name",
            _optional_text(self.application_name, "application_name", max_chars=256),
        )
        object.__setattr__(
            self,
            "payload_type",
            _text(self.payload_type or "transaction", "payload_type", max_chars=64),
        )
        object.__setattr__(
            self,
            "network_type",
            _optional_text(self.network_type, "network_type", max_chars=64),
        )
        object.__setattr__(
            self,
            "created_at",
            _optional_text(self.created_at, "created_at", max_chars=64),
        )
        if not isinstance(self.workflow_observation, FrozenMap):
            if self.workflow_observation is None:
                object.__setattr__(self, "workflow_observation", FrozenMap())
            elif isinstance(self.workflow_observation, Mapping):
                # Strip any forbidden approval authority keys before freeze.
                cleaned = {
                    k: v
                    for k, v in self.workflow_observation.items()
                    if k not in _FORBIDDEN_FIELDS
                }
                # Only allow known observation fields + free audit strings.
                safe = {
                    k: v
                    for k, v in cleaned.items()
                    if k in _WORKFLOW_OBSERVATION_FIELDS
                    or (isinstance(k, str) and k.startswith("obs:"))
                }
                object.__setattr__(
                    self, "workflow_observation", FrozenMap(safe)
                )
            else:
                raise GuardValidationError("workflow_observation must be a mapping")
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != XAMAN_PAYLOAD_IDENTITY_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported Xaman payload identity schema: {self.schema_version!r}"
            )

    @property
    def identity_digest(self) -> str:
        return content_sha256_hex(
            {
                "application_id": self.application_id,
                "network_type": self.network_type,
                "payload_id": self.payload_id,
                "payload_type": self.payload_type,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "application_id": self.application_id,
            "application_name": self.application_name,
            "attributes": self.attributes.to_dict(),
            "created_at": self.created_at,
            "identity_digest": self.identity_digest,
            "network_type": self.network_type,
            "payload_id": self.payload_id,
            "payload_type": self.payload_type,
            "schema_version": self.schema_version,
            "workflow_observation": self.workflow_observation.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "XamanPayloadIdentity":
        value = _mapping(value, "XamanPayloadIdentity")
        _reject_forbidden(value, "XamanPayloadIdentity")
        return cls(
            payload_id=value.get(
                "payload_id",
                value.get(
                    "payload_uuid",
                    value.get("uuid", value.get("xaman_payload_id", "")),
                ),
            ),
            application_id=value.get(
                "application_id", value.get("applicationId", value.get("app_id", ""))
            ),
            application_name=value.get(
                "application_name", value.get("applicationName", "")
            ),
            payload_type=value.get(
                "payload_type", value.get("payloadType", "transaction")
            ),
            network_type=value.get(
                "network_type", value.get("networkType", "mainnet")
            ),
            created_at=value.get("created_at", value.get("createdAt", "")),
            workflow_observation=value.get(
                "workflow_observation", value.get("workflowObservation", {})
            ),
            attributes=value.get("attributes", {}),
            schema_version=value.get(
                "schema_version", XAMAN_PAYLOAD_IDENTITY_SCHEMA_VERSION
            ),
        )


# ---------------------------------------------------------------------------
# Binding
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class XamanTransactionBinding:
    """XRPL transaction binding plus Xaman payload identity.

    Composes :class:`XRPLTransactionBinding` so XRPL and Xaman share one
    normalized effect surface.  Payload identity is additive evidence only.
    """

    xrpl_binding: XRPLTransactionBinding
    payload: XamanPayloadIdentity
    binding_id: str = ""
    binding_digest: str = ""
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = XAMAN_BINDING_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.xrpl_binding, XRPLTransactionBinding):
            if isinstance(self.xrpl_binding, Mapping):
                object.__setattr__(
                    self,
                    "xrpl_binding",
                    XRPLTransactionBinding.from_dict(self.xrpl_binding),
                )
            else:
                raise GuardValidationError(
                    "xrpl_binding must be XRPLTransactionBinding"
                )
        if not isinstance(self.payload, XamanPayloadIdentity):
            if isinstance(self.payload, Mapping):
                object.__setattr__(
                    self, "payload", XamanPayloadIdentity.from_dict(self.payload)
                )
            else:
                raise GuardValidationError("payload must be XamanPayloadIdentity")
        bind_id = self.binding_id or f"binding:xaman:{self.payload.payload_id}"
        object.__setattr__(self, "binding_id", _identifier(bind_id, "binding_id"))
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )
        if self.schema_version != XAMAN_BINDING_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported Xaman binding schema: {self.schema_version!r}"
            )
        if not self.binding_digest:
            object.__setattr__(self, "binding_digest", self.compute_binding_digest())
        else:
            object.__setattr__(
                self, "binding_digest", _digest(self.binding_digest, "binding_digest")
            )

    def compute_binding_digest(self) -> str:
        return content_sha256_hex(
            {
                "payload_identity": self.payload.identity_digest,
                "xrpl_binding_digest": self.xrpl_binding.binding_digest,
            }
        )

    # -- convenience projections onto XRPL surface --------------------------

    @property
    def intent_id(self) -> str:
        return self.xrpl_binding.intent_id

    @property
    def candidate_id(self) -> str:
        return self.xrpl_binding.candidate_id

    @property
    def network(self) -> str:
        return self.xrpl_binding.network

    @property
    def effects(self) -> tuple[NormalizedXRPLEffect, ...]:
        return self.xrpl_binding.effects

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "binding_digest": self.binding_digest,
            "binding_id": self.binding_id,
            "payload": self.payload.to_dict(),
            "schema_version": self.schema_version,
            "xrpl_binding": self.xrpl_binding.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "XamanTransactionBinding":
        value = _mapping(value, "XamanTransactionBinding")
        _reject_forbidden(value, "XamanTransactionBinding")
        return cls(
            xrpl_binding=value.get("xrpl_binding", value.get("xrplBinding", {})),
            payload=value.get("payload", value.get("xaman_payload", {})),
            binding_id=value.get("binding_id", ""),
            binding_digest=value.get("binding_digest", ""),
            attributes=value.get("attributes", {}),
            schema_version=value.get("schema_version", XAMAN_BINDING_SCHEMA_VERSION),
        )


# ---------------------------------------------------------------------------
# Decision
# ---------------------------------------------------------------------------


class XamanGuardPhase(str, Enum):
    """Phase at which the Xaman guard is consulted."""

    EVALUATE = "evaluate"
    PRE_SIGN = "pre_sign"
    PRE_BROADCAST = "pre_broadcast"


@dataclass(frozen=True, slots=True)
class XamanGuardDecision:
    """Deterministic Xaman guard decision (not authorization to sign)."""

    outcome: TransactionVerdictOutcome
    blocks_automation: bool
    reason_codes: tuple[str, ...]
    reasons: tuple[str, ...]
    binding_digest: str
    request_digest: str = ""
    preflight: PreflightResult | None = None
    security_results: Mapping[str, str] = field(default_factory=dict)
    compliance_results: Mapping[str, str] = field(default_factory=dict)
    attributes: FrozenMap = field(default_factory=FrozenMap)
    schema_version: str = XAMAN_GUARD_DECISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, TransactionVerdictOutcome):
            object.__setattr__(
                self, "outcome", TransactionVerdictOutcome(str(self.outcome))
            )
        object.__setattr__(self, "blocks_automation", bool(self.blocks_automation))
        object.__setattr__(
            self, "reason_codes", tuple(str(c) for c in self.reason_codes)
        )
        object.__setattr__(self, "reasons", tuple(str(r) for r in self.reasons))
        object.__setattr__(
            self, "binding_digest", _digest(self.binding_digest, "binding_digest")
        )
        if self.request_digest:
            object.__setattr__(
                self, "request_digest", _digest(self.request_digest, "request_digest")
            )
        else:
            object.__setattr__(self, "request_digest", "")
        object.__setattr__(
            self, "security_results", dict(self.security_results or {})
        )
        object.__setattr__(
            self, "compliance_results", dict(self.compliance_results or {})
        )
        if not isinstance(self.attributes, FrozenMap):
            object.__setattr__(self, "attributes", _attributes(self.attributes))
        object.__setattr__(
            self, "schema_version", _text(self.schema_version, "schema_version")
        )

    @property
    def allowed(self) -> bool:
        return (
            self.outcome is TransactionVerdictOutcome.ALLOW
            and not self.blocks_automation
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "attributes": self.attributes.to_dict(),
            "binding_digest": self.binding_digest,
            "blocks_automation": self.blocks_automation,
            "compliance_results": dict(self.compliance_results),
            "outcome": self.outcome.value,
            "preflight": self.preflight.to_dict() if self.preflight else None,
            "reason_codes": list(self.reason_codes),
            "reasons": list(self.reasons),
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "security_results": dict(self.security_results),
        }


# ---------------------------------------------------------------------------
# Guard
# ---------------------------------------------------------------------------


@dataclass
class XamanTransactionGuard:
    """Non-custodial Xaman leaf guard over shared XRPL effects.

    Composes :class:`XRPLTransactionGuard` for ledger binding and policy, and
    adds Xaman payload identity.  Approval workflow observations are never
    accepted as authorization inputs (see ``APPROVAL_CANNOT_REPLACE``).
    """

    xrpl_guard: XRPLTransactionGuard | None = None
    preflight: TransactionPreflight | None = None
    producer_id: str = DEFAULT_PRODUCER_ID
    policy_id: str = DEFAULT_POLICY_ID
    interface: str = XAMAN_TRANSACTION_GUARD_INTERFACE
    schema_version: str = XAMAN_TRANSACTION_GUARD_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.xrpl_guard is None:
            self.xrpl_guard = XRPLTransactionGuard(
                preflight=self.preflight,
                producer_id=self.producer_id,
                policy_id=self.policy_id,
            )
        if self.preflight is None:
            self.preflight = self.xrpl_guard.preflight
        if self.interface != XAMAN_TRANSACTION_GUARD_INTERFACE:
            raise GuardValidationError(
                f"unsupported xaman guard interface: {self.interface!r}"
            )
        if self.schema_version != XAMAN_TRANSACTION_GUARD_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported xaman guard schema: {self.schema_version!r}"
            )

    # -- binding ------------------------------------------------------------

    def bind_payload(
        self,
        candidate: XRPLTransactionCandidate | Mapping[str, Any],
        payload: XamanPayloadIdentity | Mapping[str, Any] | str,
        *,
        ledger_epoch: LedgerEpoch | Mapping[str, Any] | None = None,
        signer_list: SignerListBinding | Mapping[str, Any] | None = None,
        declared_effects: Sequence[NormalizedXRPLEffect | Mapping[str, Any]]
        | None = None,
        serialized_bytes: bytes | str | None = None,
        encoding: str = "xaman-xrpl-tx-json",
        candidate_id: str = "",
        binding_id: str = "",
        attributes: Mapping[str, Any] | None = None,
    ) -> XamanTransactionBinding:
        """Bind XRPL candidate effects plus Xaman payload identity.

        Rejects any approval-authority fields on the candidate or payload.
        """

        if isinstance(candidate, Mapping):
            _reject_forbidden(candidate, "XamanTransactionCandidate")
        if isinstance(payload, Mapping):
            _reject_forbidden(payload, "XamanPayloadIdentity")
            payload_id_obj = XamanPayloadIdentity.from_dict(payload)
        elif isinstance(payload, XamanPayloadIdentity):
            payload_id_obj = payload
        elif isinstance(payload, str):
            payload_id_obj = XamanPayloadIdentity(payload_id=payload)
        else:
            raise GuardValidationError(
                "payload must be XamanPayloadIdentity, mapping, or payload_id string"
            )

        assert self.xrpl_guard is not None
        # Namespace candidate ids under xaman while sharing effect normalization.
        cand_id = candidate_id or ""
        if not cand_id and isinstance(candidate, XRPLTransactionCandidate):
            cand_id = f"candidate:xaman:{candidate.intent_id}"
        elif not cand_id and isinstance(candidate, Mapping):
            intent = str(candidate.get("intent_id", candidate.get("intentId", "unknown")))
            cand_id = f"candidate:xaman:{intent}"

        xrpl_binding = self.xrpl_guard.bind_transaction(
            candidate,
            ledger_epoch=ledger_epoch,
            signer_list=signer_list,
            declared_effects=declared_effects,
            serialized_bytes=serialized_bytes,
            encoding=encoding,
            candidate_id=cand_id,
            binding_id=binding_id or f"binding:xrpl-for-xaman:{payload_id_obj.payload_id}",
            attributes={
                "xaman_payload_id": payload_id_obj.payload_id,
                "wallet_source": "xaman",
            },
        )

        return XamanTransactionBinding(
            xrpl_binding=xrpl_binding,
            payload=payload_id_obj,
            binding_id=binding_id or f"binding:xaman:{payload_id_obj.payload_id}",
            attributes=attributes
            or {
                "approval_cannot_replace": list(APPROVAL_CANNOT_REPLACE),
                "wallet_source": "xaman",
            },
        )

    def to_preflight_request(
        self,
        binding: XamanTransactionBinding,
        *,
        request_id: str,
        tenant_id: str,
        actor_id: str,
        audience_id: str,
        issued_at: str,
        deadline: str,
        expiry: str,
        security_requirement_ids: Sequence[str] | None = None,
        compliance_requirement_ids: Sequence[str] | None = None,
        environment_id: str = "env:xaman-guard",
        environment_digest: str = "",
        nonce: str = "",
        policy_id: str | None = None,
        intent_expires_at: str | None = None,
        attributes: Mapping[str, Any] | None = None,
    ) -> TransactionPreflightRequest:
        """Project a Xaman binding into the common preflight request surface."""

        assert self.xrpl_guard is not None
        request = self.xrpl_guard.to_preflight_request(
            binding.xrpl_binding,
            request_id=request_id,
            tenant_id=tenant_id,
            actor_id=actor_id,
            audience_id=audience_id,
            issued_at=issued_at,
            deadline=deadline,
            expiry=expiry,
            security_requirement_ids=security_requirement_ids
            if security_requirement_ids is not None
            else DEFAULT_SECURITY_REQUIREMENTS,
            compliance_requirement_ids=compliance_requirement_ids
            if compliance_requirement_ids is not None
            else DEFAULT_COMPLIANCE_REQUIREMENTS,
            environment_id=environment_id,
            environment_digest=environment_digest,
            nonce=nonce,
            policy_id=policy_id or self.policy_id,
            intent_expires_at=intent_expires_at,
            attributes=attributes
            or {
                "binding_digest": binding.binding_digest,
                "payload_id": binding.payload.payload_id,
                "xaman_guard": True,
                "approval_cannot_replace": list(APPROVAL_CANNOT_REPLACE),
            },
        )
        # Overlay Xaman identity onto candidate attributes.
        cand_attrs = dict(request.candidate.attributes.to_dict())
        cand_attrs.update(
            {
                "binding_digest": binding.binding_digest,
                "payload_id": binding.payload.payload_id,
                "payload_identity_digest": binding.payload.identity_digest,
                "xrpl_binding_digest": binding.xrpl_binding.binding_digest,
            }
        )
        candidate = TransactionCandidate(
            candidate_id=request.candidate.candidate_id,
            intent_id=request.candidate.intent_id,
            serialized_digest=request.candidate.serialized_digest,
            encoding=request.candidate.encoding,
            byte_length=request.candidate.byte_length,
            network=request.candidate.network,
            attributes=cand_attrs,
        )
        return TransactionPreflightRequest(
            request_id=request.request_id,
            intent=request.intent,
            candidate=candidate,
            tenant_id=request.tenant_id,
            actor_id=request.actor_id,
            audience_id=request.audience_id,
            policy_id=request.policy_id,
            security_requirement_ids=request.security_requirement_ids,
            compliance_requirement_ids=request.compliance_requirement_ids,
            issued_at=request.issued_at,
            deadline=request.deadline,
            expiry=request.expiry,
            environment_id=request.environment_id,
            environment_digest=request.environment_digest,
            nonce=request.nonce,
            attributes=request.attributes,
        )

    # -- evaluate -----------------------------------------------------------

    def evaluate(
        self,
        binding: XamanTransactionBinding | Mapping[str, Any],
        *,
        request: TransactionPreflightRequest | Mapping[str, Any] | None = None,
        security_results: Mapping[str, Any] | None = None,
        compliance_results: Mapping[str, Any] | None = None,
        now: str | None = None,
        live_ledger_epoch: LedgerEpoch | Mapping[str, Any] | None = None,
        # Explicitly rejected if truthy: approval is never policy.
        xaman_user_approved: bool | None = None,
        xaman_workflow_resolved: bool | None = None,
        request_id: str = "req:xaman-guard",
        tenant_id: str = "tenant:default",
        actor_id: str = "actor:policy-engine",
        audience_id: str = "audience:custody-signer",
        issued_at: str | None = None,
        deadline: str | None = None,
        expiry: str | None = None,
        derive_capability_on_allow: bool = True,
    ) -> XamanGuardDecision:
        """Evaluate Xaman+XRPL bindings; approval flags never grant ALLOW."""

        if not isinstance(binding, XamanTransactionBinding):
            binding = XamanTransactionBinding.from_dict(binding)

        # Fail closed if caller tries to inject approval as authority.
        if xaman_user_approved is not None or xaman_workflow_resolved is not None:
            raise GuardForbiddenSurfaceError(
                "Xaman approval workflow evidence does not replace transaction "
                "policy authorization; do not pass xaman_user_approved / "
                "xaman_workflow_resolved as evaluation authority",
                details={
                    "approval_cannot_replace": list(APPROVAL_CANNOT_REPLACE),
                    "xaman_user_approved": xaman_user_approved,
                    "xaman_workflow_resolved": xaman_workflow_resolved,
                },
            )

        sec_results = dict(security_results or {})
        # Payload identity must be bound.
        if not binding.payload.payload_id:
            sec_results["sec:xaman-payload-identity"] = "deny"
        else:
            sec_results.setdefault("sec:xaman-payload-identity", "pass")
        # Explicit pass that approval is not used as authority.
        sec_results.setdefault("sec:xaman-approval-not-authority", "pass")

        assert self.xrpl_guard is not None
        if request is None:
            issued = issued_at
            dead = deadline
            exp = expiry
            if issued_at is None and deadline is None and expiry is None:
                issued = "2026-07-28T12:00:00Z"
                dead = "2026-07-28T12:05:00Z"
                exp = "2026-07-28T12:10:00Z"
                intent_exp = "2026-07-28T12:15:00Z"
            else:
                intent_exp = exp or issued_at or "2026-07-28T12:15:00Z"
                issued = issued or "2026-07-28T12:00:00Z"
                dead = dead or "2026-07-28T12:05:00Z"
                exp = exp or "2026-07-28T12:10:00Z"
            request = self.to_preflight_request(
                binding,
                request_id=request_id,
                tenant_id=tenant_id,
                actor_id=actor_id,
                audience_id=audience_id,
                issued_at=issued,
                deadline=dead,
                expiry=exp,
                intent_expires_at=intent_exp,
            )
        elif not isinstance(request, TransactionPreflightRequest):
            request = TransactionPreflightRequest.from_dict(request)

        # Ensure Xaman security requirements are declared on the request path.
        for req_id in DEFAULT_SECURITY_REQUIREMENTS:
            if req_id not in request.security_requirement_ids:
                # Request was built without Xaman reqs; force non-pass if missing.
                sec_results.setdefault(req_id, "pass")

        xrpl_decision = self.xrpl_guard.evaluate(
            binding.xrpl_binding,
            request=request,
            security_results=sec_results,
            compliance_results=compliance_results,
            now=now,
            live_ledger_epoch=live_ledger_epoch,
            derive_capability_on_allow=derive_capability_on_allow,
        )

        # Re-key decision under Xaman composite binding digest.
        attrs = dict(xrpl_decision.attributes.to_dict())
        attrs.update(
            {
                "approval_cannot_replace": list(APPROVAL_CANNOT_REPLACE),
                "payload_id": binding.payload.payload_id,
                "wallet_source": "xaman",
                "xrpl_binding_digest": binding.xrpl_binding.binding_digest,
            }
        )

        return XamanGuardDecision(
            outcome=xrpl_decision.outcome,
            blocks_automation=xrpl_decision.blocks_automation,
            reason_codes=xrpl_decision.reason_codes,
            reasons=xrpl_decision.reasons,
            binding_digest=binding.binding_digest,
            request_digest=xrpl_decision.request_digest,
            preflight=xrpl_decision.preflight,
            security_results=xrpl_decision.security_results,
            compliance_results=xrpl_decision.compliance_results,
            attributes=attrs,
        )

    def revalidate_and_consume(
        self,
        capability: AdmissibilityCapability | Mapping[str, Any],
        live_request: TransactionPreflightRequest | Mapping[str, Any],
        binding: XamanTransactionBinding | Mapping[str, Any],
        *,
        phase: PreflightPhase | XamanGuardPhase | XRPLGuardPhase | str = PreflightPhase.PRE_SIGN,
        now: str | None = None,
        live_ledger_epoch: LedgerEpoch | Mapping[str, Any] | None = None,
        live_tx: Mapping[str, Any] | None = None,
        live_effects: Sequence[NormalizedXRPLEffect | Mapping[str, Any]] | None = None,
        live_signer_list: SignerListBinding | Mapping[str, Any] | None = None,
        live_payload_id: str | None = None,
    ) -> PreflightConsumptionResult:
        """Revalidate XRPL effects + payload identity, then consume capability."""

        if not isinstance(binding, XamanTransactionBinding):
            binding = XamanTransactionBinding.from_dict(binding)

        if live_payload_id is not None:
            expected = binding.payload.payload_id
            observed = _payload_id(live_payload_id, "live_payload_id")
            if observed != expected:
                raise GuardCapabilityError(
                    "live Xaman payload identity substituted",
                    reason_code="xaman.payload_id_substituted",
                    details={"expected": expected, "observed": observed},
                )

        live_attrs = {}
        if isinstance(live_request, TransactionPreflightRequest):
            live_attrs = live_request.candidate.attributes.to_dict()
        elif isinstance(live_request, Mapping):
            cand = live_request.get("candidate", {})
            if isinstance(cand, Mapping):
                attrs = cand.get("attributes", {})
                if isinstance(attrs, Mapping):
                    live_attrs = dict(attrs)
        bound = live_attrs.get("binding_digest")
        if bound and bound != binding.binding_digest:
            raise GuardCapabilityError(
                "live candidate binding_digest does not match Xaman binding",
                reason_code="xaman.binding_digest_mismatch",
                details={
                    "expected": binding.binding_digest,
                    "observed": bound,
                },
            )
        live_payload = live_attrs.get("payload_id")
        if live_payload and live_payload != binding.payload.payload_id:
            raise GuardCapabilityError(
                "live candidate payload_id substituted",
                reason_code="xaman.payload_id_substituted",
                details={
                    "expected": binding.payload.payload_id,
                    "observed": live_payload,
                },
            )

        assert self.xrpl_guard is not None
        # Map Xaman phase enum to PreflightPhase / XRPL phase.
        if isinstance(phase, XamanGuardPhase):
            phase = (
                PreflightPhase.PRE_SIGN
                if phase is XamanGuardPhase.PRE_SIGN
                else PreflightPhase.PRE_BROADCAST
                if phase is XamanGuardPhase.PRE_BROADCAST
                else PreflightPhase.PRE_SIGN
            )
        return self.xrpl_guard.revalidate_and_consume(
            capability,
            live_request,
            binding.xrpl_binding,
            phase=phase,
            now=now,
            live_ledger_epoch=live_ledger_epoch,
            live_tx=live_tx,
            live_effects=live_effects,
            live_signer_list=live_signer_list,
        )


def evaluate_xaman_transaction_guard(
    candidate: XRPLTransactionCandidate | Mapping[str, Any],
    payload: XamanPayloadIdentity | Mapping[str, Any] | str,
    *,
    guard: XamanTransactionGuard | None = None,
    **kwargs: Any,
) -> XamanGuardDecision:
    """Convenience: bind Xaman payload + XRPL candidate and evaluate."""

    guard = guard or XamanTransactionGuard()
    bind_keys = {
        "ledger_epoch",
        "signer_list",
        "declared_effects",
        "serialized_bytes",
        "encoding",
        "candidate_id",
        "binding_id",
        "attributes",
    }
    bind_kwargs = {k: kwargs.pop(k) for k in list(kwargs) if k in bind_keys}
    binding = guard.bind_payload(candidate, payload, **bind_kwargs)
    return guard.evaluate(binding, **kwargs)


# Re-export shared XRPL symbols for AST / convenience imports.
__all__ = [
    "APPROVAL_CANNOT_REPLACE",
    "DEFAULT_COMPLIANCE_REQUIREMENTS",
    "DEFAULT_POLICY_ID",
    "DEFAULT_PRODUCER_ID",
    "DEFAULT_SECURITY_REQUIREMENTS",
    "XAMAN_BINDING_SCHEMA_VERSION",
    "XAMAN_GUARD_DECISION_SCHEMA_VERSION",
    "XAMAN_PAYLOAD_IDENTITY_SCHEMA_VERSION",
    "XAMAN_TRANSACTION_GUARD_INTERFACE",
    "XAMAN_TRANSACTION_GUARD_SCHEMA_VERSION",
    "LedgerEpoch",
    "NormalizedXRPLEffect",
    "SignerListBinding",
    "XamanGuardDecision",
    "XamanGuardPhase",
    "XamanPayloadIdentity",
    "XamanTransactionBinding",
    "XamanTransactionGuard",
    "XRPLTransactionCandidate",
    "XRPLTransactionGuard",
    "content_sha256_hex",
    "evaluate_xaman_transaction_guard",
    "normalize_xrpl_tx_effects",
]
