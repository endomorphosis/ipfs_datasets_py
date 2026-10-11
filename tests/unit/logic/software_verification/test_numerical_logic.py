"""Authored numerical structure, unresolved obligations and native projections."""
from copy import deepcopy
import hashlib
import json
import os

import pytest

from ipfs_datasets_py.logic.software_verification import numerical_logic as logic
from ipfs_datasets_py.logic.syntax_core.ast import TypedExpression


SOURCE = '''import numpy as np
def selected_pair(matrix):
    values, vectors = np.linalg.eig(matrix)
    chosen = np.argmax(values.real)
    return values[chosen], vectors[:, chosen]
'''


def prepare(source=SOURCE, path="authored.py"):
    return logic.formalize_numerical_source(source, path=path)


def test_native_registry_routes_and_lazy_public_api():
    from ipfs_datasets_py.logic.software_verification import formalize_numerical_source
    assert formalize_numerical_source is logic.formalize_numerical_source
    profile = logic.describe_numerical_logic_profile()
    assert profile["profile"] == "python-numerical-structure@1"
    assert {r["family"] for r in profile["routes"]} == {"program", "first_order", "higher_order"}
    assert {r["family"] for r in profile["unsupported_families"]} >= {
        "transition_system", "temporal", "separation_logic", "dcec", "tdfol", "frame_logic"}
    assert profile["solver_calls"] == profile["provider_calls"] == 0
    assert not profile["proof_authority"] and not profile["source_semantics_verified"]


def test_source_bound_obligations_are_pending_not_assumptions_or_proofs():
    report = prepare()
    assert report["structural"]["status"] == "translated"
    rows = report["pending_obligations"]
    assert {r["kind"] for r in rows} == {
        "matrix_shape", "eigenpair_residual", "selection", "index_safety", "slice_safety",
        "library_semantics_and_effects"}
    expressions = {r["expression_id"] for r in report["structural"]["program"]["expressions"]}
    source_refs = {r["ref_id"] for r in report["structural"]["program"]["sources"]}
    for row in rows:
        assert row["expression_id"] in expressions
        assert row["span_ids"] and set(row["source_ref_ids"]) <= source_refs
        assert row["function_ids"] and row["status"] == "pending"
        assert not row["assumptions_asserted"] and not row["proof_authority"]
    assert report["source_sha256"] == hashlib.sha256(SOURCE.encode()).hexdigest()
    assert SOURCE not in json.dumps(report)
    assert report["coverage"]["source_obligations_discharged"] == 0
    assert report["projections"]["program"]["bridge"]["status"] == "ok"


def test_fol_has_typed_referents_and_no_truth_axioms():
    report = prepare()
    for row in report["projections"]["first_order"]:
        typed = TypedExpression.from_dict(row["expression"])
        assert typed.to_dict() == row["expression"]
        assert typed.root.kind.value == "predicate"
        assert typed.root.arguments[0].symbol == "source_expression"
        assert row["predicate_interpretation"] == "unresolved; no axiom asserted"
        assert not row["proof_authority"]


def test_smt_reuses_shared_compiler_without_discharge_or_assumptions():
    report = prepare()
    rows = report["projections"]["smt"]
    assert len(rows) == 3  # shape plus two scalar-axis candidates, still abstract
    for row in rows:
        compilation = row["compilation"]
        script = compilation["script"]["source"]
        assert "SoftwareVerificationSMTCompiler@1" in script
        assert script.count("(assert ") == 1 and "(assert (not " in script
        assert "(check-sat)" in script and "(declare-const " in script
        assert row["interpretation_prerequisites"]
        assert not row["discharged"] and not row["solver_executed"]
    assert any("(= rows columns)" in r["compilation"]["script"]["source"] for r in rows)


