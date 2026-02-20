from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag import query_optimizer as qo


def test_query_metrics_collector_track_resources_safe_without_psutil_process(monkeypatch):
    """Regression test: optional psutil dependency must not crash metrics collection."""

    class PsutilWithoutProcess:
        pass

    monkeypatch.setattr(qo, "psutil", PsutilWithoutProcess(), raising=True)
    monkeypatch.setattr(qo, "HAVE_PSUTIL", False, raising=True)

    collector = qo.QueryMetricsCollector(track_resources=True)
    query_id = collector.start_query_tracking(query_params={"x": 1})

    assert isinstance(query_id, str)
    assert collector.current_query is not None
    assert collector.current_query["resources"]["initial_memory"] == 0
    assert collector.record_resource_usage() == {}
