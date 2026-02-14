"""
Tests for BoundedCache implementation.

Tests verify:
- TTL expiration
- LRU eviction
- Thread safety
- Statistics tracking
- Backward compatibility
"""

import pytest
import time
import threading
from ipfs_datasets_py.logic.common.bounded_cache import BoundedCache


class TestBoundedCacheBasics:
    """Test basic cache operations."""
    
    def test_set_and_get(self):
        """Test basic set and get operations."""
        # GIVEN a cache
        cache = BoundedCache[str](maxsize=10, ttl=60)
        
        # WHEN we set and get a value
        cache.set("key1", "value1")
        result = cache.get("key1")
        
        # THEN it should return the correct value
        assert result == "value1"
    
    def test_get_nonexistent_key(self):
        """Test getting a key that doesn't exist."""
        # GIVEN an empty cache
        cache = BoundedCache[str]()
        
        # WHEN we get a nonexistent key
        result = cache.get("nonexistent")
        
        # THEN it should return None
        assert result is None
    
    def test_cache_miss_increments_counter(self):
        """Test that cache misses increment the miss counter."""
        # GIVEN a cache
        cache = BoundedCache[str]()
        
        # WHEN we miss the cache
        cache.get("missing")
        
        # THEN miss counter should increment
        stats = cache.get_stats()
        assert stats["misses"] == 1
        assert stats["hits"] == 0
    
    def test_cache_hit_increments_counter(self):
        """Test that cache hits increment the hit counter."""
        # GIVEN a cache with a value
        cache = BoundedCache[str]()
        cache.set("key1", "value1")
        
        # WHEN we hit the cache
        cache.get("key1")
        
        # THEN hit counter should increment
        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 0


class TestTTLExpiration:
    """Test TTL-based expiration."""
    
    def test_ttl_expiration(self):
        """Test that entries expire after TTL."""
        # GIVEN a cache with short TTL
        cache = BoundedCache[str](ttl=0.1)  # 100ms TTL
        cache.set("key1", "value1")
        
        # WHEN we wait for TTL to expire
        time.sleep(0.2)
        result = cache.get("key1")
        
        # THEN the entry should be expired
        assert result is None
        stats = cache.get_stats()
        assert stats["expirations"] == 1
    
    def test_no_expiration_with_zero_ttl(self):
        """Test that TTL=0 means no expiration."""
        # GIVEN a cache with no TTL
        cache = BoundedCache[str](ttl=0)
        cache.set("key1", "value1")
        
        # WHEN we wait
        time.sleep(0.1)
        result = cache.get("key1")
        
        # THEN the entry should still exist
        assert result == "value1"
    
    def test_cleanup_expired_entries(self):
        """Test manual cleanup of expired entries."""
        # GIVEN a cache with expired entries
        cache = BoundedCache[str](ttl=0.1)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        time.sleep(0.2)
        
        # WHEN we cleanup expired entries
        removed = cache.cleanup_expired()
        
        # THEN both entries should be removed
        assert removed == 2
        assert len(cache) == 0


class TestLRUEviction:
    """Test LRU eviction policy."""
    
    def test_lru_eviction_at_capacity(self):
        """Test that least recently used entry is evicted when at capacity."""
        # GIVEN a cache at capacity
        cache = BoundedCache[str](maxsize=3, ttl=0)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        
        # WHEN we add a new entry
        cache.set("key4", "value4")
        
        # THEN the oldest entry should be evicted
        assert cache.get("key1") is None  # Evicted
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"
        assert cache.get("key4") == "value4"
        
        stats = cache.get_stats()
        assert stats["evictions"] == 1
    
    def test_lru_order_updated_on_access(self):
        """Test that accessing an entry updates its LRU order."""
        # GIVEN a cache at capacity
        cache = BoundedCache[str](maxsize=3, ttl=0)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        
        # WHEN we access key1 (making it recently used)
        cache.get("key1")
        
        # AND add a new entry
        cache.set("key4", "value4")
        
        # THEN key2 should be evicted (not key1)
        assert cache.get("key1") == "value1"  # Still there
        assert cache.get("key2") is None  # Evicted
        assert cache.get("key3") == "value3"
        assert cache.get("key4") == "value4"
    
    def test_unlimited_size_with_zero_maxsize(self):
        """Test that maxsize=0 means unlimited."""
        # GIVEN a cache with no size limit
        cache = BoundedCache[str](maxsize=0, ttl=0)
        
        # WHEN we add many entries
        for i in range(100):
            cache.set(f"key{i}", f"value{i}")
        
        # THEN all entries should be stored
        assert len(cache) == 100
        stats = cache.get_stats()
        assert stats["evictions"] == 0


