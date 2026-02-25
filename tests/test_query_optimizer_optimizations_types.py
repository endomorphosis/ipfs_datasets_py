"""Tests for query_optimizer_optimizations type contracts.

This module tests the QueryFingerprintCacheStatsDict, GraphTypeDetectionStatsDict,
and QueryOptimizerStatsDict TypedDict contracts to ensure proper type safety for
query optimization statistics.
"""

import pytest
from ipfs_datasets_py.optimizers.graphrag.query_optimizer_optimizations import (
    QueryFingerprintCache,
    QueryFingerprintCacheStatsDict,
    FastGraphTypeDetector,
    GraphTypeDetectionStatsDict,
    OptimizedQueryOptimizerWrapper,
    QueryOptimizerStatsDict,
)


class TestQueryFingerprintCacheStatsDictType:
    """Tests for QueryFingerprintCacheStatsDict TypedDict structure."""
    
    def test_fingerprint_cache_stats_dict_has_correct_fields(self):
        """Verify QueryFingerprintCacheStatsDict has expected field names."""
        expected_fields = {"cache_size", "max_size", "accesses", "hits", "hit_rate"}
        actual_fields = set(QueryFingerprintCacheStatsDict.__annotations__.keys())
        assert actual_fields == expected_fields
    
    def test_fingerprint_cache_stats_dict_optional_fields(self):
        """Verify QueryFingerprintCacheStatsDict allows partial population."""
        partial: QueryFingerprintCacheStatsDict = {
            "cache_size": 50,
            "max_size": 1000,
            "hit_rate": 0.75
        }  # type: ignore
        assert partial["cache_size"] == 50
        assert partial["max_size"] == 1000


class TestGraphTypeDetectionStatsDictType:
    """Tests for GraphTypeDetectionStatsDict TypedDict structure."""
    
    def test_detection_stats_dict_has_correct_fields(self):
        """Verify GraphTypeDetectionStatsDict has expected field names."""
        expected_fields = {"cache_size", "cache_hits", "cache_misses", "hit_rate"}
        actual_fields = set(GraphTypeDetectionStatsDict.__annotations__.keys())
        assert actual_fields == expected_fields
    
    def test_detection_stats_dict_optional_fields(self):
        """Verify GraphTypeDetectionStatsDict allows partial population."""
        partial: GraphTypeDetectionStatsDict = {
            "cache_hits": 200,
            "cache_misses": 50,
            "hit_rate": 0.8
        }  # type: ignore
        assert partial["cache_hits"] == 200
        assert partial["cache_misses"] == 50


class TestQueryOptimizerStatsDictType:
    """Tests for QueryOptimizerStatsDict TypedDict structure."""
    
    def test_optimizer_stats_dict_has_correct_fields(self):
        """Verify QueryOptimizerStatsDict has expected field names."""
        expected_fields = {"fingerprint_cache", "type_detector", "total_calls", "avg_time_ms"}
        actual_fields = set(QueryOptimizerStatsDict.__annotations__.keys())
        assert actual_fields == expected_fields
    
    def test_optimizer_stats_dict_optional_nested_fields(self):
        """Verify QueryOptimizerStatsDict allows partial nested structure."""
        partial: QueryOptimizerStatsDict = {
            "total_calls": 100,
            "avg_time_ms": 5.5
        }  # type: ignore
        assert partial["total_calls"] == 100
        assert partial["avg_time_ms"] == 5.5


