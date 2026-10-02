"""Source-derived return tables preserve exact candidates and finite inputs."""
from copy import deepcopy

import pytest

from ipfs_datasets_py.logic.formalization.autoencoder.security import source_state_model as subject
from ipfs_datasets_py.logic.formalization.autoencoder.security import source_program_binding_384_v2 as binding
from ipfs_datasets_py.logic.software_verification.program import ProgramIR
from ipfs_datasets_py.logic.software_verification.transitions import StateTransitionIR
from tests.unit.logic.formalization.autoencoder.test_security_source_program_binding_384_v2 import inputs


DOMAINS = {"capacity": {"lower": -1, "upper": 1}, "threshold": {"lower": 0, "upper": 1}}
EXPECTED = {
    "+": [-1, 0, 0, 1, 1, 2], "-": [-1, -2, 0, -1, 1, 0], "*": [0, -1, 0, 0, 0, 1],
    "<": [True, True, False, True, False, False], "<=": [True, True, True, True, False, True],
    ">": [False, False, False, False, True, False], ">=": [False, False, True, False, True, True],
    "==": [False, False, True, False, False, True], "!=": [True, True, False, True, True, False],
}


def fixture(operator="-", temporary=True):
    source, candidate = inputs(operator, temporary)
    return source, candidate, deepcopy(DOMAINS)


@pytest.mark.parametrize("operator", EXPECTED)
@pytest.mark.parametrize("temporary", [False, True])
def test_all_nine_operators_and_temporary_forms_preserve_the_actual_results(operator, temporary):
    source, candidate, domains = fixture(operator, temporary)
    saved = deepcopy((source, candidate, domains))
    report = subject.derive_source_state_model(source, candidate, domains)
    assert (source, candidate, domains) == saved
    assert report["case_count"] == 6 and report["all_input_combinations_enumerated"]
    results = [row["result"] for row in report["cases"]]
    assert results == EXPECTED[operator]
    assert all(type(result) is (int if operator in "+-*" else bool) for result in results)
    assert report["source_qualification"] == binding.qualify_source_candidate(source, candidate)
    assert report["source_program"] == report["source_qualification"]["projections"][0]["native_document"]
    assert StateTransitionIR.from_dict(report["state_model"]).to_dict() == report["state_model"]
    assert report["parameter_order"] == ["capacity", "threshold"]
    assert all(report[key] is False for key in subject.FALSE)
    assert report["provider_calls"] == report["solver_calls"] == 0
    assert subject.verify_source_state_model(report, source, candidate, domains) == report
    function = report["source_program"]["functions"][0]
    for row in report["cases"]:
        assert set(row["initial_symbols"]) == set(function["parameter_symbol_ids"])
        assert set(row["final_symbols"]) == set(function["parameter_symbol_ids"] + function["local_symbol_ids"])
        assert function["result_symbol_id"] not in row["initial_symbols"] | row["final_symbols"]
        for local in function["local_symbol_ids"]:
            assert row["final_symbols"][local] == row["result"]


def test_single_initial_predicate_retains_all_input_choices_and_terminal_observations():
    source, candidate, domains = fixture()
    report = subject.derive_source_state_model(source, candidate, domains)
    native = report["state_model"]
    predicates = {row["predicate_id"]: row for row in native["predicates"]}
    initial, = [row for row in native["predicates"] if row["role"] == "initial"]
    assert initial["expression"] == {"state:result": 0, "state:returned": False}
    actions = {row["action_id"]: row for row in native["actions"]}
    for case in report["cases"]:
        action = actions[case["action_id"]]
        guard = predicates[action["guard_predicate_id"]]["expression"]
        following = predicates[action["next_predicate_id"]]["expression"]
        assert guard == case["initial_state"] and following == case["final_state"]
        assert set(guard) == set(following) == set(action["frame"]["reads"])
        assert action["frame"]["writes"] == ["state:result", "state:returned"]
        assert guard["state:returned"] is False and following["state:returned"] is True
        assert not action["enables_stutter"]
        for variable in report["parameter_variables"].values():
            assert guard[variable] == following[variable]
        # Every final state disables every action, including when the result
        # happens to equal the observation's initial zero sentinel.
        assert not any(all(type(case["final_state"][key]) is type(value) and case["final_state"][key] == value
            for key, value in predicates[row["guard_predicate_id"]]["expression"].items()) for row in actions.values())
    assert native["transitions"][0]["allows_stutter"] is False
    assert not native["fairness"] and not native["variants"] and not native["valuations"] and native["kripke"] is None


