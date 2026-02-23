"""
Cache Invalidation & Consistency Tests - Batch 235 [tests].

Comprehensive test coverage for cache invalidation scenarios across the
optimizer system. Tests ensure proper cache behavior during:
- Refinement cycles
- Concurrent operations
- Domain switches
- Configuration changes
- Memory pressure

Test Coverage:
1. Pattern cache invalidation (regex compilation cache)
2. Similarity score cache consistency (entity deduplication)
3. Domain pattern loader cache coordination
4. Cross-component cache interactions
5. Memory management and cleanup
6. Cache warming and cold-start performance

Reliability Target: 100% cache consistency, zero stale data
"""

import pytest
import time
from typing import List, Dict, Any
from concurrent.futures import ThreadPoolExecutor
import gc

from ipfs_datasets_py.optimizers.common.hotspot_optimization import (
    RegexPatternCache,
    SimilarityScoreCache,
    DomainPatternLoader,
    EntityPair,
    get_pattern_cache,
    get_domain_loader,
)


# ============================================================================
# Tests: Pattern Cache Invalidation
# ============================================================================


class TestPatternCacheInvalidation:
    """Test regex pattern cache invalidation scenarios."""

    def test_pattern_cache_clear_removes_all_entries(self):
        """Test that cache clear removes all cached patterns."""
        cache = RegexPatternCache()
        
        # Add multiple patterns
        patterns = [r"\b[A-Z]+\b", r"\$\d+", r"\w+@\w+\.com"]
        for pattern in patterns:
            cache.get_compiled_pattern(pattern)
        
        # Verify patterns cached
        assert len(cache._cache) == 3
        
        # Clear cache
        cache.clear()
        
        # Verify all removed
        assert len(cache._cache) == 0
        assert cache.cache_stats()["hits"] == 0
        assert cache.cache_stats()["misses"] == 0

    def test_pattern_recompilation_after_clear(self):
        """Test that patterns are recompiled after cache clear."""
        cache = RegexPatternCache()
        pattern = r"\b[A-Z]\w+\b"
        
        # Compile pattern
        p1 = cache.get_compiled_pattern(pattern)
        assert cache.cache_stats()["misses"] == 1
        
        # Get from cache
        p2 = cache.get_compiled_pattern(pattern)
        assert cache.cache_stats()["hits"] == 1
        assert p1 is p2  # Same object
        
        # Clear and recompile
        cache.clear()
        p3 = cache.get_compiled_pattern(pattern)
        
        # Stats should reflect recompilation (new miss after clear)
        # Note: Python's re.compile() may return same object due to internal caching
        assert cache.cache_stats()["misses"] == 1  # New miss after clear
        assert cache.cache_stats()["hits"] == 0  # No hits yet after clear

    def test_pattern_cache_isolation_between_instances(self):
        """Test that separate cache instances are isolated."""
        cache1 = RegexPatternCache()
        cache2 = RegexPatternCache()
        
        # Add pattern to cache1
        cache1.get_compiled_pattern(r"\btest\b")
        
        #Cache2 should be empty
        assert len(cache1._cache) == 1
        assert len(cache2._cache) == 0
        
        # Clear cache1
        cache1.clear()
        
        # Cache2 should be unaffected
        assert len(cache1._cache) == 0
        assert len(cache2._cache) == 0

    def test_global_pattern_cache_singleton_behavior(self):
        """Test global pattern cache singleton invalidation."""
        # Get singleton multiple times
        cache1 = get_pattern_cache()
        cache2 = get_pattern_cache()
        
        # Should be same instance
        assert cache1 is cache2
        
        # Add pattern
        cache1.get_compiled_pattern(r"test")
        
        # Should be visible in cache2
        assert len(cache2._cache) == 1
        
        # Clear via cache2
        cache2.clear()
        
        # Should be cleared in cache1
        assert len(cache1._cache) == 0


# ============================================================================
# Tests: Similarity Score Cache Invalidation
# ============================================================================


