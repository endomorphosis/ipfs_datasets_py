"""UIR-055: formal-policy mediation and governed invocation requests."""

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
    FormalEvidence,
    FormalEvidenceKind,
    FormalEvidenceResult,
    MediationOutcome,
    PolicyNorm,
    PolicyVerdict,
    RuntimeMediationContext,
    UIMediator,
    UI_MEDIATOR_INTERFACE,
    context_from_snapshot,
    create_mediator,
    execute_if_allowed,
)
from ipfs_datasets_py.logic.ui_ux_ir.runtime.state_machine import (
    EffectKind,
    RuntimeSnapshot,
    StagedEffect,
    UXPhase,
)
from ipfs_datasets_py.logic.ui_ux_ir.schema import (
    ProgramBindingTargetKind,
    UIIRValidationError,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _mcp_binding(
    *,
    binding_id: str = "binding:submit",
    action_id: str = "action:submit",
    risk: RiskClass = RiskClass.LOW,
    confirmation: ConfirmationClass = ConfirmationClass.NONE,
    effect_ids: tuple[str, ...] = ("effect:invoke_submit",),
) -> UIActionBinding:
    return UIActionBinding(
        binding_id=binding_id,
        action_id=action_id,
        program_ref=UIProgramRef(
            target_kind=ProgramBindingTargetKind.MCP_IDL,
            mcp_idl_interface_cid="bafyinterface0001",
            mcp_idl_method_name="submit",
            mcp_idl_argument_schema_ref="schema:args",
            mcp_idl_result_schema_ref="schema:result",
        ),
        risk_class=risk,
        confirmation_class=confirmation,
        effect_ids=effect_ids,
    )


def _event(
    *,
    event_id: str = "event:1",
    provenance: EventProvenance = EventProvenance.HUMAN,
    consent_ok: bool = True,
) -> CanonicalInteractionEvent:
    return CanonicalInteractionEvent(
        event_id=event_id,
        kind=EventKind.ACTIVATE,
        target_component_id="component:submit",
        timestamp_ms=1_000,
        provenance=provenance,
        capability_id="cap:pointer",
        consent_ok=consent_ok,
    )


def _human(
    *,
    consent: bool = True,
    confirmation: bool = False,
    actor_id: str = "actor:human-1",
) -> ActorContext:
    return ActorContext(
        actor_id=actor_id,
        kind=ActorKind.HUMAN,
        human_consent=consent,
        confirmation_granted=confirmation,
    )


def _agent(
    *,
    scope: frozenset[str] | None = None,
    actor_id: str = "actor:agent-1",
) -> ActorContext:
    return ActorContext(
        actor_id=actor_id,
        kind=ActorKind.AGENT,
        delegation_scope=scope
        if scope is not None
        else frozenset({"binding:submit", "action:submit"}),
    )


def _context(
    *,
    actor: ActorContext | None = None,
    norms: tuple[PolicyNorm, ...] = (),
    evidence: tuple[FormalEvidence, ...] = (),
    ui_enabled: bool = True,
    ui_visible: bool = True,
    rate_limit_remaining: int | None = None,
    staged_effects: tuple[StagedEffect, ...] = (),
    state_version: int = 3,
) -> RuntimeMediationContext:
    return RuntimeMediationContext(
        declaration_digest="decl:deadbeef",
        projection_id="proj:web-1",
        state_version=state_version,
        active_state_ids=frozenset({"pending"}),
        actor=actor if actor is not None else _human(),
        ui_enabled=ui_enabled,
        ui_visible=ui_visible,
        ui_phase="pending",
        rate_limit_remaining=rate_limit_remaining,
        formal_evidence=evidence,
        policy_norms=norms,
        staged_effects=staged_effects,
    )


def _allow_norm(**kwargs: object) -> PolicyNorm:
    return PolicyNorm(
        norm_id=str(kwargs.get("norm_id", "norm:allow")),
        verdict=PolicyVerdict.ALLOW,
        priority=int(kwargs.get("priority", 10)),
        binding_id=str(kwargs.get("binding_id", "binding:submit")),
        reason=str(kwargs.get("reason", "default allow")),
    )


# ---------------------------------------------------------------------------
# Interface & factory
# ---------------------------------------------------------------------------


def test_interface_identity() -> None:
    assert UI_MEDIATOR_INTERFACE == "UIMediator@1"
    m = create_mediator()
    assert isinstance(m, UIMediator)


# ---------------------------------------------------------------------------
# All-outcome matrix with executor spy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "verdict,expected",
    [
        (PolicyVerdict.ALLOW, MediationOutcome.ALLOW),
        (PolicyVerdict.DENY, MediationOutcome.DENY),
        (PolicyVerdict.CONFIRM, MediationOutcome.CONFIRM),
        (PolicyVerdict.DEFER, MediationOutcome.DEFER),
        (PolicyVerdict.REWRITE, MediationOutcome.REWRITE),
        (PolicyVerdict.FALLBACK, MediationOutcome.FALLBACK),
        (PolicyVerdict.RATE_LIMIT, MediationOutcome.RATE_LIMIT),
    ],
)
def test_all_outcomes_executor_spy(
    verdict: PolicyVerdict, expected: MediationOutcome
) -> None:
    kwargs: dict = {
        "norm_id": f"norm:{verdict.value}",
        "verdict": verdict,
        "priority": 50,
        "binding_id": "binding:submit",
    }
    if verdict is PolicyVerdict.REWRITE:
        kwargs["rewrite_binding_id"] = "binding:safe-alt"
    if verdict is PolicyVerdict.FALLBACK:
        kwargs["fallback_binding_id"] = "binding:fallback"
    norm = PolicyNorm(**kwargs)
    mediator = UIMediator()
    decision = mediator.mediate(
        _mcp_binding(),
        _event(),
        _context(norms=(norm,)),
    )
    assert decision.outcome is expected
    if expected is MediationOutcome.ALLOW:
        assert decision.can_execute is True
        assert decision.invocation_request is not None
    else:
        assert decision.can_execute is False
        assert decision.invocation_request is None

    calls: list = []

    def spy(req):  # type: ignore[no-untyped-def]
        calls.append(req)
        return {"ok": True}

    result = execute_if_allowed(decision, spy)
    if expected is MediationOutcome.ALLOW:
        assert result == {"ok": True}
        assert len(calls) == 1
        assert calls[0].binding_id == "binding:submit"
    else:
        assert result is None
        assert calls == []


