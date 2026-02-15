"""
Tests for health monitoring module.

Tests health status tracking, processor monitoring, and system health.
"""

import pytest

from ipfs_datasets_py.processors.monitoring import (
    HealthStatus,
    ProcessorHealth,
    SystemHealth,
    HealthMonitor
)
from ipfs_datasets_py.processors.registry import ProcessorRegistry


class MockProcessor:
    """Mock processor for testing."""
    
    def __init__(self, name: str):
        self.name = name
    
    def get_name(self):
        return self.name
    
    async def can_process(self, input_source):
        return True
    
    def get_supported_types(self):
        return ["test"]
    
    def get_priority(self):
        return 10


class TestHealthStatus:
    """Test health status enum."""
    
    def test_health_status_values(self):
        """Test health status enum values."""
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"
        assert HealthStatus.UNKNOWN.value == "unknown"


class TestProcessorHealth:
    """Test ProcessorHealth dataclass."""
    
    def test_processor_health_creation(self):
        """Test creating ProcessorHealth."""
        health = ProcessorHealth(
            name="TestProcessor",
            status=HealthStatus.HEALTHY,
            success_rate=0.95,
            total_calls=100,
            successful_calls=95,
            failed_calls=5
        )
        
        assert health.name == "TestProcessor"
        assert health.status == HealthStatus.HEALTHY
        assert health.success_rate == 0.95
    
    def test_is_healthy(self):
        """Test is_healthy method."""
        health = ProcessorHealth(name="Test", status=HealthStatus.HEALTHY)
        assert health.is_healthy()
        
        health.status = HealthStatus.DEGRADED
        assert not health.is_healthy()
    
    def test_is_degraded(self):
        """Test is_degraded method."""
        health = ProcessorHealth(name="Test", status=HealthStatus.DEGRADED)
        assert health.is_degraded()
        
        health.status = HealthStatus.HEALTHY
        assert not health.is_degraded()
    
    def test_is_unhealthy(self):
        """Test is_unhealthy method."""
        health = ProcessorHealth(name="Test", status=HealthStatus.UNHEALTHY)
        assert health.is_unhealthy()
        
        health.status = HealthStatus.HEALTHY
        assert not health.is_unhealthy()
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        health = ProcessorHealth(
            name="TestProcessor",
            status=HealthStatus.HEALTHY,
            success_rate=0.95,
            total_calls=100
        )
        
        d = health.to_dict()
        
        assert d['name'] == "TestProcessor"
        assert d['status'] == "healthy"
        assert d['success_rate'] == 0.95
        assert d['total_calls'] == 100


class TestSystemHealth:
    """Test SystemHealth dataclass."""
    
    def test_system_health_creation(self):
        """Test creating SystemHealth."""
        health = SystemHealth(
            status=HealthStatus.HEALTHY,
            processor_count=5,
            healthy_count=5,
            degraded_count=0,
            unhealthy_count=0,
            overall_success_rate=0.98
        )
        
        assert health.status == HealthStatus.HEALTHY
        assert health.processor_count == 5
        assert health.overall_success_rate == 0.98
    
    def test_system_health_to_dict(self):
        """Test conversion to dictionary."""
        proc_health = ProcessorHealth(
            name="Test",
            status=HealthStatus.HEALTHY
        )
        
        health = SystemHealth(
            status=HealthStatus.HEALTHY,
            processor_count=1,
            healthy_count=1,
            degraded_count=0,
            unhealthy_count=0,
            overall_success_rate=1.0,
            processor_health={"Test": proc_health}
        )
        
        d = health.to_dict()
        
        assert d['status'] == "healthy"
        assert d['processor_count'] == 1
        assert 'processors' in d
        assert 'Test' in d['processors']


