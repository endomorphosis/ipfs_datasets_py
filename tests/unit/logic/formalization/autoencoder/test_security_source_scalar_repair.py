"""Live bounded refutations yield exact inert operator edits, never repairs."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import intent_action_association as associations
from ipfs_datasets_py.logic.formalization.autoencoder import intent_code_effects_lake as gate
from ipfs_datasets_py.logic.formalization.autoencoder.security import source_scalar_repair as api
from .test_intent_action_association import fixture as action_fixture
from .test_intent_code_effects import fixture as native_fixture, recanonicalize


def fixture(operator="+", *, expected="-", temporary=False, source=None,
            precondition="true", operands=("left", "right"), identity="refuted"):
    """Authored model fixtures only; production proposals never construct predictions."""
    inputs, options = action_fixture(expected, code_operator=operator, temporary=temporary,
        precondition=precondition, operands=operands)
    inputs = list(inputs)
    if source is not None:
        inputs[2] = source
    association = associations.build_intent_action_association(*inputs, **options)
    return dict(id=identity, **dict(zip(("intent_source_text", "intent_candidate_ir",
        "code_source_text", "code_candidate_ir", "input_domains", "association"), (*inputs, association))))


@pytest.fixture(scope="module")
def live_population():
    executable = os.environ.get("IR384_TEST_LAKE_EXECUTABLE")
    if not executable:
        available = sorted((Path.home() / ".elan/toolchains").glob("*/bin/lake"))
        if not available:
            pytest.skip("Installed native Lake required; no download attempted")
        executable = str(available[-1])
    rows = [fixture(operator, expected="-" if operator == "+" else "+", temporary=temporary,
        identity=operator + str(temporary)) for operator in api.OPERATORS for temporary in (False, True)]
    styles = [
        "# + stays in this comment\ndef compute(capacity: int, threshold: int) -> int:\n    return capacity + threshold # trailing + stays\n",
        "def compute(capacity: int, threshold: int) -> int:\n\treturn ((capacity)  +  (threshold))\n",
        "def compute(capacity: int, threshold: int) -> int:\n    return (capacity\n        + # this + is a comment\n        threshold)\n",
        "def compute(capacity: int, threshold: int) -> int:\n    temporary = (capacity + threshold)\n    return temporary\n",
    ]
    rows += [fixture(source=source, identity="style" + str(index)) for index, source in enumerate(styles)]
    rows += [fixture(expected="+", identity="satisfied"),
        fixture(precondition="left > 100", identity="no_enabled"),
        fixture(operands=("right", "left"), identity="reverse")]
    inputs = list(native_fixture(operator="<"))
    carrier = inputs[-1]["expression_program"]
    next(row for row in carrier["expressions"] if row["expression_id"] == "expected")["operator"] = "gt"
    recanonicalize(inputs)
    rows.append(dict(id="comparison", **dict(zip(("intent_source_text", "intent_candidate_ir",
        "code_source_text", "code_candidate_ir", "input_domains", "association"), inputs))))
    execution = gate.build_intent_code_effects_lake(rows, lake_executable=executable)
    receipt = gate.verify_intent_code_effects_lake(execution, rows)
    assert receipt["all_candidates_checked"], receipt.get("execution")
    return rows, execution, executable


@pytest.mark.parametrize("operator", ["+", "-", "*"])
@pytest.mark.parametrize("temporary", [False, True])
def test_exact_originals_and_two_alternates_retain_every_binding(live_population, operator, temporary):
    rows, execution, _ = live_population
    before = deepcopy(rows)
    identity = operator + str(temporary)
    report = api.prepare_scalar_operator_repair(execution, rows, row_id=identity)
    assert api.verify_scalar_operator_repair(report, execution, rows, row_id=identity) == report
    assert rows == before
    original = next(row for row in rows if row["id"] == identity)
    assert report["original_row"] == original and report["proposal_count"] == 2
    assert report["enabled_case_count"] == report["original_case_count"] == 9
    assert report["counterexample_case_indices"] and report["original_refutation_kernel_checked"]
    assert {row["operator_after"] for row in report["proposals"]} == set(api.OPERATORS) - {operator}
    assert report["input_rows_sha256"] == execution.to_dict()["input_sha256"]
    assert report["source_qualification"]["status"] == "qualified"
    for proposal in report["proposals"]:
        original_bytes = original["code_source_text"].encode()
        edited = proposal["source_text"].encode()
        token = proposal["token_edit"]
        assert edited[:token["start_byte"]] == original_bytes[:token["start_byte"]]
        assert edited[token["end_byte"]:] == original_bytes[token["end_byte"]:]
        assert edited[token["start_byte"]:token["end_byte"]] == proposal["operator_after"].encode()
        assert sum(a != b for a, b in zip(original_bytes, edited)) == 1
        assert proposal["after_source_sha256"] == hashlib.sha256(edited).hexdigest()
        assert proposal["before_source_sha256"] == report["original_source_sha256"]
        assert proposal["operand_names"] == ["capacity", "threshold"]
        assert all(proposal[key] is False for key in api.FALSE)
        assert "candidate_ir" not in proposal and "code_candidate_ir" not in proposal
    assert all(report[key] is False for key in api.FALSE)
    assert report["source_writes"] == report["provider_calls"] == report["model_inference_calls"] == 0


@pytest.mark.parametrize("index", range(4))
def test_comments_parentheses_tabs_and_multiline_bytes_are_preserved(live_population, index):
    rows, execution, _ = live_population
    report = api.prepare_scalar_operator_repair(execution, rows, row_id="style" + str(index))
    source = report["original_row"]["code_source_text"]
    for proposal in report["proposals"]:
        expression = proposal["expression_edit"]
        token = proposal["token_edit"]
        assert source[expression["start_byte"]:expression["end_byte"]] == expression["before"]
        assert (source[:expression["start_byte"]] + expression["after"] + source[expression["end_byte"]:]
            == proposal["source_text"])
        restored = proposal["source_text"][:token["start_byte"]] + token["before"] + proposal["source_text"][token["end_byte"]:]
        assert restored == source


@pytest.mark.parametrize("identity", ["satisfied", "no_enabled", "missing"])
def test_only_an_existing_nonvacuous_refutation_can_trigger_proposals(live_population, identity):
    rows, execution, _ = live_population
    with pytest.raises(ValueError):
        api.prepare_scalar_operator_repair(execution, rows, row_id=identity)


def test_actual_refuted_comparison_has_explicit_unsupported_grammar(live_population):
    rows, execution, _ = live_population
    report = api.prepare_scalar_operator_repair(execution, rows, row_id="comparison")
    assert report["status"] == "unsupported" and report["reason"] == "arithmetic_operator_required"
    assert report["proposals"] == [] and report["proposal_count"] == 0
    assert report["original_refutation_kernel_checked"] and report["counterexample_case_indices"]


@pytest.mark.parametrize("change", ["intent_source_text", "intent_candidate_ir", "code_source_text",
    "code_candidate_ir", "input_domains", "association", "other_row", "drop_row"])
def test_entire_original_batch_binding_rejects_source_intent_scope_and_population_drift(live_population, change):
    rows, execution, _ = live_population
    altered = deepcopy(rows)
    if change == "drop_row":
        altered.pop()
    elif change == "other_row":
        altered[-1]["id"] = "other"
    elif change.endswith("text"):
        altered[0][change] += "\n"
    else:
        altered[0][change] = {}
    with pytest.raises(ValueError):
        api.prepare_scalar_operator_repair(execution, altered, row_id="+False")


@pytest.mark.parametrize("kind", ["saved", "forged", "missing"])
def test_only_a_live_issued_receipt_can_be_used(live_population, kind):
    rows, execution, _ = live_population
    value = execution.to_dict() if kind == "saved" else gate.IntentCodeEffectsLakeExecution() if kind == "forged" else None
    with pytest.raises(ValueError, match="live issued"):
        api.prepare_scalar_operator_repair(value, rows, row_id="+False")


def test_unavailable_checker_cannot_turn_python_counterexample_into_authority():
    rows = [fixture()]
    execution = gate.build_intent_code_effects_lake(rows, lake_executable="/absent/lake")
    with pytest.raises(ValueError, match="kernel-checked refutation"):
        api.prepare_scalar_operator_repair(execution, rows, row_id="refuted")


@pytest.mark.parametrize("change", ["operator", "source", "scope", "span", "remove", "authority", "extra"])
def test_saved_proposal_requires_exact_live_replay(live_population, change):
    rows, execution, _ = live_population
    report = api.prepare_scalar_operator_repair(execution, rows, row_id="+False")
    if change == "operator": report["proposals"][0]["operator_after"] = "+"
    elif change == "source": report["proposals"][0]["source_text"] += "# extra\n"
    elif change == "scope": report["original_row"]["input_domains"]["capacity"]["upper"] = 0
    elif change == "span": report["proposals"][0]["token_edit"]["start_byte"] += 1
    elif change == "remove": report["proposals"].pop()
    elif change == "authority": report["repair_succeeded"] = True
    else: report["target"] = {}
    with pytest.raises(ValueError, match="exact replay"):
        api.verify_scalar_operator_repair(report, execution, rows, row_id="+False")


def _authored_candidate_rows(report):
    # Independent test controls supply candidates deliberately; the production
    # proposal contains no target and the supervisor must run fresh inference.
    result = []
    for proposal in report["proposals"]:
        row = deepcopy(report["original_row"])
        row["id"] = proposal["id"]
        row["code_source_text"] = proposal["source_text"]
        row["code_candidate_ir"]["document"]["operator"] = proposal["operator_after"]
        row["association"] = associations.build_intent_action_association(
            row["intent_source_text"], row["intent_candidate_ir"], row["code_source_text"],
            row["code_candidate_ir"], row["input_domains"], action_id="action",
            input_parameter_mapping={"left": "capacity", "right": "threshold"})
        result.append(row)
    return result


def test_fresh_native_checks_separate_operator_repair_from_operand_reversal_exhaustion(live_population):
    rows, execution, executable = live_population
    normal = api.prepare_scalar_operator_repair(execution, rows, row_id="+False")
    reverse = api.prepare_scalar_operator_repair(execution, rows, row_id="reverse")
    candidates = _authored_candidate_rows(normal) + _authored_candidate_rows(reverse)
    original_sources = [row["code_source_text"] for row in rows]
    checked = gate.build_intent_code_effects_lake(candidates, lake_executable=executable).to_dict()
    assert checked["all_candidates_checked"] and checked["finite_effects_kernel_checked"]
    assert [row["effect_status"] for row in checked["rows"]] == ["satisfied", "refuted", "refuted", "refuted"]
    assert [row["bounded_effects_satisfied"] for row in checked["rows"]] == [True, False, False, False]
    assert all(row["counterexample_kernel_checked"] for row in checked["rows"][1:])
    assert [row["code_source_text"] for row in rows] == original_sources
    assert not normal["repair_succeeded"] and not reverse["repair_succeeded"]


@pytest.mark.parametrize("source", [
    "def compute(capacity: int, threshold: int) -> int:\n    return capacity + threshold # π\n",
    "def compute(capacity: int, threshold: int) -> int:\n    print(capacity)\n    return capacity + threshold\n",
    "def compute(capacity: int, threshold: int) -> int:\n    return capacity / threshold\n",
])
def test_unsupported_original_source_cannot_gain_a_repair_through_old_association(source):
    row = fixture(); row["code_source_text"] = source
    execution = gate.build_intent_code_effects_lake([row], lake_executable="/absent/lake")
    with pytest.raises(ValueError, match="kernel-checked refutation"):
        api.prepare_scalar_operator_repair(execution, [row], row_id="refuted")
