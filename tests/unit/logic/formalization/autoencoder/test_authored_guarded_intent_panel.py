"""The authored guarded fixtures retain conditions, effects, and failed guards."""
import copy
import hashlib
import runpy
from pathlib import Path

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer import authored_guarded_intent_panel as panel
from ipfs_datasets_py.logic.intent_ir.formalize import guarded_workflow as guarded


def graph(inputs):
    return guarded.guarded_workflow_graph(inputs["document"], inputs["context"]["state"]["workflow"], 4)


@pytest.mark.parametrize("index", [0, 1, 2])
def test_positive_fixture_retains_preconditions_effects_and_supplied_initial_values(index):
    inputs = panel.source_inputs(index)
    document = inputs["document"]
    assert document.actions[0].precondition_ids == ("pre",)
    assert document.actions[0].effect_ids == ("effect",)
    assert document.sources[0].content_sha256 == hashlib.sha256(inputs["source_text"].encode()).hexdigest()
    model = graph(inputs)
    assert model["initial_valuation_count"] == 1 and model["deadlock_free"] is True
    assert len(model["configurations"]) == 3 and model["max_abstract_steps"] == 2
    ready = next(row for row in model["configurations"] if row["phase"] == "ready")
    final = next(row for row in model["configurations"] if row["terminal"])
    assert ready["values"] == {"ready": True, "completed": False}
    assert final["values"] == {"ready": True, "completed": True}
    assert model["premises_verified"] is False and model["fairness_assumed"] is False


def test_false_precondition_is_preserved_as_deadlock_without_effect_execution():
    model = graph(panel.source_inputs(0, include_false_precondition=True))
    assert model["initial_valuation_count"] == 2 and model["deadlock_free"] is False
    assert len(model["configurations"]) == 4 and len(model["deadlocks"]) == 1
    blocked = next(row for row in model["configurations"] if row["phase"] == "ready" and row["values"]["ready"] is False)
    assert blocked["values"]["completed"] is False and not blocked["terminal"]
    assert model["deadlocks"][0]["position"] == blocked["position"]
    assert model["deadlocks"][0]["statement_ids"] == ["pre"]
    assert not any(row["from_position"] == blocked["position"] for row in model["transitions"])


def test_three_sources_are_distinct_and_builder_returns_fresh_premises():
    rows = [panel.source_inputs(index) for index in range(3)]
    assert len({row["document"].sources[0].content_sha256 for row in rows}) == 3
    assert len({row["source_text"] for row in rows}) == 3
    rows[0]["context"]["state"]["workflow"]["variables"][0]["initial_values"][:] = [False]
    assert graph(panel.source_inputs(0))["deadlock_free"] is True


@pytest.mark.parametrize("index", [True, -1, 3, "0"])
def test_fixture_scope_is_closed(index):
    with pytest.raises(ValueError, match="three authored"):
        panel.source_inputs(index)


def test_effect_binding_is_explicit_and_immutable():
    inputs = panel.source_inputs(0)
    binding = panel.effect_bindings(inputs)
    value = binding.to_dict()
    assert value["bindings"] == [{"statement_id": "effect", "expression": {"op": "eq", "variable_id": "completed", "value": True}, "evidence_ref": "source"}]
    value["bindings"][0]["expression"]["value"] = False
    assert binding.to_dict()["bindings"][0]["expression"]["value"] is True


def test_prepared_cases_keep_all_families_formulas_and_original_predicate_inputs():
    from ipfs_datasets_py.logic.formalization.autoencoder.family_training_v6 import validate_family_training_report_v6
    case = panel.prepare_case(0)
    report = case["report"]
    validate_family_training_report_v6(report, **case["source_inputs"])
    assert len(report["requested_families"]) == len(report["family_inventory"]) == 40
    assert {"intent_ir/native_formula/" + name + "/v3" for name in panel.FORMULAS} <= {row["projection_id"] for row in report["projections"]}
    assert case["fixture"]["document"]["actions"][0]["precondition_ids"] == ["pre"]
    assert case["fixture"]["document"]["actions"][0]["effect_ids"] == ["effect"]
    assert case["fixture"]["supplied_initial_values_are_modeling_assumptions"] is True
    assert case["fixture"]["source_semantics_verified"] is False
    assert case["fixture"]["heldout"] is False
    reviews = panel.applicability_reviews(report, 0)
    present = {row["logic_family"] for row in report["projections"]}
    assert not {row["family_id"] for row in reviews} & present
    assert all(row["source_digest"] == report["source_digest"] for row in reviews)


def test_negative_case_is_excluded_from_fit_split_and_retains_original_false_value():
    case = panel.prepare_case(0, include_false_precondition=True)
    assert case["fixture"]["split"] == "diagnostic"
    assert case["fixture"]["false_precondition_in_initial_domain"] is True
    assert case["fixture"]["context"]["state"]["workflow"]["variables"][0]["initial_values"] == [False, True]


def test_smoke_evidence_requires_every_projection_and_semantic_lowering():
    root = Path(__file__).resolve().parents[5]
    runner = runpy.run_path(str(root / "scripts/ops/autoencoder/smoke_guarded_intent_training.py"))
    report = {"projections": [{"projection_id": "a"}, {"projection_id": "b"}]}
    rows = [{"projection_id": name, "parser_status": "passed", "lake_status": "passed", "semantic_lowering_supported": True} for name in ("a", "b")]
    assert runner["_checks"]({"per_projection": rows}, report)
    with pytest.raises(ValueError, match="omitted"):
        runner["_checks"]({"per_projection": rows[:1]}, report)
    changed = copy.deepcopy(rows); changed[1]["semantic_lowering_supported"] = False
    assert not runner["_checks"]({"per_projection": changed}, report)
