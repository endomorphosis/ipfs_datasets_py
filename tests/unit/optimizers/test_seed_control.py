"""Tests for deterministic seed control across optimizer entry points."""

from __future__ import annotations

import random

from ipfs_datasets_py.optimizers.agentic.base import (
    AgenticOptimizer,
    ChangeControlMethod,
    OptimizationMethod,
    OptimizationResult,
    OptimizationTask,
)
from ipfs_datasets_py.optimizers.common.base_optimizer import (
    BaseOptimizer,
    OptimizationContext,
    OptimizerConfig as BaseOptimizerConfig,
)
from ipfs_datasets_py.optimizers.common.optimizer_config import OptimizerConfig
from ipfs_datasets_py.optimizers.common.seed_control import apply_deterministic_seed


class _SeededBaseOptimizer(BaseOptimizer):
    def generate(self, input_data, context):
        return input_data

    def critique(self, artifact, context):
        return 1.0, []

    def optimize(self, artifact, score, feedback, context):
        return artifact


class _SeededAgenticOptimizer(AgenticOptimizer):
    def _get_method(self) -> OptimizationMethod:
        return OptimizationMethod.TEST_DRIVEN

    def optimize(self, task: OptimizationTask) -> OptimizationResult:
        return OptimizationResult(
            task_id=task.task_id,
            success=True,
            method=self.method,
            changes="none",
        )


def test_apply_deterministic_seed_reproducible_random() -> None:
    apply_deterministic_seed(1234)
    first = [random.random() for _ in range(3)]

    apply_deterministic_seed(1234)
    second = [random.random() for _ in range(3)]

    assert first == second


def test_base_optimizer_applies_seed_on_init() -> None:
    _SeededBaseOptimizer(config=BaseOptimizerConfig(seed=77))
    first = random.random()

    _SeededBaseOptimizer(config=BaseOptimizerConfig(seed=77))
    second = random.random()

    assert first == second


def test_agentic_optimizer_applies_seed_on_init() -> None:
    _SeededAgenticOptimizer(
        agent_id="a1",
        llm_router=None,
        change_control=ChangeControlMethod.PATCH,
        config=OptimizerConfig(seed=991),
    )
    first = random.random()

    _SeededAgenticOptimizer(
        agent_id="a2",
        llm_router=None,
        change_control=ChangeControlMethod.PATCH,
        config=OptimizerConfig(seed=991),
    )
    second = random.random()

    assert first == second


def test_base_optimizer_seed_none_does_not_crash() -> None:
    optimizer = _SeededBaseOptimizer(config=BaseOptimizerConfig(seed=None))
    context = OptimizationContext(session_id="seed-none", input_data="x", domain="test")
    result = optimizer.run_session("x", context)
    assert result["valid"] is True
