"""Tests for WS12-06: Performance Budget Sentinel."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure the scripts modules are importable.
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "legal_data"
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

import pytest

from assert_hybrid_v2_perf_budgets import (
    BUDGET_POLICY_VERSION,
    DEFAULT_BUDGETS_MS,
    BudgetAssertionError,
    BudgetViolation,
    assert_budgets,
)
from benchmark_hybrid_v2_reasoner import BENCHMARK_SCHEMA_VERSION, PHASES, run_benchmark


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def benchmark_results():
    """Run benchmark once per module to keep test suite fast."""
    return run_benchmark(iterations=3)


# ---------------------------------------------------------------------------
# run_benchmark tests
# ---------------------------------------------------------------------------

class TestRunBenchmark:
    def test_returns_all_phases(self, benchmark_results):
        phases = benchmark_results["phases"]
        for phase in PHASES:
            assert phase in phases, f"Missing phase: {phase}"

    def test_each_phase_has_required_keys(self, benchmark_results):
        for phase in PHASES:
            data = benchmark_results["phases"][phase]
            for key in ("p50_ms", "p95_ms", "p99_ms", "samples"):
                assert key in data, f"Phase {phase!r} missing key {key!r}"

    def test_schema_version_present(self, benchmark_results):
        assert benchmark_results["schema_version"] == BENCHMARK_SCHEMA_VERSION

    def test_samples_positive(self, benchmark_results):
        for phase in PHASES:
            assert benchmark_results["phases"][phase]["samples"] > 0

    def test_latencies_are_non_negative(self, benchmark_results):
        for phase in PHASES:
            data = benchmark_results["phases"][phase]
            assert data["p50_ms"] >= 0.0
            assert data["p95_ms"] >= 0.0
            assert data["p99_ms"] >= 0.0

    def test_p50_le_p95_le_p99(self, benchmark_results):
        for phase in PHASES:
            data = benchmark_results["phases"][phase]
            assert data["p50_ms"] <= data["p95_ms"] + 1e-9
            assert data["p95_ms"] <= data["p99_ms"] + 1e-9


# ---------------------------------------------------------------------------
# assert_budgets tests
# ---------------------------------------------------------------------------

class TestAssertBudgets:
    def test_passes_with_generous_budget(self, benchmark_results):
        result = assert_budgets(benchmark_results, budgets_ms={p: 999_999.0 for p in PHASES})
        assert result["passed"] is True
        assert result["violations"] == []

    def test_passes_with_default_budgets(self, benchmark_results):
        # Default budgets are 500ms each; CI should easily pass.
        result = assert_budgets(benchmark_results)
        assert result["passed"] is True

    def test_budget_policy_version_in_result(self, benchmark_results):
        result = assert_budgets(benchmark_results, budgets_ms={p: 999_999.0 for p in PHASES})
        assert result["budget_policy_version"] == BUDGET_POLICY_VERSION

    def test_phases_checked_in_result(self, benchmark_results):
        budgets = {p: 999_999.0 for p in PHASES}
        result = assert_budgets(benchmark_results, budgets_ms=budgets)
        for phase in PHASES:
            assert phase in result["phases_checked"]

    def test_raises_on_tight_budget(self, benchmark_results):
        tight = {p: 0.0001 for p in PHASES}
        with pytest.raises(BudgetAssertionError):
            assert_budgets(benchmark_results, budgets_ms=tight)

    def test_exception_has_violations(self, benchmark_results):
        tight = {p: 0.0001 for p in PHASES}
        with pytest.raises(BudgetAssertionError) as exc_info:
            assert_budgets(benchmark_results, budgets_ms=tight)
        assert len(exc_info.value.violations) > 0

    def test_exception_machine_readable(self, benchmark_results):
        tight = {p: 0.0001 for p in PHASES}
        with pytest.raises(BudgetAssertionError) as exc_info:
            assert_budgets(benchmark_results, budgets_ms=tight)
        mr = exc_info.value.machine_readable()
        assert mr["passed"] is False
        assert "violations" in mr
        assert mr["budget_policy_version"] == BUDGET_POLICY_VERSION

    def test_custom_very_large_budget_always_passes(self, benchmark_results):
        result = assert_budgets(benchmark_results, budgets_ms={p: 1_000_000.0 for p in PHASES})
        assert result["passed"] is True


# ---------------------------------------------------------------------------
# BudgetViolation tests
# ---------------------------------------------------------------------------

class TestBudgetViolation:
    def test_fields_present(self):
        v = BudgetViolation(
            phase="parse",
            budget_ms=1.0,
            actual_p95_ms=5.0,
            delta_ms=4.0,
        )
        assert v.phase == "parse"
        assert v.budget_ms == 1.0
        assert v.actual_p95_ms == 5.0
        assert v.delta_ms == 4.0

    def test_violation_in_tight_budget(self, benchmark_results):
        tight = {"parse": 0.0001}
        with pytest.raises(BudgetAssertionError) as exc_info:
            assert_budgets(benchmark_results, budgets_ms=tight)
        violations = exc_info.value.violations
        assert any(v.phase == "parse" for v in violations)
        for v in violations:
            assert v.actual_p95_ms > v.budget_ms
            assert v.delta_ms == pytest.approx(v.actual_p95_ms - v.budget_ms)


# ---------------------------------------------------------------------------
# BudgetAssertionError machine_readable tests
# ---------------------------------------------------------------------------

class TestBudgetAssertionErrorMachineReadable:
    def test_machine_readable_violation_keys(self, benchmark_results):
        tight = {"parse": 0.0001}
        with pytest.raises(BudgetAssertionError) as exc_info:
            assert_budgets(benchmark_results, budgets_ms=tight)
        mr = exc_info.value.machine_readable()
        for violation in mr["violations"]:
            for key in ("phase", "budget_ms", "actual_p95_ms", "delta_ms"):
                assert key in violation
