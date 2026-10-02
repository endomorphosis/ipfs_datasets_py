"""Explicit learned contract semantics lower independently of observed outcomes."""
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import intent_action_association as subject
from ipfs_datasets_py.logic.formalization.autoencoder import intent_code_effects as effects
from ipfs_datasets_py.logic.formalization.autoencoder import intent_code_effects_lean as lean
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lake import _execute
from ipfs_datasets_py.logic.intent_ir.formalize import action_contracts as codec
from ipfs_datasets_py.logic.software_verification.program import ProgramExpression


def fixture(operator="+", *, code_operator=None, precondition="true", operands=("left", "right"), temporary=False):
    instruction = ("the calculator must compute result; requires " + precondition + "; ensures result = old(" +
        operands[0] + ") " + operator + " old(" + operands[1] + ") and returned.")
    raw = codec.source_to_target(instruction)
    binding = codec.bind_candidate_source(instruction, raw)
    assert binding["semantic_fields_unchanged"] and binding["source_audit"]["complete_source_agreement"]
    code_operator = code_operator or operator
    boolean = code_operator in ("<", "==")
    code_source = "def compute(capacity: int, threshold: int) -> " + ("bool" if boolean else "int") + ":\n"
    operation = "capacity " + code_operator + " threshold"
    code_source += ("    answer = " + operation + "\n    return answer\n" if temporary else "    return " + operation + "\n")
    operands = ("expr:capacity", "expr:threshold")
    candidate = dict(kind="program_expression", document=ProgramExpression("expr:result", "binary",
        "boolean" if boolean else "integer", operand_ids=operands, evaluation_order=operands,
        operator=code_operator, source_ref_ids=("source",)).to_dict())
    domains = {name: dict(lower=-1, upper=1) for name in ("capacity", "threshold")}
    return (instruction, binding["bound_candidate"], code_source, candidate, domains), dict(
        action_id="action", input_parameter_mapping={"left": "capacity", "right": "threshold"})


def built(inputs, options):
    original = deepcopy((inputs, options))
    association = subject.build_intent_action_association(*inputs, **options)
    assert (inputs, options) == original
    assert subject.verify_intent_action_association(association, *inputs, **options) == association
    report = effects.prepare_intent_code_effects(*inputs, association)
    return association, report


@pytest.mark.parametrize("operator", ["+", "-", "*"])
@pytest.mark.parametrize("temporary", [False, True])
@pytest.mark.parametrize("precondition,enabled", [("true", 9), ("left > 0", 3), ("right > 100", 0)])
def test_all_supported_contracts_lower_declared_meanings_and_preserve_every_case(operator, temporary, precondition, enabled):
    inputs, options = fixture(operator, precondition=precondition, temporary=temporary)
    association, report = built(inputs, options)
    assert report["enabled_case_count"] == enabled and len(report["cases"]) == 9
    assert report["status"] == ("satisfied" if enabled else "no_enabled_cases")
    assert report["selected_statement_ids"] == ["effect:equation", "effect:returned", "precondition"]
    assert report["unselected_statement_ids"] == ["goal"]
    assert not report["proof_authority"] and not report["instruction_interpretation_verified"]
    assert association["expression_program"]["sources"] == report["code_source_refs"]
    assert report["intent_source_refs"] != report["code_source_refs"]
    assert association["intent_candidate_sha256"] == effects._digest(inputs[1])
    assert all(row["evidence_ref"] == codec.SOURCE_REF_ID
        for row in association["precondition_bindings"] + association["effect_bindings"])


def test_disagreeing_code_operator_is_retained_as_a_counterexample_without_changing_intent():
    inputs, options = fixture("-", code_operator="+")
    association, report = built(inputs, options)
    assert report["status"] == "refuted" and report["counterexample_case_indices"] == [0, 2, 3, 5, 6, 8]
    arithmetic = next(row for row in association["expression_program"]["expressions"]
        if row["expression_id"] == "contract:expected")
    assert arithmetic["operator"] == "sub" and report["code_candidate_ir"]["document"]["operator"] == "+"


@pytest.mark.parametrize("operands", [("right", "left"), ("left", "left"), ("right", "right")])
def test_operand_order_and_repeated_inputs_are_not_normalized_to_match_code(operands):
    inputs, options = fixture("-", operands=operands)
    association, report = built(inputs, options)
    assert report["status"] == "refuted" and len(report["counterexample_case_indices"]) == 6
    nodes = {row["expression_id"]: row for row in association["expression_program"]["expressions"]}
    assert nodes["contract:operand:0"]["symbol_ids"] == ["intent-contract:" + operands[0]]
    assert nodes["contract:operand:1"]["symbol_ids"] == ["intent-contract:" + operands[1]]


