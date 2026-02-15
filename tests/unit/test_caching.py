"""
Tests for smart caching module.

Tests TTL expiration, eviction policies (LRU/LFU/FIFO), and cache statistics.
"""

import pytest
import time
from datetime import datetime, timedelta

from ipfs_datasets_py.processors.caching import (
    SmartCache,
    CacheEntry,
    CacheStatistics,
    EvictionPolicy
)


class TestCacheStatistics:
    """Test cache statistics dataclass."""
    
    def test_empty_statistics(self):
        """Test empty statistics."""
        stats = CacheStatistics()
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.evictions == 0
        assert stats.hit_rate() == 0.0
    
    def test_hit_rate_calculation(self):
        """Test hit rate calculation."""
        stats = CacheStatistics(hits=80, misses=20)
        assert stats.hit_rate() == 0.8
    
    def test_to_dict(self):
        """Test conversion to dictionary."""
        stats = CacheStatistics(hits=10, misses=5, evictions=2)
        d = stats.to_dict()
        
        assert d['hits'] == 10
        assert d['misses'] == 5
        assert d['evictions'] == 2
        assert d['hit_rate'] == 2/3


class TestSmartCacheBasics:
    """Test basic cache operations."""
    
    def test_cache_initialization(self):
        """Test cache initialization with default values."""
        cache = SmartCache()
        
        assert cache.max_size_bytes > 0
        assert cache.eviction_policy == EvictionPolicy.LRU
        assert cache.get_size_mb() == 0.0
    
    def test_cache_put_and_get(self):
        """Test basic put and get operations."""
        cache = SmartCache()
        
        cache.put("key1", "value1")
        result = cache.get("key1")
        
        assert result == "value1"
        
        stats = cache.get_statistics()
        assert stats.hits == 1
        assert stats.misses == 0
    
    def test_cache_miss(self):
        """Test cache miss."""
        cache = SmartCache()
        
        result = cache.get("nonexistent")
        
        assert result is None
        
        stats = cache.get_statistics()
        assert stats.hits == 0
        assert stats.misses == 1
    
    def test_cache_has_key(self):
        """Test has_key method."""
        cache = SmartCache()
        
        assert not cache.has_key("key1")
        
        cache.put("key1", "value1")
        assert cache.has_key("key1")
    
    def test_cache_remove(self):
        """Test removing entries."""
        cache = SmartCache()
        
        cache.put("key1", "value1")
        assert cache.has_key("key1")
        
        removed = cache.remove("key1")
        assert removed
        assert not cache.has_key("key1")
        
        # Removing again should return False
        removed = cache.remove("key1")
        assert not removed
    
    def test_cache_clear(self):
        """Test clearing cache."""
        cache = SmartCache()
        
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        
        assert cache.get_statistics().entry_count == 2
        
        cache.clear()
        
        assert cache.get_statistics().entry_count == 0
        assert cache.get_size_mb() == 0.0


class TestCacheTTL:
    """Test TTL (time-to-live) functionality."""
    
    def test_ttl_expiration(self):
        """Test that entries expire after TTL."""
        cache = SmartCache(ttl_seconds=1)  # 1 second TTL
        
        cache.put("key1", "value1")
        
        # Should be available immediately
        assert cache.get("key1") == "value1"
        
        # Wait for expiration
        time.sleep(1.1)
        
        # Should be expired
        assert cache.get("key1") is None
        
        stats = cache.get_statistics()
        assert stats.misses == 1  # Expired entry counts as miss
    
    def test_no_ttl(self):
        """Test cache with no TTL."""
        cache = SmartCache(ttl_seconds=0)  # No expiration
        
        cache.put("key1", "value1")
        time.sleep(0.1)
        
        # Should still be available
        assert cache.get("key1") == "value1"
    
    def test_cleanup_expired(self):
        """Test manual cleanup of expired entries."""
        cache = SmartCache(ttl_seconds=1)
        
        cache.put("key1", "value1")
        cache.put("key2", "value2")
        
        time.sleep(1.1)
        
        # Manually cleanup expired
        removed_count = cache.cleanup_expired()
        
        assert removed_count == 2
        assert cache.get_statistics().entry_count == 0


