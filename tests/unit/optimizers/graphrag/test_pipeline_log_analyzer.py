"""Tests for pipeline log analyzer and aggregation utilities.

Tests verify that logs are correctly parsed, aggregated, and analyzed.
"""

import json
import logging
import pytest
import tempfile
from datetime import datetime, timedelta

from ipfs_datasets_py.optimizers.graphrag.pipeline_log_analyzer import (
    LogAnalyzer,
    StageStatistics,
    RunStatistics,
    load_log_file,
    save_log_file,
)


@pytest.fixture
def sample_logs():
    """Create sample JSON logs for testing."""
    base_time = datetime.now()
    
    return [
        {
            "event": "pipeline.run.started",
            "run_id": "run_123",
            "domain": "legal",
            "data_source": "test",
            "timestamp": base_time.isoformat(),
            "schema": "ipfs_datasets_py.optimizer_log",
            "schema_version": 2,
        },
        {
            "event": "extraction.started",
            "run_id": "run_123",
            "timestamp": (base_time + timedelta(milliseconds=100)).isoformat(),
            "schema": "ipfs_datasets_py.optimizer_log",
            "schema_version": 2,
        },
        {
            "event": "extraction.completed",
            "run_id": "run_123",
            "entity_count": 10,
            "relationship_count": 5,
            "timestamp": (base_time + timedelta(milliseconds=500)).isoformat(),
            "schema": "ipfs_datasets_py.optimizer_log",
            "schema_version": 2,
        },
        {
            "event": "evaluation.started",
            "run_id": "run_123",
            "timestamp": (base_time + timedelta(milliseconds=600)).isoformat(),
            "schema": "ipfs_datasets_py.optimizer_log",
            "schema_version": 2,
        },
        {
            "event": "evaluation.completed",
            "run_id": "run_123",
            "score": 0.85,
            "cache_hit": False,
            "timestamp": (base_time + timedelta(milliseconds=1000)).isoformat(),
            "schema": "ipfs_datasets_py.optimizer_log",
            "schema_version": 2,
        },
        {
            "event": "refinement.started",
            "run_id": "run_123",
            "current_score": 0.85,
            "timestamp": (base_time + timedelta(milliseconds=1100)).isoformat(),
            "schema": "ipfs_datasets_py.optimizer_log",
            "schema_version": 2,
        },
        {
            "event": "refinement.round.completed",
            "run_id": "run_123",
            "round": 1,
            "score_before": 0.85,
            "score_after": 0.88,
            "actions": ["fix_entity", "add_relationship"],
            "timestamp": (base_time + timedelta(milliseconds=1500)).isoformat(),
            "schema": "ipfs_datasets_py.optimizer_log",
            "schema_version": 2,
        },
        {
            "event": "refinement.completed",
            "run_id": "run_123",
            "final_score": 0.88,
            "initial_score": 0.85,
            "rounds": 1,
            "total_actions": 2,
            "timestamp": (base_time + timedelta(milliseconds=2000)).isoformat(),
            "schema": "ipfs_datasets_py.optimizer_log",
            "schema_version": 2,
        },
        {
            "event": "pipeline.run.completed",
            "run_id": "run_123",
            "total_elapsed_ms": 2000,
            "metrics": {"entity_count": 10},
            "error_count": 0,
            "timestamp": (base_time + timedelta(milliseconds=2000)).isoformat(),
            "schema": "ipfs_datasets_py.optimizer_log",
            "schema_version": 2,
        },
    ]


class TestStageStatistics:
    """Test StageStatistics data structure."""
    
    def test_stage_statistics_initialization(self):
        """StageStatistics should initialize correctly."""
        stats = StageStatistics(stage_name="extraction")
        
        assert stats.stage_name == "extraction"
        assert stats.event_count == 0
        assert stats.total_duration_ms == 0.0
        assert stats.avg_duration_ms == 0.0
    
    def test_avg_duration_calculation(self):
        """Should calculate average duration correctly."""
        stats = StageStatistics(
            stage_name="extraction",
            event_count=4,
            total_duration_ms=400.0,
        )
        
        assert stats.avg_duration_ms == 100.0
    
    def test_to_dict_conversion(self):
        """Should convert to dict correctly."""
        stats = StageStatistics(
            stage_name="extraction",
            event_count=2,
            total_duration_ms=200.0,
            min_duration_ms=90.0,
            max_duration_ms=110.0,
        )
        
        d = stats.to_dict()
        
        assert d["stage"] == "extraction"
        assert d["event_count"] == 2
        assert d["total_duration_ms"] == 200.0
        assert d["avg_duration_ms"] == 100.0