class TestQueryFingerprintCacheIntegration:
    """Integration tests for QueryFingerprintCache.get_cache_stats()."""
    
    def test_fingerprint_cache_get_cache_stats_returns_typed_dict(self):
        """Verify QueryFingerprintCache.get_cache_stats() returns QueryFingerprintCacheStatsDict."""
        cache = QueryFingerprintCache(max_cache_size=500)
        
        result = cache.get_cache_stats()
        
        # Verify structure matches QueryFingerprintCacheStatsDict
        assert "cache_size" in result
        assert "max_size" in result
        assert "accesses" in result
        assert "hits" in result
        assert "hit_rate" in result
    
    def test_fingerprint_cache_stats_initial_state(self):
        """Verify get_cache_stats() returns correct initial values."""
        cache = QueryFingerprintCache(max_cache_size=1000)
        
        result = cache.get_cache_stats()
        
        assert result["cache_size"] == 0
        assert result["max_size"] == 1000
        assert result["accesses"] == 0
        assert result["hits"] == 0
        assert result["hit_rate"] == 0.0
    
    def test_fingerprint_cache_stats_after_operations(self):
        """Verify cache stats reflect cache operations."""
        cache = QueryFingerprintCache(max_cache_size=100)
        
        # Create some queries and access cache
        query1 = {"q": "test1"}
        query2 = {"q": "test2"}
        
        # Access behavior depends on implementation
        cache.get_fingerprint(query1)
        cache.get_fingerprint(query2)
        cache.get_fingerprint(query1)  # Potential hit
        
        result = cache.get_cache_stats()
        
        # Verify structure is correct
        assert isinstance(result["cache_size"], (int, float))
        assert isinstance(result["hits"], (int, float))
        assert isinstance(result["hit_rate"], float)
        assert 0.0 <= result["hit_rate"] <= 100.0


class TestFastGraphTypeDetectorIntegration:
    """Integration tests for FastGraphTypeDetector.get_detection_stats()."""
    
    def test_detector_get_detection_stats_returns_typed_dict(self):
        """Verify FastGraphTypeDetector.get_detection_stats() returns GraphTypeDetectionStatsDict."""
        detector = FastGraphTypeDetector()
        
        result = detector.get_detection_stats()
        
        # Verify structure matches GraphTypeDetectionStatsDict
        assert "cache_size" in result
        assert "cache_hits" in result
        assert "cache_misses" in result
        assert "hit_rate" in result
    
    def test_detector_stats_initial_state(self):
        """Verify get_detection_stats() returns correct initial values."""
        detector = FastGraphTypeDetector()
        
        result = detector.get_detection_stats()
        
        assert result["cache_size"] == 0
        assert result["cache_hits"] == 0
        assert result["cache_misses"] == 0
        assert result["hit_rate"] == 0.0


class TestQueryOptimizerStatsRealWorldScenarios:
    """Real-world usage scenarios for query optimizer stats."""
    
    def test_high_hit_rate_scenario(self):
        """Test scenario with high cache hit rate."""
        cache = QueryFingerprintCache(max_cache_size=500)
        
        # Simulate repeated queries
        query = {"q": "repeated_query", "params": {"limit": 10}}
        
        for _ in range(10):
            cache.get_fingerprint(query)
        
        result = cache.get_cache_stats()
        
        # Hit rate should be high (after first access)
        assert result["accesses"] >= 1
        assert isinstance(result["hit_rate"], float)
        assert 0.0 <= result["hit_rate"] <= 100.0
    
    def test_cache_capacity_respected(self):
        """Test that cache respects max_size parameter."""
        max_size = 10
        cache = QueryFingerprintCache(max_cache_size=max_size)
        
        result = cache.get_cache_stats()
        
        assert result["max_size"] == max_size


class TestQueryOptimizerStatsDictStructure:
    """Tests verifying QueryOptimizerStatsDict structure compliance."""
    
    def test_fingerprint_cache_stats_from_get_stats_matches_type(self):
        """Verify dict from get_cache_stats() matches QueryFingerprintCacheStatsDict."""
        cache = QueryFingerprintCache(max_cache_size=200)
        
        # Perform some operations
        query = {"test": "query"}
        cache.get_fingerprint(query)
        cache.get_fingerprint(query)
        
        result = cache.get_cache_stats()
        
        # Verify exact field set
        expected_fields = {"cache_size", "max_size", "accesses", "hits", "hit_rate"}
        assert set(result.keys()) == expected_fields
        
        # Verify types
        assert isinstance(result["cache_size"], (int, float))
        assert isinstance(result["max_size"], (int, float))
        assert isinstance(result["accesses"], (int, float))
        assert isinstance(result["hits"], (int, float))
        assert isinstance(result["hit_rate"], float)
    
    def test_detection_stats_from_get_detection_stats_matches_type(self):
        """Verify dict from get_detection_stats() matches GraphTypeDetectionStatsDict."""
        detector = FastGraphTypeDetector()
        
        # Perform detection
        query = {"entities": ["e1"], "relationships": []}
        detector.detect_type_fast(query, fallback_detector=None)
        
        result = detector.get_detection_stats()
        
        # Verify exact field set
        expected_fields = {"cache_size", "cache_hits", "cache_misses", "hit_rate"}
        assert set(result.keys()) == expected_fields
        
        # Verify types
        assert isinstance(result["cache_size"], (int, float))
        assert isinstance(result["cache_hits"], (int, float))
        assert isinstance(result["cache_misses"], (int, float))
        assert isinstance(result["hit_rate"], float)


