"""Authored assertion provenance; observations are not function specifications."""
from copy import deepcopy
import hashlib
import json
import os

import pytest

from ipfs_datasets_py.logic.software_verification import numerical_logic as logic


SOURCE = '''import numpy as np
from engine import solve
def check(matrix):
    value, vector = solve(matrix)
    assert not np.allclose(vector, 0), "zero"
    assert not np.isnan(value), "nan"
    assert not np.isinf(value), "inf"
    assert np.allclose(matrix @ vector, value * vector), f"bad {vector}"
'''


def prepare(source=SOURCE):
    return logic.formalize_numerical_source(source, path="authored.py")


def expressions(report):
    return {row["expression_id"]: row for row in report["structural"]["program"]["expressions"]}


def test_four_assertion_predicates_keep_negation_and_argument_direction_without_invented_requirements():
    report = prepare()
    rows = report["assertion_requirements"]
    assert len(rows) == 4
    assert [(r["predicate"]["operator"], r["predicate"]["imported_callee"]) for r in rows] == [
        ("not", "numpy.allclose"), ("not", "numpy.isnan"),
        ("not", "numpy.isinf"), ("call", "numpy.allclose")]
    ex = expressions(report)
    last = rows[-1]
    left, right = [ex[key] for key in last["predicate"]["argument_expression_ids"]]
    assert (left["operator"], right["operator"]) == ("matmul", "mul")
    assert report["compound_contracts"] == []
    assert report["summary"]["partial_or_unsupported_functions"] == 1
    assert report["assertion_requirement_assessments"][0]["reason"] == "deferred_failure_message"
    assert last["failure_message_structure_lowered"] is False
    for row in rows:
        assert row["origin"] == "source_assertion" and row["status"] == "pending"
        assert row["unknown_effects"] and not row["function_postcondition_inferred"]
        assert not row["assertion_execution_verified"] and not row["runtime_truthiness_verified"]
        assert not row["runtime_identity_verified"] and not row["assumptions_asserted"]
        assert all(row[key] is False for key in logic._FALSE)
        assert row["comparison_policy"] == "explicit_source_arguments_only_no_library_defaults_assumed"
        assert row["source_obligations_discharged"] == 0
    kinds = {r["kind"] for r in report["pending_obligations"]}
    assert not kinds & {"selected_eigenpair_nonzero", "selected_eigenpair_finite",
                        "selected_eigenpair_magnitude_selection", "selected_eigenpair_approximate_residual"}
    assert report["coverage"]["source_obligations_discharged"] == 0


