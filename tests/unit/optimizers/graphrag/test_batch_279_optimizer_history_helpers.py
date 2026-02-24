"""Tests for OntologyOptimizer history/stat helper methods."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
    OntologyOptimizer,
    OptimizationReport,
)


def _report(score: float, trend: str, batch_size: int) -> OptimizationReport:
    return OptimizationReport(
        average_score=score,
        trend=trend,
        metadata={"batch_size": batch_size},
    )


def test_optimizer_history_summary_and_latest_batch_size() -> None:
    optimizer = OntologyOptimizer(enable_tracing=False)
    optimizer._history = [  # type: ignore[attr-defined]
        _report(0.2, "improving", 2),
        _report(0.5, "stable", 3),
        _report(0.6, "stable", 4),
    ]

    summary = optimizer.history_summary()
    assert summary["count"] == 3
    assert summary["min"] == 0.2
    assert summary["max"] == 0.6
    assert summary["mean"] == pytest.approx((0.2 + 0.5 + 0.6) / 3)
    assert summary["trend"] == "stable"
    assert optimizer.latest_batch_size() == 4


def test_optimizer_convergence_rate_and_history_as_list() -> None:
    optimizer = OntologyOptimizer(enable_tracing=False)
    optimizer._history = [  # type: ignore[attr-defined]
        _report(0.50, "improving", 1),
        _report(0.505, "stable", 1),
        _report(0.60, "improving", 1),
    ]

    # Deltas: 0.005 and 0.095, so 1/2 pairs are below default threshold=0.01.
    assert optimizer.convergence_rate() == 0.5
    assert optimizer.history_as_list() == [0.50, 0.505, 0.60]
