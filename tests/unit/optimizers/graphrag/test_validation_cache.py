"""Tests for validation_cache module."""

import json
import time
from pathlib import Path
import pytest
from ipfs_datasets_py.optimizers.graphrag.validation_cache import (
    CacheStats,
    LRUCache,
    ValidationCache,
)


class TestCacheStats:
    """Test cache statistics."""
    
    def test_initial_stats(self):
        """Initial stats should be zero."""
        stats = CacheStats()
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.evictions == 0
        assert stats.writes == 0
        assert stats.hit_rate == 0.0
        assert stats.total_requests == 0
    
    def test_hit_rate_calculation(self):
        """Hit rate should be hits / (hits + misses)."""
        stats = CacheStats(hits=75, misses=25)
        assert stats.hit_rate == 0.75
        assert stats.total_requests == 100
    
    def test_to_dict(self):
        """Stats should serialize to dict."""
        stats = CacheStats(hits=10, misses=5, evictions=2, writes=15, total_size_bytes=1024 * 1024)
        d = stats.to_dict()
        assert d["hits"] == 10
        assert d["misses"] == 5
        assert d["hit_rate"] == pytest.approx(0.6667, abs=0.001)
        assert d["total_size_mb"] == pytest.approx(1.0, abs=0.01)


class TestLRUCache:
    """Test LRU cache."""
    
    def test_basic_get_set(self):
        """Basic get/set operations should work."""
        cache = LRUCache(max_size=10)
        cache.set("key1", {"value": "data1"})
        
        result = cache.get("key1")
        assert result == {"value": "data1"}
        assert cache.stats.hits == 1
        assert cache.stats.misses == 0
    
    def test_cache_miss(self):
        """Get on missing key should return None and increment miss counter."""
        cache = LRUCache(max_size=10)
        result = cache.get("nonexistent")
        
        assert result is None
        assert cache.stats.misses == 1
        assert cache.stats.hits == 0
    
    def test_lru_eviction_by_count(self):
        """Oldest entries should be evicted when size limit reached."""
        cache = LRUCache(max_size=3)
        
        cache.set("key1", {"value": "data1"})
        cache.set("key2", {"value": "data2"})
        cache.set("key3", {"value": "data3"})
        
        # This should evict key1
        cache.set("key4", {"value": "data4"})
        
        assert cache.get("key1") is None  # Evicted
        assert cache.get("key2") is not None
        assert cache.get("key3") is not None
        assert cache.get("key4") is not None
        assert cache.stats.evictions == 1
    
    def test_lru_access_updates_order(self):
        """Accessing an entry should mark it as recently used."""
        cache = LRUCache(max_size=3)
        
        cache.set("key1", {"value": "data1"})
        cache.set("key2", {"value": "data2"})
        cache.set("key3", {"value": "data3"})
        
        # Access key1 to mark it as recently used
        cache.get("key1")
        
        # Add key4, should evict key2 (not key1)
        cache.set("key4", {"value": "data4"})
        
        assert cache.get("key1") is not None  # Still present
        assert cache.get("key2") is None       # Evicted
        assert cache.get("key3") is not None
        assert cache.get("key4") is not None
    
    def test_update_existing_key(self):
        """Updating existing key should not increase size."""
        cache = LRUCache(max_size=2)
        
        cache.set("key1", {"value": "data1"})
        cache.set("key2", {"value": "data2"})
        
        # Update key1
        cache.set("key1", {"value": "updated"})
        
        assert cache.get("key1") == {"value": "updated"}
        assert cache.get("key2") is not None
        assert len(cache._cache) == 2
    
    def test_clear(self):
        """Clear should remove all entries."""
        cache = LRUCache(max_size=10)
        
        cache.set("key1", {"value": "data1"})
        cache.set("key2", {"value": "data2"})
        
        cache.clear()
        
        assert cache.get("key1") is None
        assert cache.get("key2") is None
        assert len(cache._cache) == 0
        assert cache.stats.total_size_bytes == 0
    
    def test_memory_limit_eviction(self):
        """Entries should be evicted when memory limit reached."""
        # Small memory limit
        cache = LRUCache(max_size=100, max_memory_mb=0.001)  # ~1KB
        
        # Add entries until memory limit reached
        for i in range(10):
            cache.set(f"key{i}", {"value": "x" * 200})  # ~200 bytes each
        
        # Memory limit should trigger evictions
        assert cache.stats.evictions > 0
        assert cache.stats.total_size_bytes <= cache.max_memory_bytes


