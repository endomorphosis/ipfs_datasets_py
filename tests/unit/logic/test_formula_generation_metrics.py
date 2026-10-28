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




# These 632 occurrences are authored accounting fixtures, not retained data.
def _f18_matched_fixture():
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_generation_metrics import (
        compare_f18_frozen_matched_arms,
    )
    sizes = {"train": 168, "old_tune": 64, **{"other_" + str(i): 56 for i in range(7)}, "law": 8}
    expected, targets, hashes, source = {}, {}, {}, {}
    for panel, size in sizes.items():
        expected[panel], targets[panel], source[panel] = [], [], []
        for index in range(size):
            key = panel + ":" + str(index)
            target = _target(key, key)
            if panel == "old_tune" and index < 32:
                target["canonical_ir"]["rules"][0]["modality"] = "P"
            if panel == "train" and index < 72:
                target["canonical_ir"]["rules"][0]["conditions"] = ["condition"]
            expected[panel].append(key)
            source[panel].append(target)
            hashes[key] = hashlib.sha256(target["source_text"].encode()).hexdigest()
            if panel != "law":
                targets[panel].append(deepcopy(target))

    arms = {}
    for arm in ("parent", "coefficient_0", "coefficient_025"):
        arms[arm] = []
        for panel, rows in source.items():
            chunks, joint = [], []
            for start in range(0, len(rows), 128):
                selected = rows[start:start + 128]
                predictions = [_prediction(row) for row in selected]
                for prediction in predictions:
                    prediction.pop("id")
                chunks.append({"schema": "conditions-fullspan-four-tensor-target-free-head-capture/v1",
                    "inference": {"rows": predictions, "decoded_count": len(predictions),
                                  "target_access": False, "teacher_forcing": False},
                    "occurrences": [{"id": row["id"], "source_sha256": hashes[row["id"]], "scores": None}
                                    for row in selected],
                    "actual_source_forwards": len(selected), "extra_capture_forwards": 0,
                    "target_access": False, "teacher_forcing": False})
            if arm == "parent":
                raw = {"schema": "modality-conditions-retention-adapter-target-free-head-capture/v1",
                    "inference": {"rows": [row for chunk in chunks for row in chunk["inference"]["rows"]],
                                  "decoded_count": len(rows), "teacher_forcing": False, "target_access": False},
                    "occurrences": [row for chunk in chunks for row in chunk["occurrences"]],
                    "actual_source_forwards": len(rows), "source_model_forwards": len(rows),
                    "extra_capture_forwards": 0, "target_access": False, "teacher_forcing": False}
            else:
                raw = {"schema": "f18-paired-target-free-panel/v1", "panel": panel, "rows": len(rows),
                       "chunks": chunks, "source_model_forwards": len(rows), "target_access": False, "teacher_forcing": False}
            for row in rows:
                result = _prediction(row)
                result.pop("id")
                result["status"] = "selected"
                joint.append({"id": row["id"], "result": result})
            arms[arm].append({"panel": panel, "raw": raw, "joint": {
                "schema": "modality-conditions-retention-joint-panel/v1", "rows": joint,
                "top_k": 8, "max_search_nodes": 50000, "reference_scoring_performed": False}})
    return compare_f18_frozen_matched_arms, arms, targets, {
        "expected_ids": expected, "expected_source_sha256": hashes,
        "retention_ids": expected["train"][:72], "permission_ids": expected["old_tune"][:32],
        "unscored_ids": expected["law"][:]}


def _f18_fixture_prediction(arms, arm, mode, panel=0, row=0):
    value = arms[arm][panel][mode]
    if mode == "joint":
        return value["rows"][row]["result"]
    if arm == "parent":
        return value["inference"]["rows"][row]
    for chunk in value["chunks"]:
        if row < len(chunk["inference"]["rows"]):
            return chunk["inference"]["rows"][row]
        row -= len(chunk["inference"]["rows"])
    raise AssertionError("fixture row absent")


def test_f18_matched_panels_keep_every_source_and_target_denominator_without_authority():
    compare, arms, targets, options = _f18_matched_fixture()
    before = deepcopy((arms, targets, options))
    result = compare(arms, targets, **options)
    assert result["valid_evaluation"]
    assert result["expected_source_count"] == 632 and result["weak_label_target_count"] == 624
    assert len(result["panels"]) == 30
    for arm in ("parent", "coefficient_0", "coefficient_025"):
        for mode in ("raw", "joint"):
            assert result["arms"][arm][mode]["exact_reconstruction"]["matched"] == 624
            assert result["arms"][arm][mode]["exact_reconstruction"]["total"] == 624
            assert result["permission_counts"][mode][arm] == {"matched": 32, "total": 32, "fraction": 1.0}
    for mode in ("raw", "joint"):
        assert len(result["retention"][mode]) == 72
        assert all(row["parent_to_coefficient_025"] == "retained" for row in result["retention"][mode])
        assert len(result["permission_decisions"][mode]) == 32
    for flag in ("qualified", "admitted", "formalized", "semantic_correctness_verified", "training_executed",
                 "source_commitment_origin_verified", "target_origin_verified", "freeze_timing_verified",
                 "roster_membership_verified", "retained_other_comparator_no_loss_gate_evaluated"):
        assert result[flag] is False
    assert result["parent_relative_only"] is True
    assert (arms, targets, options) == before
    assert compare(arms, targets, **options) == result
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("damage", ["missing_panel", "panel_order", "raw_schema", "chunk_schema", "joint_envelope",
                                  "inference_occurrence_length", "target_missing", "target_duplicate", "source_map_missing",
                                  "source_map_invalid", "target_source_conflict", "expected_duplicate", "permission_31",
                                  "permission_duplicate", "permission_not_target_p", "permission_multi_rule_target", "retention_71",
                                  "retention_conditions_absent"])