def test_rewrite_and_fallback_are_explicit() -> None:
    mediator = UIMediator()
    rewrite = mediator.mediate(
        _mcp_binding(),
        _event(),
        _context(
            norms=(
                PolicyNorm(
                    norm_id="norm:rw",
                    verdict=PolicyVerdict.REWRITE,
                    rewrite_binding_id="binding:rewritten",
                    binding_id="binding:submit",
                ),
            )
        ),
    )
    assert rewrite.outcome is MediationOutcome.REWRITE
    assert rewrite.rewrite_binding_id == "binding:rewritten"
    assert rewrite.fallback_binding_id == ""

    fallback = mediator.mediate(
        _mcp_binding(),
        _event(),
        _context(
            norms=(
                PolicyNorm(
                    norm_id="norm:fb",
                    verdict=PolicyVerdict.FALLBACK,
                    fallback_binding_id="binding:fallback",
                    binding_id="binding:submit",
                ),
            )
        ),
    )
    assert fallback.outcome is MediationOutcome.FALLBACK
    assert fallback.fallback_binding_id == "binding:fallback"


# ---------------------------------------------------------------------------
# Fail closed: missing policy, unknown, error
# ---------------------------------------------------------------------------


def test_missing_policy_norm_fails_closed() -> None:
    decision = UIMediator().mediate(_mcp_binding(), _event(), _context(norms=()))
    assert decision.outcome is MediationOutcome.DENY
    assert decision.can_execute is False
    assert decision.invocation_request is None
    assert "no_matching_policy_norm" in decision.reasons
    assert execute_if_allowed(decision, lambda r: "boom") is None


