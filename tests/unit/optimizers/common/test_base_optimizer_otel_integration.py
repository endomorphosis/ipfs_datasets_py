"""Tests for BaseOptimizer OpenTelemetry session span integration."""

from __future__ import annotations

from ipfs_datasets_py.optimizers.common.base_optimizer import (
    BaseOptimizer,
    OptimizationContext,
    OptimizerConfig,
)


class _SpanRecorder:
    def __init__(self, name: str, sink: list[tuple[str, dict[str, object]]]) -> None:
        self._name = name
        self._sink = sink
        self._attrs: dict[str, object] = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self._sink.append((self._name, dict(self._attrs)))
        return False

    def set_attribute(self, key: str, value: object) -> None:
        self._attrs[key] = value


class _TracerRecorder:
    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, object]]] = []

    def start_as_current_span(self, name: str) -> _SpanRecorder:
        return _SpanRecorder(name, self.spans)


class _DummyOptimizer(BaseOptimizer):
    def generate(self, input_data, context):
        return {"input": input_data}

    def critique(self, artifact, context):
        return 0.33, ["improve"]

    def optimize(self, artifact, score, feedback, context):
        return artifact


def _context() -> OptimizationContext:
    return OptimizationContext(session_id="otel-base-001", input_data="x", domain="test")


def test_base_optimizer_run_session_otel_span_enabled(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_ENABLED", "true")

    optimizer = _DummyOptimizer(
        config=OptimizerConfig(max_iterations=2, target_score=0.9, early_stopping=False)
    )
    tracer = _TracerRecorder()
    optimizer._otel_tracer = tracer

    result = optimizer.run_session("x", _context())

    assert result["iterations"] == 2
    assert len(tracer.spans) == 1
    span_name, attrs = tracer.spans[0]
    assert span_name == "optimizer.run_session"
    assert attrs["optimizer.session_id"] == "otel-base-001"
    assert attrs["optimizer.domain"] == "test"
    assert attrs["optimizer.iterations"] == 2
    assert attrs["optimizer.valid"] is True


def test_base_optimizer_run_session_otel_span_disabled(monkeypatch) -> None:
    monkeypatch.delenv("OTEL_ENABLED", raising=False)

    optimizer = _DummyOptimizer(
        config=OptimizerConfig(max_iterations=1, target_score=0.9, early_stopping=False)
    )
    tracer = _TracerRecorder()
    optimizer._otel_tracer = tracer

    optimizer.run_session("x", _context())

    assert tracer.spans == []