class TestValidationCache:
    """Test validation cache."""
    
    def test_tdfol_cache(self):
        """TDFOL formulas should be cached."""
        cache = ValidationCache(max_size=10)
        
        formulas = ["entity(e1).", "type(e1, Person)."]
        cache.set_tdfol("hash123", formulas)
        
        result = cache.get_tdfol("hash123")
        assert result == formulas
    
    def test_consistency_cache(self):
        """Consistency results should be cached."""
        cache = ValidationCache(max_size=10)
        
        result = {"is_consistent": True, "contradictions": []}
        cache.set_consistency("hash456", result)
        
        cached = cache.get_consistency("hash456")
        assert cached == result
    
    def test_incremental_cache(self):
        """Incremental validation results should be cached."""
        cache = ValidationCache(max_size=10)
        
        entity_ids = ["e1", "e2", "e3"]
        result = {"valid": True, "issues": []}
        cache.set_incremental(entity_ids, result)
        
        cached = cache.get_incremental(entity_ids)
        assert cached == result
    
    def test_incremental_cache_order_independent(self):
        """Incremental cache should be order-independent."""
        cache = ValidationCache(max_size=10)
        
        result = {"valid": True}
        cache.set_incremental(["e1", "e2", "e3"], result)
        
        # Different order, same IDs
        cached = cache.get_incremental(["e3", "e1", "e2"])
        assert cached == result
    
    def test_get_stats(self):
        """Stats should aggregate all cache layers."""
        cache = ValidationCache(max_size=10)
        
        cache.set_tdfol("hash1", ["formula1"])
        cache.get_tdfol("hash1")  # Hit
        cache.get_tdfol("hash2")  # Miss
        
        stats = cache.get_stats()
        assert "tdfol_cache" in stats
        assert "consistency_cache" in stats
        assert "incremental_cache" in stats
        assert stats["tdfol_cache"]["hits"] == 1
        assert stats["tdfol_cache"]["misses"] == 1
    
    def test_clear_all(self):
        """Clear all should clear all cache layers."""
        cache = ValidationCache(max_size=10)
        
        cache.set_tdfol("hash1", ["formula1"])
        cache.set_consistency("hash2", {"result": True})
        cache.set_incremental(["e1"], {"valid": True})
        
        cache.clear_all()
        
        assert cache.get_tdfol("hash1") is None
        assert cache.get_consistency("hash2") is None
        assert cache.get_incremental(["e1"]) is None


class TestCachePersistence:
    """Test cache persistence to disk."""
    
    def test_persistence_disabled_by_default(self, tmp_path):
        """Persistence should be disabled by default."""
        cache = LRUCache(max_size=10, enable_persistence=False)
        cache.set("key1", {"value": "data1"})
        
        # Should not create any files
        del cache
        assert not any(tmp_path.glob("*.json"))
    
    def test_persistence_enabled(self, tmp_path):
        """Cache should persist to disk when enabled."""
        cache_path = tmp_path / "test_cache.json"
        
        cache = LRUCache(
            max_size=10,
            enable_persistence=True,
            persistence_path=cache_path,
        )
        cache.set("key1", {"value": "data1"})
        cache._save_to_disk()
        
        assert cache_path.exists()
        
        # Load in new cache instance
        cache2 = LRUCache(
            max_size=10,
            enable_persistence=True,
            persistence_path=cache_path,
        )
        
        result = cache2.get("key1")
        assert result == {"value": "data1"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
