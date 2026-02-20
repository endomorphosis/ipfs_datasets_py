"""
Comprehensive tests for monitoring module.

Tests cover metrics collection, health checks, performance snapshots,
and tool performance tracking.
"""
import pytest
from unittest.mock import Mock, MagicMock, patch, AsyncMock
from datetime import datetime, timedelta
from collections import deque


# Test fixtures
@pytest.fixture
def metrics_collector():
    """Create metrics collector instance for testing."""
    from ipfs_datasets_py.mcp_server.monitoring import EnhancedMetricsCollector
    return EnhancedMetricsCollector(enabled=True, retention_hours=24)


@pytest.fixture
def mock_psutil():
    """Mock psutil for system metrics."""
    with patch('ipfs_datasets_py.mcp_server.monitoring.psutil') as mock:
        # Mock CPU and memory usage
        mock.cpu_percent.return_value = 45.5
        mock.virtual_memory.return_value.percent = 60.0
        mock.virtual_memory.return_value.used = 8 * 1024 * 1024 * 1024  # 8GB
        mock.disk_usage.return_value.percent = 70.0
        yield mock


# Test Class 1: Metrics Collection
class TestMetricsCollection:
    """Test suite for metrics collection functionality."""
    
    def test_increment_counter(self, metrics_collector):
        """
        GIVEN: A metrics collector
        WHEN: Incrementing a counter
        THEN: Counter value increases
        """
        # Arrange
        counter_name = "test_counter"
        
        # Act
        metrics_collector.increment_counter(counter_name, 1)
        metrics_collector.increment_counter(counter_name, 2)
        
        # Assert
        assert metrics_collector.counters[counter_name] >= 3
    
    def test_set_gauge(self, metrics_collector):
        """
        GIVEN: A metrics collector
        WHEN: Setting a gauge value
        THEN: Gauge value is updated
        """
        # Arrange
        gauge_name = "test_gauge"
        value = 42.5
        
        # Act
        metrics_collector.set_gauge(gauge_name, value)
        
        # Assert
        assert metrics_collector.gauges[gauge_name] == value
    
    def test_observe_histogram_value(self, metrics_collector):
        """
        GIVEN: A metrics collector
        WHEN: Recording histogram values
        THEN: Values are stored in histogram
        """
        # Arrange
        histogram_name = "test_histogram"
        
        # Act
        metrics_collector.observe_histogram(histogram_name, 10.0)
        metrics_collector.observe_histogram(histogram_name, 20.0)
        metrics_collector.observe_histogram(histogram_name, 30.0)
        
        # Assert
        histogram = metrics_collector.histograms[histogram_name]
        assert len(histogram) >= 3
        assert 10.0 in histogram
        assert 20.0 in histogram
        assert 30.0 in histogram


# Test Class 2: Health Check Functionality
class TestHealthCheckFunctionality:
    """Test suite for health check functionality."""
    
    def test_register_health_check(self, metrics_collector):
        """
        GIVEN: A health check function
        WHEN: Registering health check
        THEN: Health check is added to registry
        """
        # Arrange
        def health_check():
            return {"status": "healthy"}
        
        # Act
        metrics_collector.register_health_check("test_component", health_check)
        
        # Assert
        assert "test_component" in metrics_collector.health_check_registry


# Test Class 3: Performance Snapshots (Simplified)
class TestPerformanceSnapshots:
    """Test suite for performance snapshot functionality."""
    
    def test_metrics_collector_has_performance_snapshots(self, metrics_collector):
        """
        GIVEN: A metrics collector
        WHEN: Checking for performance snapshots storage
        THEN: Deque exists for storing snapshots
        """
        # Assert
        assert hasattr(metrics_collector, 'performance_snapshots')
        assert isinstance(metrics_collector.performance_snapshots, deque)


# Test Class 4: Tool Metrics Tracking
class TestToolMetricsTracking:
    """Test suite for tool performance tracking."""
    
    def test_track_tool_execution_success(self, metrics_collector):
        """
        GIVEN: A successful tool execution
        WHEN: Tracking tool execution
        THEN: Tool metrics are updated
        """
        # Arrange
        tool_name = "test_tool"
        execution_time = 150.0  # milliseconds
        
        # Act
        metrics_collector.track_tool_execution(tool_name, execution_time, success=True)
        
        # Assert
        assert metrics_collector.tool_metrics['call_counts'][tool_name] >= 1
    
    def test_track_tool_execution_failure(self, metrics_collector):
        """
        GIVEN: A failed tool execution
        WHEN: Tracking tool execution
        THEN: Error count increases
        """
        # Arrange
        tool_name = "test_tool"
        execution_time = 50.0
        
        # Act
        metrics_collector.track_tool_execution(tool_name, execution_time, success=False)
        
        # Assert
        assert metrics_collector.tool_metrics['error_counts'][tool_name] >= 1


