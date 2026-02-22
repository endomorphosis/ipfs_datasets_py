from __future__ import annotations

from ipfs_datasets_py.optimizers.graphrag import query_optimizer as qo
from ipfs_datasets_py.optimizers.graphrag import query_metrics


def test_query_metrics_collector_track_resources_safe_without_psutil_process(monkeypatch):
    """Regression test: optional psutil dependency must not crash metrics collection."""

    class PsutilWithoutProcess:
        pass

    # Monkeypatch the query_metrics module since QueryMetricsCollector is now defined there
    monkeypatch.setattr(query_metrics, "psutil", PsutilWithoutProcess(), raising=True)
    monkeypatch.setattr(query_metrics, "HAVE_PSUTIL", False, raising=True)

    collector = qo.QueryMetricsCollector(track_resources=True)
    query_id = collector.start_query_tracking(query_params={"x": 1})

    assert isinstance(query_id, str)
    assert collector.current_query is not None
    assert collector.current_query["resources"]["initial_memory"] == 0
    assert collector.record_resource_usage() == {}


def test_query_metrics_collector_health_check_empty_history():
    """Health check should return safe defaults when no sessions exist."""
    collector = qo.QueryMetricsCollector(track_resources=False)

    health = collector.get_health_check()

    assert health["status"] == "ok"
    assert isinstance(health["memory_usage_bytes"], int)
    assert health["memory_usage_bytes"] >= 0
    assert health["last_session_duration_seconds"] is None
    assert health["error_rate_last_100"] == 0.0
    assert health["evaluated_sessions"] == 0


def test_query_metrics_collector_health_check_error_rate_window():
    """Health check should compute error rate from recent sessions."""
    collector = qo.QueryMetricsCollector(track_resources=False)

    # 3 successful sessions
    for _ in range(3):
        collector.start_query_tracking()
        collector.end_query_tracking(results_count=1, quality_score=0.9)

    # 1 failed session
    collector.start_query_tracking()
    collector.end_query_tracking(
        results_count=0,
        quality_score=0.0,
        error_message="timeout",
    )

    health = collector.get_health_check(window_size=100)

    assert health["evaluated_sessions"] == 4
    assert health["error_rate_last_100"] == 0.25
    assert health["status"] == "degraded"
    assert isinstance(health["last_session_duration_seconds"], float)


def test_query_metrics_collector_health_check_reports_process_memory(monkeypatch):
    """Health check should report process RSS when psutil is available."""

    class _FakeMem:
        rss = 123456
        vms = 0

    class _FakeProcess:
        def memory_info(self):
            return _FakeMem()

    class _PsutilWithProcess:
        @staticmethod
        def Process():
            return _FakeProcess()

    # Monkeypatch the query_metrics module since QueryMetricsCollector is now defined there
    monkeypatch.setattr(query_metrics, "psutil", _PsutilWithProcess(), raising=True)
    monkeypatch.setattr(query_metrics, "HAVE_PSUTIL", True, raising=True)

    collector = qo.QueryMetricsCollector(track_resources=False)
    health = collector.get_health_check()

    assert health["memory_usage_bytes"] == 123456
