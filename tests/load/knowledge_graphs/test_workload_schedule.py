"""Deterministic workload coverage for short load profiles."""

from __future__ import annotations

import random

from benchmarks.knowledge_graphs.profiles import WorkloadMix
from benchmarks.knowledge_graphs.workloads import _operation_plan


def test_positive_weight_operations_cannot_disappear_by_seed() -> None:
    mix = WorkloadMix(
        write_weight=0.4,
        read_weight=0.3,
        query_weight=0.3,
        operations=12,
    )
    for seed in range(250):
        plan = _operation_plan(random.Random(seed), mix)
        assert len(plan) == 12
        assert set(plan) == {"write", "read", "query"}
        assert plan.count("write") == 5
        assert plan.count("read") + plan.count("query") == 7


def test_schedule_is_repeatable_for_the_same_seed() -> None:
    mix = WorkloadMix(operations=9)
    assert _operation_plan(random.Random(31), mix) == _operation_plan(
        random.Random(31), mix
    )