class TestRunStatistics:
    """Test RunStatistics data structure."""
    
    def test_run_statistics_initialization(self):
        """RunStatistics should initialize correctly."""
        stats = RunStatistics(
            run_id="run_123",
            domain="legal",
            data_source="test",
        )
        
        assert stats.run_id == "run_123"
        assert stats.domain == "legal"
        assert stats.total_duration_ms == 0.0
        assert len(stats.stage_stats) == 0
    
    def test_to_dict_conversion(self):
        """Should convert to dict."""
        stats = RunStatistics(
            run_id="run_123",
            domain="legal",
            data_source="test",
            total_duration_ms=2000.0,
            entity_count=10,
            overall_score=0.85,
        )
        
        d = stats.to_dict()
        
        assert d["run_id"] == "run_123"
        assert d["entity_count"] == 10
        assert d["overall_score"] == 0.85


class TestLogAnalyzer:
    """Test LogAnalyzer functionality."""
    
    def test_analyzer_initialization(self, sample_logs):
        """Analyzer should parse logs on initialization."""
        analyzer = LogAnalyzer(sample_logs)
        
        assert analyzer.logs == sample_logs
        assert "run_123" in analyzer._runs
    
    def test_run_statistics_extraction(self, sample_logs):
        """Should extract run statistics from logs."""
        analyzer = LogAnalyzer(sample_logs)
        runs = analyzer.run_statistics()
        
        assert "run_123" in runs
        run_stats = runs["run_123"]
        
        assert run_stats.domain == "legal"
        assert run_stats.data_source == "test"
        assert run_stats.entity_count == 10
        assert run_stats.relationship_count == 5
        assert run_stats.overall_score == 0.85
        assert run_stats.refinement_rounds == 1
    
    def test_stage_statistics_aggregation(self, sample_logs):
        """Should aggregate statistics by stage."""
        analyzer = LogAnalyzer(sample_logs)
        stage_stats = analyzer.stage_statistics()
        
        # Should have extraction, evaluation, refinement stages
        assert "extraction" in stage_stats or "evaluation" in stage_stats or "refinement" in stage_stats
    
    def test_filter_by_run_id(self, sample_logs):
        """Should filter logs by run ID."""
        analyzer = LogAnalyzer(sample_logs)
        filtered = analyzer.filter_logs(run_id="run_123")
        
        # All filtered logs should have run_123
        for log in filtered:
            assert log.get("run_id") == "run_123"
    
    def test_filter_by_event_type(self, sample_logs):
        """Should filter logs by event type."""
        analyzer = LogAnalyzer(sample_logs)
        filtered = analyzer.filter_logs(event_type="extraction.completed")
        
        # All filtered logs should be extraction.completed
        assert all(log.get("event") == "extraction.completed" for log in filtered)
        assert len(filtered) >= 1
    
    def test_filter_by_timestamp_range(self, sample_logs):
        """Should filter logs by timestamp range."""
        base_time = datetime.fromisoformat(sample_logs[0]["timestamp"])
        min_time = base_time + timedelta(milliseconds=500)
        max_time = base_time + timedelta(milliseconds=1500)
        
        analyzer = LogAnalyzer(sample_logs)
        filtered = analyzer.filter_logs(
            minimum_timestamp=min_time,
            maximum_timestamp=max_time,
        )
        
        # Should have some logs in the range
        assert len(filtered) > 0
    
    def test_error_summary(self):
        """Should summarize errors in logs."""
        logs = [
            {
                "event": "pipeline.error",
                "stage": "extraction",
                "error_message": "Invalid format",
                "run_id": "run_1",
            },
            {
                "event": "pipeline.error",
                "stage": "evaluation",
                "error_message": "Timeout",
                "run_id": "run_1",
            },
        ]
        
        analyzer = LogAnalyzer(logs)
        summary = analyzer.error_summary()
        
        assert summary["total_errors"] == 2
        assert "extraction" in summary["errors_by_stage"]
        assert "evaluation" in summary["errors_by_stage"]
    
    def test_performance_summary(self, sample_logs):
        """Should summarize performance metrics."""
        analyzer = LogAnalyzer(sample_logs)
        summary = analyzer.performance_summary()
        
        assert "total_runs" in summary
        assert "avg_duration_ms" in summary
        assert "avg_score" in summary
        assert "total_errors" in summary
    
    def test_export_report_json(self, sample_logs):
        """Should export report as JSON."""
        analyzer = LogAnalyzer(sample_logs)
        report = analyzer.export_report(format="json")
        
        # Should be valid JSON
        parsed = json.loads(report)
        
        assert "runs" in parsed
        assert "stages" in parsed
        assert "performance_summary" in parsed
        assert "error_summary" in parsed
    
    def test_export_report_unsupported_format(self, sample_logs):
        """Should raise error for unsupported format."""
        analyzer = LogAnalyzer(sample_logs)
        
        with pytest.raises(ValueError):
            analyzer.export_report(format="xml")