# Test Class 5: Metrics Summary
class TestMetricsSummary:
    """Test suite for metrics summary functionality."""
    
    def test_get_metrics_summary(self, metrics_collector):
        """
        GIVEN: A metrics collector with some metrics
        WHEN: Getting metrics summary
        THEN: Returns summary dictionary
        """
        # Arrange
        metrics_collector.increment_counter("test", 5)
        metrics_collector.set_gauge("gauge1", 42.0)
        
        # Act
        summary = metrics_collector.get_metrics_summary()
        
        # Assert
        assert isinstance(summary, dict)
        assert 'counters' in summary or 'gauges' in summary or 'uptime_seconds' in summary


# Test Class 6: Session Metrics (Simplified)
class TestSessionMetrics:
    """Test suite for session metrics tracking."""
    
    def test_session_metrics_structure(self, metrics_collector):
        """
        GIVEN: A metrics collector
        WHEN: Checking session metrics structure
        THEN: Session metrics dict exists
        """
        # Assert
        assert hasattr(metrics_collector, 'session_metrics')
        assert isinstance(metrics_collector.session_metrics, dict)


# Test Class 7: Metrics Collector Configuration
class TestMetricsCollectorConfiguration:
    """Test suite for metrics collector configuration."""
    
    def test_collector_can_be_disabled(self):
        """
        GIVEN: Metrics collector with enabled=False
        WHEN: Creating collector
        THEN: Collector is disabled
        """
        # Arrange & Act
        from ipfs_datasets_py.mcp_server.monitoring import EnhancedMetricsCollector
        collector = EnhancedMetricsCollector(enabled=False)
        
        # Assert
        assert collector.enabled is False
    
    def test_retention_hours_configuration(self):
        """
        GIVEN: Custom retention hours
        WHEN: Creating collector
        THEN: Retention is configured
        """
        # Arrange & Act
        from ipfs_datasets_py.mcp_server.monitoring import EnhancedMetricsCollector
        retention_hours = 48
        collector = EnhancedMetricsCollector(retention_hours=retention_hours)
        
        # Assert
        assert collector.retention_hours == retention_hours


# Test Class 8: Data Classes
class TestDataClasses:
    """Test suite for monitoring data classes."""
    
    def test_metric_data_creation(self):
        """
        GIVEN: Metric data parameters
        WHEN: Creating MetricData
        THEN: Data class is created correctly
        """
        # Arrange & Act
        from ipfs_datasets_py.mcp_server.monitoring import MetricData
        metric = MetricData(
            value=42.5,
            labels={"type": "cpu"},
            metadata={"source": "test"}
        )
        
        # Assert
        assert metric.value == 42.5
        assert metric.labels["type"] == "cpu"
        assert metric.metadata["source"] == "test"
        assert isinstance(metric.timestamp, datetime)
    
    def test_health_check_result_creation(self):
        """
        GIVEN: Health check parameters
        WHEN: Creating HealthCheckResult
        THEN: Data class is created correctly
        """
        # Arrange & Act
        from ipfs_datasets_py.mcp_server.monitoring import HealthCheckResult
        result = HealthCheckResult(
            component="database",
            status="healthy",
            message="Connection OK",
            details={"latency": 10}
        )
        
        # Assert
        assert result.component == "database"
        assert result.status == "healthy"
        assert result.message == "Connection OK"
        assert result.details["latency"] == 10
        assert isinstance(result.timestamp, datetime)
    
    def test_performance_snapshot_creation(self):
        """
        GIVEN: Performance metrics
        WHEN: Creating PerformanceSnapshot
        THEN: Data class is created correctly
        """
        # Arrange & Act
        from ipfs_datasets_py.mcp_server.monitoring import PerformanceSnapshot
        snapshot = PerformanceSnapshot(
            timestamp=datetime.utcnow(),
            cpu_percent=45.5,
            memory_percent=60.0,
            memory_used_mb=8192.0,
            disk_percent=70.0,
            active_connections=10,
            request_rate=100.0,
            error_rate=0.5,
            avg_response_time_ms=150.0
        )
        
        # Assert
        assert snapshot.cpu_percent == 45.5
        assert snapshot.memory_percent == 60.0
        assert snapshot.active_connections == 10
        assert isinstance(snapshot.timestamp, datetime)


