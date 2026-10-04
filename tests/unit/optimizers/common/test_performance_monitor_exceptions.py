"""Exception-handling tests for performance monitor persistence paths."""

from __future__ import annotations

import pytest

from ipfs_datasets_py.optimizers.common.performance_monitor import PerformanceMetricsCollector


def test_load_from_disk_handles_typed_json_error(tmp_path) -> None:
    bad_json = tmp_path / "bad_metrics.json"
    bad_json.write_text("{ this is not valid json }", encoding="utf-8")

    collector = PerformanceMetricsCollector(persistence_path=bad_json)

    assert collector.get_statistics()["overall_stats"]["total_cycles"] == 0


def test_load_from_disk_does_not_swallow_keyboard_interrupt(monkeypatch, tmp_path) -> None:
    metrics_path = tmp_path / "metrics.json"
    metrics_path.write_text("{}", encoding="utf-8")

    monkeypatch.setattr(
        "builtins.open",
        lambda *args, **kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        PerformanceMetricsCollector(persistence_path=metrics_path)
