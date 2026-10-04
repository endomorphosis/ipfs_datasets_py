"""Explicit UI guard declarations, never training or independent fidelity data."""
from copy import deepcopy
from dataclasses import replace
import hashlib


def cases():
    from ipfs_datasets_py.logic.ui_ux_ir.schema import (
        UIComponent, UIIRDocument, UISourceRef, UITerminalOutcome, TerminalOutcomeKind,
        UIState, UIEvent, UITransition, EventKind, UIGuard,
    )
    from ipfs_datasets_py.logic.ui_ux_ir.model.behavior import BehaviorModel, BehaviorState, BehaviorTransition
    from ipfs_datasets_py.logic.formalization.autoencoder import ui_source_contract_384_v4 as adapter
    from ipfs_datasets_py.logic.formalization.autoencoder import native_ui_guarded_lean as owner
    source_text = "Explicit fixture: close is guarded by a caller-declared frozen Boolean condition."
    source = UISourceRef(ref_id="source", source_uri="fixture://boolean-guard", source_id="ui",
        source_revision="v1", content_sha256=hashlib.sha256(source_text.encode()).hexdigest())
    document = UIIRDocument(document_id="ui", title="Explicit Boolean guard", sources=(source,),
        components=(UIComponent("button", "button"),), entry_components=("button",),
        terminal_outcomes=(UITerminalOutcome("done", TerminalOutcomeKind.SUCCESS, source_ref_ids=("source",)),),
        states=(UIState("open"), UIState("closed")), initial_states=("open",),
        events=(UIEvent("close_event", EventKind.INPUT),),
        guards=(UIGuard("guard_close", constraint_ref="open", source_ref_ids=("source",)),),
        transitions=(UITransition("close", "open", "closed", "close_event", guard_id="guard_close"),))
    target = {"kind": "document", "document": document.to_dict()}
    model = BehaviorModel("explicit_boolean_guard", (BehaviorState("open"), BehaviorState("closed", terminal=True)),
        (BehaviorTransition("close", ("open",), "closed", event_id="close_event", guard_id="guard_close"),), ("open",))

    def build(identity, initial, expression=None, *, timeout=None):
        actual_model = model if timeout is None else replace(model,
            transitions=(replace(model.transitions[0], timeout_ms=timeout),))
        behavior = adapter.UIBehaviorInterpretation.from_model(source_text, target, actual_model)
        expression = expression or {"op": "variable", "variable_id": "allowed"}
        variables = [{"variable_id": "allowed", "type": "boolean", "initial_value": initial}]
        if expression["op"] == "and":
            variables.append({"variable_id": "cancelled", "type": "boolean", "initial_value": False})
        guard = adapter.UIGuardInterpretation.from_dict({"schema": owner.EVIDENCE_SCHEMA,
            "source_sha256": hashlib.sha256(source_text.encode()).hexdigest(),
            "candidate_sha256": owner.digest(target), "behavior_sha256": owner.digest(behavior.to_dict()),
            "declaration_scope": owner.SCOPE,
            "parameter_update_semantics": "unchanged_by_all_transitions_no_external_updates",
            "variables": variables, "guards": [{"native_guard": document.guards[0].to_dict(), "expression": expression}],
            "max_steps": 4})
        return {"id": identity, "domain": "ui_ux_ir", "source_text": source_text, "candidate": deepcopy(target),
            "candidate_origin": "authored_adapter_fixture_not_model_output",
            "options": {"behavior_interpretation": behavior, "guard_interpretation": guard}}

    result = [build("ui-guard-initial-true", True), build("ui-guard-initial-false", False),
        build("ui-guard-compound", True, {"op": "and", "args": [
            {"op": "variable", "variable_id": "allowed"},
            {"op": "not", "arg": {"op": "variable", "variable_id": "cancelled"}}]}),
        build("ui-guard-timeout-still-blocked", True, timeout=100)]
    mismatch = build("ui-guard-wrong-binding", True)
    declaration = mismatch["options"]["guard_interpretation"].to_dict()
    declaration["candidate_sha256"] = "0" * 64
    mismatch["options"]["guard_interpretation"] = adapter.UIGuardInterpretation.from_dict(declaration)
    result.append(mismatch)
    return result