def test_f18_closed_rosters_and_envelopes_refuse_structural_ambiguity(damage):
    compare, arms, targets, options = _f18_matched_fixture()
    raw = arms["coefficient_025"][0]["raw"]
    if damage == "missing_panel":
        arms["coefficient_025"].pop()
    elif damage == "panel_order":
        arms["coefficient_025"][:2] = reversed(arms["coefficient_025"][:2])
    elif damage == "raw_schema":
        raw["schema"] = "unrecognized"
    elif damage == "chunk_schema":
        raw["chunks"][0]["schema"] = "unrecognized"
    elif damage == "joint_envelope":
        arms["coefficient_025"][0]["joint"]["rows"][0]["ignored"] = True
    elif damage == "inference_occurrence_length":
        raw["chunks"][0]["occurrences"].pop()
    elif damage == "target_missing":
        targets["train"].pop()
    elif damage == "target_duplicate":
        targets["train"][1] = deepcopy(targets["train"][0])
    elif damage == "source_map_missing":
        options["expected_source_sha256"].pop(options["unscored_ids"][0])
    elif damage == "source_map_invalid":
        options["expected_source_sha256"][options["unscored_ids"][0]] = "x" * 64
    elif damage == "target_source_conflict":
        targets["train"][0]["source_text"] += " changed"
    elif damage == "expected_duplicate":
        options["expected_ids"]["train"][1] = options["expected_ids"]["train"][0]
    elif damage == "permission_31":
        options["permission_ids"].pop()
    elif damage == "permission_duplicate":
        options["permission_ids"][1] = options["permission_ids"][0]
    elif damage == "permission_not_target_p":
        options["permission_ids"][0] = options["expected_ids"]["train"][0]
    elif damage == "permission_multi_rule_target":
        targets["old_tune"][0]["canonical_ir"]["rules"].append(deepcopy(targets["old_tune"][0]["canonical_ir"]["rules"][0]))
    elif damage == "retention_71":
        options["retention_ids"].pop()
    elif damage == "retention_conditions_absent":
        options["retention_ids"][0] = options["expected_ids"]["train"][100]
    with pytest.raises(ValueError):
        compare(arms, targets, **options)


@pytest.mark.parametrize("damage", ["missing", "duplicate", "invalid_list_id", "invalid_dict_id", "raw_source_hash",
                                  "occurrence_source_hash", "unscored_cross_arm_source_hash", "unscored_generation_flag",
                                  "report_generation_flag", "nested_generation_flag", "raw_count", "decoded_count"])
def test_f18_all_source_integrity_failures_remain_visible_without_favorable_selection(damage):
    compare, arms, targets, options = _f18_matched_fixture()
    raw, joint = arms["coefficient_025"][0]["raw"], arms["coefficient_025"][0]["joint"]
    if damage == "missing":
        joint["rows"].pop()
    elif damage == "duplicate":
        joint["rows"][1]["id"] = joint["rows"][0]["id"]
        _replace(joint["rows"][1]["result"], "actor", "wrong")
    elif damage in ("invalid_list_id", "invalid_dict_id"):
        joint["rows"][0]["id"] = [] if damage == "invalid_list_id" else {}
    elif damage == "raw_source_hash":
        raw["chunks"][0]["inference"]["rows"][0]["source_sha256"] = "a" * 64
    elif damage == "occurrence_source_hash":
        raw["chunks"][0]["occurrences"][0]["source_sha256"] = "a" * 64
    elif damage == "unscored_cross_arm_source_hash":
        law = arms["coefficient_025"][-1]
        law["raw"]["chunks"][0]["occurrences"][0]["source_sha256"] = "a" * 64
        law["raw"]["chunks"][0]["inference"]["rows"][0]["source_sha256"] = "a" * 64
        law["joint"]["rows"][0]["result"]["source_sha256"] = "a" * 64
    elif damage == "unscored_generation_flag":
        _f18_fixture_prediction(arms, "coefficient_025", "joint", panel=9)["target_access"] = True
    elif damage == "report_generation_flag":
        raw["teacher_forcing"] = True
    elif damage == "nested_generation_flag":
        raw["chunks"][0]["inference"]["target_access"] = True
    elif damage == "raw_count":
        raw["rows"] -= 1
    elif damage == "decoded_count":
        raw["chunks"][0]["inference"]["decoded_count"] -= 1
    result = compare(arms, targets, **options)
    assert result["valid_evaluation"] is False
    assert result["arms"]["coefficient_025"]["joint"]["exact_reconstruction"]["total"] == 624
    assert result["arms"]["coefficient_025"]["raw"]["exact_reconstruction"]["total"] == 624
    if damage == "duplicate":
        item = result["arms"]["coefficient_025"]["joint"]["rows"][0]
        assert item["status"] == "duplicate" and item["exact"] is False
    assert len(result["permission_decisions"]["joint"]) == 32


