"""Actual Intent inputs; strict operator, role, reference and control semantics."""
from copy import deepcopy
from dataclasses import replace
import hashlib
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import native_intent_lean as api
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lean_emitters as old
from ipfs_datasets_py.logic.formalization.autoencoder import native_family_lake as lake
from ipfs_datasets_py.logic.formalization.autoencoder import family_training_v3 as targets
from ipfs_datasets_py.logic.intent_ir.schema import (IntentIRDocument, IntentKind, IntentStatement,
    StatementKind, IntentModality, IntentAction, IntentControlEdge, ControlEdgeKind, SourceRef)


def document(modality="required", kind="goal", actions=True, contract=False, sequence=False):
    ref = SourceRef("source", "urn:authored:intent", "authored", "v1", content_sha256="a" * 64)
    statements = [IntentStatement("statement:goal", StatementKind(kind), IntentModality(modality),
        "Officer publishes report.", ("source",), "publish", ("officer", "report"))]
    if kind != "goal":
        statements.append(IntentStatement("statement:requiredgoal", StatementKind.GOAL, IntentModality.REQUIRED,
            "A required objective is declared.", ("source",), "objective", ("officer",)))
    if contract:
        statements += [IntentStatement("pre", StatementKind.PRECONDITION, IntentModality.ASSERTED,
            "Report exists.", ("source",), "exists", ("report",)),
            IntentStatement("post", StatementKind.EFFECT, IntentModality.ASSERTED,
            "Report published.", ("source",), "published", ("report",))]
    nodes = [IntentAction("action:publish", "officer", "publish", ("report",), ("source",),
        precondition_ids=("pre",) if contract else (), effect_ids=("post",) if contract else ())] if actions else []
    edges = []
    if sequence:
        nodes.append(IntentAction("action:archive", "officer", "archive", ("report",), ("source",)))
        edges.append(IntentControlEdge("edge:next", "action:publish", "action:archive", ControlEdgeKind.NEXT, source_ref_ids=("source",)))
    return IntentIRDocument("intent:fixture", "Authored intent", IntentKind.PROCEDURE if actions else IntentKind.DECLARATIVE,
        (ref,), tuple(statements), tuple(nodes), tuple(edges), (nodes[0].action_id,) if nodes else (),
        (nodes[-1].action_id,) if nodes else ())


def report(**kwargs):
    return targets.prepare_family_training_targets_v3("intent_ir", document=document(**kwargs))


def row(value, identity):
    return next(v for v in value["projections"] if v["projection_id"] == identity)


@pytest.mark.parametrize("modality,operator", [("required", "O"), ("permitted", "P"), ("prohibited", "F")])
def test_norms_preserve_distinct_declared_modality_order_and_provenance(modality, operator):
    value = report(modality=modality)
    target = row(value, "intent-route/norms/v1")
    source, details = api.emit_projection(target, report=value)
    assert 'deontic:' + operator in source and 'i.atom "publish" [(i.constant "officer"), (i.constant "report")]' in source
    assert details["retained_native_records"] == target["payload"]
    assert "axiom" not in source and "sorry" not in source


def test_asserted_goal_remains_intention_with_exact_actor_binding():
    value = report(modality="asserted")
    source, details = api.emit_projection(row(value, "intent-route/intentions/v1"), report=value)
    assert 'i.cognitive "I" (i.agent "officer")' in source
    assert details["operators"] == ["I"]
    value["projections"] = [r for r in value["projections"] if r["projection_id"] != "intent-route/action-hoare/v1"]
    with pytest.raises(old.UnsupportedNativeLean, match="exact_native_action_actor"):
        api.emit_projection(row(value, "intent-route/intentions/v1"), report=value)


def test_recommendation_has_no_invented_obligation_operator():
    value = report(modality="recommended")
    with pytest.raises(old.UnsupportedNativeLean, match="recommendation"):
        api.emit_projection(row(value, "intent-route/norms/v1"), report=value)


def test_asserted_assumption_subfragment_has_predicates_but_complete_mixed_row_stays_blocked():
    value = report(modality="asserted", kind="assumption", actions=False)
    target = row(value, "intent-route/facts/v1")
    actual_assumption = [r for r in target["payload"] if r.get("statement_kind") == "assumption"]
    source, details = api._facts(actual_assumption)
    assert 'i.atom "publish" [(i.constant "officer"), (i.constant "report")]' in source
    assert "assumption_0" in source and details["operators"] == ["ordered_ground_predicate"]
    with pytest.raises(old.UnsupportedNativeLean, match="flattened_to_FOL"):
        api.emit_projection(target, report=value)


