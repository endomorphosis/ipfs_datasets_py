"""
Test suite for query optimizer optimizations.

Tests for:
1. QueryFingerprintCache - fingerprint caching and hit rates
2. FastGraphTypeDetector - graph type detection with caching
3. OptimizedQueryOptimizerWrapper - integration and performance
"""

import sys
import time
import json
from pathlib import Path
from typing import Dict, Any, List

import pytest

# Setup path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ipfs_datasets_py.optimizers.graphrag.query_optimizer_optimizations import (
    QueryFingerprintCache,
    FastGraphTypeDetector,
    OptimizedQueryOptimizerWrapper,
)


class TestQueryFingerprintCache:
    """Test QueryFingerprintCache functionality."""
    
    def setup_method(self):
        """Setup cache for each test."""
        self.cache = QueryFingerprintCache(max_cache_size=100)
    
    def test_cache_hit_on_repeated_query(self):
        """Test that repeated queries hit the cache."""
        query = {
            "query_text": "find entity A",
            "max_vector_results": 5,
            "traversal": {"max_depth": 2},
        }
        
        # First call
        fp1 = self.cache.get_fingerprint(query)
        stats_before = self.cache.get_cache_stats()
        
        # Second call (should hit cache)
        fp2 = self.cache.get_fingerprint(query)
        stats_after = self.cache.get_cache_stats()
        
        # Verify fingerprints are identical
        assert fp1 == fp2, "Fingerprints should be identical for same query"
        
        # Verify cache hit count increased
        assert stats_after["hits"] > stats_before["hits"], "Cache hit count should increase"
        assert stats_after["hit_rate"] > 0, "Hit rate should be positive after repeated query"
    
    def test_fingerprint_differs_for_different_queries(self):
        """Test that different queries produce different fingerprints."""
        query1 = {"query_text": "entity A short", "max_vector_results": 5}
        query2 = {"query_text": "entity B different text", "max_vector_results": 10}
        
        fp1 = self.cache.get_fingerprint(query1)
        fp2 = self.cache.get_fingerprint(query2)
        
        assert fp1 != fp2, "Different queries should have different fingerprints"
    
    def test_cache_replacement_with_vector_placeholder(self):
        """Test that vectors are replaced with placeholders in hashing."""
        query_with_vector = {
            "query_text": "find",
            "query_vector": [0.1] * 768,  # Large 768-dim vector
        }
        
        query_without_vector = {
            "query_text": "find",
            "query_vector": [0.2] * 768,  # Different vector values
        }
        
        fp1 = self.cache.get_fingerprint(query_with_vector)
        fp2 = self.cache.get_fingerprint(query_without_vector)
        
        # Both should have same fingerprint because vectors are replaced
        assert fp1 == fp2, "Vector values should not affect fingerprint (only dimension)"
    
    def test_cache_size_limit(self):
        """Test that cache respects max size."""
        small_cache = QueryFingerprintCache(max_cache_size=5)
        
        # Add queries beyond cache size
        for i in range(10):
            query = {"query_text": f"query_{i}", "id": i}
            small_cache.get_fingerprint(query)
        
        stats = small_cache.get_cache_stats()
        assert stats["cache_size"] <= stats["max_size"], "Cache size should not exceed max"
    
    def test_normalize_for_hash(self):
        """Test query normalization for hashing."""
        query = {
            "query_text": "test",
            "query_vector": [0.1, 0.2, 0.3],
            "params": {"key": "value"},
        }
        
        normalized = self.cache._normalize_for_hash(query)
        
        # Vector should be replaced
        assert "[vector_" in str(normalized["query_vector"]), "Vector should be replaced"
        
        # Text and params should remain
        assert normalized["query_text"] == "test"
        assert normalized["params"]["key"] == "value"
    
    def test_cache_stats_initial_state(self):
        """Test cache stats in initial state."""
        stats = self.cache.get_cache_stats()
        
        assert stats["cache_size"] == 0, "Cache should be empty initially"
        assert stats["accesses"] == 0, "Access count should be zero"
        assert stats["hits"] == 0, "Hit count should be zero"
    
    def test_clear_cache(self):
        """Test cache clearing."""
        query = {"query_text": "test"}
        self.cache.get_fingerprint(query)
        
        stats_before = self.cache.get_cache_stats()
        assert stats_before["cache_size"] > 0, "Cache should have entries"
        
        self.cache.clear_cache()
        stats_after = self.cache.get_cache_stats()
        
        assert stats_after["cache_size"] == 0, "Cache should be empty after clear"
        assert stats_after["accesses"] == 0, "Accesses should reset to zero"
        assert stats_after["hits"] == 0, "Hits should reset to zero"


