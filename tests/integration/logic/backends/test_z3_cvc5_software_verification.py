"""Integration contract: shared VCs through Z3 and CVC5 (LFV-030 / LFV-G041).

Acceptance covered here:

* both adapters run identical canonical VCs when available;
* explicit unavailability when a solver is missing;
* agreement on reviewed fixtures;
* disagreement evidence is preserved fail-closed;
* malformed solver output is rejected;
* versions, resources, and translation receipts are bound.
"""

from __future__ import annotations

import shutil

import pytest
from ipfs_datasets_py.logic.backends.cvc5.compiler import (
    CVC5_SOFTWARE_VERIFICATION_INTERFACE,
    CVC5Compiler,
    CVC5SoftwareVerificationBackend,
)
from ipfs_datasets_py.logic.backends.results import (
    ResultAuthority,
    ResultStatus,
    SatisfiabilityResult,
    TheoremResult,
)
from ipfs_datasets_py.logic.backends.smt.compiler import (
    BOOL_SORT,
    INT_SORT,
    SMT_COMPILER_ID,
    SmtFunDecl,
    SmtNamedAssertion,
    SmtObligation,
    SmtQueryMode,
    SmtTerm,
    SmtTermKind,
    SoftwareVerificationSMTCompiler,
    term_eq,
    term_int,
    term_symbol,
    term_true,
)
from ipfs_datasets_py.logic.backends.smt.differential import (
    DifferentialClassification,
    MalformedSmtSolverOutput,
    SmtDifferentialReport,
    SmtDifferentialVerifier,
    SmtRawSolverOutput,
    SmtSolverVerdict,
    classify_differential,
    parse_smt_solver_stdout,
    run_z3_cvc5_differential,
)
from ipfs_datasets_py.logic.backends.z3.compiler import (
    Z3_SOFTWARE_VERIFICATION_INTERFACE,
    Z3Compiler,
    Z3SoftwareVerificationBackend,
)
from ipfs_datasets_py.logic.ir_core.protocols import ExecutionBounds


def _arith_vc_obligation() -> SmtObligation:
    """Reviewed fixture: x >= 1 entails x > 0 (theorem-by-negation + unsat core)."""

    x = term_symbol("x")
    return SmtObligation(
        obligation_id="obl:vc-x-positive",
        query_mode=SmtQueryMode.THEOREM_BY_NEGATION,
        features=("arithmetic", "equality", "verification_conditions"),
        goal=SmtTerm(SmtTermKind.GT, arguments=(x, term_int(0))),
        assumptions=(
            SmtNamedAssertion(
                formula=SmtTerm(SmtTermKind.GE, arguments=(x, term_int(1))),
                name="assume_ge_one",
            ),
        ),
        functions=(SmtFunDecl(name="x", range=INT_SORT, is_const=True),),
        request_unsat_core=True,
        property_ids=("property:vc-x-positive",),
    )


def _sat_bool_obligation() -> SmtObligation:
    return SmtObligation(
        obligation_id="obl:sat-p-true",
        query_mode=SmtQueryMode.SATISFIABILITY,
        features=("equality",),
        goal=term_eq(term_symbol("p"), term_true()),
        functions=(SmtFunDecl("p", range=BOOL_SORT, is_const=True),),
        request_model=True,
    )


def _disproved_theorem_obligation() -> SmtObligation:
    """x > 0 is not a theorem without assumptions (counterexample exists)."""

    x = term_symbol("x")
    return SmtObligation(
        obligation_id="obl:vc-x-positive-open",
        query_mode=SmtQueryMode.THEOREM_BY_NEGATION,
        features=("arithmetic", "equality", "verification_conditions"),
        goal=SmtTerm(SmtTermKind.GT, arguments=(x, term_int(0))),
        functions=(SmtFunDecl(name="x", range=INT_SORT, is_const=True),),
        request_model=True,
        property_ids=("property:vc-open",),
    )


def _fixed_runner(stdout: str, **kwargs):
    def run(_smtlib: str, _bounds: ExecutionBounds) -> SmtRawSolverOutput:
        return SmtRawSolverOutput(
            stdout=stdout,
            stderr=kwargs.get("stderr", ""),
            returncode=kwargs.get("returncode", 0),
            elapsed_ms=kwargs.get("elapsed_ms", 7),
            solver_version=kwargs.get("solver_version", "mock-solver/1.0"),
            timed_out=kwargs.get("timed_out", False),
            unavailable=kwargs.get("unavailable", False),
        )

    return run


def _bounds() -> ExecutionBounds:
    return ExecutionBounds(
        timeout_ms=5_000,
        max_steps=100_000,
        max_memory_bytes=64 * 1024 * 1024,
        max_output_bytes=65_536,
    )


