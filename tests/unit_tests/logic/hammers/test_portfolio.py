"""Tests for policy-controlled parallel ATP/SMT portfolio execution
(HAMMER-008).

These tests cover:
- :mod:`ipfs_datasets_py.logic.hammers.policy`: :class:`SolverBudget` and
  :class:`PortfolioPolicy` validation (rejecting unknown/non-allowlisted
  solver names anywhere they can appear), executable resolution (override
  vs. ``PATH`` search, both gated by ``HammerPolicy.allowed_solvers``),
  per-solver budget derivation (and the rule that an override may never
  exceed the governing ``HammerPolicy.timeout_seconds``), argv construction
  for every allowlisted solver family, and ``to_dict``/``from_dict``
  round-trips.
- :mod:`ipfs_datasets_py.logic.hammers.portfolio`: building solver input
  text from a :class:`TranslationRecord`, parsing raw SMT-LIB/TPTP solver
  output into an untrusted :class:`SolverVerdict`, and the
  :class:`SolverPortfolio` orchestrator's attempt resolution (permitted vs.
  policy-denied), parallel execution bounded by the process-count budget,
  cancellation-on-first-conclusive-verdict semantics, and evidence capture
  (command, input digest, raw output digest, solver trace) — all exercised
  against an injected fake process runner so these tests never depend on a
  real Z3/CVC5/Vampire/E installation.
- The security invariant that translated theorem content is never placed
  into a subprocess argv, only into a temporary file whose path appears in
  the command.
- That neither :class:`SolverAttemptRecord` nor :class:`PortfolioRunResult`
  can ever represent a "verified" result — there is no such field to set.
"""

from __future__ import annotations

import inspect
import os
import stat
import threading
import time
from typing import List, Optional

import pytest

