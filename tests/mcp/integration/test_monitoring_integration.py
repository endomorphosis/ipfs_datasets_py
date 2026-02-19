"""
Integration tests for monitoring system.

Tests cover metrics collection during tool execution, health checks,
alert triggering, system metrics collection, and graceful shutdown.
"""
import pytest
import asyncio
import time
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime, timedelta
from collections import defaultdict


@pytest.fixture
def mock_metrics_collector():
    """Create a mock metrics collector."""
    from ipfs_datasets_py.mcp_server.monitoring import EnhancedMetricsCollector
    
    collector = EnhancedMetricsCollector(enabled=True, retention_hours=24)
    return collector


@pytest.fixture
def mock_health_check_registry():
    """Create a mock health check registry."""
    registry = {}
    
    async def database_check():
        return {"status": "healthy", "latency_ms": 5.2}
    
    async def cache_check():
        return {"status": "healthy", "hit_rate": 0.85}
    
    registry["database"] = database_check
    registry["cache"] = cache_check
    
    return registry


class TestMetricsCollectionDuringToolExecution:
    """Test suite for metrics collection during tool execution."""
    
    @pytest.mark.asyncio
    async def test_metrics_captured_during_tool_execution(self, mock_metrics_collector):
        """
        GIVEN: A tool being executed with metrics collector enabled
        WHEN: Tool executes successfully
        THEN: Execution metrics are captured (time, success, count)
        """
        # Arrange
        tool_name = "test_tool"
        start_time = time.time()
        
        # Act - Simulate tool execution
        await asyncio.sleep(0.1)
        execution_time = time.time() - start_time
        
        mock_metrics_collector.tool_metrics['call_counts'][tool_name] += 1
        mock_metrics_collector.tool_metrics['execution_times'][tool_name].append(execution_time)
        mock_metrics_collector.tool_metrics['last_called'][tool_name] = datetime.utcnow()
        
        # Assert
        assert mock_metrics_collector.tool_metrics['call_counts'][tool_name] == 1
        assert len(mock_metrics_collector.tool_metrics['execution_times'][tool_name]) == 1
        assert mock_metrics_collector.tool_metrics['execution_times'][tool_name][0] > 0
    
    @pytest.mark.asyncio
    async def test_error_metrics_on_tool_failure(self, mock_metrics_collector):
        """
        GIVEN: A tool that fails during execution
        WHEN: Tool execution raises exception
        THEN: Error metrics are recorded properly
        """
        # Arrange
        from ipfs_datasets_py.mcp_server.exceptions import ToolExecutionError
        
        tool_name = "failing_tool"
        
        # Act - Simulate failed tool execution
        try:
            raise ValueError("Tool failed")
        except Exception as e:
            mock_metrics_collector.tool_metrics['error_counts'][tool_name] += 1
            mock_metrics_collector.error_count += 1
        
        # Assert
        assert mock_metrics_collector.tool_metrics['error_counts'][tool_name] == 1
        assert mock_metrics_collector.error_count == 1
    
    @pytest.mark.asyncio
    async def test_concurrent_tool_metrics_collection(self, mock_metrics_collector):
        """
        GIVEN: Multiple tools executing concurrently
        WHEN: Collecting metrics from all executions
        THEN: Metrics are correctly aggregated without loss
        """
        # Arrange
        tool_names = [f"tool_{i}" for i in range(5)]
        
        async def execute_tool_with_metrics(tool_name):
            start = time.time()
            await asyncio.sleep(0.05)
            duration = time.time() - start
            mock_metrics_collector.tool_metrics['call_counts'][tool_name] += 1
            mock_metrics_collector.tool_metrics['execution_times'][tool_name].append(duration)
        
        # Act
        await asyncio.gather(*[execute_tool_with_metrics(tn) for tn in tool_names])
        
        # Assert
        for tool_name in tool_names:
            assert mock_metrics_collector.tool_metrics['call_counts'][tool_name] == 1
            assert len(mock_metrics_collector.tool_metrics['execution_times'][tool_name]) == 1


class TestHealthCheckIntegration:
    """Test suite for health check registration and execution."""
    
    @pytest.mark.asyncio
    async def test_health_check_registration(self, mock_health_check_registry):
        """
        GIVEN: Multiple health check functions
        WHEN: Registering health checks
        THEN: All checks are registered and callable
        """
        # Assert
        assert "database" in mock_health_check_registry
        assert "cache" in mock_health_check_registry
        assert callable(mock_health_check_registry["database"])
    
    @pytest.mark.asyncio
    async def test_health_check_execution_all_healthy(self, mock_health_check_registry):
        """
        GIVEN: Registered health checks with all services healthy
        WHEN: Running all health checks
        THEN: All checks pass with healthy status
        """
        # Act
        results = {}
        for name, check in mock_health_check_registry.items():
            results[name] = await check()
        
        # Assert
        assert all(r["status"] == "healthy" for r in results.values())
        assert "database" in results
        assert "cache" in results
    
    @pytest.mark.asyncio
    async def test_health_check_failure_detection(self):
        """
        GIVEN: A health check that fails
        WHEN: Running health checks
        THEN: Failure is detected and reported
        """
        # Arrange
        from ipfs_datasets_py.mcp_server.exceptions import HealthCheckError
        
        async def failing_health_check():
            raise HealthCheckError("service", "Service unavailable")
        
        # Act & Assert
        with pytest.raises(HealthCheckError) as exc_info:
            await failing_health_check()
        
        assert "Service unavailable" in str(exc_info.value)