def test_swapped_operand_order_is_preserved_and_cannot_borrow_an_unswapped_candidate():
    source, candidate, domains = fixture("-", False)
    source = source.replace("capacity - threshold", "threshold - capacity")
    with pytest.raises(subject.SourceStateModelError, match="mismatch"):
        subject.derive_source_state_model(source, candidate, domains)
    candidate["document"]["operand_ids"].reverse()
    candidate["document"]["evaluation_order"].reverse()
    report = subject.derive_source_state_model(source, candidate, domains)
    assert [row["result"] for row in report["cases"]] == [1, 2, 0, 1, -1, 0]


@pytest.mark.parametrize("domains,reason", [
    ({}, "exact_source_parameter"),
    ({"capacity": {"lower": 0, "upper": 1}}, "exact_source_parameter"),
    ({**DOMAINS, "unknown": {"lower": 0, "upper": 1}}, "exact_source_parameter"),
    ({**DOMAINS, "capacity": {"lower": 0, "upper": 1, "sample": True}}, "closed_integer"),
    ({**DOMAINS, "capacity": {"lower": False, "upper": 1}}, "excludes_Boolean"),
    ({**DOMAINS, "capacity": {"lower": 0, "upper": True}}, "excludes_Boolean"),
    ({**DOMAINS, "capacity": {"lower": 0.0, "upper": 1}}, "excludes_Boolean"),
    ({**DOMAINS, "capacity": {"lower": "0", "upper": 1}}, "excludes_Boolean"),
    ({**DOMAINS, "capacity": {"lower": 2, "upper": 1}}, "nonempty_bounded"),
    ({**DOMAINS, "capacity": {"lower": -1000001, "upper": -1000001}}, "nonempty_bounded"),
    ({**DOMAINS, "capacity": {"lower": 1000001, "upper": 1000001}}, "nonempty_bounded"),
    ({"capacity": {"lower": 0, "upper": 64}, "threshold": {"lower": 0, "upper": 0}}, "exceeds_64"),
    ({"capacity": {"lower": 0, "upper": 7}, "threshold": {"lower": 0, "upper": 8}}, "exceeds_64"),
])
def test_unknown_empty_ill_typed_or_oversized_domains_are_rejected_whole(domains, reason):
    source, candidate, _ = fixture()
    saved = deepcopy(domains)
    with pytest.raises(subject.SourceStateModelError, match=reason):
        subject.derive_source_state_model(source, candidate, domains)
    assert domains == saved


def test_boundary_64_combinations_are_all_kept_and_large_valid_outputs_are_not_clamped():
    source, candidate, _ = fixture("*", False)
    domains = {name: {"lower": -3, "upper": 4} for name in ("capacity", "threshold")}
    report = subject.derive_source_state_model(source, candidate, domains)
    assert len(report["cases"]) == report["case_count"] == 64
    assert len({tuple(row["parameter_values"].items()) for row in report["cases"]}) == 64
    domains = {name: {"lower": 1000000, "upper": 1000000} for name in domains}
    report = subject.derive_source_state_model(source, candidate, domains)
    assert report["cases"][0]["result"] == 1000000000000
    variable = next(v for v in report["state_model"]["schema"]["variables"] if v["variable_id"] == "state:result")
    assert variable["domain_bound"]["lower"] == 0 and variable["domain_bound"]["upper"] == 1000000000000


