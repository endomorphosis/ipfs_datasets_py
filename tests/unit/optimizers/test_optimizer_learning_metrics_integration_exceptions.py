"""Exception-path regression tests for optimizer_learning_metrics_integration."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from ipfs_datasets_py.optimizers.optimizer_learning_metrics_integration import (
    MetricsCollectorAdapter,
    enhance_optimizer_with_learning_metrics,
)


def test_export_metrics_csv_returns_none_on_typed_write_error(monkeypatch, tmp_path):
    adapter = MetricsCollectorAdapter(metrics_dir=str(tmp_path))
    query_id = adapter.start_query_tracking({"q": "demo"})
    adapter.end_query_tracking(results_count=1, quality_score=0.9)
    assert query_id in adapter.query_metrics

    def _raise_oserror(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("builtins.open", _raise_oserror)
    assert adapter.export_metrics_csv(str(tmp_path / "out.csv")) is None


def test_export_metrics_csv_propagates_base_exception(monkeypatch, tmp_path):
    adapter = MetricsCollectorAdapter(metrics_dir=str(tmp_path))

    def _raise_interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt("stop")

    monkeypatch.setattr("builtins.open", _raise_interrupt)
    with pytest.raises(KeyboardInterrupt):
        adapter.export_metrics_csv(str(tmp_path / "out.csv"))


def test_instrumented_learn_catches_typed_result_shape_errors(tmp_path):
    optimizer = SimpleNamespace(metrics_collector=None)
    sentinel = object()

    def _learn(_self, _count=50):
        return sentinel

    optimizer._learn_from_query_statistics = _learn
    enhanced = enhance_optimizer_with_learning_metrics(optimizer, metrics_dir=str(tmp_path))
    result = enhanced._learn_from_query_statistics()
    assert result is sentinel


def test_instrumented_learn_propagates_base_exception(tmp_path):
    class _InterruptingResult:
        def get(self, *_args, **_kwargs):
            raise KeyboardInterrupt("stop")

    optimizer = SimpleNamespace(metrics_collector=None)

    def _learn(_self, _count=50):
        return _InterruptingResult()

    optimizer._learn_from_query_statistics = _learn
    enhanced = enhance_optimizer_with_learning_metrics(optimizer, metrics_dir=str(tmp_path))

    with pytest.raises(KeyboardInterrupt):
        enhanced._learn_from_query_statistics()
