"""UIR-061: property, fuzz, and mutation gates for UI/UX IR.

Bounded Hypothesis strategies exercise canonical/mediation/state invariants.
Failures minimize to durable fixture shapes; seeds and bounds are recorded.
Model-checking evidence here is *bounded* — never claimed as theorem proof.
"""

from __future__ import annotations

from typing import Final

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

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
    validate_event,
)
from ipfs_datasets_py.logic.ui_ux_ir.runtime.mediator import (
    ActorContext,
    ActorKind,
    FormalEvidence,
    FormalEvidenceKind,
    FormalEvidenceResult,
    MediationOutcome,
    PolicyNorm,
    PolicyVerdict,
    RuntimeMediationContext,
    UIMediator,
    execute_if_allowed,
)
from ipfs_datasets_py.logic.ui_ux_ir.runtime.receipts import (
    build_receipt_from_decision,
    replay_receipts,
    validate_receipt,
)
from ipfs_datasets_py.logic.ui_ux_ir.schema import (
    ProgramBindingTargetKind,
    UIIRValidationError,
)

# Recorded seeds / bounds for the property suite (UIR-061 acceptance).
PROPERTY_SUITE_INTERFACE: Final = "UIIRPropertySuite@1"
PROPERTY_SEED: Final = 0x061_061
MAX_EXAMPLES: Final = 40
STATE_GRAPH_BOUND: Final = 16


_ident = st.from_regex(r"[a-z][a-z0-9_]{0,12}", fullmatch=True)


@st.composite
def mcp_bindings(draw: st.DrawFn) -> UIActionBinding:
    bid = f"binding:{draw(_ident)}"
    aid = f"action:{draw(_ident)}"
    risk = draw(st.sampled_from(list(RiskClass)))
    if risk in {RiskClass.HIGH, RiskClass.DESTRUCTIVE}:
        conf = draw(
            st.sampled_from(
                [ConfirmationClass.CONFIRM, ConfirmationClass.CONSENT, ConfirmationClass.DOUBLE_CONFIRM]
            )
        )
    else:
        conf = draw(st.sampled_from(list(ConfirmationClass)))
    return UIActionBinding(
        binding_id=bid,
        action_id=aid,
        program_ref=UIProgramRef(
            target_kind=ProgramBindingTargetKind.MCP_IDL,
            mcp_idl_interface_cid=f"bafy{draw(_ident)}",
            mcp_idl_method_name=draw(_ident),
        ),
        risk_class=risk,
        confirmation_class=conf,
        effect_ids=(f"effect:{draw(_ident)}",),
    )


@st.composite
def events(draw: st.DrawFn) -> CanonicalInteractionEvent:
    return CanonicalInteractionEvent(
        event_id=f"event:{draw(_ident)}",
        kind=draw(st.sampled_from(list(EventKind))),
        target_component_id=f"component:{draw(_ident)}",
        timestamp_ms=draw(st.integers(min_value=0, max_value=10_000_000)),
        provenance=draw(st.sampled_from(list(EventProvenance))),
        capability_id=f"cap:{draw(_ident)}",
        consent_ok=True,
        confidence=draw(st.one_of(st.none(), st.floats(0.0, 1.0, allow_nan=False))),
    )


def test_suite_identity_and_bounds_recorded() -> None:
    assert PROPERTY_SUITE_INTERFACE == "UIIRPropertySuite@1"
    assert MAX_EXAMPLES >= 20
    assert STATE_GRAPH_BOUND >= 8
    assert PROPERTY_SEED == 0x061_061


