"""Closed modeling premises and exhaustive exploration resource frontiers."""
from copy import deepcopy
from dataclasses import replace

import pytest

from ipfs_datasets_py.logic.intent_ir.formalize import guarded_workflow as guarded
from ipfs_datasets_py.logic.intent_ir.formalize.state_projections import project_state_families
from ipfs_datasets_py.logic.intent_ir.formalize.projection_contracts import source_ir_sha256
from ipfs_datasets_py.logic.intent_ir.formalize.roundtrip import frame_to_intent_ir
from ipfs_datasets_py.logic.intent_ir.schema import IntentModality, StatementKind


def fixture():
    source = frame_to_intent_ir({"actor": "agent", "action": "inspect", "object": "cache", "modality": "required"},
                               instruction="agent must inspect cache")
    condition = replace(source.statements[0], statement_id="condition", kind=StatementKind.PRECONDITION,
                        modality=IntentModality.ASSERTED)
    source = replace(source, statements=(*source.statements, condition),
                     actions=(replace(source.actions[0], precondition_ids=("condition",)),))
    return source, {"state": {"max_steps": 8, "workflow": {
        "semantics": guarded.SEMANTICS, "source_ir_sha256": source_ir_sha256(source), "evidence_ref": "source",
        "variables": [{"variable_id": "value", "kind": "integer", "domain": [0, 2],
                       "initial_values": [0], "evidence_ref": "source"}],
        "predicate_bindings": [{"statement_id": "condition", "expression": {
            "op": "eq", "variable_id": "value", "value": 0}, "evidence_ref": "source"}],
        "action_updates": [{"action_id": "action", "outcomes": [{"values": {"value": 2},
            "evidence_ref": "source"}], "evidence_ref": "source"}], "retry_bounds": []}}}


def test_sparse_integer_domain_is_exact_and_not_its_enclosing_range():
    source, context = fixture()
    projection = project_state_families(source, context)[0]
    rows = projection["representation"]["configuration_map"]
    assert {row["values"].get("value") for row in rows} == {None, 0, 2}
    assert projection["representation"]["guarded_model"]["deadlock_free"]
    for field in ("initial", "comparison", "update"):
        changed = deepcopy(context)
        workflow = changed["state"]["workflow"]
        if field == "initial":
            workflow["variables"][0]["initial_values"] = [1]
        elif field == "comparison":
            workflow["predicate_bindings"][0]["expression"]["value"] = 1
        else:
            workflow["action_updates"][0]["outcomes"][0]["values"]["value"] = 1
        with pytest.raises(ValueError):
            project_state_families(source, changed)


@pytest.mark.parametrize("slot", ["domain", "initial", "comparison", "update"])
def test_boolean_cannot_alias_an_integer_state_value(slot):
    source, context = fixture()
    premise = context["state"]["workflow"]
    if slot == "domain":
        premise["variables"][0]["domain"] = [False, 2]
    elif slot == "initial":
        premise["variables"][0]["initial_values"] = [False]
    elif slot == "comparison":
        premise["predicate_bindings"][0]["expression"]["value"] = False
    else:
        premise["action_updates"][0]["outcomes"][0]["values"]["value"] = False
    with pytest.raises(ValueError):
        project_state_families(source, context)


@pytest.mark.parametrize("location", ["workflow", "variable", "binding", "expression", "update", "outcome"])
def test_unknown_fields_cannot_smuggle_additional_model_semantics(location):
    source, context = fixture()
    premise = context["state"]["workflow"]
    selected = {"workflow": premise, "variable": premise["variables"][0],
        "binding": premise["predicate_bindings"][0], "expression": premise["predicate_bindings"][0]["expression"],
        "update": premise["action_updates"][0], "outcome": premise["action_updates"][0]["outcomes"][0]}[location]
    selected["python"] = "unreviewed_behavior()"
    with pytest.raises(ValueError):
        project_state_families(source, context)


@pytest.mark.parametrize("bad_expression", [
    {"op": "eval", "expression": "True"}, {"op": "literal", "value": 1}, {"op": []},
    {"op": "and", "args": []}, {"op": "eq", "variable_id": "absent", "value": 0},
])
def test_unrecognized_or_untyped_predicates_are_rejected(bad_expression):
    source, context = fixture()
    context["state"]["workflow"]["predicate_bindings"][0]["expression"] = bad_expression
    with pytest.raises(ValueError):
        project_state_families(source, context)


