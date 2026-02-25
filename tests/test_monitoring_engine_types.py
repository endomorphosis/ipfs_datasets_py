"""
Tests for monitoring_engine TypedDict contracts.

Validates that all monitoring functions return properly-structured data
matching their TypedDict contracts.
"""

import pytest
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, List

from ipfs_datasets_py.monitoring_engine import (
    HealthStatus,
    AlertSeverity,
    SystemMetrics,
    ServiceMetrics,
    Alert,
    MockMonitoringService,
    SystemHealthDict,
    MemoryHealthDict,
    CPUHealthDict,
    DiskHealthDict,
    NetworkHealthDict,
    ServicesHealthDict,
    EmbeddingsHealthDict,
    VectorStoresHealthDict,
    ServiceStatusDict,
    PerformanceMetricsDict,
    HealthCheckResultDict,
    _check_system_health,
    _check_memory_health,
    _check_cpu_health,
    _check_disk_health,
    _check_network_health,
    _check_services_health,
    _check_embeddings_health,
    _check_vector_stores_health,
    _check_service_status,
    _get_performance_metrics,
)


class TestSystemHealthDict:
    """Test SystemHealthDict contract."""
    
    @pytest.mark.asyncio
    async def test_system_health_structure(self):
        """Verify _check_system_health returns valid SystemHealthDict."""
        result = await _check_system_health()
        assert isinstance(result, dict)
        assert "status" in result
        assert isinstance(result["status"], str)
        assert result["status"] in ["healthy", "warning", "error"]
    
    @pytest.mark.asyncio
    async def test_system_health_has_optional_uptime(self):
        """Verify uptime_hours is included when psutil available."""
        result = await _check_system_health()
        assert "status" in result
        if "uptime_hours" in result:
            assert isinstance(result["uptime_hours"], (int, float))
            assert result["uptime_hours"] >= 0
    
    @pytest.mark.asyncio
    async def test_system_health_process_count(self):
        """Verify process_count when included."""
        result = await _check_system_health()
        if "process_count" in result:
            assert isinstance(result["process_count"], int)
            assert result["process_count"] >= 0
    
    @pytest.mark.asyncio
    async def test_system_health_boot_time_iso_format(self):
        """Verify boot_time is ISO format when included."""
        result = await _check_system_health()
        if "boot_time" in result:
            assert isinstance(result["boot_time"], str)
            # Should parse as ISO format
            try:
                datetime.fromisoformat(result["boot_time"])
            except ValueError:
                pytest.fail(f"boot_time not ISO format: {result['boot_time']}")


class TestMemoryHealthDict:
    """Test MemoryHealthDict contract."""
    
    @pytest.mark.asyncio
    async def test_memory_health_structure(self):
        """Verify _check_memory_health returns valid MemoryHealthDict."""
        result = await _check_memory_health()
        assert isinstance(result, dict)
        assert "status" in result
        assert isinstance(result["status"], str)
    
    @pytest.mark.asyncio
    async def test_memory_health_status_valid(self):
        """Verify status is one of expected values."""
        result = await _check_memory_health()
        assert result["status"] in ["healthy", "warning", "critical", "error"]
    
    @pytest.mark.asyncio
    async def test_memory_health_usage_percent(self):
        """Verify usage_percent when included."""
        result = await _check_memory_health()
        if "usage_percent" in result:
            assert isinstance(result["usage_percent"], (int, float))
            assert 0 <= result["usage_percent"] <= 100
    
    @pytest.mark.asyncio
    async def test_memory_health_gb_values(self):
        """Verify GB values are non-negative when included."""
        result = await _check_memory_health()
        for field in ["available_gb", "total_gb"]:
            if field in result:
                assert isinstance(result[field], (int, float))
                assert result[field] >= 0


class TestCPUHealthDict:
    """Test CPUHealthDict contract."""
    
    @pytest.mark.asyncio
    async def test_cpu_health_structure(self):
        """Verify _check_cpu_health returns valid CPUHealthDict."""
        result = await _check_cpu_health()
        assert isinstance(result, dict)
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_cpu_health_usage_percent(self):
        """Verify usage_percent when included."""
        result = await _check_cpu_health()
        if "usage_percent" in result:
            assert isinstance(result["usage_percent"], (int, float))
            assert 0 <= result["usage_percent"] <= 100
    
    @pytest.mark.asyncio
    async def test_cpu_health_count(self):
        """Verify CPU count when included."""
        result = await _check_cpu_health()
        if "count" in result:
            assert isinstance(result["count"], int)
            assert result["count"] > 0


class TestDiskHealthDict:
    """Test DiskHealthDict contract."""
    
    @pytest.mark.asyncio
    async def test_disk_health_structure(self):
        """Verify _check_disk_health returns valid DiskHealthDict."""
        result = await _check_disk_health()
        assert isinstance(result, dict)
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_disk_health_usage_percent(self):
        """Verify usage_percent is valid percentage."""
        result = await _check_disk_health()
        if "usage_percent" in result:
            assert isinstance(result["usage_percent"], (int, float))
            assert 0 <= result["usage_percent"] <= 100
    
    @pytest.mark.asyncio
    async def test_disk_health_gb_values(self):
        """Verify GB values are valid."""
        result = await _check_disk_health()
        for field in ["free_gb", "total_gb"]:
            if field in result:
                assert isinstance(result[field], (int, float))
                assert result[field] >= 0


