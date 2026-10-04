"""Explicit graph reconstruction and source-bound behavioral interpretations."""
from copy import deepcopy
from dataclasses import fields, replace
import hashlib

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import ui_source_contract_384_v2 as old
from ipfs_datasets_py.logic.formalization.autoencoder import ui_source_contract_384_v3 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake_v5 as lake
from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v7 as training
from ipfs_datasets_py.logic.ui_ux_ir.schema import (
    UIComponent, UIIRDocument, UISourceRef, UITerminalOutcome, TerminalOutcomeKind,
    UICompositionEdge, CompositionEdgeKind, UIState, UIEvent, UITransition, EventKind, UIGuard, UIEffect,
)
from ipfs_datasets_py.logic.ui_ux_ir.model.behavior import BehaviorModel, BehaviorState, BehaviorTransition

SOURCE = "An explicitly authored UI graph and declared close transition."


def component(**changes):
    return {"kind": "ui_component", "document": {"component_id": "submit", "role": "button",
        "privacy_sensitivity": "restricted", "presentation_classification": "interactive", **changes}}


def document(*, behavior=False):
    source = UISourceRef(ref_id="source", source_uri="fixture://explicit-graph", source_id="ui",
        source_revision="v1", content_sha256=hashlib.sha256(SOURCE.encode()).hexdigest())
    nodes = (UIComponent("a_child", "button", parent_id="root"),
             UIComponent("b_child", "textbox", parent_id="root"),
             UIComponent("root", "group", child_ids=("b_child", "a_child")))
    edge = UICompositionEdge("slot_edge", CompositionEdgeKind.SLOT, "root", "a_child", "main")
    outcome = UITerminalOutcome("done", TerminalOutcomeKind.SUCCESS, source_ref_ids=("source",))
    extra = {}
    if behavior:
        extra = {"states": (UIState("closed"), UIState("open")),
                 "events": (UIEvent("close_event", EventKind.INPUT),),
                 "transitions": (UITransition("close", "open", "closed", "close_event"),),
                 "initial_states": ("open",)}
    native = UIIRDocument(document_id="ui", title="Declared UI", sources=(source,), components=nodes,
        entry_components=("root",), terminal_outcomes=(outcome,), composition_edges=(edge,), **extra)
    return {"kind": "document", "document": native.to_dict()}


def model():
    # These values are supplied by the fixture author, not inferred from text
    # or from fields absent in the UI envelope.
    return BehaviorModel("declared_behavior", (BehaviorState("closed", terminal=True), BehaviorState("open")),
        (BehaviorTransition("close", ("open",), "closed", event_id="close_event"),), ("open",))


def declaration(target, native=None):
    return subject.UIBehaviorInterpretation.from_model(SOURCE, target, model() if native is None else native)


def prepare(target=None, **kwargs):
    return subject.prepare_family_targets(SOURCE, component() if target is None else target, **kwargs)


def decoded_declarations(audit):
    symbols = {row["symbol"]: (row["category"], row["value"]) for row in audit["symbol_table"]}
    return [(row["predicate"], tuple(symbols[arg] for arg in row["arguments"])) for row in audit["declarations"]]


def test_plain_four_field_components_preserve_v2_formula_and_all_requested_families():
    old_result, result = old.prepare_family_targets(SOURCE, component()), prepare()
    assert result["audit"]["native_formula"]["payload"]["native_ast"] == old_result["audit"]["native_formula"]["payload"]["native_ast"]
    assert result["audit"]["available_families"] == ["first_order", "frame_logic"]
    assert len(result["audit"]["missing_requested_families"]) == 38
    assert len(result["report"]["requested_families"]) == 40
    assert result["audit"]["behavior_status"] == "not_supplied_no_behavior_inferred"
    assert result["source_inputs"]["document"].actor_id == ""
    assert all(result["audit"][key] is False for key in subject.FALSE)
    training.validate_family_training_report_v7(result["report"], **result["source_inputs"])
    assert subject.validate_prepared(result, SOURCE, component())