class TestP2PAlertHelpers:
    """Tests for P2PMetricsCollector alert helper methods (extracted from get_alert_conditions)."""

    @pytest.fixture
    def collector(self):
        from ipfs_datasets_py.mcp_server.monitoring import P2PMetricsCollector
        return P2PMetricsCollector()

    # ── _check_peer_discovery_alerts ────────────────────────────────────────

    def test_peer_discovery_no_alert_below_threshold(self, collector):
        """GIVEN <10 total discoveries WHEN checking peer alerts THEN empty list."""
        collector.peer_discovery_metrics['total_discoveries'] = 5
        collector.peer_discovery_metrics['failed_discoveries'] = 4
        assert collector._check_peer_discovery_alerts() == []

    def test_peer_discovery_no_alert_good_rate(self, collector):
        """GIVEN 10% failure rate (below 30%) THEN no alert."""
        collector.peer_discovery_metrics['total_discoveries'] = 20
        collector.peer_discovery_metrics['failed_discoveries'] = 2
        assert collector._check_peer_discovery_alerts() == []

    def test_peer_discovery_warning_at_high_rate(self, collector):
        """GIVEN >30% failure rate THEN warning alert returned."""
        collector.peer_discovery_metrics['total_discoveries'] = 20
        collector.peer_discovery_metrics['failed_discoveries'] = 8  # 40%
        alerts = collector._check_peer_discovery_alerts()
        assert len(alerts) == 1
        assert alerts[0]['type'] == 'warning'
        assert alerts[0]['component'] == 'peer_discovery'
        assert '40.0%' in alerts[0]['message']
        assert 'timestamp' in alerts[0]

    # ── _check_workflow_alerts ───────────────────────────────────────────────

    def test_workflow_no_alert_insufficient_samples(self, collector):
        """GIVEN ≤5 total workflows THEN no alert (avoid false positives)."""
        collector.workflow_metrics['completed_workflows'] = 3
        collector.workflow_metrics['failed_workflows'] = 2
        assert collector._check_workflow_alerts() == []

    def test_workflow_no_alert_good_rate(self, collector):
        """GIVEN 10% failure rate (below 20%) THEN no alert."""
        collector.workflow_metrics['completed_workflows'] = 9
        collector.workflow_metrics['failed_workflows'] = 1
        assert collector._check_workflow_alerts() == []

    def test_workflow_warning_at_high_rate(self, collector):
        """GIVEN >20% failure rate THEN warning alert returned."""
        collector.workflow_metrics['completed_workflows'] = 7
        collector.workflow_metrics['failed_workflows'] = 3  # 30%
        alerts = collector._check_workflow_alerts()
        assert len(alerts) == 1
        assert alerts[0]['type'] == 'warning'
        assert alerts[0]['component'] == 'workflows'
        assert '30.0%' in alerts[0]['message']

    # ── _check_bootstrap_alerts ──────────────────────────────────────────────

    def test_bootstrap_no_alert_insufficient_samples(self, collector):
        """GIVEN ≤3 bootstrap attempts THEN no alert."""
        collector.bootstrap_metrics['total_bootstrap_attempts'] = 2
        collector.bootstrap_metrics['failed_bootstraps'] = 2
        assert collector._check_bootstrap_alerts() == []

    def test_bootstrap_no_alert_good_rate(self, collector):
        """GIVEN 25% failure rate (below 50%) THEN no alert."""
        collector.bootstrap_metrics['total_bootstrap_attempts'] = 8
        collector.bootstrap_metrics['failed_bootstraps'] = 2
        assert collector._check_bootstrap_alerts() == []

    def test_bootstrap_critical_at_high_rate(self, collector):
        """GIVEN >50% failure rate THEN critical alert returned."""
        collector.bootstrap_metrics['total_bootstrap_attempts'] = 10
        collector.bootstrap_metrics['failed_bootstraps'] = 6  # 60%
        alerts = collector._check_bootstrap_alerts()
        assert len(alerts) == 1
        assert alerts[0]['type'] == 'critical'
        assert alerts[0]['component'] == 'bootstrap'
        assert '60.0%' in alerts[0]['message']

    # ── get_alert_conditions integration ────────────────────────────────────

    def test_get_alert_conditions_delegates_to_helpers(self, collector):
        """GIVEN all thresholds exceeded WHEN get_alert_conditions THEN 3 alerts."""
        collector.peer_discovery_metrics['total_discoveries'] = 20
        collector.peer_discovery_metrics['failed_discoveries'] = 8
        collector.workflow_metrics['completed_workflows'] = 7
        collector.workflow_metrics['failed_workflows'] = 3
        collector.bootstrap_metrics['total_bootstrap_attempts'] = 10
        collector.bootstrap_metrics['failed_bootstraps'] = 6
        alerts = collector.get_alert_conditions()
        assert len(alerts) == 3
        types = {a['component'] for a in alerts}
        assert types == {'peer_discovery', 'workflows', 'bootstrap'}

    def test_get_alert_conditions_empty_when_healthy(self, collector):
        """GIVEN healthy metrics WHEN get_alert_conditions THEN empty list."""
        assert collector.get_alert_conditions() == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