# ---------------------------------------------------------------------------
# Parser contracts
# ---------------------------------------------------------------------------


def test_parse_rejects_ambiguous_and_prefix_noise() -> None:
    with pytest.raises(MalformedSmtSolverOutput, match="exactly one"):
        parse_smt_solver_stdout("sat\nunsat\n")
    with pytest.raises(MalformedSmtSolverOutput, match="non-result"):
        parse_smt_solver_stdout("hello\nsat\n")
    with pytest.raises(MalformedSmtSolverOutput, match="exactly one"):
        parse_smt_solver_stdout("")


def test_parse_unsat_core_and_model_artifacts() -> None:
    verdict, core, model = parse_smt_solver_stdout(
        "unsat\n(assume_ge_one path_0)\n",
        expect_unsat_core=True,
    )
    assert verdict == "unsat"
    assert "assume_ge_one" in core
    assert model == ""

    verdict, core, model = parse_smt_solver_stdout(
        "sat\n(\n  (define-fun p () Bool true)\n)\n",
        expect_model=True,
    )
    assert verdict == "sat"
    assert core == ()
    assert "define-fun" in model


# ---------------------------------------------------------------------------
# Single-backend contracts (injectable runners)
# ---------------------------------------------------------------------------


def test_z3_software_verification_backend_interface_and_typed_theorem() -> None:
    backend = Z3SoftwareVerificationBackend(
        runner=_fixed_runner(
            "unsat\n(assume_ge_one)\n",
            solver_version="Z3 version mock",
        ),
        availability_probe=lambda: True,
        version_probe=lambda: "Z3 version mock",
    )
    assert backend.INTERFACE == Z3_SOFTWARE_VERIFICATION_INTERFACE
    assert backend.backend_interface == Z3_SOFTWARE_VERIFICATION_INTERFACE

    outcome = backend.run(_arith_vc_obligation(), bounds=_bounds())
    assert outcome.verdict is SmtSolverVerdict.UNSAT
    assert isinstance(outcome.result, TheoremResult)
    assert outcome.result.authority is ResultAuthority.THEOREM
    assert outcome.result.status is ResultStatus.PROVED
    assert "assume_ge_one" in outcome.unsat_core
    assert list(outcome.result.witness["unsat_core"]) == list(outcome.unsat_core)
    assert outcome.compilation is not None
    assert outcome.compilation.receipt.receipt_id
    assert outcome.result.metadata["translation_receipt_id"] == (
        outcome.compilation.receipt.receipt_id
    )
    assert outcome.result.metadata["semantic_compiler_id"] == SMT_COMPILER_ID
    assert outcome.result.metadata["script_digest"] == outcome.compilation.script.digest
    assert outcome.result.usage.elapsed_ms == 7
    assert outcome.result.bounds.timeout_ms == _bounds().timeout_ms
    assert outcome.solver_version == "Z3 version mock"


def test_cvc5_software_verification_backend_interface_and_sat_model() -> None:
    backend = CVC5SoftwareVerificationBackend(
        runner=_fixed_runner(
            "sat\n(\n(define-fun p () Bool true)\n)\n",
            solver_version="cvc5 version mock",
        ),
        availability_probe=lambda: True,
    )
    assert backend.INTERFACE == CVC5_SOFTWARE_VERIFICATION_INTERFACE

    outcome = backend.run(_sat_bool_obligation(), bounds=_bounds())
    assert outcome.verdict is SmtSolverVerdict.SAT
    assert isinstance(outcome.result, SatisfiabilityResult)
    assert outcome.result.authority is ResultAuthority.SATISFIABILITY
    assert outcome.result.status is ResultStatus.SATISFIABLE
    assert "define-fun" in outcome.model_text
    assert outcome.result.witness["model_digest"]
    assert outcome.result.translation_ceiling is not None


def test_explicit_unavailability_never_looks_like_success() -> None:
    backend = Z3SoftwareVerificationBackend(
        runner=_fixed_runner("", unavailable=True, stderr="not installed"),
        availability_probe=lambda: False,
    )
    assert backend.is_available() is False
    outcome = backend.run(_arith_vc_obligation(), bounds=_bounds())
    assert outcome.verdict is SmtSolverVerdict.UNAVAILABLE
    assert outcome.result.status is ResultStatus.UNAVAILABLE
    assert outcome.result.is_conclusive is False
    assert "not available" in outcome.result.reason or "unavailable" in (
        outcome.result.reason.lower() + " ".join(outcome.result.diagnostics).lower()
    )


def test_malformed_output_is_rejected_as_malformed_status() -> None:
    backend = CVC5SoftwareVerificationBackend(
        runner=_fixed_runner("sat\nunsat\n"),
        availability_probe=lambda: True,
    )
    outcome = backend.run(_arith_vc_obligation(), bounds=_bounds())
    assert outcome.verdict is SmtSolverVerdict.MALFORMED
    assert outcome.result.status is ResultStatus.MALFORMED
    assert "exactly one" in outcome.result.reason