def test_f18_equal_aggregate_gains_do_not_hide_casewise_retention_losses():
    compare, arms, targets, options = _f18_matched_fixture()
    for mode in ("raw", "joint"):
        _replace(_f18_fixture_prediction(arms, "parent", mode, row=0), "actor", "wrong-parent")
        _replace(_f18_fixture_prediction(arms, "coefficient_0", mode, row=0), "actor", "wrong-control")
        _replace(_f18_fixture_prediction(arms, "coefficient_025", mode, row=1), "conditions", ["wrong-condition"])
    result = compare(arms, targets, **options)
    assert result["valid_evaluation"] is True
    for mode in ("raw", "joint"):
        assert result["arms"]["coefficient_0"][mode]["exact_reconstruction"]["matched"] == 623
        assert result["arms"]["coefficient_025"][mode]["exact_reconstruction"]["matched"] == 623
        rows = result["retention"][mode]
        assert rows[0]["coefficient_0_to_coefficient_025"] == "gained"
        assert rows[1]["coefficient_0_to_coefficient_025"] == "lost"
        assert rows[1]["facets"]["conditions"]["parent_to_coefficient_025"] == "lost"
        assert all(rows[1]["facets"][facet]["parent_to_coefficient_025"] == "retained"
                   for facet in FACETS if facet != "conditions")


@pytest.mark.parametrize("kind", ["modality_loss", "extra_rule", "abstention"])
def test_f18_all_32_permission_decisions_include_lost_extra_rule_and_abstained_cases(kind):
    compare, arms, targets, options = _f18_matched_fixture()
    for mode in ("raw", "joint"):
        row = _f18_fixture_prediction(arms, "coefficient_025", mode, panel=1)
        if kind == "modality_loss":
            _replace(row, "modality", "O")
        elif kind == "extra_rule":
            extra = deepcopy(row["canonical_ir"]["rules"][0])
            extra["modality"] = "O"
            row["canonical_ir"]["rules"].append(extra)
            row["formal_outputs"].append({"family": "deontic", "format": "typed-deontic-rule/v1", "payload": deepcopy(extra)})
        else:
            row.update(status="abstained", canonical_ir=None, formal_outputs=[], formula_text=None)
            if mode == "raw":
                arms["coefficient_025"][1]["raw"]["chunks"][0]["inference"]["decoded_count"] -= 1
    result = compare(arms, targets, **options)
    assert result["valid_evaluation"]
    for mode in ("raw", "joint"):
        assert len(result["permission_decisions"][mode]) == 32
        decision = result["permission_decisions"][mode][0]["arms"]["coefficient_025"]
        assert decision["permission_retained"] is False and decision["full_ir_exact"] is False
        assert result["permission_counts"][mode]["coefficient_025"] == {"matched": 31, "total": 32, "fraction": 31 / 32}
        if kind == "extra_rule":
            assert decision["predicted_modalities"] == ["P", "O"]
        elif kind == "abstention":
            assert decision["status"] == "abstained" and decision["predicted_modalities"] is None


# The joint producer's selected/abstained route is distinct from raw decoding.
@pytest.mark.parametrize("damage", ["decoded", "unknown", "missing", "boolean", "list"])
def test_f18_joint_producer_status_cannot_borrow_exact_IR_or_permission_credit(damage):
    compare, arms, targets, options = _f18_matched_fixture()
    target = targets["old_tune"][31]
    prediction = _f18_fixture_prediction(arms, "coefficient_025", "joint", panel=1, row=31)
    # All seven facets are exact, including P: only producer provenance is bad.
    assert set(prediction["canonical_ir"]["rules"][0]) == set(FACETS)
    assert prediction["canonical_ir"] == target["canonical_ir"]
    assert prediction["formal_outputs"][0]["payload"] == target["canonical_ir"]["rules"][0]
    if damage == "missing":
        prediction.pop("status")
    else:
        prediction["status"] = {
            "decoded": "decoded", "unknown": "unknown_producer_status",
            "boolean": True, "list": [],
        }[damage]
    before = deepcopy((arms, targets, options))
    result = compare(arms, targets, **options)
    assert (arms, targets, options) == before
    assert result["valid_evaluation"] is False
    panel = next(row for row in result["panels"]
                 if row["arm"] == "coefficient_025" and row["panel"] == "old_tune")
    assert panel["joint"]["source_coverage"]["valid"] is True
    assert panel["joint"]["source_integrity_valid"] is False
    assert panel["raw"]["source_integrity_valid"] is True
    raw, joint = result["arms"]["coefficient_025"]["raw"], result["arms"]["coefficient_025"]["joint"]
    assert raw["valid_evaluation"] is True and raw["exact_reconstruction"]["matched"] == 624
    assert joint["valid_evaluation"] is False and joint["exact_reconstruction"]["matched"] == 0
    diagnostic = next(row for row in joint["rows"] if row["id"] == target["id"])
    assert diagnostic["exact"] is False and all(value is False for value in diagnostic["facets"].values())
    decisions = result["permission_decisions"]["joint"]
    assert len(decisions) == 32 and decisions[31]["id"] == target["id"]
    assert decisions[31]["arms"]["coefficient_025"]["permission_retained"] is False
    assert decisions[31]["arms"]["coefficient_025"]["full_ir_exact"] is False
    assert decisions[31]["arms"]["coefficient_025"]["predicted_modalities"] is None
    assert result["permission_counts"]["joint"]["coefficient_025"]["matched"] == 0
    assert result["permission_counts"]["raw"]["coefficient_025"]["matched"] == 32
    assert result["permission_counts"]["joint"]["parent"]["matched"] == 32
    assert result["permission_counts"]["joint"]["coefficient_0"]["matched"] == 32


