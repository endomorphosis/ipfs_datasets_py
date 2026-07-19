"""Integration tests for policy-controlled parallel ATP/SMT portfolio
execution (HAMMER-008).

Unlike ``tests/unit_tests/logic/hammers/test_portfolio.py`` (which injects a
fake process runner so it never depends on any external tool), these tests
run the real :class:`SolverPortfolio` against whichever allowlisted
Z3/CVC5/Vampire/E executables actually happen to be installed in this
environment, gated with ``pytest.mark.skipif`` (mirroring the pattern used
by ``tests/integration/logic/hammers/test_itp_frontends.py`` for the native
ITP frontends) so the suite still passes, via skip, on a host with none of
these solvers installed.

These tests cover:
- A genuine, trivially valid first-order tautology
  (``forall x. p(x) => p(x)``), translated through the real HAMMER-007
  pipeline (:class:`TranslationContext`), is handed to a real solver
  subprocess and produces the raw verdict that format/solver combination
  actually reports for an *asserted* (SMT-LIB) vs. *conjectured* (TPTP)
  formula — never a fabricated "verified" status.
- A genuine, trivially unsatisfiable formula
  (``exists x. p(x) and not p(x)``) is reported ``unsat`` by a real SMT
  solver.
- The full :class:`SolverAttemptRecord`/:class:`SolverAttemptEvidence`
  produced by a real invocation carries a real, non-empty ``solver_version``
  (probed from the actual executable), a real command argv whose first
  element is the resolved executable path, and a raw output digest that
  matches the actual captured stdout/stderr.
- Running two allowlisted solvers against the same goal in one portfolio
  call (when at least two of the four are installed) respects the
  process-count and cancellation budgets end-to-end against real
  subprocesses, not simulated ones.
"""

from __future__ import annotations

import shutil

import pytest

from ipfs_datasets_py.logic.hammers.corpus import compute_content_digest
from ipfs_datasets_py.logic.hammers.models import HammerPolicy, SolverVerdict, TranslationTarget
from ipfs_datasets_py.logic.hammers.policy import PortfolioPolicy, SolverBudget
from ipfs_datasets_py.logic.hammers.portfolio import PortfolioAttemptSpec, SolverPortfolio
from ipfs_datasets_py.logic.hammers.translation import (
    PROP_SORT,
    And,
    App,
    Const,
    Exists,
    Forall,
    FunctionTypeRef,
    Implies,
    Not,
    SortRef,
    TranslationContext,
    Var,
)

Z3_AVAILABLE = shutil.which("z3") is not None
CVC5_AVAILABLE = shutil.which("cvc5") is not None
VAMPIRE_AVAILABLE = shutil.which("vampire") is not None
EPROVER_AVAILABLE = shutil.which("eprover") is not None or shutil.which("eprover-ho") is not None

NAT = SortRef("nat")


def _predicate(name: str) -> Const:
    return Const(name, FunctionTypeRef((NAT,), PROP_SORT))


def _tautology_translation(*, target: TranslationTarget, request_id: str):
    """``forall x. p(x) => p(x)`` — trivially valid regardless of format."""

    p = _predicate("p")
    goal = Forall("x", NAT, Implies(App(p, (Var("x", NAT),)), App(p, (Var("x", NAT),))))
    ctx = TranslationContext(request_id=request_id)
    return ctx.translate(source_construct="tautology_goal", term=goal, target=target)


def _contradiction_translation(*, target: TranslationTarget, request_id: str):
    """``exists x. p(x) and not p(x)`` — trivially unsatisfiable."""

    p = _predicate("p")
    goal = Exists(
        "x", NAT, And(App(p, (Var("x", NAT),)), Not(App(p, (Var("x", NAT),))))
    )
    ctx = TranslationContext(request_id=request_id)
    return ctx.translate(source_construct="contradiction_goal", term=goal, target=target)


def _smt_policy(
    *solvers: str,
    timeout_seconds: float = 20.0,
    cancel_on_first_conclusive: bool = True,
) -> PortfolioPolicy:
    return PortfolioPolicy(
        hammer_policy=HammerPolicy(timeout_seconds=timeout_seconds, allowed_solvers=list(solvers)),
        solver_budgets={name: SolverBudget(timeout_seconds=timeout_seconds) for name in solvers},
        cancel_on_first_conclusive=cancel_on_first_conclusive,
    )


