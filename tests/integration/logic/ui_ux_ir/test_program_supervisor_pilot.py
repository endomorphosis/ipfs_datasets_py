"""UIR-074: dynamic program and Agent Supervisor UI pilot."""

from __future__ import annotations

import json
from pathlib import Path

from ipfs_datasets_py.logic.ui_ux_ir.runtime.events import (
    CanonicalInteractionEvent,
    EventKind,
    EventProvenance,
    validate_event,
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
from ipfs_datasets_py.logic.ui_ux_ir.model.bindings import (
    ConfirmationClass,
    RiskClass,
    UIActionBinding,
    UIProgramRef,
)
from ipfs_datasets_py.logic.ui_ux_ir.schema import ProgramBindingTargetKind, UIIRValidationError
import pytest

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "fixtures"
    / "ui_ux_ir"
    / "pilots"
    / "agent_supervisor_program.json"
)


def test_agent_proposals_visibly_distinct_and_policy_bound() -> None:
    pilot = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert pilot["agent_proposal_visible"] is True
    assert pilot["capability_bound_ui_changes"] is True
    assert "proposal_visible" in pilot["program_states"]

    binding = UIActionBinding(
        binding_id="binding:run-task",
        action_id="action:run-task",
        program_ref=UIProgramRef(
            target_kind=ProgramBindingTargetKind.MCP_IDL,
            mcp_idl_interface_cid="bafyagent",
            mcp_idl_method_name="run_task",
        ),
        risk_class=RiskClass.MEDIUM,
        confirmation_class=ConfirmationClass.CONFIRM,
    )
    # Goal/task text cannot smuggle authority or code through event payload.
    with pytest.raises(UIIRValidationError):
        validate_event(
            CanonicalInteractionEvent(
                event_id="e1",
                kind=EventKind.ACTIVATE,
                target_component_id="c",
                timestamp_ms=1,
                provenance=EventProvenance.AGENT,
                capability_id="cap:agent",
                consent_ok=True,
                raw_payload={"authorization": "grant-all"},
            )
        )

    event = CanonicalInteractionEvent(
        event_id="e2",
        kind=EventKind.ACTIVATE,
        target_component_id="c",
        timestamp_ms=1,
        provenance=EventProvenance.AGENT,
        capability_id="cap:agent",
        consent_ok=True,
    )
    agent = ActorContext(
        actor_id="agent:supervisor",
        kind=ActorKind.AGENT,
        delegation_scope=frozenset({"binding:run-task"}),
        confirmation_granted=False,
    )
    decision = UIMediator().mediate(
        binding,
        event,
        RuntimeMediationContext(
            declaration_digest="decl:agent-pilot",
            projection_id="proj:supervisor",
            state_version=0,
            actor=agent,
            policy_norms=(
                PolicyNorm(
                    norm_id="norm:allow",
                    verdict=PolicyVerdict.ALLOW,
                    binding_id="binding:run-task",
                ),
            ),
        ),
    )
    # Agent path still requires confirmation — cannot silently execute.
    assert decision.outcome is MediationOutcome.CONFIRM
    assert decision.can_execute is False