@pytest.mark.parametrize("kwargs", [{}, {"modality": "asserted"}, {"modality": "required", "actions": False}])
def test_modal_goals_and_action_declarations_do_not_become_FOL_truth(kwargs):
    value = report(**kwargs)
    with pytest.raises(old.UnsupportedNativeLean):
        api.emit_projection(row(value, "intent-route/facts/v1"), report=value)


def test_nonvacuous_hoare_preserves_pre_and_post_and_actual_action_identity():
    value = report(contract=True)
    target = row(value, "intent-route/action-hoare/v1")
    source, details = api.emit_projection(target, report=value)
    assert 'i.atom "exists" [(i.constant "report")] s' in source
    assert 'i.atom "published" [(i.constant "report")] t' in source
    assert 'i.step "action:publish" (i.constant "officer") "publish" [(i.constant "report")] s t' in source
    assert details["capability_floor_eligible"]
    assert details["retained_native_records"] == target["payload"]


def test_vacuous_contract_cannot_earn_program_capability_floor():
    value = report()
    source, details = api.emit_projection(row(value, "intent-route/action-hoare/v1"), report=value)
    assert "(True)" in source and not details["capability_floor_eligible"]
    assert details["capability_floor_reason"] == "vacuous_contract_without_meaningful_postcondition"


@pytest.mark.parametrize("change", ["missing_post", "wrong_join", "wrong_role", "tool", "verification", "modal_pre"])
def test_hoare_unsupported_or_mismatched_semantics_fail_closed(change):
    value = report(contract=True)
    target = row(value, "intent-route/action-hoare/v1")
    item = target["payload"][0]
    if change == "missing_post": item["postcondition"] = []
    elif change == "wrong_join": item["action"]["effect_ids"] = ["other"]
    elif change == "wrong_role":
        item["postcondition"][0]["kind"] = item["effects"][0]["kind"] = "verification"
    elif change == "tool": item["action"]["tool_refs"] = ["tool:unbound"]
    elif change == "verification": item["action"]["verification_ids"] = ["proof:unbound"]
    else: item["precondition"][0]["modality"] = "required"
    with pytest.raises((old.UnsupportedNativeLean, ValueError)):
        api.emit_projection(target, report=value)


@pytest.mark.parametrize("sequence", [False, True])
def test_actual_linear_pc_state_preserves_terminal_stutter_and_declared_bound(sequence):
    value = report(sequence=sequence)
    target = row(value, "intent-extended/transition_system/default/v1")
    source, details = api.emit_projection(target, report=value)
    assert "boundedControlRun" in source and "declaredMaxSteps : Nat := 64" in source
    assert "simpa" in source and "intentActionOrigins" in source
    assert details["retained_native_context"] == target["payload"]
    assert "terminal_self_loop" in details["operators"]
    workflow, info = api.emit_projection(row(value, "intent-route/workflow-temporal/v1"), report=value)
    assert "completeDeclaredActionSequence" in workflow
    assert info["validator"] == "native_workflow_boundary_edges_join_exact_linear_StateTransitionIR"


@pytest.mark.parametrize("change", ["schema_extra", "schema_missing", "variable", "predicate", "transition", "element_type"])
def test_direct_linear_state_helper_cannot_discard_uninterpreted_annotations(change):
    from ipfs_datasets_py.logic.software_verification.transitions import StateTransitionIR
    value = report(sequence=True)
    payload = deepcopy(row(value, "intent-extended/transition_system/default/v1")["payload"])
    native = StateTransitionIR.from_dict(payload["payload"])
    unknown = {"semantic_constraint": "uninterpreted"}
    if change.startswith("schema_"):
        metadata = {**native.schema.metadata.to_dict(), **unknown} if change == "schema_extra" else {}
        native = replace(native, schema=replace(native.schema, metadata=metadata, schema_id=""), document_id="")
    elif change == "variable":
        variables = (replace(native.schema.variables[0], attributes=unknown),)
        native = replace(native, schema=replace(native.schema, variables=variables, schema_id=""), document_id="")
    elif change == "predicate":
        native = replace(native, predicates=(replace(native.predicates[0], attributes=unknown), *native.predicates[1:]), document_id="")
    elif change == "transition":
        native = replace(native, transitions=(replace(native.transitions[0], attributes=unknown), *native.transitions[1:]), document_id="")
    payload["payload"] = native.to_dict()
    if change == "element_type":
        # The native schema already disallows an element sort on the scalar pc;
        # the direct helper must preserve that parser rejection too.
        payload["payload"]["schema"]["variables"][0]["element_type_kind"] = "integer"
    with pytest.raises((old.UnsupportedNativeLean, ValueError)):
        api._linear_native(payload)