def test_callable_and_tuple_component_relationships_are_replayable_source_links():
    report = prepare()
    ex = expressions(report)
    symbols = {r["symbol_id"]: r["name"] for r in report["structural"]["program"]["symbols"]}
    commands = {r["command_id"]: r for r in report["structural"]["program"]["commands"]}
    obligations = {r["obligation_id"]: r for r in report["pending_obligations"]}
    fol = {r["obligation_id"]: r for r in report["projections"]["first_order"]}
    lean = {r["obligation_id"]: r for r in report["projections"]["lean"]["bindings"]}
    for row in report["assertion_requirements"]:
        command = commands[row["command_id"]]
        assert command["kind"] == "assert"
        assert command["expression_ids"] == [row["predicate_expression_id"]]
        assert command["span_ids"] == row["span_ids"]
        for definition in row["symbol_definitions"]:
            source_call = ex[definition["value_expression_id"]]
            assert source_call["attributes"]["imported_callee"] == "engine.solve"
            name = symbols[definition["symbol_id"]]
            assert definition["component_path"] == ([0] if name == "value" else [1])
            assert definition["binding_kind"] == "lexical_reaching_assignment_not_runtime_value"
        obligation = obligations[row["obligation_id"]]
        assert obligation["roles"]["requirement_id"] == row["requirement_id"]
        assert obligation["expression_id"] == row["predicate_expression_id"]
        assert obligation["function_ids"] == [row["function_id"]]
        assert row["obligation_id"] in fol and row["obligation_id"] in lean
        assert fol[row["obligation_id"]]["predicate_interpretation"] == "unresolved; no axiom asserted"
        assert lean[row["obligation_id"]]["definition"] == (
            "NegatedCallPredicate" if row["predicate"]["operator"] == "not" else "CallPredicate")


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_predicate_span_bytes_preserve_unicode_comments_and_failure_messages(newline):
    statement = 'assert np.allclose(a, b), f"résidu λ {a}"'
    source = newline.join(["# café 🍋\u2028 comment", "import numpy as np", "def check(a, b):",
                           "    " + statement, ""])
    report = prepare(source)
    row, = report["assertion_requirements"]
    raw = source.encode("utf-8")
    span = next(s for s in report["structural"]["program"]["spans"] if s["span_id"] == row["span_ids"][0])
    expected = statement.encode("utf-8")
    assert (span["start_byte"], span["end_byte"]) == (raw.index(expected), raw.index(expected) + len(expected))
    assert raw[span["start_byte"]:span["end_byte"]] == expected
    assert row["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert row["failure_message_structure_lowered"] is False


def test_keyword_literals_and_comparison_direction_remain_exact_without_default_tolerance():
    source = "import numpy as np\ndef check(a, b):\n    assert np.allclose(b, a, rtol=0.25, atol=0.0, equal_nan=True)\n"
    report = prepare(source)
    row, = report["assertion_requirements"]
    ex = expressions(report)
    symbols = {r["symbol_id"]: r["name"] for r in report["structural"]["program"]["symbols"]}
    args = [ex[key] for key in row["predicate"]["argument_expression_ids"]]
    assert [symbols[a["symbol_ids"][0]] for a in args[:2]] == ["b", "a"]
    assert row["predicate"]["keyword_names"] == ["rtol", "atol", "equal_nan"]
    assert [a["attributes"].get("value_hex") for a in args[2:4]] == [float(0.25).hex(), float(0).hex()]
    assert args[4]["attributes"]["value"] is True
    assert not row["runtime_identity_verified"]


def test_rebinding_versions_use_previous_rhs_binding_not_the_new_lhs():
    source = "def check(seed):\n    x = first(seed)\n    x = second(x)\n    assert valid(x)\n"
    row, = prepare(source)["assertion_requirements"]
    assert len(row["symbol_definitions"]) == 2
    direct = next(use["definition_id"] for use in row["symbol_uses"] if use["definition_id"] is not None)
    definitions = {r["definition_id"]: r for r in row["symbol_definitions"]}
    current = definitions[direct]
    prior, = current["input_definition_ids"]
    assert prior != direct and definitions[prior]["input_definition_ids"] == []
    assert definitions[prior]["symbol_id"] == current["symbol_id"]
    assert len(row["intervening_effect_command_ids"]) == 2 and row["unknown_effects"]


def test_simultaneous_unpacking_preserves_nested_components_and_rhs_environment():
    source = "def check(seed):\n    a = seed\n    (a, (b, c)) = split(a)\n    assert valid(a, b, c)\n"
    row, = prepare(source)["assertion_requirements"]
    direct = {u["definition_id"] for u in row["symbol_uses"] if u["definition_id"] is not None}
    definitions = {r["definition_id"]: r for r in row["symbol_definitions"]}
    assert {tuple(definitions[key]["component_path"]) for key in direct} == {(0,), (1, 0), (1, 1)}
    dependencies = {tuple(definitions[key]["input_definition_ids"]) for key in direct}
    old, = dependencies
    assert len(old) == 1 and old[0] not in direct


def test_duplicate_unpack_target_retains_no_ambiguous_definition_witness():
    row, = prepare("def check(seed):\n    a, a = split(seed)\n    assert valid(a)\n")["assertion_requirements"]
    assert row["symbol_definitions"] == []
    assert all(use["definition_id"] is None for use in row["symbol_uses"])


@pytest.mark.parametrize("source", [
    "def check(np, x):\n    assert not np.isnan(x)\n",
    "import numpy as np\nnp = other\ndef check(x):\n    assert not np.isnan(x)\n",
    "import numpy as np\ndef check(x):\n    np = other\n    assert not np.isnan(x)\n",
])
def test_shadowed_call_remains_a_generic_requirement_not_numpy_interpretation(source):
    row, = prepare(source)["assertion_requirements"]
    assert row["predicate"]["operator"] == "not"
    assert row["predicate"]["imported_callee"] is None
    assert row["predicate"]["callee_resolution"] == "unresolved_or_shadowed"


def test_intervening_call_effects_are_explicit_without_dropping_syntactic_definition():
    row, = prepare("def check(seed):\n    x = make(seed)\n    mutate(x)\n    assert valid(x)\n")["assertion_requirements"]
    assert len(row["symbol_definitions"]) == 1
    assert len(row["intervening_effect_command_ids"]) == 2
    assert row["unknown_effects"] and not row["source_semantics_verified"]


@pytest.mark.parametrize("body", [
    "if x:\n        assert valid(x)",
    "for y in x:\n        assert valid(y)",
    "assert valid(x)\n    if x:\n        mutate(x)",
    "x[0] = 0\n    assert valid(x)",
    "assert valid(*x)",
    "global x\n    assert valid(x)",
    "return x\n    assert valid(x)",
])
def test_control_flow_or_other_unsupported_constructs_fence_function(body):
    report = prepare("def check(x):\n    " + body + "\n")
    assert report["assertion_requirements"] == []
    assert report["assertion_requirement_assessments"][0]["status"] == "not_scanned"


@pytest.mark.parametrize("predicate", ["x", "not x", "x + 1", "x < 2", "not not valid(x)"])
def test_generic_predicate_does_not_invent_call_or_boolean_runtime_interpretation(predicate):
    report = prepare("def check(x):\n    assert " + predicate + "\n")
    row, = report["assertion_requirements"]
    assert row["predicate"]["operator"] == "expression"
    assert row["predicate"]["call_expression_id"] is None
    bindings = report["projections"]["lean"]["bindings"]
    assert next(r for r in bindings if r["obligation_id"] == row["obligation_id"])["definition"] == "AssertionPredicate"


def test_source_assertions_have_no_smt_discharge_or_implicit_truth_assumption():
    report = prepare("def check(x):\n    assert x\n")
    assert report["projections"]["smt"] == []
    assert len(report["pending_obligations"]) == 1
    assert report["pending_obligations"][0]["status"] == "pending"
    assert not report["pending_obligations"][0]["assumptions_asserted"]


def test_summary_counts_bounds_and_total_obligation_limit_include_assertions():
    report = prepare("def check(x):\n" + "    assert valid(x)\n" * 8)
    summary = report["summary"]
    assert summary["assertion_requirement_count"] == 8
    rows = summary["assertion_requirements"]
    assert 0 < len(rows) <= 4
    assert len(logic._raw(rows)) <= 4096
    assert summary["omitted_assertion_requirement_summaries"] == 8 - len(rows)
    assert all(not row["proof_authority"] and row["unknown_effects"] for row in rows)
    # Each ASSERT adds one requirement even when no call/atomic obligation exists.
    with pytest.raises(logic.NumericalLogicError, match="count exceeds bound"):
        prepare("def check(x):\n" + "    assert x\n" * 257)


def test_compact_definition_ids_join_full_versioned_records_without_inlining_dependencies():
    source = "def check(seed):\n    x = first(seed)\n    x = second(x)\n    assert valid(x)\n"
    report = prepare(source)
    full, = report["assertion_requirements"]
    compact, = report["summary"]["assertion_requirements"]
    definition, = compact["symbol_definitions"]
    direct_ids = {use["definition_id"] for use in full["symbol_uses"] if use["definition_id"] is not None}
    assert {definition["definition_id"]} == direct_ids
    complete = next(row for row in full["symbol_definitions"] if row["definition_id"] == definition["definition_id"])
    assert len(complete["input_definition_ids"]) == 1
    assert "input_definition_ids" not in definition
    assert definition == {key: complete[key] for key in definition}
    assert compact["requirement_id"] == full["requirement_id"]
    # A consumer may forward these flat IDs while the source-replayed report
    # retains the dependency graph; no extra planner nesting is required.
    assert all(type(key) is str for key in direct_ids)
    assert not compact["proof_authority"] and compact["unknown_effects"]


@pytest.mark.parametrize("field", ["predicate", "definition", "span", "effects", "origin", "summary", "authority"])
def test_replay_rejects_assertion_binding_changes_even_after_rehash(field):
    report = deepcopy(prepare())
    row = report["assertion_requirements"][0]
    if field == "predicate":
        row["predicate"]["operator"] = "call"
    elif field == "definition":
        row["symbol_definitions"][0]["component_path"] = [0]
    elif field == "span":
        row["span_ids"] = []
    elif field == "effects":
        row["unknown_effects"] = False
    elif field == "origin":
        row["origin"] = "verified_postcondition"
    elif field == "summary":
        report["summary"]["assertion_requirement_count"] = 0
    else:
        row["proof_authority"] = True
    report.pop("report_sha256")
    report["report_sha256"] = logic._sha(report)
    with pytest.raises(logic.NumericalLogicError, match="differs"):
        logic.validate_numerical_logic_report(report, SOURCE, path="authored.py")


def test_preparation_replay_is_process_free_and_syntax_failure_has_no_ghost_requirements(monkeypatch):
    import subprocess
    def forbidden(*args, **kwargs):
        raise AssertionError("no source, provider or solver execution")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    report = prepare()
    assert report["provider_calls"] == report["solver_calls"] == 0
    assert logic.validate_numerical_logic_report(json.loads(json.dumps(report)), SOURCE, path="authored.py") == report
    bad = prepare("def f(:\n")
    assert bad["assertion_requirements"] == []
    assert bad["summary"]["assertion_requirement_count"] == 0


@pytest.mark.skipif(not os.environ.get("IPFS_NUMERICAL_TEST_LAKE"), reason="explicit native Lake required")
@pytest.mark.parametrize("negative", [False, True])
def test_native_lake_assertion_polarity_and_false_positive_rejection(negative):
    from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lake_v4 import _execute
    artifact = prepare()["projections"]["lean"]
    source = artifact["source"] + '''
namespace NumericalObligations
example : NegatedCallPredicate (fun _ : Unit => false) (fun x => x = true) () := by
  simp [NegatedCallPredicate]
end NumericalObligations
'''
    if negative:
        source = source.replace("example : NegatedCallPredicate", "example : CallPredicate")
    assert "axiom " not in source and "sorry" not in source
    result = _execute(source, artifact["library"], os.environ["IPFS_NUMERICAL_TEST_LAKE"], 60)
    assert result["backend_executed"] is True
    assert result["status"] == ("failed" if negative else "passed")
    assert (result["returncode"] == 0) is not negative
    assert artifact["source_obligations_discharged"] == 0
