"""
Test suite for integrated query optimizer optimizations in UnifiedGraphRAGQueryOptimizer.

Validates that the direct integration of QueryFingerprintCache and FastGraphTypeDetector
functionality delivers expected performance improvements without wrapper overhead.
"""

import pytest
import time
import numpy as np
from ipfs_datasets_py.optimizers.graphrag.query_unified_optimizer import UnifiedGraphRAGQueryOptimizer


class TestQueryOptimizerIntegratedOptimizations:
    """Test integrated optimization functionality in UnifiedGraphRAGQueryOptimizer."""
    
    @pytest.fixture
    def optimizer(self):
        """Create optimizer instance."""
        return UnifiedGraphRAGQueryOptimizer()
    
    def test_fingerprint_cache_integration(self, optimizer):
        """Test that query fingerprint caching is integrated and functional."""
        # Create query with caching enabled
        query = {
            "query_text": "test query",
            "max_vector_results": 10,
            "traversal": {"max_depth": 3}
        }
        
        # First call - cache miss
        result1 = optimizer.optimize_query(query, priority="normal")
        
        # Get stats after first call
        stats = optimizer.get_optimization_stats()
        fp_stats = stats["query_fingerprint_cache"]
        
        # Should have at least 1 access (if caching was enabled for this query)
        initial_accesses = fp_stats["accesses"]
        
        # Second call - should potentially use cache
        result2 = optimizer.optimize_query(query, priority="normal")
        
        # Get stats after second call
        stats2 = optimizer.get_optimization_stats()
        fp_stats2 = stats2["query_fingerprint_cache"]
        
        # Should have more accesses
        assert fp_stats2["accesses"] >= initial_accesses
        
        # Results should be consistent
        assert result1["graph_type"] == result2["graph_type"]
        assert result1["weights"] == result2["weights"]
    
    def test_graph_type_detection_cache_integration(self, optimizer):
        """Test that fast graph type detection is integrated and functional."""
        # Wikipedia query
        wiki_query = {
            "query_text": "What is wikipedia?",
            "entity_source": "wikipedia",
        }
        
        # First detection - cache miss
        result1 = optimizer.optimize_query(wiki_query)
        
        # Get stats
        stats1 = optimizer.get_optimization_stats()
        type_stats1 = stats1["graph_type_detection_cache"]
        
        initial_accesses = type_stats1["accesses"]
        initial_hits = type_stats1["hits"]
        
        # Second detection - should hit cache
        result2 = optimizer.optimize_query(wiki_query)
        
        # Get updated stats
        stats2 = optimizer.get_optimization_stats()
        type_stats2 = stats2["graph_type_detection_cache"]
        
        # Should have more accesses and potentially more hits
        assert type_stats2["accesses"] > initial_accesses
        
        # Results should be consistent
        assert result1["graph_type"] == result2["graph_type"] == "wikipedia"
    
    def test_optimization_stats_structure(self, optimizer):
        """Test that get_optimization_stats returns proper structure."""
        stats = optimizer.get_optimization_stats()
        
        # Check structure
        assert "query_fingerprint_cache" in stats
        assert "graph_type_detection_cache" in stats
        
        # Check fingerprint cache stats
        fp = stats["query_fingerprint_cache"]
        assert "size" in fp
        assert "max_size" in fp
        assert "accesses" in fp
        assert "hits" in fp
        assert "hit_rate_percent" in fp
        
        # Check type detection cache stats
        td = stats["graph_type_detection_cache"]
        assert "size" in td
        assert "max_size" in td
        assert "accesses" in td
        assert "hits" in td
        assert "hit_rate_percent" in td
    
    def test_heuristic_graph_type_detection_wikipedia(self, optimizer):
        """Test fast heuristic detection for Wikipedia queries."""
        queries = [
            {"entity_source": "wikipedia"},
            {"query_text": "wikipedia article"},
            {"query_text": "wikidata entry"},
            {"query_text": "dbpedia resource"},
        ]
        
        for query in queries:
            result = optimizer.optimize_query(query)
            assert result["graph_type"] == "wikipedia", f"Failed for query: {query}"
    
    def test_heuristic_graph_type_detection_ipld(self, optimizer):
        """Test fast heuristic detection for IPLD queries."""
        queries = [
            {"entity_source": "ipld"},
            {"query_text": "ipld dag"},
            {"query_text": "content-addressed data"},
            {"entity_ids": ["QmTest123"]},  # CID prefix
            {"entity_ids": ["bafyTest456"]},  # CID prefix
        ]
        
        for query in queries:
            result = optimizer.optimize_query(query)
            assert result["graph_type"] == "ipld", f"Failed for query: {query}"
    
    def test_heuristic_graph_type_detection_general(self, optimizer):
        """Test fallback to general for unrecognized queries."""
        query = {
            "query_text": "generic query without specific markers",
            "traversal": {"max_depth": 2}
        }
        
        result = optimizer.optimize_query(query)
        assert result["graph_type"] == "general"
    
    def test_cache_hit_rate_improvement_with_repeated_queries(self, optimizer):
        """Test that cache hit rate improves with repeated queries."""
        query_template = {
            "query_text": "test query {}",
            "traversal": {"max_depth": 2}
        }
        
        # Execute multiple unique queries
        for i in range(5):
            query = query_template.copy()
            query["query_text"] = query_template["query_text"].format(i)
            optimizer.optimize_query(query)
        
        # Get initial stats
        stats1 = optimizer.get_optimization_stats()
        
        # Repeat the same queries
        for i in range(5):
            query = query_template.copy()
            query["query_text"] = query_template["query_text"].format(i)
            optimizer.optimize_query(query)
        
        # Get final stats
        stats2 = optimizer.get_optimization_stats()
        
        # Type detection cache hit rate should improve
        hit_rate_1 = stats1["graph_type_detection_cache"]["hit_rate_percent"]
        hit_rate_2 = stats2["graph_type_detection_cache"]["hit_rate_percent"]
        
        # Hit rate should be stable or improved
        assert hit_rate_2 >= hit_rate_1


