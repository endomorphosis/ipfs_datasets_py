"""Tests for BaseOptimizer lifecycle hook integration."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.common.base_optimizer import (
    BaseOptimizer,
    OptimizationContext,
    OptimizerConfig,
)


class _HookedOptimizer(BaseOptimizer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.events = []

    def generate(self, input_data, context):
        return {"value": input_data}

    def critique(self, artifact, context):
        return 0.2, ["improve"]

    def optimize(self, artifact, score, feedback, context):
        return artifact

    def validate(self, artifact, context):
        return True

    def on_session_start(self, context, input_data):
        self.events.append(("start", context.session_id))

    def on_generate_complete(self, artifact, context):
        self.events.append(("generate", artifact["value"]))

    def on_critique_complete(self, artifact, score, feedback, context):
        self.events.append(("critique", round(score, 2)))

    def on_optimize_complete(self, artifact, score, feedback, iteration, context):
        self.events.append(("optimize", iteration))

    def on_validate_complete(self, artifact, valid, context):
        self.events.append(("validate", valid))

    def on_session_complete(self, result, context):
        self.events.append(("complete", result["iterations"]))


class _FailingHookOptimizer(_HookedOptimizer):
    def on_generate_complete(self, artifact, context):
        raise RuntimeError("hook failure")


def test_lifecycle_hooks_fire_in_expected_order() -> None:
    optimizer = _HookedOptimizer(
        config=OptimizerConfig(max_iterations=2, target_score=0.95, early_stopping=False)
    )
    context = OptimizationContext(
        session_id="hooks-001",
        input_data="x",
        domain="test",
    )

    result = optimizer.run_session("x", context)
    assert result["valid"] is True

    labels = [name for name, _ in optimizer.events]
    assert labels[0] == "start"
    assert labels[1] == "generate"
    assert labels[2] == "critique"
    assert labels.count("optimize") == 2
    assert labels.count("critique") == 3  # initial + after each optimize
    assert labels[-2] == "validate"
    assert labels[-1] == "complete"


def test_hook_exceptions_are_non_fatal() -> None:
    optimizer = _FailingHookOptimizer(
        config=OptimizerConfig(max_iterations=1, target_score=0.95, early_stopping=False)
    )
    context = OptimizationContext(
        session_id="hooks-002",
        input_data="x",
        domain="test",
    )

    result = optimizer.run_session("x", context)
    assert result["valid"] is True
    assert result["iterations"] == 1
