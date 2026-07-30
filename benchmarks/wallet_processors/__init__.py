"""Deterministic wallet-processor fixture benchmarks (WALPROC-G640).

Default execution is offline and fixture-only.  Live provider latency is never
used to set performance budgets.
"""

from __future__ import annotations

from .runner import (
    BenchmarkReport,
    FixtureBenchmarkResult,
    run_fixture_benchmark,
)

__all__ = [
    "BenchmarkReport",
    "FixtureBenchmarkResult",
    "run_fixture_benchmark",
]
