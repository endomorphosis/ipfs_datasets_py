"""Authored source joins and conditional math, never a proof of NumPy execution."""
from copy import deepcopy
import hashlib
import json
import os

import pytest

from ipfs_datasets_py.logic.software_verification import numerical_logic as logic


SOURCE = '''import numpy as np
def choose(matrix):
    values, vectors = np.linalg.eig(matrix)
    selected = np.argmax(np.abs(values))
    return values[selected], vectors[:, selected]
'''


def prepare(source=SOURCE):
    return logic.formalize_numerical_source(source, path="authored.py")


def test_compound_joins_exact_source_commands_expressions_and_pending_families():
    report = prepare()
    contract, = report["compound_contracts"]
    program = report["structural"]["program"]
    expressions = {row["expression_id"]: row for row in program["expressions"]}
    commands = {row["command_id"]: row for row in program["commands"]}
    symbols = {row["symbol_id"]: row["name"] for row in program["symbols"]}
    roles = contract["roles"]
    assert [symbols[row["symbol_id"]] for row in contract["tuple_components"]] == ["values", "vectors"]
    assert [row["component"] for row in contract["tuple_components"]] == [0, 1]
    for command_role, expression_role in [
        ("eig_assignment_command", "eig_expression"),
        ("selection_assignment_command", "selection_expression"), ("return_command", "return_expression")]:
        assert commands[roles[command_role]]["expression_ids"] == [roles[expression_role]]
    selected = expressions[roles["selection_expression"]]
    assert selected["operand_ids"][1] == roles["magnitude_expression"]
    for expression_role, symbol_role in [("returned_value_expression", "values_symbol"),
                                         ("returned_vector_expression", "vectors_symbol")]:
        receiver = expressions[expressions[roles[expression_role]]["operand_ids"][0]]
        assert receiver["symbol_ids"] == [roles[symbol_role]]
    pending = {row["obligation_id"]: row for row in report["pending_obligations"]}
    assert len(contract["obligation_ids"]) == 7
    fol = {row["obligation_id"] for row in report["projections"]["first_order"]}
    lean = {row["obligation_id"] for row in report["projections"]["lean"]["bindings"]}
    for key in contract["obligation_ids"]:
        row = pending[key]
        assert row["roles"]["compound_contract_id"] == contract["contract_id"]
        assert row["expression_id"] == roles["return_expression"]
        assert row["span_ids"] == contract["span_ids"]
        assert row["function_ids"] == [contract["function_id"]]
        assert row["status"] == "pending" and key in fol
        assert (key in lean) is (row["kind"] != "selected_eigenpair_runtime_interpretation")
        assert not row["assumptions_asserted"] and not row["proof_authority"]
    assert contract["pattern_status"] == "matched_syntax_only"
    assert contract["tolerance_policy"] == "unresolved_no_defaults_assumed"
    assert not contract["runtime_identity_verified"]
    assert all(contract[key] is False for key in logic._FALSE)
    assert report["coverage"]["source_obligations_discharged"] == 0
    assert contract["source_obligations_discharged"] == 0


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_compound_spans_are_exact_raw_bytes_after_unicode_comments(newline):
    statements = ["values, vectors = np.linalg.eig(matrix)",
                  "selected = np.argmax(np.abs(values))",
                  "return values[selected], vectors[:, selected]"]
    source = newline.join(["# π 🍋\u2028 still a comment", "import numpy as np",
        "def choose(matrix):", '    """Choose a pair."""',
        "    " + statements[0] + "  # café", "    " + statements[1],
        "    " + statements[2], ""])
    report = prepare(source)
    contract, = report["compound_contracts"]
    raw = source.encode("utf-8")
    assert contract["source_sha256"] == hashlib.sha256(raw).hexdigest()
    spans = {row["span_id"]: row for row in report["structural"]["program"]["spans"]}
    for span_id, statement in zip(contract["span_ids"], statements, strict=True):
        expected = statement.encode("utf-8")
        start = raw.index(expected)
        span = spans[span_id]
        assert (span["start_byte"], span["end_byte"]) == (start, start + len(expected))
        assert raw[span["start_byte"]:span["end_byte"]] == expected


