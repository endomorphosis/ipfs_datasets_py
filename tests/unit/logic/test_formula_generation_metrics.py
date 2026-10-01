"""Free-running formula metrics must expose incomplete and actor-wrong output.

All rows below are authored test fixtures. No decoder, compiler, training,
held-out corpus or proof tool is invoked to test this accounting contract.
"""
from copy import deepcopy
import hashlib
import json

import pytest

from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_generation_metrics import (
    FACETS,
    compare_free_running_formulas,
)


def _target(identifier="agency", actor="agency"):
    return {"id": identifier, "source_text": f"The {actor} shall submit reports.",
            "canonical_ir": {"rules": [{"modality": "O", "actor": actor,
                "action": "submit", "object": "reports", "conditions": [],
                "exceptions": [], "temporal": []}]}}


def _prediction(target, *, ir=None, status="decoded"):
    ir = deepcopy(target["canonical_ir"] if ir is None else ir)
    return {"id": target["id"], "source_sha256": hashlib.sha256(
                target["source_text"].encode()).hexdigest(),
            "status": status, "canonical_ir": ir, "teacher_forcing": False,
            "target_access": False, "formula_text": "O(agency,submit,reports)",
            "formal_outputs": [{"family": "deontic", "format": "typed-deontic-rule/v1",
                "payload": deepcopy(rule), "formula_text": "display only",
                "origin": "learned_latent_conditioned_formula_decoder"}
                for rule in ir["rules"]]}


def _report(*rows, **fields):
    return {"schema": "modal-latent-formula-inference/v1", "rows": list(rows), **fields}


def _replace(prediction, facet, value):
    prediction["canonical_ir"]["rules"][0][facet] = value
    prediction["formal_outputs"][0]["payload"][facet] = deepcopy(value)


def test_complete_exact_report_with_optional_envelope_flags_grants_no_authority():
    target = _target()
    prediction = _prediction(target)
    report = _report(prediction, decoded_count=1)
    before = deepcopy((report, [target]))
    result = compare_free_running_formulas(report, [target], partition="evaluation")

    assert result["valid_evaluation"]
    assert result["operational_complete"]
    assert result["all_targets_decoded"]
    assert result["exact_reconstruction"] == {"matched": 1, "total": 1,
                                               "fraction": 1.0, "complete": True}
    assert result["rule_count_exact"] == {"matched": 1, "total": 1, "fraction": 1.0}
    assert all(value["matched"] == 1 for value in result["facets"].values())
    assert result["target_origin"] == "caller_supplied_compiler_weak_labels"
    assert result["teacher_forcing"] is False
    assert result["metric_target_access"] is True
    assert result["generation_declarations_verified"]
    for field in ("qualified", "admitted", "formalized", "roundtrip_ok", "proof_authority",
                  "semantic_correctness_verified", "heldout_fidelity_verified",
                  "independent_validation", "lake_executed", "promotion_performed",
                  "publication_performed", "training_executed", "target_origin_verified",
                  "partition_membership_verified", "generation_declarations_are_independent_proof"):
        assert result[field] is False, field
    assert (report, [target]) == before
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(("facet", "replacement"), [
    ("modality", "F"), ("actor", "officer"), ("action", "retain"),
    ("object", "records"), ("conditions", ["requested"]),
    ("exceptions", ["emergency"]), ("temporal", ["within_10_days"]),
])
def test_each_facet_must_match_even_with_low_loss_and_successful_syntax(facet, replacement):
    target = _target()
    prediction = _prediction(target)
    _replace(prediction, facet, replacement)
    prediction.update(family_syntax_checked=True, teacher_forced_loss=0.00001)
    result = compare_free_running_formulas(_report(prediction,
        syntax_passed=True, loss=0.0), [target])

    assert result["valid_evaluation"] and result["operational_complete"]
    assert result["exact_reconstruction"]["matched"] == 0
    assert not result["exact_reconstruction"]["complete"]
    assert result["facets"][facet] == {"matched": 0, "total": 1, "fraction": 0.0}
    assert all(result["facets"][other]["matched"] == 1 for other in FACETS if other != facet)
    assert result["syntax_checks_contribute_to_exact_match"] is False
    assert result["teacher_forced_losses_contribute_to_exact_match"] is False
    if facet == "actor":
        assert result["actor_confusions"] == [{"expected": ["agency"],
                                               "predicted": ["officer"], "count": 1}]