@pytest.mark.parametrize("change", ["budget", "mapping", "scope", "missing_state", "missing_edge", "boundary"])
def test_workflow_cannot_hide_unknown_control_or_different_native_mapping(change):
    value = report(sequence=True)
    target = row(value, "intent-route/workflow-temporal/v1")
    state = row(value, "intent-extended/transition_system/default/v1")
    if change == "budget": state["payload"]["context"]["max_steps"] = 1
    elif change == "mapping": state["payload"]["node_map"][0]["to_position"] = "done"
    elif change == "scope": state["payload"]["context"]["workflow"] = {"semantics": "unknown"}
    elif change == "missing_state": value["projections"].remove(state)
    elif change == "missing_edge": target["payload"] = [r for r in target["payload"] if r["kind"] == "workflow_boundary"]
    else: next(r for r in target["payload"] if r["kind"] == "workflow_boundary")["terminal_action_ids"] = ["action:publish"]
    with pytest.raises((old.UnsupportedNativeLean, ValueError)):
        api.emit_projection(target, report=value)


@pytest.mark.parametrize("family", ["datalog", "horn_chc"])
def test_declaration_dumps_cannot_earn_domain_logic_family_floor(family):
    value = report()
    with pytest.raises(old.UnsupportedNativeLean, match="reified_Intent_declaration_data"):
        api.emit_projection(row(value, "intent-extended/" + family + "/default/v1"), report=value)


def test_wrong_domain_and_unknown_routes_do_not_enter_emitter():
    value = report()
    target = row(value, "intent-route/norms/v1")
    with pytest.raises(old.UnsupportedNativeLean, match="same_domain"):
        api.emit_projection(target, report={**value, "domain_id": "legal_ir"})
    with pytest.raises(NotImplementedError): api.emit_projection({"projection_id": "unowned"})


def test_own_source_guard_rejects_drift(monkeypatch):
    value = report()
    monkeypatch.setattr(api, "_SOURCE_SHA", "0" * 64)
    with pytest.raises(old.UnsupportedNativeLean, match="changed_after_import"):
        api.emit_projection(row(value, "intent-route/norms/v1"), report=value)


def test_real_lake_build_for_all_supported_Intent_fragments():
    executable = Path("/home/barberb/.elan/toolchains/leanprover--lean4---v4.34.1/bin/lake")
    if not executable.is_file(): pytest.skip("installed native Lean toolchain unavailable")
    sources = []
    cases = [(report(), "intent-route/norms/v1"), (report(modality="asserted"), "intent-route/intentions/v1"),
        (report(contract=True), "intent-route/action-hoare/v1"),
        (report(), "intent-route/action-hoare/v1"),
        (report(sequence=True), "intent-extended/transition_system/default/v1"),
        (report(sequence=True), "intent-route/workflow-temporal/v1")]
    for index, (value, identity) in enumerate(cases):
        source, _ = api.emit_projection(row(value, identity), report=value)
        sources.append("namespace Case" + str(index) + "\n" + source + "\nend Case" + str(index))
    # The assertion-only subfragment can be interpreted, but the full inherited
    # facts projection is blocked because its required GOAL is modal, not FOL.
    mixed = report(modality="asserted", kind="assumption", actions=False)
    fact_rows = [v for v in row(mixed, "intent-route/facts/v1")["payload"] if v.get("statement_kind") == "assumption"]
    fragment, _ = api._facts(fact_rows)
    sources.append("namespace AssertionFragment\n" + fragment + "\nend AssertionFragment")
    result = lake._execute("namespace IntentIR\n" + old.PRELUDE + "\n" + "\n".join(sources) + "\nend IntentIR\n",
        "IntentIR", str(executable), 30)
    assert result["backend_executed"] and result["status"] == "passed", result
    assert result["command"][-2:] == ["build", "IntentIR"]