def test_formal_fail_denies_even_with_allow_norm() -> None:
    decision = UIMediator().mediate(
        _mcp_binding(),
        _event(),
        _context(
            norms=(_allow_norm(),),
            evidence=(
                FormalEvidence(
                    kind=FormalEvidenceKind.THEOREM,
                    result=FormalEvidenceResult.FAIL,
                    evidence_id="thm:safety",
                    detail="obligation violated",
                ),
            ),
        ),
    )
    assert decision.outcome is MediationOutcome.DENY
    assert "formal_theorem_fail" in decision.reasons
    assert decision.can_execute is False


def test_formal_unknown_and_error_never_execute() -> None:
    m = UIMediator()
    unknown = m.mediate(
        _mcp_binding(),
        _event(),
        _context(
            norms=(_allow_norm(),),
            evidence=(
                FormalEvidence(
                    kind=FormalEvidenceKind.SATISFIABILITY,
                    result=FormalEvidenceResult.UNKNOWN,
                    evidence_id="sat:1",
                ),
            ),
        ),
    )
    assert unknown.outcome is MediationOutcome.UNKNOWN
    assert unknown.can_execute is False

    error = m.mediate(
        _mcp_binding(),
        _event(),
        _context(
            norms=(_allow_norm(),),
            evidence=(
                FormalEvidence(
                    kind=FormalEvidenceKind.MONITOR,
                    result=FormalEvidenceResult.ERROR,
                    evidence_id="mon:1",
                ),
            ),
        ),
    )
    assert error.outcome is MediationOutcome.ERROR
    assert error.can_execute is False
    assert execute_if_allowed(error, lambda r: "nope") is None


def test_evidence_kinds_not_substituted() -> None:
    """Theorem PASS does not satisfy require_policy_evidence."""

    decision = UIMediator(require_policy_evidence=True).mediate(
        _mcp_binding(),
        _event(),
        _context(
            norms=(_allow_norm(),),
            evidence=(
                FormalEvidence(
                    kind=FormalEvidenceKind.THEOREM,
                    result=FormalEvidenceResult.PASS,
                    evidence_id="thm:ok",
                ),
            ),
        ),
    )
    assert decision.outcome is MediationOutcome.DENY
    assert "missing_policy_evidence_pass" in decision.reasons

    ok = UIMediator(require_policy_evidence=True).mediate(
        _mcp_binding(),
        _event(),
        _context(
            norms=(_allow_norm(),),
            evidence=(
                FormalEvidence(
                    kind=FormalEvidenceKind.POLICY,
                    result=FormalEvidenceResult.PASS,
                    evidence_id="pol:ok",
                ),
            ),
        ),
    )
    assert ok.outcome is MediationOutcome.ALLOW


# ---------------------------------------------------------------------------
# Authority non-substitution: UI state never grants
# ---------------------------------------------------------------------------


def test_ui_enabled_does_not_grant_permission() -> None:
    """ui_enabled/ui_visible true still deny without policy."""

    decision = UIMediator().mediate(
        _mcp_binding(),
        _event(),
        _context(norms=(), ui_enabled=True, ui_visible=True),
    )
    assert decision.outcome is MediationOutcome.DENY
    assert decision.ui_state_authority_used is False

    # Even with allow norm, disabled UI does not change allow (observational only).
    allowed = UIMediator().mediate(
        _mcp_binding(),
        _event(),
        _context(norms=(_allow_norm(),), ui_enabled=False, ui_visible=False),
    )
    assert allowed.outcome is MediationOutcome.ALLOW
    assert allowed.ui_state_authority_used is False


def test_decision_rejects_ui_state_authority_flag() -> None:
    from ipfs_datasets_py.logic.ui_ux_ir.runtime.mediator import UIMediationDecision

    with pytest.raises(UIIRValidationError, match="UI state must never"):
        UIMediationDecision(
            decision_id="d1",
            outcome=MediationOutcome.DENY,
            binding_id="binding:submit",
            action_id="action:submit",
            event_id="event:1",
            reasons=("x",),
            can_execute=False,
            ui_state_authority_used=True,
        )


# ---------------------------------------------------------------------------
# Delegation and human consent exactness
# ---------------------------------------------------------------------------