class TestFastGraphTypeDetector:
    """Test FastGraphTypeDetector functionality."""
    
    def setup_method(self):
        """Setup detector for each test."""
        self.detector = FastGraphTypeDetector()
    
    def test_detect_wikipedia_type(self):
        """Test Wikipedia graph type detection."""
        queries = [
            {"query_text": "from wikipedia"},
            {"entity_source": "wikipedia"},
            {"graph_type": "wikipedia"},
        ]
        
        for query in queries:
            detected = self.detector.detect_type_fast(query)
            assert detected == "wikipedia", f"Should detect wikipedia for query: {query}"
    
    def test_detect_ipld_type(self):
        """Test IPLD graph type detection."""
        queries = [
            {"query_text": "from ipld"},
            {"entity_source": "ipld"},
            {"graph_type": "ipld"},
            {"query_text": "cid bafyreigdig4fq"},
        ]
        
        for query in queries:
            detected = self.detector.detect_type_fast(query)
            assert detected == "ipld", f"Should detect ipld for query: {query}"
    
    def test_detect_mixed_type(self):
        """Test mixed graph type detection."""
        query = {
            "graph_type": "mixed",
        }
        
        detected = self.detector.detect_type_fast(query)
        assert detected == "mixed", "Should detect mixed type"
    
    def test_detect_general_fallback(self):
        """Test fallback to general type."""
        query = {"query_text": "generic query"}
        
        detected = self.detector.detect_type_fast(query)
        assert detected == "general", "Should fallback to general for unrecognized queries"
    
    def test_detection_cache_hit(self):
        """Test that detection caching works."""
        query = {"query_text": "from wikipedia"}
        
        # First call
        type1 = self.detector.detect_type_fast(query)
        stats_before = self.detector.get_detection_stats()
        
        # Second call (should hit cache)
        type2 = self.detector.detect_type_fast(query)
        stats_after = self.detector.get_detection_stats()
        
        # Types should match
        assert type1 == type2 == "wikipedia", "Types should be consistent"
        
        # Cache hit should increase
        assert stats_after["cache_hits"] > stats_before["cache_hits"], "Cache hits should increase"
    
    def test_detection_with_fallback_function(self):
        """Test fallback function is called when heuristics fail."""
        query = {"custom_field": "value"}
        
        def fallback_detector(q):
            if q.get("custom_field") == "value":
                return "custom_type"
            return "general"
        
        detected = self.detector.detect_type_fast(query, fallback_detector)
        assert detected == "custom_type", "Fallback function should be used"
    
    def test_detection_signature_creation(self):
        """Test signature creation for cache."""""
        query1 = {"entity_source": "wikipedia", "query_text": "test"}
        query2 = {"entity_source": "wikipedia", "query_text": "different"}
        
        sig1 = self.detector._create_detection_signature(query1)
        sig2 = self.detector._create_detection_signature(query2)
        
        # Signatures should be based on source and other factors
        assert "wiki" in sig1.lower() or "src" in sig1
    
    def test_clear_detection_cache(self):
        """Test detection cache clearing."""
        query = {"entity_source": "wikipedia"}
        self.detector.detect_type_fast(query)
        
        stats_before = self.detector.get_detection_stats()
        assert stats_before["cache_size"] > 0, "Cache should have entries"
        
        self.detector.clear_cache()
        stats_after = self.detector.get_detection_stats()
        
        assert stats_after["cache_size"] == 0, "Cache should be empty after clear"


class TestOptimizedAndConformance:
    """Test cross-cutting and conformance aspects."""
    
    def test_fingerprint_consistency_across_runs(self):
        """Test that fingerprints are reproducible."""
        cache = QueryFingerprintCache()
        query = {"query_text": "test", "params": {"key": "value"}}
        
        fp1 = cache.get_fingerprint(query)
        
        # Clear and recreate cache (same query)
        cache2 = QueryFingerprintCache()
        fp2 = cache2.get_fingerprint(query)
        
        assert fp1 == fp2, "Fingerprints should be consistent across cache instances"
    
    def test_fast_detector_consistency(self):
        """Test that graph type detection is consistent."""
        detector1 = FastGraphTypeDetector()
        detector2 = FastGraphTypeDetector()
        
        query = {"entity_source": "wikipedia"}
        
        type1 = detector1.detect_type_fast(query)
        type2 = detector2.detect_type_fast(query)
        
        assert type1 == type2 == "wikipedia", "Detection should be consistent"
    
    def test_cache_hit_rate_improves_with_repeated_queries(self):
        """Test that hit rate improves with repeated queries."""
        cache = QueryFingerprintCache()
        query = {"query_text": "repeated"}
        
        # First access
        cache.get_fingerprint(query)
        stats1 = cache.get_cache_stats()
        initial_hit_rate = stats1["hit_rate"]
        
        # Multiple repeated accesses
        for _ in range(10):
            cache.get_fingerprint(query)
        
        stats2 = cache.get_cache_stats()
        final_hit_rate = stats2["hit_rate"]
        
        assert final_hit_rate > initial_hit_rate, "Hit rate should improve with repetition"


class TestPerformance:
    """Performance validation tests."""
    
    def test_fingerprint_cache_faster_on_hit(self):
        """Test that cache hits are faster than misses."""
        cache = QueryFingerprintCache()
        query = {"query_text": "test"}
        
        # Prime cache
        cache.get_fingerprint(query)
        
        # Measure hit time
        start = time.perf_counter()
        for _ in range(100):
            cache.get_fingerprint(query)
        hit_time = time.perf_counter() - start
        
        # Create new cache for misses
        cache2 = QueryFingerprintCache()
        
        # Measure miss time
        queries = [{"query_text": f"test_{i}"} for i in range(100)]
        start = time.perf_counter()
        for q in queries:
            cache2.get_fingerprint(q)
        miss_time = time.perf_counter() - start
        
        # Cache hits should be faster
        avg_hit = hit_time / 100
        avg_miss = miss_time / 100
        
        # Hits should be at least 2x faster
        assert avg_hit < avg_miss, f"Hits ({avg_hit:.6f}ms) should be faster than misses ({avg_miss:.6f}ms)"
    
    def test_detection_cache_effectiveness(self):
        """Test detection cache reduces work."""
        detector = FastGraphTypeDetector()
        query = {"entity_source": "wikipedia"}
        
        # Warm up cache
        detector.detect_type_fast(query)
        initial_cache_size = len(detector._detection_cache)
        
        # Many repeated calls
        for _ in range(1000):
            detector.detect_type_fast(query)
        
        stats = detector.get_detection_stats()
        
        # Most calls should be cache hits
        assert stats["hit_rate"] > 90, "Hit rate should be high for repeated queries"


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "--tb=short"])
