"""
Tests for Hotspot Optimization Strategies - Batch 234 Part 3.

Comprehensive test coverage for regex caching, similarity caching, and
domain pattern optimization. Verifies correctness and measures speedups.

Test Coverage:
1. RegexPatternCache - Pattern compilation caching
2. SimilarityScoreCache - Entity similarity memoization
3. DomainPatternLoader - Lazy-loaded domain patterns
4. OptimizationBenchmark - Performance measurement
"""

import pytest
import time

from ipfs_datasets_py.optimizers.common.hotspot_optimization import (
    RegexPatternCache,
    SimilarityScoreCache,
    EntityPair,
    DomainPatternLoader,
    OptimizationBenchmark,
    get_pattern_cache,
    get_domain_loader,
    memoized_with_cache_stats,
)


# ============================================================================
# Tests: RegexPatternCache
# ============================================================================


class TestRegexPatternCache:
    """Test regex pattern caching functionality."""

    def test_pattern_compilation_caching(self):
        """Test that patterns are compiled once and reused."""
        cache = RegexPatternCache()
        pattern_str = r"\b[A-Z][a-z]+\b"
        
        # First call - compiles pattern
        pattern1 = cache.get_compiled_pattern(pattern_str)
        assert pattern1 is not None
        
        # Second call - returns cached pattern
        pattern2 = cache.get_compiled_pattern(pattern_str)
        
        # Should be same object (not just equal)
        assert pattern1 is pattern2
        
        # Stats should reflect one miss and one hit
        stats = cache.cache_stats()
        assert stats["misses"] >= 1
        assert stats["hits"] >= 1

    def test_pattern_cache_key_independence(self):
        """Test that different cache keys don't interfere."""
        cache = RegexPatternCache()
        pattern_str = r"\$[0-9]+"
        
        # Same pattern, different keys
        pattern1 = cache.get_compiled_pattern(pattern_str, cache_key="price")
        pattern2 = cache.get_compiled_pattern(pattern_str, cache_key="amount")
        
        # Both should work independently
        assert pattern1.search("Price: $100")
        assert pattern2.search("Amount: $50")

    def test_multiple_patterns_compilation(self):
        """Test batch pattern compilation."""
        cache = RegexPatternCache()
        patterns = [
            (r"\b[A-Z][a-z]+\b", "name"),
            (r"\$[0-9,]+", "amount"),
            (r"\b(?:agreement|contract)\b", "legal_term"),
        ]
        
        # Compile all patterns
        compiled = cache.get_compiled_patterns(patterns)
        
        assert len(compiled) == 3
        for compiled_pattern, label in compiled:
            assert compiled_pattern is not None
            assert label in ["name", "amount", "legal_term"]

    def test_pattern_cache_statistics(self):
        """Test cache statistics tracking."""
        cache = RegexPatternCache()
        
        # Initial state
        assert cache.cache_stats()["hits"] == 0
        assert cache.cache_stats()["misses"] == 0
        
        # Multiple accesses
        pattern = r"\b\w+\b"
        cache.get_compiled_pattern(pattern)  # Miss
        cache.get_compiled_pattern(pattern)  # Hit
        cache.get_compiled_pattern(pattern)  # Hit
        
        stats = cache.cache_stats()
        assert stats["misses"] >= 1
        assert stats["hits"] >= 2

    def test_pattern_cache_clear(self):
        """Test clearing cache."""
        cache = RegexPatternCache()
        pattern = r"\w+"
        
        # Cache pattern
        cache.get_compiled_pattern(pattern)
        assert cache.cache_stats()["misses"] > 0
        
        # Clear
        cache.clear()
        
        # Stats reset
        assert cache.cache_stats()["misses"] == 0
        assert cache.cache_stats()["hits"] == 0

    def test_pattern_matching_functionality(self):
        """Test that cached patterns work correctly in matching."""
        cache = RegexPatternCache()
        
        # Complex patterns that would benefit from caching
        patterns_and_tests = [
            (r"\b[A-Z]+\b", ("HELLO world", ["HELLO"])),
            (r"\$\d+\.?\d*", ("Price $99.99", ["$99.99"])),
            (r"(agreement|contract)", ("This contract is binding", ["contract"])),
        ]
        
        for pattern_str, (text, expected_matches) in patterns_and_tests:
            compiled = cache.get_compiled_pattern(pattern_str)
            matches = compiled.findall(text)
            
            # Verify pattern works
            assert len(matches) > 0


