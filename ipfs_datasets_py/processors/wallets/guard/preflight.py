"""Fail-closed transaction preflight over ``logic.admissibility``.

``TransactionPreflight`` is a custody-neutral guard contract:

* binds an unsigned :class:`TransactionIntent` and exact
  :class:`TransactionCandidate`;
* composes declared security and compliance requirements;
* issues a request-bound, one-use :class:`AdmissibilityCapability` only after
  a current ``ALLOW``;
* live-revalidates and atomically consumes that capability at pre-sign and
  pre-broadcast boundaries.

Signing keys, user approval UI, and broadcast remain the responsibility of an
external custody system.  This module never accepts bare booleans, caller
approval flags, private keys, signatures, or broadcast handles as authority.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Final

from ipfs_datasets_py.logic.admissibility.compose import InternalDecisionStatus
from ipfs_datasets_py.logic.admissibility.enforcement import (
    CapabilityConsumptionStore,
    ConsumptionRaceError,
    ConsumptionStoreError,
    InMemoryCapabilityConsumptionStore,
    consume_dispatch_capability,
)
from ipfs_datasets_py.logic.admissibility.receipt import (
    BoundContext,
    BoundRoots,
    CapabilityDerivationError,
    DecisionReceipt,
    ReceiptError,
    ReceiptVerificationError,
    build_decision_receipt,
    derive_capability,
    verify_capability,
    verify_decision_receipt,
)
from ipfs_datasets_py.logic.crypto_ir.verdicts import (
    TransactionVerdictOutcome,
    transaction_blocks_automation,
)
from ipfs_datasets_py.logic.ir_core.claims import stable_digest

from .errors import (
    GuardCapabilityError,
    GuardConsumptionRaceError,
    GuardError,
    GuardForbiddenSurfaceError,
    GuardPolicyError,
    GuardValidationError,
)
from .models import (
    AdmissibilityCapability,
    PreflightConsumptionResult,
    PreflightPhase,
    PreflightResult,
    TransactionPreflightRequest,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRANSACTION_PREFLIGHT_INTERFACE: Final = "TransactionPreflight@1"
TRANSACTION_PREFLIGHT_SCHEMA_VERSION: Final = "wallet-guard.transaction-preflight/v1"
DEFAULT_PRODUCER_ID: Final = "producer:wallet-guard-preflight-v1"
DEFAULT_ALLOWED_EFFECT: Final = "effect:wallet.sign-candidate"
REQUIREMENT_PASS: Final = "pass"


# ---------------------------------------------------------------------------
# Requirement composition
# ---------------------------------------------------------------------------


def _normalize_requirement_result(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip().lower()
        if not text:
            raise GuardPolicyError("requirement result must be non-empty")
        return text
    raise GuardPolicyError(
        f"requirement result must be a string outcome (got {type(value).__name__})"
    )


def compose_requirement_outcomes(
    declared: Sequence[str],
    results: Mapping[str, Any] | None,
    *,
    family: str,
) -> tuple[TransactionVerdictOutcome | None, list[str], list[str], dict[str, str]]:
    """Compose named requirement results into a partial verdict.

    Returns ``(blocking_outcome_or_None, reason_codes, reasons, normalized)``.
    A missing declared result is fail-closed as ``INCONCLUSIVE``.
    """

    normalized: dict[str, str] = {}
    reason_codes: list[str] = []
    reasons: list[str] = []
    blocking: TransactionVerdictOutcome | None = None

    provided = dict(results or {})
    for req_id in declared:
        if req_id not in provided:
            reason_codes.append(f"{family}.missing:{req_id}")
            reasons.append(f"missing {family} requirement result for {req_id}")
            blocking = TransactionVerdictOutcome.INCONCLUSIVE
            normalized[req_id] = "missing"
            continue
        outcome = _normalize_requirement_result(provided[req_id])
        normalized[req_id] = outcome
        if outcome == REQUIREMENT_PASS:
            continue
        if outcome in {"stale"}:
            reason_codes.append(f"{family}.stale:{req_id}")
            reasons.append(f"{family} requirement {req_id} is stale")
            if blocking is None or blocking is TransactionVerdictOutcome.ALLOW:
                blocking = TransactionVerdictOutcome.STALE
            continue
        if outcome in {"review"}:
            reason_codes.append(f"{family}.review:{req_id}")
            reasons.append(f"{family} requirement {req_id} requires review")
            if blocking is None or blocking is TransactionVerdictOutcome.ALLOW:
                blocking = TransactionVerdictOutcome.REVIEW
            continue
        if outcome in {"deny", "fail", "disproved"}:
            reason_codes.append(f"{family}.deny:{req_id}")
            reasons.append(f"{family} requirement {req_id} denied")
            blocking = TransactionVerdictOutcome.DENY
            continue
        if outcome in {"error"}:
            reason_codes.append(f"{family}.error:{req_id}")
            reasons.append(f"{family} requirement {req_id} errored")
            if blocking is not TransactionVerdictOutcome.DENY:
                blocking = TransactionVerdictOutcome.ERROR
            continue
        # unknown / unsupported / inconclusive / not_ready / missing / other
        reason_codes.append(f"{family}.inconclusive:{req_id}")
        reasons.append(
            f"{family} requirement {req_id} is inconclusive ({outcome})"
        )
        if blocking is None or blocking is TransactionVerdictOutcome.ALLOW:
            blocking = TransactionVerdictOutcome.INCONCLUSIVE

    # Undeclared extra results do not expand authority; they are ignored for
    # allow, but still recorded as policy noise via normalized map only when
    # they collide with declared IDs (handled above).
    return blocking, reason_codes, reasons, normalized


def _default_roots(policy_id: str) -> BoundRoots:
    return BoundRoots(
        policy_root=f"policy:{policy_id}",
        corpus_roots=("corpus:wallet-guard",),
        revocation_root="revocation:wallet-guard",
    )


def _effect_ids_for(request: TransactionPreflightRequest) -> tuple[str, ...]:
    # Capability effects must be stable identifiers; map expected effects plus
    # the dedicated sign-candidate effect used by custody adapters.
    effects = [DEFAULT_ALLOWED_EFFECT]
    for item in request.intent.expected_effects:
        effects.append(item.effect_id)
    # unique preserve order then sorted for BoundContext
    return tuple(sorted(set(effects)))


def _build_bound_context(request: TransactionPreflightRequest) -> BoundContext:
    arguments_digest = stable_digest(
        {
            "candidate": request.candidate.to_dict(),
            "intent": request.intent.to_dict(),
        }
    )
    return BoundContext(
        request_digest=request.request_digest,
        arguments_digest=arguments_digest,
        actor_id=request.actor_id,
        audience_id=request.audience_id,
        tool_id="tool:wallet.preflight",
        tool_version="1.0.0",
        effect_ids=_effect_ids_for(request),
        environment_digest=request.environment_digest or ("e" * 64),
        environment_id=request.environment_id or "env:wallet-guard",
        resource_ids=(
            f"resource:intent:{request.intent.intent_id}",
            f"resource:candidate:{request.candidate.candidate_id}",
        ),
        nonce=request.nonce,
        metadata={
            "network": request.intent.network,
            "tenant_id": request.tenant_id,
            "intent_digest": request.intent_digest,
            "candidate_digest": request.candidate_digest,
        },
    )


def _iso_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _is_expired(expiry: str, now: str) -> bool:
    return now > expiry


# ---------------------------------------------------------------------------
# TransactionPreflight
# ---------------------------------------------------------------------------


@dataclass
class TransactionPreflight:
    """Custody-neutral preflight evaluator and capability issuer.

    The processor issues evidence-bound permission only.  An external custody
    system remains responsible for keys and user approval.
    """

    producer_id: str = DEFAULT_PRODUCER_ID
    consumption_store: CapabilityConsumptionStore | None = None
    interface: str = TRANSACTION_PREFLIGHT_INTERFACE
    schema_version: str = TRANSACTION_PREFLIGHT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.consumption_store is None:
            self.consumption_store = InMemoryCapabilityConsumptionStore()
        if self.interface != TRANSACTION_PREFLIGHT_INTERFACE:
            raise GuardValidationError(
                f"unsupported preflight interface: {self.interface!r}"
            )
        if self.schema_version != TRANSACTION_PREFLIGHT_SCHEMA_VERSION:
            raise GuardValidationError(
                f"unsupported preflight schema: {self.schema_version!r}"
            )

    # -- evaluation ---------------------------------------------------------

    def evaluate(
        self,
        request: TransactionPreflightRequest | Mapping[str, Any],
        *,
        security_results: Mapping[str, Any] | None = None,
        compliance_results: Mapping[str, Any] | None = None,
        outcome_override: TransactionVerdictOutcome | str | None = None,
        now: str | None = None,
        derive_capability_on_allow: bool = True,
    ) -> PreflightResult:
        """Evaluate a preflight request and optionally issue a capability.

        Parameters
        ----------
        request:
            Exact intent + candidate binding.
        security_results / compliance_results:
            Maps of requirement id → outcome string (``pass`` or fail-closed).
        outcome_override:
            Optional explicit terminal outcome (still fails closed; cannot be a
            bare boolean and cannot inject keys).  When omitted, requirements
            are composed deterministically.
        now:
            Evaluation clock (ISO-8601).  Defaults to UTC now.
        derive_capability_on_allow:
            When true (default), mint a one-use capability only on ``ALLOW``.
        """

        if not isinstance(request, TransactionPreflightRequest):
            if isinstance(request, Mapping):
                request = TransactionPreflightRequest.from_dict(request)
            else:
                raise GuardValidationError(
                    "request must be a TransactionPreflightRequest"
                )

        clock = now or _iso_now()
        reasons: list[str] = []
        reason_codes: list[str] = []

        # Freshness: request and intent expiry.
        if _is_expired(request.expiry, clock):
            return self._blocked(
                request,
                TransactionVerdictOutcome.STALE,
                reason_codes=["preflight.expired"],
                reasons=["preflight request expired before evaluation"],
                security_results={},
                compliance_results={},
            )
        if _is_expired(request.intent.expires_at, clock):
            return self._blocked(
                request,
                TransactionVerdictOutcome.STALE,
                reason_codes=["preflight.intent_expired"],
                reasons=["unsigned intent expired before evaluation"],
                security_results={},
                compliance_results={},
            )

        sec_block, sec_codes, sec_reasons, sec_norm = compose_requirement_outcomes(
            request.security_requirement_ids,
            security_results,
            family="security",
        )
        comp_block, comp_codes, comp_reasons, comp_norm = compose_requirement_outcomes(
            request.compliance_requirement_ids,
            compliance_results,
            family="compliance",
        )
        reason_codes.extend(sec_codes)
        reason_codes.extend(comp_codes)
        reasons.extend(sec_reasons)
        reasons.extend(comp_reasons)

        outcome = self._compose_terminal(
            sec_block, comp_block, outcome_override, reason_codes, reasons
        )

        if transaction_blocks_automation(outcome):
            return self._blocked(
                request,
                outcome,
                reason_codes=reason_codes or [f"preflight.{outcome.value}"],
                reasons=reasons or [f"preflight outcome {outcome.value}"],
                security_results=sec_norm,
                compliance_results=comp_norm,
            )

        # ALLOW path: mint receipt + one-use capability.
        try:
            receipt = self._build_allow_receipt(
                request, reason_codes=reason_codes, reasons=reasons
            )
        except (ReceiptError, GuardError) as exc:
            return self._blocked(
                request,
                TransactionVerdictOutcome.ERROR,
                reason_codes=["preflight.receipt_error"],
                reasons=[f"failed to build decision receipt: {exc}"],
                security_results=sec_norm,
                compliance_results=comp_norm,
            )

        capability: AdmissibilityCapability | None = None
        if derive_capability_on_allow:
            try:
                capability = self._issue_capability(request, receipt)
            except (
                CapabilityDerivationError,
                ReceiptError,
                GuardError,
            ) as exc:
                return self._blocked(
                    request,
                    TransactionVerdictOutcome.ERROR,
                    reason_codes=["preflight.capability_error"],
                    reasons=[f"failed to derive capability: {exc}"],
                    security_results=sec_norm,
                    compliance_results=comp_norm,
                    receipt=receipt,
                )
        else:
            # Without a capability, ALLOW cannot leave automation open.
            return self._blocked(
                request,
                TransactionVerdictOutcome.INCONCLUSIVE,
                reason_codes=["preflight.capability_not_derived"],
                reasons=["ALLOW without capability derivation blocks automation"],
                security_results=sec_norm,
                compliance_results=comp_norm,
                receipt=receipt,
            )

        return PreflightResult(
            request_digest=request.request_digest,
            outcome=TransactionVerdictOutcome.ALLOW,
            blocks_automation=False,
            reason_codes=tuple(reason_codes) or ("preflight.allow",),
            reasons=tuple(reasons) or ("all required checks passed",),
            receipt_id=receipt.receipt_id,
            receipt_digest=receipt.digest,
            capability=capability,
            security_results=sec_norm,
            compliance_results=comp_norm,
        )

    # -- live revalidation + atomic consumption -----------------------------

    def revalidate_and_consume(
        self,
        capability: AdmissibilityCapability | Mapping[str, Any],
        live_request: TransactionPreflightRequest | Mapping[str, Any],
        *,
        phase: PreflightPhase | str = PreflightPhase.PRE_SIGN,
        now: str | None = None,
        receipt: DecisionReceipt | Mapping[str, Any] | None = None,
    ) -> PreflightConsumptionResult:
        """Live-revalidate and atomically consume a one-use capability.

        Rejects substitution of network/sender/destination/method/candidate
        bytes, expiry, audience, or tenant.  Concurrent second consumption
        fails closed as a race.
        """

        if not isinstance(capability, AdmissibilityCapability):
            if isinstance(capability, Mapping):
                capability = AdmissibilityCapability.from_dict(capability)
            else:
                raise GuardValidationError(
                    "capability must be an AdmissibilityCapability"
                )
        if not isinstance(live_request, TransactionPreflightRequest):
            if isinstance(live_request, Mapping):
                live_request = TransactionPreflightRequest.from_dict(live_request)
            else:
                raise GuardValidationError(
                    "live_request must be a TransactionPreflightRequest"
                )

        if isinstance(phase, PreflightPhase):
            phase_value = phase.value
        else:
            phase_value = str(phase)
        if phase_value not in {
            PreflightPhase.PRE_SIGN.value,
            PreflightPhase.PRE_BROADCAST.value,
        }:
            raise GuardValidationError(
                "phase must be pre_sign or pre_broadcast"
            )

        clock = now or _iso_now()

        try:
            capability.authorization.verify_integrity()
            verify_capability(capability.authorization)
        except (ReceiptError, ReceiptVerificationError) as exc:
            raise GuardCapabilityError(
                f"capability integrity failed: {exc}",
                reason_code="guard.capability_invalid",
            ) from exc

        # Expiry
        if _is_expired(capability.expiry, clock):
            raise GuardCapabilityError(
                "admissibility capability expired",
                reason_code="guard.expired",
                details={"expiry": capability.expiry, "now": clock},
            )
        if _is_expired(live_request.expiry, clock):
            raise GuardCapabilityError(
                "live request expired at consumption",
                reason_code="guard.request_expired",
            )
        if _is_expired(live_request.intent.expires_at, clock):
            raise GuardCapabilityError(
                "live intent expired at consumption",
                reason_code="guard.intent_expired",
            )

        # Exact binding revalidation (substitution resistance)
        mismatches: list[str] = []
        if capability.request_digest != live_request.request_digest:
            mismatches.append("request_digest")
        if capability.intent_digest != live_request.intent_digest:
            mismatches.append("intent_digest")
        if capability.candidate_digest != live_request.candidate_digest:
            mismatches.append("candidate_digest")
        if capability.network != live_request.intent.network:
            mismatches.append("network")
        if capability.intent_id != live_request.intent.intent_id:
            mismatches.append("intent_id")
        if capability.candidate_id != live_request.candidate.candidate_id:
            mismatches.append("candidate_id")
        if capability.tenant_id != live_request.tenant_id:
            mismatches.append("tenant_id")
        if capability.audience_id != live_request.audience_id:
            mismatches.append("audience_id")
        if (
            capability.authorization.request_digest
            != live_request.request_digest
        ):
            mismatches.append("authorization.request_digest")
        if mismatches:
            raise GuardCapabilityError(
                "live request does not match capability binding: "
                + ", ".join(mismatches),
                reason_code="guard.context_mismatch",
                details={"mismatches": mismatches},
            )

        # Optional receipt revalidation when supplied by the caller.
        if receipt is not None:
            if isinstance(receipt, Mapping):
                receipt = DecisionReceipt.from_dict(receipt)
            if not isinstance(receipt, DecisionReceipt):
                raise GuardValidationError("receipt must be a DecisionReceipt")
            try:
                verify_decision_receipt(receipt)
            except (ReceiptError, ReceiptVerificationError) as exc:
                raise GuardCapabilityError(
                    f"receipt verification failed: {exc}",
                    reason_code="guard.receipt_invalid",
                ) from exc
            if not receipt.permits_capability_derivation:
                raise GuardCapabilityError(
                    "receipt is not a current ALLOW",
                    reason_code="guard.non_allow",
                )
            if receipt.receipt_id != capability.authorization.receipt_id:
                raise GuardCapabilityError(
                    "receipt_id does not match capability",
                    reason_code="guard.receipt_mismatch",
                )
            if receipt.digest != capability.authorization.receipt_digest:
                raise GuardCapabilityError(
                    "receipt digest does not match capability",
                    reason_code="guard.receipt_mismatch",
                )

        store = self.consumption_store
        assert store is not None
        try:
            record = consume_dispatch_capability(
                store,
                capability.authorization,
                tenant_id=capability.tenant_id,
                now=clock,
                consumer_id=f"consumer:wallet-guard:{phase_value}",
            )
        except ConsumptionRaceError as exc:
            raise GuardConsumptionRaceError(
                "admissibility capability already consumed",
                capability_id=capability.capability_id,
            ) from exc
        except (ConsumptionStoreError, ReceiptError, ReceiptVerificationError) as exc:
            raise GuardCapabilityError(
                f"capability consumption failed: {exc}",
                reason_code="guard.consumption_error",
            ) from exc

        return PreflightConsumptionResult(
            allowed=True,
            reason_code="guard.consumed",
            reason=f"capability consumed for {phase_value}",
            capability_id=capability.capability_id,
            request_digest=live_request.request_digest,
            phase=phase_value,
            consumed_at=record.consumed_at,
        )

    def is_consumed(
        self,
        capability: AdmissibilityCapability,
        *,
        tenant_id: str | None = None,
    ) -> bool:
        """Return True if *capability* was already atomically consumed."""

        store = self.consumption_store
        assert store is not None
        return store.is_consumed(
            capability.capability_id,
            tenant_id=tenant_id or capability.tenant_id,
            capability_digest=capability.authorization.digest,
        )

    # -- internals ----------------------------------------------------------

    def _compose_terminal(
        self,
        security_block: TransactionVerdictOutcome | None,
        compliance_block: TransactionVerdictOutcome | None,
        outcome_override: TransactionVerdictOutcome | str | None,
        reason_codes: list[str],
        reasons: list[str],
    ) -> TransactionVerdictOutcome:
        if outcome_override is not None:
            if isinstance(outcome_override, bool):
                raise GuardForbiddenSurfaceError(
                    "bare boolean outcomes are forbidden; use TransactionVerdictOutcome"
                )
            if isinstance(outcome_override, str):
                try:
                    outcome_override = TransactionVerdictOutcome(outcome_override)
                except ValueError as exc:
                    raise GuardPolicyError(
                        f"unsupported outcome_override: {outcome_override!r}"
                    ) from exc
            if not isinstance(outcome_override, TransactionVerdictOutcome):
                raise GuardPolicyError(
                    "outcome_override must be a TransactionVerdictOutcome"
                )
            # Override still cannot ignore hard denies from composition when
            # it claims ALLOW; fail closed.
            if outcome_override is TransactionVerdictOutcome.ALLOW:
                for block in (security_block, compliance_block):
                    if block is not None:
                        reason_codes.append("preflight.override_blocked")
                        reasons.append(
                            "ALLOW override rejected because a requirement blocked"
                        )
                        return block
            return outcome_override

        for block in (security_block, compliance_block):
            if block is not None:
                # Prefer DENY over other blockers when both present.
                pass
        if security_block is TransactionVerdictOutcome.DENY or (
            compliance_block is TransactionVerdictOutcome.DENY
        ):
            return TransactionVerdictOutcome.DENY
        if security_block is TransactionVerdictOutcome.ERROR or (
            compliance_block is TransactionVerdictOutcome.ERROR
        ):
            return TransactionVerdictOutcome.ERROR
        if security_block is TransactionVerdictOutcome.STALE or (
            compliance_block is TransactionVerdictOutcome.STALE
        ):
            return TransactionVerdictOutcome.STALE
        if security_block is TransactionVerdictOutcome.REVIEW or (
            compliance_block is TransactionVerdictOutcome.REVIEW
        ):
            return TransactionVerdictOutcome.REVIEW
        if security_block is TransactionVerdictOutcome.INCONCLUSIVE or (
            compliance_block is TransactionVerdictOutcome.INCONCLUSIVE
        ):
            return TransactionVerdictOutcome.INCONCLUSIVE
        if security_block is not None:
            return security_block
        if compliance_block is not None:
            return compliance_block
        return TransactionVerdictOutcome.ALLOW

    def _build_allow_receipt(
        self,
        request: TransactionPreflightRequest,
        *,
        reason_codes: Sequence[str],
        reasons: Sequence[str],
    ) -> DecisionReceipt:
        roots = request.roots or _default_roots(request.policy_id)
        context = _build_bound_context(request)
        receipt_id = "receipt:" + stable_digest(
            {
                "request": request.request_digest,
                "producer": self.producer_id,
            }
        )[:32]
        return build_decision_receipt(
            receipt_id=receipt_id,
            context=context,
            roots=roots,
            outcome=InternalDecisionStatus.ALLOW,
            reasons=tuple(reasons) or ("preflight allow",),
            reason_codes=tuple(reason_codes) or ("preflight.allow",),
            obligation_ids=tuple(
                sorted(
                    set(request.security_requirement_ids)
                    | set(request.compliance_requirement_ids)
                )
            ),
            profile_id=request.profile_id,
            issued_at=request.issued_at,
            deadline=request.deadline,
            expiry=request.expiry,
            producer_id=self.producer_id,
            policy_digest=stable_digest({"policy_id": request.policy_id}),
            metadata={
                "network": request.intent.network,
                "intent_id": request.intent.intent_id,
                "candidate_id": request.candidate.candidate_id,
                "tenant_id": request.tenant_id,
            },
        )

    def _issue_capability(
        self,
        request: TransactionPreflightRequest,
        receipt: DecisionReceipt,
    ) -> AdmissibilityCapability:
        # Prefer the dedicated sign effect; if only one effect exists overall,
        # derive_capability accepts equality.
        allowed = (DEFAULT_ALLOWED_EFFECT,)
        if DEFAULT_ALLOWED_EFFECT not in receipt.effect_ids:
            # Fall back to a strict subset of receipt effects.
            if len(receipt.effect_ids) > 1:
                allowed = (receipt.effect_ids[0],)
            else:
                allowed = receipt.effect_ids

        capability_id = "cap:" + stable_digest(
            {
                "receipt": receipt.content_digest,
                "request": request.request_digest,
                "audience": request.audience_id,
            }
        )[:32]
        try:
            auth = derive_capability(
                receipt,
                capability_id=capability_id,
                allowed_effects=allowed,
                resource_ids=receipt.context.resource_ids,
                audience_id=request.audience_id,
                issued_at=request.issued_at,
                expiry=request.expiry,
                producer_id=self.producer_id,
                require_strict_subset=True,
            )
        except CapabilityDerivationError as exc:
            raise GuardCapabilityError(
                f"capability derivation failed: {exc}",
                reason_code="guard.capability_derivation",
            ) from exc

        return AdmissibilityCapability(
            capability_id=auth.capability_id,
            request_digest=request.request_digest,
            intent_digest=request.intent_digest,
            candidate_digest=request.candidate_digest,
            network=request.intent.network,
            intent_id=request.intent.intent_id,
            candidate_id=request.candidate.candidate_id,
            tenant_id=request.tenant_id,
            authorization=auth,
            phase=PreflightPhase.PRE_SIGN.value,
        )

    def _blocked(
        self,
        request: TransactionPreflightRequest,
        outcome: TransactionVerdictOutcome,
        *,
        reason_codes: Sequence[str],
        reasons: Sequence[str],
        security_results: Mapping[str, Any],
        compliance_results: Mapping[str, Any],
        receipt: DecisionReceipt | None = None,
    ) -> PreflightResult:
        if not transaction_blocks_automation(outcome):
            # Safety: never return an unblocked non-capability result.
            outcome = TransactionVerdictOutcome.ERROR
        return PreflightResult(
            request_digest=request.request_digest,
            outcome=outcome,
            blocks_automation=True,
            reason_codes=tuple(reason_codes),
            reasons=tuple(reasons),
            receipt_id="" if receipt is None else receipt.receipt_id,
            receipt_digest="" if receipt is None else receipt.digest,
            capability=None,
            security_results=dict(security_results),
            compliance_results=dict(compliance_results),
        )


def evaluate_transaction_preflight(
    request: TransactionPreflightRequest | Mapping[str, Any],
    *,
    security_results: Mapping[str, Any] | None = None,
    compliance_results: Mapping[str, Any] | None = None,
    outcome_override: TransactionVerdictOutcome | str | None = None,
    now: str | None = None,
    preflight: TransactionPreflight | None = None,
) -> PreflightResult:
    """Module-level helper matching the plan surface for preflight evaluation."""

    engine = preflight or TransactionPreflight()
    return engine.evaluate(
        request,
        security_results=security_results,
        compliance_results=compliance_results,
        outcome_override=outcome_override,
        now=now,
    )


__all__ = [
    "DEFAULT_ALLOWED_EFFECT",
    "DEFAULT_PRODUCER_ID",
    "REQUIREMENT_PASS",
    "TRANSACTION_PREFLIGHT_INTERFACE",
    "TRANSACTION_PREFLIGHT_SCHEMA_VERSION",
    "TransactionPreflight",
    "compose_requirement_outcomes",
    "evaluate_transaction_preflight",
]
