"""Tests for Prometheus metrics integration."""

import os
import pytest
from ipfs_datasets_py.optimizers.common.metrics_prometheus import (
    PrometheusMetrics,
    MetricValue,
)


class TestPrometheusMetricsInit:
    """Test PrometheusMetrics initialization."""
    
    def test_init_disabled_by_default(self):
        """Test that metrics are disabled by default."""
        # Ensure env var is not set
        os.environ.pop("ENABLE_PROMETHEUS", None)
        metrics = PrometheusMetrics()
        
        assert metrics.enabled is False
    
    def test_init_enabled_explicit(self):
        """Test explicit enablement."""
        metrics = PrometheusMetrics(enabled=True)
        
        assert metrics.enabled is True
    
    def test_init_enabled_from_env(self):
        """Test enabling via environment variable."""
        os.environ["ENABLE_PROMETHEUS"] = "true"
        try:
            metrics = PrometheusMetrics()
            assert metrics.enabled is True
        finally:
            del os.environ["ENABLE_PROMETHEUS"]
    
    def test_init_enabled_from_env_1(self):
        """Test enabling via env var with '1'."""
        os.environ["ENABLE_PROMETHEUS"] = "1"
        try:
            metrics = PrometheusMetrics()
            assert metrics.enabled is True
        finally:
            del os.environ["ENABLE_PROMETHEUS"]
    
    def test_init_disabled_from_env(self):
        """Test disabling via env var."""
        os.environ["ENABLE_PROMETHEUS"] = "false"
        try:
            metrics = PrometheusMetrics()
            assert metrics.enabled is False
        finally:
            del os.environ["ENABLE_PROMETHEUS"]


class TestPrometheusMetricsRecording:
    """Test metric recording."""
    
    def test_record_score(self):
        """Test recording optimization scores."""
        metrics = PrometheusMetrics(enabled=True)
        
        metrics.record_score(0.75)
        metrics.record_score(0.85)
        metrics.record_score(0.90)
        
        assert len(metrics.scores) == 3
        assert metrics.scores[0].value == 0.75
        assert metrics.scores[1].value == 0.85
        assert metrics.scores[2].value == 0.90
    
    def test_record_score_with_labels(self):
        """Test recording scores with labels."""
        metrics = PrometheusMetrics(enabled=True)
        
        metrics.record_score(0.95, labels={"domain": "legal", "strategy": "genetic"})
        
        assert metrics.scores[0].labels["domain"] == "legal"
        assert metrics.scores[0].labels["strategy"] == "genetic"
    
    def test_record_score_clamping(self):
        """Test that scores outside [0, 1] are clamped."""
        metrics = PrometheusMetrics(enabled=True)
        
        metrics.record_score(1.5)  # Should be clamped to 1.0
        metrics.record_score(-0.5)  # Should be clamped to 0.0
        
        assert metrics.scores[0].value == 1.0
        assert metrics.scores[1].value == 0.0
    
    def test_record_round_completion(self):
        """Test recording round completions."""
        metrics = PrometheusMetrics(enabled=True)
        
        assert metrics.current_round == 0
        
        metrics.record_round_completion()
        assert metrics.current_round == 1
        
        metrics.record_round_completion(domain="medical")
        assert metrics.current_round == 2
        
        assert len(metrics.rounds) == 2
    
    def test_record_session_duration(self):
        """Test recording session duration."""
        metrics = PrometheusMetrics(enabled=True)
        
        metrics.record_session_duration(15.5)
        metrics.record_session_duration(20.3)
        
        assert len(metrics.durations) == 2
        assert metrics.durations[0].value == 15.5
        assert metrics.durations[1].value == 20.3
    
    def test_record_error(self):
        """Test recording errors."""
        metrics = PrometheusMetrics(enabled=True)
        
        assert metrics.total_errors == 0
        
        metrics.record_error("validation", "round_1")
        assert metrics.total_errors == 1
        
        metrics.record_error("llm", "fallback")
        assert metrics.total_errors == 2
        
        assert len(metrics.errors) == 2
    
    def test_record_cache_hit(self):
        """Test recording cache hits."""
        metrics = PrometheusMetrics(enabled=True)
        
        assert metrics.total_cache_hits == 0
        
        metrics.record_cache_hit("ontology")
        metrics.record_cache_hit("validation")
        metrics.record_cache_hit()  # Default type
        
        assert metrics.total_cache_hits == 3
        assert len(metrics.cache_hits) == 3
    
    def test_record_memory_usage(self):
        """Test recording memory usage."""
        metrics = PrometheusMetrics(enabled=True)
        
        metrics.record_memory_usage(1024 * 1024)  # 1 MB
        metrics.record_memory_usage(2048 * 1024)  # 2 MB
        
        assert len(metrics.memory_usage) == 2
        assert metrics.memory_usage[0].value == 1024 * 1024

    def test_record_stage_duration(self):
        """Test recording stage durations."""
        metrics = PrometheusMetrics(enabled=True)

        metrics.record_stage_duration("extracting", 0.12)
        metrics.record_stage_duration("refining", 0.55, labels={"domain": "legal"})

        assert len(metrics.stage_durations) == 2
        assert metrics.stage_durations[0].labels["stage"] == "extracting"
        assert metrics.stage_durations[1].labels["stage"] == "refining"
        assert metrics.stage_durations[1].labels["domain"] == "legal"
    
    def test_disabled_metrics_no_recording(self):
        """Test that disabled metrics don't record anything."""
        metrics = PrometheusMetrics(enabled=False)
        
        metrics.record_score(0.75)
        metrics.record_round_completion()
        metrics.record_error("llm")
        
        assert len(metrics.scores) == 0
        assert len(metrics.rounds) == 0
        assert len(metrics.errors) == 0


