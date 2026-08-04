"""UIR-056: immutable receipts, lineage integrity, and side-effect-free replay."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.logic.ui_ux_ir.model.bindings import (
    ConfirmationClass,
    RiskClass,
    UIActionBinding,
    UIProgramRef,
)
from ipfs_datasets_py.logic.ui_ux_ir.runtime.events import (
    CanonicalInteractionEvent,
    EventKind,
    EventProvenance,
)
from ipfs_datasets_py.logic.ui_ux_ir.runtime.mediator import (
    ActorContext,
    ActorKind,
    MediationOutcome,
    PolicyNorm,
    PolicyVerdict,
    RuntimeMediationContext,
    UIMediator,
)
from ipfs_datasets_py.logic.ui_ux_ir.runtime.receipts import (
    FeedbackKind,
    ResultDisposition,
    UI_INTERACTION_RECEIPT_INTERFACE,
    UI_REPLAY_TRACE_INTERFACE,
    assert_replay_no_effects,
    build_receipt_from_decision,
    feedback_for_outcome,
    replay_receipts,
    tamper_receipt,
    validate_receipt,
    validate_receipt_chain,
)
from ipfs_datasets_py.logic.ui_ux_ir.schema import (
    ProgramBindingTargetKind,
    UIIRValidationError,
)


def _binding() -> UIActionBinding:
    return UIActionBinding(
        binding_id="binding:submit",
        action_id="action:submit",
        program_ref=UIProgramRef(
            target_kind=ProgramBindingTargetKind.MCP_IDL,
            mcp_idl_interface_cid="bafyiface",
            mcp_idl_method_name="submit",
        ),
        risk_class=RiskClass.LOW,
        confirmation_class=ConfirmationClass.NONE,
        effect_ids=("effect:invoke",),
    )


def _event(eid: str = "event:1") -> CanonicalInteractionEvent:
    return CanonicalInteractionEvent(
        event_id=eid,
        kind=EventKind.ACTIVATE,
        target_component_id="component:submit",
        timestamp_ms=1,
        provenance=EventProvenance.HUMAN,
        capability_id="cap:pointer",
        consent_ok=True,
    )


def _ctx(norms: tuple[PolicyNorm, ...]) -> RuntimeMediationContext:
    return RuntimeMediationContext(
        declaration_digest="decl:abc",
        projection_id="proj:web",
        state_version=1,
        actor=ActorContext(actor_id="actor:h", kind=ActorKind.HUMAN, human_consent=True),
        policy_norms=norms,
    )


def _decide(outcome_norm: PolicyVerdict) -> object:
    kwargs: dict = {
        "norm_id": f"norm:{outcome_norm.value}",
        "verdict": outcome_norm,
        "priority": 10,
        "binding_id": "binding:submit",
    }
    if outcome_norm is PolicyVerdict.REWRITE:
        kwargs["rewrite_binding_id"] = "binding:rw"
    if outcome_norm is PolicyVerdict.FALLBACK:
        kwargs["fallback_binding_id"] = "binding:fb"
    return UIMediator().mediate(
        _binding(),
        _event(),
        _ctx((PolicyNorm(**kwargs),)),
    )


def _receipt(decision, *, sequence: int = 0, parent: str = ""):
    return build_receipt_from_decision(
        decision,
        declaration_digest="decl:abc",
        projection_id="proj:web",
        state_version=1,
        sequence=sequence,
        parent_receipt_id=parent,
        observational={"latency_ms": 12},
    )


# ---------------------------------------------------------------------------
# Feedback for every outcome
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "verdict,feedback_kind",
    [
        (PolicyVerdict.ALLOW, FeedbackKind.SUCCESS),
        (PolicyVerdict.DENY, FeedbackKind.DENIAL),
        (PolicyVerdict.CONFIRM, FeedbackKind.CONFIRMATION),
        (PolicyVerdict.DEFER, FeedbackKind.DEFER),
        (PolicyVerdict.REWRITE, FeedbackKind.REWRITE),
        (PolicyVerdict.FALLBACK, FeedbackKind.FALLBACK),
        (PolicyVerdict.RATE_LIMIT, FeedbackKind.RATE_LIMIT),
    ],
)
def test_every_outcome_has_user_visible_feedback(
    verdict: PolicyVerdict, feedback_kind: FeedbackKind
) -> None:
    decision = _decide(verdict)
    receipt = _receipt(decision)
    assert receipt.feedback.kind is feedback_kind
    assert receipt.feedback.message_key.startswith("ui.feedback.")
    assert receipt.interface == UI_INTERACTION_RECEIPT_INTERFACE
    validate_receipt(receipt)


def test_feedback_for_error_and_unknown() -> None:
    assert feedback_for_outcome(MediationOutcome.ERROR).kind is FeedbackKind.ERROR
    assert feedback_for_outcome(MediationOutcome.UNKNOWN).kind is FeedbackKind.UNKNOWN


# ---------------------------------------------------------------------------
# Lineage bindings
# ---------------------------------------------------------------------------


def test_allow_receipt_binds_invocation_lineage() -> None:
    decision = _decide(PolicyVerdict.ALLOW)
    receipt = _receipt(decision)
    assert receipt.lineage.decision_id == decision.decision_id
    assert receipt.lineage.invocation_request_id
    assert receipt.lineage.policy_norm_id == "norm:allow"
    assert receipt.lineage.declaration_digest == "decl:abc"
    assert receipt.lineage.projection_id == "proj:web"
    assert receipt.lineage.event_id == "event:1"
    assert receipt.disposition is ResultDisposition.NONE
    # Observational excluded from digest identity
    digest_a = receipt.content_digest
    other = build_receipt_from_decision(
        decision,
        declaration_digest="decl:abc",
        projection_id="proj:web",
        state_version=1,
        sequence=0,
        observational={"latency_ms": 9999, "noise": "x"},
    )
    assert other.content_digest == digest_a


def test_rewrite_fallback_captured_in_lineage() -> None:
    rw = _receipt(_decide(PolicyVerdict.REWRITE))
    assert rw.lineage.rewrite_binding_id == "binding:rw"
    fb = _receipt(_decide(PolicyVerdict.FALLBACK))
    assert fb.lineage.fallback_binding_id == "binding:fb"


# ---------------------------------------------------------------------------
# Chain integrity: tamper, missing parent, reorder, identity mismatch
# ---------------------------------------------------------------------------


def test_receipt_chain_integrity() -> None:
    d1 = _decide(PolicyVerdict.CONFIRM)
    d2 = _decide(PolicyVerdict.ALLOW)
    r1 = _receipt(d1, sequence=0)
    r2 = _receipt(d2, sequence=1, parent=r1.receipt_id)
    chain = validate_receipt_chain((r1, r2), expected_declaration_digest="decl:abc")
    assert len(chain) == 2


def test_tamper_detected() -> None:
    r = _receipt(_decide(PolicyVerdict.ALLOW))
    bad = tamper_receipt(r, mutate_outcome=MediationOutcome.DENY)
    with pytest.raises(UIIRValidationError, match="tamper|mismatch"):
        validate_receipt(bad)

    bad_digest = tamper_receipt(r, mutate_digest="sha256:deadbeef")
    with pytest.raises(UIIRValidationError, match="tamper|mismatch"):
        validate_receipt(bad_digest)


def test_missing_parent_fails() -> None:
    d1 = _decide(PolicyVerdict.DENY)
    d2 = _decide(PolicyVerdict.ALLOW)
    r1 = _receipt(d1, sequence=0)
    r2 = _receipt(d2, sequence=1, parent="")  # missing parent
    with pytest.raises(UIIRValidationError, match="missing parent"):
        validate_receipt_chain((r1, r2))


def test_wrong_parent_fails() -> None:
    d1 = _decide(PolicyVerdict.DENY)
    d2 = _decide(PolicyVerdict.ALLOW)
    r1 = _receipt(d1, sequence=0)
    r2 = _receipt(d2, sequence=1, parent="rcpt-not-real")
    with pytest.raises(UIIRValidationError, match="does not match previous"):
        validate_receipt_chain((r1, r2))


def test_reorder_detected() -> None:
    d1 = _decide(PolicyVerdict.CONFIRM)
    d2 = _decide(PolicyVerdict.ALLOW)
    r1 = _receipt(d1, sequence=0)
    r2 = _receipt(d2, sequence=1, parent=r1.receipt_id)
    # Swap order but keep sequence numbers wrong relative to index.
    with pytest.raises(UIIRValidationError, match="reorder"):
        validate_receipt_chain((r2, r1))


def test_declaration_identity_mismatch() -> None:
    d1 = _decide(PolicyVerdict.ALLOW)
    r1 = _receipt(d1, sequence=0)
    with pytest.raises(UIIRValidationError, match="declaration_digest mismatch"):
        validate_receipt_chain((r1,), expected_declaration_digest="decl:other")


def test_first_receipt_must_not_have_parent() -> None:
    d1 = _decide(PolicyVerdict.ALLOW)
    r1 = _receipt(d1, sequence=0, parent="rcpt-ghost")
    with pytest.raises(UIIRValidationError, match="must not have a parent"):
        validate_receipt_chain((r1,))


def test_empty_chain_fails() -> None:
    with pytest.raises(UIIRValidationError, match="must not be empty"):
        validate_receipt_chain(())


# ---------------------------------------------------------------------------
# Deterministic replay — no executor / no effects
# ---------------------------------------------------------------------------


def test_deterministic_replay_no_effects() -> None:
    d1 = _decide(PolicyVerdict.CONFIRM)
    d2 = _decide(PolicyVerdict.ALLOW)
    r1 = _receipt(d1, sequence=0)
    r2 = _receipt(d2, sequence=1, parent=r1.receipt_id)

    spy: list = []
    trace = assert_replay_no_effects((r1, r2), executor_spy=spy)
    assert spy == []
    assert trace.terminated is True
    assert trace.final_outcome is MediationOutcome.ALLOW
    assert trace.interface == UI_REPLAY_TRACE_INTERFACE
    assert len(trace.receipts) == 2
    assert trace.reason == "replay_ok_no_effects"

    # Same inputs → same trace id
    trace2 = replay_receipts((r1, r2))
    assert trace2.trace_id == trace.trace_id


def test_replay_reproduces_decision_dispositions() -> None:
    outcomes = [
        PolicyVerdict.DENY,
        PolicyVerdict.CONFIRM,
        PolicyVerdict.ALLOW,
    ]
    receipts = []
    parent = ""
    for i, v in enumerate(outcomes):
        d = _decide(v)
        r = _receipt(d, sequence=i, parent=parent)
        receipts.append(r)
        parent = r.receipt_id
    trace = replay_receipts(receipts)
    assert [r.outcome for r in trace.receipts] == [
        MediationOutcome.DENY,
        MediationOutcome.CONFIRM,
        MediationOutcome.ALLOW,
    ]
    assert trace.final_outcome is MediationOutcome.ALLOW


def test_denial_receipt_has_no_invocation_lineage() -> None:
    d = _decide(PolicyVerdict.DENY)
    r = _receipt(d)
    assert r.lineage.invocation_request_id == ""
    assert r.outcome is MediationOutcome.DENY
    assert r.feedback.kind is FeedbackKind.DENIAL
    validate_receipt(r)


def test_observational_cannot_claim_declaration_digest() -> None:
    d = _decide(PolicyVerdict.ALLOW)
    r = build_receipt_from_decision(
        d,
        declaration_digest="decl:abc",
        sequence=0,
        observational={"content_digest": "decl:abc"},
    )
    with pytest.raises(UIIRValidationError, match="observational"):
        validate_receipt(r)