class TestNetworkHealthDict:
    """Test NetworkHealthDict contract."""
    
    @pytest.mark.asyncio
    async def test_network_health_structure(self):
        """Verify _check_network_health returns valid NetworkHealthDict."""
        result = await _check_network_health()
        assert isinstance(result, dict)
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_network_health_io_counters(self):
        """Verify I/O counters are non-negative integers."""
        result = await _check_network_health()
        for field in ["bytes_sent", "bytes_recv", "packets_sent", "packets_recv"]:
            if field in result:
                assert isinstance(result[field], int)
                assert result[field] >= 0


class TestServicesHealthDict:
    """Test ServicesHealthDict contract."""
    
    @pytest.mark.asyncio
    async def test_services_health_structure(self):
        """Verify _check_services_health returns valid ServicesHealthDict."""
        result = await _check_services_health()
        assert isinstance(result, dict)
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_services_health_counts(self):
        """Verify service counts are non-negative."""
        result = await _check_services_health()
        if "healthy_services" in result:
            assert isinstance(result["healthy_services"], int)
            assert result["healthy_services"] >= 0
        if "total_services" in result:
            assert isinstance(result["total_services"], int)
            assert result["total_services"] >= 0
    
    @pytest.mark.asyncio
    async def test_services_health_services_dict(self):
        """Verify services dict contains status strings."""
        result = await _check_services_health()
        if "services" in result:
            assert isinstance(result["services"], dict)
            for svc_name, svc_status in result["services"].items():
                assert isinstance(svc_name, str)
                assert isinstance(svc_status, str)


class TestEmbeddingsHealthDict:
    """Test EmbeddingsHealthDict contract."""
    
    @pytest.mark.asyncio
    async def test_embeddings_health_structure(self):
        """Verify _check_embeddings_health returns valid EmbeddingsHealthDict."""
        result = await _check_embeddings_health()
        assert isinstance(result, dict)
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_embeddings_health_model_count(self):
        """Verify active_models is non-negative."""
        result = await _check_embeddings_health()
        if "active_models" in result:
            assert isinstance(result["active_models"], int)
            assert result["active_models"] >= 0
    
    @pytest.mark.asyncio
    async def test_embeddings_health_endpoints(self):
        """Verify endpoints_available is non-negative."""
        result = await _check_embeddings_health()
        if "endpoints_available" in result:
            assert isinstance(result["endpoints_available"], int)
            assert result["endpoints_available"] >= 0
    
    @pytest.mark.asyncio
    async def test_embeddings_health_cache_hit_rate(self):
        """Verify cache_hit_rate is valid percentage."""
        result = await _check_embeddings_health()
        if "cache_hit_rate" in result:
            assert isinstance(result["cache_hit_rate"], (int, float))
            assert 0 <= result["cache_hit_rate"] <= 100


class TestVectorStoresHealthDict:
    """Test VectorStoresHealthDict contract."""
    
    @pytest.mark.asyncio
    async def test_vector_stores_health_structure(self):
        """Verify _check_vector_stores_health returns valid VectorStoresHealthDict."""
        result = await _check_vector_stores_health()
        assert isinstance(result, dict)
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_vector_stores_health_counts(self):
        """Verify store counts are non-negative."""
        result = await _check_vector_stores_health()
        if "total_stores" in result:
            assert isinstance(result["total_stores"], int)
            assert result["total_stores"] >= 0
        if "healthy_stores" in result:
            assert isinstance(result["healthy_stores"], int)
            assert result["healthy_stores"] >= 0
    
    @pytest.mark.asyncio
    async def test_vector_stores_health_healthy_lte_total(self):
        """Verify healthy_stores <= total_stores."""
        result = await _check_vector_stores_health()
        if "healthy_stores" in result and "total_stores" in result:
            assert result["healthy_stores"] <= result["total_stores"]


class TestServiceStatusDict:
    """Test ServiceStatusDict contract."""
    
    @pytest.mark.asyncio
    async def test_service_status_structure(self):
        """Verify _check_service_status returns valid ServiceStatusDict."""
        result = await _check_service_status("test_service")
        assert isinstance(result, dict)
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_service_status_response_time(self):
        """Verify response_time is non-negative when included."""
        result = await _check_service_status("test_service")
        if "response_time" in result:
            assert isinstance(result["response_time"], (int, float))
            assert result["response_time"] >= 0
    
    @pytest.mark.asyncio
    async def test_service_status_message(self):
        """Verify message is string when included."""
        result = await _check_service_status("test_service")
        if "message" in result:
            assert isinstance(result["message"], str)
    
    @pytest.mark.asyncio
    async def test_service_status_timestamp(self):
        """Verify last_check is ISO timestamp when included."""
        result = await _check_service_status("test_service")
        if "last_check" in result:
            assert isinstance(result["last_check"], str)
            try:
                datetime.fromisoformat(result["last_check"])
            except ValueError:
                pytest.fail(f"last_check not ISO format: {result['last_check']}")


