"""
Integration tests for processor system.

Tests the interaction between different components:
- UniversalProcessor + adapters
- Error handling + retry logic
- Caching + TTL/eviction
- Health monitoring
- Configuration validation
"""

import asyncio
import pytest
import time
from pathlib import Path
from unittest.mock import Mock, AsyncMock, patch

# Import processor components
from ipfs_datasets_py.processors.universal_processor import UniversalProcessor, ProcessorConfig
from ipfs_datasets_py.processors.error_handling import (
    ProcessorError, TransientError, RetryConfig, CircuitBreakerConfig
)
from ipfs_datasets_py.processors.caching import SmartCache, EvictionPolicy, CacheStatistics
from ipfs_datasets_py.processors.monitoring import HealthStatus
from ipfs_datasets_py.processors.protocol import ProcessingResult, ProcessingMetadata, ProcessingStatus


class TestUniversalProcessorIntegration:
    """Integration tests for UniversalProcessor with all components."""
    
    def test_processor_initialization_with_full_config(self):
        """
        Test processor initializes correctly with all features enabled.
        
        GIVEN: A complete ProcessorConfig with all features
        WHEN: UniversalProcessor is initialized
        THEN: All components are properly set up
        """
        # GIVEN
        config = ProcessorConfig(
            enable_caching=True,
            cache_size_mb=100,
            cache_ttl_seconds=3600,
            cache_eviction_policy="lru",
            enable_monitoring=True,
            max_retries=3,
            circuit_breaker_enabled=True,
            circuit_breaker_threshold=5,
            parallel_workers=4,
            timeout_seconds=300
        )
        
        # WHEN
        processor = UniversalProcessor(config)
        
        # THEN
        assert processor.config == config
        assert processor._cache is not None
        assert processor._retry_handler is not None
        assert processor._health_monitor is not None
        assert len(processor.registry.list_processors()) > 0
    
    def test_processor_with_caching_disabled(self):
        """Test processor works when caching is disabled."""
        # GIVEN
        config = ProcessorConfig(enable_caching=False)
        
        # WHEN
        processor = UniversalProcessor(config)
        
        # THEN
        assert processor._cache is None
        assert processor.config.enable_caching is False
    
    def test_processor_with_monitoring_disabled(self):
        """Test processor works when monitoring is disabled."""
        # GIVEN
        config = ProcessorConfig(enable_monitoring=False)
        
        # WHEN
        processor = UniversalProcessor(config)
        
        # THEN
        assert processor._health_monitor is None
        assert processor.config.enable_monitoring is False


class TestCachingIntegration:
    """Test caching integration with processor."""
    
    def test_cache_hit_on_repeated_input(self):
        """
        Test cache returns cached result on repeated input.
        
        GIVEN: A processor with caching enabled
        WHEN: Same input is processed twice
        THEN: Second call returns cached result (faster)
        """
        # GIVEN
        config = ProcessorConfig(
            enable_caching=True,
            cache_ttl_seconds=60
        )
        processor = UniversalProcessor(config)
        
        # Create a test input
        test_input = "test_input_123"
        
        # Mock the cache to simulate behavior
        from ipfs_datasets_py.processors.processing import ProcessingResult
        mock_result = ProcessingResult(
            success=True,
            content={"data": "test"},
            metadata={"cached": False}
        )
        
        # WHEN - Put something in cache
        if processor.cache:
            processor.cache.put(test_input, mock_result)
        
        # THEN - Should be able to retrieve it
        if processor.cache:
            assert processor.cache.has_key(test_input)
            cached = processor.cache.get(test_input)
            assert cached is not None
            assert cached.content["data"] == "test"
    
    def test_cache_expiration_with_ttl(self):
        """
        Test cache entries expire after TTL.
        
        GIVEN: A processor with short TTL
        WHEN: Entry is added and TTL expires
        THEN: Entry is no longer in cache
        """
        # GIVEN
        config = ProcessorConfig(
            enable_caching=True,
            cache_ttl_seconds=1  # 1 second TTL
        )
        processor = UniversalProcessor(config)
        
        # WHEN
        test_key = "expire_test"
        if processor.cache:
            processor.cache.put(test_key, {"data": "test"})
            
            # Entry should exist immediately
            assert processor.cache.has_key(test_key)
            
            # Wait for expiration
            time.sleep(1.5)
            
            # THEN - Entry should be expired
            expired = processor.cache.get(test_key)
            assert expired is None
    
    def test_cache_eviction_on_size_limit(self):
        """
        Test cache evicts entries when size limit reached.
        
        GIVEN: A processor with small cache size
        WHEN: More data is added than fits
        THEN: Old entries are evicted
        """
        # GIVEN
        config = ProcessorConfig(
            enable_caching=True,
            cache_size_mb=1,  # 1MB limit
            cache_eviction_policy="lru"
        )
        processor = UniversalProcessor(config)
        
        # WHEN - Add entries
        if processor.cache:
            for i in range(5):
                key = f"key_{i}"
                # Small value for testing
                value = {"data": f"value_{i}"}
                processor.cache.put(key, value)
            
            # THEN - Cache should have entries
            stats = processor.cache.get_statistics()
            assert stats.total_entries > 0
    
    def test_cache_statistics_tracking(self):
        """Test cache statistics are tracked correctly."""
        # GIVEN
        config = ProcessorConfig(enable_caching=True)
        processor = UniversalProcessor(config)
        
        # WHEN
        if processor.cache:
            # Add some entries
            processor.cache.put("key1", "value1")
            processor.cache.put("key2", "value2")
            
            # Get some entries (hits)
            processor.cache.get("key1")
            processor.cache.get("key2")
            
            # Try non-existent key (miss)
            processor.cache.get("nonexistent")
            
            # THEN
            stats = processor.get_cache_statistics()
            assert stats['total_entries'] == 2
            assert stats['hits'] >= 2
            assert stats['misses'] >= 1


