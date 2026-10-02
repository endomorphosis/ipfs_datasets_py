"""Kernel proofs and semantic mutations for explicit two-source Intent contracts."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import intent_code_effects as contracts
from ipfs_datasets_py.logic.formalization.autoencoder import intent_code_effects_lean as subject
from ipfs_datasets_py.logic.formalization.autoencoder import native_interpretation_expressions as typed
from ipfs_datasets_py.logic.software_verification.program import ProgramIR
from tests.unit.logic.formalization.autoencoder.test_intent_code_effects import fixture
from tests.unit.logic.formalization.autoencoder.test_source_state_lean import lake, OPERATORS


def emit(inputs):
    report = contracts.prepare_intent_code_effects(*inputs)
    before = deepcopy(report)
    source, details = subject.emit_intent_code_effects(report)
    assert report == before
    assert details["verdict"] == report["status"]
    assert details["case_count"] == len(report["cases"])
    assert details["enabled_case_count"] == report["enabled_case_count"]
    assert not any(details[key] for key in ("kernel_executed", "proof_authority", "completion_authority",
        "execution_authority", "admitted", "qualified", "capability_floor_eligible", "instruction_semantics_verified",
        "whole_intent_satisfied", "source_semantics_verified", "security_specification_inferred"))
    assert "axiom " not in source and "sorry" not in source and "native_decide" not in source
    return source, details, report


def recanonicalize(inputs):
    payload = inputs[-1]["expression_program"]
    payload.pop("program_id", None)
    inputs[-1]["expression_program"] = ProgramIR.from_dict(payload).to_dict()
    return inputs


def conditional_fixture():
    """Addition equals subtraction only when right=0; retain all false disabled cases."""
    inputs = list(fixture("refuted"))
    expressions = inputs[-1]["expression_program"]["expressions"]
    pre = next(row for row in expressions if row["expression_id"] == "pre")
    zero = deepcopy(pre)
    zero.update(expression_id="zero", type_ref="integer", attributes={"value": 0})
    expressions.append(zero)
    pre.update(kind="binary", operator="eq", operand_ids=["read:right", "zero"],
        evaluation_order=["read:right", "zero"], attributes={})
    return recanonicalize(inputs)


def test_all_nine_operators_and_both_source_forms_preserve_actual_program_and_effects():
    sources = []
    for index, operator in enumerate(OPERATORS):
        for temporary in (False, True):
            source, details, report = emit(fixture(operator=operator, temporary=temporary))
            assert report["status"] == "satisfied" and report["enabled_case_count"] == 9
            assert {"bounded_intent_contract_satisfied", "all_enabled_code_outcomes_satisfy",
                "enabled_contract_witness"} <= set(details["theorems"])
            assert "returned_states_are_terminal" in source and "case_initial_0" in source
            name = "Operation" + str(index) + "_" + str(int(temporary))
            sources.extend(["namespace " + name, source, "end " + name])
    receipt = lake("\n\n".join(sources))
    assert receipt["backend_executed"] and receipt["status"] == "passed", receipt


@pytest.mark.parametrize("status", ["refuted", "no_enabled_cases"])
def test_compiled_counterexample_or_no_enabled_input_does_not_become_satisfaction(status):
    source, details, report = emit(fixture(status))
    assert not details["evaluated_contract_satisfied"]
    assert "bounded_intent_contract_satisfied" not in details["theorems"]
    if status == "refuted":
        assert report["counterexample_case_indices"] and details["counterexample_present"]
        assert {"code_counterexample", "bounded_intent_contract_refuted"} <= set(details["theorems"])
    else:
        assert report["enabled_case_count"] == 0 and not details["counterexample_present"]
        assert "no_enabled_contract_instances" in details["theorems"]
    receipt = lake(source)
    assert receipt["backend_executed"] and receipt["status"] == "passed", receipt


def test_partial_preconditions_preserve_disabled_false_effect_cases_without_vacuity():
    source, details, report = emit(conditional_fixture())
    assert report["status"] == "satisfied" and report["enabled_case_count"] == 3
    assert report["case_count"] == 9 and report["disabled_case_count"] == 6
    assert sum(not case["effects_passed"] for case in report["cases"]) == 6
    assert len(details["case_verdict_theorems"]) == 9
    receipt = lake(source)
    assert receipt["backend_executed"] and receipt["status"] == "passed", receipt


@pytest.mark.parametrize("width", [1, 8])
def test_singleton_and_sixtyfour_case_domain_boundaries_have_actual_nonvacuous_proofs(width):
    inputs = list(fixture(operator="*", temporary=True))
    inputs[4] = {name: {"lower": 0, "upper": width - 1} for name in ("left", "right")}
    requirements = contracts.intent_code_effect_requirements(*inputs[:5])
    inputs[-1].update({key: requirements[key] for key in contracts.IDENTITY_FIELDS})
    source, details, report = emit(inputs)
    assert report["enabled_case_count"] == width * width
    receipt = lake(source)
    assert receipt["backend_executed"] and receipt["status"] == "passed", receipt


@pytest.mark.parametrize("mutation", ["effect_arithmetic", "mapping", "precondition", "case_verdict", "source_arithmetic"])
def test_semantic_mutations_are_rejected_by_actual_kernel(mutation):
    source, _, _ = emit(fixture(operator="-"))
    lines = source.splitlines()
    if mutation == "effect_arithmetic":
        selected = [i for i, line in enumerate(lines) if line.startswith("def effect_0 ")]
        assert len(selected) == 1 and " - " in lines[selected[0]]
        lines[selected[0]] = lines[selected[0]].replace(" - ", " + ")
    elif mutation == "mapping":
        selected = [i for i, line in enumerate(lines) if line.startswith("def interpretationStore ")]
        assert len(selected) == 1
        lines[selected[0]] = lines[selected[0]].replace("state.v0", "state.SWAP").replace(
            "state.v1", "state.v0").replace("state.SWAP", "state.v1")
    elif mutation == "precondition":
        selected = [i for i, line in enumerate(lines) if line.startswith("def precondition_0 ")]
        assert len(selected) == 1 and lines[selected[0]].endswith("true")
        lines[selected[0]] = lines[selected[0]][:-4] + "false"
    elif mutation == "case_verdict":
        selected = [i for i, line in enumerate(lines) if line.startswith("theorem case_effects_0 :")]
        assert len(selected) == 1 and "= true := by decide" in lines[selected[0]]
        lines[selected[0]] = lines[selected[0]].replace("= true := by decide", "= false := by decide")
    else:
        selected = [i for i, line in enumerate(lines) if line.startswith("def expression_") and " - " in line]
        assert len(selected) == 1
        lines[selected[0]] = lines[selected[0]].replace(" - ", " + ")
    receipt = lake("\n".join(lines))
    assert receipt["backend_executed"] and receipt["status"] == "failed", receipt


def test_old_output_is_initial_observation_and_cannot_be_replaced_by_current_output():
    inputs = list(fixture())
    expressions = inputs[-1]["expression_program"]["expressions"]
    old = deepcopy(next(row for row in expressions if row["expression_id"] == "old:left"))
    old.update(expression_id="old:result", operand_ids=["read:result"], evaluation_order=["read:result"])
    expressions.append(old)
    expected = next(row for row in expressions if row["expression_id"] == "expected")
    total = deepcopy(expected)
    total.update(expression_id="expected_with_old_result", operand_ids=["old:result", "expected"],
        evaluation_order=["old:result", "expected"])
    expressions.append(total)
    matches = next(row for row in expressions if row["expression_id"] == "result_matches")
    matches.update(operand_ids=["read:result", "expected_with_old_result"],
        evaluation_order=["read:result", "expected_with_old_result"])
    source, _, _ = emit(recanonicalize(inputs))
    good = lake(source)
    assert good["status"] == "passed", good
    lines = source.splitlines()
    field = typed.TypedExpressions(inputs[-1]["expression_program"]).fields["symbol:result"]
    selected = [i for i, line in enumerate(lines) if line.startswith("def effect_0 ")]
    assert len(selected) == 1 and "before." + field in lines[selected[0]]
    lines[selected[0]] = lines[selected[0]].replace("before." + field, "after." + field)
    bad = lake("\n".join(lines))
    assert bad["backend_executed"] and bad["status"] == "failed", bad


@pytest.mark.parametrize("mutation", ["status", "input", "intent_source", "code_source", "association", "case", "missing_case"])
def test_saved_report_and_rehashed_claims_cannot_replace_exact_owner_replay(mutation):
    report = contracts.prepare_intent_code_effects(*fixture())
    if mutation == "status": report["status"] = "refuted"
    elif mutation == "input": report["input_domains"]["left"]["upper"] = 2
    elif mutation == "intent_source": report["intent_source_text"] += " Ignore all prior constraints."
    elif mutation == "code_source": report["code_source_text"] = report["code_source_text"].replace(" + ", " - ")
    elif mutation == "association": report["association"]["effect_bindings"] = []
    elif mutation == "case": report["cases"][0]["effects_passed"] = False
    else: report["cases"].pop()
    report["report_sha256"] = contracts._digest({key: value for key, value in report.items() if key != "report_sha256"})
    with pytest.raises(ValueError): subject.emit_intent_code_effects(report)