from ipfs_datasets_py.logic.hammers.models import (
    HammerPolicy,
    SolverAttemptRecord,
    SolverVerdict,
    TranslationRecord,
    TranslationStatus,
    TranslationTarget,
)
from ipfs_datasets_py.logic.hammers.policy import (
    PolicyError,
    PortfolioPolicy,
    SolverBudget,
    known_solver_names,
    solver_spec,
)
from ipfs_datasets_py.logic.hammers.portfolio import (
    PortfolioAttemptSpec,
    PortfolioRunResult,
    SolverPortfolio,
    SolverProcessOutcome,
    build_solver_input_text,
    parse_smtlib_verdict,
    parse_tptp_verdict,
    run_bounded_solver_process,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _smt_translation(
    *, translation_id: str = "t-smt-1", request_id: str = "req-1", text: Optional[str] = None
) -> TranslationRecord:
    return TranslationRecord(
        translation_id=translation_id,
        request_id=request_id,
        target=TranslationTarget.SMTLIB,
        status=TranslationStatus.SUPPORTED,
        source_construct="goal",
        translated_text=text
        if text is not None
        else (
            "(declare-sort nat 0)\n"
            "(declare-fun p (nat) Bool)\n"
            "(assert (forall ((x nat)) (=> (p x) (p x))))"
        ),
    )


def _tptp_translation(
    *, translation_id: str = "t-tptp-1", request_id: str = "req-1", text: Optional[str] = None
) -> TranslationRecord:
    return TranslationRecord(
        translation_id=translation_id,
        request_id=request_id,
        target=TranslationTarget.TPTP,
        status=TranslationStatus.SUPPORTED,
        source_construct="goal",
        translated_text=text
        if text is not None
        else (
            "tff(sort_0, type, nat: $tType).\n"
            "tff(sym_0, type, p: nat > $o).\n"
            "tff(goal, conjecture, (! [X: nat] : (p(X) => p(X))))."
        ),
    )


def _make_fake_executable(path) -> str:
    """Create an empty, executable dummy file at ``path`` and return it as
    ``str`` — a stand-in "resolved executable" for ``executable_overrides``
    that is never actually invoked by these unit tests (a fake
    ``process_runner`` is always injected instead)."""

    path = str(path)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("#!/bin/sh\nexit 0\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def _allow_policy(*solvers: str, timeout_seconds: float = 30.0) -> HammerPolicy:
    return HammerPolicy(timeout_seconds=timeout_seconds, allowed_solvers=list(solvers))


# ---------------------------------------------------------------------------
# SolverBudget
# ---------------------------------------------------------------------------


class TestSolverBudget:
    def test_defaults_are_valid(self):
        SolverBudget().validate()

    def test_rejects_non_positive_timeout(self):
        with pytest.raises(ValueError):
            SolverBudget(timeout_seconds=0).validate()
        with pytest.raises(ValueError):
            SolverBudget(timeout_seconds=-1).validate()

    def test_rejects_non_positive_cpu_seconds(self):
        with pytest.raises(ValueError):
            SolverBudget(cpu_seconds=0).validate()

    def test_rejects_non_positive_memory_mb(self):
        with pytest.raises(ValueError):
            SolverBudget(memory_mb=0).validate()

    def test_to_dict_from_dict_round_trip(self):
        budget = SolverBudget(timeout_seconds=12.5, cpu_seconds=10.0, memory_mb=512)
        restored = SolverBudget.from_dict(budget.to_dict())
        assert restored == budget


# ---------------------------------------------------------------------------
# Solver registry
# ---------------------------------------------------------------------------


class TestSolverRegistry:
    def test_known_solver_names(self):
        assert known_solver_names() == ("cvc5", "e", "vampire", "z3")

    def test_solver_spec_unknown_raises_policy_error(self):
        with pytest.raises(PolicyError):
            solver_spec("not-a-real-solver")

    def test_solver_spec_targets(self):
        assert solver_spec("z3").target is TranslationTarget.SMTLIB
        assert solver_spec("cvc5").target is TranslationTarget.SMTLIB
        assert solver_spec("vampire").target is TranslationTarget.TPTP
        assert solver_spec("e").target is TranslationTarget.TPTP


# ---------------------------------------------------------------------------
# PortfolioPolicy validation
# ---------------------------------------------------------------------------


class TestPortfolioPolicyValidate:
    def test_valid_policy_passes(self):
        PortfolioPolicy(hammer_policy=_allow_policy("z3", "cvc5")).validate()

    def test_rejects_unknown_solver_in_allowed_solvers(self):
        policy = PortfolioPolicy(hammer_policy=_allow_policy("not-a-real-solver"))
        with pytest.raises(PolicyError):
            policy.validate()

    def test_rejects_unknown_solver_in_solver_budgets(self):
        policy = PortfolioPolicy(
            hammer_policy=_allow_policy("z3"),
            solver_budgets={"not-a-real-solver": SolverBudget()},
        )
        with pytest.raises(PolicyError):
            policy.validate()

    def test_rejects_unknown_solver_in_executable_overrides(self):
        policy = PortfolioPolicy(
            hammer_policy=_allow_policy("z3"),
            executable_overrides={"not-a-real-solver": "/usr/bin/true"},
        )
        with pytest.raises(PolicyError):
            policy.validate()

    def test_rejects_non_positive_max_parallel_processes(self):
        policy = PortfolioPolicy(hammer_policy=_allow_policy("z3"), max_parallel_processes=0)
        with pytest.raises(ValueError):
            policy.validate()

    def test_rejects_invalid_solver_budget_value(self):
        policy = PortfolioPolicy(
            hammer_policy=_allow_policy("z3"),
            solver_budgets={"z3": SolverBudget(timeout_seconds=-1)},
        )
        with pytest.raises(ValueError):
            policy.validate()

    def test_to_dict_from_dict_round_trip(self):
        policy = PortfolioPolicy(
            hammer_policy=_allow_policy("z3", "cvc5", timeout_seconds=20.0),
            solver_budgets={"z3": SolverBudget(timeout_seconds=5.0)},
            executable_overrides={"cvc5": "/usr/bin/true"},
            max_parallel_processes=2,
            cancel_on_first_conclusive=False,
        )
        restored = PortfolioPolicy.from_dict(policy.to_dict())
        restored.validate()
        assert restored.to_dict() == policy.to_dict()


# ---------------------------------------------------------------------------
# PortfolioPolicy.budget_for
# ---------------------------------------------------------------------------


class TestBudgetFor:
    def test_unknown_solver_raises_policy_error(self):
        policy = PortfolioPolicy(hammer_policy=_allow_policy("z3"))
        with pytest.raises(PolicyError):
            policy.budget_for("not-a-real-solver")

    def test_defaults_from_hammer_policy_when_no_override(self):
        policy = PortfolioPolicy(
            hammer_policy=HammerPolicy(
                timeout_seconds=15.0, cpu_seconds=10.0, memory_mb=256, allowed_solvers=["z3"]
            )
        )
        budget = policy.budget_for("z3")
        assert budget.timeout_seconds == 15.0
        assert budget.cpu_seconds == 10.0
        assert budget.memory_mb == 256

    def test_override_is_used_when_present(self):
        policy = PortfolioPolicy(
            hammer_policy=_allow_policy("z3", timeout_seconds=30.0),
            solver_budgets={"z3": SolverBudget(timeout_seconds=5.0)},
        )
        assert policy.budget_for("z3").timeout_seconds == 5.0

    def test_override_exceeding_hammer_policy_timeout_raises(self):
        policy = PortfolioPolicy(
            hammer_policy=_allow_policy("z3", timeout_seconds=5.0),
            solver_budgets={"z3": SolverBudget(timeout_seconds=60.0)},
        )
        with pytest.raises(PolicyError):
            policy.budget_for("z3")


# ---------------------------------------------------------------------------
# PortfolioPolicy.resolve_executable
# ---------------------------------------------------------------------------


class TestResolveExecutable:
    def test_unknown_solver_raises_policy_error(self):
        policy = PortfolioPolicy(hammer_policy=_allow_policy("z3"))
        with pytest.raises(PolicyError):
            policy.resolve_executable("not-a-real-solver")

    def test_not_in_allowed_solvers_raises_policy_error(self, tmp_path):
        fake = _make_fake_executable(tmp_path / "cvc5")
        policy = PortfolioPolicy(
            hammer_policy=_allow_policy("z3"),  # cvc5 not allowed
            executable_overrides={"cvc5": fake},
        )
        with pytest.raises(PolicyError):
            policy.resolve_executable("cvc5")

    def test_override_resolves_when_valid(self, tmp_path):
        fake = _make_fake_executable(tmp_path / "z3")
        policy = PortfolioPolicy(
            hammer_policy=_allow_policy("z3"), executable_overrides={"z3": fake}
        )
        assert policy.resolve_executable("z3") == fake

    def test_override_missing_file_raises_policy_error(self, tmp_path):
        missing = str(tmp_path / "does-not-exist")
        policy = PortfolioPolicy(
            hammer_policy=_allow_policy("z3"), executable_overrides={"z3": missing}
        )
        with pytest.raises(PolicyError):
            policy.resolve_executable("z3")

    def test_override_non_executable_file_raises_policy_error(self, tmp_path):
        non_exec = tmp_path / "z3"
        non_exec.write_text("not executable")
        policy = PortfolioPolicy(
            hammer_policy=_allow_policy("z3"), executable_overrides={"z3": str(non_exec)}
        )
        with pytest.raises(PolicyError):
            policy.resolve_executable("z3")

    def test_no_override_and_not_on_path_raises_policy_error(self, monkeypatch):
        monkeypatch.setattr(
            "ipfs_datasets_py.logic.hammers.policy.shutil.which", lambda name: None
        )
        policy = PortfolioPolicy(hammer_policy=_allow_policy("z3"))
        with pytest.raises(PolicyError):
            policy.resolve_executable("z3")

    def test_no_override_found_on_path(self, monkeypatch):
        monkeypatch.setattr(
            "ipfs_datasets_py.logic.hammers.policy.shutil.which",
            lambda name: f"/opt/bin/{name}" if name == "z3" else None,
        )
        policy = PortfolioPolicy(hammer_policy=_allow_policy("z3"))
        assert policy.resolve_executable("z3") == "/opt/bin/z3"


# ---------------------------------------------------------------------------
# PortfolioPolicy.build_command (argv construction)
# ---------------------------------------------------------------------------


class TestBuildCommand:
    def test_z3_argv_shape(self):
        policy = PortfolioPolicy(hammer_policy=_allow_policy("z3"))
        budget = SolverBudget(timeout_seconds=7.2, memory_mb=1024)
        argv = policy.build_command("z3", "/bin/z3", "/tmp/in.smt2", budget)
        assert argv[0] == "/bin/z3"
        assert "-T:8" in argv  # ceil(7.2) == 8
        assert "-memory:1024" in argv
        assert argv[-1] == "/tmp/in.smt2"
        assert all(isinstance(part, str) for part in argv)

    def test_cvc5_argv_shape(self):
        policy = PortfolioPolicy(hammer_policy=_allow_policy("cvc5"))
        budget = SolverBudget(timeout_seconds=2.0)
        argv = policy.build_command("cvc5", "/bin/cvc5", "/tmp/in.smt2", budget)
        assert argv[0] == "/bin/cvc5"
        assert "--lang=smt2" in argv
        assert "--tlimit=2000" in argv
        assert argv[-1] == "/tmp/in.smt2"

    def test_vampire_argv_shape(self):
        policy = PortfolioPolicy(hammer_policy=_allow_policy("vampire"))
        budget = SolverBudget(timeout_seconds=10.0, memory_mb=2048)
        argv = policy.build_command("vampire", "/bin/vampire", "/tmp/in.p", budget)
        assert argv[0] == "/bin/vampire"
        assert "--time_limit" in argv and "10" in argv
        assert "--memory_limit" in argv and "2048" in argv
        assert argv[-1] == "/tmp/in.p"

    def test_eprover_argv_shape(self):
        policy = PortfolioPolicy(hammer_policy=_allow_policy("e"))
        budget = SolverBudget(timeout_seconds=3.4)
        argv = policy.build_command("e", "/bin/eprover", "/tmp/in.p", budget)
        assert argv[0] == "/bin/eprover"
        assert "--auto" in argv
        assert "--tstp-out" in argv
        assert "--cpu-limit=4" in argv  # ceil(3.4) == 4
        assert argv[-1] == "/tmp/in.p"

    def test_argv_never_contains_shell_metacharacter_joined_string(self):
        # The whole point of returning a list is that no single argv
        # element is ever a concatenated shell command string.
        policy = PortfolioPolicy(hammer_policy=_allow_policy("z3"))
        argv = policy.build_command("z3", "/bin/z3", "/tmp/in.smt2", SolverBudget())
        assert isinstance(argv, list)
        assert all(";" not in part and "&&" not in part for part in argv)


# ---------------------------------------------------------------------------
# build_solver_input_text
# ---------------------------------------------------------------------------


class TestBuildSolverInputText:
    def test_tptp_text_is_unchanged(self):
        translation = _tptp_translation()
        assert build_solver_input_text(translation) == translation.translated_text

    def test_smtlib_text_gets_check_sat_and_exit_appended(self):
        translation = _smt_translation()
        text = build_solver_input_text(translation)
        assert text.startswith(translation.translated_text)
        assert "(check-sat)" in text
        assert "(exit)" in text

    def test_unsupported_translation_raises(self):
        translation = TranslationRecord(
            translation_id="t-bad",
            request_id="req-1",
            target=TranslationTarget.TPTP,
            status=TranslationStatus.UNSUPPORTED,
            source_construct="goal",
            unsupported_reason="higher-order construct",
        )
        with pytest.raises(ValueError):
            build_solver_input_text(translation)


# ---------------------------------------------------------------------------
# Verdict parsers
# ---------------------------------------------------------------------------


class TestParseSMTLIBVerdict:
    @pytest.mark.parametrize(
        "stdout,expected",
        [
            ("sat\n", SolverVerdict.SAT),
            ("unsat\n", SolverVerdict.UNSAT),
            ("unknown\n", SolverVerdict.UNKNOWN),
        ],
    )
    def test_recognizes_standard_tokens(self, stdout, expected):
        verdict, trace = parse_smtlib_verdict(stdout, "")
        assert verdict is expected
        assert trace == stdout.strip()

    def test_ignores_leading_warnings_on_other_lines(self):
        stdout = "; warning: some diagnostic\nsat\n"
        verdict, _ = parse_smtlib_verdict(stdout, "")
        assert verdict is SolverVerdict.SAT

    def test_unparseable_output_is_error(self):
        verdict, trace = parse_smtlib_verdict("garbage output only", "")
        assert verdict is SolverVerdict.ERROR
        assert trace is None


class TestParseTPTPVerdict:
    def test_szs_theorem_is_proved(self):
        verdict, trace = parse_tptp_verdict("% SZS status Theorem for goal\n", "")
        assert verdict is SolverVerdict.PROVED
        assert trace == "SZS status Theorem"

    def test_szs_countersatisfiable_is_disproved(self):
        verdict, _ = parse_tptp_verdict("% SZS status CounterSatisfiable for goal\n", "")
        assert verdict is SolverVerdict.DISPROVED

    def test_szs_timeout(self):
        verdict, _ = parse_tptp_verdict("% SZS status Timeout for goal\n", "")
        assert verdict is SolverVerdict.TIMEOUT

    def test_fallback_refutation_found(self):
        verdict, trace = parse_tptp_verdict("Refutation found. Thanks to Tanya!\n", "")
        assert verdict is SolverVerdict.PROVED
        assert trace == "refutation found"

    def test_fallback_unknown(self):
        verdict, trace = parse_tptp_verdict("nothing recognizable here\n", "")
        assert verdict is SolverVerdict.UNKNOWN
        assert trace is None


# ---------------------------------------------------------------------------
# SolverPortfolio.resolve_attempts
# ---------------------------------------------------------------------------


class TestResolveAttempts:
    def test_permits_matching_solver_and_target(self, tmp_path):
        fake = _make_fake_executable(tmp_path / "z3")
        policy = PortfolioPolicy(
            hammer_policy=_allow_policy("z3"), executable_overrides={"z3": fake}
        )
        portfolio = SolverPortfolio(policy)
        permitted, denied = portfolio.resolve_attempts(
            [PortfolioAttemptSpec(translation=_smt_translation(), solver_name="z3")]
        )
        assert denied == []
        assert len(permitted) == 1
        assert permitted[0][1] == fake

    def test_denies_unknown_solver(self):
        policy = PortfolioPolicy(hammer_policy=_allow_policy("z3"))
        portfolio = SolverPortfolio(policy)
        _, denied = portfolio.resolve_attempts(
            [PortfolioAttemptSpec(translation=_smt_translation(), solver_name="ghost-solver")]
        )
        assert len(denied) == 1
        assert denied[0]["solver_name"] == "ghost-solver"

    def test_denies_solver_not_in_allowlist(self, tmp_path):
        fake = _make_fake_executable(tmp_path / "cvc5")
        policy = PortfolioPolicy(
            hammer_policy=_allow_policy("z3"),  # cvc5 not allowed
            executable_overrides={"cvc5": fake},
        )
        portfolio = SolverPortfolio(policy)
        _, denied = portfolio.resolve_attempts(
            [PortfolioAttemptSpec(translation=_smt_translation(), solver_name="cvc5")]
        )
        assert len(denied) == 1
        assert "allowed_solvers" in denied[0]["reason"]

    def test_denies_mismatched_target(self, tmp_path):
        fake = _make_fake_executable(tmp_path / "z3")
        policy = PortfolioPolicy(
            hammer_policy=_allow_policy("z3"), executable_overrides={"z3": fake}
        )
        portfolio = SolverPortfolio(policy)
        # z3 expects SMT-LIB, but this translation targets TPTP.
        _, denied = portfolio.resolve_attempts(
            [PortfolioAttemptSpec(translation=_tptp_translation(), solver_name="z3")]
        )
        assert len(denied) == 1
        assert "target" in denied[0]["reason"]

    def test_denies_unsupported_translation(self, tmp_path):
        fake = _make_fake_executable(tmp_path / "z3")
        policy = PortfolioPolicy(
            hammer_policy=_allow_policy("z3"), executable_overrides={"z3": fake}
        )
        portfolio = SolverPortfolio(policy)
        translation = TranslationRecord(
            translation_id="t-bad",
            request_id="req-1",
            target=TranslationTarget.SMTLIB,
            status=TranslationStatus.UNSUPPORTED,
            source_construct="goal",
            unsupported_reason="dependent type",
        )
        _, denied = portfolio.resolve_attempts(
            [PortfolioAttemptSpec(translation=translation, solver_name="z3")]
        )
        assert len(denied) == 1
        assert "UNSUPPORTED" in denied[0]["reason"]

    def test_denies_missing_executable(self):
        policy = PortfolioPolicy(hammer_policy=_allow_policy("z3"))
        portfolio = SolverPortfolio(policy)
        # No override configured and (almost certainly) no "z3" on PATH in a
        # bare test environment; if it genuinely is on PATH this assertion
        # would need a monkeypatch, but resolve_attempts must gracefully
        # deny rather than raise either way.
        import shutil

        if shutil.which("z3") is not None:
            pytest.skip("a real z3 executable is on PATH in this environment")
        _, denied = portfolio.resolve_attempts(
            [PortfolioAttemptSpec(translation=_smt_translation(), solver_name="z3")]
        )
        assert len(denied) == 1
        assert "no allowlisted executable" in denied[0]["reason"]


# ---------------------------------------------------------------------------
# SolverPortfolio.run with an injected fake process runner
# ---------------------------------------------------------------------------


class TestSolverPortfolioRun:
    def test_empty_attempts_returns_empty_result(self):
        policy = PortfolioPolicy(hammer_policy=_allow_policy("z3"))
        portfolio = SolverPortfolio(policy)
        result = portfolio.run("req-1", [])
        assert result.attempts == []
        assert result.denied == []

    def test_single_successful_attempt_produces_record_and_evidence(self, tmp_path):
        fake_z3 = _make_fake_executable(tmp_path / "z3")
        policy = PortfolioPolicy(
            hammer_policy=_allow_policy("z3"), executable_overrides={"z3": fake_z3}
        )

        def _runner(command, *, budget, cancel_event=None):
            return SolverProcessOutcome(
                command=command, returncode=0, stdout="sat\n", stderr="", wall_time_seconds=0.01
            )

        portfolio = SolverPortfolio(policy, process_runner=_runner, version_prober=lambda *_: "4.13.0")
        translation = _smt_translation()
        result = portfolio.run(
            "req-1", [PortfolioAttemptSpec(translation=translation, solver_name="z3")]
        )

        assert result.denied == []
        assert len(result.attempts) == 1
        record = result.attempts[0]
        assert isinstance(record, SolverAttemptRecord)
        assert record.solver_name == "z3"
        assert record.solver_version == "4.13.0"
        assert record.verdict is SolverVerdict.SAT
        assert record.translation_id == translation.translation_id
        assert record.network_used is False
        assert record.raw_output_digest is not None

        evidence = result.evidence[record.attempt_id]
        assert evidence.command[0] == fake_z3
        assert evidence.raw_stdout == "sat\n"
        assert evidence.input_digest is not None
        assert evidence.solver_trace == "sat"

        # Round trip through to_dict/from_dict.
        restored = PortfolioRunResult.from_dict(result.to_dict())
        assert restored.attempts[0].attempt_id == record.attempt_id
        assert restored.attempts[0].verdict is SolverVerdict.SAT

    def test_denied_attempt_produces_no_solver_attempt_record(self):
        policy = PortfolioPolicy(hammer_policy=_allow_policy("z3"))
        portfolio = SolverPortfolio(policy, process_runner=lambda *a, **k: SolverProcessOutcome(command=[]))
        result = portfolio.run(
            "req-1",
            [PortfolioAttemptSpec(translation=_smt_translation(), solver_name="ghost-solver")],
        )
        assert result.attempts == []
        assert len(result.denied) == 1

    def test_timeout_outcome_forces_timeout_verdict_and_wall_time_floor(self, tmp_path):
        fake_z3 = _make_fake_executable(tmp_path / "z3")
        policy = PortfolioPolicy(
            hammer_policy=_allow_policy("z3"),
            executable_overrides={"z3": fake_z3},
            solver_budgets={"z3": SolverBudget(timeout_seconds=5.0)},
        )

        def _runner(command, *, budget, cancel_event=None):
            return SolverProcessOutcome(
                command=command, timed_out=True, stdout="", stderr="", wall_time_seconds=4.9
            )

        portfolio = SolverPortfolio(policy, process_runner=_runner, version_prober=lambda *_: None)
        result = portfolio.run(
            "req-1", [PortfolioAttemptSpec(translation=_smt_translation(), solver_name="z3")]
        )
        record = result.attempts[0]
        assert record.verdict is SolverVerdict.TIMEOUT
        assert record.wall_time_seconds >= record.timeout_seconds

    def test_never_places_theorem_content_into_argv(self, tmp_path):
        fake_z3 = _make_fake_executable(tmp_path / "z3")
        policy = PortfolioPolicy(
            hammer_policy=_allow_policy("z3"), executable_overrides={"z3": fake_z3}
        )
        malicious = "$(rm -rf /tmp/should-not-run); `touch /tmp/pwned`"
        translation = _smt_translation(
            text=f"(declare-fun weird-name-{malicious} () Bool)\n(assert weird-name)"
        )

        def _runner(command, *, budget, cancel_event=None):
            return SolverProcessOutcome(command=command, stdout="unknown\n", stderr="")

        portfolio = SolverPortfolio(policy, process_runner=_runner, version_prober=lambda *_: None)
        result = portfolio.run(
            "req-1", [PortfolioAttemptSpec(translation=translation, solver_name="z3")]
        )
        evidence = next(iter(result.evidence.values()))
        # The malicious text must never appear as a literal argv token — it
        # only ever reached the solver by being written to the temporary
        # input file whose *path* is the last argv element.
        assert all(malicious not in part for part in evidence.command)
        assert evidence.command[-1].endswith(".smt2")

    def test_process_count_budget_bounds_concurrency(self, tmp_path):
        fake_z3 = _make_fake_executable(tmp_path / "z3")
        policy = PortfolioPolicy(
            hammer_policy=_allow_policy("z3"),
            executable_overrides={"z3": fake_z3},
            max_parallel_processes=2,
        )

        state = {"current": 0, "max": 0}
        lock = threading.Lock()

        def _runner(command, *, budget, cancel_event=None):
            with lock:
                state["current"] += 1
                state["max"] = max(state["max"], state["current"])
            time.sleep(0.05)
            with lock:
                state["current"] -= 1
            return SolverProcessOutcome(command=command, stdout="unknown\n")

        portfolio = SolverPortfolio(policy, process_runner=_runner, version_prober=lambda *_: None)
        attempts = [
            PortfolioAttemptSpec(
                translation=_smt_translation(translation_id=f"t-{i}"), solver_name="z3"
            )
            for i in range(6)
        ]
        result = portfolio.run("req-1", attempts)
        assert len(result.attempts) == 6
        assert state["max"] <= 2

    def test_cancels_other_attempts_on_first_conclusive_verdict(self, tmp_path):
        fake_z3 = _make_fake_executable(tmp_path / "z3")
        fake_cvc5 = _make_fake_executable(tmp_path / "cvc5")
        policy = PortfolioPolicy(
            hammer_policy=_allow_policy("z3", "cvc5"),
            executable_overrides={"z3": fake_z3, "cvc5": fake_cvc5},
            cancel_on_first_conclusive=True,
        )

        def _runner(command, *, budget, cancel_event=None):
            exe_name = os.path.basename(command[0])
            if exe_name == "cvc5":
                # Resolves immediately with a conclusive verdict.
                return SolverProcessOutcome(command=command, stdout="unsat\n")
            # z3: simulate a long-running attempt that cooperatively checks
            # the cancellation event, exactly like the real bounded runner.
            start = time.monotonic()
            while time.monotonic() - start < 2.0:
                if cancel_event is not None and cancel_event.is_set():
                    return SolverProcessOutcome(
                        command=command, cancelled=True, wall_time_seconds=time.monotonic() - start
                    )
                time.sleep(0.005)
            return SolverProcessOutcome(command=command, stdout="unknown\n", wall_time_seconds=2.0)

        portfolio = SolverPortfolio(policy, process_runner=_runner, version_prober=lambda *_: None)
        attempts = [
            PortfolioAttemptSpec(translation=_smt_translation(translation_id="t-z3"), solver_name="z3"),
            PortfolioAttemptSpec(
                translation=_smt_translation(translation_id="t-cvc5"), solver_name="cvc5"
            ),
        ]
        result = portfolio.run("req-1", attempts)

        assert len(result.attempts) == 2
        by_solver = {a.solver_name: a for a in result.attempts}
        assert by_solver["cvc5"].verdict is SolverVerdict.UNSAT
        assert by_solver["z3"].verdict is SolverVerdict.UNKNOWN
        assert len(result.cancelled_attempt_ids) == 1
        assert result.cancelled_attempt_ids[0] == by_solver["z3"].attempt_id

    def test_no_conclusive_result_ever_carries_a_verified_field(self):
        # The trust boundary (HAMMER-001) requires that nothing produced by
        # the portfolio can be mistaken for a verified theorem — enforced
        # structurally here by there being no such field to inspect.
        assert not hasattr(SolverAttemptRecord, "verified")
        assert not hasattr(SolverAttemptRecord, "kernel_accepted")
        assert not hasattr(PortfolioRunResult, "verified")


# ---------------------------------------------------------------------------
# run_bounded_solver_process
# ---------------------------------------------------------------------------


class TestRunBoundedSolverProcess:
    def test_never_uses_a_shell(self):
        source = inspect.getsource(run_bounded_solver_process)
        assert "shell=True" not in source

    def test_empty_command_reports_error(self):
        outcome = run_bounded_solver_process([], budget=SolverBudget())
        assert outcome.error == "empty command"

    def test_runs_a_real_short_lived_process(self):
        outcome = run_bounded_solver_process(
            ["python3", "-c", "print('sat')"], budget=SolverBudget(timeout_seconds=5.0)
        )
        assert outcome.returncode == 0
        assert outcome.stdout.strip() == "sat"
        assert not outcome.timed_out

    def test_enforces_wall_clock_timeout(self):
        outcome = run_bounded_solver_process(
            ["python3", "-c", "import time; time.sleep(5)"],
            budget=SolverBudget(timeout_seconds=0.2),
        )
        assert outcome.timed_out is True
        assert outcome.wall_time_seconds < 4.0

    def test_cancel_event_preempts_a_running_process(self):
        cancel_event = threading.Event()

        def _cancel_soon():
            time.sleep(0.1)
            cancel_event.set()

        threading.Thread(target=_cancel_soon).start()
        outcome = run_bounded_solver_process(
            ["python3", "-c", "import time; time.sleep(5)"],
            budget=SolverBudget(timeout_seconds=30.0),
            cancel_event=cancel_event,
        )
        assert outcome.cancelled is True
        assert outcome.wall_time_seconds < 4.0

    def test_already_cancelled_before_start_never_spawns(self):
        cancel_event = threading.Event()
        cancel_event.set()
        outcome = run_bounded_solver_process(
            ["python3", "-c", "print('should not run')"],
            budget=SolverBudget(),
            cancel_event=cancel_event,
        )
        assert outcome.cancelled is True
        assert outcome.stdout == ""
