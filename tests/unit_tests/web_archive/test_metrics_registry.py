#!/usr/bin/env python3

import pytest

from ipfs_datasets_py.processors.web_archiving.metrics.registry import MetricsRegistry


def test_registry_records_and_aggregates_snapshot() -> None:
    registry = MetricsRegistry(default_windows_seconds=(10, 60))

    # Use deterministic timestamps for reliable assertions.
    registry.record_event(
        provider="common_crawl",
        operation="fetch",
        success=True,
        latency_ms=100,
        items_processed=4,
        quality_score=0.8,
        timestamp=100.0,
    )
    registry.record_event(
        provider="common_crawl",
        operation="fetch",
        success=False,
        latency_ms=200,
        items_processed=0,
        error_type="timeout",
        timestamp=105.0,
    )

    snap = registry.snapshot(
        provider="common_crawl",
        operation="fetch",
        window_seconds=10,
        now_ts=110.0,
    )

    assert snap["total_requests"] == 2.0
    assert snap["successes"] == 1.0
    assert snap["failures"] == 1.0
    assert snap["success_rate"] == pytest.approx(0.5)
    assert snap["avg_latency_ms"] == pytest.approx(150.0)
    assert snap["p95_latency_ms"] in {100.0, 200.0}
    assert snap["items_processed"] == 4.0
    assert snap["throughput_items_per_sec"] == pytest.approx(0.4)
    assert snap["avg_quality_score"] == pytest.approx(0.8)


def test_registry_prunes_old_events_by_max_window() -> None:
    registry = MetricsRegistry(default_windows_seconds=(10, 30))
    registry.record_event(
        provider="brave",
        operation="search",
        success=True,
        latency_ms=50,
        items_processed=3,
        timestamp=100.0,
    )
    registry.record_event(
        provider="brave",
        operation="search",
        success=True,
        latency_ms=70,
        items_processed=2,
        timestamp=140.0,
    )

    # Event at t=100 should be pruned because max window is 30 seconds.
    snap = registry.snapshot(
        provider="brave",
        operation="search",
        window_seconds=30,
        now_ts=140.0,
    )

    assert snap["total_requests"] == 1.0
    assert snap["items_processed"] == 2.0


def test_snapshots_for_all_windows() -> None:
    registry = MetricsRegistry(default_windows_seconds=(5, 10))
    registry.record_event(
        provider="duckduckgo",
        operation="search",
        success=True,
        latency_ms=90,
        items_processed=5,
        timestamp=200.0,
    )

    snaps = registry.snapshots_for_all_windows(
        provider="duckduckgo",
        operation="search",
        now_ts=201.0,
    )

    assert set(snaps.keys()) == {"5s", "10s"}
    assert snaps["5s"]["total_requests"] == 1.0
    assert snaps["10s"]["total_requests"] == 1.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {
            "provider": "",
            "operation": "fetch",
            "success": True,
            "latency_ms": 1,
        },
        {
            "provider": "common_crawl",
            "operation": "",
            "success": True,
            "latency_ms": 1,
        },
        {
            "provider": "common_crawl",
            "operation": "fetch",
            "success": True,
            "latency_ms": -1,
        },
        {
            "provider": "common_crawl",
            "operation": "fetch",
            "success": True,
            "latency_ms": 1,
            "items_processed": -1,
        },
        {
            "provider": "common_crawl",
            "operation": "fetch",
            "success": True,
            "latency_ms": 1,
            "quality_score": 1.2,
        },
    ],
)
def test_registry_record_validation(kwargs) -> None:
    registry = MetricsRegistry()
    with pytest.raises(ValueError):
        registry.record_event(**kwargs)


def test_registry_reset_and_keys() -> None:
    registry = MetricsRegistry(default_windows_seconds=(5,))
    registry.record_event(
        provider="wayback",
        operation="fetch",
        success=True,
        latency_ms=42,
        timestamp=300.0,
    )
    assert registry.provider_operation_keys() == [("wayback", "fetch")]

    registry.reset()
    assert registry.provider_operation_keys() == []