def test_f18_honest_joint_abstention_is_valid_but_loses_last_permission_and_full_IR():
    compare, arms, targets, options = _f18_matched_fixture()
    target = targets["old_tune"][31]
    prediction = _f18_fixture_prediction(arms, "coefficient_025", "joint", panel=1, row=31)
    prediction.update(status="abstained", canonical_ir=None, formal_outputs=[], formula_text=None)
    before = deepcopy((arms, targets, options))
    result = compare(arms, targets, **options)
    assert (arms, targets, options) == before
    assert result["valid_evaluation"] is True
    joint = result["arms"]["coefficient_025"]["joint"]
    assert joint["operational_complete"] is True and joint["all_targets_decoded"] is False
    assert joint["counts"]["abstained"] == 1 and joint["exact_reconstruction"]["matched"] == 623
    decisions = result["permission_decisions"]["joint"]
    assert len(decisions) == 32 and decisions[31]["id"] == target["id"]
    decision = decisions[31]["arms"]["coefficient_025"]
    assert decision == {"status": "abstained", "predicted_modalities": None,
                        "permission_retained": False, "full_ir_exact": False}
    assert all(row["arms"]["coefficient_025"]["permission_retained"] is True for row in decisions[:31])
    assert result["permission_counts"]["joint"]["coefficient_025"] == {
        "matched": 31, "total": 32, "fraction": 31 / 32}
    assert result["permission_counts"]["raw"]["coefficient_025"]["matched"] == 32
    assert result["arms"]["coefficient_025"]["raw"]["exact_reconstruction"]["matched"] == 624


def test_f18_selected_permission_does_not_hide_an_independent_seven_facet_mismatch():
    compare, arms, targets, options = _f18_matched_fixture()
    target = targets["old_tune"][31]
    prediction = _f18_fixture_prediction(arms, "coefficient_025", "joint", panel=1, row=31)
    prediction["canonical_ir"]["rules"][0]["actor"] = "a different authored actor"
    prediction["formal_outputs"][0]["payload"]["actor"] = "a different authored actor"
    expected_facets = {"modality": True, "actor": False, "action": True, "object": True,
                       "conditions": True, "exceptions": True, "temporal": True}
    assert {facet: prediction["canonical_ir"]["rules"][0][facet] == target["canonical_ir"]["rules"][0][facet]
            for facet in FACETS} == expected_facets
    before = deepcopy((arms, targets, options))
    result = compare(arms, targets, **options)
    assert (arms, targets, options) == before and prediction["status"] == "selected"
    assert result["valid_evaluation"] is True
    joint = result["arms"]["coefficient_025"]["joint"]
    diagnostic = next(row for row in joint["rows"] if row["id"] == target["id"])
    assert diagnostic["status"] == "decoded" and diagnostic["facets"] == expected_facets
    assert diagnostic["exact"] is False and joint["exact_reconstruction"]["matched"] == 623
    decision = result["permission_decisions"]["joint"][31]["arms"]["coefficient_025"]
    assert decision == {"status": "decoded", "predicted_modalities": ["P"],
                        "permission_retained": True, "full_ir_exact": False}
    assert result["permission_counts"]["joint"]["coefficient_025"]["matched"] == 32


def test_f18_raw_decoded_and_joint_selected_keep_their_distinct_valid_routes():
    compare, arms, targets, options = _f18_matched_fixture()
    raw = _f18_fixture_prediction(arms, "coefficient_025", "raw", panel=0, row=0)
    joint = _f18_fixture_prediction(arms, "coefficient_025", "joint", panel=0, row=0)
    assert raw["status"] == "decoded" and joint["status"] == "selected"
    before = deepcopy((arms, targets, options))
    result = compare(arms, targets, **options)
    assert result["valid_evaluation"] is True and (arms, targets, options) == before
    assert raw["status"] == "decoded" and joint["status"] == "selected"
    for mode in ("raw", "joint"):
        assert result["arms"]["coefficient_025"][mode]["exact_reconstruction"]["matched"] == 624
        assert result["permission_counts"][mode]["coefficient_025"]["matched"] == 32
    assert all(row[mode]["source_integrity_valid"] is True for row in result["panels"] for mode in ("raw", "joint"))