class TestPerformanceMetricsDict:
    """Test PerformanceMetricsDict contract."""
    
    @pytest.mark.asyncio
    async def test_performance_metrics_structure(self):
        """Verify _get_performance_metrics returns valid PerformanceMetricsDict."""
        result = await _get_performance_metrics()
        assert isinstance(result, dict)
    
    @pytest.mark.asyncio
    async def test_performance_metrics_cpu_memory(self):
        """Verify CPU and memory usage are valid percentages."""
        result = await _get_performance_metrics()
        for field in ["cpu_usage", "memory_usage", "disk_usage"]:
            if field in result:
                assert isinstance(result[field], (int, float))
                assert 0 <= result[field] <= 100
    
    @pytest.mark.asyncio
    async def test_performance_metrics_counts(self):
        """Verify count fields are non-negative integers."""
        result = await _get_performance_metrics()
        for field in ["process_count", "network_connections"]:
            if field in result:
                assert isinstance(result[field], int)
                assert result[field] >= 0


class TestMockMonitoringServiceCheckHealth:
    """Test MockMonitoringService.check_health() TypedDict contract."""
    
    @pytest.mark.asyncio
    async def test_check_health_structure(self):
        """Verify check_health returns valid HealthCheckResultDict."""
        service = MockMonitoringService()
        result = await service.check_health()
        assert isinstance(result, dict)
        assert "overall_status" in result
        assert isinstance(result["overall_status"], str)
    
    @pytest.mark.asyncio
    async def test_check_health_timestamp(self):
        """Verify timestamp is ISO format."""
        service = MockMonitoringService()
        result = await service.check_health()
        assert "timestamp" in result
        assert isinstance(result["timestamp"], str)
        try:
            datetime.fromisoformat(result["timestamp"])
        except ValueError:
            pytest.fail(f"timestamp not ISO format: {result['timestamp']}")
    
    @pytest.mark.asyncio
    async def test_check_health_checks_performed(self):
        """Verify checks_performed is list of strings."""
        service = MockMonitoringService()
        result = await service.check_health()
        if "checks_performed" in result:
            assert isinstance(result["checks_performed"], list)
            assert all(isinstance(c, str) for c in result["checks_performed"])
    
    @pytest.mark.asyncio
    async def test_check_health_issues(self):
        """Verify issues is list of strings."""
        service = MockMonitoringService()
        result = await service.check_health()
        if "issues" in result:
            assert isinstance(result["issues"], list)
            assert all(isinstance(i, str) for i in result["issues"])
    
    @pytest.mark.asyncio
    async def test_check_health_with_services(self):
        """Verify service_health included when requested."""
        service = MockMonitoringService()
        result = await service.check_health(include_services=True)
        if "service_health" in result:
            assert isinstance(result["service_health"], list)
            for svc in result["service_health"]:
                assert "service_name" in svc
                assert "status" in svc
    
    @pytest.mark.asyncio
    async def test_check_health_without_services(self):
        """Verify service_health behavior with include_services=False."""
        service = MockMonitoringService()
        result = await service.check_health(include_services=False)
        # service_health should not be in result or be None/empty
        assert not result.get("service_health") or len(result.get("service_health", [])) == 0


class TestTypeConsistency:
    """Test consistency across health check functions."""
    
    @pytest.mark.asyncio
    async def test_all_health_checks_have_status(self):
        """Verify all health check functions return status field."""
        checks = [
            _check_system_health(),
            _check_memory_health(),
            _check_cpu_health(),
            _check_disk_health(),
            _check_network_health(),
            _check_services_health(),
            _check_embeddings_health(),
            _check_vector_stores_health(),
        ]
        results = await asyncio.gather(*checks)
        for result in results:
            assert "status" in result
            assert isinstance(result["status"], str)
    
    @pytest.mark.asyncio
    async def test_status_values_are_valid(self):
        """Verify status values are from expected set."""
        checks = [
            _check_system_health(),
            _check_memory_health(),
            _check_cpu_health(),
            _check_disk_health(),
            _check_network_health(),
            _check_services_health(),
            _check_embeddings_health(),
            _check_vector_stores_health(),
        ]
        results = await asyncio.gather(*checks)
        valid_statuses = {"healthy", "warning", "critical", "error"}
        for result in results:
            assert result.get("status") in valid_statuses


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    @pytest.mark.asyncio
    async def test_service_status_with_empty_string(self):
        """Verify _check_service_status handles empty service name."""
        result = await _check_service_status("")
        assert isinstance(result, dict)
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_service_status_with_unknown_service(self):
        """Verify _check_service_status handles unknown service."""
        result = await _check_service_status("unknown_service_xyz_123")
        assert isinstance(result, dict)
        assert "status" in result
    
    @pytest.mark.asyncio
    async def test_check_health_status_degradation(self):
        """Verify check_health properly sets overall_status."""
        service = MockMonitoringService()
        result = await service.check_health()
        assert "overall_status" in result
        status = result["overall_status"]
        assert status in ["healthy", "warning", "critical"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