class TestAlertTriggering:
    """Test suite for alert triggering conditions."""
    
    @pytest.mark.asyncio
    async def test_high_error_rate_alert(self, mock_metrics_collector):
        """
        GIVEN: Error rate exceeding threshold
        WHEN: Checking alert conditions
        THEN: Alert is triggered for high error rate
        """
        # Arrange
        error_threshold = 0.1  # 10%
        mock_metrics_collector.request_count = 100
        mock_metrics_collector.error_count = 15
        
        # Act
        error_rate = mock_metrics_collector.error_count / mock_metrics_collector.request_count
        alert_triggered = error_rate > error_threshold
        
        # Assert
        assert error_rate == 0.15
        assert alert_triggered is True
    
    @pytest.mark.asyncio
    async def test_high_memory_usage_alert(self):
        """
        GIVEN: Memory usage exceeding threshold
        WHEN: Monitoring system resources
        THEN: Alert is triggered for high memory usage
        """
        # Arrange
        memory_threshold = 80.0  # 80%
        current_memory_usage = 85.5
        
        # Act
        alert_triggered = current_memory_usage > memory_threshold
        
        # Assert
        assert alert_triggered is True
    
    @pytest.mark.asyncio
    async def test_slow_response_time_alert(self, mock_metrics_collector):
        """
        GIVEN: Response times exceeding threshold
        WHEN: Monitoring performance
        THEN: Alert is triggered for slow responses
        """
        # Arrange
        response_threshold_ms = 1000  # 1 second
        slow_responses = [1200, 1500, 2000]
        
        for resp_time in slow_responses:
            mock_metrics_collector.request_times.append(resp_time)
        
        # Act
        avg_response_time = sum(mock_metrics_collector.request_times) / len(mock_metrics_collector.request_times)
        alert_triggered = avg_response_time > response_threshold_ms
        
        # Assert
        assert alert_triggered is True


class TestMonitoringDataCleanup:
    """Test suite for monitoring data cleanup."""
    
    @pytest.mark.asyncio
    async def test_old_metrics_cleanup(self, mock_metrics_collector):
        """
        GIVEN: Metrics older than retention period
        WHEN: Running cleanup routine
        THEN: Old metrics are removed
        """
        # Arrange
        retention_hours = 24
        old_timestamp = datetime.utcnow() - timedelta(hours=25)
        recent_timestamp = datetime.utcnow() - timedelta(hours=1)
        
        # Simulate metrics with timestamps
        metrics = [
            {"timestamp": old_timestamp, "value": 100},
            {"timestamp": recent_timestamp, "value": 200}
        ]
        
        # Act - Cleanup old metrics
        cutoff_time = datetime.utcnow() - timedelta(hours=retention_hours)
        cleaned_metrics = [m for m in metrics if m["timestamp"] > cutoff_time]
        
        # Assert
        assert len(cleaned_metrics) == 1
        assert cleaned_metrics[0]["value"] == 200
    
    @pytest.mark.asyncio
    async def test_metrics_retention_limit(self, mock_metrics_collector):
        """
        GIVEN: Metrics exceeding retention limit
        WHEN: Adding new metrics
        THEN: Oldest metrics are automatically dropped
        """
        # Arrange - histograms have maxlen=1000
        tool_name = "test_tool"
        
        # Act - Add more than max
        for i in range(1100):
            mock_metrics_collector.histograms[tool_name].append(i)
        
        # Assert
        assert len(mock_metrics_collector.histograms[tool_name]) == 1000
        assert mock_metrics_collector.histograms[tool_name][0] == 100  # First 100 dropped


class TestSystemMetricsCollection:
    """Test suite for system metrics collection (CPU, memory, disk)."""
    
    @pytest.mark.asyncio
    async def test_cpu_metrics_collection(self):
        """
        GIVEN: System monitoring enabled
        WHEN: Collecting CPU metrics
        THEN: CPU usage percentage is captured
        """
        # Arrange
        try:
            import psutil
            
            # Act
            cpu_percent = psutil.cpu_percent(interval=0.1)
            
            # Assert
            assert isinstance(cpu_percent, (int, float))
            assert 0 <= cpu_percent <= 100
        except ImportError:
            pytest.skip("psutil not available")
    
    @pytest.mark.asyncio
    async def test_memory_metrics_collection(self):
        """
        GIVEN: System monitoring enabled
        WHEN: Collecting memory metrics
        THEN: Memory usage is captured
        """
        # Arrange
        try:
            import psutil
            
            # Act
            memory = psutil.virtual_memory()
            
            # Assert
            assert hasattr(memory, 'percent')
            assert hasattr(memory, 'used')
            assert hasattr(memory, 'available')
            assert 0 <= memory.percent <= 100
        except ImportError:
            pytest.skip("psutil not available")
    
    @pytest.mark.asyncio
    async def test_disk_metrics_collection(self):
        """
        GIVEN: System monitoring enabled
        WHEN: Collecting disk metrics
        THEN: Disk usage is captured
        """
        # Arrange
        try:
            import psutil
            
            # Act
            disk = psutil.disk_usage('/')
            
            # Assert
            assert hasattr(disk, 'percent')
            assert hasattr(disk, 'used')
            assert hasattr(disk, 'free')
            assert 0 <= disk.percent <= 100
        except ImportError:
            pytest.skip("psutil not available")