def test_tuple_index_is_split_into_source_axes_not_coerced_to_an_integer():
    report = prepare()
    expressions = {e["expression_id"]: e for e in report["structural"]["program"]["expressions"]}
    for row in report["pending_obligations"]:
        if row["kind"] == "index_safety":
            index = expressions[row["roles"]["index_expression"]]
            assert index["kind"] == "symbol"
    assert {r["roles"]["syntactic_axis"] for r in report["pending_obligations"]
            if r["kind"] == "slice_safety"} == {0}


@pytest.mark.parametrize("index", ["None", "True", "1.5", "'name'", "[1, 2]"])
def test_known_nonscalar_index_is_not_projected_as_integer_bounds(index):
    report = prepare(f"def f(a):\n    return a[{index}]\n")
    assert {r["kind"] for r in report["pending_obligations"]} == {"indexing_semantics"}
    assert report["projections"]["smt"] == []


@pytest.mark.parametrize("callee,definition", [
    ("argmax", "SelectionMax"), ("argmin", "SelectionMin"), ("argsort", "Ordering")])
def test_selection_direction_and_permutation_template_follow_declared_call(callee, definition):
    report = prepare(f"import numpy as np\ndef f(a):\n    return np.{callee}(a)\n")
    assert [b["definition"] for b in report["projections"]["lean"]["bindings"]] == [definition]


def test_smt_constraints_are_not_valid_without_source_witnesses():
    z3 = pytest.importorskip("z3")
    for row in prepare()["projections"]["smt"]:
        solver = z3.Solver()
        solver.from_string(row["compilation"]["script"]["source"])
        assert solver.check() == z3.sat


@pytest.mark.parametrize("source", [
    "def f(np, a):\n    return np.linalg.eig(a)\n",
    "import numpy as np\ndef f(np, a):\n    return np.linalg.eig(a)\n",
    "import numpy as np\nnp = other\ndef f(a):\n    return np.linalg.eig(a)\n",
    "import numpy as np\ndef f(a):\n    np = other\n    return np.linalg.eig(a)\n",
    "def f(a):\n    return a.argsort()\n",
])
def test_unresolved_or_shadowed_calls_do_not_acquire_numpy_contracts(source):
    rows = prepare(source)["pending_obligations"]
    assert "library_semantics_and_effects" in {r["kind"] for r in rows}
    assert not {r["kind"] for r in rows} & {"matrix_shape", "eigenpair_residual", "selection"}


@pytest.mark.parametrize("source", [
    "from numpy.linalg import eig as solve\ndef f(a):\n    return solve(a)\n",
    "import numpy\ndef f(a):\n    return numpy.linalg.eigh(a=a)\n",
])
def test_declared_import_alias_and_keyword_are_source_bound_but_opaque(source):
    rows = prepare(source)["pending_obligations"]
    assert {r["kind"] for r in rows} == {
        "library_semantics_and_effects", "matrix_shape", "eigenpair_residual"}
    assert all(not r["source_semantics_verified"] for r in rows)


def test_summary_is_bounded_and_separates_structural_from_proof_coverage():
    report = prepare(SOURCE + "\ndef loop(a):\n    for x in a:\n        print(x)\n    return a\n")
    summary = report["summary"]
    assert summary["functions"] == 2
    assert summary["structurally_complete_functions"] == 1
    assert summary["partial_or_unsupported_functions"] == 1
    assert {f["status"] for f in summary["per_function"]} == {"partial", "structurally_complete"}
    assert summary["families_with_artifacts"] == ["program", "first_order", "higher_order"]
    assert len(json.dumps(summary).encode()) < 8192
    assert not summary["proof_authority"] and not summary["source_semantics_verified"]
    report = prepare("\n".join(f"def f{i}(a):\n    return a[0]\n" for i in range(20)))
    assert len(report["summary"]["per_function"]) == 16
    assert report["summary"]["omitted_function_summaries"] == 4
    assert report["summary"]["functions"] == 20