def test_graph_declares_edge_identity_slot_direction_and_ordered_children_in_formula():
    target = document()
    before = deepcopy(target)
    result = prepare(target)
    facts = decoded_declarations(result["audit"])
    assert ("UICompositionEdge", (("composition_edge", "slot_edge"), ("edge_kind", "slot"),
        ("component", "root"), ("component", "a_child"))) in facts
    assert ("UIEdgeSlot", (("composition_edge", "slot_edge"), ("slot_name", "main"))) in facts
    assert ("UIChildAt", (("component", "root"), ("list_position", "0"), ("component", "b_child"))) in facts
    assert ("UIChildAt", (("component", "root"), ("list_position", "1"), ("component", "a_child"))) in facts
    assert ("UIChildListLength", (("component", "root"), ("list_length", "2"))) in facts
    assert ("UIEntryComponent", (("document", "ui"), ("component", "root"))) in facts
    assert target == before == result["audit"]["candidate"]
    native = lake.prepare_native_family_lean(result["report"], source_inputs=result["source_inputs"])
    assert all(row["parser_status"] == "passed" for row in native["per_projection"])
    assert len(native["per_projection"]) == 2 and native["backend_executed"] is False


@pytest.mark.parametrize("change", ["edge_id", "slot", "child_order"])
def test_previously_lost_graph_changes_now_change_actual_native_ast(change):
    target, changed = document(), document()
    if change == "edge_id":
        changed["document"]["composition_edges"][0]["edge_id"] = "different_edge"
    elif change == "slot":
        changed["document"]["composition_edges"][0]["slot_name"] = "different slot"
    else:
        changed["document"]["components"][-1]["child_ids"].reverse()
    before, after = prepare(target), prepare(changed)
    assert before["audit"]["native_formula"]["payload"]["native_ast"] != after["audit"]["native_formula"]["payload"]["native_ast"]
    old_before, old_after = old.prepare_family_targets(SOURCE, target), old.prepare_family_targets(SOURCE, changed)
    assert old_before["audit"]["native_formula"]["payload"]["native_ast"] == old_after["audit"]["native_formula"]["payload"]["native_ast"]


def test_empty_and_absent_graph_fields_stay_distinct_without_loader_defaults():
    absent = prepare(component())
    explicit = prepare(component(child_ids=[], parent_id="", purpose="", source_ref_ids=[]))
    assert absent["audit"]["declaration_count"] == 4
    predicates = {row[0] for row in decoded_declarations(explicit["audit"])}
    assert {"UIChildListLength", "UIEmptyParentField", "UIPurposeText", "UISourceRefSetSize"} <= predicates
    assert predicates.isdisjoint({"UIChildAt", "UIParent", "UISourceRefRef"})
    assert explicit["audit"]["native_defaults_promoted"] is False


def test_literal_prose_and_provenance_are_fields_not_inferred_policy_or_authority():
    result = prepare(component(purpose="Require consent before sending.", source_ref_ids=["declared-source"]))
    facts = decoded_declarations(result["audit"])
    assert ("UIPurposeText", (("component", "submit"), ("purpose", "Require consent before sending."))) in facts
    assert result["audit"]["ground_structure"]["modal_operators"] == 0
    assert result["audit"]["graph_scope"]["literal_prose_interpreted"] is False
    assert result["audit"]["graph_scope"]["provenance_references_attested"] is False
    assert result["audit"]["source_semantics_verified"] is False


def test_complete_graph_field_accounting_and_unrelated_document_gaps_remain():
    result = prepare(document())
    accounting = result["audit"]["field_accounting"]
    assert len(accounting["component_fields"]) == 3 * len(fields(UIComponent))
    assert {row["path"].rsplit("/", 1)[-1] for row in accounting["document_fields"]} == {f.name for f in fields(UIIRDocument)}
    assert all("first_order" in row["represented_families"] for row in accounting["component_fields"] if row["supplied"])
    assert "program_bindings" in result["audit"]["unprojected_facets"]
    assert "program" in result["audit"]["missing_requested_families"]
    assert "transition_system" in result["audit"]["missing_requested_families"]


