"""WS12-06: Performance Budget Sentinel - budget assertion module.

Defines latency budget thresholds and raises a structured error when they are
exceeded.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

BUDGET_POLICY_VERSION = "1.0"

DEFAULT_BUDGETS_MS: Dict[str, float] = {
    "parse": 500.0,
    "compile_dcec": 500.0,
    "compile_tdfol": 500.0,
    "check_compliance": 500.0,
    "explain_proof": 500.0,
}


@dataclass
class BudgetViolation:
    """A single phase that exceeded its p95 latency budget."""

    phase: str
    budget_ms: float
    actual_p95_ms: float
    delta_ms: float


class BudgetAssertionError(Exception):
    """Raised when one or more phases exceed their p95 latency budget."""

    def __init__(self, violations: List[BudgetViolation]) -> None:
        self.violations = violations
        summary = "; ".join(
            f"{v.phase}: p95={v.actual_p95_ms:.3f}ms > budget={v.budget_ms:.3f}ms"
            for v in violations
        )
        super().__init__(f"Performance budget exceeded: {summary}")

    def machine_readable(self) -> Dict[str, Any]:
        """Return machine-readable over-budget diagnostics."""
        return {
            "budget_policy_version": BUDGET_POLICY_VERSION,
            "passed": False,
            "violations": [
                {
                    "phase": v.phase,
                    "budget_ms": v.budget_ms,
                    "actual_p95_ms": v.actual_p95_ms,
                    "delta_ms": v.delta_ms,
                }
                for v in self.violations
            ],
        }


def assert_budgets(
    benchmark_results: Dict[str, Any],
    budgets_ms: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Check benchmark results against latency budgets.

    Parameters
    ----------
    benchmark_results:
        Output from :func:`benchmark_hybrid_v2_reasoner.run_benchmark`.
    budgets_ms:
        Per-phase p95 budget in milliseconds.  Defaults to
        :data:`DEFAULT_BUDGETS_MS`.

    Returns
    -------
    dict
        ``{"budget_policy_version", "passed", "violations", "phases_checked"}``

    Raises
    ------
    BudgetAssertionError
        When any phase's p95 latency exceeds its budget.
    """
    if budgets_ms is None:
        budgets_ms = DEFAULT_BUDGETS_MS

    phases: Dict[str, Dict[str, Any]] = benchmark_results.get("phases", {})
    violations: List[BudgetViolation] = []
    phases_checked: List[str] = []

    for phase, budget in budgets_ms.items():
        if phase not in phases:
            continue
        phases_checked.append(phase)
        actual_p95 = phases[phase].get("p95_ms", 0.0)
        if actual_p95 > budget:
            violations.append(
                BudgetViolation(
                    phase=phase,
                    budget_ms=budget,
                    actual_p95_ms=actual_p95,
                    delta_ms=actual_p95 - budget,
                )
            )

    diagnostic: Dict[str, Any] = {
        "budget_policy_version": BUDGET_POLICY_VERSION,
        "passed": len(violations) == 0,
        "violations": [
            {
                "phase": v.phase,
                "budget_ms": v.budget_ms,
                "actual_p95_ms": v.actual_p95_ms,
                "delta_ms": v.delta_ms,
            }
            for v in violations
        ],
        "phases_checked": phases_checked,
    }

    if violations:
        raise BudgetAssertionError(violations)

    return diagnostic