def test_timeout_and_error_paths_are_typed() -> None:
    timeout_backend = Z3SoftwareVerificationBackend(
        runner=_fixed_runner("", timed_out=True, elapsed_ms=5_000),
        availability_probe=lambda: True,
    )
    timed = timeout_backend.run(_arith_vc_obligation(), bounds=_bounds())
    assert timed.verdict is SmtSolverVerdict.TIMEOUT
    assert timed.result.status is ResultStatus.TIMEOUT

    error_backend = CVC5SoftwareVerificationBackend(
        runner=_fixed_runner("", returncode=2, stderr="internal error"),
        availability_probe=lambda: True,
    )
    errored = error_backend.run(_arith_vc_obligation(), bounds=_bounds())
    assert errored.verdict is SmtSolverVerdict.ERROR
    assert errored.result.status is ResultStatus.ERROR


# ---------------------------------------------------------------------------
# Differential contracts
# ---------------------------------------------------------------------------


def test_differential_agreement_on_reviewed_theorem_fixture() -> None:
    z3 = Z3SoftwareVerificationBackend(
        runner=_fixed_runner("unsat\n(assume_ge_one)\n", solver_version="z3-mock"),
        availability_probe=lambda: True,
    )
    cvc5 = CVC5SoftwareVerificationBackend(
        runner=_fixed_runner(
            "unsat\n(\nassume_ge_one\n)\n", solver_version="cvc5-mock"
        ),
        availability_probe=lambda: True,
    )
    report = run_z3_cvc5_differential(
        _arith_vc_obligation(),
        bounds=_bounds(),
        z3_backend=z3,
        cvc5_backend=cvc5,
    )
    assert isinstance(report, SmtDifferentialReport)
    assert report.agreement is True
    assert report.classification is DifferentialClassification.AGREE_PROVED
    assert report.left.verdict is SmtSolverVerdict.UNSAT
    assert report.right.verdict is SmtSolverVerdict.UNSAT
    assert report.script_digest == report.compilation.script.digest
    assert report.left.compilation is not None
    assert report.right.compilation is not None
    # Identical canonical script for both solvers.
    assert report.left.compilation.script.digest == report.right.compilation.script.digest
    assert report.compilation.receipt.compilers[0].compiler_id == SMT_COMPILER_ID
    payload = report.to_dict()
    assert payload["report_id"] == report.report_id
    assert payload["translation_receipt_id"] == report.compilation.receipt.receipt_id


def test_differential_preserves_disagreement_evidence() -> None:
    z3 = Z3SoftwareVerificationBackend(
        runner=_fixed_runner("unsat\n", solver_version="z3-mock"),
        availability_probe=lambda: True,
    )
    cvc5 = CVC5SoftwareVerificationBackend(
        runner=_fixed_runner("sat\n", solver_version="cvc5-mock"),
        availability_probe=lambda: True,
    )
    report = SmtDifferentialVerifier(left=z3, right=cvc5).verify(
        _arith_vc_obligation(), bounds=_bounds()
    )
    assert report.agreement is False
    assert report.classification is DifferentialClassification.DISAGREE
    evidence = report.disagreement_evidence.to_dict()
    assert evidence["preserved"] is True
    assert evidence["left"]["verdict"] == "unsat"
    assert evidence["right"]["verdict"] == "sat"
    assert evidence["script_digest"] == report.script_digest
    assert evidence["left"]["stdout_digest"]
    assert evidence["right"]["stdout_digest"]


def test_differential_partial_and_full_unavailability() -> None:
    available = Z3SoftwareVerificationBackend(
        runner=_fixed_runner("unsat\n"),
        availability_probe=lambda: True,
    )
    missing = CVC5SoftwareVerificationBackend(
        runner=_fixed_runner("", unavailable=True),
        availability_probe=lambda: False,
    )
    partial = run_z3_cvc5_differential(
        _arith_vc_obligation(),
        bounds=_bounds(),
        z3_backend=available,
        cvc5_backend=missing,
    )
    assert partial.classification is DifferentialClassification.PARTIAL_UNAVAILABLE
    assert partial.agreement is False

    both_missing_left = Z3SoftwareVerificationBackend(
        availability_probe=lambda: False,
        runner=_fixed_runner("", unavailable=True),
    )
    both_missing_right = CVC5SoftwareVerificationBackend(
        availability_probe=lambda: False,
        runner=_fixed_runner("", unavailable=True),
    )
    both = run_z3_cvc5_differential(
        _arith_vc_obligation(),
        bounds=_bounds(),
        z3_backend=both_missing_left,
        cvc5_backend=both_missing_right,
    )
    assert both.classification is DifferentialClassification.BOTH_UNAVAILABLE