class TestSimilarityScoreCacheInvalidation:
    """Test similarity score cache invalidation scenarios."""

    def test_similarity_cache_clear_removes_all_scores(self):
        """Test that cache clear removes all cached scores."""
        cache = SimilarityScoreCache()
        
        # Compute multiple similarities
        pairs = [("A", "B"), ("C", "D"), ("E", "F")]
        for text1, text2 in pairs:
            cache.compute_similarity(text1, text2)
        
        # Verify cached
        assert len(cache._cache) > 0
        
        # Clear cache
        cache.clear()
        
        # Verify all removed
        assert len(cache._cache) == 0
        assert cache.cache_stats()["hits"] == 0
        assert cache.cache_stats()["misses"] == 0

    def test_similarity_recomputation_after_clear(self):
        """Test that similarities are recomputed after cache clear."""
        cache = SimilarityScoreCache()
        
        # Compute similarity
        score1 = cache.compute_similarity("Apple Inc", "Apple Incorporated")
        stats1 = cache.cache_stats()
        
        # Get from cache
        score2 = cache.compute_similarity("Apple Inc", "Apple Incorporated")
        stats2 = cache.cache_stats()
        
        # Should be cached
        assert score1 == score2
        assert stats2["hits"] > stats1["hits"]
        
        # Clear cache
        cache.clear()
        
        # Recompute
        score3 = cache.compute_similarity("Apple Inc", "Apple Incorporated")
        stats3 = cache.cache_stats()
        
        # Should match original but stats reset
        assert score3 == score1
        assert stats3["misses"] == 1
        assert stats3["hits"] == 0

    def test_similarity_cache_consistency_with_entity_updates(self):
        """Test cache consistency when entity names change."""
        cache = SimilarityScoreCache()
        
        # Compute similarity for original entities
        entity1_v1 = "Company Corporation"
        entity2 = "Company LLC"
        score1 = cache.compute_similarity(entity1_v1, entity2)
        
        # Entity name changes (simulated refinement)
        entity1_v2 = "Company Incorporated"
        
        # Score for updated entity should be freshly computed
        score2 = cache.compute_similarity(entity1_v2, entity2)
        
        # Scores should be different (different entity names)
        assert score1 != score2
        
        # Both should be in cache as separate entries
        assert len(cache._cache) >= 2

    def test_similarity_cache_max_size_enforcement(self):
        """Test that cache respects max size and evicts entries."""
        max_size = 10
        cache = SimilarityScoreCache(max_cache_size=max_size)
        
        # Add more entries than max_size
        for i in range(max_size + 5):
            cache.compute_similarity(f"Entity{i}", f"Entity{i+100}")
        
        # Cache should not exceed max_size
        assert len(cache._cache) <= max_size

    def test_entity_pair_hash_consistency(self):
        """Test that EntityPair hashing is consistent."""
        pair1 = EntityPair("A", "B", normalize=True)
        pair2 = EntityPair("a", "b", normalize=True)
        
        # Should have same hash when normalized
        assert hash(pair1) == hash(pair2)
        
        # Should be considered equal
        assert pair1 == pair2


# ============================================================================
# Tests: Domain Pattern Loader Invalidation
# ============================================================================


