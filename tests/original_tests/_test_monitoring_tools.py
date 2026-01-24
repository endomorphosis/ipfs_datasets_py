#!/usr/bin/env python3
"""
Test suite for monitoring tools functionality.
"""

import pytest
import anyio
import sys
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch, MagicMock

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class TestMonitoringTools:
    """Test monitoring tools functionality."""

    @pytest.mark.asyncio
    async def test_system_health_monitoring(self):
        """Test system health monitoring."""
        from ipfs_datasets_py.mcp_server.tools.monitoring_tools.monitoring_tools import monitor_system_health
        
        result = await monitor_system_health(
            components=["cpu", "memory", "disk", "network"],
            detailed=True
        )
        
        assert result is not None
        assert "status" in result
        assert "health_status" in result or "metrics" in result
    
    @pytest.mark.asyncio
    async def test_performance_metrics_collection(self):
        """Test performance metrics collection."""
        from ipfs_datasets_py.mcp_server.tools.monitoring_tools.monitoring_tools import collect_performance_metrics
        
        result = await collect_performance_metrics(
            metric_types=["response_time", "throughput", "error_rate"],
            time_range="1h",
            aggregation="avg"
        )
        
        assert result is not None
        assert "status" in result
        assert "metrics" in result or "performance_data" in result
    
    @pytest.mark.asyncio
    async def test_service_status_monitoring(self):
        """Test service status monitoring."""
        from ipfs_datasets_py.mcp_server.tools.monitoring_tools.monitoring_tools import monitor_service_status
        
        result = await monitor_service_status(
            services=["embedding_service", "vector_store", "ipfs_node"],
            include_dependencies=True
        )
        
        assert result is not None
        assert "status" in result
        assert "service_status" in result or "services" in result
    
    @pytest.mark.asyncio
    async def test_resource_usage_monitoring(self):
        """Test resource usage monitoring."""
        from ipfs_datasets_py.mcp_server.tools.monitoring_tools.monitoring_tools import monitor_resource_usage
        
        result = await monitor_resource_usage(
            resources=["cpu", "memory", "disk", "gpu"],
            threshold_alerts=True,
            historical_data=True
        )
        
        assert result is not None
        assert "status" in result
        assert "resource_usage" in result or "usage_data" in result
    
    @pytest.mark.asyncio
    async def test_error_rate_monitoring(self):
        """Test error rate monitoring."""
        from ipfs_datasets_py.mcp_server.tools.monitoring_tools.monitoring_tools import monitor_error_rates
        
        result = await monitor_error_rates(
            services=["mcp_server", "fastapi_service"],
            time_window="30m",
            error_threshold=0.05
        )
        
        assert result is not None
        assert "status" in result
        assert "error_rates" in result or "error_statistics" in result
    
    @pytest.mark.asyncio
    async def test_alert_configuration(self):
        """Test alert configuration and management."""
        from ipfs_datasets_py.mcp_server.tools.monitoring_tools.monitoring_tools import configure_alerts
        
        alert_config = {
            "cpu_threshold": 80,
            "memory_threshold": 90,
            "disk_threshold": 85,
            "error_rate_threshold": 0.1,
            "notification_channels": ["email", "slack"]
        }
        
        result = await configure_alerts(
            alert_configuration=alert_config,
            enable_auto_scaling=True
        )
        
        assert result is not None
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_log_analysis(self):
        """Test log analysis and aggregation."""
        from ipfs_datasets_py.mcp_server.tools.monitoring_tools.monitoring_tools import analyze_logs
        
        result = await analyze_logs(
            log_sources=["application", "system", "security"],
            time_range="24h",
            analysis_type="error_pattern",
            include_anomalies=True
        )
        
        assert result is not None
        assert "status" in result
        assert "log_analysis" in result or "analysis_results" in result


class TestMonitoringDashboard:
    """Test monitoring dashboard functionality."""

    @pytest.mark.asyncio
    async def test_create_monitoring_dashboard(self):
        """Test monitoring dashboard creation."""
        from ipfs_datasets_py.mcp_server.tools.monitoring_tools.monitoring_tools import create_dashboard
        
        dashboard_config = {
            "name": "System Overview",
            "widgets": [
                {"type": "cpu_usage", "position": {"x": 0, "y": 0}},
                {"type": "memory_usage", "position": {"x": 1, "y": 0}},
                {"type": "error_rates", "position": {"x": 0, "y": 1}}
            ],
            "refresh_interval": 30
        }
        
        result = await create_dashboard(
            dashboard_configuration=dashboard_config,
            dashboard_id="system-overview"
        )
        
        assert result is not None
        assert "status" in result
        assert "dashboard_id" in result or "dashboard_url" in result
    
    @pytest.mark.asyncio
    async def test_get_dashboard_data(self):
        """Test retrieving dashboard data."""
        from ipfs_datasets_py.mcp_server.tools.monitoring_tools.monitoring_tools import get_dashboard_data
        
        result = await get_dashboard_data(
            dashboard_id="system-overview",
            time_range="1h",
            include_historical=True
        )
        
        assert result is not None
        assert "status" in result
        assert "dashboard_data" in result or "widgets_data" in result


