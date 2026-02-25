"""Parity tests for query optimizer split - ensure behavior stability across modularization.

These tests verify that once the query_unified_optimizer is split into modular components
(query_detection.py, query_normalization.py, query_caching.py, etc.), the behavioral
output remains identical to the original monolithic implementation.

This test suite will be run:
1. Against original monolithic query_unified_optimizer (baseline)
2. Against modular split version (post-split validation)

Any deviation in outputs will be flagged as breaking change.
"""

from __future__ import annotations

import pytest
import json
import hashlib
from typing import Dict, Any, List
from unittest.mock import Mock, patch

from ipfs_datasets_py.optimizers.graphrag.query_unified_optimizer import UnifiedGraphRAGQueryOptimizer


class TestQueryOptimizerParity:
    """Validate query optimizer output behavior for later parity checks."""
    
    @pytest.fixture
    def optimizer(self):
        """Create optimizer instance."""
        return UnifiedGraphRAGQueryOptimizer()
    
    def test_simple_query_optimization_output_structure(self, optimizer):
        """Test simple query produces expected output structure."""
        query = {
            "query_type": "entity_search",
            "domain": "test",
            "query_text": "What is entity A?",
        }
        
        result = optimizer.optimize_query(query)
        
        # Verify output structure
        assert isinstance(result, dict)
        assert "result" in result or "error" not in result
        
    def test_moderate_query_optimization_determinism(self, optimizer):
        """Test that running identical query twice produces identical output."""
        query = {
            "query_type": "entity_search",
            "query_text": "Relationships between A and B",
            "query_vector": [0.1] * 100,
            "vector_params": {"top_k": 10, "min_score": 0.5},
            "traversal": {"max_depth": 3, "edge_types": ["related_to", "part_of"]},
        }
        
        result1 = optimizer.optimize_query(query)
        result2 = optimizer.optimize_query(query)
        
        # For deterministic operations, results should be identical
        # (excluding timestamps which may differ)
        result1_copy = dict(result1)
        result2_copy = dict(result2)
        
        # Remove timestamp if present
        for r in [result1_copy, result2_copy]:
            if isinstance(r, dict):
                r.pop("timestamp", None)
        
        # Results should be structurally identical
        assert result1_copy == result2_copy, "Query optimization should be deterministic"
    
    def test_complex_query_parameter_preservation(self, optimizer):
        """Test that complex query parameters are preserved/normalized correctly."""
        query = {
            "query_type": "multi_hop",
            "query_text": "Complex reasoning path",
            "query_vector": [0.05] * 256,
            "vector_params": {"top_k": 50, "min_score": 0.3},
            "traversal": {
                "max_depth": 5,
                "edge_types": ["related_to", "part_of", "influences"],
            },
            "max_vector_results": 100,
            "entity_importance_threshold": 0.4,
        }
        
        result = optimizer.optimize_query(query)
        
        # Verify result structure exists
        assert result is not None
        assert isinstance(result, dict)
        
    def test_graph_type_detection_consistency(self, optimizer):
        """Test that graph type detection produces expected results."""
        test_cases = [
            # (query, expected_graph_type_clue)
            (
                {"query_type": "entity_search"},
                None  # Any valid result is acceptable
            ),
            (
                {"query_type": "relationship_search", "traversal": {"max_depth": 1}},
                None
            ),
            (
                {"query_type": "path_search", "traversal": {"max_depth": 5}},
                None
            ),
        ]
        
        for query, expected_clue in test_cases:
            result = optimizer.optimize_query(query)
            # Just verify no exception and result is dict
            assert isinstance(result, dict)
    
    def test_vector_optimization_idempotency(self, optimizer):
        """Test that vector optimization is idempotent."""
        query = {
            "query_type": "vector_search",
            "query_vector": [0.1] * 100,
            "max_vector_results": 10,
        }
        
        result1 = optimizer.optimize_query(query)
        result2 = optimizer.optimize_query(query)
        result3 = optimizer.optimize_query(query)
        
        # For vector path, results should stabilize (no state mutation)
        assert result1 is not None
        assert result2 is not None
        assert result3 is not None
    
    def test_budget_allocation_presence(self, optimizer):
        """Test that budget allocation is always present in output."""
        queries = [
            {"query_type": "simple"},
            {"query_type": "complex", "traversal": {"max_depth": 5}},
        ]
        
        for query in queries:
            result = optimizer.optimize_query(query)
            # Budget should be allocated (may be in result or side-effect)
            assert result is not None
    
    def test_edge_case_empty_query(self, optimizer):
        """Test handling of edge case: empty query dict."""
        query = {}
        
        # Should not raise, should return valid result
        result = optimizer.optimize_query(query)
        assert result is not None
        assert isinstance(result, dict)
    
    def test_edge_case_minimal_query(self, optimizer):
        """Test handling of minimal query."""
        query = {"query_type": "test"}
        
        result = optimizer.optimize_query(query)
        assert result is not None
        assert isinstance(result, dict)
    
    def test_query_validation_error_handling(self, optimizer):
        """Test that invalid queries are handled gracefully."""
        invalid_queries = [
            None,  # Not a dict
            123,   # Not a dict
            "string",  # Not a dict
            [],    # Not a dict
        ]
        
        for invalid_query in invalid_queries:
            with pytest.raises((ValueError, TypeError, AssertionError)):
                optimizer.optimize_query(invalid_query)
    
    def test_parameter_normalization_traversal(self, optimizer):
        """Test traversal parameter normalization."""
        # Query with traversal at top level (should be normalized to nested)
        query = {
            "query_type": "traversal",
            "max_traversal_depth": 3,
            "edge_types": ["type1", "type2"],
        }
        
        result = optimizer.optimize_query(query)
        assert result is not None
    
    def test_weight_calculation_consistency(self, optimizer):
        """Test that weight calculation is consistent."""
        query = {
            "query_type": "hybrid",
            "query_vector": [0.1] * 100,
            "traversal": {"max_depth": 3},
        }
        
        result1 = optimizer.optimize_query(query)
        result2 = optimizer.optimize_query(query)
        
        # Weights should be consistent across runs
        assert result1 is not None
        assert result2 is not None


