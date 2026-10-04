"""Public GuardService cutover for every signing and broadcast boundary.

CRYPTOIR-G600 / CRYPTOIR-034.

``GuardService`` is the integration-owner surface that:

* evaluates exact-candidate transaction preflight;
* live-revalidates and atomically consumes one-use admissibility capabilities;
* exposes ``sign_transaction``, ``send_raw_transaction``, and ``broadcast``
  only after capability consumption for the matching phase;
* inventories every known sign/broadcast path for cutover evidence;
* never stores private keys, seeds, or mnemonics;
* never accepts bare booleans or caller-supplied ``approved=true`` flags.

Keys, interactive approval UI, and network broadcast transport remain the
responsibility of an external custody adapter injected at the call boundary.
Without a consumed capability the signing and broadcast paths stay disabled.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Final

from ipfs_datasets_py.logic.crypto_ir.verdicts import TransactionVerdictOutcome

from .errors import (
    GuardCapabilityError,
    GuardError,
    GuardForbiddenSurfaceError,
    GuardValidationError,
)
from .models import (
    AdmissibilityCapability,
    PreflightConsumptionResult,
    PreflightPhase,
    PreflightResult,
    TransactionPreflightRequest,
)
from .preflight import (
    DEFAULT_PRODUCER_ID,
    TransactionPreflight,
    evaluate_transaction_preflight,
)


# ---------------------------------------------------------------------------
# Schema / interface identities
# ---------------------------------------------------------------------------

GUARD_SERVICE_INTERFACE: Final = "GuardService@1"
GUARD_SERVICE_SCHEMA_VERSION: Final = "wallet-guard.guard-service/v1"
SIGN_AUTHORIZATION_SCHEMA_VERSION: Final = "wallet-guard.sign-authorization/v1"
BROADCAST_AUTHORIZATION_SCHEMA_VERSION: Final = (
    "wallet-guard.broadcast-authorization/v1"
)
SIGNING_INVENTORY_SCHEMA_VERSION: Final = "wallet-guard.signing-inventory/v1"

DEFAULT_GUARD_SERVICE_PRODUCER_ID: Final = "producer:wallet-guard-service-v1"

# Explicit denylist of compatibility escape hatches.  Legacy callers that still
# pass these fields must migrate to exact-candidate capability consumption.
_FORBIDDEN_APPROVAL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "approved",
        "approve",
        "approval",
        "is_approved",
        "caller_approved",
        "user_approved",
        "force_allow",
        "skip_guard",
        "bypass_guard",
        "bypass_policy",
        "trusted",
        "allow",
        "ok",
    }
)

_FORBIDDEN_KEY_MATERIAL_KEYS: Final[frozenset[str]] = frozenset(
    {
        "private_key",
        "privateKey",
        "signing_key",
        "signingKey",
        "seed",
        "seed_phrase",
        "mnemonic",
        "secret_key",
        "secretKey",
        "wallet_seed",
    }
)

# Repository-wide inventory of known sign / broadcast entry points that this
# cutover either gates or documents as disabled-by-default.
KNOWN_SIGNING_PATHS: Final[tuple[dict[str, str], ...]] = (
    {
        "path_id": "guard.service.sign_transaction",
        "module": "ipfs_datasets_py.processors.wallets.guard.service",
        "symbol": "GuardService.sign_transaction",
        "status": "gated",
        "phase": "pre_sign",
        "notes": "Requires consumed AdmissibilityCapability; no key storage.",
    },
    {
        "path_id": "guard.service.send_raw_transaction",
        "module": "ipfs_datasets_py.processors.wallets.guard.service",
        "symbol": "GuardService.send_raw_transaction",
        "status": "gated",
        "phase": "pre_broadcast",
        "notes": "Requires consumed AdmissibilityCapability; external broadcaster only.",
    },
    {
        "path_id": "guard.service.broadcast",
        "module": "ipfs_datasets_py.processors.wallets.guard.service",
        "symbol": "GuardService.broadcast",
        "status": "gated",
        "phase": "pre_broadcast",
        "notes": "Alias of send_raw_transaction under the cutover service.",
    },
    {
        "path_id": "zkp.eth_integration.submit_proof_transaction",
        "module": "ipfs_datasets_py.logic.zkp.eth_integration",
        "symbol": "EthereumProofClient.submit_proof_transaction",
        "status": "gated",
        "phase": "pre_sign",
        "notes": "Disabled by default; requires consumed guard capability.",
    },
    {
        "path_id": "zkp.eth_integration.register_vk_hash",
        "module": "ipfs_datasets_py.logic.zkp.eth_integration",
        "symbol": "EthereumProofClient.register_vk_hash",
        "status": "gated",
        "phase": "pre_sign",
        "notes": "Disabled by default; requires consumed guard capability.",
    },
    {
        "path_id": "zkp.eth_integration.pipeline",
        "module": "ipfs_datasets_py.logic.zkp.eth_integration",
        "symbol": "ProofSubmissionPipeline.generate_and_verify_proof",
        "status": "gated",
        "phase": "pre_sign",
        "notes": "On-chain submission path inherits EthereumProofClient gate.",
    },
    {
        "path_id": "wallets.api.sign_verbs",
        "module": "ipfs_datasets_py.processors.wallets.api",
        "symbol": "WalletProcessorAPI.__getattr__",
        "status": "disabled",
        "phase": "n/a",
        "notes": "Read-only facade; sign/broadcast verbs raise UnsupportedCapabilityError.",
    },
    {
        "path_id": "wallets.registry.processors",
        "module": "ipfs_datasets_py.processors.wallets.registry",
        "symbol": "WalletProcessorRegistry / WalletRegistry",
        "status": "disabled",
        "phase": "n/a",
        "notes": "Processors declare supports_sign=False / supports_broadcast=False.",
    },
    {
        "path_id": "smart_contracts.api",
        "module": "ipfs_datasets_py.processors.smart_contracts.api",
        "symbol": "SmartContractProcessorAPI",
        "status": "disabled",
        "phase": "n/a",
        "notes": "Read-only acquisition/lookup; SigningForbiddenError on custody verbs.",
    },
)


# ---------------------------------------------------------------------------
# Result records
# ---------------------------------------------------------------------------


def _iso_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _reject_forbidden_kwargs(options: Mapping[str, Any] | None, *, surface: str) -> None:
    """Fail closed on approved=true escape hatches and inline key material."""

    if not options:
        return
    if not isinstance(options, Mapping):
        raise GuardValidationError(f"{surface} options must be a mapping")
    for key, value in options.items():
        key_text = str(key)
        lowered = key_text.strip().lower()
        if lowered in _FORBIDDEN_APPROVAL_KEYS or key_text in _FORBIDDEN_APPROVAL_KEYS:
            raise GuardForbiddenSurfaceError(
                f"{surface} rejects compatibility escape hatch {key_text!r}; "
                "legacy callers must migrate to exact-candidate capability "
                "consumption (no approved=true bypass)",
                reason_code="guard.forbidden_approval_escape",
                details={"field": key_text, "surface": surface},
            )
        if key_text in _FORBIDDEN_KEY_MATERIAL_KEYS or lowered in {
            k.lower() for k in _FORBIDDEN_KEY_MATERIAL_KEYS
        }:
            raise GuardForbiddenSurfaceError(
                f"{surface} never accepts key material field {key_text!r}; "
                "keys remain with an external custody adapter",
                reason_code="guard.forbidden_key_material",
                details={"field": key_text, "surface": surface},
            )
        # Boolean True under any approval-like key is also rejected above;
        # additionally reject bare approved-style values nested under "flags".
        if lowered in {"flags", "options", "meta", "metadata"} and isinstance(
            value, Mapping
        ):
            _reject_forbidden_kwargs(value, surface=f"{surface}.{key_text}")


def _coerce_request(
    request: TransactionPreflightRequest | Mapping[str, Any],
) -> TransactionPreflightRequest:
    if isinstance(request, TransactionPreflightRequest):
        return request
    if isinstance(request, Mapping):
        _reject_forbidden_kwargs(request, surface="TransactionPreflightRequest")
        return TransactionPreflightRequest.from_dict(request)
    raise GuardValidationError(
        "request must be a TransactionPreflightRequest or mapping"
    )


def _coerce_capability(
    capability: AdmissibilityCapability | Mapping[str, Any],
) -> AdmissibilityCapability:
    if isinstance(capability, AdmissibilityCapability):
        return capability
    if isinstance(capability, Mapping):
        _reject_forbidden_kwargs(capability, surface="AdmissibilityCapability")
        return AdmissibilityCapability.from_dict(capability)
    raise GuardValidationError(
        "capability must be an AdmissibilityCapability or mapping"
    )


def _normalize_phase(phase: PreflightPhase | str) -> PreflightPhase:
    if isinstance(phase, PreflightPhase):
        return phase
    text = str(phase).strip().lower()
    if text == PreflightPhase.PRE_SIGN.value:
        return PreflightPhase.PRE_SIGN
    if text == PreflightPhase.PRE_BROADCAST.value:
        return PreflightPhase.PRE_BROADCAST
    raise GuardValidationError("phase must be pre_sign or pre_broadcast")


@dataclass(frozen=True, slots=True)
class SignAuthorization:
    """Proof that pre-sign capability consumption succeeded.

    This is not a signature and does not contain key material.  External
    custody may proceed only when ``allowed`` is true.
    """

    allowed: bool
    capability_id: str
    request_digest: str
    candidate_digest: str
    phase: str
    consumption: PreflightConsumptionResult
    signed_payload: Any = None
    schema_version: str = SIGN_AUTHORIZATION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "capability_id": self.capability_id,
            "candidate_digest": self.candidate_digest,
            "consumption": self.consumption.to_dict(),
            "phase": self.phase,
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
            "signed_payload_present": self.signed_payload is not None,
        }


@dataclass(frozen=True, slots=True)
class BroadcastAuthorization:
    """Proof that pre-broadcast capability consumption succeeded."""

    allowed: bool
    capability_id: str
    request_digest: str
    candidate_digest: str
    phase: str
    consumption: PreflightConsumptionResult
    broadcast_receipt: Any = None
    schema_version: str = BROADCAST_AUTHORIZATION_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "broadcast_receipt_present": self.broadcast_receipt is not None,
            "capability_id": self.capability_id,
            "candidate_digest": self.candidate_digest,
            "consumption": self.consumption.to_dict(),
            "phase": self.phase,
            "request_digest": self.request_digest,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class SigningPathInventory:
    """Immutable inventory of sign/broadcast paths covered by the cutover."""

    paths: tuple[Mapping[str, str], ...]
    schema_version: str = SIGNING_INVENTORY_SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "path_count": len(self.paths),
            "paths": [dict(path) for path in self.paths],
            "schema_version": self.schema_version,
        }


# ---------------------------------------------------------------------------
# GuardService
# ---------------------------------------------------------------------------


@dataclass
class GuardService:
    """Public service API for guarded preflight and signing boundaries.

    Parameters
    ----------
    preflight:
        Shared :class:`TransactionPreflight` engine (capability store is
        process-local unless a durable store is injected).
    producer_id:
        Receipt / capability producer identity.
    signing_enabled:
        Master switch.  When false (default for legacy-unmigrated hosts),
        ``sign_transaction`` / ``send_raw_transaction`` / ``broadcast`` refuse
        even with a capability until the host explicitly enables gated signing.
        Read-only preflight evaluation remains available.
    enable_signing_with_capability:
        When true (default), gated signing is permitted only after successful
        live revalidation and atomic capability consumption.  There is no
        ``approved=true`` escape hatch.
    """

    preflight: TransactionPreflight | None = None
    producer_id: str = DEFAULT_GUARD_SERVICE_PRODUCER_ID
    signing_enabled: bool = True
    enable_signing_with_capability: bool = True
    interface: str = GUARD_SERVICE_INTERFACE
    schema_version: str = GUARD_SERVICE_SCHEMA_VERSION
    _registry: Any = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if self.preflight is None:
            self.preflight = TransactionPreflight(producer_id=self.producer_id)
        if self.interface != GUARD_SERVICE_INTERFACE:
            raise GuardValidationError(
                f"unsupported guard service interface: {self.interface!r}"
            )
        if self.schema_version != GUARD_SERVICE_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported guard service schema: {self.schema_version!r}"
            )

    # -- discovery / inventory ----------------------------------------------

    def inventory_signing_paths(self) -> SigningPathInventory:
        """Return the cutover inventory of known sign/broadcast paths."""

        return SigningPathInventory(paths=KNOWN_SIGNING_PATHS)

    def capabilities(self) -> Mapping[str, Any]:
        """Inspectable service capabilities (no custody authority)."""

        return MappingProxyType(
            {
                "interface": self.interface,
                "schema_version": self.schema_version,
                "producer_id": self.producer_id,
                "supports_preflight": True,
                "supports_capability_consumption": True,
                "supports_sign": bool(
                    self.signing_enabled and self.enable_signing_with_capability
                ),
                "supports_broadcast": bool(
                    self.signing_enabled and self.enable_signing_with_capability
                ),
                "requires_consumed_capability": True,
                "approved_escape_hatch": False,
                "stores_keys": False,
                "read_only_lookup": True,
            }
        )

    # -- preflight (read-only policy evaluation) ----------------------------

    def evaluate_preflight(
        self,
        request: TransactionPreflightRequest | Mapping[str, Any],
        *,
        security_results: Mapping[str, Any] | None = None,
        compliance_results: Mapping[str, Any] | None = None,
        outcome_override: TransactionVerdictOutcome | str | None = None,
        now: str | None = None,
        derive_capability_on_allow: bool = True,
        options: Mapping[str, Any] | None = None,
    ) -> PreflightResult:
        """Evaluate exact-candidate preflight without custody authority.

        Read-only: issues a one-use capability on ``ALLOW`` but never signs.
        """

        _reject_forbidden_kwargs(options, surface="evaluate_preflight")
        if isinstance(outcome_override, bool):
            raise GuardForbiddenSurfaceError(
                "bare boolean outcomes are forbidden; use TransactionVerdictOutcome"
            )
        request_obj = _coerce_request(request)
        assert self.preflight is not None
        return self.preflight.evaluate(
            request_obj,
            security_results=security_results,
            compliance_results=compliance_results,
            outcome_override=outcome_override,
            now=now,
            derive_capability_on_allow=derive_capability_on_allow,
        )

    def revalidate_and_consume(
        self,
        capability: AdmissibilityCapability | Mapping[str, Any],
        live_request: TransactionPreflightRequest | Mapping[str, Any],
        *,
        phase: PreflightPhase | str = PreflightPhase.PRE_SIGN,
        now: str | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> PreflightConsumptionResult:
        """Live-revalidate and atomically consume a one-use capability."""

        _reject_forbidden_kwargs(options, surface="revalidate_and_consume")
        assert self.preflight is not None
        return self.preflight.revalidate_and_consume(
            _coerce_capability(capability),
            _coerce_request(live_request),
            phase=_normalize_phase(phase),
            now=now,
        )

    def is_consumed(
        self,
        capability: AdmissibilityCapability | Mapping[str, Any],
        *,
        tenant_id: str | None = None,
    ) -> bool:
        assert self.preflight is not None
        return self.preflight.is_consumed(
            _coerce_capability(capability), tenant_id=tenant_id
        )

    # -- signing boundary ---------------------------------------------------

    def sign_transaction(
        self,
        *,
        capability: AdmissibilityCapability | Mapping[str, Any] | None = None,
        live_request: TransactionPreflightRequest | Mapping[str, Any] | None = None,
        unsigned_candidate: Any = None,
        external_signer: Callable[[Any, SignAuthorization], Any] | None = None,
        now: str | None = None,
        options: Mapping[str, Any] | None = None,
        # Explicitly rejected legacy kwargs — kept in the signature so callers
        # get a typed ForbiddenSurface error rather than a silent TypeError
        # when migrating from approved=true helpers.
        approved: Any = None,
        private_key: Any = None,
    ) -> SignAuthorization:
        """Authorize (and optionally invoke external) signing for one candidate.

        Requires successful pre-sign capability consumption immediately before
        any external signer runs.  Never accepts ``approved=true`` or stores
        private keys.
        """

        if approved is not None:
            raise GuardForbiddenSurfaceError(
                "sign_transaction rejects approved=...; migrate to "
                "AdmissibilityCapability consumption",
                reason_code="guard.forbidden_approval_escape",
                details={"field": "approved"},
            )
        if private_key is not None:
            raise GuardForbiddenSurfaceError(
                "sign_transaction never accepts private_key; inject an "
                "external_signer custody adapter instead",
                reason_code="guard.forbidden_key_material",
                details={"field": "private_key"},
            )
        _reject_forbidden_kwargs(options, surface="sign_transaction")
        self._assert_signing_enabled(surface="sign_transaction")

        if capability is None or live_request is None:
            raise GuardCapabilityError(
                "sign_transaction is disabled without a consumed-path "
                "AdmissibilityCapability and matching live_request",
                reason_code="guard.signing_disabled",
            )

        cap = _coerce_capability(capability)
        request = _coerce_request(live_request)
        consumption = self.revalidate_and_consume(
            cap,
            request,
            phase=PreflightPhase.PRE_SIGN,
            now=now or _iso_now(),
        )
        if not consumption.allowed:
            raise GuardCapabilityError(
                "pre-sign capability consumption did not allow signing",
                reason_code="guard.sign_not_allowed",
            )

        authorization = SignAuthorization(
            allowed=True,
            capability_id=cap.capability_id,
            request_digest=request.request_digest,
            candidate_digest=request.candidate_digest,
            phase=PreflightPhase.PRE_SIGN.value,
            consumption=consumption,
            signed_payload=None,
        )

        signed_payload: Any = None
        if external_signer is not None:
            try:
                signed_payload = external_signer(unsigned_candidate, authorization)
            except GuardError:
                raise
            except Exception as exc:  # pragma: no cover - custody adapter failure
                raise GuardCapabilityError(
                    f"external signer failed after capability consumption: {exc}",
                    reason_code="guard.external_signer_error",
                ) from exc
            authorization = SignAuthorization(
                allowed=True,
                capability_id=cap.capability_id,
                request_digest=request.request_digest,
                candidate_digest=request.candidate_digest,
                phase=PreflightPhase.PRE_SIGN.value,
                consumption=consumption,
                signed_payload=signed_payload,
            )
        return authorization

    # -- broadcast boundary -------------------------------------------------

    def send_raw_transaction(
        self,
        *,
        capability: AdmissibilityCapability | Mapping[str, Any] | None = None,
        live_request: TransactionPreflightRequest | Mapping[str, Any] | None = None,
        raw_transaction: Any = None,
        external_broadcaster: Callable[[Any, BroadcastAuthorization], Any]
        | None = None,
        now: str | None = None,
        options: Mapping[str, Any] | None = None,
        approved: Any = None,
        private_key: Any = None,
    ) -> BroadcastAuthorization:
        """Authorize (and optionally invoke external) broadcast for one candidate.

        Requires successful pre-broadcast capability consumption immediately
        before any external broadcaster runs.
        """

        if approved is not None:
            raise GuardForbiddenSurfaceError(
                "send_raw_transaction rejects approved=...; migrate to "
                "AdmissibilityCapability consumption",
                reason_code="guard.forbidden_approval_escape",
                details={"field": "approved"},
            )
        if private_key is not None:
            raise GuardForbiddenSurfaceError(
                "send_raw_transaction never accepts private_key",
                reason_code="guard.forbidden_key_material",
                details={"field": "private_key"},
            )
        _reject_forbidden_kwargs(options, surface="send_raw_transaction")
        self._assert_signing_enabled(surface="send_raw_transaction")

        if capability is None or live_request is None:
            raise GuardCapabilityError(
                "send_raw_transaction is disabled without a consumed-path "
                "AdmissibilityCapability and matching live_request",
                reason_code="guard.broadcast_disabled",
            )

        cap = _coerce_capability(capability)
        request = _coerce_request(live_request)
        consumption = self.revalidate_and_consume(
            cap,
            request,
            phase=PreflightPhase.PRE_BROADCAST,
            now=now or _iso_now(),
        )
        if not consumption.allowed:
            raise GuardCapabilityError(
                "pre-broadcast capability consumption did not allow broadcast",
                reason_code="guard.broadcast_not_allowed",
            )

        authorization = BroadcastAuthorization(
            allowed=True,
            capability_id=cap.capability_id,
            request_digest=request.request_digest,
            candidate_digest=request.candidate_digest,
            phase=PreflightPhase.PRE_BROADCAST.value,
            consumption=consumption,
            broadcast_receipt=None,
        )

        receipt: Any = None
        if external_broadcaster is not None:
            try:
                receipt = external_broadcaster(raw_transaction, authorization)
            except GuardError:
                raise
            except Exception as exc:  # pragma: no cover
                raise GuardCapabilityError(
                    f"external broadcaster failed after capability consumption: {exc}",
                    reason_code="guard.external_broadcaster_error",
                ) from exc
            authorization = BroadcastAuthorization(
                allowed=True,
                capability_id=cap.capability_id,
                request_digest=request.request_digest,
                candidate_digest=request.candidate_digest,
                phase=PreflightPhase.PRE_BROADCAST.value,
                consumption=consumption,
                broadcast_receipt=receipt,
            )
        return authorization

    def broadcast(
        self,
        *,
        capability: AdmissibilityCapability | Mapping[str, Any] | None = None,
        live_request: TransactionPreflightRequest | Mapping[str, Any] | None = None,
        raw_transaction: Any = None,
        external_broadcaster: Callable[[Any, BroadcastAuthorization], Any]
        | None = None,
        now: str | None = None,
        options: Mapping[str, Any] | None = None,
        approved: Any = None,
        private_key: Any = None,
    ) -> BroadcastAuthorization:
        """AST alias of :meth:`send_raw_transaction`."""

        return self.send_raw_transaction(
            capability=capability,
            live_request=live_request,
            raw_transaction=raw_transaction,
            external_broadcaster=external_broadcaster,
            now=now,
            options=options,
            approved=approved,
            private_key=private_key,
        )

    # -- internals ----------------------------------------------------------

    def _assert_signing_enabled(self, *, surface: str) -> None:
        if not self.signing_enabled:
            raise GuardCapabilityError(
                f"{surface} is disabled by host policy "
                "(signing_enabled=False); enable only after cutover review",
                reason_code="guard.signing_master_disabled",
            )
        if not self.enable_signing_with_capability:
            raise GuardCapabilityError(
                f"{surface} requires enable_signing_with_capability=True; "
                "there is no approved=true compatibility path",
                reason_code="guard.signing_capability_gate_disabled",
            )


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------

_DEFAULT_SERVICE: GuardService | None = None


def get_default_guard_service() -> GuardService:
    global _DEFAULT_SERVICE
    if _DEFAULT_SERVICE is None:
        _DEFAULT_SERVICE = GuardService()
    return _DEFAULT_SERVICE


def reset_default_guard_service() -> None:
    global _DEFAULT_SERVICE
    _DEFAULT_SERVICE = None


def evaluate_guard_preflight(
    request: TransactionPreflightRequest | Mapping[str, Any],
    **kwargs: Any,
) -> PreflightResult:
    """Module-level preflight entry (read-only)."""

    return get_default_guard_service().evaluate_preflight(request, **kwargs)


def sign_transaction(**kwargs: Any) -> SignAuthorization:
    """Module-level AST symbol: ``sign_transaction``."""

    return get_default_guard_service().sign_transaction(**kwargs)


def send_raw_transaction(**kwargs: Any) -> BroadcastAuthorization:
    """Module-level AST symbol: ``send_raw_transaction``."""

    return get_default_guard_service().send_raw_transaction(**kwargs)


def broadcast(**kwargs: Any) -> BroadcastAuthorization:
    """Module-level AST symbol: ``broadcast``."""

    return get_default_guard_service().broadcast(**kwargs)


__all__ = [
    "BROADCAST_AUTHORIZATION_SCHEMA_VERSION",
    "BroadcastAuthorization",
    "DEFAULT_GUARD_SERVICE_PRODUCER_ID",
    "GUARD_SERVICE_INTERFACE",
    "GUARD_SERVICE_SCHEMA_VERSION",
    "GuardService",
    "KNOWN_SIGNING_PATHS",
    "SIGN_AUTHORIZATION_SCHEMA_VERSION",
    "SIGNING_INVENTORY_SCHEMA_VERSION",
    "SignAuthorization",
    "SigningPathInventory",
    "broadcast",
    "evaluate_guard_preflight",
    "evaluate_transaction_preflight",
    "get_default_guard_service",
    "reset_default_guard_service",
    "send_raw_transaction",
    "sign_transaction",
]