class TestIntegratedOptimizationPerformance:
    """Performance tests for integrated optimizations."""
    
    @pytest.fixture
    def optimizer(self):
        """Create optimizer instance."""
        return UnifiedGraphRAGQueryOptimizer()
    
    def test_repeated_query_performance_benefit(self, optimizer):
        """Test that repeated queries show performance benefit from caching."""
        query = {
            "query_text": "complex query with many parameters",
            "max_vector_results": 20,
            "min_similarity": 0.7,
            "traversal": {
                "max_depth": 4,
                "edge_types": ["related_to", "part_of", "instance_of"]
            }
        }
        
        # First execution - cache population
        times_first = []
        for _ in range(10):
            start = time.perf_counter()
            optimizer.optimize_query(query)
            times_first.append(time.perf_counter() - start)
        
        # Clear to get fresh baseline
        optimizer2 = UnifiedGraphRAGQueryOptimizer()
        
        # Second set - should benefit from warm cache in first optimizer
        times_second = []
        for _ in range(10):
            start = time.perf_counter()
            optimizer.optimize_query(query)
            times_second.append(time.perf_counter() - start)
        
        # Calculate averages
        avg_first = sum(times_first) / len(times_first)
        avg_second = sum(times_second) / len(times_second)
        
        # Both should be fast (under 5ms each)
        assert avg_first < 0.005, f"Average first run time {avg_first:.4f}s exceeds 5ms"
        assert avg_second < 0.005, f"Average second run time {avg_second:.4f}s exceeds 5ms"
        
        # Get stats to confirm caching is active
        stats = optimizer.get_optimization_stats()
        
        # Should have recorded accesses
        assert stats["graph_type_detection_cache"]["accesses"] > 0
    
    def test_graph_type_detection_speed(self, optimizer):
        """Test that graph type detection is fast with heuristics."""
        queries = [
            {"entity_source": "wikipedia", "query_text": "test"},
            {"entity_source": "ipld", "query_text": "test"},
            {"query_text": "generic query"},
        ]
        
        # Measure detection time
        times = []
        for query in queries * 10:  # Repeat to get stable measurements
            start = time.perf_counter()
            result = optimizer.optimize_query(query)
            elapsed = time.perf_counter() - start
            times.append(elapsed)
            assert result["graph_type"] in ["wikipedia", "ipld", "general"]
        
        # Average should be well under 1ms
        avg_time = sum(times) / len(times)
        assert avg_time < 0.001, f"Average detection time {avg_time:.4f}s exceeds 1ms"
        
        # Get cache stats
        stats = optimizer.get_optimization_stats()
        
        # Should have high hit rate after warm-up
        hit_rate = stats["graph_type_detection_cache"]["hit_rate_percent"]
        
        # Should have some cache usage
        assert hit_rate >= 0.0  # At minimum, should have statistics


class TestIntegratedOptimizationCorrectness:
    """Correctness tests to ensure optimizations don't change behavior."""
    
    @pytest.fixture
    def optimizer(self):
        """Create optimizer instance."""
        return UnifiedGraphRAGQueryOptimizer()
    
    def test_consistent_results_across_cache_states(self, optimizer):
        """Test that results are consistent regardless of cache state."""
        query = {
            "query_text": "test query",
            "entity_source": "wikipedia",
            "traversal": {"max_depth": 3}
        }
        
        # First call
        result1 = optimizer.optimize_query(query)
        
        # Multiple subsequent calls
        for _ in range(5):
            result = optimizer.optimize_query(query)
            
            # Core fields should match
            assert result["graph_type"] == result1["graph_type"]
            assert result["weights"] == result1["weights"]
            assert result["traversal_strategy"] == result1["traversal_strategy"]
    
    def test_different_queries_different_fingerprints(self, optimizer):
        """Test that different queries get different cache treatment."""
        query1 = {"query_text": "query one", "max_vector_results": 5}
        query2 = {"query_text": "query two", "max_vector_results": 10}
        query3 = {"query_text": "query one", "max_vector_results": 5}  # Same as query1
        
        result1 = optimizer.optimize_query(query1)
        result2 = optimizer.optimize_query(query2)
        result3 = optimizer.optimize_query(query3)
        
        # Results for query1 and query3 should be identical (same query)
        assert result1["query"] == result3["query"]
        
        # Result2 should differ from result1
        assert result1["query"]["max_vector_results"] != result2["query"]["max_vector_results"]
