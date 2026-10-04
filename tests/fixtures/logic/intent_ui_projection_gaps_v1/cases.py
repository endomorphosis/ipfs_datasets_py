"""Authored adapter fixtures, explicitly separate from learned predictions.

These are executable declaration tests, not a training set or fidelity holdout.
Behavior meanings are supplied by the fixture author and never inferred from
event labels or a component's privacy classification.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib


def cases():
    from ipfs_datasets_py.logic.ui_ux_ir.schema import (
        UIComponent, UIIRDocument, UISourceRef, UITerminalOutcome, TerminalOutcomeKind,
        UICompositionEdge, CompositionEdgeKind, UIState, UIEvent, UITransition, EventKind,
    )
    from ipfs_datasets_py.logic.ui_ux_ir.model.behavior import BehaviorModel, BehaviorState, BehaviorTransition
    from ipfs_datasets_py.logic.formalization.autoencoder.ui_source_contract_384_v3 import UIBehaviorInterpretation

    def atom(actor, action, obj, modality):
        return {"kind": "atom", "actor": actor, "action": action, "object": obj, "modality": modality}

    def intent(identity, text, ast):
        return {"id": identity, "domain": "intent_ir", "source_text": text,
            "candidate": {"kind": "intent_rich_ast", "document": ast}, "options": {}}

    action = atom("agent", "inspect", "Cache.py", "required")
    conditional = {"kind": "if", "guard": {"subject": "Cache.py", "property": "ready", "negated": False},
        "body": action}
    negative = deepcopy(conditional)
    negative["guard"]["negated"] = True
    wrong = deepcopy(conditional)
    wrong["body"]["modality"] = "permitted"
    result = [
        intent("intent-if", "If Cache.py is ready, agent must inspect Cache.py.", conditional),
        intent("intent-if-negative", "If Cache.py is not ready, agent must inspect Cache.py.", negative),
        intent("intent-and", "agent must inspect Cache.py and reviewer may archive Report.py.",
            {"kind": "and", "left": action, "right": atom("reviewer", "archive", "Report.py", "permitted")}),
        intent("intent-or", "agent must inspect Cache.py or reviewer must not delete Report.py.",
            {"kind": "or", "left": action, "right": atom("reviewer", "delete", "Report.py", "prohibited")}),
        intent("intent-recommendation", "agent should inspect Cache.py.", atom("agent", "inspect", "Cache.py", "recommended")),
        intent("intent-wrong-modality", "If Cache.py is ready, agent must inspect Cache.py.", wrong),
    ]
    source_text = "An explicitly authored UI graph and declared close transition."
    source = UISourceRef(ref_id="source", source_uri="fixture://explicit-graph", source_id="ui",
        source_revision="v1", content_sha256=hashlib.sha256(source_text.encode()).hexdigest())
    nodes = (UIComponent("a_child", "button", parent_id="root"),
        UIComponent("b_child", "textbox", parent_id="root"),
        UIComponent("root", "group", child_ids=("b_child", "a_child")))
    edge = UICompositionEdge("slot_edge", CompositionEdgeKind.SLOT, "root", "a_child", "main")
    outcome = UITerminalOutcome("done", TerminalOutcomeKind.SUCCESS, source_ref_ids=("source",))
    document = UIIRDocument(document_id="ui", title="Declared UI", sources=(source,), components=nodes,
        entry_components=("root",), terminal_outcomes=(outcome,), composition_edges=(edge,))
    graph = {"kind": "document", "document": document.to_dict()}
    behavior_document = replace(document, states=(UIState("closed"), UIState("open")),
        events=(UIEvent("close_event", EventKind.INPUT),),
        transitions=(UITransition("close", "open", "closed", "close_event"),), initial_states=("open",))
    behavior_target = {"kind": "document", "document": behavior_document.to_dict()}
    model = BehaviorModel("declared_behavior", (BehaviorState("closed", terminal=True), BehaviorState("open")),
        (BehaviorTransition("close", ("open",), "closed", event_id="close_event"),), ("open",))

    def ui(identity, candidate, supplied=None):
        options = {} if supplied is None else {"behavior_interpretation":
            UIBehaviorInterpretation.from_model(source_text, candidate, supplied)}
        return {"id": identity, "domain": "ui_ux_ir", "source_text": source_text,
            "candidate": candidate, "options": options}

    result.extend([
        ui("ui-ordered-graph", graph),
        ui("ui-state-without-interpretation", behavior_target),
        ui("ui-declared-state", behavior_target, model),
        ui("ui-behavior-mismatch", behavior_target, replace(model, initial_state_ids=("closed",))),
        ui("ui-timeout-frontier", behavior_target,
            replace(model, transitions=(replace(model.transitions[0], timeout_ms=100),))),
    ])
    for row in result:
        row["candidate_origin"] = "authored_adapter_fixture_not_model_output"
    return result