def test_deep_boolean_ast_is_rejected_before_interpretation():
    source, context = fixture()
    expression = {"op": "literal", "value": True}
    for _ in range(10):
        expression = {"op": "not", "arg": expression}
    context["state"]["workflow"]["predicate_bindings"][0]["expression"] = expression
    with pytest.raises(ValueError, match="bounded"):
        project_state_families(source, context)


def test_boolean_expression_composition_changes_enabledness():
    source, context = fixture()
    condition = context["state"]["workflow"]["predicate_bindings"][0]
    condition["expression"] = {"op": "and", "args": [
        {"op": "ne", "variable_id": "value", "value": 2},
        {"op": "or", "args": [{"op": "literal", "value": False},
            {"op": "not", "arg": {"op": "literal", "value": False}}]}]}
    assert project_state_families(source, context)[0]["representation"]["guarded_model"]["deadlock_free"]
    condition["expression"]["args"][0]["value"] = 0
    assert not project_state_families(source, context)[0]["representation"]["guarded_model"]["deadlock_free"]


def test_a_normative_precondition_is_not_reinterpreted_as_boolean_truth():
    source, context = fixture()
    source = replace(source, statements=tuple(replace(s, modality=IntentModality.REQUIRED)
        if s.statement_id == "condition" else s for s in source.statements))
    context["state"]["workflow"]["source_ir_sha256"] = source_ir_sha256(source)
    reports = project_state_families(source, context)
    assert all(r["status"] == "unsupported" for r in reports)
    assert reports[0]["unsupported"][0]["reason"] == "normative_statement_cannot_be_used_as_state_truth"


@pytest.mark.parametrize("slot", ["workflow", "variable", "binding", "update", "outcome"])
def test_missing_source_evidence_cannot_be_manufactured(slot):
    source, context = fixture()
    premise = context["state"]["workflow"]
    selected = {"workflow": premise, "variable": premise["variables"][0],
        "binding": premise["predicate_bindings"][0], "update": premise["action_updates"][0],
        "outcome": premise["action_updates"][0]["outcomes"][0]}[slot]
    selected["evidence_ref"] = "nonexistent"
    with pytest.raises(ValueError):
        project_state_families(source, context)


def test_oversized_initial_cartesian_product_is_unsupported_not_sampled():
    source, context = fixture()
    premise = context["state"]["workflow"]
    premise["variables"] = [{"variable_id": f"var{i}", "kind": "boolean", "domain": [False, True],
        "initial_values": [False, True], "evidence_ref": "source"} for i in range(6)]
    premise["predicate_bindings"][0]["expression"] = {"op": "literal", "value": True}
    premise["action_updates"][0]["outcomes"][0]["values"] = {}
    reports = project_state_families(source, context)
    assert all(r["status"] == "unsupported" and r["representation"]["payload"] is None for r in reports)
    assert reports[0]["unsupported"][0]["reason"] == "guarded_workflow_initial_valuation_bound_exceeded"


@pytest.mark.parametrize("limit,reason", [
    ("MAX_CONFIGURATIONS", "guarded_workflow_configuration_bound_exceeded"),
    ("MAX_TRANSITIONS", "guarded_workflow_transition_bound_exceeded"),
])
def test_resource_limit_rejects_entire_model_instead_of_returning_partial_graph(monkeypatch, limit, reason):
    source, context = fixture()
    monkeypatch.setattr(guarded, limit, 1)
    reports = project_state_families(source, context)
    assert all(r["status"] == "unsupported" and r["representation"]["payload"] is None for r in reports)
    assert reports[0]["unsupported"][0]["reason"] == reason


def test_native_guarded_model_has_no_opaque_guard_fallback_or_proof_claim():
    source, context = fixture()
    state, tla = project_state_families(source, context)
    payload = state["representation"]["payload"]
    assert all(set(row["expression"]) == {"var:pc"} for row in payload["predicates"])
    assert all(state[key] is False for key in ("proof_authority", "execution_authority", "source_semantics_verified"))
    assert state["representation"]["guarded_model"]["predicate_binding_semantics"] == \
        "caller_supplied_abstract_truth_not_source_code_equivalence"
    assert "INVARIANT NoAbstractDeadlock" in tla["representation"]["qualification"]["tlc_config_text"]
    # The native compiler honestly retains its generic finite-step loss; there
    # must be no opaque predicate approximation to TRUE in this lowering.
    assert {row["construct"] for row in tla["representation"]["payload"]["losses"]} == {"finite_step_bound"}
