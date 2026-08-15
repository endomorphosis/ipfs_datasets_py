"""UIR-072: destructive confirmation, rollback, recovery pilot."""

from __future__ import annotations

import json
from pathlib import Path

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
    execute_if_allowed,
)
from ipfs_datasets_py.logic.ui_ux_ir.schema import ProgramBindingTargetKind

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "ui_ux_ir"
    / "pilots"
    / "destructive_workflow.json"
)


def _binding() -> UIActionBinding:
    pilot = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return UIActionBinding(
        binding_id=pilot["binding_id"],
        action_id=pilot["action_id"],
        program_ref=UIProgramRef(
            target_kind=ProgramBindingTargetKind.MCP_IDL,
            mcp_idl_interface_cid="bafydelete",
            mcp_idl_method_name="delete_dataset",
        ),
        risk_class=RiskClass.DESTRUCTIVE,
        confirmation_class=ConfirmationClass.CONFIRM,
        effect_ids=("effect:delete",),
    )


def test_no_invocation_before_explicit_confirmation() -> None:
    binding = _binding()
    event = CanonicalInteractionEvent(
        event_id="event:delete-1",
        kind=EventKind.ACTIVATE,
        target_component_id="component:delete",
        timestamp_ms=1,
        provenance=EventProvenance.HUMAN,
        capability_id="cap:pointer",
        consent_ok=True,
    )
    # Agent proposal without confirmation cannot execute.
    agent = ActorContext(
        actor_id="actor:agent",
        kind=ActorKind.AGENT,
        delegation_scope=frozenset({binding.binding_id}),
        confirmation_granted=False,
    )
    ctx = RuntimeMediationContext(
        declaration_digest="decl:pilot",
        projection_id="proj:web",
        state_version=1,
        actor=agent,
        ui_enabled=True,
        ui_visible=True,
        policy_norms=(
            PolicyNorm(
                norm_id="norm:allow-delete",
                verdict=PolicyVerdict.ALLOW,
                binding_id=binding.binding_id,
            ),
        ),
    )
    decision = UIMediator().mediate(binding, event, ctx)
    assert decision.outcome is MediationOutcome.CONFIRM
    assert decision.can_execute is False
    assert execute_if_allowed(decision, lambda r: "boom") is None

    # Explicit confirmation then allows.
    confirmed = ActorContext(
        actor_id="actor:human",
        kind=ActorKind.HUMAN,
        human_consent=True,
        confirmation_granted=True,
    )
    ctx2 = RuntimeMediationContext(
        declaration_digest="decl:pilot",
        projection_id="proj:web",
        state_version=2,
        actor=confirmed,
        policy_norms=ctx.policy_norms,
    )
    ok = UIMediator().mediate(binding, event, ctx2)
    assert ok.outcome is MediationOutcome.ALLOW
    assert ok.invocation_request is not None
