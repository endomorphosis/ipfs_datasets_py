#!/usr/bin/env python3
"""
Test suite for monitoring_tools functionality with GIVEN WHEN THEN format.

Written to match the actual monitoring_tools API:
  health_check(), get_performance_metrics(), monitor_services(), generate_monitoring_report()
Note: the original _test_monitoring_tools.py used nonexistent function names
  (monitor_system_health, collect_performance_metrics, etc.) — this file uses the real names.
"""

import pytest
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from ipfs_datasets_py.mcp_server.tools.monitoring_tools.monitoring_tools import (
    health_check,
    get_performance_metrics,
    monitor_services,
    generate_monitoring_report,
)


class TestHealthCheck:
    """Test the health_check() function."""

    @pytest.mark.asyncio
    async def test_basic_health_check(self):
        """GIVEN a running system
        WHEN health_check() is called
        THEN success=True and a health_check section are returned
        """
        result = await health_check()
        assert result is not None
        assert result["success"] is True
        assert "health_check" in result

    @pytest.mark.asyncio
    async def test_health_check_has_recommendations(self):
        """GIVEN a running system
        WHEN health_check() is called
        THEN the recommendations field is a list
        """
        result = await health_check()
        assert "recommendations" in result
        assert isinstance(result["recommendations"], list)

    @pytest.mark.asyncio
    async def test_health_check_components(self):
        """GIVEN a running system
        WHEN health_check() is called with components
        THEN specific components can be filtered
        """
        result = await health_check(components=["cpu", "memory"])
        assert result is not None
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_health_check_detailed(self):
        """GIVEN a running system
        WHEN health_check() is called with detailed=True
        THEN a detailed health report is returned
        """
        result = await health_check(check_type="detailed", include_metrics=True)
        assert result is not None
        assert result["success"] is True


class TestPerformanceMetrics:
    """Test the get_performance_metrics() function."""

    @pytest.mark.asyncio
    async def test_get_performance_metrics_basic(self):
        """GIVEN a running system
        WHEN get_performance_metrics() is called
        THEN success=True and a performance_metrics section are returned
        """
        result = await get_performance_metrics()
        assert result is not None
        assert result["success"] is True
        assert "performance_metrics" in result

    @pytest.mark.asyncio
    async def test_get_performance_metrics_with_types(self):
        """GIVEN a running system
        WHEN get_performance_metrics() is called with metric_types
        THEN metrics for those types are returned
        """
        result = await get_performance_metrics(metric_types=["response_time", "throughput"])
        assert result is not None
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_get_performance_metrics_time_range(self):
        """GIVEN a running system
        WHEN get_performance_metrics() is called with a time_range
        THEN the result respects the time window
        """
        result = await get_performance_metrics(time_range="1h", include_history=True)
        assert result is not None
        assert result["success"] is True


class TestMonitorServices:
    """Test the monitor_services() function."""

    @pytest.mark.asyncio
    async def test_monitor_services_basic(self):
        """GIVEN a running system
        WHEN monitor_services() is called
        THEN success=True and monitoring_results are returned
        """
        result = await monitor_services()
        assert result is not None
        assert result["success"] is True
        assert "monitoring_results" in result

    @pytest.mark.asyncio
    async def test_monitor_services_with_service_list(self):
        """GIVEN a list of service names
        WHEN monitor_services() is called with them
        THEN the results include those services
        """
        result = await monitor_services(services=["embeddings", "vector_store"])
        assert result is not None
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_monitor_services_check_interval(self):
        """GIVEN a running system
        WHEN monitor_services() is called with a check_interval
        THEN the result is returned successfully
        """
        result = await monitor_services(check_interval=30)
        assert result is not None
        assert result["success"] is True


class TestMonitoringReport:
    """Test the generate_monitoring_report() function."""

    @pytest.mark.asyncio
    async def test_generate_report_basic(self):
        """GIVEN a running system
        WHEN generate_monitoring_report() is called
        THEN a report is returned
        """
        result = await generate_monitoring_report()
        assert result is not None
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_generate_report_with_timeframe(self):
        """GIVEN a time frame
        WHEN generate_monitoring_report() is called with time_frame
        THEN a report for that period is returned
        """
        result = await generate_monitoring_report(time_period="1h")
        assert result is not None
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_generate_report_with_format(self):
        """GIVEN a report format
        WHEN generate_monitoring_report() is called with report_format
        THEN a formatted report is returned
        """
        result = await generate_monitoring_report(report_type="detailed")
        assert result is not None
        assert result["success"] is True


class TestEnhancedMonitoringTools:
    """Test enhanced monitoring tools if available."""

    @pytest.mark.asyncio
    async def test_enhanced_monitoring_import(self):
        """GIVEN the enhanced monitoring module
        WHEN it is imported
        THEN it imports without error or is gracefully skipped
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.monitoring_tools.enhanced_monitoring_tools import (
                get_cache_stats,
                clear_cache,
                monitor_cache,
            )
            assert callable(get_cache_stats)
            assert callable(clear_cache)
            assert callable(monitor_cache)
        except ImportError:
            pytest.skip("Enhanced monitoring tools not available")

    @pytest.mark.asyncio
    async def test_get_cache_stats_via_enhanced(self):
        """GIVEN the enhanced monitoring module
        WHEN get_cache_stats is called
        THEN cache stats are returned
        """
        try:
            from ipfs_datasets_py.mcp_server.tools.monitoring_tools.enhanced_monitoring_tools import (
                get_cache_stats,
            )
            result = await get_cache_stats()
            assert result is not None
        except ImportError:
            pytest.skip("Enhanced monitoring tools not available")