# ============================================================================
# Tests: SimilarityScoreCache
# ============================================================================


class TestSimilarityScoreCache:
    """Test entity similarity score caching."""

    def test_similarity_exact_match(self):
        """Test similarity computation for exact matches."""
        cache = SimilarityScoreCache()
        
        score = cache.compute_similarity("Company Inc", "Company Inc")
        assert score == 1.0

    def test_similarity_containment(self):
        """Test similarity when one string contains the other."""
        cache = SimilarityScoreCache()
        
        score = cache.compute_similarity("Apple", "Apple Inc")
        assert score >= 0.8  # Should be high but not perfect

    def test_similarity_caching_behavior(self):
        """Test that similarity scores are cached."""
        cache = SimilarityScoreCache()
        
        # Compute once
        score1 = cache.compute_similarity("Entity A", "Entity B")
        stats1 = cache.cache_stats()
        
        # Compute same pair again
        score2 = cache.compute_similarity("Entity A", "Entity B")
        stats2 = cache.cache_stats()
        
        # Should be identical
        assert score1 == score2
        
        # Hit count should increase
        assert stats2["hits"] > stats1["hits"]

    def test_entity_pair_hash_commutative(self):
        """Test that EntityPair hash is commutative (order doesn't matter)."""
        pair1 = EntityPair("A", "B")
        pair2 = EntityPair("B", "A")
        
        # Hashes should be same (commutative)
        assert hash(pair1) == hash(pair2)

    def test_entity_pair_normalization(self):
        """Test entity pair normalization."""
        pair1 = EntityPair("Company Inc", "company inc", normalize=True)
        pair2 = EntityPair("COMPANY INC", "company inc", normalize=True)
        
        # Should be considered equal when normalized
        assert pair1 == pair2

    def test_similarity_cache_max_size(self):
        """Test that cache respects maximum size limit."""
        cache = SimilarityScoreCache(max_cache_size=10)
        
        # Add more than max_cache_size entries
        for i in range(20):
            cache.compute_similarity(f"entity_{i}", f"entity_{i+100}")
        
        # Cache size should not exceed max
        assert len(cache._cache) <= 10

    def test_similarity_cache_statistics(self):
        """Test similarity cache statistics."""
        cache = SimilarityScoreCache()
        
        # Initial state
        assert cache.cache_stats()["hits"] == 0
        assert cache.cache_stats()["misses"] == 0
        
        # Multiple computations
        cache.compute_similarity("A", "B")  # Miss
        cache.compute_similarity("A", "B")  # Hit
        cache.compute_similarity("C", "D")  # Miss
        cache.compute_similarity("C", "D")  # Hit
        
        stats = cache.cache_stats()
        assert stats["misses"] >= 2
        assert stats["hits"] >= 2

    def test_similarity_cache_clear(self):
        """Test clearing similarity cache."""
        cache = SimilarityScoreCache()
        
        # Add some scores
        cache.compute_similarity("A", "B")
        cache.compute_similarity("C", "D")
        
        assert len(cache._cache) > 0
        
        # Clear
        cache.clear()
        
        assert len(cache._cache) == 0
        assert cache.cache_stats()["hits"] == 0
        assert cache.cache_stats()["misses"] == 0


# ============================================================================
# Tests: DomainPatternLoader
# ============================================================================