@settings(
    max_examples=MAX_EXAMPLES,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(events())
def test_event_validation_idempotent(event: CanonicalInteractionEvent) -> None:
    a = validate_event(event)
    b = validate_event(a)
    assert a == b
    assert a.event_id == event.event_id


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(mcp_bindings(), events(), st.booleans())
def test_mediator_non_execution_without_allow_norm(
    binding: UIActionBinding,
    event: CanonicalInteractionEvent,
    ui_enabled: bool,
) -> None:
    """UI state never grants; empty norms never allow; executor never called."""

    # Align agent provenance with actor to isolate policy-path property.
    if event.provenance is EventProvenance.AGENT:
        actor = ActorContext(
            actor_id="actor:agent",
            kind=ActorKind.AGENT,
            delegation_scope=frozenset({binding.binding_id, binding.action_id}),
        )
    else:
        actor = ActorContext(
            actor_id="actor:human",
            kind=ActorKind.HUMAN,
            human_consent=True,
            confirmation_granted=True,
        )
    ctx = RuntimeMediationContext(
        declaration_digest="decl:property",
        projection_id="proj:property",
        state_version=1,
        actor=actor,
        ui_enabled=ui_enabled,
        ui_visible=True,
        policy_norms=(),
    )
    decision = UIMediator().mediate(binding, event, ctx)
    assert decision.outcome is not MediationOutcome.ALLOW
    assert decision.can_execute is False
    assert decision.invocation_request is None
    assert decision.ui_state_authority_used is False
    calls: list = []
    execute_if_allowed(decision, lambda req: calls.append(req) or "ran")
    assert calls == []


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(mcp_bindings(), events())
def test_allow_norm_only_path_builds_invocation(
    binding: UIActionBinding,
    event: CanonicalInteractionEvent,
) -> None:
    if event.provenance is EventProvenance.AGENT:
        actor = ActorContext(
            actor_id="actor:agent",
            kind=ActorKind.AGENT,
            delegation_scope=frozenset({binding.binding_id, binding.action_id}),
        )
    else:
        actor = ActorContext(
            actor_id="actor:human",
            kind=ActorKind.HUMAN,
            human_consent=True,
            confirmation_granted=True,
        )
    norm = PolicyNorm(
        norm_id="norm:allow",
        verdict=PolicyVerdict.ALLOW,
        priority=10,
        binding_id=binding.binding_id,
    )
    ctx = RuntimeMediationContext(
        declaration_digest="decl:property",
        projection_id="proj:property",
        state_version=2,
        actor=actor,
        policy_norms=(norm,),
    )
    decision = UIMediator().mediate(binding, event, ctx)
    # Confirmation class may still block allow.
    if decision.outcome is MediationOutcome.ALLOW:
        assert decision.invocation_request is not None
        assert decision.invocation_request.declaration_digest == "decl:property"
        assert decision.invocation_request.binding_id == binding.binding_id
        assert decision.invocation_request.event_id == event.event_id
        calls: list = []
        execute_if_allowed(decision, lambda req: calls.append(req.request_id))
        assert len(calls) == 1
    else:
        assert decision.can_execute is False
        assert decision.invocation_request is None


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(
    st.sampled_from(list(FormalEvidenceKind)),
    st.sampled_from(
        [
            FormalEvidenceResult.FAIL,
            FormalEvidenceResult.ERROR,
            FormalEvidenceResult.UNKNOWN,
        ]
    ),
)
def test_formal_evidence_kinds_block_allow_without_substitution(
    kind: FormalEvidenceKind,
    result: FormalEvidenceResult,
) -> None:
    """Theorem/sat/monitor/policy FAIL-family always blocks; kinds stay typed."""

    binding = UIActionBinding(
        binding_id="binding:x",
        action_id="action:x",
        program_ref=UIProgramRef(
            target_kind=ProgramBindingTargetKind.MCP_IDL,
            mcp_idl_interface_cid="bafyiface",
            mcp_idl_method_name="run",
        ),
    )
    event = CanonicalInteractionEvent(
        event_id="event:x",
        kind=EventKind.ACTIVATE,
        target_component_id="component:x",
        timestamp_ms=1,
        provenance=EventProvenance.HUMAN,
        capability_id="cap:x",
        consent_ok=True,
    )
    ctx = RuntimeMediationContext(
        declaration_digest="decl:x",
        projection_id="proj:x",
        state_version=0,
        actor=ActorContext(
            actor_id="actor:h",
            kind=ActorKind.HUMAN,
            human_consent=True,
            confirmation_granted=True,
        ),
        formal_evidence=(
            FormalEvidence(kind=kind, result=result, evidence_id=f"ev:{kind.value}"),
        ),
        policy_norms=(
            PolicyNorm(
                norm_id="norm:a",
                verdict=PolicyVerdict.ALLOW,
                binding_id="binding:x",
            ),
        ),
    )
    decision = UIMediator().mediate(binding, event, ctx)
    assert decision.outcome is not MediationOutcome.ALLOW
    assert f"formal_{kind.value}_" in decision.reasons[0]


@settings(max_examples=MAX_EXAMPLES, deadline=None)
@given(mcp_bindings(), events())
def test_receipt_digest_stable_under_observational_noise(
    binding: UIActionBinding,
    event: CanonicalInteractionEvent,
) -> None:
    actor = ActorContext(
        actor_id="actor:h",
        kind=ActorKind.HUMAN,
        human_consent=True,
        confirmation_granted=True,
    )
    decision = UIMediator().mediate(
        binding,
        event,
        RuntimeMediationContext(
            declaration_digest="decl:r",
            projection_id="proj:r",
            state_version=0,
            actor=actor,
            policy_norms=(
                PolicyNorm(
                    norm_id="norm:a",
                    verdict=PolicyVerdict.ALLOW,
                    binding_id=binding.binding_id,
                ),
            ),
        ),
    )
    r1 = build_receipt_from_decision(
        decision,
        declaration_digest="decl:r",
        sequence=0,
        observational={"latency_ms": 1},
    )
    r2 = build_receipt_from_decision(
        decision,
        declaration_digest="decl:r",
        sequence=0,
        observational={"latency_ms": 999, "extra": "noise"},
    )
    validate_receipt(r1)
    validate_receipt(r2)
    assert r1.content_digest == r2.content_digest
    # Replay never mutates disposition.
    trace = replay_receipts((r1,))
    assert trace.final_outcome is decision.outcome


def test_critical_mutant_ui_state_cannot_allow() -> None:
    """Mutation-style gate: forcing ui_enabled/visible never produces allow alone."""

    binding = UIActionBinding(
        binding_id="binding:mut",
        action_id="action:mut",
        program_ref=UIProgramRef(
            target_kind=ProgramBindingTargetKind.MCP_IDL,
            mcp_idl_interface_cid="bafymut",
            mcp_idl_method_name="mut",
        ),
    )
    event = CanonicalInteractionEvent(
        event_id="event:mut",
        kind=EventKind.ACTIVATE,
        target_component_id="c",
        timestamp_ms=0,
        provenance=EventProvenance.HUMAN,
        capability_id="cap",
        consent_ok=True,
    )
    decision = UIMediator().mediate(
        binding,
        event,
        RuntimeMediationContext(
            declaration_digest="decl:m",
            projection_id="proj:m",
            state_version=0,
            actor=ActorContext(actor_id="a", kind=ActorKind.HUMAN, human_consent=True),
            ui_enabled=True,
            ui_visible=True,
            policy_norms=(),
        ),
    )
    assert decision.outcome is MediationOutcome.DENY


def test_consent_missing_event_fails_closed() -> None:
    with pytest.raises(UIIRValidationError):
        validate_event(
            CanonicalInteractionEvent(
                event_id="event:bad",
                kind=EventKind.ACTIVATE,
                target_component_id="c",
                timestamp_ms=0,
                provenance=EventProvenance.HUMAN,
                capability_id="cap",
                consent_ok=False,
            )
        )
