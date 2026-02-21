import types

import pytest

from ipfs_datasets_py.optimizers import advanced_performance_optimizer as apo


@pytest.fixture
def optimizer():
    return apo.AdvancedPerformanceOptimizer()


def _metrics(**overrides):
    base = apo.ResourceMetrics(
        cpu_percent=50.0,
        memory_percent=50.0,
        memory_available_gb=2.0,
        memory_used_gb=2.0,
        disk_usage_percent=50.0,
        network_io={},
        process_memory_mb=100.0,
    )
    for key, value in overrides.items():
        setattr(base, key, value)
    return base


def test_calculate_optimal_config_low_memory(optimizer, monkeypatch):
    monkeypatch.setattr(apo.psutil, "cpu_count", lambda: 8)
    metrics = _metrics(memory_available_gb=0.5, cpu_percent=50.0)

    config = optimizer._calculate_optimal_config(
        content_count=10,
        estimated_size_mb=10.0,
        processing_type="standard",
        metrics=metrics,
    )

    assert config["batch_size"] <= 5
    assert config["max_workers"] <= 2
    assert config["enable_caching"] is False
    assert config["gc_frequency"] == 5


def test_calculate_optimal_config_high_memory_low_cpu(optimizer, monkeypatch):
    monkeypatch.setattr(apo.psutil, "cpu_count", lambda: 8)
    metrics = _metrics(memory_available_gb=5.0, cpu_percent=20.0)

    config = optimizer._calculate_optimal_config(
        content_count=10,
        estimated_size_mb=10.0,
        processing_type="standard",
        metrics=metrics,
    )

    assert config["batch_size"] >= optimizer.target_profile.batch_size
    assert config["max_workers"] == 8
    assert config["enable_caching"] is True


def test_calculate_optimal_config_fast_profile(optimizer, monkeypatch):
    monkeypatch.setattr(apo.psutil, "cpu_count", lambda: 8)
    metrics = _metrics(memory_available_gb=2.0, cpu_percent=50.0)

    config = optimizer._calculate_optimal_config(
        content_count=10,
        estimated_size_mb=10.0,
        processing_type="fast",
        metrics=metrics,
    )

    assert config["quality_threshold"] == 0.4
    assert config["processing_timeout"] == 60
    assert config["enable_caching"] is False


def test_get_optimization_recommendations(optimizer, monkeypatch):
    monkeypatch.setattr(apo.psutil, "cpu_count", lambda: 8)
    metrics = _metrics(memory_percent=90.0, cpu_percent=90.0, disk_usage_percent=95.0)

    recs = optimizer.get_optimization_recommendations(metrics, content_count=200)
    optimizations = {rec["optimization"] for rec in recs}

    assert "reduce_batch_size" in optimizations
    assert "reduce_workers" in optimizations
    assert "use_fast_profile" in optimizations
    assert "cleanup_storage" in optimizations


def test_generate_recommendations_with_history(optimizer):
    metrics = _metrics(memory_percent=90.0, cpu_percent=95.0, memory_available_gb=3.0)
    config = {
        "batch_size": 4,
        "max_workers": 2,
        "chunk_size": 500,
        "enable_caching": True,
        "quality_threshold": 0.6,
        "processing_timeout": 300,
        "gc_frequency": 10,
    }

    optimizer.processing_history.extend({"duration": 40} for _ in range(11))
    recs = optimizer._generate_recommendations(metrics, config)

    categories = {rec.category for rec in recs}
    assert "memory" in categories
    assert "cpu" in categories
    assert "configuration" in categories
    assert "performance" in categories


def test_estimate_processing_time_returns_positive_values(optimizer):
    config = {
        "max_workers": 2,
        "batch_size": 10,
        "quality_threshold": 0.6,
    }

    estimate = optimizer._estimate_processing_time(
        content_count=100,
        estimated_size_mb=50.0,
        config=config,
    )

    assert estimate["estimated_seconds"] > 0
    assert estimate["estimated_minutes"] > 0
    assert estimate["items_per_second"] > 0
    assert estimate["quality_factor"] > 0
    assert estimate["size_factor"] > 0


def test_track_processing_operation_runs_gc(optimizer, monkeypatch):
    called = {"gc": 0}

    def fake_collect():
        called["gc"] += 1
        return 0

    monkeypatch.setattr(apo.gc, "collect", fake_collect)
    monkeypatch.setattr(
        optimizer,
        "_collect_resource_metrics",
        lambda: _metrics(memory_percent=40.0),
    )

    optimizer.adaptive_parameters["gc_frequency"] = 1
    optimizer.track_processing_operation(
        operation_type="test",
        duration=1.0,
        items_processed=10,
        success_rate=0.95,
        memory_used_mb=50.0,
    )

    assert called["gc"] == 1
    assert optimizer.adaptive_parameters["operation_count"] == 1


def test_emergency_memory_cleanup_reduces_state(optimizer):
    optimizer.processing_history.extend({"duration": 1.0} for _ in range(15))
    optimizer.resource_history.extend(_metrics() for _ in range(25))

    optimizer.adaptive_parameters["current_batch_size"] = 20
    optimizer.adaptive_parameters["current_workers"] = 4
    optimizer.adaptive_parameters["gc_frequency"] = 10

    optimizer._emergency_memory_cleanup()

    assert len(optimizer.processing_history) == 10
    assert len(optimizer.resource_history) == 20
    assert optimizer.adaptive_parameters["current_batch_size"] == 10
    assert optimizer.adaptive_parameters["current_workers"] == 2
    assert optimizer.adaptive_parameters["gc_frequency"] == 1


def test_get_performance_report_no_history(optimizer):
    report = optimizer.get_performance_report()
    assert report["error"] == "No processing history available"