def test_missing_predictions_keep_full_requested_denominator():
    targets = [_target(), _target("officer", "officer")]
    result = compare_free_running_formulas(_report(_prediction(targets[0])), targets)
    assert not result["valid_evaluation"]
    assert not result["generation_declarations_verified"]
    assert result["coverage"]["missing_ids"] == ["officer"]
    assert result["counts"]["missing"] == 1
    assert result["exact_reconstruction"] == {"matched": 1, "total": 2,
                                               "fraction": 0.5, "complete": False}
    assert all(value["total"] == 2 for value in result["facets"].values())


def test_empty_prediction_report_is_missing_data_not_an_empty_success():
    result = compare_free_running_formulas(_report(), [_target()])
    assert result["counts"]["missing"] == 1
    assert result["exact_reconstruction"]["fraction"] == 0.0
    assert not result["valid_evaluation"]


def test_duplicate_ids_never_select_a_favorable_occurrence():
    target = _target()
    correct, wrong = _prediction(target), _prediction(target)
    _replace(wrong, "actor", "officer")
    for rows in ([correct, wrong], [wrong, correct], [correct, correct]):
        result = compare_free_running_formulas(_report(*rows), [target])
        assert not result["valid_evaluation"]
        assert result["coverage"]["duplicate_ids"] == {"agency": 2}
        assert result["counts"]["duplicate"] == 1
        assert result["exact_reconstruction"]["matched"] == 0


def test_extra_and_invalid_id_rows_invalidate_otherwise_correct_output():
    target = _target()
    result = compare_free_running_formulas(_report(_prediction(target),
        _prediction(_target("unexpected")), {"id": ""}, None), [target])
    assert not result["valid_evaluation"]
    assert result["coverage"]["unexpected_ids"] == ["unexpected"]
    assert result["coverage"]["invalid_id_row_indices"] == [2, 3]
    assert result["exact_reconstruction"] == {"matched": 1, "total": 1,
                                               "fraction": 1.0, "complete": False}


@pytest.mark.parametrize("field", ["teacher_forcing", "target_access"])
@pytest.mark.parametrize("value", [True, None, 0, "false", "missing"])
def test_row_generation_declarations_are_required_literal_false(field, value):
    target = _target()
    prediction = _prediction(target)
    if value == "missing":
        prediction.pop(field)
    else:
        prediction[field] = value
    result = compare_free_running_formulas(_report(prediction), [target])
    assert not result["valid_evaluation"]
    assert result["counts"]["unverifiable_generation"] == 1
    assert result["exact_reconstruction"]["matched"] == 0


@pytest.mark.parametrize("field", ["teacher_forcing", "target_access"])
def test_contradictory_report_declaration_invalidates_exact_rows(field):
    target = _target()
    result = compare_free_running_formulas(_report(_prediction(target), **{field: True}), [target])
    assert not result["valid_evaluation"]
    assert result["counts"]["unverifiable_generation"] == 1
    assert result["envelope_issues"] == ["report_" + field + "_not_false"]


def test_source_hash_binding_prevents_relabeling_a_prediction():
    target = _target()
    prediction = _prediction(target)
    target["source_text"] = "The agency shall not submit reports."
    result = compare_free_running_formulas(_report(prediction), [target])
    assert not result["valid_evaluation"]
    assert result["counts"]["unverifiable_generation"] == 1
    assert result["exact_reconstruction"]["matched"] == 0


@pytest.mark.parametrize("claimed", [0, 2, True, "1"])
def test_reported_decoded_count_must_match_rows(claimed):
    target = _target()
    result = compare_free_running_formulas(_report(_prediction(target),
                                                  decoded_count=claimed), [target])
    assert not result["valid_evaluation"]
    assert result["exact_reconstruction"]["complete"] is False
    assert result["envelope_issues"] == ["reported_decoded_count_disagrees_with_rows"]


def test_abstention_is_complete_operation_and_zero_reconstruction():
    target = _target()
    prediction = _prediction(target)
    prediction.update(status="abstained", canonical_ir=None,
                      formal_outputs=[], formula_text=None)
    result = compare_free_running_formulas(_report(prediction, decoded_count=0), [target])
    assert result["valid_evaluation"] and result["operational_complete"]
    assert not result["all_targets_decoded"]
    assert result["counts"]["abstained"] == 1
    assert result["exact_reconstruction"]["fraction"] == 0.0


def test_abstention_with_formula_and_decoded_without_formula_are_malformed():
    target = _target()
    contradictory = _prediction(target, status="abstained")
    empty = _prediction(target)
    empty.update(canonical_ir=None, formal_outputs=[])
    for prediction in (contradictory, empty):
        result = compare_free_running_formulas(_report(prediction), [target])
        assert result["valid_evaluation"]
        assert not result["operational_complete"]
        assert result["counts"]["malformed"] == 1
        assert result["counts"]["abstained"] == 0
        assert result["exact_reconstruction"]["matched"] == 0