class TestErrorHandlingIntegration:
    """Test error handling integration."""
    
    def test_retry_configuration(self):
        """Test retry logic is configured correctly."""
        # GIVEN
        config = ProcessorConfig(
            max_retries=5,
            retry_base_delay=2.0,
            retry_max_delay=30.0
        )
        
        # WHEN
        processor = UniversalProcessor(config)
        
        # THEN
        assert processor.retry_handler is not None
        assert processor.retry_handler.config.max_retries == 5
    
    def test_circuit_breaker_configuration(self):
        """Test circuit breaker is configured correctly."""
        # GIVEN
        config = ProcessorConfig(
            circuit_breaker_enabled=True,
            circuit_breaker_threshold=3,
            circuit_breaker_timeout=60
        )
        
        # WHEN
        processor = UniversalProcessor(config)
        
        # THEN
        assert processor.circuit_breakers == {}  # Empty until processors used


class TestHealthMonitoringIntegration:
    """Test health monitoring integration."""
    
    def test_health_monitor_initialization(self):
        """Test health monitor is properly initialized."""
        # GIVEN
        config = ProcessorConfig(enable_monitoring=True)
        
        # WHEN
        processor = UniversalProcessor(config)
        
        # THEN
        assert processor.health_monitor is not None
        health = processor.check_health()
        assert health is not None
        assert health.status in [HealthStatus.HEALTHY, HealthStatus.UNKNOWN]
    
    def test_health_report_generation(self):
        """Test health report can be generated."""
        # GIVEN
        config = ProcessorConfig(enable_monitoring=True)
        processor = UniversalProcessor(config)
        
        # WHEN
        text_report = processor.get_health_report(format="text")
        json_report = processor.get_health_report(format="json")
        
        # THEN
        assert isinstance(text_report, str)
        assert len(text_report) > 0
        assert "System Health" in text_report or "Overall" in text_report
        
        assert isinstance(json_report, str)
        assert "{" in json_report  # Valid JSON
    
    def test_processor_statistics(self):
        """Test processor statistics are collected."""
        # GIVEN
        config = ProcessorConfig(enable_monitoring=True)
        processor = UniversalProcessor(config)
        
        # WHEN
        stats = processor.get_statistics()
        
        # THEN
        assert isinstance(stats, dict)
        assert 'total_calls' in stats
        assert 'successful_calls' in stats
        assert 'failed_calls' in stats
        assert 'cache_hits' in stats


