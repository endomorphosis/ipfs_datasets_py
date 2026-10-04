"""Tests for BaseOptimizer Prometheus integration."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.common.base_optimizer import (
    BaseOptimizer,
    OptimizationContext,
    OptimizerConfig,
)


class _DummyOptimizer(BaseOptimizer):
    """Minimal concrete optimizer for BaseOptimizer integration tests."""

    def generate(self, input_data, context):
        return {"input": input_data}

    def critique(self, artifact, context):
        return 0.25, ["improve coverage"]

    def optimize(self, artifact, score, feedback, context):
        return artifact

    def validate(self, artifact, context):
        return True


def test_run_session_records_prometheus_metrics(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_PROMETHEUS", "true")

    optimizer = _DummyOptimizer(
        config=OptimizerConfig(
            max_iterations=3,
            target_score=0.95,
            early_stopping=False,
            validation_enabled=True,
        )
    )
    context = OptimizationContext(
        session_id="base-prom-001",
        input_data="x",
        domain="test",
    )

    result = optimizer.run_session("x", context)

    assert result["iterations"] == 3
    assert optimizer._prometheus_metrics is not None
    assert optimizer._prometheus_metrics.enabled is True
    assert len(optimizer._prometheus_metrics.scores) == 1
    assert optimizer._prometheus_metrics.current_round == 3
    assert len(optimizer._prometheus_metrics.durations) == 1
    assert optimizer._prometheus_metrics.scores[0].labels["domain"] == "test"
    assert optimizer._prometheus_metrics.scores[0].labels["optimizer_type"] == "_DummyOptimizer"


def test_run_session_with_prometheus_disabled_is_non_fatal(monkeypatch) -> None:
    monkeypatch.delenv("ENABLE_PROMETHEUS", raising=False)

    optimizer = _DummyOptimizer(
        config=OptimizerConfig(max_iterations=2, target_score=0.95, early_stopping=False)
    )
    context = OptimizationContext(
        session_id="base-prom-002",
        input_data="y",
        domain="test",
    )

    result = optimizer.run_session("y", context)

    assert result["valid"] is True
    assert result["iterations"] == 2
    assert optimizer._prometheus_metrics is not None
    assert optimizer._prometheus_metrics.enabled is False
    assert optimizer._prometheus_metrics.current_round == 0
    assert len(optimizer._prometheus_metrics.scores) == 0
