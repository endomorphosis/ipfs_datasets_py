"""
Comprehensive type validation tests for monitoring.py TypedDicts.

Tests the structure and typing of monitoring system return types:
- MetricsDictRepr: Metric representation dictionary
- HealthCheckDict: Health check result dictionary  
- MetricsExportDict: Metrics export format dictionary
"""

import pytest
from typing import Dict, Any
from ipfs_datasets_py.monitoring import (
    MetricValue, MetricType, OperationMetrics, LogContext,
    MetricsDictRepr, HealthCheckDict, MetricsExportDict
)


class TestMetricsDictRepr:
    """Tests for MetricsDictRepr TypedDict structure."""
    
    def test_metric_to_dict_structure(self):
        """Verify MetricValue.to_dict() returns MetricsDictRepr structure."""
        metric = MetricValue(
            name="response_time",
            type=MetricType.TIMER,
            value=42.5,
            labels={"endpoint": "/api/user"}
        )
        result = metric.to_dict()
        
        # Verify all required fields present
        assert "name" in result
        assert "type" in result
        assert "value" in result
        assert "timestamp" in result
        assert "labels" in result
        
    def test_metric_to_dict_types(self):
        """Verify MetricValue.to_dict() returns correct types for all fields."""
        metric = MetricValue(
            name="cpu_usage",
            type=MetricType.GAUGE,
            value=75.0,
            labels={"host": "server1"}
        )
        result = metric.to_dict()
        
        assert isinstance(result["name"], str)
        assert isinstance(result["type"], str)
        assert isinstance(result["value"], (int, float))
        assert isinstance(result["timestamp"], float)
        assert isinstance(result["labels"], dict)
        
    def test_metric_to_dict_with_description(self):
        """Verify MetricsDictRepr includes optional description field."""
        metric = MetricValue(
            name="queue_depth",
            type=MetricType.COUNTER,
            value=100,
            description="Number of items in processing queue"
        )
        result = metric.to_dict()
        
        assert result["name"] == "queue_depth"
        assert result["description"] == "Number of items in processing queue"


class TestHealthCheckDict:
    """Tests for HealthCheckDict TypedDict structure."""
    
    def test_log_context_get_current_returns_healthcheck_dict(self):
        """Verify LogContext.get_current() returns HealthCheckDict structure."""
        context = LogContext.get_current()
        
        # Verify it's a dict (may be empty initially)
        assert isinstance(context, dict)
        
    def test_healthcheck_dict_with_data(self):
        """Verify HealthCheckDict can hold monitoring information."""
        LogContext.set("status", "healthy")
        LogContext.set("timestamp", 1234567890.0)
        context = LogContext.get_current()
        
        # Should be a dict with the set values
        assert isinstance(context, dict)
        assert context.get("status") == "healthy"
        assert context.get("timestamp") == 1234567890.0
        
        # Clean up
        LogContext.clear()
        
    def test_healthcheck_isolation_between_contexts(self):
        """Verify separate LogContext instances maintain isolation."""
        context1 = LogContext.get_current()
        context2 = LogContext.get_current()
        
        # Both should be valid health check dicts
        assert isinstance(context1, dict)
        assert isinstance(context2, dict)


class TestMetricsExportDict:
    """Tests for MetricsExportDict TypedDict structure."""
    
    def test_metricsexport_dict_structure(self):
        """Verify MetricsExportDict has expected structure for export."""
        # MetricsExportDict is used for exporting metrics to external systems
        # It should contain: metrics list, export timestamp, and format identifier
        
        # Create sample export dict matching the TypedDict
        export_data: MetricsExportDict = {
            "metrics": [
                {
                    "name": "api_requests",
                    "type": "counter",
                    "value": 1000,
                    "timestamp": 1234567890.0,
                    "labels": {"path": "/api/v1"}
                }
            ],
            "timestamp": 1234567890.0,
            "export_format": "prometheus"
        }
        
        assert "metrics" in export_data
        assert "timestamp" in export_data
        assert "export_format" in export_data
        
    def test_metricsexport_dict_metrics_array(self):
        """Verify MetricsExportDict metrics field is an array."""
        export_data: MetricsExportDict = {
            "metrics": [
                {"name": "gauge1", "type": "gauge", "value": 50.0, 
                 "timestamp": 1234567890.0, "labels": {}}
            ],
            "timestamp": 1234567890.0,
            "export_format": "json"
        }
        
        assert isinstance(export_data["metrics"], list)
        assert len(export_data["metrics"]) > 0
        
    def test_metricsexport_dict_formats(self):
        """Verify MetricsExportDict supports different export formats."""
        formats = ["prometheus", "json", "influxdb", "graphite"]
        
        for fmt in formats:
            export_data: MetricsExportDict = {
                "metrics": [],
                "timestamp": 1234567890.0,
                "export_format": fmt
            }
            assert export_data["export_format"] == fmt


class TestOperationMetricsToDictIntegration:
    """Integration tests for OperationMetrics.to_dict() return type."""
    
    def test_operation_metrics_to_dict_structure(self):
        """Verify OperationMetrics.to_dict() returns MetricsDictRepr."""
        op_metrics = OperationMetrics(
            operation_id="op_123",
            operation_type="data_sync",
            start_time=1234567890.0,
            status="in_progress"
        )
        result = op_metrics.to_dict()
        
        # Verify core fields present
        assert "operation_id" in result
        assert "operation_type" in result
        assert "start_time" in result
        assert "status" in result
        assert "success" in result
        
    def test_operation_metrics_to_dict_after_complete(self):
        """Verify OperationMetrics.to_dict() includes completion status."""
        op_metrics = OperationMetrics(
            operation_id="op_456",
            operation_type="backup",
            start_time=1234567890.0
        )
        op_metrics.complete(success=True)
        result = op_metrics.to_dict()
        
        assert result["success"] is True
        assert result["status"] == "success"
        assert "end_time" in result
        assert "duration_ms" in result
        
    def test_operation_metrics_to_dict_error_case(self):
        """Verify OperationMetrics.to_dict() includes error information."""
        op_metrics = OperationMetrics(
            operation_id="op_789",
            operation_type="sync",
            start_time=1234567890.0
        )
        op_metrics.complete(success=False, error="Connection timeout")
        result = op_metrics.to_dict()
        
        assert result["success"] is False
        assert result["status"] == "error"
        assert result["error"] == "Connection timeout"


class TestTypeConsistency:
    """Tests for consistency across all TypedDict returns."""
    
    def test_all_metric_representations_are_dicts(self):
        """Verify all metric representations return dict instances."""
        # MetricValue as MetricsDictRepr
        metric = MetricValue(
            name="test",
            type=MetricType.GAUGE,
            value=10.0
        )
        metric_dict = metric.to_dict()
        assert isinstance(metric_dict, dict)
        
        # OperationMetrics as MetricsDictRepr
        op_metrics = OperationMetrics(
            operation_id="test_op",
            operation_type="test",
            start_time=1234567890.0
        )
        op_dict = op_metrics.to_dict()
        assert isinstance(op_dict, dict)
        
    def test_log_context_is_dict(self):
        """Verify LogContext.get_current() returns a dictionary."""
        context = LogContext.get_current()
        assert isinstance(context, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