@pytest.mark.parametrize("damage", ["missing_actor", "extra_facet", "empty_rules",
                                  "unrecognized_modality", "unsorted_qualifiers",
                                  "payload_disagreement", "missing_output"])
def test_malformed_formulas_and_conflicting_formal_outputs_receive_no_credit(damage):
    target = _target()
    prediction = _prediction(target)
    rule = prediction["canonical_ir"]["rules"][0]
    if damage == "missing_actor":
        rule.pop("actor")
    elif damage == "extra_facet":
        rule["uninterpreted"] = "ignored actor"
    elif damage == "empty_rules":
        prediction["canonical_ir"]["rules"] = []
    elif damage == "unrecognized_modality":
        rule["modality"] = "obligation"
    elif damage == "unsorted_qualifiers":
        rule["conditions"] = ["z", "a"]
    elif damage == "payload_disagreement":
        prediction["formal_outputs"][0]["payload"]["actor"] = "officer"
    elif damage == "missing_output":
        prediction["formal_outputs"] = []
    result = compare_free_running_formulas(_report(prediction), [target])
    assert result["counts"]["malformed"] == 1
    assert not result["operational_complete"]
    assert result["exact_reconstruction"]["matched"] == 0


def test_rule_counts_and_order_are_exact_no_partial_rule_credit():
    target = _target()
    target["canonical_ir"]["rules"].append(_target("officer", "officer")["canonical_ir"]["rules"][0])
    one = deepcopy(target["canonical_ir"])
    one["rules"].pop()
    result = compare_free_running_formulas(_report(_prediction(target, ir=one)), [target])
    assert result["rule_count_exact"]["matched"] == 0
    assert result["rows"][0]["predicted_rule_count"] == 1
    assert result["rows"][0]["target_rule_count"] == 2
    assert all(value["matched"] == 0 for value in result["facets"].values())

    swapped = {"rules": list(reversed(target["canonical_ir"]["rules"]))}
    result = compare_free_running_formulas(_report(_prediction(target, ir=swapped)), [target])
    assert result["rule_count_exact"]["matched"] == 1
    assert result["facets"]["actor"]["matched"] == 0
    assert not result["exact_reconstruction"]["complete"]


def test_collapse_and_cross_target_matches_are_diagnostics_not_copying_proof():
    first, second = _target(), _target("officer", "officer")
    predictions = [_prediction(first), _prediction(second, ir=first["canonical_ir"])]
    predictions[1]["formula_text"] = second["source_text"]
    result = compare_free_running_formulas(_report(*predictions), [first, second])
    diagnostics = result["diagnostics"]
    assert result["exact_reconstruction"]["fraction"] == 0.5
    assert diagnostics["single_formula_collapse"]
    assert diagnostics["single_actor_collapse"]
    assert diagnostics["cross_target_matches"] == [{"id": "officer",
                                                     "matching_other_target_ids": ["agency"]}]
    assert diagnostics["formula_display_copies_source_ids"] == ["officer"]
    assert diagnostics["similarity_anomalies_prove_target_copying"] is False


def test_explicit_empty_object_is_valid_and_display_text_is_not_authoritative():
    target = _target()
    target["canonical_ir"]["rules"][0]["object"] = ""
    prediction = _prediction(target)
    prediction["formula_text"] = "This display text is irrelevant to exact AST equality."
    result = compare_free_running_formulas(_report(prediction), [target])
    assert result["exact_reconstruction"]["complete"]


@pytest.mark.parametrize("damage", ["duplicate_ids", "unknown_field", "no_rows", "missing_actor",
                                  "noncanonical_qualifiers", "missing_source"])
def test_invalid_or_open_targets_are_rejected(damage):
    targets = [_target()]
    if damage == "duplicate_ids":
        targets.append(deepcopy(targets[0]))
    elif damage == "unknown_field":
        targets[0]["is_heldout"] = True
    elif damage == "no_rows":
        targets.clear()
    elif damage == "missing_actor":
        del targets[0]["canonical_ir"]["rules"][0]["actor"]
    elif damage == "noncanonical_qualifiers":
        targets[0]["canonical_ir"]["rules"][0]["conditions"] = ["x", "x"]
    elif damage == "missing_source":
        del targets[0]["source_text"]
    with pytest.raises(ValueError):
        compare_free_running_formulas(_report(), targets)