# V2 expectations below are independent authored commitments. Rendering those
# commitments into fake captures does not authenticate files or select a fit.
def _f18_v2_training_context():
    bindings = {name: "a" * 64 for name in (
        "donor_checkpoint_sha256", "donor_model_state_sha256", "donor_provenance_sha256",
        "source_parent_checkpoint_sha256", "source_parent_model_state_sha256", "context_contract_sha256",
        "training_manifest_sha256", "prepared_training_records_sha256", "teacher_checkpoint_sha256",
        "teacher_model_state_sha256", "teacher_capture_sha256", "teacher_training_sha256",
        "row_weight_training_sha256", "training_mask_certificate_sha256")}
    bindings.update(schema="conditions-fullspan-f18-four-tensor-input-bindings/v1",
        donor_checkpoint_sha256="90031d084f2d86cf860c5fc95d2dae374dc254adec70bd85a90893f98c5a1555",
        donor_model_state_sha256="2ed0ccf633f55fac202e2edb95ea9fa6e390b8d99381a05925f4dd5221925883")
    return {"schema": "f18-frozen-matched-training-expectations/v2",
        "profile_source_sha256": "d80a08844c06daae6466a39b87bc0c395e0dd4a2da01b284704a4e03e44af0f1",
        "optimizer_recipe_source_sha256": "d22b932b80c48b688ff3f18d5f141152a6032b7cb2f6195845840af818d8dc84",
        "input_bindings": bindings, "learning_rate": 0.003, "donor_config_learning_rate": 0.001,
        "arms": {"coefficient_0": {"checkpoint_sha256": "4" * 64, "model_state_sha256": "3" * 64,
                                   "recipe_sha256": "6" * 64, "margin_weight": 0.0},
                 "coefficient_025": {"checkpoint_sha256": "5" * 64, "model_state_sha256": "3" * 64,
                                     "recipe_sha256": "7" * 64, "margin_weight": 0.25}}}


def _f18_render_v2_capture_metadata(arms, context):
    for arm in ("coefficient_0", "coefficient_025"):
        expected = context["arms"][arm]
        for panel in arms[arm]:
            panel["raw"]["schema"] = "f18-paired-target-free-panel/v2"
            for chunk in panel["raw"]["chunks"]:
                chunk.update(schema="conditions-fullspan-four-tensor-target-free-head-capture/v2",
                             training_executed=False)
                chunk["inference"].update(schema="conditions-fullspan-four-tensor-inference/v2",
                    checkpoint_sha256=expected["checkpoint_sha256"], model_state_sha256=expected["model_state_sha256"],
                    recipe_sha256=expected["recipe_sha256"], learning_rate=context["learning_rate"],
                    donor_config_learning_rate=context["donor_config_learning_rate"],
                    training_executed=False, latent_ablation="none")


def _f18_v2_matched_fixture():
    context = _f18_v2_training_context()
    compare, arms, targets, options = _f18_matched_fixture()
    _f18_render_v2_capture_metadata(arms, context)
    options["expected_training"] = context
    return compare, arms, targets, options