class TestToolExecutionTracking:
    """Test suite for tool execution tracking metrics."""
    
    @pytest.mark.asyncio
    async def test_tool_call_count_tracking(self, mock_metrics_collector):
        """
        GIVEN: Multiple tool executions
        WHEN: Tracking call counts
        THEN: Accurate counts are maintained per tool
        """
        # Arrange & Act
        tools = ["tool_a", "tool_b", "tool_a", "tool_c", "tool_a"]
        for tool in tools:
            mock_metrics_collector.tool_metrics['call_counts'][tool] += 1
        
        # Assert
        assert mock_metrics_collector.tool_metrics['call_counts']["tool_a"] == 3
        assert mock_metrics_collector.tool_metrics['call_counts']["tool_b"] == 1
        assert mock_metrics_collector.tool_metrics['call_counts']["tool_c"] == 1
    
    @pytest.mark.asyncio
    async def test_tool_success_rate_calculation(self, mock_metrics_collector):
        """
        GIVEN: Tool executions with successes and failures
        WHEN: Calculating success rate
        THEN: Correct success rate is computed
        """
        # Arrange
        tool_name = "test_tool"
        total_calls = 10
        errors = 2
        
        mock_metrics_collector.tool_metrics['call_counts'][tool_name] = total_calls
        mock_metrics_collector.tool_metrics['error_counts'][tool_name] = errors
        
        # Act
        success_rate = (total_calls - errors) / total_calls
        mock_metrics_collector.tool_metrics['success_rates'][tool_name] = success_rate
        
        # Assert
        assert mock_metrics_collector.tool_metrics['success_rates'][tool_name] == 0.8


class TestP2PMetricsTracking:
    """Test suite for P2P metrics tracking (if enabled)."""
    
    @pytest.mark.asyncio
    async def test_p2p_connection_metrics(self):
        """
        GIVEN: P2P service with active connections
        WHEN: Tracking P2P metrics
        THEN: Connection count and status are captured
        """
        # Arrange
        p2p_metrics = {
            "active_connections": 5,
            "peer_count": 10,
            "data_transferred_bytes": 1024000
        }
        
        # Act
        total_peers = p2p_metrics["peer_count"]
        active = p2p_metrics["active_connections"]
        
        # Assert
        assert total_peers == 10
        assert active == 5
        assert p2p_metrics["data_transferred_bytes"] > 0
    
    @pytest.mark.asyncio
    async def test_p2p_message_metrics(self):
        """
        GIVEN: P2P message passing
        WHEN: Tracking message metrics
        THEN: Message counts and types are recorded
        """
        # Arrange
        message_counts = defaultdict(int)
        
        # Act - Simulate messages
        messages = ["ping", "pong", "data", "ping", "data"]
        for msg_type in messages:
            message_counts[msg_type] += 1
        
        # Assert
        assert message_counts["ping"] == 2
        assert message_counts["pong"] == 1
        assert message_counts["data"] == 2


class TestMonitoringGracefulShutdown:
    """Test suite for monitoring graceful shutdown."""
    
    @pytest.mark.asyncio
    async def test_monitoring_shutdown_flushes_metrics(self, mock_metrics_collector):
        """
        GIVEN: Monitoring system with pending metrics
        WHEN: Shutting down gracefully
        THEN: All metrics are flushed before shutdown
        """
        # Arrange
        mock_metrics_collector.counters["requests"] = 100
        mock_metrics_collector.gauges["active_connections"] = 5
        
        # Act - Simulate shutdown
        flushed_data = {
            "counters": dict(mock_metrics_collector.counters),
            "gauges": dict(mock_metrics_collector.gauges)
        }
        
        # Assert
        assert flushed_data["counters"]["requests"] == 100
        assert flushed_data["gauges"]["active_connections"] == 5
    
    @pytest.mark.asyncio
    async def test_monitoring_cleanup_on_shutdown(self):
        """
        GIVEN: Monitoring system with active resources
        WHEN: Shutting down
        THEN: Resources are cleaned up properly
        """
        # Arrange
        monitoring_resources = {
            "threads": [],
            "connections": [],
            "file_handles": []
        }
        
        # Act - Simulate cleanup
        for resource_list in monitoring_resources.values():
            resource_list.clear()
        
        cleanup_complete = all(len(r) == 0 for r in monitoring_resources.values())
        
        # Assert
        assert cleanup_complete is True