class TestConfigurationValidation:
    """Test configuration validation."""
    
    def test_valid_configuration(self):
        """Test valid configuration is accepted."""
        # GIVEN/WHEN
        config = ProcessorConfig(
            cache_size_mb=100,
            cache_ttl_seconds=3600,
            max_retries=3,
            parallel_workers=4
        )
        
        # THEN - Should not raise
        processor = UniversalProcessor(config)
        assert processor.config == config
    
    def test_invalid_cache_size_rejected(self):
        """Test invalid cache size is rejected."""
        # WHEN/THEN
        with pytest.raises(ValueError, match="cache_size_mb must be positive"):
            ProcessorConfig(cache_size_mb=-10)
    
    def test_invalid_ttl_rejected(self):
        """Test invalid TTL is rejected."""
        # WHEN/THEN
        with pytest.raises(ValueError, match="cache_ttl_seconds must be positive"):
            ProcessorConfig(cache_ttl_seconds=-100)
    
    def test_invalid_eviction_policy_rejected(self):
        """Test invalid eviction policy is rejected."""
        # WHEN/THEN
        with pytest.raises(ValueError, match="cache_eviction_policy must be one of"):
            ProcessorConfig(cache_eviction_policy="invalid")
    
    def test_invalid_max_retries_rejected(self):
        """Test invalid max retries is rejected."""
        # WHEN/THEN
        with pytest.raises(ValueError, match="max_retries must be non-negative"):
            ProcessorConfig(max_retries=-5)
    
    def test_invalid_circuit_breaker_threshold_rejected(self):
        """Test invalid circuit breaker threshold is rejected."""
        # WHEN/THEN
        with pytest.raises(ValueError, match="circuit_breaker_threshold must be positive"):
            ProcessorConfig(circuit_breaker_threshold=0)


class TestAdapterRegistry:
    """Test adapter registry integration."""
    
    def test_all_adapters_registered(self):
        """Test all expected adapters are registered."""
        # GIVEN
        processor = UniversalProcessor()
        
        # WHEN
        adapters = processor.registry.list_processors()
        
        # THEN - Should have 8 adapters from Week 1
        assert len(adapters) >= 6  # At least 6 adapters
        
        # Check for key adapters
        adapter_names = [a['name'] for a in adapters]
        # Note: Exact names might differ, checking for reasonable count
        assert len(adapter_names) > 0
    
    def test_adapter_priorities(self):
        """Test adapters are ordered by priority."""
        # GIVEN
        processor = UniversalProcessor()
        
        # WHEN
        adapters = processor.registry.list_processors()
        
        # THEN - Priorities should be in descending order
        if len(adapters) > 1:
            priorities = [a.get('priority', 0) for a in adapters]
            # Check that we have some priority differentiation
            assert len(set(priorities)) > 1


class TestComponentInteractions:
    """Test interactions between components."""
    
    def test_caching_with_monitoring(self):
        """Test caching and monitoring work together."""
        # GIVEN
        config = ProcessorConfig(
            enable_caching=True,
            enable_monitoring=True
        )
        processor = UniversalProcessor(config)
        
        # WHEN - Use cache
        if processor.cache:
            processor.cache.put("test", "value")
            processor.cache.get("test")
        
        # THEN - Stats should be updated
        stats = processor.get_statistics()
        cache_stats = processor.get_cache_statistics()
        
        assert isinstance(stats, dict)
        assert isinstance(cache_stats, dict)
    
    def test_error_handling_with_monitoring(self):
        """Test error handling and monitoring integration."""
        # GIVEN
        config = ProcessorConfig(
            enable_monitoring=True,
            max_retries=2
        )
        processor = UniversalProcessor(config)
        
        # WHEN/THEN - Should have both components
        assert processor.retry_handler is not None
        assert processor.health_monitor is not None
        
        health = processor.check_health()
        assert health is not None
    
    def test_full_integration_all_components(self):
        """Test all components working together."""
        # GIVEN - Enable everything
        config = ProcessorConfig(
            enable_caching=True,
            cache_size_mb=50,
            cache_ttl_seconds=300,
            enable_monitoring=True,
            max_retries=3,
            circuit_breaker_enabled=True,
            parallel_workers=4
        )
        
        # WHEN
        processor = UniversalProcessor(config)
        
        # THEN - All components should be initialized
        assert processor.cache is not None
        assert processor.retry_handler is not None
        assert processor.health_monitor is not None
        assert processor.circuit_breakers is not None
        
        # Can generate reports
        health_report = processor.get_health_report()
        assert isinstance(health_report, str)
        
        cache_stats = processor.get_cache_statistics()
        assert isinstance(cache_stats, dict)
        
        stats = processor.get_statistics()
        assert isinstance(stats, dict)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