def test_classify_differential_rejects_cross_obligation_pairing() -> None:
    z3 = Z3SoftwareVerificationBackend(
        runner=_fixed_runner("unsat\n"),
        availability_probe=lambda: True,
    )
    left = z3.run(_arith_vc_obligation(), bounds=_bounds())
    right = z3.run(_sat_bool_obligation(), bounds=_bounds())
    # Force same backend_id collision path via classify only.
    with pytest.raises(Exception):
        classify_differential(left, right)


def test_semantic_compilers_on_z3_and_cvc5_emit_identical_script_digests() -> None:
    obligation = _arith_vc_obligation()
    shared = SoftwareVerificationSMTCompiler().compile(obligation)
    z3_compilation, _ = Z3Compiler().compile_obligation(obligation)
    cvc5_compilation, _ = CVC5Compiler().compile_obligation(obligation)
    assert z3_compilation.script.digest == shared.script.digest
    assert cvc5_compilation.script.digest == shared.script.digest
    assert z3_compilation.smtlib == cvc5_compilation.smtlib
    assert "(get-unsat-core)" in z3_compilation.smtlib
    assert z3_compilation.receipt.receipt_id == cvc5_compilation.receipt.receipt_id


def test_disproved_theorem_agreement_with_models() -> None:
    z3 = Z3SoftwareVerificationBackend(
        runner=_fixed_runner(
            "sat\n(\n(define-fun x () Int 0)\n)\n",
            solver_version="z3-mock",
        ),
        availability_probe=lambda: True,
    )
    cvc5 = CVC5SoftwareVerificationBackend(
        runner=_fixed_runner(
            "sat\n(\n(define-fun x () Int (- 1))\n)\n",
            solver_version="cvc5-mock",
        ),
        availability_probe=lambda: True,
    )
    report = run_z3_cvc5_differential(
        _disproved_theorem_obligation(),
        bounds=_bounds(),
        z3_backend=z3,
        cvc5_backend=cvc5,
    )
    assert report.classification is DifferentialClassification.AGREE_DISPROVED
    assert isinstance(report.left.result, TheoremResult)
    assert report.left.result.status is ResultStatus.DISPROVED
    assert report.right.result.status is ResultStatus.DISPROVED
    assert report.left.model_text
    assert report.right.model_text


# ---------------------------------------------------------------------------
# Live solvers (when installed)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(shutil.which("z3") is None, reason="z3 not on PATH")
@pytest.mark.skipif(shutil.which("cvc5") is None, reason="cvc5 not on PATH")
def test_live_z3_cvc5_agree_on_reviewed_vc_fixture() -> None:
    report = run_z3_cvc5_differential(_arith_vc_obligation(), bounds=_bounds())
    assert report.classification is DifferentialClassification.AGREE_PROVED
    assert report.agreement is True
    assert report.left.verdict is SmtSolverVerdict.UNSAT
    assert report.right.verdict is SmtSolverVerdict.UNSAT
    assert isinstance(report.left.result, TheoremResult)
    assert report.left.result.status is ResultStatus.PROVED
    assert report.right.result.status is ResultStatus.PROVED
    # Versions and resources must be bound.
    assert report.left.solver_version
    assert report.right.solver_version
    assert report.left.result.usage.elapsed_ms >= 0
    assert report.right.result.usage.elapsed_ms >= 0
    assert report.left.result.metadata["script_digest"] == report.script_digest
    assert report.right.result.metadata["script_digest"] == report.script_digest


@pytest.mark.skipif(shutil.which("z3") is None, reason="z3 not on PATH")
@pytest.mark.skipif(shutil.which("cvc5") is None, reason="cvc5 not on PATH")
def test_live_z3_cvc5_agree_on_satisfiability_with_model() -> None:
    report = run_z3_cvc5_differential(_sat_bool_obligation(), bounds=_bounds())
    assert report.classification is DifferentialClassification.AGREE_SATISFIABLE
    assert report.left.result.status is ResultStatus.SATISFIABLE
    assert report.right.result.status is ResultStatus.SATISFIABLE
    assert report.left.model_text or report.right.model_text


@pytest.mark.skipif(shutil.which("z3") is None, reason="z3 not on PATH")
def test_live_z3_software_verification_backend_alone() -> None:
    backend = Z3SoftwareVerificationBackend()
    assert backend.is_available() is True
    outcome = backend.run(_arith_vc_obligation(), bounds=_bounds())
    assert outcome.verdict is SmtSolverVerdict.UNSAT
    assert outcome.result.status is ResultStatus.PROVED
    assert outcome.compilation is not None
    assert outcome.compilation.receipt.authority_ceiling is not None