class TestThreadSafety:
    """Test thread-safe operations."""
    
    def test_concurrent_access(self):
        """Test concurrent reads and writes."""
        # GIVEN a cache
        cache = BoundedCache[int](maxsize=100, ttl=0)
        errors = []
        
        def writer(start, end):
            try:
                for i in range(start, end):
                    cache.set(f"key{i}", i)
            except Exception as e:
                errors.append(e)
        
        def reader(keys):
            try:
                for key in keys:
                    cache.get(key)
            except Exception as e:
                errors.append(e)
        
        # WHEN we access cache from multiple threads
        threads = []
        threads.append(threading.Thread(target=writer, args=(0, 50)))
        threads.append(threading.Thread(target=writer, args=(50, 100)))
        threads.append(threading.Thread(target=reader, args=([f"key{i}" for i in range(50)],)))
        
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        # THEN there should be no errors
        assert len(errors) == 0


class TestStatistics:
    """Test cache statistics."""
    
    def test_hit_rate_calculation(self):
        """Test hit rate calculation."""
        # GIVEN a cache with some hits and misses
        cache = BoundedCache[str]()
        cache.set("key1", "value1")
        
        # WHEN we have 1 hit and 2 misses
        cache.get("key1")  # Hit
        cache.get("key2")  # Miss
        cache.get("key3")  # Miss
        
        # THEN hit rate should be 33%
        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 2
        assert abs(stats["hit_rate"] - 0.333) < 0.01
    
    def test_stats_after_clear(self):
        """Test that stats reset after clear."""
        # GIVEN a cache with activity
        cache = BoundedCache[str]()
        cache.set("key1", "value1")
        cache.get("key1")
        cache.get("key2")
        
        # WHEN we clear the cache
        cache.clear()
        
        # THEN stats should be reset
        stats = cache.get_stats()
        assert stats["size"] == 0
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["evictions"] == 0
        assert stats["expirations"] == 0


class TestCacheUtilityMethods:
    """Test utility methods."""
    
    def test_clear(self):
        """Test clearing the cache."""
        # GIVEN a cache with entries
        cache = BoundedCache[str]()
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        
        # WHEN we clear it
        cache.clear()
        
        # THEN it should be empty
        assert len(cache) == 0
        assert cache.get("key1") is None
    
    def test_remove(self):
        """Test removing specific entry."""
        # GIVEN a cache with entries
        cache = BoundedCache[str]()
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        
        # WHEN we remove one entry
        removed = cache.remove("key1")
        
        # THEN only that entry should be removed
        assert removed is True
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"
    
    def test_remove_nonexistent(self):
        """Test removing nonexistent entry."""
        # GIVEN an empty cache
        cache = BoundedCache[str]()
        
        # WHEN we try to remove nonexistent key
        removed = cache.remove("nonexistent")
        
        # THEN it should return False
        assert removed is False
    
    def test_contains(self):
        """Test __contains__ method."""
        # GIVEN a cache with an entry
        cache = BoundedCache[str](ttl=0.1)
        cache.set("key1", "value1")
        
        # THEN contains should work
        assert "key1" in cache
        assert "key2" not in cache
        
        # WHEN entry expires
        time.sleep(0.2)
        
        # THEN contains should return False
        assert "key1" not in cache
    
    def test_len(self):
        """Test __len__ method."""
        # GIVEN a cache with entries
        cache = BoundedCache[str]()
        
        # WHEN we add entries
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        
        # THEN len should be correct
        assert len(cache) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