class TestDomainPatternLoaderInvalidation:
    """Test domain pattern loader cache invalidation."""

    def test_domain_loader_caches_patterns_per_domain(self):
        """Test that domain patterns are cached per domain."""
        loader = DomainPatternLoader()
        
        # Load patterns for different domains
        legal_patterns1, _ = loader.get_domain_patterns("legal")
        medical_patterns1, _ = loader.get_domain_patterns("medical")
        
        # Patterns should be cached
        assert len(loader._loaded_patterns) == 2
        assert "legal" in loader._loaded_patterns
        assert "medical" in loader._loaded_patterns
        
        # Subsequent loads should use cache
        legal_patterns2, _ = loader.get_domain_patterns("legal")
        
        # Should be same patterns (cached)
        assert legal_patterns1[0] is legal_patterns2[0]

    def test_domain_pattern_independence(self):
        """Test that domain patterns are independent."""
        loader = DomainPatternLoader()
        
        # Load multiple domains
        loader.get_domain_patterns("legal")
        loader.get_domain_patterns("medical")
        loader.get_domain_patterns("technical")
        
        # Should have 3 separate cached domain sets
        assert len(loader._loaded_patterns) == 3

    def test_domain_switch_reuses_cache(self):
        """Test switching between domains reuses cached patterns."""
        loader = DomainPatternLoader()
        
        # Load legal domain
        legal1, _ = loader.get_domain_patterns("legal")
        stats1 = loader.cache_stats()
        
        # Switch to medical
        medical, _ = loader.get_domain_patterns("medical")
        
        # Switch back to legal
        legal2, _ = loader.get_domain_patterns("legal")
        stats2 = loader.cache_stats()
        
        # Legal patterns should be cached
        assert legal1[0] is legal2[0]
        
        # Domains loaded count should be 2
        assert stats2["domains_loaded"] == 2

    def test_global_domain_loader_singleton_consistency(self):
        """Test global domain loader singleton cache consistency."""
        loader1 = get_domain_loader()
        loader2 = get_domain_loader()
        
        # Should be same instance
        assert loader1 is loader2
        
        # Load patterns via loader1
        loader1.get_domain_patterns("legal")
        
        # Should be visible in loader2
        assert "legal" in loader2._loaded_patterns


# ============================================================================
# Tests: Cross-Component Cache Interactions
# ============================================================================


class TestCrossComponentCacheInteractions:
    """Test cache interactions across multiple components."""

    def test_pattern_and_domain_caches_independent(self):
        """Test that pattern cache and domain loader are independent."""
        pattern_cache = RegexPatternCache()
        domain_loader = DomainPatternLoader()
        
        # Add to pattern cache
        pattern_cache.get_compiled_pattern(r"test")
        
        # Load domain patterns
        domain_loader.get_domain_patterns("legal")
        
        # Clear pattern cache
        pattern_cache.clear()
        
        # Domain loader should be unaffected
        assert "legal" in domain_loader._loaded_patterns
        
        # Pattern cache should be empty
        assert len(pattern_cache._cache) == 0

    def test_similarity_cache_independent_of_pattern_cache(self):
        """Test that similarity cache is independent of pattern cache."""
        pattern_cache = RegexPatternCache()
        similarity_cache = SimilarityScoreCache()
        
        # Use both caches
        pattern_cache.get_compiled_pattern(r"\w+")
        similarity_cache.compute_similarity("A", "B")
        
        # Clear one
        pattern_cache.clear()
        
        # Other should be unaffected
        assert len(similarity_cache._cache) > 0

    def test_concurrent_cache_operations(self):
        """Test cache consistency under concurrent operations."""
        cache = RegexPatternCache()
        patterns = [r"\btest\d+\b", r"\w+", r"[A-Z]+", r"\$\d+\.?\d*"]
        
        def access_cache(pattern):
            for _ in range(10):
                cache.get_compiled_pattern(pattern)
            return cache.cache_stats()
        
        # Execute concurrent cache accesses
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(access_cache, patterns))
        
        # Cache should be consistent
        assert len(cache._cache) == len(patterns)
        
        # All patterns should be cached
        for pattern in patterns:
            assert pattern in cache._cache or any(
                pattern in key for key in cache._cache.keys()
            )


# ============================================================================
# Tests: Memory Management
# ============================================================================