def test_syntax_failure_has_no_ghost_projection_or_lemmas():
    report = prepare("def f(:\n")
    assert report["structural"]["status"] == "unsupported"
    assert report["pending_obligations"] == []
    assert report["projections"] == dict(program=None, first_order=[], smt=[], lean=None)
    assert report["summary"]["families_with_artifacts"] == []


def test_obligation_bound_refuses_overflow_instead_of_silently_dropping_work():
    source = "import numpy as np\ndef f(a):\n" + "    np.linalg.eig(a)\n" * 90 + "    return a\n"
    with pytest.raises(logic.NumericalLogicError, match="count exceeds bound"):
        prepare(source)


def test_report_roundtrip_and_source_path_binding():
    report = prepare()
    assert logic.validate_numerical_logic_report(json.loads(json.dumps(report)), SOURCE, path="authored.py") == report
    for source, path in [(SOURCE + "# changed\n", "authored.py"), (SOURCE, "renamed.py")]:
        with pytest.raises(logic.NumericalLogicError, match="differs"):
            logic.validate_numerical_logic_report(report, source, path=path)


@pytest.mark.parametrize("field", ["authority", "obligation", "fol", "smt", "lean", "summary", "hash"])
def test_exact_replay_rejects_modified_artifacts_even_with_source_unchanged(field):
    report = deepcopy(prepare())
    if field == "authority":
        report["proof_authority"] = True
    elif field == "obligation":
        report["pending_obligations"][0]["status"] = "proved"
    elif field == "fol":
        report["projections"]["first_order"][0]["predicate_interpretation"] = "trusted"
    elif field == "smt":
        report["projections"]["smt"][0]["compilation"]["script"]["source"] += "(assert false)\n"
    elif field == "lean":
        report["projections"]["lean"]["source"] += "axiom trustMe : False\n"
    elif field == "summary":
        report["summary"]["source_semantics_verified"] = True
    else:
        report["report_sha256"] = "0" * 64
    with pytest.raises(logic.NumericalLogicError, match="differs"):
        logic.validate_numerical_logic_report(report, SOURCE, path="authored.py")


def test_preparation_makes_no_process_calls(monkeypatch):
    import subprocess
    def forbidden(*args, **kwargs):
        raise AssertionError("preparation must not invoke solvers/providers/source")
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    report = prepare()
    assert report["solver_calls"] == report["provider_calls"] == 0
    assert not report["source_executed"] and not report["model_inference_executed"]


def test_lean_source_has_explicit_residual_equation_and_no_admission():
    artifact = prepare()["projections"]["lean"]
    assert artifact["status"] == "prepared_not_built" and not artifact["lake_executed"]
    assert "finiteSum zero add (fun j => mul (matrix i j) (vector j)) n =" in artifact["source"]
    assert "axiom " not in artifact["source"] and "sorry" not in artifact["source"]
    assert artifact["source_obligations_discharged"] == 0
    assert not artifact["source_semantics_verified"]


@pytest.mark.skipif(not os.environ.get("IPFS_NUMERICAL_TEST_LAKE"),
                    reason="explicit installed native Lake executable required")
@pytest.mark.parametrize("negative", [False, True])
def test_actual_native_lake_conditional_lemmas_and_false_claim_rejection(negative):
    from ipfs_datasets_py.logic.formalization.autoencoder.native_family_lake_v4 import _execute
    artifact = prepare()["projections"]["lean"]
    source = artifact["source"]
    if negative:
        # Removing the nonempty premise makes extent=0 a counterexample.
        source = source.replace("(nonempty : 0 < extent)", "")
        assert source != artifact["source"]
    result = _execute(source, artifact["library"], os.environ["IPFS_NUMERICAL_TEST_LAKE"], 60)
    assert result["backend_executed"] is True
    assert result["status"] == ("failed" if negative else "passed")
    assert (result["returncode"] == 0) is not negative
    assert artifact["source_obligations_discharged"] == 0