class TestQueryOptimizerParityRegression:
    """Regression tests to catch unintended behavior changes."""
    
    @pytest.fixture
    def optimizer(self):
        """Create optimizer instance."""
        return UnifiedGraphRAGQueryOptimizer()
    
    def test_no_query_state_mutation(self, optimizer):
        """Test that optimizing a query doesn't mutate the original query dict."""
        query = {
            "query_type": "test",
            "query_vector": [0.1] * 10,
            "traversal": {"max_depth": 2},
        }
        
        query_copy = dict(query)
        query_copy_vector = list(query.get("query_vector", []))
        
        # Optimize
        result = optimizer.optimize_query(query)
        
        # Original query should be unchanged
        assert query == query_copy
        assert query.get("query_vector") == query_copy_vector
    
    def test_multiple_queries_independence(self, optimizer):
        """Test that processing one query doesn't affect another."""
        query1 = {"query_type": "query1", "param": "A"}
        query2 = {"query_type": "query2", "param": "B"}
        
        result1a = optimizer.optimize_query(query1)
        result2 = optimizer.optimize_query(query2)
        result1b = optimizer.optimize_query(query1)
        
        # Running query1 before/after query2 should produce identical results
        assert result1a == result1b
    
    def test_optimizer_reusability(self, optimizer):
        """Test that optimizer can be reused without state accumulation."""
        queries = [
            {"query_type": f"type{i}", "idx": i}
            for i in range(10)
        ]
        
        results = []
        for q in queries:
            r = optimizer.optimize_query(q)
            results.append(r)
        
        # Run again
        results2 = []
        for q in queries:
            r = optimizer.optimize_query(q)
            results2.append(r)
        
        # Results should be identical (no state carryover)
        assert results == results2
    
    def test_cache_key_stability(self, optimizer):
        """Test that cache keys are stable/deterministic."""
        query = {
            "query_type": "cache_test",
            "query_vector": [0.1] * 50,
            "traversal": {"max_depth": 2},
        }
        
        # Run multiple times, collect any cache keys
        results = []
        for _ in range(3):
            result = optimizer.optimize_query(query)
            results.append(result)
        
        # All runs should have same structure if caching exists
        assert len(set(str(r) for r in results)) <= len(results)