class TestCacheMemoryManagement:
    """Test cache memory management and cleanup."""

    def test_similarity_cache_respects_memory_limit(self):
        """Test that similarity cache respects memory limits."""
        max_size = 100
        cache = SimilarityScoreCache(max_cache_size=max_size)
        
        # Add many entries
        for i in range(max_size * 2):
            cache.compute_similarity(f"Entity{i}", f"Entity{i+1000}")
        
        # Should not exceed max_size
        assert len(cache._cache) <= max_size

    def test_cache_clear_frees_memory(self):
        """Test that cache clear helps free memory."""
        cache = RegexPatternCache()
        
        # Add many patterns
        for i in range(100):
            cache.get_compiled_pattern(f"pattern_{i}_\\w+")
        
        initial_size = len(cache._cache)
        assert initial_size == 100
        
        # Clear cache
        cache.clear()
        
        # Force garbage collection
        gc.collect()
        
        # Cache should be empty
        assert len(cache._cache) == 0

    def test_large_pattern_cache_behavior(self):
        """Test cache behavior with large pattern sets."""
        cache = RegexPatternCache()
        
        # Add 1000 patterns
        pattern_count = 1000
        for i in range(pattern_count):
            cache.get_compiled_pattern(f"\\bpattern{i}\\b")
        
        # All should be cached
        assert len(cache._cache) == pattern_count
        
        # Stats should be accurate
        stats = cache.cache_stats()
        assert stats["misses"] == pattern_count

    def test_similarity_cache_memory_efficiency(self):
        """Test similarity cache memory efficiency."""
        cache = SimilarityScoreCache(max_cache_size=500)
        
        # Add many similarities
        for i in range(1000):
            cache.compute_similarity(f"Ent{i}", f"Ent{i+1}")
        
        # Cache should be at or below max
        assert len(cache._cache) <= 500


# ============================================================================
# Tests: Cache Warming and Cold Start
# ============================================================================


class TestCacheWarmingAndColdStart:
    """Test cache warming and cold-start scenarios."""

    def test_cold_start_cache_miss_rate(self):
        """Test cache behavior on cold start."""
        cache = RegexPatternCache()
        
        # Initial state - all misses
        patterns = [r"\w+", r"\d+", r"[A-Z]+"]
        for pattern in patterns:
            cache.get_compiled_pattern(pattern)
        
        stats = cache.cache_stats()
        assert stats["misses"] == 3
        assert stats["hits"] == 0

    def test_cache_warming_improves_hit_rate(self):
        """Test that cache warming improves hit rate."""
        cache = RegexPatternCache()
        common_patterns = [r"\b\w+\b", r"\d+", r"[A-Z][a-z]+"]
        
        # Warm cache
        for pattern in common_patterns:
            cache.get_compiled_pattern(pattern)
        
        initial_stats = cache.cache_stats()
        
        # Access patterns again
        for pattern in common_patterns:
            cache.get_compiled_pattern(pattern)
        
        final_stats = cache.cache_stats()
        
        # Hit rate should improve
        assert final_stats["hits"] > initial_stats["hits"]

    def test_domain_loader_lazy_loading_performance(self):
        """Test domain loader lazy loading performance."""
        loader = DomainPatternLoader()
        
        # First load (cold)
        start = time.perf_counter()
        legal1, _ = loader.get_domain_patterns("legal")
        cold_time = time.perf_counter() - start
        
        # Second load (cached)
        start = time.perf_counter()
        legal2, _ = loader.get_domain_patterns("legal")
        cached_time = time.perf_counter() - start
        
        # Cached should be much faster
        assert cached_time < cold_time
        
        # Should be same patterns
        assert legal1[0] is legal2[0]


# ============================================================================
# Tests: Error Recovery and Edge Cases
# ============================================================================