class TestMonitoringIntegration:
    """Test monitoring tools integration."""

    @pytest.mark.asyncio
    async def test_embedding_service_monitoring(self):
        """Test monitoring of embedding services."""
        from ipfs_datasets_py.mcp_server.tools.monitoring_tools.monitoring_tools import monitor_embedding_service
        
        result = await monitor_embedding_service(
            service_endpoint="http://localhost:8080",
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            health_check=True
        )
        
        assert result is not None
        assert "status" in result
        assert "service_health" in result or "embedding_service_status" in result
    
    @pytest.mark.asyncio
    async def test_vector_store_monitoring(self):
        """Test monitoring of vector stores."""
        from ipfs_datasets_py.mcp_server.tools.monitoring_tools.monitoring_tools import monitor_vector_store
        
        result = await monitor_vector_store(
            store_type="qdrant",
            store_endpoint="http://localhost:6333",
            check_indices=True
        )
        
        assert result is not None
        assert "status" in result
        assert "store_health" in result or "vector_store_status" in result
    
    @pytest.mark.asyncio
    async def test_ipfs_node_monitoring(self):
        """Test monitoring of IPFS nodes."""
        from ipfs_datasets_py.mcp_server.tools.monitoring_tools.monitoring_tools import monitor_ipfs_node
        
        result = await monitor_ipfs_node(
            node_endpoint="http://localhost:5001",
            check_connectivity=True,
            check_storage=True
        )
        
        assert result is not None
        assert "status" in result
        assert "node_health" in result or "ipfs_status" in result


class TestMonitoringAlerts:
    """Test monitoring alerting system."""

    @pytest.mark.asyncio
    async def test_threshold_based_alerts(self):
        """Test threshold-based alerting."""
        from ipfs_datasets_py.mcp_server.tools.monitoring_tools.monitoring_tools import check_thresholds
        
        thresholds = {
            "cpu_usage": 80,
            "memory_usage": 90,
            "error_rate": 0.05,
            "response_time": 1000  # ms
        }
        
        current_metrics = {
            "cpu_usage": 85,  # Above threshold
            "memory_usage": 75,  # Below threshold
            "error_rate": 0.03,  # Below threshold
            "response_time": 1200  # Above threshold
        }
        
        result = await check_thresholds(
            thresholds=thresholds,
            current_metrics=current_metrics,
            alert_on_breach=True
        )
        
        assert result is not None
        assert "status" in result
        assert "alerts" in result or "threshold_breaches" in result
    
    @pytest.mark.asyncio
    async def test_anomaly_detection_alerts(self):
        """Test anomaly detection alerting."""
        from ipfs_datasets_py.mcp_server.tools.monitoring_tools.monitoring_tools import detect_anomalies
        
        # Simulate historical data
        historical_data = [50, 52, 48, 51, 49, 53, 47]  # Normal range
        current_value = 75  # Anomalous value
        
        result = await detect_anomalies(
            metric_name="cpu_usage",
            historical_data=historical_data,
            current_value=current_value,
            sensitivity=0.95
        )
        
        assert result is not None
        assert "status" in result
        assert "anomaly_detected" in result or "is_anomaly" in result


class TestMonitoringToolsIntegration:
    """Test monitoring tools integration with other components."""

    @pytest.mark.asyncio
    async def test_monitoring_tools_mcp_registration(self):
        """Test that monitoring tools are properly registered with MCP."""
        from ipfs_datasets_py.mcp_server.tools.tool_registration import get_registered_tools
        
        tools = get_registered_tools()
        monitoring_tools = [tool for tool in tools if 'monitor' in tool.get('name', '').lower()]
        
        assert len(monitoring_tools) > 0, "Monitoring tools should be registered"
    
    @pytest.mark.asyncio
    async def test_monitoring_tools_error_handling(self):
        """Test error handling in monitoring tools."""
        from ipfs_datasets_py.mcp_server.tools.monitoring_tools.monitoring_tools import monitor_system_health
        
        # Test with invalid component
        result = await monitor_system_health(
            components=["invalid_component"],
            detailed=True
        )
        
        assert result is not None
        assert "status" in result
        # Should handle error gracefully
        assert result["status"] in ["error", "success"]
    
    @pytest.mark.asyncio
    async def test_monitoring_data_export(self):
        """Test monitoring data export functionality."""
        from ipfs_datasets_py.mcp_server.tools.monitoring_tools.monitoring_tools import export_monitoring_data
        
        result = await export_monitoring_data(
            data_types=["metrics", "logs", "alerts"],
            time_range="24h",
            export_format="json",
            output_path="/tmp/monitoring_export.json"
        )
        
        assert result is not None
        assert "status" in result
        assert "export_path" in result or "exported_data" in result


class TestRealTimeMonitoring:
    """Test real-time monitoring capabilities."""

    @pytest.mark.asyncio
    async def test_start_real_time_monitoring(self):
        """Test starting real-time monitoring."""
        from ipfs_datasets_py.mcp_server.tools.monitoring_tools.monitoring_tools import start_real_time_monitoring
        
        result = await start_real_time_monitoring(
            metrics=["cpu", "memory", "active_connections"],
            update_interval=5,  # seconds
            duration=60  # seconds
        )
        
        assert result is not None
        assert "status" in result
        assert "monitoring_session_id" in result or "session_id" in result
    
    @pytest.mark.asyncio
    async def test_stop_real_time_monitoring(self):
        """Test stopping real-time monitoring."""
        from ipfs_datasets_py.mcp_server.tools.monitoring_tools.monitoring_tools import stop_real_time_monitoring
        
        result = await stop_real_time_monitoring(
            session_id="test-session-123"
        )
        
        assert result is not None
        assert "status" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
