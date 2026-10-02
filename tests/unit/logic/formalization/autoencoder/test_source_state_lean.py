"""Real-kernel finite source/state correspondence and semantic mutation checks."""
from copy import deepcopy
from pathlib import Path

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder import source_state_lean as subject
from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lake import _execute
from ipfs_datasets_py.logic.formalization.autoencoder.security.source_state_model import derive_source_state_model
from ipfs_datasets_py.logic.software_verification.program import ProgramExpression


OPERATORS = ("+", "-", "*", "<", "<=", ">", ">=", "==", "!=")


def fixture(operator="+", *, temporary=False, domains=None):
    boolean = operator in ("<", "<=", ">", ">=", "==", "!=")
    source = "def combine(left: int, right: int) -> " + ("bool" if boolean else "int") + ":\n"
    source += ("    outcome = left " + operator + " right\n    return outcome\n" if temporary else
        "    return left " + operator + " right\n")
    refs = ("expr:left", "expr:right")
    candidate = {"kind": "program_expression", "document": ProgramExpression("expr:result", "binary",
        "boolean" if boolean else "integer", operand_ids=refs, evaluation_order=refs,
        operator=operator, source_ref_ids=("source",)).to_dict()}
    return derive_source_state_model(source, candidate, domains or {
        "left": {"lower": -1, "upper": 1}, "right": {"lower": -1, "upper": 1}})


def lake(source):
    available = sorted((Path.home() / ".elan/toolchains").glob("*/bin/lake"))
    if not available:
        pytest.skip("Installed native Lake unavailable; no download attempted")
    return _execute(source, "SourceStateCorrespondence", available[-1], 60)


def test_all_nine_operators_and_both_source_forms_have_kernel_checked_correspondence():
    sources = []
    for index, operator in enumerate(OPERATORS):
        for temporary in (False, True):
            model = fixture(operator, temporary=temporary)
            saved = deepcopy(model)
            source, details = subject.emit_source_state_model(model)
            assert model == saved
            assert details["case_count"] == 9
            assert "every_transition_matches_program" in details["theorems"]
            assert {"all_finite_cases_initial", "returned_states_are_terminal",
                "returned_bounded_states_are_terminal"} <= set(details["theorems"])
            assert not details["kernel_executed"] and not details["source_semantics_verified"]
            assert not details["capability_floor_eligible"]
            namespace = "Operation" + str(index) + "_" + str(int(temporary))
            sources.extend(["namespace " + namespace, source, "end " + namespace])
    receipt = lake("\n\n".join(sources))
    assert receipt["backend_executed"] and receipt["status"] == "passed", receipt


def test_singleton_and_maximum_domains_build_without_changing_the_scope():
    for domains in ({"left": {"lower": 2, "upper": 2}, "right": {"lower": -3, "upper": -3}},
            {"left": {"lower": -3, "upper": 4}, "right": {"lower": -3, "upper": 4}},
            {"left": {"lower": -1000000, "upper": -1000000}, "right": {"lower": 999937, "upper": 1000000}},
            {"left": {"lower": 999937, "upper": 1000000}, "right": {"lower": -1000000, "upper": -1000000}}):
        model = fixture("*", temporary=True, domains=domains)
        source, details = subject.emit_source_state_model(model)
        assert details["case_count"] in (1, 64)
        assert details["bounded_tla"]["max_steps"] == 1
        assert not details["bounded_tla"]["native_document"]["transitions"][0]["allows_stutter"]
        receipt = lake(source)
        assert receipt["status"] == "passed", receipt


def test_mutating_program_arithmetic_is_rejected_by_actual_case_theorems():
    source, _ = subject.emit_source_state_model(fixture())
    lines = source.splitlines()
    changed = 0
    for index, line in enumerate(lines):
        if line.startswith("def expression_") and " + " in line:
            lines[index] = line.replace(" + ", " - ")
            changed += 1
    assert changed == 1
    receipt = lake("\n".join(lines))
    assert receipt["backend_executed"] and receipt["status"] == "failed", receipt


def test_mutating_state_output_relation_is_rejected_by_correspondence_theorem():
    model = fixture()
    source, _ = subject.emit_source_state_model(model)
    selected = model["cases"][0]
    predicates = model["state_model"]["predicates"]
    position = next(i for i, row in enumerate(predicates) if row["predicate_id"] == selected["next_predicate_id"])
    fields = {row["variable_id"]: "v" + str(i) for i, row in enumerate(model["state_model"]["schema"]["variables"])}
    needle = "s." + fields[model["result_variable_id"]] + " = (" + str(selected["result"]) + " : Int)"
    replacement = "s." + fields[model["result_variable_id"]] + " = (" + str(selected["result"] + 1) + " : Int)"
    lines = source.splitlines()
    positions = [i for i, line in enumerate(lines) if line.startswith("def predicate_" + str(position) + " ")]
    assert len(positions) == 1 and needle in lines[positions[0]]
    lines[positions[0]] = lines[positions[0]].replace(needle, replacement)
    receipt = lake("\n".join(lines))
    assert receipt["backend_executed"] and receipt["status"] == "failed", receipt


@pytest.mark.parametrize("mutation", ["contradict_initial", "remove_returned_guard"])
def test_real_kernel_checks_initial_witnesses_and_returned_state_terminality(mutation):
    model = fixture()
    source, _ = subject.emit_source_state_model(model)
    predicates = model["state_model"]["predicates"]
    if mutation == "contradict_initial":
        position = next(i for i, row in enumerate(predicates) if row["role"] == "initial")
    else:
        position = next(i for i, row in enumerate(predicates)
            if row["predicate_id"] == model["cases"][0]["guard_predicate_id"])
    fields = {row["variable_id"]: "v" + str(i) for i, row in enumerate(model["state_model"]["schema"]["variables"])}
    field = fields[model["returned_variable_id"]]
    needle = "(s." + field + " = false)"
    replacement = "(s." + field + " = true)" if mutation == "contradict_initial" else "True"
    lines = source.splitlines()
    positions = [i for i, line in enumerate(lines) if line.startswith("def predicate_" + str(position) + " ")]
    assert len(positions) == 1 and needle in lines[positions[0]]
    lines[positions[0]] = lines[positions[0]].replace(needle, replacement)
    receipt = lake("\n".join(lines))
    assert receipt["backend_executed"] and receipt["status"] == "failed", receipt


@pytest.mark.parametrize("mutation", ["case_result", "input_domain", "source", "candidate", "missing_case", "extra_field"])
def test_stale_or_forged_model_cannot_be_used_as_saved_authority(mutation):
    model = fixture()
    if mutation == "case_result": model["cases"][0]["result"] += 1
    elif mutation == "input_domain": model["input_domains"]["left"]["upper"] += 1
    elif mutation == "source": model["source_text"] = model["source_text"].replace(" + ", " - ")
    elif mutation == "candidate": model["candidate_ir"]["document"]["operator"] = "-"
    elif mutation == "missing_case": model["cases"].pop()
    else: model["assume_correct"] = True
    with pytest.raises(ValueError):
        subject.emit_source_state_model(model)