class TestPrometheusMetricsCollection:
    """Test metric collection and format."""
    
    def test_collect_metrics_enabled(self):
        """Test collecting metrics in Prometheus format."""
        metrics = PrometheusMetrics(enabled=True)
        
        metrics.record_score(0.75)
        metrics.record_score(0.85)
        metrics.record_round_completion()
        metrics.record_session_duration(10.5)
        
        output = metrics.collect_metrics()
        
        assert "optimizer_score" in output
        assert "optimizer_rounds_completed_total" in output
        assert "optimizer_session_duration_seconds" in output
        assert "optimizer_session_duration_seconds 10.5" in output  # Latest duration
        assert "# HELP" in output
        assert "# TYPE" in output
    
    def test_collect_metrics_disabled(self):
        """Test collecting metrics when disabled."""
        metrics = PrometheusMetrics(enabled=False)
        metrics.record_score(0.75)
        
        output = metrics.collect_metrics()
        
        assert "disabled" in output.lower()
        assert "optimizer_score" not in output
    
    def test_collect_metrics_score_histogram(self):
        """Test score histogram buckets in output."""
        metrics = PrometheusMetrics(enabled=True)
        
        # Add scores across the range
        for score in [0.1, 0.2, 0.5, 0.75, 0.9, 0.95]:
            metrics.record_score(score)
        
        output = metrics.collect_metrics()
        
        assert 'le="0.1"' in output
        assert 'le="0.5"' in output
        assert 'le="1.0"' in output
        assert f'optimizer_score_count 6' in output

    def test_collect_metrics_stage_histogram(self):
        """Test stage duration histogram in output."""
        metrics = PrometheusMetrics(enabled=True)

        metrics.record_stage_duration("extracting", 0.05, labels={"domain": "general"})
        metrics.record_stage_duration("extracting", 0.12, labels={"domain": "general"})
        metrics.record_stage_duration("refining", 0.8, labels={"domain": "legal"})

        output = metrics.collect_metrics()

        assert "optimizer_stage_duration_seconds_bucket" in output
        assert 'stage="extracting"' in output
        assert 'stage="refining"' in output
        assert 'domain="general"' in output
    
    def test_collect_metrics_round_counter(self):
        """Test round counter in output."""
        metrics = PrometheusMetrics(enabled=True)
        
        for _ in range(5):
            metrics.record_round_completion()
        
        output = metrics.collect_metrics()
        
        assert "optimizer_rounds_completed_total 5" in output
    
    def test_collect_metrics_error_counter(self):
        """Test error counter in output."""
        metrics = PrometheusMetrics(enabled=True)
        
        metrics.record_error("validation")
        metrics.record_error("llm")
        metrics.record_error("timeout")
        
        output = metrics.collect_metrics()
        
        assert "optimizer_errors_total 3" in output
    
    def test_collect_metrics_empty(self):
        """Test collecting metrics with no data recorded."""
        metrics = PrometheusMetrics(enabled=True)
        
        output = metrics.collect_metrics()
        
        assert "optimizer_score_count 0" in output
        assert "optimizer_rounds_completed_total 0" in output


class TestPrometheusMetricsSummary:
    """Test metric summary generation."""
    
    def test_get_summary_disabled(self):
        """Test summary when metrics disabled."""
        metrics = PrometheusMetrics(enabled=False)
        summary = metrics.get_summary()
        
        assert summary["enabled"] is False
    
    def test_get_summary_with_data(self):
        """Test summary with recorded data."""
        metrics = PrometheusMetrics(enabled=True)
        
        metrics.record_score(0.60)
        metrics.record_score(0.80)
        metrics.record_score(0.90)
        metrics.record_round_completion()
        metrics.record_round_completion()
        metrics.record_error("llm")
        metrics.record_cache_hit()
        metrics.record_cache_hit()
        metrics.record_session_duration(15.0)
        
        summary = metrics.get_summary()
        
        assert summary["scores_recorded"] == 3
        # Use approximate comparison for floating point
        assert abs(summary["avg_score"] - 0.7666666666666667) < 0.0000001
        assert summary["min_score"] == 0.6
        assert summary["max_score"] == 0.9
        assert summary["rounds_completed"] == 2
        assert summary["errors"] == 1
        assert summary["cache_hits"] == 2
        assert summary["total_sessions"] == 1
    
    def test_get_summary_empty(self):
        """Test summary with no scores recorded."""
        metrics = PrometheusMetrics(enabled=True)
        summary = metrics.get_summary()
        
        assert summary["scores_recorded"] == 0
        assert "avg_score" not in summary