def test_agent_delegation_exact_match() -> None:
    m = UIMediator()
    denied = m.mediate(
        _mcp_binding(),
        _event(provenance=EventProvenance.AGENT),
        _context(
            actor=_agent(scope=frozenset({"binding:other"})),
            norms=(_allow_norm(),),
        ),
    )
    assert denied.outcome is MediationOutcome.DENY
    assert "agent_delegation_mismatch" in denied.reasons

    allowed = m.mediate(
        _mcp_binding(),
        _event(provenance=EventProvenance.AGENT),
        _context(
            actor=_agent(scope=frozenset({"binding:submit"})),
            norms=(_allow_norm(),),
        ),
    )
    assert allowed.outcome is MediationOutcome.ALLOW
    assert allowed.invocation_request is not None
    assert allowed.invocation_request.actor_id == "actor:agent-1"


def test_agent_event_with_human_actor_denied() -> None:
    decision = UIMediator().mediate(
        _mcp_binding(),
        _event(provenance=EventProvenance.AGENT),
        _context(actor=_human(), norms=(_allow_norm(),)),
    )
    assert decision.outcome is MediationOutcome.DENY
    assert "agent_event_without_agent_actor" in decision.reasons


def test_human_consent_and_confirmation_exact() -> None:
    m = UIMediator()
    destructive = _mcp_binding(
        risk=RiskClass.DESTRUCTIVE,
        confirmation=ConfirmationClass.CONSENT,
    )
    no_consent = m.mediate(
        destructive,
        _event(),
        _context(
            actor=_human(consent=False, confirmation=False),
            norms=(_allow_norm(),),
        ),
    )
    assert no_consent.outcome is MediationOutcome.CONFIRM
    assert "human_consent_required" in no_consent.reasons
    assert no_consent.can_execute is False

    with_consent = m.mediate(
        destructive,
        _event(),
        _context(
            actor=_human(consent=True, confirmation=False),
            norms=(_allow_norm(),),
        ),
    )
    # CONSENT class satisfied by human_consent; no extra confirmation_granted.
    assert with_consent.outcome is MediationOutcome.ALLOW

    confirm_binding = _mcp_binding(
        risk=RiskClass.HIGH,
        confirmation=ConfirmationClass.CONFIRM,
    )
    needs_confirm = m.mediate(
        confirm_binding,
        _event(),
        _context(
            actor=_human(consent=True, confirmation=False),
            norms=(_allow_norm(),),
        ),
    )
    assert needs_confirm.outcome is MediationOutcome.CONFIRM
    assert "confirmation_required" in needs_confirm.reasons

    confirmed = m.mediate(
        confirm_binding,
        _event(),
        _context(
            actor=_human(consent=True, confirmation=True),
            norms=(_allow_norm(),),
        ),
    )
    assert confirmed.outcome is MediationOutcome.ALLOW


# ---------------------------------------------------------------------------
# Invocation request bindings
# ---------------------------------------------------------------------------


def test_invocation_request_binds_all_required_identities() -> None:
    decision = UIMediator().mediate(
        _mcp_binding(effect_ids=("effect:a", "effect:b")),
        _event(event_id="event:42"),
        _context(
            actor=_human(actor_id="actor:h"),
            norms=(_allow_norm(norm_id="norm:primary"),),
            state_version=7,
        ),
    )
    assert decision.outcome is MediationOutcome.ALLOW
    req = decision.invocation_request
    assert req is not None
    assert req.declaration_digest == "decl:deadbeef"
    assert req.projection_id == "proj:web-1"
    assert req.state_version == 7
    assert req.event_id == "event:42"
    assert req.actor_id == "actor:h"
    assert req.policy_norm_id == "norm:primary"
    assert req.mcp_idl_interface_cid == "bafyinterface0001"
    assert req.mcp_idl_method_name == "submit"
    assert req.program_target_kind == ProgramBindingTargetKind.MCP_IDL.value
    assert "mcp:bafyinterface0001#submit" in req.program_target_ref
    assert req.expected_effect_ids == ("effect:a", "effect:b")
    payload = req.to_dict()
    assert payload["interface"] == "UIInvocationRequest@1"
    assert "grant" not in payload
    assert "ucan" not in payload