class TestCacheErrorRecovery:
    """Test cache behavior in error scenarios."""

    def test_invalid_pattern_does_not_corrupt_cache(self):
        """Test that invalid patterns don't corrupt cache."""
        cache = RegexPatternCache()
        
        # Add valid pattern
        cache.get_compiled_pattern(r"\w+")
        
        # Try invalid pattern
        try:
            cache.get_compiled_pattern(r"[invalid(")
        except Exception:
            pass  # Expected to fail
        
        # Cache should still have valid pattern
        assert len(cache._cache) == 1
        
        # Valid pattern should still work
        pattern = cache.get_compiled_pattern(r"\w+")
        assert pattern is not None

    def test_cache_recovery_after_clear(self):
        """Test cache recovery after clear operation."""
        cache = SimilarityScoreCache()
        
        # Populate cache
        cache.compute_similarity("A", "B")
        cache.compute_similarity("C", "D")
        
        # Clear
        cache.clear()
        
        # Should be able to rebuild
        score = cache.compute_similarity("A", "B")
        assert 0 <= score <= 1
        assert len(cache._cache) == 1

    def test_concurrent_clear_operations(self):
        """Test cache behavior with concurrent clears."""
        cache = RegexPatternCache()
        
        # Add patterns
        for i in range(10):
            cache.get_compiled_pattern(f"pattern{i}")
        
        def clear_cache():
            cache.clear()
            return len(cache._cache)
        
        # Concurrent clears
        with ThreadPoolExecutor(max_workers=3) as executor:
            results = list(executor.map(lambda _: clear_cache(), range(3)))
        
        # Cache should be empty
        assert len(cache._cache) == 0


# ============================================================================
# Integration Tests
# ============================================================================


class TestCacheIntegration:
    """Integration tests for cache system."""

    def test_full_refinement_cycle_cache_behavior(self):
        """Test cache behavior through full refinement cycle."""
        pattern_cache = RegexPatternCache()
        similarity_cache = SimilarityScoreCache()
        domain_loader = DomainPatternLoader()
        
        # Simulate refinement cycle
        # Step 1: Extract entities (use patterns)
        domain_patterns, _ = domain_loader.get_domain_patterns("legal")
        for pattern in domain_patterns[:3]:
            matches = pattern.findall("Agreement between parties")
        
        # Step 2: Deduplicate entities (use similarity)
        score1 = similarity_cache.compute_similarity("Party A", "Party A Inc")
        score2 = similarity_cache.compute_similarity("Party B", "Party B LLC")
        
        # Step 3: Verify caches populated
        assert len(domain_loader._loaded_patterns) > 0
        assert len(similarity_cache._cache) > 0
        
        # Step 4: Clear for next refinement round
        similarity_cache.clear()
        
        # Step 5: Verify patterns still cached (persistent across rounds)
        assert "legal" in domain_loader._loaded_patterns

    def test_multi_domain_workflow_cache_efficiency(self):
        """Test cache efficiency in multi-domain workflow."""
        domain_loader = DomainPatternLoader()
        
        # Process multiple domains
        domains = ["legal", "medical", "technical", "financial"]
        
        for domain in domains:
            patterns, _ = domain_loader.get_domain_patterns(domain)
            assert len(patterns) > 0
        
        # All domains should be cached
        stats = domain_loader.cache_stats()
        assert stats["domains_loaded"] == len(domains)
        
        # Re-access should be from cache
        for domain in domains:
            patterns, _ = domain_loader.get_domain_patterns(domain)
        
        # No additional loads
        stats = domain_loader.cache_stats()
        assert stats["domains_loaded"] == len(domains)

    def test_cache_coordination_in_batch_processing(self):
        """Test cache coordination during batch processing."""
        pattern_cache = RegexPatternCache()
        similarity_cache = SimilarityScoreCache()
        
        # Simulate batch of 10 ontologies
        for batch_id in range(10):
            # Each ontology uses patterns
            pattern_cache.get_compiled_pattern(r"\b[A-Z]\w+\b")
            
            # Each ontology computes similarities
            similarity_cache.compute_similarity(
                f"Entity{batch_id}_A",
                f"Entity{batch_id}_B"
            )
        
        # Pattern cache should have 1 entry (reused across batch)
        assert len(pattern_cache._cache) == 1
        
        # Similarity cache should have 10 entries (unique pairs)
        assert len(similarity_cache._cache) == 10
        
        # High hit rate for patterns
        pattern_stats = pattern_cache.cache_stats()
        assert pattern_stats["hits"] >= 9  # 9 cache hits after first miss