@pytest.mark.parametrize("source", [
    SOURCE.replace("np", "nx").replace("values", "roots").replace("vectors", "basis"),
    SOURCE.replace("import numpy as np", "import numpy").replace("np.", "numpy."),
    SOURCE.replace("import numpy as np", "from numpy.linalg import eig as solve\nfrom numpy import argmax, abs as magnitude")
        .replace("np.linalg.eig", "solve").replace("np.argmax", "argmax").replace("np.abs", "magnitude"),
    SOURCE.replace("eig(matrix)", "eig(a=matrix)").replace("argmax(np.abs(values))", "argmax(a=np.abs(values))"),
    SOURCE.replace("values, vectors =", "[values, vectors] ="),
    SOURCE.replace("    values,", "    pass\n    values,"),
])
def test_renaming_aliases_and_supported_call_shapes_preserve_contract(source):
    report = prepare(source)
    assert len(report["compound_contracts"]) == 1
    assert report["compound_contract_assessments"][0]["status"] == "matched_syntax_only"


@pytest.mark.parametrize("old,new", [
    ("eig(matrix)", "eig(matrix, other)"),
    ("eig(matrix)", "eig(b=matrix)"),
    ("np.abs(values)", "np.abs(x=values)"),
    ("np.abs(values)", "np.abs(values, out=values)"),
    ("argmax(np.abs(values))", "argmax(np.abs(values), axis=0)"),
    ("argmax(np.abs(values))", "argmax(np.abs(values), keepdims=True)"),
    ("argmax(np.abs(values))", "argmax(np.abs(values), out=values)"),
    ("argmax", "argmin"), ("argmax", "argsort"), ("linalg.eig", "linalg.eigh"),
    ("np.abs(values)", "values"), ("np.abs(values)", "values.real"),
    ("np.abs(values)", "np.abs(vectors)"),
    ("values[selected], vectors[:, selected]", "vectors[selected], values[:, selected]"),
    ("values[selected], vectors[:, selected]", "values[selected], vectors[:, 0]"),
    ("values[selected], vectors[:, selected]", "values[0], vectors[:, selected]"),
    ("vectors[:, selected]", "vectors[selected, :]"),
    ("vectors[:, selected]", "vectors[1:, selected]"),
    ("vectors[:, selected]", "vectors[::1, selected]"),
    ("vectors[:, selected]", "vectors[None, selected]"),
    ("vectors[:, selected]", "vectors[[0], selected]"),
    ("vectors[:, selected]", "vectors[:, selected + 1]"),
    ("return values[selected], vectors[:, selected]", "return [values[selected], vectors[:, selected]]"),
    ("values, vectors =", "values, values ="),
    ("values, vectors =", "matrix, vectors ="),
    ("selected =", "values ="),
    ("selected =", "matrix ="),
    ("def choose(matrix)", "def choose(matrix, extra)"),
])
def test_unmatched_call_shapes_indices_and_rebindings_abstain(old, new):
    source = SOURCE.replace(old, new)
    assert source != SOURCE
    report = prepare(source)
    assert report["compound_contracts"] == []
    assert report["summary"]["compound_contract_count"] == 0
    assert all(row["status"] == "not_matched" for row in report["compound_contract_assessments"])


@pytest.mark.parametrize("statement", [
    "values = other", "vectors = other", "selected = 0", "side_effect()",
    "values[0] = 9", "matrix[0] = 9", "np.linalg.eig = other", "np = other",
    "if matrix:\n        side_effect()", "for x in matrix:\n        pass",
    "global values", "nonlocal values", "assert ready", "import numpy as other",
])
def test_intervening_mutations_effects_or_control_flow_abstain(statement):
    source = SOURCE.replace("    return ", "    " + statement + "\n    return ")
    report = prepare(source)
    assert report["compound_contracts"] == []


@pytest.mark.parametrize("prefix", ["np = other", "np.linalg.eig = other", "del np.linalg.eig"])
def test_module_alias_mutation_does_not_inherit_declared_numpy_contract(prefix):
    report = prepare(SOURCE.replace("def choose", prefix + "\ndef choose"))
    assert report["compound_contracts"] == []


def test_other_partial_function_does_not_hide_supported_function_or_invent_contract():
    report = prepare(SOURCE + "\ndef loop(a):\n    for x in a:\n        print(x)\n    return a\n")
    assert len(report["compound_contracts"]) == 1
    assert [row["status"] for row in report["compound_contract_assessments"]] == ["matched_syntax_only", "not_matched"]
    assert report["compound_contract_assessments"][1]["reason"] == "incomplete_or_unsupported_function"
    report = prepare("def f(:\n")
    assert report["compound_contracts"] == [] and report["compound_contract_assessments"] == []
    assert report["summary"]["compound_contract_count"] == 0