class TestCacheEviction:
    """Test cache eviction policies."""
    
    def test_lru_eviction(self):
        """Test Least Recently Used eviction."""
        # Small cache that will trigger eviction
        cache = SmartCache(max_size_mb=0.001, eviction_policy="lru")
        
        # Add entries
        cache.put("key1", "a" * 100)
        cache.put("key2", "b" * 100)
        cache.put("key3", "c" * 100)
        
        # Access key1 to make it recently used
        cache.get("key1")
        
        # Add more entries to trigger eviction
        cache.put("key4", "d" * 200)
        cache.put("key5", "e" * 200)
        
        # key1 should still be there (recently accessed)
        # but some others should be evicted
        stats = cache.get_statistics()
        assert stats.evictions > 0
    
    def test_lfu_eviction(self):
        """Test Least Frequently Used eviction."""
        cache = SmartCache(max_size_mb=0.001, eviction_policy="lfu")
        
        # Add entries
        cache.put("key1", "a" * 100)
        cache.put("key2", "b" * 100)
        cache.put("key3", "c" * 100)
        
        # Access key1 multiple times to make it frequently used
        for _ in range(5):
            cache.get("key1")
        
        # Add more entries to trigger eviction
        cache.put("key4", "d" * 200)
        cache.put("key5", "e" * 200)
        
        # key1 should still be there (frequently accessed)
        assert cache.has_key("key1")
        
        stats = cache.get_statistics()
        assert stats.evictions > 0
    
    def test_fifo_eviction(self):
        """Test First In First Out eviction."""
        cache = SmartCache(max_size_mb=0.001, eviction_policy="fifo")
        
        # Add entries
        cache.put("key1", "a" * 100)
        cache.put("key2", "b" * 100)
        cache.put("key3", "c" * 100)
        
        # Add more entries to trigger eviction
        cache.put("key4", "d" * 200)
        cache.put("key5", "e" * 200)
        
        # Oldest entries should be evicted
        stats = cache.get_statistics()
        assert stats.evictions > 0
    
    def test_size_limit_enforcement(self):
        """Test that cache respects size limit."""
        cache = SmartCache(max_size_mb=0.01)  # 10KB
        
        # Add a large entry
        large_value = "x" * 5000  # ~5KB
        cache.put("key1", large_value)
        
        # Add another large entry
        cache.put("key2", "y" * 5000)
        
        # Cache should not exceed max size
        assert cache.get_size_mb() <= 0.01
    
    def test_entry_too_large(self):
        """Test handling of entries too large for cache."""
        cache = SmartCache(max_size_mb=0.001)  # 1KB
        
        # Try to cache something larger than max
        huge_value = "z" * 10000  # ~10KB
        cache.put("huge", huge_value)
        
        # Should not be cached
        assert not cache.has_key("huge")


class TestCacheStatisticsTracking:
    """Test cache statistics tracking."""
    
    def test_hit_tracking(self):
        """Test tracking cache hits."""
        cache = SmartCache()
        
        cache.put("key1", "value1")
        
        # Multiple hits
        for _ in range(5):
            cache.get("key1")
        
        stats = cache.get_statistics()
        assert stats.hits == 5
    
    def test_miss_tracking(self):
        """Test tracking cache misses."""
        cache = SmartCache()
        
        # Multiple misses
        for i in range(3):
            cache.get(f"nonexistent_{i}")
        
        stats = cache.get_statistics()
        assert stats.misses == 3
    
    def test_eviction_tracking(self):
        """Test tracking evictions."""
        cache = SmartCache(max_size_mb=0.001)
        
        # Fill cache to trigger evictions
        for i in range(20):
            cache.put(f"key_{i}", "x" * 100)
        
        stats = cache.get_statistics()
        assert stats.evictions > 0
    
    def test_size_tracking(self):
        """Test size tracking."""
        cache = SmartCache()
        
        initial_size = cache.get_size_mb()
        assert initial_size == 0.0
        
        cache.put("key1", "a" * 1000)
        
        new_size = cache.get_size_mb()
        assert new_size > initial_size
    
    def test_usage_percent(self):
        """Test usage percentage calculation."""
        cache = SmartCache(max_size_mb=1.0)
        
        assert cache.get_usage_percent() == 0.0
        
        # Add some data
        cache.put("key1", "x" * 500000)  # ~500KB
        
        usage = cache.get_usage_percent()
        assert 0 < usage < 100


class TestCachePrewarm:
    """Test cache pre-warming functionality."""
    
    def test_prewarm(self):
        """Test pre-warming cache with entries."""
        cache = SmartCache()
        
        entries = {
            "key1": "value1",
            "key2": "value2",
            "key3": "value3"
        }
        
        cache.prewarm(entries)
        
        # All entries should be cached
        for key, value in entries.items():
            assert cache.get(key) == value
        
        stats = cache.get_statistics()
        assert stats.entry_count == 3
    
    def test_prewarm_with_eviction(self):
        """Test pre-warming with size limits."""
        cache = SmartCache(max_size_mb=0.001)
        
        # Try to prewarm with more data than cache can hold
        entries = {
            f"key_{i}": "x" * 100
            for i in range(20)
        }
        
        cache.prewarm(entries)
        
        # Not all entries will fit
        stats = cache.get_statistics()
        assert stats.entry_count < len(entries)
        assert stats.evictions > 0


class TestCacheAccessTracking:
    """Test access tracking for LRU/LFU."""
    
    def test_access_count_tracking(self):
        """Test that access counts are tracked."""
        cache = SmartCache()
        
        cache.put("key1", "value1")
        
        # Access multiple times
        for _ in range(5):
            cache.get("key1")
        
        # Check internal access count (via entry)
        entry = cache._cache.get("key1")
        assert entry.access_count == 5
    
    def test_last_accessed_tracking(self):
        """Test that last accessed time is tracked."""
        cache = SmartCache()
        
        cache.put("key1", "value1")
        time.sleep(0.1)
        
        before_access = datetime.now()
        cache.get("key1")
        
        entry = cache._cache.get("key1")
        assert entry.last_accessed >= before_access