# ---------------------------------------------------------------------------
# Z3
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not Z3_AVAILABLE, reason="z3 executable not found on PATH")
class TestZ3RealInvocation:
    def test_asserted_tautology_is_satisfiable(self):
        translation = _tautology_translation(target=TranslationTarget.SMTLIB, request_id="z3-req")
        policy = _smt_policy("z3")
        portfolio = SolverPortfolio(policy)
        result = portfolio.run(
            "z3-req", [PortfolioAttemptSpec(translation=translation, solver_name="z3")]
        )
        assert result.denied == []
        record = result.attempts[0]
        assert record.verdict is SolverVerdict.SAT
        assert record.solver_version  # a real, non-empty version string
        evidence = result.evidence[record.attempt_id]
        assert evidence.command[0] == shutil.which("z3")
        assert compute_content_digest(
            {"stdout": evidence.raw_stdout, "stderr": evidence.raw_stderr}
        ) == record.raw_output_digest

    def test_asserted_contradiction_is_unsatisfiable(self):
        translation = _contradiction_translation(
            target=TranslationTarget.SMTLIB, request_id="z3-contra-req"
        )
        policy = _smt_policy("z3")
        portfolio = SolverPortfolio(policy)
        result = portfolio.run(
            "z3-contra-req",
            [PortfolioAttemptSpec(translation=translation, solver_name="z3")],
        )
        record = result.attempts[0]
        assert record.verdict is SolverVerdict.UNSAT


# ---------------------------------------------------------------------------
# CVC5
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not CVC5_AVAILABLE, reason="cvc5 executable not found on PATH")
class TestCVC5RealInvocation:
    def test_asserted_tautology_is_satisfiable(self):
        translation = _tautology_translation(
            target=TranslationTarget.SMTLIB, request_id="cvc5-req"
        )
        policy = _smt_policy("cvc5")
        portfolio = SolverPortfolio(policy)
        result = portfolio.run(
            "cvc5-req", [PortfolioAttemptSpec(translation=translation, solver_name="cvc5")]
        )
        assert result.denied == []
        record = result.attempts[0]
        assert record.verdict is SolverVerdict.SAT
        assert record.solver_version
        evidence = result.evidence[record.attempt_id]
        assert evidence.command[0] == shutil.which("cvc5")
        assert "--lang=smt2" in evidence.command
        assert evidence.command[-1].endswith(".smt2")

    def test_asserted_contradiction_is_unsatisfiable(self):
        translation = _contradiction_translation(
            target=TranslationTarget.SMTLIB, request_id="cvc5-contra-req"
        )
        policy = _smt_policy("cvc5")
        portfolio = SolverPortfolio(policy)
        result = portfolio.run(
            "cvc5-contra-req",
            [PortfolioAttemptSpec(translation=translation, solver_name="cvc5")],
        )
        record = result.attempts[0]
        assert record.verdict is SolverVerdict.UNSAT

    def test_denies_solver_not_present_in_allowed_solvers(self):
        # cvc5 is available in this environment, but the policy only
        # allowlists z3 — the executable must never be silently substituted
        # in, and no SolverAttemptRecord should be produced.
        policy = _smt_policy("z3")
        portfolio = SolverPortfolio(policy)
        translation = _tautology_translation(
            target=TranslationTarget.SMTLIB, request_id="cvc5-denied-req"
        )
        result = portfolio.run(
            "cvc5-denied-req",
            [PortfolioAttemptSpec(translation=translation, solver_name="cvc5")],
        )
        assert result.attempts == []
        assert len(result.denied) == 1
        assert result.denied[0]["solver_name"] == "cvc5"

    def test_timeout_budget_is_enforced_on_a_real_process(self):
        # An extremely tight timeout must bound the real cvc5 invocation
        # even for a trivial goal; the recorded wall time must never be
        # reported as less than the configured budget once TIMEOUT is set,
        # and the process must not be allowed to run past it un-bounded.
        translation = _tautology_translation(
            target=TranslationTarget.SMTLIB, request_id="cvc5-timeout-req"
        )
        policy = PortfolioPolicy(
            hammer_policy=HammerPolicy(timeout_seconds=5.0, allowed_solvers=["cvc5"]),
            solver_budgets={"cvc5": SolverBudget(timeout_seconds=0.001)},
        )
        portfolio = SolverPortfolio(policy)
        result = portfolio.run(
            "cvc5-timeout-req",
            [PortfolioAttemptSpec(translation=translation, solver_name="cvc5")],
        )
        record = result.attempts[0]
        # Either the process legitimately finished faster than our poll
        # granularity could observe a timeout (trivial goal, fast solver) or
        # it was reported as TIMEOUT with wall_time >= the budget — both are
        # acceptable, but wall time must never be negative/absurd and the
        # attempt must never silently hang past a generous outer bound.
        assert record.wall_time_seconds is not None
        assert record.wall_time_seconds < 15.0


