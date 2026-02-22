"""Tests for optimizer hyperparameter tuning behavior.

Validates that optimizer configuration parameters (hyperparameters) influence
run_session outcomes in predictable ways.
"""

from __future__ import annotations

from ipfs_datasets_py.optimizers.common.base_optimizer import (
    BaseOptimizer,
    OptimizerConfig,
    OptimizationContext,
)


class _TunedOptimizer(BaseOptimizer):
    """Minimal optimizer that uses config parameters to shape score updates."""

    def __init__(self, config: OptimizerConfig) -> None:
        super().__init__(config=config)
        self._score = 0.2

    def generate(self, input_data, context):
        return {"input": input_data}

    def critique(self, artifact, context):
        return self._score, []

    def optimize(self, artifact, score, feedback, context):
        # Use learning_rate to control improvement magnitude.
        self._score = min(1.0, self._score + (self.config.learning_rate * 0.2))
        return artifact


def _make_context() -> OptimizationContext:
    return OptimizationContext(
        session_id="tune-1",
        input_data="input",
        domain="test",
    )


def test_higher_learning_rate_improves_score_more():
    """Higher learning_rate should produce a higher final score."""
    ctx = _make_context()

    slow_cfg = OptimizerConfig(
        learning_rate=0.05,
        max_iterations=5,
        target_score=0.95,
        early_stopping=False,
        validation_enabled=False,
    )
    fast_cfg = OptimizerConfig(
        learning_rate=0.5,
        max_iterations=5,
        target_score=0.95,
        early_stopping=False,
        validation_enabled=False,
    )

    slow_opt = _TunedOptimizer(config=slow_cfg)
    fast_opt = _TunedOptimizer(config=fast_cfg)

    slow_result = slow_opt.run_session("data", ctx)
    fast_result = fast_opt.run_session("data", ctx)

    assert fast_result["score"] > slow_result["score"]


def test_target_score_stops_early():
    """Target score should stop the loop before max_iterations."""
    cfg = OptimizerConfig(
        learning_rate=0.5,
        max_iterations=10,
        target_score=0.5,
        early_stopping=False,
        validation_enabled=False,
    )
    opt = _TunedOptimizer(config=cfg)
    ctx = _make_context()

    result = opt.run_session("data", ctx)

    assert result["score"] >= cfg.target_score
    assert result["iterations"] < cfg.max_iterations


def test_max_iterations_caps_progress():
    """max_iterations should cap optimization when target is unreachable."""
    cfg = OptimizerConfig(
        learning_rate=0.01,
        max_iterations=2,
        target_score=0.95,
        early_stopping=False,
        validation_enabled=False,
    )
    opt = _TunedOptimizer(config=cfg)
    ctx = _make_context()

    result = opt.run_session("data", ctx)

    assert result["iterations"] == cfg.max_iterations
    assert result["score"] < cfg.target_score


def test_zero_convergence_threshold_allows_iterations():
    """convergence_threshold=0 should not trigger early stopping on zero improvement."""
    cfg = OptimizerConfig(
        learning_rate=0.2,
        max_iterations=3,
        target_score=0.95,
        early_stopping=True,
        convergence_threshold=0.0,
        validation_enabled=False,
    )
    opt = _TunedOptimizer(config=cfg)
    ctx = _make_context()

    result = opt.run_session("data", ctx)

    assert result["iterations"] == cfg.max_iterations
