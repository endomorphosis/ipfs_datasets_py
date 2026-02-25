"""Tests for semantic_deduplicator_cached type contracts.

This module tests the DeduplicatorCacheStatsDict TypedDict contract to ensure
proper type safety for cache statistics from EmbeddingCache and
CachedSemanticEntityDeduplicator.
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.semantic_deduplicator_cached import (
    EmbeddingCache,
    DeduplicatorCacheStatsDict,
    CachedSemanticEntityDeduplicator,
)


class TestDeduplicatorCacheStatsDictType:
    """Tests for DeduplicatorCacheStatsDict TypedDict structure."""
    
    def test_cache_stats_dict_has_correct_fields(self):
        """Verify DeduplicatorCacheStatsDict has expected field names."""
        expected_fields = {"hits", "misses", "hit_rate", "size", "capacity"}
        actual_fields = set(DeduplicatorCacheStatsDict.__annotations__.keys())
        assert actual_fields == expected_fields
    
    def test_cache_stats_dict_field_types(self):
        """Verify DeduplicatorCacheStatsDict field types are correct."""
        annotations = DeduplicatorCacheStatsDict.__annotations__
        assert annotations["hits"] == int
        assert annotations["misses"] == int
        assert annotations["hit_rate"] == float
        assert annotations["size"] == int
        assert annotations["capacity"] == int
    
    def test_cache_stats_dict_optional_fields(self):
        """Verify DeduplicatorCacheStatsDict allows partial population."""
        partial: DeduplicatorCacheStatsDict = {
            "hits": 100,
            "misses": 20,
            "capacity": 1000
        }  # type: ignore
        assert partial["hits"] == 100
        assert partial["misses"] == 20
        assert partial["capacity"] == 1000


class TestEmbeddingCacheIntegration:
    """Integration tests for EmbeddingCache.stats()."""
    
    def test_embedding_cache_stats_returns_typed_dict(self):
        """Verify EmbeddingCache.stats() returns DeduplicatorCacheStatsDict."""
        cache = EmbeddingCache(maxsize=500)
        
        # Perform some cache operations
        cache.get("key1")  # Miss
        cache.put("key1", [0.1, 0.2, 0.3])
        cache.get("key1")  # Hit
        
        result = cache.stats()
        
        # Verify structure matches DeduplicatorCacheStatsDict
        assert "hits" in result
        assert "misses" in result
        assert "hit_rate" in result
        assert "size" in result
        assert "capacity" in result
    
    def test_embedding_cache_stats_field_values(self):
        """Verify EmbeddingCache.stats() returns correct stat values."""
        cache = EmbeddingCache(maxsize=100)
        
        # 2 misses, 0 hits
        cache.get("key1")
        cache.get("key2")
        cache.put("key1", [0.1, 0.2])
        cache.put("key2", [0.3, 0.4])
        
        # 2 hits
        cache.get("key1")
        cache.get("key2")
        
        result = cache.stats()
        
        assert result["hits"] == 2
        assert result["misses"] == 2
        assert result["hit_rate"] == 0.5  # 2/4
        assert result["size"] == 2
        assert result["capacity"] == 100
    
    def test_embedding_cache_stats_zero_requests(self):
        """Verify EmbeddingCache.stats() handles zero requests correctly."""
        cache = EmbeddingCache(maxsize=200)
        
        result = cache.stats()
        
        assert result["hits"] == 0
        assert result["misses"] == 0
        assert result["hit_rate"] == 0.0
        assert result["size"] == 0
        assert result["capacity"] == 200


class TestCachedSemanticDeduplicatorIntegration:
    """Integration tests for CachedSemanticEntityDeduplicator.get_cache_stats()."""
    
    def test_deduplicator_get_cache_stats_returns_typed_dict(self):
        """Verify get_cache_stats() returns DeduplicatorCacheStatsDict."""
        dedup = CachedSemanticEntityDeduplicator(cache_size=500)
        
        result = dedup.get_cache_stats()
        
        # Verify structure matches DeduplicatorCacheStatsDict
        assert "hits" in result
        assert "misses" in result
        assert "hit_rate" in result
        assert "size" in result
        assert "capacity" in result
    
    def test_deduplicator_get_cache_stats_initial_state(self):
        """Verify get_cache_stats() returns correct initial values."""
        dedup = CachedSemanticEntityDeduplicator(cache_size=1000)
        
        result = dedup.get_cache_stats()
        
        assert result["hits"] == 0
        assert result["misses"] == 0
        assert result["hit_rate"] == 0.0
        assert result["size"] == 0
        assert result["capacity"] == 1000


class TestDeduplicatorCacheStatsRealWorldScenarios:
    """Real-world usage scenarios for deduplicator cache stats."""
    
    def test_high_hit_rate_scenario(self):
        """Test scenario with high cache hit rate."""
        cache = EmbeddingCache(maxsize=1000)
        
        # Load cache with embeddings
        for i in range(10):
            cache.put(f"entity_{i}", [float(i)] * 384)
        
        # Many hits, few misses
        for _ in range(100):
            for i in range(10):
                cache.get(f"entity_{i}")
        
        result = cache.stats()
        
        assert result["hits"] > result["misses"]
        assert result["hit_rate"] > 0.9
        assert result["size"] == 10
    
    def test_cache_eviction_scenario(self):
        """Test scenario where cache evicts old entries."""
        cache = EmbeddingCache(maxsize=5)
        
        # Fill cache to capacity
        for i in range(10):
            cache.put(f"entity_{i}", [float(i)] * 384)
        
        result = cache.stats()
        
        # Cache should be at capacity (evicted older entries)
        assert result["size"] == 5
        assert result["capacity"] == 5
    
    def test_mixed_hit_miss_pattern(self):
        """Test scenario with mixed hits and misses."""
        cache = EmbeddingCache(maxsize=100)
        
        # Pattern: miss, set, hit, miss, set, hit
        cache.get("key1")  # miss
        cache.put("key1", [0.1])
        cache.get("key1")  # hit
        cache.get("key2")  # miss
        cache.put("key2", [0.2])
        cache.get("key2")  # hit
        
        result = cache.stats()
        
        assert result["hits"] == 2
        assert result["misses"] == 2
        assert result["hit_rate"] == 0.5


class TestCacheStatsDictStructure:
    """Tests verifying DeduplicatorCacheStatsDict structure compliance."""
    
    def test_cache_stats_dict_from_stats_matches_type(self):
        """Verify dict from stats() matches DeduplicatorCacheStatsDict structure."""
        cache = EmbeddingCache(maxsize=500)
        
        # Perform operations
        cache.get("test")
        cache.put("test", [1.0, 2.0])
        cache.get("test")
        
        result = cache.stats()
        
        # Verify exact field set
        expected_fields = {"hits", "misses", "hit_rate", "size", "capacity"}
        assert set(result.keys()) == expected_fields
        
        # Verify types
        assert isinstance(result["hits"], int)
        assert isinstance(result["misses"], int)
        assert isinstance(result["hit_rate"], float)
        assert isinstance(result["size"], int)
        assert isinstance(result["capacity"], int)
    
    def test_hit_rate_bounds(self):
        """Verify hit_rate is always between 0.0 and 1.0."""
        cache = EmbeddingCache(maxsize=100)
        
        # All misses
        for i in range(5):
            cache.get(f"miss_{i}")
        
        result1 = cache.stats()
        assert 0.0 <= result1["hit_rate"] <= 1.0
        
        # Add some hits
        for i in range(5):
            cache.put(f"miss_{i}", [float(i)])
        for i in range(5):
            cache.get(f"miss_{i}")
        
        result2 = cache.stats()
        assert 0.0 <= result2["hit_rate"] <= 1.0
        assert result2["hit_rate"] == 0.5  # 5 hits, 5 misses
    
    def test_size_never_exceeds_capacity(self):
        """Verify cache size never exceeds capacity."""
        cache = EmbeddingCache(maxsize=10)
        
        # Try to overfill cache
        for i in range(50):
            cache.put(f"entity_{i}", [float(i)])
        
        result = cache.stats()
        
        assert result["size"] <= result["capacity"]
        assert result["size"] == 10  # LRU should have evicted old entries
        assert result["capacity"] == 10


class TestCacheStatsConsistency:
    """Tests for cache statistics consistency."""
    
    def test_hits_plus_misses_equals_total_requests(self):
        """Verify hits + misses = total get() requests."""
        cache = EmbeddingCache(maxsize=50)
        
        # Track requests manually
        request_count = 0
        
        cache.get("key1")  # miss
        request_count += 1
        cache.put("key1", [0.1])
        cache.get("key1")  # hit
        request_count += 1
        cache.get("key2")  # miss
        request_count += 1
        
        result = cache.stats()
        
        assert result["hits"] + result["misses"] == request_count
        assert result["hits"] + result["misses"] == 3
    
    def test_clear_resets_statistics(self):
        """Verify clear() resets statistics to zero."""
        cache = EmbeddingCache(maxsize=100)
        
        # Generate some activity
        for i in range(10):
            cache.put(f"key_{i}", [float(i)])
            cache.get(f"key_{i}")
        
        result_before = cache.stats()
        assert result_before["hits"] > 0
        assert result_before["size"] > 0
        
        # Clear cache
        cache.clear()
        
        result_after = cache.stats()
        assert result_after["hits"] == 0
        assert result_after["misses"] == 0
        assert result_after["size"] == 0
        assert result_after["hit_rate"] == 0.0
    
    def test_capacity_remains_constant(self):
        """Verify capacity doesn't change during operations."""
        initial_capacity = 250
        cache = EmbeddingCache(maxsize=initial_capacity)
        
        # Perform various operations
        for i in range(100):
            cache.put(f"key_{i}", [float(i)])
        for i in range(50):
            cache.get(f"key_{i}")
        
        result = cache.stats()
        
        assert result["capacity"] == initial_capacity


class TestDeduplicatorIntegration:
    """Integration tests combining deduplicator and cache stats."""
    
    def test_deduplicator_cache_stats_after_operations(self):
        """Test cache stats reflect deduplicator operations."""
        dedup = CachedSemanticEntityDeduplicator(cache_size=500)
        
        # Get initial stats
        stats_initial = dedup.get_cache_stats()
        assert stats_initial["size"] == 0
        
        # Note: We can't easily test suggest_merges without mocking embeddings,
        # so we just verify the stats structure is available
        assert "hits" in stats_initial
        assert "misses" in stats_initial
        assert "capacity" in stats_initial
    
    def test_deduplicator_cache_size_configuration(self):
        """Test deduplicator respects cache_size parameter."""
        cache_size = 750
        dedup = CachedSemanticEntityDeduplicator(cache_size=cache_size)
        
        stats = dedup.get_cache_stats()
        
        assert stats["capacity"] == cache_size