class TestDomainPatternLoader:
    """Test lazy-loaded domain pattern loading."""

    def test_legal_patterns_loaded(self):
        """Test that legal domain patterns load correctly."""
        loader = DomainPatternLoader()
        patterns, labels = loader.get_domain_patterns("legal")
        
        assert len(patterns) > 0
        assert len(labels) == len(patterns)

    def test_medical_patterns_loaded(self):
        """Test that medical domain patterns load correctly."""
        loader = DomainPatternLoader()
        patterns, labels = loader.get_domain_patterns("medical")
        
        assert len(patterns) > 0
        # Medical patterns should find medical terms
        has_matches = any(
            pattern.search("patient diagnosis treatment") for pattern in patterns
        )
        assert has_matches

    def test_technical_patterns_loaded(self):
        """Test that technical domain patterns load correctly."""
        loader = DomainPatternLoader()
        patterns, labels = loader.get_domain_patterns("technical")
        
        assert len(patterns) > 0
        # Technical patterns should find API endpoints
        has_matches = any(
            pattern.search("GET /api/endpoint") for pattern in patterns
        )
        assert has_matches

    def test_financial_patterns_loaded(self):
        """Test that financial domain patterns load correctly."""
        loader = DomainPatternLoader()
        patterns, labels = loader.get_domain_patterns("financial")
        
        assert len(patterns) > 0
        # Financial patterns should find money amounts
        has_matches = any(
            pattern.search("$1,000.00") for pattern in patterns
        )
        assert has_matches

    def test_domain_pattern_caching(self):
        """Test that domain patterns are cached after first load."""
        loader = DomainPatternLoader()
        
        # First load
        patterns1, _ = loader.get_domain_patterns("legal")
        
        # Second load (should be from cache)
        patterns2, _ = loader.get_domain_patterns("legal")
        
        # Should be same objects
        assert patterns1[0] is patterns2[0]  # Same compiled pattern

    def test_unknown_domain_returns_empty(self):
        """Test that unknown domain returns empty patterns."""
        loader = DomainPatternLoader()
        patterns, labels = loader.get_domain_patterns("unknown_domain")
        
        assert len(patterns) == 0
        assert len(labels) == 0

    def test_domain_loader_cache_stats(self):
        """Test domain loader cache statistics."""
        loader = DomainPatternLoader()
        
        # Load some domains
        loader.get_domain_patterns("legal")
        loader.get_domain_patterns("medical")
        
        stats = loader.cache_stats()
        assert "pattern_cache" in stats
        assert "domains_loaded" in stats
        assert stats["domains_loaded"] == 2

    def test_patterns_match_expected_content(self):
        """Test that domain patterns match expected content types."""
        loader = DomainPatternLoader()
        
        # Test legal patterns against legal text
        legal_patterns, _ = loader.get_domain_patterns("legal")
        legal_text = "Agreement between parties regarding liability and warranty"
        legal_matches = sum(
            1 for p in legal_patterns if p.search(legal_text)
        )
        assert legal_matches > 0
        
        # Test medical patterns against medical text
        medical_patterns, _ = loader.get_domain_patterns("medical")
        medical_text = "Patient admitted with diagnosis of infection requiring treatment"
        medical_matches = sum(
            1 for p in medical_patterns if p.search(medical_text)
        )
        assert medical_matches > 0


# ============================================================================
# Tests: Memoization Decorator
# ============================================================================


class TestMemoizationDecorator:
    """Test memoization decorator with cache statistics."""

    def test_memoized_function_caching(self):
        """Test that memoized function caches results."""
        call_count = 0
        
        @memoized_with_cache_stats
        def expensive_computation(x):
            nonlocal call_count
            call_count += 1
            return x ** 2
        
        # First call - computed
        result1 = expensive_computation(5)
        assert result1 == 25
        assert call_count == 1
        
        # Second call - cached
        result2 = expensive_computation(5)
        assert result2 == 25
        assert call_count == 1  # Should not increment
        
        # Different argument
        result3 = expensive_computation(10)
        assert result3 == 100
        assert call_count == 2

    def test_memoized_cache_info(self):
        """Test that memoized function exposes cache_info."""
        @memoized_with_cache_stats
        def func(x):
            return x * 2
        
        # Should have cache_info method
        assert hasattr(func, "cache_info")
        assert callable(func.cache_info)
        
        # Call function to populate cache
        func(5)
        func(5)
        func(10)
        
        # Check cache info
        info = func.cache_info()
        assert info.hits > 0
        assert info.misses > 0
        assert info.currsize > 0

    def test_memoized_cache_clear(self):
        """Test that memoized function cache can be cleared."""
        @memoized_with_cache_stats
        def func(x):
            return x + 1
        
        # Populate cache
        func(5)
        func(10)
        
        info_before = func.cache_info()
        assert info_before.currsize > 0
        
        # Clear cache
        func.cache_clear()
        
        info_after = func.cache_info()
        assert info_after.currsize == 0


# ============================================================================
# Tests: Optimization Benchmarks
# ============================================================================