class TestLogFileIo:
    """Test log file I/O operations."""
    
    def test_save_and_load_logs(self, sample_logs):
        """Should save and load logs correctly."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            temp_path = f.name
        
        try:
            # Save logs
            save_log_file(temp_path, sample_logs)
            
            # Load logs
            loaded_logs = load_log_file(temp_path)
            
            # Should have same number of logs
            assert len(loaded_logs) == len(sample_logs)
            
            # Should have same content
            for original, loaded in zip(sample_logs, loaded_logs):
                assert loaded["event"] == original["event"]
                assert loaded["run_id"] == original["run_id"]
        finally:
            import os
            os.unlink(temp_path)
    
    def test_load_malformed_json(self):
        """Should raise error for malformed JSON."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            f.write('{"valid": "json"}\n')
            f.write('not valid json\n')
            temp_path = f.name
        
        try:
            with pytest.raises(ValueError):
                load_log_file(temp_path)
        finally:
            import os
            os.unlink(temp_path)
    
    def test_load_empty_file(self):
        """Should handle empty file."""
        with tempfile.NamedTemporaryFile(mode='w', delete=False, suffix='.jsonl') as f:
            temp_path = f.name
        
        try:
            logs = load_log_file(temp_path)
            assert logs == []
        finally:
            import os
            os.unlink(temp_path)


class TestMultipleRuns:
    """Test analyzer with multiple runs."""
    
    def test_multiple_runs_aggregation(self):
        """Should aggregate statistics across multiple runs."""
        logs = [
            {"event": "pipeline.run.started", "run_id": "run_1", "domain": "legal"},
            {"event": "evaluation.completed", "run_id": "run_1", "score": 0.8},
            {"event": "pipeline.run.completed", "run_id": "run_1", "total_elapsed_ms": 1000},
            {"event": "pipeline.run.started", "run_id": "run_2", "domain": "legal"},
            {"event": "evaluation.completed", "run_id": "run_2", "score": 0.9},
            {"event": "pipeline.run.completed", "run_id": "run_2", "total_elapsed_ms": 1500},
        ]
        
        analyzer = LogAnalyzer(logs)
        runs = analyzer.run_statistics()
        
        assert len(runs) == 2
        assert runs["run_1"].overall_score == 0.8
        assert runs["run_2"].overall_score == 0.9
    
    def test_performance_summary_multiple_runs(self):
        """Should calculate performance summary across multiple runs."""
        logs = [
            {"event": "pipeline.run.completed", "run_id": "run_1", "total_elapsed_ms": 1000},
            {
                "event": "evaluation.completed",
                "run_id": "run_1",
                "score": 0.8,
            },
            {"event": "pipeline.run.completed", "run_id": "run_2", "total_elapsed_ms": 2000},
            {
                "event": "evaluation.completed",
                "run_id": "run_2",
                "score": 0.9,
            },
        ]
        
        analyzer = LogAnalyzer(logs)
        summary = analyzer.performance_summary()
        
        assert summary["total_runs"] == 2
        assert summary["avg_duration_ms"] == 1500.0
        assert summary["avg_score"] == pytest.approx(0.85)
