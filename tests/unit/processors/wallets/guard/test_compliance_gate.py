"""Unit tests for the direct-sanctions / bounded-flow compliance gate.

Evidence:

* ``ipfs_datasets_py/processors/wallets/guard/compliance_gate.py``

Acceptance coverage (CRYPTOIR-G520 / CRYPTOIR-028):

* Exact listed matches hard-deny.
* Party and ownership decisions require reviewed evidence.
* Indirect exposure obeys named bounds and policy.
* Stale/incomplete list or graph evidence blocks automation.
* Destination indirection, token/router/proxy changes, bridge legs, fee flows,
  multisend outputs, and UTXO change cannot bypass screening.
* License exceptions are scoped and expiry-bound.
* Screen all economically relevant effects, not only the displayed ``to``.
"""

from __future__ import annotations

from typing import Any

import pytest

from ipfs_datasets_py.logic.crypto_ir.compliance.models import SanctionsPolicyOutcome
from ipfs_datasets_py.logic.crypto_ir.verdicts import (
    SanctionsMatchLevel,
    TransactionVerdictOutcome,
)
from ipfs_datasets_py.processors.wallets.guard.compliance_gate import (
    ComplianceGate,
    ComplianceGateDecision,
    ComplianceGateRequest,
    Counterparty,
    CounterpartyRole,
    CounterpartySet,
    ExposureDecision,
    ExposureVerdict,
    SanctionsDecision,
    evaluate_compliance_gate,
    policy_outcome_to_transaction,
)
from ipfs_datasets_py.processors.wallets.guard.errors import (
    GuardForbiddenSurfaceError,
    GuardPolicyError,
    GuardValidationError,
)
from ipfs_datasets_py.processors.wallets.guard.models import (
    AssetAmount,
    ExpectedEffect,
    FeeSpec,
    TransactionCandidate,
    TransactionIntent,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_DIGEST_A = "a" * 64
_DIGEST_B = "b" * 64
_DIGEST_C = "c" * 64
_DIGEST_BOUNDS = "d" * 64

_ISSUED = "2026-07-28T12:00:00Z"
_EXPIRY = "2026-07-28T12:10:00Z"
_INTENT_EXPIRY = "2026-07-28T12:15:00Z"
_NOW_OK = "2026-07-28T12:02:00Z"
_NOW_EXPIRED = "2026-07-28T12:11:00Z"
_EVIDENCE_EXPIRY = "2026-07-28T12:09:00Z"
_LICENSE_EXPIRY = "2026-07-28T18:00:00Z"
_STALE_EVIDENCE = "2026-07-28T12:01:00Z"

_SNAPSHOT_ID = "snapshot:ofac-sdn-2026-07-28"
_SNAPSHOT_REV = "rev:2026-07-28"
_POLICY_ID = "policy:sanctions-v1"
_POLICY_REV = "1.0.0"
_BOUNDS_POLICY = "policy:exposure-bounds-v1"
_GRAPH_SNAP = "graph:snap-001"
_LIST_REV = "list:rev-001"


def _intent(**overrides: Any) -> TransactionIntent:
    base: dict[str, Any] = {
        "intent_id": "intent:transfer-001",
        "network": "ethereum:mainnet",
        "sender": "0xSender0000000000000000000000000000000001",
        "destination": "0xRecipient000000000000000000000000000002",
        "method": "transfer(address,uint256)",
        "assets": (
            AssetAmount(
                asset_id="asset:usdc",
                amount="1000000",
                asset_namespace="erc20",
                symbol="USDC",
            ),
        ),
        "fees": (
            FeeSpec(
                amount="21000000000000",
                asset_id="asset:eth-native",
                payer="0xFeeRecipient0000000000000000000000003",
            ),
        ),
        "nonce_or_sequence": "7",
        "signers": ("signer:0xSender0000000000000000000000000000000001",),
        "expected_effects": (
            ExpectedEffect(
                effect_id="effect:transfer-usdc",
                kind="transfer",
                summary="transfer USDC to recipient",
            ),
            ExpectedEffect(
                effect_id="effect:fee-gas",
                kind="fee",
                summary="pay gas fee",
            ),
        ),
        "expires_at": _INTENT_EXPIRY,
        "chain_namespace": "eip155",
    }
    base.update(overrides)
    return TransactionIntent(**base)


def _candidate(
    intent: TransactionIntent | None = None, **overrides: Any
) -> TransactionCandidate:
    intent = intent or _intent()
    base: dict[str, Any] = {
        "candidate_id": "candidate:tx-transfer-001",
        "intent_id": intent.intent_id,
        "serialized_digest": _DIGEST_A,
        "encoding": "rlp",
        "byte_length": 180,
        "network": intent.network,
    }
    base.update(overrides)
    return TransactionCandidate(**base)


def _clear_sanctions(party: Counterparty, **overrides: Any) -> SanctionsDecision:
    base: dict[str, Any] = {
        "decision_id": f"sdn:{party.party_id}",
        "party_id": party.party_id,
        "outcome": SanctionsPolicyOutcome.ALLOW,
        "match_level": SanctionsMatchLevel.NO_MATCH,
        "policy_id": _POLICY_ID,
        "policy_revision": _POLICY_REV,
        "snapshot_id": _SNAPSHOT_ID,
        "snapshot_revision": _SNAPSHOT_REV,
        "reason_codes": ("no_match",),
        "reviewed_evidence": False,
        "list_complete": True,
        "freshness_expires_at": _EVIDENCE_EXPIRY,
        "screening_key": party.screening_key,
    }
    base.update(overrides)
    return SanctionsDecision(**base)


def _clear_exposure(party: Counterparty, **overrides: Any) -> ExposureDecision:
    base: dict[str, Any] = {
        "decision_id": f"exp:{party.party_id}",
        "origin_party_id": party.party_id,
        "verdict": ExposureVerdict.CLEAR,
        "policy_id": _BOUNDS_POLICY,
        "policy_revision": "1.0.0",
        "bounds_digest": _DIGEST_BOUNDS,
        "max_depth": 3,
        "graph_snapshot_id": _GRAPH_SNAP,
        "list_revision": _LIST_REV,
        "outcome": SanctionsPolicyOutcome.ALLOW,
        "truncated": False,
        "incomplete_frontier": False,
        "freshness_expires_at": _EVIDENCE_EXPIRY,
        "screening_key": party.screening_key,
        "reason_codes": ("no_path_within_bounds",),
    }
    base.update(overrides)
    return ExposureDecision(**base)


def _counterparties(
    intent: TransactionIntent | None = None,
    candidate: TransactionCandidate | None = None,
    extra: tuple[Counterparty, ...] = (),
) -> CounterpartySet:
    intent = intent or _intent()
    candidate = candidate or _candidate(intent)
    return CounterpartySet.from_intent(
        intent,
        set_id="cps:transfer-001",
        candidate=candidate,
        extra=extra,
    )


def _passing_request(**overrides: Any) -> ComplianceGateRequest:
    intent = overrides.pop("intent", None) or _intent()
    candidate = overrides.pop("candidate", None) or _candidate(intent)
    extra = overrides.pop("extra", ())
    cps = overrides.pop("counterparties", None) or _counterparties(
        intent, candidate, extra=extra
    )
    sanctions = overrides.pop("sanctions_decisions", None)
    if sanctions is None:
        sanctions = tuple(_clear_sanctions(p) for p in cps.counterparties)
    exposure = overrides.pop("exposure_decisions", None)
    if exposure is None:
        exposure = tuple(_clear_exposure(p) for p in cps.counterparties)
    base: dict[str, Any] = {
        "request_id": "req:compliance-001",
        "intent": intent,
        "candidate": candidate,
        "counterparties": cps,
        "sanctions_decisions": sanctions,
        "exposure_decisions": exposure,
        "tenant_id": "tenant:alpha",
        "actor_id": "actor:policy-engine",
        "policy_id": _POLICY_ID,
        "issued_at": _ISSUED,
        "expiry": _EXPIRY,
        "activity_id": "activity:transfer",
        "require_exposure": True,
        "expected_bounds_digest": _DIGEST_BOUNDS,
        "list_snapshot_id": _SNAPSHOT_ID,
        "list_revision": _SNAPSHOT_REV,
    }
    base.update(overrides)
    return ComplianceGateRequest(**base)


# ---------------------------------------------------------------------------
# AST surface
# ---------------------------------------------------------------------------


def test_ast_symbols_exported() -> None:
    """AST query: ComplianceGate CounterpartySet SanctionsDecision ExposureDecision."""

    assert ComplianceGate is not None
    assert CounterpartySet is not None
    assert SanctionsDecision is not None
    assert ExposureDecision is not None
    assert CounterpartyRole is not None
    assert ExposureVerdict is not None


def test_policy_outcome_mapping() -> None:
    assert (
        policy_outcome_to_transaction(SanctionsPolicyOutcome.ALLOW)
        is TransactionVerdictOutcome.ALLOW
    )
    assert (
        policy_outcome_to_transaction(SanctionsPolicyOutcome.DENY)
        is TransactionVerdictOutcome.DENY
    )
    assert (
        policy_outcome_to_transaction(SanctionsPolicyOutcome.STALE)
        is TransactionVerdictOutcome.STALE
    )


# ---------------------------------------------------------------------------
# CounterpartySet — not only displayed `to`
# ---------------------------------------------------------------------------


def test_counterparty_set_includes_sender_recipient_fee_signer() -> None:
    intent = _intent()
    cps = CounterpartySet.from_intent(intent, set_id="cps:1", candidate=_candidate(intent))
    roles = cps.roles
    assert CounterpartyRole.SENDER.value in roles
    assert CounterpartyRole.RECIPIENT.value in roles
    assert CounterpartyRole.CONTRACT.value in roles
    assert CounterpartyRole.FEE_RECIPIENT.value in roles
    assert CounterpartyRole.SIGNER.value in roles
    # Destination is not the only screened party.
    assert len(cps.counterparties) >= 4
    restored = CounterpartySet.from_dict(cps.to_dict())
    assert restored.digest == cps.digest


def test_counterparty_set_round_trip() -> None:
    party = Counterparty(
        party_id="party:bridge-leg-1",
        role=CounterpartyRole.BRIDGE_LEG,
        address="0xBridge000000000000000000000000000000004",
        network="ethereum:mainnet",
        effect_id="effect:bridge-out",
    )
    cps = _counterparties(extra=(party,))
    assert party.screening_key in {c.screening_key for c in cps.counterparties}
    assert CounterpartyRole.BRIDGE_LEG.value in cps.roles


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_all_clear_allows_automation() -> None:
    decision = evaluate_compliance_gate(_passing_request(), now=_NOW_OK)
    assert decision.outcome is TransactionVerdictOutcome.ALLOW
    assert decision.blocks_automation is False
    assert decision.permits_automation()
    assert CounterpartyRole.FEE_RECIPIENT.value in decision.screened_roles
    assert CounterpartyRole.RECIPIENT.value in decision.screened_roles
    restored = ComplianceGateDecision.from_dict(decision.to_dict())
    assert restored.digest == decision.digest


def test_gate_class_evaluate() -> None:
    gate = ComplianceGate()
    decision = gate.evaluate(_passing_request(), now=_NOW_OK)
    assert decision.permits_automation()
    assert decision.counterparty_set_digest == _passing_request().counterparties.digest


# ---------------------------------------------------------------------------
# Exact listed hard-deny
# ---------------------------------------------------------------------------


def test_exact_listed_match_hard_denies() -> None:
    request = _passing_request()
    recipient = next(
        p
        for p in request.counterparties.counterparties
        if p.role is CounterpartyRole.RECIPIENT
    )
    sanctions = []
    for p in request.counterparties.counterparties:
        if p.party_id == recipient.party_id:
            sanctions.append(
                _clear_sanctions(
                    p,
                    outcome=SanctionsPolicyOutcome.DENY,
                    match_level=SanctionsMatchLevel.EXACT_LISTED_IDENTIFIER,
                    reason_codes=("exact_listed_identifier",),
                )
            )
        else:
            sanctions.append(_clear_sanctions(p))
    decision = evaluate_compliance_gate(
        _passing_request(sanctions_decisions=tuple(sanctions)),
        now=_NOW_OK,
    )
    assert decision.outcome is TransactionVerdictOutcome.DENY
    assert decision.blocks_automation
    assert not decision.permits_automation()
    assert any("exact_listed" in v for v in decision.sanctions_results.values())


def test_named_designated_party_hard_denies_when_reviewed() -> None:
    request = _passing_request()
    recipient = next(
        p
        for p in request.counterparties.counterparties
        if p.role is CounterpartyRole.RECIPIENT
    )
    sanctions = tuple(
        _clear_sanctions(
            p,
            outcome=SanctionsPolicyOutcome.DENY,
            match_level=SanctionsMatchLevel.NAMED_DESIGNATED_PARTY,
            reviewed_evidence=True,
            reason_codes=("named_designated_party",),
        )
        if p.party_id == recipient.party_id
        else _clear_sanctions(p)
        for p in request.counterparties.counterparties
    )
    decision = evaluate_compliance_gate(
        _passing_request(sanctions_decisions=sanctions), now=_NOW_OK
    )
    assert decision.outcome is TransactionVerdictOutcome.DENY


# ---------------------------------------------------------------------------
# Party / ownership require reviewed evidence
# ---------------------------------------------------------------------------


def test_owned_entity_without_reviewed_evidence_blocks() -> None:
    request = _passing_request()
    recipient = next(
        p
        for p in request.counterparties.counterparties
        if p.role is CounterpartyRole.RECIPIENT
    )
    sanctions = tuple(
        _clear_sanctions(
            p,
            outcome=SanctionsPolicyOutcome.DENY,
            match_level=SanctionsMatchLevel.OWNED_ENTITY,
            reviewed_evidence=False,
            reason_codes=("owned_entity",),
        )
        if p.party_id == recipient.party_id
        else _clear_sanctions(p)
        for p in request.counterparties.counterparties
    )
    decision = evaluate_compliance_gate(
        _passing_request(sanctions_decisions=sanctions), now=_NOW_OK
    )
    assert decision.blocks_automation
    assert decision.outcome is TransactionVerdictOutcome.INCONCLUSIVE
    assert any(
        v == "unreviewed_party_ownership" for v in decision.sanctions_results.values()
    )


def test_owned_entity_with_reviewed_evidence_denies() -> None:
    request = _passing_request()
    recipient = next(
        p
        for p in request.counterparties.counterparties
        if p.role is CounterpartyRole.RECIPIENT
    )
    sanctions = tuple(
        _clear_sanctions(
            p,
            outcome=SanctionsPolicyOutcome.DENY,
            match_level=SanctionsMatchLevel.OWNED_ENTITY,
            reviewed_evidence=True,
            reason_codes=("owned_entity",),
        )
        if p.party_id == recipient.party_id
        else _clear_sanctions(p)
        for p in request.counterparties.counterparties
    )
    decision = evaluate_compliance_gate(
        _passing_request(sanctions_decisions=sanctions), now=_NOW_OK
    )
    assert decision.outcome is TransactionVerdictOutcome.DENY


# ---------------------------------------------------------------------------
# Indirect exposure obeys named bounds and policy
# ---------------------------------------------------------------------------


def test_indirect_exposure_review_blocks_automation() -> None:
    request = _passing_request()
    sender = next(
        p
        for p in request.counterparties.counterparties
        if p.role is CounterpartyRole.SENDER
    )
    exposure = tuple(
        _clear_exposure(
            p,
            verdict=ExposureVerdict.INDIRECT_EXPOSURE,
            outcome=SanctionsPolicyOutcome.REVIEW,
            path_ids=("path:hop1",),
            reason_codes=("bounded_indirect",),
        )
        if p.party_id == sender.party_id
        else _clear_exposure(p)
        for p in request.counterparties.counterparties
    )
    decision = evaluate_compliance_gate(
        _passing_request(exposure_decisions=exposure), now=_NOW_OK
    )
    assert decision.outcome is TransactionVerdictOutcome.REVIEW
    assert decision.blocks_automation
    assert any(v == "indirect_exposure" for v in decision.exposure_results.values())


def test_indirect_exposure_cannot_map_to_allow() -> None:
    with pytest.raises(GuardPolicyError, match="indirect exposure"):
        ExposureDecision(
            decision_id="exp:bad",
            origin_party_id="party:x",
            verdict=ExposureVerdict.INDIRECT_EXPOSURE,
            policy_id=_BOUNDS_POLICY,
            policy_revision="1.0.0",
            bounds_digest=_DIGEST_BOUNDS,
            max_depth=3,
            graph_snapshot_id=_GRAPH_SNAP,
            list_revision=_LIST_REV,
            outcome=SanctionsPolicyOutcome.ALLOW,
        )


def test_bounds_mismatch_denies() -> None:
    request = _passing_request()
    exposure = tuple(
        _clear_exposure(p, bounds_digest=_DIGEST_C)
        for p in request.counterparties.counterparties
    )
    decision = evaluate_compliance_gate(
        _passing_request(exposure_decisions=exposure), now=_NOW_OK
    )
    assert decision.outcome is TransactionVerdictOutcome.DENY
    assert any(v == "bounds_mismatch" for v in decision.exposure_results.values())


# ---------------------------------------------------------------------------
# Stale / incomplete blocks
# ---------------------------------------------------------------------------


def test_stale_sanctions_list_blocks() -> None:
    request = _passing_request()
    sanctions = tuple(
        _clear_sanctions(p, freshness_expires_at=_STALE_EVIDENCE)
        for p in request.counterparties.counterparties
    )
    decision = evaluate_compliance_gate(
        _passing_request(sanctions_decisions=sanctions), now=_NOW_OK
    )
    assert decision.outcome is TransactionVerdictOutcome.STALE
    assert decision.blocks_automation


def test_incomplete_list_blocks() -> None:
    request = _passing_request()
    sanctions = tuple(
        _clear_sanctions(p, list_complete=False)
        for p in request.counterparties.counterparties
    )
    decision = evaluate_compliance_gate(
        _passing_request(sanctions_decisions=sanctions), now=_NOW_OK
    )
    assert decision.outcome is TransactionVerdictOutcome.INCONCLUSIVE
    assert any(v == "incomplete_list" for v in decision.sanctions_results.values())


def test_truncated_exposure_blocks() -> None:
    request = _passing_request()
    exposure = tuple(
        _clear_exposure(
            p,
            verdict=ExposureVerdict.TRUNCATED,
            truncated=True,
            outcome=SanctionsPolicyOutcome.INCONCLUSIVE,
        )
        for p in request.counterparties.counterparties
    )
    decision = evaluate_compliance_gate(
        _passing_request(exposure_decisions=exposure), now=_NOW_OK
    )
    assert decision.outcome is TransactionVerdictOutcome.INCONCLUSIVE
    assert any(v == "truncated" for v in decision.exposure_results.values())


def test_incomplete_frontier_blocks() -> None:
    request = _passing_request()
    exposure = tuple(
        _clear_exposure(
            p,
            verdict=ExposureVerdict.INCOMPLETE_FRONTIER,
            incomplete_frontier=True,
            outcome=SanctionsPolicyOutcome.INCONCLUSIVE,
        )
        for p in request.counterparties.counterparties
    )
    decision = evaluate_compliance_gate(
        _passing_request(exposure_decisions=exposure), now=_NOW_OK
    )
    assert decision.outcome is TransactionVerdictOutcome.INCONCLUSIVE
    assert any(v == "incomplete_frontier" for v in decision.exposure_results.values())


def test_expired_request_blocks() -> None:
    decision = evaluate_compliance_gate(_passing_request(), now=_NOW_EXPIRED)
    assert decision.outcome is TransactionVerdictOutcome.STALE
    assert decision.blocks_automation


# ---------------------------------------------------------------------------
# Anti-bypass: destination indirection, token/router/proxy, bridge, fee,
# multisend, UTXO change
# ---------------------------------------------------------------------------


def test_missing_fee_recipient_role_cannot_bypass() -> None:
    """Fee effect declared but fee recipient omitted from counterparty set."""

    intent = _intent(
        fees=(FeeSpec(amount="1", asset_id="asset:eth-native"),),  # no payer
        expected_effects=(
            ExpectedEffect(effect_id="effect:transfer", kind="transfer"),
            ExpectedEffect(effect_id="effect:fee", kind="fee"),
        ),
    )
    # Build set without fee_recipient (no fee payer on FeeSpec, no extra).
    parties = [
        Counterparty(
            party_id="party:sender:s",
            role=CounterpartyRole.SENDER,
            address="0xs",
            network=intent.network,
        ),
        Counterparty(
            party_id="party:recipient:r",
            role=CounterpartyRole.RECIPIENT,
            address="0xr",
            network=intent.network,
        ),
    ]
    cps = CounterpartySet(
        set_id="cps:bypass-fee",
        counterparties=tuple(parties),
        intent_id=intent.intent_id,
        network=intent.network,
    )
    sanctions = tuple(_clear_sanctions(p) for p in cps.counterparties)
    exposure = tuple(_clear_exposure(p) for p in cps.counterparties)
    decision = evaluate_compliance_gate(
        ComplianceGateRequest(
            request_id="req:bypass-fee",
            intent=intent,
            candidate=_candidate(intent),
            counterparties=cps,
            sanctions_decisions=sanctions,
            exposure_decisions=exposure,
            tenant_id="tenant:alpha",
            actor_id="actor:policy-engine",
            policy_id=_POLICY_ID,
            issued_at=_ISSUED,
            expiry=_EXPIRY,
            expected_bounds_digest=_DIGEST_BOUNDS,
            list_snapshot_id=_SNAPSHOT_ID,
            list_revision=_SNAPSHOT_REV,
        ),
        now=_NOW_OK,
    )
    assert decision.outcome is TransactionVerdictOutcome.DENY
    assert any("missing_roles" in c for c in decision.reason_codes)


@pytest.mark.parametrize(
    "role,kind",
    [
        (CounterpartyRole.BRIDGE_LEG, "bridge"),
        (CounterpartyRole.MULTISEND_OUTPUT, "multisend"),
        (CounterpartyRole.UTXO_CHANGE, "utxo_change"),
        (CounterpartyRole.SPENDER, "approval"),
        (CounterpartyRole.PROXY, "proxy"),
        (CounterpartyRole.ROUTER, "router"),
        (CounterpartyRole.BENEFICIARY, "destination_indirection"),
    ],
)
def test_effect_kind_requires_role_or_denies(
    role: CounterpartyRole, kind: str
) -> None:
    intent = _intent(
        expected_effects=(
            ExpectedEffect(effect_id=f"effect:{kind}", kind=kind, summary=kind),
        ),
        fees=(FeeSpec(amount="1", asset_id="asset:eth-native"),),
    )
    # Only sender + recipient — missing the role required by *kind*.
    cps = CounterpartySet(
        set_id=f"cps:bypass-{kind}",
        counterparties=(
            Counterparty(
                party_id="party:sender:s",
                role=CounterpartyRole.SENDER,
                address="0xs",
                network=intent.network,
            ),
            Counterparty(
                party_id="party:recipient:r",
                role=CounterpartyRole.RECIPIENT,
                address="0xr",
                network=intent.network,
            ),
        ),
        intent_id=intent.intent_id,
        network=intent.network,
    )
    decision = evaluate_compliance_gate(
        ComplianceGateRequest(
            request_id=f"req:bypass-{kind}",
            intent=intent,
            candidate=_candidate(intent),
            counterparties=cps,
            sanctions_decisions=tuple(_clear_sanctions(p) for p in cps.counterparties),
            exposure_decisions=tuple(_clear_exposure(p) for p in cps.counterparties),
            tenant_id="tenant:alpha",
            actor_id="actor:policy-engine",
            policy_id=_POLICY_ID,
            issued_at=_ISSUED,
            expiry=_EXPIRY,
            expected_bounds_digest=_DIGEST_BOUNDS,
            list_snapshot_id=_SNAPSHOT_ID,
            list_revision=_SNAPSHOT_REV,
        ),
        now=_NOW_OK,
    )
    assert decision.outcome is TransactionVerdictOutcome.DENY
    assert role.value not in cps.roles
    assert any("missing_roles" in c for c in decision.reason_codes)


def test_bridge_leg_screened_when_present() -> None:
    bridge = Counterparty(
        party_id="party:bridge:leg1",
        role=CounterpartyRole.BRIDGE_LEG,
        address="0xBridge000000000000000000000000000000009",
        network="ethereum:mainnet",
        effect_id="effect:bridge-out",
    )
    intent = _intent(
        expected_effects=(
            ExpectedEffect(effect_id="effect:bridge-out", kind="bridge"),
            ExpectedEffect(effect_id="effect:fee", kind="fee"),
        ),
    )
    request = _passing_request(intent=intent, extra=(bridge,))
    decision = evaluate_compliance_gate(request, now=_NOW_OK)
    assert decision.permits_automation()
    assert CounterpartyRole.BRIDGE_LEG.value in decision.screened_roles
    assert any(
        "bridge_leg" in key for key in decision.sanctions_results
    )


def test_token_router_proxy_swap_effects_require_roles() -> None:
    intent = _intent(
        expected_effects=(
            ExpectedEffect(effect_id="effect:swap", kind="swap"),
            ExpectedEffect(effect_id="effect:fee", kind="fee"),
        ),
    )
    # Missing router/token → deny.
    bare = CounterpartySet(
        set_id="cps:swap-bare",
        counterparties=(
            Counterparty(
                party_id="party:sender:s",
                role=CounterpartyRole.SENDER,
                address=intent.sender,
                network=intent.network,
            ),
            Counterparty(
                party_id="party:recipient:r",
                role=CounterpartyRole.RECIPIENT,
                address=intent.destination,
                network=intent.network,
            ),
            Counterparty(
                party_id="party:fee:f",
                role=CounterpartyRole.FEE_RECIPIENT,
                address="0xfee",
                network=intent.network,
            ),
        ),
        intent_id=intent.intent_id,
        network=intent.network,
    )
    decision = evaluate_compliance_gate(
        ComplianceGateRequest(
            request_id="req:swap-bare",
            intent=intent,
            candidate=_candidate(intent),
            counterparties=bare,
            sanctions_decisions=tuple(_clear_sanctions(p) for p in bare.counterparties),
            exposure_decisions=tuple(_clear_exposure(p) for p in bare.counterparties),
            tenant_id="tenant:alpha",
            actor_id="actor:policy-engine",
            policy_id=_POLICY_ID,
            issued_at=_ISSUED,
            expiry=_EXPIRY,
            expected_bounds_digest=_DIGEST_BOUNDS,
            list_snapshot_id=_SNAPSHOT_ID,
            list_revision=_SNAPSHOT_REV,
        ),
        now=_NOW_OK,
    )
    assert decision.outcome is TransactionVerdictOutcome.DENY

    # With router + token present → allow when clear.
    full = CounterpartySet(
        set_id="cps:swap-full",
        counterparties=bare.counterparties
        + (
            Counterparty(
                party_id="party:router:1",
                role=CounterpartyRole.ROUTER,
                address="0xrouter",
                network=intent.network,
            ),
            Counterparty(
                party_id="party:token:1",
                role=CounterpartyRole.TOKEN,
                address="0xtoken",
                network=intent.network,
            ),
        ),
        intent_id=intent.intent_id,
        network=intent.network,
    )
    decision_ok = evaluate_compliance_gate(
        ComplianceGateRequest(
            request_id="req:swap-full",
            intent=intent,
            candidate=_candidate(intent),
            counterparties=full,
            sanctions_decisions=tuple(
                _clear_sanctions(p) for p in full.counterparties
            ),
            exposure_decisions=tuple(
                _clear_exposure(p) for p in full.counterparties
            ),
            tenant_id="tenant:alpha",
            actor_id="actor:policy-engine",
            policy_id=_POLICY_ID,
            issued_at=_ISSUED,
            expiry=_EXPIRY,
            expected_bounds_digest=_DIGEST_BOUNDS,
            list_snapshot_id=_SNAPSHOT_ID,
            list_revision=_SNAPSHOT_REV,
        ),
        now=_NOW_OK,
    )
    assert decision_ok.permits_automation()


def test_missing_sanctions_for_any_party_blocks() -> None:
    request = _passing_request()
    # Drop one sanctions decision.
    sanctions = request.sanctions_decisions[1:]
    decision = evaluate_compliance_gate(
        _passing_request(sanctions_decisions=sanctions), now=_NOW_OK
    )
    assert decision.blocks_automation
    assert decision.outcome is TransactionVerdictOutcome.INCONCLUSIVE
    assert any(v == "missing" for v in decision.sanctions_results.values())


def test_fee_recipient_listed_is_screened_not_only_to() -> None:
    """Sanctions on fee recipient deny even when destination is clear."""

    request = _passing_request()
    fee_party = next(
        p
        for p in request.counterparties.counterparties
        if p.role is CounterpartyRole.FEE_RECIPIENT
    )
    sanctions = tuple(
        _clear_sanctions(
            p,
            outcome=SanctionsPolicyOutcome.DENY,
            match_level=SanctionsMatchLevel.EXACT_LISTED_IDENTIFIER,
        )
        if p.party_id == fee_party.party_id
        else _clear_sanctions(p)
        for p in request.counterparties.counterparties
    )
    decision = evaluate_compliance_gate(
        _passing_request(sanctions_decisions=sanctions), now=_NOW_OK
    )
    assert decision.outcome is TransactionVerdictOutcome.DENY
    # Recipient itself remains clear in results.
    recipient_key = next(
        p.screening_key
        for p in request.counterparties.counterparties
        if p.role is CounterpartyRole.RECIPIENT
    )
    assert decision.sanctions_results[recipient_key] == "clear"


# ---------------------------------------------------------------------------
# License exceptions scoped and expiry-bound
# ---------------------------------------------------------------------------


def test_scoped_active_license_downgrades_exact_deny_to_review() -> None:
    request = _passing_request()
    recipient = next(
        p
        for p in request.counterparties.counterparties
        if p.role is CounterpartyRole.RECIPIENT
    )
    sanctions = tuple(
        _clear_sanctions(
            p,
            outcome=SanctionsPolicyOutcome.DENY,
            match_level=SanctionsMatchLevel.EXACT_LISTED_IDENTIFIER,
            license_ids=("license:ofac-exception-1",),
            license_expires_at=_LICENSE_EXPIRY,
            license_scoped_activity="activity:transfer",
        )
        if p.party_id == recipient.party_id
        else _clear_sanctions(p)
        for p in request.counterparties.counterparties
    )
    decision = evaluate_compliance_gate(
        _passing_request(sanctions_decisions=sanctions), now=_NOW_OK
    )
    assert decision.outcome is TransactionVerdictOutcome.REVIEW
    assert decision.blocks_automation
    assert any(v == "licensed_exception" for v in decision.sanctions_results.values())


def test_expired_license_does_not_override_exact_deny() -> None:
    request = _passing_request()
    recipient = next(
        p
        for p in request.counterparties.counterparties
        if p.role is CounterpartyRole.RECIPIENT
    )
    sanctions = tuple(
        _clear_sanctions(
            p,
            outcome=SanctionsPolicyOutcome.DENY,
            match_level=SanctionsMatchLevel.EXACT_LISTED_IDENTIFIER,
            license_ids=("license:expired",),
            license_expires_at=_STALE_EVIDENCE,
            license_scoped_activity="activity:transfer",
        )
        if p.party_id == recipient.party_id
        else _clear_sanctions(p)
        for p in request.counterparties.counterparties
    )
    decision = evaluate_compliance_gate(
        _passing_request(sanctions_decisions=sanctions), now=_NOW_OK
    )
    assert decision.outcome is TransactionVerdictOutcome.DENY
    assert any(
        v == "expired_or_unscoped_license" for v in decision.sanctions_results.values()
    )


def test_license_wrong_activity_scope_does_not_override() -> None:
    request = _passing_request()
    recipient = next(
        p
        for p in request.counterparties.counterparties
        if p.role is CounterpartyRole.RECIPIENT
    )
    sanctions = tuple(
        _clear_sanctions(
            p,
            outcome=SanctionsPolicyOutcome.DENY,
            match_level=SanctionsMatchLevel.EXACT_LISTED_IDENTIFIER,
            license_ids=("license:other-activity",),
            license_expires_at=_LICENSE_EXPIRY,
            license_scoped_activity="activity:custody-only",
        )
        if p.party_id == recipient.party_id
        else _clear_sanctions(p)
        for p in request.counterparties.counterparties
    )
    decision = evaluate_compliance_gate(
        _passing_request(sanctions_decisions=sanctions), now=_NOW_OK
    )
    assert decision.outcome is TransactionVerdictOutcome.DENY


# ---------------------------------------------------------------------------
# Substitution / revalidation
# ---------------------------------------------------------------------------


def test_snapshot_substitution_denies() -> None:
    request = _passing_request()
    sanctions = tuple(
        _clear_sanctions(p, snapshot_id="snapshot:other")
        for p in request.counterparties.counterparties
    )
    decision = evaluate_compliance_gate(
        _passing_request(sanctions_decisions=sanctions), now=_NOW_OK
    )
    assert decision.outcome is TransactionVerdictOutcome.DENY
    assert any(v == "snapshot_mismatch" for v in decision.sanctions_results.values())


def test_revalidate_detects_candidate_change() -> None:
    gate = ComplianceGate()
    request = _passing_request()
    decision = gate.evaluate(request, now=_NOW_OK)
    assert decision.permits_automation()
    altered = _passing_request(
        candidate=_candidate(request.intent, serialized_digest=_DIGEST_B)
    )
    revalidated = gate.revalidate(decision, altered, now=_NOW_OK)
    assert revalidated.blocks_automation
    assert revalidated.outcome is TransactionVerdictOutcome.STALE
    assert "compliance.revalidate_mismatch" in revalidated.reason_codes


def test_revalidate_same_request_stays_allow() -> None:
    gate = ComplianceGate()
    request = _passing_request()
    decision = gate.evaluate(request, now=_NOW_OK)
    again = gate.revalidate(decision, request, now=_NOW_OK)
    assert again.permits_automation()


# ---------------------------------------------------------------------------
# Forbidden surfaces / validation
# ---------------------------------------------------------------------------


def test_forbidden_approval_fields_rejected() -> None:
    with pytest.raises(GuardForbiddenSurfaceError):
        Counterparty(
            party_id="party:x",
            role=CounterpartyRole.RECIPIENT,
            attributes={"approved": True},
        )


def test_decision_round_trip() -> None:
    decision = evaluate_compliance_gate(_passing_request(), now=_NOW_OK)
    payload = decision.to_dict()
    restored = ComplianceGateDecision.from_dict(payload)
    assert restored.outcome is decision.outcome
    assert restored.digest == decision.digest
    assert restored.screened_party_ids == decision.screened_party_ids


def test_sanctions_decision_round_trip() -> None:
    party = Counterparty(
        party_id="party:x",
        role=CounterpartyRole.RECIPIENT,
        address="0xabc",
    )
    sd = _clear_sanctions(party)
    assert SanctionsDecision.from_dict(sd.to_dict()).decision_id == sd.decision_id


def test_exposure_decision_round_trip() -> None:
    party = Counterparty(
        party_id="party:x",
        role=CounterpartyRole.SENDER,
        address="0xabc",
    )
    ed = _clear_exposure(party)
    assert ExposureDecision.from_dict(ed.to_dict()).decision_id == ed.decision_id


def test_direct_hit_cannot_allow() -> None:
    with pytest.raises(GuardPolicyError, match="direct exposure"):
        ExposureDecision(
            decision_id="exp:direct-bad",
            origin_party_id="party:x",
            verdict=ExposureVerdict.DIRECT_HIT,
            policy_id=_BOUNDS_POLICY,
            policy_revision="1.0.0",
            bounds_digest=_DIGEST_BOUNDS,
            max_depth=1,
            graph_snapshot_id=_GRAPH_SNAP,
            list_revision=_LIST_REV,
            outcome=SanctionsPolicyOutcome.ALLOW,
        )


def test_require_exposure_false_skips_exposure_missing() -> None:
    request = _passing_request(require_exposure=False, exposure_decisions=())
    decision = evaluate_compliance_gate(request, now=_NOW_OK)
    assert decision.permits_automation()
    assert decision.exposure_results == {}
