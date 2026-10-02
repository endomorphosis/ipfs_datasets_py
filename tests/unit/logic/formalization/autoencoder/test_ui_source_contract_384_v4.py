"""Finite guard semantics retain false cases and never infer timing or updates."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import ui_source_contract_384_v4 as subject
from ipfs_datasets_py.logic.formalization.autoencoder import ui_source_contract_384_v3 as previous
from ipfs_datasets_py.logic.formalization.autoencoder import native_ui_guarded_lean as guarded


def cases():
    path = Path(__file__).resolve().parents[4] / "fixtures/logic/native_dcec_ui_v1/guard_cases.py"
    spec = importlib.util.spec_from_file_location("ui_guard_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.cases()


def prepare(row):
    return subject.prepare_family_targets(row["source_text"], row["candidate"], **row["options"])


def changed_declaration(row, change):
    row = deepcopy(row)
    value = row["options"]["guard_interpretation"].to_dict()
    change(value)
    row["options"]["guard_interpretation"] = subject.UIGuardInterpretation.from_dict(value)
    return row


def test_true_and_false_initial_values_change_reachability_without_erasing_guard_cases():
    true, false = [prepare(row) for row in cases()[:2]]
    for result in (true, false):
        report = result["report"]
        assert len(report["requested_families"]) == 40
        assert result["audit"]["available_families"] == ["first_order", "frame_logic", "transition_system"]
        assert len(result["audit"]["missing_requested_families"]) == 37
        assert len(report["projections"]) == 5
        ec = next(row for row in report["projections"] if row["logic_family"] == "event_calculus")
        assert ec["ready_for_training"] is False
        payload = report["projections"][-1]["payload"]
        assert {row["enabled"] for row in payload["truth_table"]} == {True, False}
        assert len(payload["enabled_edges"]) == 1
        assert payload["bounded_tla"]["model_checker_executed"] is False
        subject.validate_family_training_report(report, **result["source_inputs"])
    assert true["audit"]["reachable_nonterminal_deadlocks"] == []
    assert false["audit"]["reachable_nonterminal_deadlocks"] == ["open"]
    assert true["report"]["source_digest"] != false["report"]["source_digest"]


def test_compound_guard_truth_table_and_both_native_routes_replay():
    row = cases()[2]
    result = prepare(row)
    assert result["audit"]["guarded_truth_table_rows"] == 4
    assert result["audit"]["guarded_enabled_edges"] == 1
    for projection in result["report"]["projections"]:
        if not projection["projection_id"].startswith(guarded.PREFIX): continue
        source, checks = guarded.emit_projection(projection, report=result["report"])
        assert "= false := by decide" in source and "= true := by decide" in source
        assert "has no expanded native successor" in source
        assert "frozen_parameter_frame" in checks["operators"]
        assert checks["source_semantics_verified"] is False
        assert len(checks["syntax_requirements"]) == (projection["profile"] == "tla_plus")
        assert checks["enabled_edge_count"] == 1
    assert subject.validate_prepared(result, row["source_text"], row["candidate"], **row["options"])


def test_no_guard_declaration_preserves_entire_old_preparation_and_failures():
    row = cases()[0]
    options = {"behavior_interpretation": row["options"]["behavior_interpretation"]}
    assert subject.prepare_family_targets(row["source_text"], row["candidate"], **options) == previous.prepare_family_targets(
        row["source_text"], row["candidate"], **options)


@pytest.mark.parametrize("index,reason", [(3, "clock semantics"), (4, "binding differs")])
def test_timeout_and_binding_mismatch_are_blocked_with_candidate_retained(index, reason):
    row = cases()[index]
    with pytest.raises(ValueError, match=reason): prepare(row)
    result = subject.qualify_source_candidate(row["source_text"], row["candidate"], **row["options"])
    assert result["candidate"] == row["candidate"] and result["candidate_rewritten"] is False
    assert result["status"] == "invalid_or_missing_context"


@pytest.mark.parametrize("change,reason", [
    (lambda v: v["variables"][0].pop("initial_value"), "complete explicit"),
    (lambda v: v["variables"][0].update(initial_value=1), "Boolean type"),
    (lambda v: v.update(parameter_update_semantics="may_change"), "persistence"),
    (lambda v: v.update(max_steps=True), "step count"),
    (lambda v: v["guards"][0].update(expression={"op": "eval", "code": "True"}), "unsupported Boolean"),
    (lambda v: v["guards"][0].update(expression={"op": "variable", "variable_id": "unknown"}), "declared Boolean"),
    (lambda v: v["guards"].append(deepcopy(v["guards"][0])), "unique explicit"),
])
def test_closed_interpretations_reject_implicit_or_untyped_fields(change, reason):
    with pytest.raises(ValueError, match=reason): changed_declaration(cases()[0], change)


def test_complete_native_guard_and_exhaustive_boolean_outputs_are_bound():
    row = changed_declaration(cases()[0], lambda v: v["guards"][0]["native_guard"].update(constraint_ref="closed"))
    with pytest.raises(ValueError, match="native UI guard record differs"): prepare(row)
    result = prepare(cases()[0])
    projection = deepcopy(next(row for row in result["report"]["projections"] if row["projection_id"].startswith(guarded.PREFIX)))
    projection["payload"]["truth_table"] = [row for row in projection["payload"]["truth_table"] if row["enabled"]]
    with pytest.raises(ValueError, match="binding"): guarded.emit_projection(projection, report=result["report"])
    original = next(row for row in result["report"]["projections"] if row["projection_id"].startswith(guarded.PREFIX))
    with pytest.raises(ValueError, match="live report"): guarded.emit_projection(original)


def test_no_outgoing_action_is_fabricated_for_globally_false_guard():
    row = changed_declaration(cases()[0], lambda v: v["guards"][0].update(expression={"op": "and", "args": [
        {"op": "variable", "variable_id": "allowed"}, {"op": "not", "arg": {"op": "variable", "variable_id": "allowed"}}]}))
    with pytest.raises(ValueError, match="no edge or stutter fabricated"): prepare(row)


def test_frozen_parameters_are_read_only_and_initial_values_exact():
    result = prepare(cases()[0])
    native = next(row["payload"]["native_state"] for row in result["report"]["projections"]
                  if row["projection_id"].startswith(guarded.PREFIX))
    assert all(row["frame"]["writes"] == ["var:ui-control"] for row in native["actions"])
    initial = next(row for row in native["predicates"] if row["role"] == "initial")
    assert initial["expression"]["var:ui-param:0"] is True


def test_reduced_request_explicitly_changes_denominator_without_fake_guard_route():
    row = cases()[0]
    result = subject.prepare_family_targets(row["source_text"], row["candidate"],
        requested_families=("first_order", "frame_logic"), **row["options"])
    assert result["report"]["requested_families"] == ["first_order", "frame_logic"]
    assert result["audit"]["guarded_state_route_available"] is False
    assert not any(p["projection_id"].startswith(guarded.PREFIX) for p in result["report"]["projections"])


@pytest.mark.parametrize("tamper", ["domain", "source", "detach"])
def test_emitter_requires_exact_live_report_binding(tamper):
    result = prepare(cases()[0])
    report = deepcopy(result["report"])
    row = next(row for row in report["projections"] if row["projection_id"].startswith(guarded.PREFIX))
    if tamper == "domain": report["domain_id"] = "intent_ir"
    elif tamper == "source": row["source_digest"] = "0" * 64
    else: report["projections"].remove(row)
    with pytest.raises(ValueError, match="live report"): guarded.emit_projection(row, report=report)


def test_rehashed_disabled_case_removal_still_fails_original_source_replay():
    from ipfs_datasets_py.logic.formalization.autoencoder import family_training as core
    result = prepare(cases()[0])
    report = deepcopy(result["report"])
    row = next(row for row in report["projections"] if row["projection_id"].startswith(guarded.PREFIX))
    row["payload"]["truth_table"] = [x for x in row["payload"]["truth_table"] if x["enabled"]]
    row["target_sha256"] = core._sha({k: v for k, v in row.items() if k != "target_sha256"})
    report["report_sha256"] = core._sha({k: v for k, v in report.items() if k != "report_sha256"})
    with pytest.raises(ValueError, match="exact UI guarded source replay"):
        guarded.emit_projection(row, report=report)


def test_decoded_interpretation_mutation_does_not_mutate_immutable_declaration():
    row = cases()[0]
    declaration = row["options"]["guard_interpretation"]
    decoded = declaration.to_dict()
    decoded["variables"][0]["initial_value"] = False
    assert declaration.to_dict()["variables"][0]["initial_value"] is True


def test_explicit_capacity_is_an_error_instead_of_pruning_boolean_parameters():
    value = cases()[0]["options"]["guard_interpretation"].to_dict()
    value["variables"] = [{"variable_id": "x" + str(i), "type": "boolean", "initial_value": False} for i in range(5)]
    with pytest.raises(ValueError, match="four explicit"): subject.UIGuardInterpretation.from_dict(value)


def test_original_failure_payload_and_validation_are_unchanged_after_additive_guard_route():
    row = cases()[0]
    before = previous.prepare_family_targets(row["source_text"], row["candidate"],
        behavior_interpretation=row["options"]["behavior_interpretation"])
    after = prepare(row)
    old = next(p for p in before["report"]["projections"] if p["logic_family"] == "event_calculus")
    new = next(p for p in after["report"]["projections"] if p["logic_family"] == "event_calculus")
    for field in ("payload", "validation", "ready_for_training", "qualification_gaps", "projection_id"):
        assert old[field] == new[field]
    assert after["report"]["frontier"] == before["report"]["frontier"]