def test_f18_v2_complete_comparison_binds_detached_expectations_without_origin_or_training_authority():
    compare, arms, targets, options = _f18_v2_matched_fixture()
    before = deepcopy((arms, targets, options))
    context = options["expected_training"]
    assert context["arms"]["coefficient_0"]["model_state_sha256"] == context["arms"]["coefficient_025"]["model_state_sha256"]
    result = compare(arms, targets, **options)
    assert (arms, targets, options) == before and result["valid_evaluation"] is True
    assert result["schema"] == "f18-frozen-matched-arm-fidelity/v2"
    assert result["training_expectations"] == context and result["training_expectations"] is not context
    raw = json.dumps(context, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()
    assert result["training_expectations_sha256"] == hashlib.sha256(raw).hexdigest()
    assert result["training_expectations_consistency_verified"] is True
    for flag in ("training_expectations_origin_verified", "checkpoint_recipe_source_bindings_independently_verified",
                 "freeze_timing_verified", "source_commitment_origin_verified", "target_origin_verified",
                 "qualified", "admitted", "formalized", "training_executed", "promotion_performed"):
        assert result[flag] is False
    for arm in ("parent", "coefficient_0", "coefficient_025"):
        for mode in ("raw", "joint"):
            assert result["arms"][arm][mode]["exact_reconstruction"]["matched"] == 624
            assert result["arms"][arm][mode]["exact_reconstruction"]["total"] == 624
            assert result["permission_counts"][mode][arm]["matched"] == 32
    result["training_expectations"]["arms"]["coefficient_0"]["recipe_sha256"] = "e" * 64
    assert options == before[2]


def test_f18_v2_comparison_executes_without_import_or_file_access(monkeypatch):
    import builtins
    import os
    from pathlib import Path
    compare, arms, targets, options = _f18_v2_matched_fixture()
    attempts = []
    def refuse(*args, **kwargs):
        attempts.append(repr(args[:1]))
        raise AssertionError("pure comparison attempted import or file access")
    with monkeypatch.context() as guard:
        guard.setattr(builtins, "open", refuse)
        guard.setattr(os, "open", refuse)
        for name in ("open", "read_bytes", "read_text", "write_bytes", "write_text"):
            guard.setattr(Path, name, refuse)
        # pytest resolves patch metadata with imports; install this guard last.
        # It is restored first by context teardown, after the actual comparison.
        guard.setattr(builtins, "__import__", refuse)
        result = compare(arms, targets, **options)
    assert attempts == [] and result["valid_evaluation"] is True


@pytest.mark.parametrize("explicit_schema", [False, True])
def test_f18_v1_default_retains_result_shape_and_legacy_inference_schema_policy(explicit_schema):
    compare, arms, targets, options = _f18_matched_fixture()
    if explicit_schema:
        for arm in ("coefficient_0", "coefficient_025"):
            for panel in arms[arm]:
                for chunk in panel["raw"]["chunks"]:
                    chunk["inference"]["schema"] = "conditions-fullspan-four-tensor-inference/v1"
    result = compare(arms, targets, **options)
    assert result == compare(arms, targets, **options, expected_training=None)
    assert result["valid_evaluation"] is True and result["schema"] == "f18-frozen-matched-arm-fidelity/v1"
    assert not any(key.startswith("training_expectations") for key in result)
    assert "checkpoint_recipe_source_bindings_independently_verified" not in result


@pytest.mark.parametrize("schema", ["conditions-fullspan-four-tensor-inference/v2", "foreign", None])
def test_f18_v1_cannot_hide_an_explicit_different_inference_generation(schema):
    compare, arms, targets, options = _f18_matched_fixture()
    arms["coefficient_025"][-1]["raw"]["chunks"][0]["inference"]["schema"] = schema
    with pytest.raises(ValueError):
        compare(arms, targets, **options)


@pytest.mark.parametrize("damage", ["no_expectations", "old_envelopes"])
def test_f18_v2_requires_explicit_context_and_matching_generation(damage):
    if damage == "no_expectations":
        compare, arms, targets, options = _f18_v2_matched_fixture()
        options.pop("expected_training")
    else:
        compare, arms, targets, options = _f18_matched_fixture()
        options["expected_training"] = _f18_v2_training_context()
    with pytest.raises(ValueError):
        compare(arms, targets, **options)


@pytest.mark.parametrize("damage", ["panel", "chunk", "inference", "inference_missing"])
def test_f18_v2_refuses_mixed_generation_even_on_last_unscored_panel(damage):
    compare, arms, targets, options = _f18_v2_matched_fixture()
    raw = arms["coefficient_025"][-1]["raw"]
    if damage == "panel": raw["schema"] = "f18-paired-target-free-panel/v1"
    elif damage == "chunk": raw["chunks"][0]["schema"] = "conditions-fullspan-four-tensor-target-free-head-capture/v1"
    elif damage == "inference": raw["chunks"][0]["inference"]["schema"] = "conditions-fullspan-four-tensor-inference/v1"
    else: raw["chunks"][0]["inference"].pop("schema")
    with pytest.raises(ValueError):
        compare(arms, targets, **options)


@pytest.mark.parametrize("field", ["checkpoint_sha256", "model_state_sha256", "recipe_sha256",
                                   "learning_rate", "donor_config_learning_rate"])
@pytest.mark.parametrize("arm,panel,chunk", [("coefficient_0", 0, 0), ("coefficient_025", 0, 1), ("coefficient_025", 9, 0)])
def test_f18_v2_identity_is_checked_on_both_arms_later_chunks_and_unscored_panels(field, arm, panel, chunk):
    compare, arms, targets, options = _f18_v2_matched_fixture()
    inference = arms[arm][panel]["raw"]["chunks"][chunk]["inference"]
    inference[field] = "e" * 64 if field.endswith("sha256") else 0.004
    with pytest.raises(ValueError):
        compare(arms, targets, **options)


@pytest.mark.parametrize("field", ["checkpoint_sha256", "model_state_sha256", "recipe_sha256",
                                   "learning_rate", "donor_config_learning_rate"])
def test_f18_v2_identity_fields_cannot_be_missing(field):
    compare, arms, targets, options = _f18_v2_matched_fixture()
    arms["coefficient_025"][0]["raw"]["chunks"][1]["inference"].pop(field)
    with pytest.raises(ValueError):
        compare(arms, targets, **options)


def test_f18_v2_learning_rate_requires_exact_declared_numeric_type():
    compare, arms, targets, options = _f18_v2_matched_fixture()
    options["expected_training"]["learning_rate"] = 3
    _f18_render_v2_capture_metadata(arms, options["expected_training"])
    arms["coefficient_025"][0]["raw"]["chunks"][1]["inference"]["learning_rate"] = 3.0
    with pytest.raises(ValueError):
        compare(arms, targets, **options)


@pytest.mark.parametrize("damage", ["chunk_training", "chunk_training_missing", "inference_training",
                                   "inference_training_missing", "ablation", "ablation_missing"])
def test_f18_v2_readout_scope_requires_no_training_and_original_unablated_inference(damage):
    compare, arms, targets, options = _f18_v2_matched_fixture()
    chunk = arms["coefficient_025"][-1]["raw"]["chunks"][0]
    if damage == "chunk_training": chunk["training_executed"] = True
    elif damage == "chunk_training_missing": chunk.pop("training_executed")
    elif damage == "inference_training": chunk["inference"]["training_executed"] = True
    elif damage == "inference_training_missing": chunk["inference"].pop("training_executed")
    elif damage == "ablation": chunk["inference"]["latent_ablation"] = "zero"
    else: chunk["inference"].pop("latent_ablation")
    with pytest.raises(ValueError):
        compare(arms, targets, **options)


@pytest.mark.parametrize("field", ["checkpoint_sha256", "recipe_sha256"])
def test_f18_v2_capture_cannot_borrow_other_arm_commitment(field):
    compare, arms, targets, options = _f18_v2_matched_fixture()
    arms["coefficient_025"][0]["raw"]["chunks"][0]["inference"][field] = options["expected_training"]["arms"]["coefficient_0"][field]
    with pytest.raises(ValueError):
        compare(arms, targets, **options)


@pytest.mark.parametrize("rate", [True, False, None, "0.003", 0, -0.003,
                                  float("nan"), float("inf"), -float("inf"), 10 ** 400])
def test_f18_v2_training_expectations_refuse_nonfinite_boolean_or_unbounded_rates(rate):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_generation_metrics import _f18_training_expectations
    context = _f18_v2_training_context()
    context["learning_rate"] = rate
    with pytest.raises(ValueError):
        _f18_training_expectations(context)


@pytest.mark.parametrize("damage", ["outer_extra", "outer_missing", "schema", "profile", "recipe_source",
    "arms_list", "arm_missing", "arm_extra", "arm_fields_extra", "arm_fields_missing", "checkpoint_hash",
    "model_hash", "recipe_hash", "margin_boolean", "margin_integer", "wrong_margin", "shared_checkpoint",
    "shared_recipe", "donor_rate", "donor_rate_boolean", "bindings_list", "bindings_extra", "bindings_schema",
    "donor_checkpoint", "donor_model", "binding_hash"])
def test_f18_v2_training_expectations_refuse_unclosed_crossed_or_borrowed_commitments(damage):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_generation_metrics import _f18_training_expectations
    context = _f18_v2_training_context()
    candidate = context["arms"]["coefficient_025"]
    if damage == "outer_extra": context["admitted"] = True
    elif damage == "outer_missing": context.pop("learning_rate")
    elif damage == "schema": context["schema"] = "f18-frozen-matched-training-expectations/v1"
    elif damage == "profile": context["profile_source_sha256"] = "e" * 64
    elif damage == "recipe_source": context["optimizer_recipe_source_sha256"] = "e" * 64
    elif damage == "arms_list": context["arms"] = list(context["arms"].values())
    elif damage == "arm_missing": context["arms"].pop("coefficient_0")
    elif damage == "arm_extra": context["arms"]["parent"] = deepcopy(candidate)
    elif damage == "arm_fields_extra": candidate["admitted"] = True
    elif damage == "arm_fields_missing": candidate.pop("recipe_sha256")
    elif damage == "checkpoint_hash": candidate["checkpoint_sha256"] = "A" * 64
    elif damage == "model_hash": candidate["model_state_sha256"] = "3" * 63
    elif damage == "recipe_hash": candidate["recipe_sha256"] = 7
    elif damage == "margin_boolean": context["arms"]["coefficient_0"]["margin_weight"] = False
    elif damage == "margin_integer": context["arms"]["coefficient_0"]["margin_weight"] = 0
    elif damage == "wrong_margin": candidate["margin_weight"] = 0.0
    elif damage == "shared_checkpoint": candidate["checkpoint_sha256"] = context["arms"]["coefficient_0"]["checkpoint_sha256"]
    elif damage == "shared_recipe": candidate["recipe_sha256"] = context["arms"]["coefficient_0"]["recipe_sha256"]
    elif damage == "donor_rate": context["donor_config_learning_rate"] = 0.003
    elif damage == "donor_rate_boolean": context["donor_config_learning_rate"] = True
    elif damage == "bindings_list": context["input_bindings"] = []
    elif damage == "bindings_extra": context["input_bindings"]["unrecognized"] = "a" * 64
    elif damage == "bindings_schema": context["input_bindings"]["schema"] = "unrecognized"
    elif damage == "donor_checkpoint": context["input_bindings"]["donor_checkpoint_sha256"] = "e" * 64
    elif damage == "donor_model": context["input_bindings"]["donor_model_state_sha256"] = "e" * 64
    else: context["input_bindings"]["teacher_capture_sha256"] = "invalid"
    with pytest.raises(ValueError):
        _f18_training_expectations(context)


@pytest.mark.parametrize("field", ["schema", "donor_checkpoint_sha256", "donor_model_state_sha256",
    "donor_provenance_sha256", "source_parent_checkpoint_sha256", "source_parent_model_state_sha256",
    "context_contract_sha256", "training_manifest_sha256", "prepared_training_records_sha256",
    "teacher_checkpoint_sha256", "teacher_model_state_sha256", "teacher_capture_sha256",
    "teacher_training_sha256", "row_weight_training_sha256", "training_mask_certificate_sha256"])
def test_f18_v2_training_expectations_require_every_original_input_binding(field):
    from ipfs_datasets_py.optimizers.logic_theorem_optimizer.formula_generation_metrics import _f18_training_expectations
    context = _f18_v2_training_context()
    context["input_bindings"].pop(field)
    with pytest.raises(ValueError):
        _f18_training_expectations(context)


@pytest.mark.parametrize("damage", ["honest_abstention", "independent_actor_loss", "invalid_joint_status",
                                   "missing_row", "unscored_source_mismatch"])
def test_f18_v2_generation_consistency_never_substitutes_for_complete_fidelity_accounting(damage):
    compare, arms, targets, options = _f18_v2_matched_fixture()
    prediction = _f18_fixture_prediction(arms, "coefficient_025", "joint", panel=1, row=31)
    if damage == "honest_abstention":
        prediction.update(status="abstained", canonical_ir=None, formal_outputs=[], formula_text=None)
    elif damage == "independent_actor_loss":
        _replace(prediction, "actor", "a different authored actor")
    elif damage == "invalid_joint_status": prediction["status"] = "decoded"
    elif damage == "missing_row": arms["coefficient_025"][1]["joint"]["rows"].pop()
    else:
        _f18_fixture_prediction(arms, "coefficient_025", "joint", panel=9, row=0)["source_sha256"] = "e" * 64
    result = compare(arms, targets, **options)
    assert result["training_expectations_consistency_verified"] is True
    assert result["weak_label_target_count"] == 624
    assert len(result["retention"]["joint"]) == 72 and len(result["permission_decisions"]["joint"]) == 32
    assert result["arms"]["coefficient_025"]["joint"]["exact_reconstruction"]["total"] == 624
    if damage in {"honest_abstention", "independent_actor_loss"}:
        assert result["valid_evaluation"] is True
        assert result["arms"]["coefficient_025"]["joint"]["exact_reconstruction"]["matched"] == 623
        decision = result["permission_decisions"]["joint"][31]["arms"]["coefficient_025"]
        assert decision["full_ir_exact"] is False
        assert decision["permission_retained"] is (damage == "independent_actor_loss")
    else:
        assert result["valid_evaluation"] is False
    assert result["training_expectations_origin_verified"] is False



@pytest.mark.parametrize("damage", ["context_schema", "profile_source", "recipe_source", "bindings_schema",
    "context_key", "binding_key", "arm_key", "arm_field", "panel_schema", "chunk_schema",
    "inference_schema", "latent_ablation"])
def test_f18_v2_context_and_generation_names_require_literal_strings(damage):
    class EqualString(str):
        def __eq__(self, other): return True
        __hash__ = str.__hash__
    compare, arms, targets, options = _f18_v2_matched_fixture()
    context = options["expected_training"]
    chunk = arms["coefficient_025"][-1]["raw"]["chunks"][0]
    if damage in {"context_schema", "profile_source", "recipe_source"}:
        field = {"context_schema": "schema", "profile_source": "profile_source_sha256",
                 "recipe_source": "optimizer_recipe_source_sha256"}[damage]
        context[field] = EqualString("unrecognized")
    elif damage == "bindings_schema": context["input_bindings"]["schema"] = EqualString("unrecognized")
    elif damage == "context_key": context[EqualString("schema")] = context.pop("schema")
    elif damage == "binding_key":
        bindings = context["input_bindings"]
        bindings[EqualString("teacher_capture_sha256")] = bindings.pop("teacher_capture_sha256")
    elif damage == "arm_key": context["arms"][EqualString("coefficient_025")] = context["arms"].pop("coefficient_025")
    elif damage == "arm_field":
        arm = context["arms"]["coefficient_025"]
        arm[EqualString("recipe_sha256")] = arm.pop("recipe_sha256")
    elif damage == "panel_schema": arms["coefficient_025"][-1]["raw"]["schema"] = EqualString("unrecognized")
    elif damage == "chunk_schema": chunk["schema"] = EqualString("unrecognized")
    elif damage == "inference_schema": chunk["inference"]["schema"] = EqualString("unrecognized")
    else: chunk["inference"]["latent_ablation"] = EqualString("unrecognized")
    with pytest.raises(ValueError):
        compare(arms, targets, **options)