def test_wire_behavior_is_not_implicitly_interpreted():
    result = prepare(document(behavior=True))
    assert result["source_inputs"]["document"].behavior_model is None
    assert not result["source_inputs"]["document"].events
    assert result["audit"]["available_families"] == ["first_order", "frame_logic"]
    assert result["audit"]["behavior_interpretation"] is None


def test_explicit_corresponding_behavior_reuses_native_state_and_tla_routes():
    target = document(behavior=True)
    interpretation = declaration(target)
    result = prepare(target, behavior_interpretation=interpretation)
    assert {"transition_system", "event_calculus", "first_order", "frame_logic"} <= set(result["audit"]["available_families"])
    assert len(result["audit"]["missing_requested_families"]) == 36
    assert result["audit"]["behavior_status"] == "explicit_declared_control_targets_available_native_build_required"
    projection_ids = {row["projection_id"] for row in result["report"]["projections"]}
    assert {"ui_ux_ir/declared_state/native/v2", "ui_ux_ir/bounded_state/tla_plus/v4", "ui_ux_ir:event_calculus"} <= projection_ids
    assert not result["source_inputs"]["document"].events
    assert not result["source_inputs"]["document"].action_bindings
    assert result["audit"]["actors_inferred"] is False
    assert result["audit"]["observed_events_invented"] is False
    assert subject.validate_prepared(result, SOURCE, target, behavior_interpretation=interpretation)
    native = lake.prepare_native_family_lean(result["report"], source_inputs=result["source_inputs"])
    assert all(row["parser_status"] == "passed" for row in native["per_projection"])
    assert any(row["lowering"].get("syntax_requirements") for row in native["per_projection"])
    assert native["backend_executed"] is False


@pytest.mark.parametrize("change", ["source", "candidate", "state", "target", "event", "initial", "guard", "priority", "effect"])
def test_interpretation_hashes_and_every_overlapping_native_field_are_checked(change):
    target = document(behavior=True)
    value = declaration(target).to_dict()
    if change == "source":
        value["source_sha256"] = "0" * 64
    elif change == "candidate":
        value["candidate_sha256"] = "0" * 64
    elif change == "state":
        value["behavior_model"]["states"].append({"state_id": "extra", "label": "", "parallel_region": "", "terminal": False})
    elif change == "target":
        value["behavior_model"]["transitions"][0]["target_state_id"] = "open"
    elif change == "event":
        value["behavior_model"]["transitions"][0]["event_id"] = "imagined_event"
    elif change == "initial":
        value["behavior_model"]["initial_state_ids"] = ["closed"]
    elif change == "guard":
        value["behavior_model"]["transitions"][0]["guard_id"] = "invented_guard"
    elif change == "priority":
        value["behavior_model"]["transitions"][0]["priority"] = 9
    else:
        value["behavior_model"]["transitions"][0]["effect_ids"] = ["invented_effect"]
    interpretation = subject.UIBehaviorInterpretation.from_dict(value)
    with pytest.raises(ValueError, match="differs|differ"):
        prepare(target, behavior_interpretation=interpretation)


@pytest.mark.parametrize("location,key", [("states", "terminal"), ("states", "parallel_region"),
    ("transitions", "cancelable"), ("transitions", "retryable"), ("transitions", "timeout_ms"),
    ("transitions", "rollback_target_state_id"), ("transitions", "join_kind")])
def test_missing_behavior_fields_cannot_acquire_constructor_defaults(location, key):
    target = document(behavior=True)
    value = declaration(target).to_dict()
    del value["behavior_model"][location][0][key]
    with pytest.raises(ValueError, match="complete explicit"):
        subject.UIBehaviorInterpretation.from_dict(value)


def test_supplied_timeout_is_retained_and_blocked_not_silently_erased():
    target = document(behavior=True)
    native = model()
    native = replace(native, transitions=(replace(native.transitions[0], timeout_ms=15),))
    result = prepare(target, behavior_interpretation=declaration(target, native))
    assert result["audit"]["status"] == "projected_candidate_with_blocked_behavior"
    assert result["audit"]["behavior_interpretation"]["behavior_model"]["transitions"][0]["timeout_ms"] == 15
    assert "transition_system" in result["audit"]["missing_requested_families"]
    assert any("timeout" in row.get("reason", "").lower() for row in result["audit"]["behavior_frontier"])
    prepared = lake.prepare_native_family_lean(result["report"], source_inputs=result["source_inputs"])
    assert any(row["logic_family"] == "event_calculus" and row["parser_status"] == "blocked" for row in prepared["per_projection"])


