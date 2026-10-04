"""Tests for BaseOptimizer hyperparameter behavior in run_session()."""

import pytest

from ipfs_datasets_py.optimizers.common.base_optimizer import (
    BaseOptimizer,
    OptimizerConfig,
    OptimizationContext,
)


class TuningOptimizer(BaseOptimizer):
    """Deterministic optimizer for hyperparameter behavior tests."""

    def __init__(self, initial_score=0.2, step=0.0, config=None):
        super().__init__(config=config)
        self._score = float(initial_score)
        self._step = float(step)

    def generate(self, input_data, context):
        return {"input": input_data, "score": self._score}

    def critique(self, artifact, context):
        return float(self._score), []

    def optimize(self, artifact, score, feedback, context):
        self._score = min(1.0, self._score + self._step)
        return artifact


class TestOptimizerHyperparameterTuning:
    """Validate config knobs that influence run_session control flow."""

    def _context(self):
        return OptimizationContext(
            session_id="tuning-session",
            input_data="sample",
            domain="test",
        )

    def test_max_iterations_respected_without_early_stopping(self):
        """max_iterations should cap loop when early_stopping is disabled."""
        config = OptimizerConfig(
            max_iterations=3,
            target_score=1.0,
            early_stopping=False,
        )
        optimizer = TuningOptimizer(initial_score=0.2, step=0.0, config=config)

        result = optimizer.run_session("data", self._context())

        assert result["iterations"] == 3

    def test_target_score_stops_early(self):
        """target_score should terminate the loop before max_iterations."""
        config = OptimizerConfig(
            max_iterations=5,
            target_score=0.4,
            early_stopping=False,
        )
        optimizer = TuningOptimizer(initial_score=0.2, step=0.2, config=config)

        result = optimizer.run_session("data", self._context())

        assert result["iterations"] == 2

    def test_convergence_threshold_triggers_early_stop(self):
        """convergence_threshold should stop when improvement is too small."""
        config = OptimizerConfig(
            max_iterations=5,
            target_score=1.0,
            early_stopping=True,
            convergence_threshold=0.01,
        )
        optimizer = TuningOptimizer(initial_score=0.2, step=0.0, config=config)

        result = optimizer.run_session("data", self._context())

        assert result["iterations"] == 1

    def test_early_stopping_disabled_ignores_threshold(self):
        """convergence_threshold should be ignored when early_stopping is off."""
        config = OptimizerConfig(
            max_iterations=4,
            target_score=1.0,
            early_stopping=False,
            convergence_threshold=0.9,
        )
        optimizer = TuningOptimizer(initial_score=0.2, step=0.0, config=config)

        result = optimizer.run_session("data", self._context())

        assert result["iterations"] == 4