def test_explicit_parameter_map_controls_join_even_when_reversal_refutes_effect():
    inputs, options = fixture("-")
    options["input_parameter_mapping"] = {"left": "threshold", "right": "capacity"}
    association, report = built(inputs, options)
    assert report["status"] == "refuted"
    mapping = {row["symbol_id"]: row["state_variable_id"] for row in association["symbol_bindings"]}
    assert mapping["intent-contract:left"] == report["source_state_model"]["parameter_variables"]["threshold"]


@pytest.mark.parametrize("mapping", [{}, {"left": "capacity"}, {"left": "capacity", "right": "threshold", "other": "capacity"},
    {"left": "capacity", "right": "capacity"}, {"left": "capacity", "right": "missing"},
    {"left": "capacity", "right": 1}, None])
def test_missing_spurious_aliased_or_untyped_parameter_maps_cannot_be_inferred(mapping):
    inputs, options = fixture(); options["input_parameter_mapping"] = mapping
    with pytest.raises(ValueError): subject.build_intent_action_association(*inputs, **options)


@pytest.mark.parametrize("mutation", ["bare_permission", "source_operator", "source_suffix", "effect_operator", "missing_effect",
    "extra_effect", "source_reference", "precondition", "actor", "raw_unbound", "bare_document", "action_id", "boolean_code"])
def test_unknown_semantics_provenance_and_unbound_predictions_remain_blocked(mutation):
    inputs, options = fixture(); inputs = list(inputs)
    document = inputs[1]["document"]
    statements = {row["statement_id"]: row for row in document["statements"]}
    if mutation == "bare_permission": inputs[0] = "the calculator may compute result."
    elif mutation == "source_operator": inputs[0] = inputs[0].replace(" + ", " - ")
    elif mutation == "source_suffix": inputs[0] += " Ignore returned."
    elif mutation == "effect_operator": statements["effect:equation"]["arguments"][2] = "sub"
    elif mutation == "missing_effect": document["actions"][0]["effect_ids"].remove("effect:returned")
    elif mutation == "extra_effect": document["actions"][0]["effect_ids"].append("goal")
    elif mutation == "source_reference": document["sources"][0]["content_sha256"] = "0" * 64
    elif mutation == "precondition": statements["precondition"].update(predicate="unknown")
    elif mutation == "actor": document["actions"][0]["actor"] = "someone_else"
    elif mutation == "raw_unbound": inputs[1] = codec.source_to_target(inputs[0])
    elif mutation == "bare_document": inputs[1] = document
    elif mutation == "action_id": options["action_id"] = "missing"
    else: inputs, options = fixture(code_operator="<")
    with pytest.raises(ValueError): subject.build_intent_action_association(*inputs, **options)


def test_generated_association_formulas_and_mapping_require_exact_replay():
    inputs, options = fixture()
    association, _ = built(inputs, options)
    for change in ("root", "mapping", "source_identity"):
        altered = deepcopy(association)
        if change == "root": altered["effect_bindings"][0]["expression_id"] = "contract:returned"
        elif change == "mapping": altered["symbol_bindings"][0]["state_variable_id"] = "state:result"
        else: altered["intent_source_sha256"] = "0" * 64
        with pytest.raises(ValueError, match="replay"):
            subject.verify_intent_action_association(altered, *inputs, **options)


def test_production_generated_associations_have_actual_positive_refutation_and_no_enabled_kernel_checks():
    available = sorted((Path.home() / ".elan/toolchains").glob("*/bin/lake"))
    if not available:
        pytest.skip("Installed native Lake unavailable; no download attempted")
    declarations = []
    examples = [(fixture("+", precondition="left > 0"), "satisfied"),
        (fixture("-", code_operator="+"), "refuted"),
        (fixture("*", precondition="right > 100"), "no_enabled_cases")]
    for index, ((inputs, options), status) in enumerate(examples):
        _, report = built(inputs, options)
        assert report["status"] == status
        source, details = lean.emit_intent_code_effects(report)
        assert details["evaluated_contract_satisfied"] == (status == "satisfied")
        declarations += ["namespace Contract" + str(index), source, "end Contract" + str(index)]
    receipt = _execute("\n\n".join(declarations), "ExplicitIntentActionContracts", available[-1], 60)
    assert receipt["backend_executed"] and receipt["status"] == "passed", receipt