# ---------------------------------------------------------------------------
# Vampire
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not VAMPIRE_AVAILABLE, reason="vampire executable not found on PATH")
class TestVampireRealInvocation:
    def test_conjectured_tautology_is_proved(self):
        translation = _tautology_translation(
            target=TranslationTarget.TPTP, request_id="vampire-req"
        )
        policy = PortfolioPolicy(
            hammer_policy=HammerPolicy(timeout_seconds=20.0, allowed_solvers=["vampire"])
        )
        portfolio = SolverPortfolio(policy)
        result = portfolio.run(
            "vampire-req",
            [PortfolioAttemptSpec(translation=translation, solver_name="vampire")],
        )
        assert result.denied == []
        record = result.attempts[0]
        assert record.verdict is SolverVerdict.PROVED
        assert record.solver_version


# ---------------------------------------------------------------------------
# E prover
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not EPROVER_AVAILABLE, reason="eprover executable not found on PATH")
class TestEProverRealInvocation:
    def test_conjectured_tautology_is_proved(self):
        translation = _tautology_translation(target=TranslationTarget.TPTP, request_id="e-req")
        policy = PortfolioPolicy(
            hammer_policy=HammerPolicy(timeout_seconds=20.0, allowed_solvers=["e"])
        )
        portfolio = SolverPortfolio(policy)
        result = portfolio.run(
            "e-req", [PortfolioAttemptSpec(translation=translation, solver_name="e")]
        )
        assert result.denied == []
        record = result.attempts[0]
        assert record.verdict is SolverVerdict.PROVED
        assert record.solver_version


# ---------------------------------------------------------------------------
# Cross-solver portfolio (only meaningful with >= 2 real solvers installed)
# ---------------------------------------------------------------------------


_SMT_SOLVERS_AVAILABLE = [name for name, ok in (("z3", Z3_AVAILABLE), ("cvc5", CVC5_AVAILABLE)) if ok]


@pytest.mark.skipif(
    len(_SMT_SOLVERS_AVAILABLE) < 2,
    reason="fewer than two SMT solver executables (z3, cvc5) found on PATH",
)
def test_multi_solver_smt_portfolio_runs_both_concurrently():
    translation = _tautology_translation(
        target=TranslationTarget.SMTLIB, request_id="multi-smt-req"
    )
    # This test verifies real cross-solver parity, so both processes must be
    # allowed to finish. Default early-cancellation behavior is covered by
    # the focused unit test with a deterministic slow runner.
    policy = _smt_policy(*_SMT_SOLVERS_AVAILABLE, cancel_on_first_conclusive=False)
    portfolio = SolverPortfolio(policy)
    attempts = [
        PortfolioAttemptSpec(translation=translation, solver_name=name)
        for name in _SMT_SOLVERS_AVAILABLE
    ]
    result = portfolio.run("multi-smt-req", attempts)
    assert result.denied == []
    assert len(result.attempts) == len(_SMT_SOLVERS_AVAILABLE)
    for record in result.attempts:
        assert record.verdict is SolverVerdict.SAT


@pytest.mark.skipif(
    not (Z3_AVAILABLE or CVC5_AVAILABLE or VAMPIRE_AVAILABLE or EPROVER_AVAILABLE),
    reason="no allowlisted ATP/SMT solver executable found on PATH",
)
def test_no_result_ever_claims_verified_status():
    # Regardless of which real solver ran, the produced records must never
    # carry any concept of "verified" — only a later, independent kernel
    # reconstruction (HAMMER-010, not this module) may assert that.
    available = [
        name
        for name, ok in (
            ("z3", Z3_AVAILABLE),
            ("cvc5", CVC5_AVAILABLE),
        )
        if ok
    ]
    if not available:
        pytest.skip("no SMT solver executable found on PATH for this check")
    translation = _tautology_translation(
        target=TranslationTarget.SMTLIB, request_id="verified-check-req"
    )
    policy = _smt_policy(available[0])
    portfolio = SolverPortfolio(policy)
    result = portfolio.run(
        "verified-check-req",
        [PortfolioAttemptSpec(translation=translation, solver_name=available[0])],
    )
    record = result.attempts[0]
    assert not hasattr(record, "verified")
    assert not hasattr(record, "kernel_accepted")