def test_local_state_binding_never_builds_invocation() -> None:
    binding = UIActionBinding(
        binding_id="binding:local",
        action_id="action:local",
        program_ref=UIProgramRef(
            target_kind=ProgramBindingTargetKind.LOCAL_STATE,
            local_state_transition="t_focus",
        ),
    )
    decision = UIMediator().mediate(
        binding,
        _event(),
        _context(
            norms=(
                PolicyNorm(
                    norm_id="norm:local",
                    verdict=PolicyVerdict.ALLOW,
                    binding_id="binding:local",
                ),
            )
        ),
    )
    assert decision.outcome is MediationOutcome.DENY
    assert "local_state_only_no_external_invocation" in decision.reasons


def test_rate_limit_exhausted() -> None:
    decision = UIMediator().mediate(
        _mcp_binding(),
        _event(),
        _context(norms=(_allow_norm(),), rate_limit_remaining=0),
    )
    assert decision.outcome is MediationOutcome.RATE_LIMIT
    assert decision.can_execute is False


def test_deny_over_permit_on_equal_priority() -> None:
    decision = UIMediator().mediate(
        _mcp_binding(),
        _event(),
        _context(
            norms=(
                PolicyNorm(
                    norm_id="norm:a",
                    verdict=PolicyVerdict.ALLOW,
                    priority=10,
                    binding_id="binding:submit",
                ),
                PolicyNorm(
                    norm_id="norm:d",
                    verdict=PolicyVerdict.DENY,
                    priority=10,
                    binding_id="binding:submit",
                    reason="deny wins",
                ),
            )
        ),
    )
    assert decision.outcome is MediationOutcome.DENY
    assert decision.selected_policy_norm_id == "norm:d"


def test_external_effect_already_executed_errors() -> None:
    # Constructing StagedEffect with executed=True for EXTERNAL raises at build.
    with pytest.raises(UIIRValidationError, match="must remain staged"):
        StagedEffect(
            effect_id="effect:invoke_submit",
            kind=EffectKind.EXTERNAL_REQUEST,
            binding_ref="binding:submit",
            executed=True,
        )


def test_evaluate_staged_effect_happy_path() -> None:
    effect = StagedEffect(
        effect_id="effect:invoke_submit",
        kind=EffectKind.EXTERNAL_REQUEST,
        binding_ref="binding:submit",
        executed=False,
    )
    decision = UIMediator().evaluate_staged_effect(
        _mcp_binding(),
        _event(),
        _context(norms=(_allow_norm(),)),
        effect,
    )
    assert decision.outcome is MediationOutcome.ALLOW


def test_context_from_snapshot_ui_observational() -> None:
    snap = RuntimeSnapshot(
        active_state_ids=frozenset({"confirming"}),
        state_version=2,
        latest_timestamp_ms=10,
        phase=UXPhase.CONFIRMING,
        pending_confirmation=True,
    )
    ctx = context_from_snapshot(
        snap,
        declaration_digest="decl:x",
        projection_id="proj:y",
        actor=_human(),
        policy_norms=(_allow_norm(),),
    )
    assert ctx.state_version == 2
    assert ctx.ui_phase == "confirming"
    decision = UIMediator().mediate(_mcp_binding(), _event(), ctx)
    assert decision.outcome is MediationOutcome.ALLOW


def test_missing_actor_denies() -> None:
    ctx = RuntimeMediationContext(
        declaration_digest="decl:x",
        projection_id="proj:y",
        state_version=0,
        actor=None,
        policy_norms=(_allow_norm(),),
    )
    decision = UIMediator().mediate(_mcp_binding(), _event(), ctx)
    assert decision.outcome is MediationOutcome.DENY
    assert "missing_actor" in decision.reasons


def test_policy_norm_rewrite_requires_target() -> None:
    with pytest.raises(UIIRValidationError, match="rewrite_binding_id"):
        PolicyNorm(
            norm_id="norm:bad",
            verdict=PolicyVerdict.REWRITE,
        ).validate()


def test_allow_decision_serialization_and_interface() -> None:
    decision = UIMediator().mediate(
        _mcp_binding(),
        _event(),
        _context(norms=(_allow_norm(),)),
    )
    payload = decision.to_dict()
    assert payload["interface"] == "UIMediationDecision@1"
    assert payload["outcome"] == "allow"
    assert payload["can_execute"] is True
    assert payload["invocation_request"]["mcp_idl_method_name"] == "submit"