@pytest.mark.parametrize("unsupported", ["guard", "effect", "priority", "uncancelable", "undoable"])
def test_explicit_unsupported_control_fields_keep_failed_projections_and_frontier(unsupported):
    target, native = document(behavior=True), model()
    updates = {}
    if unsupported == "guard":
        target["document"]["guards"] = [UIGuard("guard_open", constraint_ref="open").to_dict()]
        target["document"]["transitions"][0]["guard_id"] = "guard_open"
        updates["guard_id"] = "guard_open"
    elif unsupported == "effect":
        target["document"]["effects"] = [UIEffect("effect_close", local_state_transition="close").to_dict()]
        target["document"]["transitions"][0]["effect_ids"] = ["effect_close"]
        updates["effect_ids"] = ("effect_close",)
    elif unsupported == "priority":
        target["document"]["transitions"][0]["priority"] = 7
        updates["priority"] = 7
    else:
        updates["cancelable" if unsupported == "uncancelable" else "undoable"] = unsupported != "uncancelable"
    native = replace(native, transitions=(replace(native.transitions[0], **updates),))
    result = prepare(target, behavior_interpretation=declaration(target, native))
    assert result["audit"]["status"] == "projected_candidate_with_blocked_behavior"
    assert {"event_calculus", "transition_system"} <= set(result["audit"]["missing_requested_families"])
    ec = next(row for row in result["report"]["projections"] if row["logic_family"] == "event_calculus")
    assert ec["ready_for_training"] is False
    assert result["audit"]["behavior_frontier"] and result["audit"]["candidate"] == target


def test_extra_explicit_behavior_changes_binding_without_rewriting_candidate():
    target = document(behavior=True)
    first = prepare(target, behavior_interpretation=declaration(target))
    alternative = replace(model(), states=(BehaviorState("closed", terminal=False), BehaviorState("open")))
    second = prepare(target, behavior_interpretation=declaration(target, alternative))
    assert first["audit"]["candidate"] == second["audit"]["candidate"] == target
    assert first["report"]["source_digest"] != second["report"]["source_digest"]
    assert first["audit"]["behavior_interpretation_sha256"] != second["audit"]["behavior_interpretation_sha256"]
    assert second["audit"]["source_semantics_verified"] is False


def test_no_event_id_substitution_and_no_fragment_behavior_context():
    target = document(behavior=True)
    target["document"]["transitions"][0]["event_id"] = ""
    native = replace(model(), transitions=(replace(model().transitions[0], event_id=""),))
    with pytest.raises(ValueError, match="no transition-ID event fallback"):
        prepare(target, behavior_interpretation=declaration(target, native))
    target = component()
    with pytest.raises(ValueError, match="complete native UI document"):
        prepare(target, behavior_interpretation=declaration(target))


def test_bounds_and_tampered_replay_refuse_without_truncation():
    with pytest.raises(ValueError, match="no truncation"):
        prepare(component(purpose="x" * 9000))
    prepared = prepare(document())
    prepared["audit"]["symbol_table"][0]["value"] = "wrong"
    with pytest.raises(ValueError, match="replay differs"):
        subject.validate_prepared(prepared, SOURCE, document())


def test_explicit_request_scope_remains_visible_for_behavior():
    target = document(behavior=True)
    result = prepare(target, requested_families=("frame_logic", "first_order", "dcec"),
        behavior_interpretation=declaration(target))
    assert result["audit"]["missing_requested_families"] == ["dcec"]
    assert result["audit"]["behavior_status"] == "explicit_behavior_retained_but_state_route_not_requested"
    assert result["source_inputs"]["document"].behavior_model is not None
    assert result["report"]["all_requested_families_available"] is False