class TestHealthMonitor:
    """Test HealthMonitor class."""
    
    def test_monitor_initialization(self):
        """Test HealthMonitor initialization."""
        registry = ProcessorRegistry()
        monitor = HealthMonitor(registry)
        
        assert monitor.registry is registry
    
    def test_check_processor_health_unknown(self):
        """Test checking health of unknown processor."""
        registry = ProcessorRegistry()
        monitor = HealthMonitor(registry)
        
        health = monitor.check_processor_health("UnknownProcessor")
        
        assert health.status == HealthStatus.UNKNOWN
        assert health.name == "UnknownProcessor"
    
    def test_check_processor_health_healthy(self):
        """Test checking health of healthy processor."""
        registry = ProcessorRegistry()
        processor = MockProcessor("HealthyProcessor")
        registry.register(processor)
        
        # Simulate successful calls
        for _ in range(100):
            registry.record_call("HealthyProcessor", success=True, duration_seconds=0.1)
        
        monitor = HealthMonitor(registry)
        health = monitor.check_processor_health("HealthyProcessor")
        
        assert health.status == HealthStatus.HEALTHY
        assert health.success_rate == 1.0
        assert health.total_calls == 100
    
    def test_check_processor_health_degraded(self):
        """Test checking health of degraded processor."""
        registry = ProcessorRegistry()
        processor = MockProcessor("DegradedProcessor")
        registry.register(processor)
        
        # Simulate 85% success rate (degraded range)
        for _ in range(85):
            registry.record_call("DegradedProcessor", success=True, duration_seconds=0.1)
        for _ in range(15):
            registry.record_call("DegradedProcessor", success=False, duration_seconds=0.1)
        
        monitor = HealthMonitor(registry)
        health = monitor.check_processor_health("DegradedProcessor")
        
        assert health.status == HealthStatus.DEGRADED
        assert 0.80 <= health.success_rate <= 0.95
    
    def test_check_processor_health_unhealthy(self):
        """Test checking health of unhealthy processor."""
        registry = ProcessorRegistry()
        processor = MockProcessor("UnhealthyProcessor")
        registry.register(processor)
        
        # Simulate 70% success rate (unhealthy)
        for _ in range(70):
            registry.record_call("UnhealthyProcessor", success=True, duration_seconds=0.1)
        for _ in range(30):
            registry.record_call("UnhealthyProcessor", success=False, duration_seconds=0.1)
        
        monitor = HealthMonitor(registry)
        health = monitor.check_processor_health("UnhealthyProcessor")
        
        assert health.status == HealthStatus.UNHEALTHY
        assert health.success_rate < 0.80
    
    def test_check_system_health(self):
        """Test checking overall system health."""
        registry = ProcessorRegistry()
        
        # Register multiple processors
        for i in range(3):
            processor = MockProcessor(f"Processor{i}")
            registry.register(processor)
        
        # Simulate calls with different success rates
        for _ in range(100):
            registry.record_call("Processor0", success=True, duration_seconds=0.1)
        
        for _ in range(85):
            registry.record_call("Processor1", success=True, duration_seconds=0.1)
        for _ in range(15):
            registry.record_call("Processor1", success=False, duration_seconds=0.1)
        
        for _ in range(70):
            registry.record_call("Processor2", success=True, duration_seconds=0.1)
        for _ in range(30):
            registry.record_call("Processor2", success=False, duration_seconds=0.1)
        
        monitor = HealthMonitor(registry)
        system_health = monitor.check_system_health()
        
        assert system_health.processor_count == 3
        assert system_health.healthy_count == 1  # Processor0
        assert system_health.degraded_count == 1  # Processor1
        assert system_health.unhealthy_count == 1  # Processor2
        assert len(system_health.processor_health) == 3
    
    def test_get_unhealthy_processors(self):
        """Test getting list of unhealthy processors."""
        registry = ProcessorRegistry()
        
        # Register processors with different health
        healthy_proc = MockProcessor("HealthyProc")
        unhealthy_proc = MockProcessor("UnhealthyProc")
        registry.register(healthy_proc)
        registry.register(unhealthy_proc)
        
        # Healthy
        for _ in range(100):
            registry.record_call("HealthyProc", success=True, duration_seconds=0.1)
        
        # Unhealthy
        for _ in range(50):
            registry.record_call("UnhealthyProc", success=True, duration_seconds=0.1)
        for _ in range(50):
            registry.record_call("UnhealthyProc", success=False, duration_seconds=0.1)
        
        monitor = HealthMonitor(registry)
        unhealthy = monitor.get_unhealthy_processors()
        
        assert len(unhealthy) == 1
        assert unhealthy[0].name == "UnhealthyProc"
    
    def test_get_degraded_processors(self):
        """Test getting list of degraded processors."""
        registry = ProcessorRegistry()
        
        # Register processors with different health
        healthy_proc = MockProcessor("HealthyProc")
        degraded_proc = MockProcessor("DegradedProc")
        registry.register(healthy_proc)
        registry.register(degraded_proc)
        
        # Healthy
        for _ in range(100):
            registry.record_call("HealthyProc", success=True, duration_seconds=0.1)
        
        # Degraded
        for _ in range(85):
            registry.record_call("DegradedProc", success=True, duration_seconds=0.1)
        for _ in range(15):
            registry.record_call("DegradedProc", success=False, duration_seconds=0.1)
        
        monitor = HealthMonitor(registry)
        degraded = monitor.get_degraded_processors()
        
        assert len(degraded) == 1
        assert degraded[0].name == "DegradedProc"
    
    def test_health_report_text_format(self):
        """Test generating health report in text format."""
        registry = ProcessorRegistry()
        processor = MockProcessor("TestProc")
        registry.register(processor)
        
        for _ in range(100):
            registry.record_call("TestProc", success=True, duration_seconds=0.1)
        
        monitor = HealthMonitor(registry)
        report = monitor.get_health_report(format="text")
        
        assert "PROCESSOR HEALTH REPORT" in report
        assert "TestProc" in report
        assert "100.0%" in report or "100%" in report
    
    def test_health_report_json_format(self):
        """Test generating health report in JSON format."""
        import json
        
        registry = ProcessorRegistry()
        processor = MockProcessor("TestProc")
        registry.register(processor)
        
        for _ in range(100):
            registry.record_call("TestProc", success=True, duration_seconds=0.1)
        
        monitor = HealthMonitor(registry)
        report = monitor.get_health_report(format="json")
        
        # Should be valid JSON
        data = json.loads(report)
        
        assert 'status' in data
        assert 'processor_count' in data
        assert 'processors' in data
        assert 'TestProc' in data['processors']