@pytest.mark.parametrize("change", ["operator", "operand_order", "source_type", "literal", "branch", "call", "reassignment"])
def test_no_source_fallback_repairs_a_wrong_candidate_or_unsupported_source(change):
    source, candidate, domains = fixture("-", False)
    if change == "operator": candidate["document"]["operator"] = "+"
    elif change == "operand_order": candidate["document"]["operand_ids"].reverse()
    elif change == "source_type": source = source.replace(": int", "")
    elif change == "literal": source = source.replace("capacity - threshold", "capacity - 1")
    elif change == "branch": source = source.replace("    return capacity - threshold", "    if capacity > threshold:\n        return capacity\n    return threshold")
    elif change == "call": source = source.replace("capacity - threshold", "helper(capacity, threshold)")
    else: source = source.replace("    return capacity - threshold", "    capacity = capacity - threshold\n    return capacity")
    saved = deepcopy(candidate)
    with pytest.raises(subject.SourceStateModelError, match="source_candidate_"):
        subject.derive_source_state_model(source, candidate, domains)
    assert candidate == saved


@pytest.mark.parametrize("mutation", ["source", "domain", "result", "omit_case", "effects", "state_guard", "authority", "extra"])
def test_rehashed_reports_cannot_bypass_exact_source_candidate_and_case_replay(mutation):
    source, candidate, domains = fixture()
    report = subject.derive_source_state_model(source, candidate, domains)
    if mutation == "source": source += "# changed exact source\n"
    elif mutation == "domain": domains["capacity"]["upper"] = 0
    elif mutation == "result": report["cases"][0]["result"] = 999
    elif mutation == "omit_case": report["cases"].pop()
    elif mutation == "effects": report["source_program"]["functions"][0]["effects"]["reads"] = []
    elif mutation == "state_guard":
        next(row for row in report["state_model"]["predicates"] if row["role"] == "guard")["expression"]["state:returned"] = True
    elif mutation == "authority": report["source_semantics_verified"] = True
    else: report["trusted"] = True
    report.pop("report_sha256")
    report["report_sha256"] = subject._digest(report)
    with pytest.raises(subject.SourceStateModelError, match="exact_replay"):
        subject.verify_source_state_model(report, source, candidate, domains)


def _rebuild(program):
    program["program_id"] = ""
    return ProgramIR.from_dict(program).to_dict()


@pytest.mark.parametrize("scope", ["function", "command"])
def test_evaluator_rejects_external_effects_instead_of_computing_a_pure_answer(scope):
    source, candidate, domains = fixture()
    report = subject.derive_source_state_model(source, candidate, domains)
    program = deepcopy(report["source_program"])
    program["functions" if scope == "function" else "commands"][0]["effects"]["performs_io"] = True
    if scope == "command":
        with pytest.raises(ValueError, match="effects exceed function"):
            subject._evaluate_program(_rebuild(program), report["cases"][0]["parameter_values"])
        return
    program = _rebuild(program)
    with pytest.raises(subject.SourceStateModelError, match="external_effect"):
        subject._evaluate_program(program, report["cases"][0]["parameter_values"])


def test_evaluator_rejects_uninitialized_result_and_incomplete_read_summaries():
    source, candidate, domains = fixture()
    report = subject.derive_source_state_model(source, candidate, domains)
    program = deepcopy(report["source_program"])
    function = program["functions"][0]
    temporary = function["local_symbol_ids"][0]
    expression = next(row for row in program["expressions"] if row["symbol_ids"] == [temporary])
    expression["symbol_ids"] = [function["result_symbol_id"]]
    with pytest.raises(ValueError, match="initialized"):
        subject._evaluate_program(_rebuild(program), report["cases"][0]["parameter_values"])
    program = deepcopy(report["source_program"])
    command = next(row for row in program["commands"] if row["kind"] == "assign")
    command["effects"]["reads"] = []
    with pytest.raises(subject.SourceStateModelError, match="command_effects"):
        subject._evaluate_program(_rebuild(program), report["cases"][0]["parameter_values"])


def test_parameter_named_returned_does_not_collide_with_observation_state_slots():
    source, candidate, domains = fixture("+", False)
    source = source.replace("capacity", "returned")
    candidate["document"]["operand_ids"][0] = "expr:returned"
    candidate["document"]["evaluation_order"][0] = "expr:returned"
    domains["returned"] = domains.pop("capacity")
    report = subject.derive_source_state_model(source, candidate, domains)
    assert report["parameter_variables"]["returned"] != report["returned_variable_id"]
    assert [row["result"] for row in report["cases"]] == EXPECTED["+"]