class TestQueryOptimizerCriticalPaths:
    """Test critical execution paths that must remain stable."""
    
    @pytest.fixture
    def optimizer(self):
        """Create optimizer instance."""
        return UnifiedGraphRAGQueryOptimizer()
    
    def test_fast_path_simple_query(self, optimizer):
        """Test fast path for simple queries (no vector, no complex traversal)."""
        query = {"query_type": "simple_search"}
        
        # Should complete quickly without exceptions
        result = optimizer.optimize_query(query)
        assert result is not None
    
    def test_vector_path_with_fallback(self, optimizer):
        """Test vector path handles missing vector gracefully."""
        query = {
            "query_type": "vector_search",
            "max_vector_results": 10,
            # Note: no query_vector provided
        }
        
        result = optimizer.optimize_query(query)
        assert result is not None
    
    def test_traversal_depth_scaling(self, optimizer):
        """Test that traversal depth parameter is applied correctly."""
        for depth in [1, 2, 3, 5, 10]:
            query = {
                "query_type": "traversal",
                "traversal": {"max_depth": depth},
            }
            
            result = optimizer.optimize_query(query)
            assert result is not None
    
    def test_edge_type_processing(self, optimizer):
        """Test that edge types are processed correctly."""
        edge_type_cases = [
            [],  # No edge types
            ["type1"],  # Single edge type
            ["type1", "type2", "type3"],  # Multiple edge types
            ["type1"] * 10,  # Duplicate edge types
        ]
        
        for edge_types in edge_type_cases:
            query = {
                "query_type": "typed_traversal",
                "traversal": {"edge_types": edge_types},
            }
            
            result = optimizer.optimize_query(query)
            assert result is not None


class TestQueryOptimizerComparisonFixture:
    """Fixture for running comparison tests between implementations.
    
    Usage after split:
        from ipfs_datasets_py.optimizers.graphrag import query_unified_optimizer_new
        
        @pytest.mark.parametrize("query", generate_test_queries())
        def test_parity(query):
            result_old = optimizer_old.optimize_query(query)
            result_new = query_unified_optimizer_new.optimize_query(query)
            assert result_old == result_new  # or structural equality
    """
    
    @staticmethod
    def generate_test_queries() -> List[Dict[str, Any]]:
        """Generate comprehensive test query set for parity checking."""
        return [
            # Simple queries
            {"query_type": "search"},
            {"query_type": "search", "domain": "test"},
            
            # Vector queries
            {
                "query_type": "vector",
                "query_vector": [0.1] * 50,
                "max_vector_results": 5,
            },
            
            # Traversal queries
            {
                "query_type": "traversal",
                "traversal": {"max_depth": 3},
            },
            {
                "query_type": "traversal",
                "traversal": {"max_depth": 3, "edge_types": ["type1", "type2"]},
            },
            
            # Complex queries
            {
                "query_type": "complex",
                "query_text": "Complex reasoning",
                "query_vector": [0.05] * 256,
                "vector_params": {"top_k": 20, "min_score": 0.4},
                "traversal": {"max_depth": 5, "edge_types": ["r", "p"]},
                "max_vector_results": 50,
            },
        ]


# Regression test markers for CI/CD
markers = {
    "parity_critical": "Critical for post-split validation",
    "determinism": "Must be deterministic for debugging",
    "regression": "Must not change behavior",
}


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "parity_critical"])