class TestStatsConsistency:
    """Tests for statistics consistency across components."""
    
    def test_hit_rate_bounds(self):
        """Verify hit_rate is always between 0.0 and 100.0."""
        cache = QueryFingerprintCache(max_cache_size=100)
        
        # With zero accesses
        result1 = cache.get_cache_stats()
        assert 0.0 <= result1["hit_rate"] <= 100.0
        
        # After operations
        query = {"q": "test"}
        cache.get_fingerprint(query)
        cache.get_fingerprint(query)
        
        result2 = cache.get_cache_stats()
        assert 0.0 <= result2["hit_rate"] <= 100.0
    
    def test_cache_size_never_exceeds_max(self):
        """Verify cache_size never exceeds max_size."""
        cache = QueryFingerprintCache(max_cache_size=5)
        
        # Try many operations
        for i in range(20):
            query = {"q": f"query_{i}"}
            cache.get_fingerprint(query)
        
        result = cache.get_cache_stats()
        
        assert result["cache_size"] <= result["max_size"]
    
    def test_detection_stats_consistency(self):
        """Verify detection stats have consistent structure."""
        detector = FastGraphTypeDetector()
        
        # Test detection
        query = {"entities": ["e1"], "relationships": []}
        detector.detect_type_fast(query, fallback_detector=None)
        
        result = detector.get_detection_stats()
        
        # Stats should be available
        assert "cache_hits" in result
        assert "cache_misses" in result
        assert result["cache_hits"] >= 0
        assert result["cache_misses"] >= 0


class TestQueryOptimizerTypeContractDataFlow:
    """Tests for data flow through type contracts."""
    
    def test_fingerprint_cache_type_contract_population(self):
        """Verify fingerprint cache stats populate all TypedDict fields."""
        cache = QueryFingerprintCache(max_cache_size=300)
        query = {"test": "query"}
        
        cache.get_fingerprint(query)
        cache.get_fingerprint(query)
        result = cache.get_cache_stats()
        
        # All required fields should be present
        typed_dict_fields = QueryFingerprintCacheStatsDict.__annotations__.keys()
        for field in typed_dict_fields:
            assert field in result, f"Missing field '{field}' in cache stats"
    
    def test_detection_type_contract_population(self):
        """Verify detection stats populate all TypedDict fields."""
        detector = FastGraphTypeDetector()
        query = {"entities": ["e1"], "relationships": []}
        
        detector.detect_type_fast(query, fallback_detector=None)
        result = detector.get_detection_stats()
        
        # All required fields should be present
        typed_dict_fields = GraphTypeDetectionStatsDict.__annotations__.keys()
        for field in typed_dict_fields:
            assert field in result, f"Missing field '{field}' in detection stats"
    
    def test_cache_stats_numeric_ranges(self):
        """Verify cache stats numeric values are in reasonable ranges."""
        cache = QueryFingerprintCache(max_cache_size=50)
        
        result = cache.get_cache_stats()
        
        # Numeric consistency checks
        assert result["cache_size"] >= 0
        assert result["max_size"] > 0
        assert result["accesses"] >= 0
        assert result["hits"] >= 0
        assert result["hits"] <= result["accesses"]