def test_summaries_are_bounded_and_compound_obligations_count_toward_limit():
    body = SOURCE.split("\n", 1)[1]
    source = "import numpy as np\n" + "\n".join(body.replace("choose(", f"choose{i}(") for i in range(12))
    report = prepare(source)
    summary = report["summary"]
    rows = summary["compound_contracts"]
    assert summary["compound_contract_count"] == 12
    assert 0 < len(rows) <= 8
    assert len(json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()) <= 4096
    assert summary["omitted_compound_contract_summaries"] == 12 - len(rows)
    assert all(row["status"] == "pending" and not row["proof_authority"] for row in rows)
    # 17*9 atomic obligations fits the old limit; adding 17*7 compound ones does not.
    source = "import numpy as np\n" + "\n".join(body.replace("choose(", f"choose{i}(") for i in range(17))
    with pytest.raises(logic.NumericalLogicError, match="count exceeds bound"):
        prepare(source)


@pytest.mark.parametrize("field", ["roles", "span", "id", "tolerance", "authority", "summary"])
def test_exact_replay_rejects_compound_tampering_even_with_rehashed_report(field):
    report = deepcopy(prepare())
    contract = report["compound_contracts"][0]
    if field == "roles":
        contract["roles"]["returned_vector_expression"] = contract["roles"]["returned_value_expression"]
    elif field == "span":
        contract["span_ids"] = contract["span_ids"][:1]
    elif field == "id":
        contract["contract_id"] = "numerical-contract:" + "0" * 32
    elif field == "tolerance":
        contract["tolerance_policy"] = "assume_default"
    elif field == "authority":
        contract["proof_authority"] = True
    else:
        report["summary"]["compound_contracts"][0]["status"] = "proved"
    report.pop("report_sha256")
    report["report_sha256"] = logic._sha(report)
    with pytest.raises(logic.NumericalLogicError, match="differs"):
        logic.validate_numerical_logic_report(report, SOURCE, path="authored.py")


def test_preparation_runs_no_code_models_or_solvers(monkeypatch):
    import subprocess
    def forbidden(*args, **kwargs):
        raise AssertionError("source/solver/provider execution forbidden during preparation")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    report = prepare()
    assert report["provider_calls"] == report["solver_calls"] == 0
    assert report["training_performed"] is False
    assert not report["source_executed"] and not report["model_inference_executed"]
    assert logic.validate_numerical_logic_report(json.loads(json.dumps(report)), SOURCE, path="authored.py") == report
    artifact = report["projections"]["lean"]
    assert "axiom " not in artifact["source"] and "sorry" not in artifact["source"]
    assert "selected_column_contract" in artifact["conditional_lemmas"]
    assert artifact["source_obligations_discharged"] == 0


@pytest.mark.skipif(not os.environ.get("IPFS_NUMERICAL_TEST_LAKE"), reason="explicit installed native Lake required")
@pytest.mark.parametrize("negative", [False, True])
def test_native_lake_conditional_contract_and_zero_vector_refutation(negative):
    from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lake_v4 import _execute
    artifact = prepare()["projections"]["lean"]
    authored = '''
namespace NumericalObligations
-- An exact residual alone admits the zero vector, so nonzero must be separate.
example : EigenpairResidual (0 : Int) (· + ·) (· * ·) 1
    (fun _ _ => 7) (fun _ => 0) 99 := by
  intro row _
  simp [finiteSum]
example : ¬ NonzeroVector (0 : Int) 1 (fun _ => 0) := by
  intro h
  obtain ⟨row, _, nonzero⟩ := h
  exact nonzero rfl
end NumericalObligations
'''
    if negative:
        authored = authored.replace("example : ¬ NonzeroVector", "example : NonzeroVector")
    result = _execute(artifact["source"] + authored, artifact["library"],
                      os.environ["IPFS_NUMERICAL_TEST_LAKE"], 60)
    assert result["backend_executed"] is True
    assert result["status"] == ("failed" if negative else "passed")
    assert (result["returncode"] == 0) is not negative
    assert artifact["source_obligations_discharged"] == 0