class TestOptimizationBenchmark:
    """Test performance benchmark comparisons."""

    def test_pattern_caching_benchmark(self):
        """Test regex pattern caching speedup measurement."""
        result = OptimizationBenchmark.benchmark_pattern_caching(iterations=1000)
        
        assert "cached_sec" in result
        assert "uncached_sec" in result
        assert "speedup_percent" in result
        
        # Cached should be faster
        assert result["cached_sec"] < result["uncached_sec"]
        
        # Should have positive speedup
        assert result["speedup_percent"] > 0

    def test_similarity_caching_benchmark(self):
        """Test similarity score caching speedup measurement."""
        result = OptimizationBenchmark.benchmark_similarity_caching(iterations=500)
        
        assert "cached_sec" in result
        assert "uncached_sec" in result
        assert "speedup_percent" in result
        
        # Speedup should be non-negative (could be 0 for small operations)
        assert result["speedup_percent"] >= 0

    def test_benchmark_results_reasonable(self):
        """Test that benchmark results are reasonable."""
        pattern_result = OptimizationBenchmark.benchmark_pattern_caching(iterations=100)
        
        # Execution times should be positive
        assert pattern_result["cached_sec"] > 0
        assert pattern_result["uncached_sec"] > 0
        
        # Speedup should be between 0-100%
        assert 0 <= pattern_result["speedup_percent"] <= 100


# ============================================================================
# Tests: Global Singletons
# ============================================================================


class TestGlobalSingletons:
    """Test global cache instances."""

    def test_global_pattern_cache_singleton(self):
        """Test that get_pattern_cache returns singleton."""
        cache1 = get_pattern_cache()
        cache2 = get_pattern_cache()
        
        # Should be same instance
        assert cache1 is cache2

    def test_global_domain_loader_singleton(self):
        """Test that get_domain_loader returns singleton."""
        loader1 = get_domain_loader()
        loader2 = get_domain_loader()
        
        # Should be same instance
        assert loader1 is loader2

    def test_singleton_state_persistence(self):
        """Test that singleton state persists across calls."""
        cache = get_pattern_cache()
        
        # Add a pattern
        cache.get_compiled_pattern(r"\test\b", cache_key="test_pattern")
        
        # Retrieve singleton again
        cache2 = get_pattern_cache()
        
        # Should have the cached pattern
        assert "test_pattern" in cache2._cache


# ============================================================================
# Integration Tests
# ============================================================================


class TestOptimizationIntegration:
    """Integration tests combining multiple optimizations."""

    def test_combined_caching_workflow(self):
        """Test workflow using multiple cache types together."""
        pattern_cache = RegexPatternCache()
        similarity_cache = SimilarityScoreCache()
        domain_loader = DomainPatternLoader()
        
        # Step 1: Load domain patterns
        domain_patterns, _ = domain_loader.get_domain_patterns("legal")
        assert len(domain_patterns) > 0
        
        # Step 2: Compile custom patterns
        custom_pattern = pattern_cache.get_compiled_pattern(r"\b\w+\b")
        assert custom_pattern is not None
        
        # Step 3: Compare entities using cached similarity
        score1 = similarity_cache.compute_similarity("Company A", "Company A Inc")
        score2 = similarity_cache.compute_similarity("Company A", "Company A Inc")
        
        # Should retrieve from cache
        stats = similarity_cache.cache_stats()
        assert stats["hits"] > 0
        
        # Results should be consistent
        assert score1 == score2

    def test_optimization_performance_measurement(self):
        """Test complete optimization performance measurement."""
        # Measure pattern caching speedup
        pattern_speedup = OptimizationBenchmark.benchmark_pattern_caching(
            iterations=500
        )
        
        # Measure similarity caching speedup
        similarity_speedup = OptimizationBenchmark.benchmark_similarity_caching(
            iterations=300
        )
        
        # Both should show non-negative improvements
        assert pattern_speedup["speedup_percent"] >= 0
        assert similarity_speedup["speedup_percent"] >= 0
        
        # Combined speedup estimate
        combined = (
            pattern_speedup["speedup_percent"] +
            similarity_speedup["speedup_percent"]
        ) / 2
        
        # Log results
        logger = __import__("logging").getLogger(__name__)
        logger.info(
            f"Pattern cache speedup: {pattern_speedup['speedup_percent']:.1f}%"
        )
        logger.info(
            f"Similarity cache speedup: {similarity_speedup['speedup_percent']:.1f}%"
        )
        logger.info(f"Combined speedup: {combined:.1f}%")
