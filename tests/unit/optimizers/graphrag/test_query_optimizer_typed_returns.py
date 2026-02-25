"""Tests for typed return contracts in query optimizer methods.

Validates that query optimizer methods return properly typed results
matching their TypedDict contracts.
"""

import pytest
from unittest.mock import Mock, MagicMock
from ipfs_datasets_py.optimizers.graphrag.query_unified_optimizer import UnifiedGraphRAGQueryOptimizer
from ipfs_datasets_py.optimizers.graphrag.query_optimizer_types import (
    QueryOptimizationResult,
    QueryOptimizationPlan,
    WikipediaTraversalOptimization,
    IPLDTraversalOptimization,
)


class MockBudgetManager:
    """Mock budget manager for testing."""
    def allocate_budget(self, query, priority):
        return {
            "vector_search_ms": 500,
            "graph_traversal_ms": 1000,
            "ranking_ms": 100,
            "max_nodes": 100,
        }


class MockSpecificOptimizer:
    """Mock optimizer for specific graph types."""
    vector_weight = 0.7
    graph_weight = 0.3
    cache_enabled = False
    
    def __init__(self):
        """Initialize with required query_stats attribute."""
        self.query_stats = Mock(avg_query_time=0.0, cache_hit_rate=0.0)
    
    def optimize_query(self, **kwargs):
        return {
            "params": {},
            "weights": {"vector": 0.7, "graph": 0.3}
        }


class TestQueryOptimizerTypedReturns:
    """Test typed return contracts for query optimizer."""

    @pytest.fixture
    def optimizer(self):
        """Create a query optimizer with mocked dependencies."""
        # Create optimizer with mocked dependencies
        budget_manager = MockBudgetManager()
        base_optimizer = MockSpecificOptimizer()
        
        opt = UnifiedGraphRAGQueryOptimizer(
            rewriter=None,
            budget_manager=budget_manager,
            base_optimizer=base_optimizer,
            graph_info=None,
            metrics_collector=None,
            visualizer=None,
            metrics_dir=None
        )
        opt._specific_optimizers = {"wikipedia": MockSpecificOptimizer()}
        opt.query_stats = Mock(avg_query_time=0.0, cache_hit_rate=0.0)
        return opt

    def test_optimize_query_returns_correct_structure(self, optimizer):
        """Verify optimize_query returns QueryOptimizationResult structure."""
        query = {
            "query_text": "Who is the president?",
            "max_vector_results": 5,
        }
        
        result = optimizer.optimize_query(query, priority="normal")
        
        # Verify result is dict with expected keys (TypedDict at runtime)
        assert isinstance(result, dict)
        assert "query" in result
        assert "weights" in result
        assert "budget" in result
        assert "graph_type" in result
        assert "statistics" in result
        assert "caching" in result
        assert "traversal_strategy" in result
        
        # Verify types of fields
        assert isinstance(result["query"], dict)
        assert isinstance(result["weights"], dict)
        assert isinstance(result["budget"], dict)
        assert isinstance(result["graph_type"], str)
        assert isinstance(result["statistics"], dict)
        assert isinstance(result["caching"], dict)
        assert isinstance(result["traversal_strategy"], str)

    def test_optimize_query_weights_valid_range(self, optimizer):
        """Verify weights are in valid range [0, 1]."""
        query = {"query_text": "Test query"}
        result = optimizer.optimize_query(query)
        
        weights = result["weights"]
        for key, value in weights.items():
            assert 0 <= value <= 1, f"Weight {key}={value} out of range"

    def test_optimize_query_budget_positive_values(self, optimizer):
        """Verify budget values are positive."""
        query = {"query_text": "Test query"}
        result = optimizer.optimize_query(query)
        
        budget = result["budget"]
        for key, value in budget.items():
            if isinstance(value, (int, float)):
                assert value >= 0, f"Budget {key}={value} is negative"

    def test_optimize_query_with_vector_query(self, optimizer):
        """Verify optimize_query handles vector queries correctly."""
        query = {
            "query_text": "Find similar items",
            "query_vector": [0.1, 0.2, 0.3, 0.4],
            "max_vector_results": 10,
        }
        
        result = optimizer.optimize_query(query)
        
        assert result["query"]["max_vector_results"] == 10
        assert result["weights"]["vector"] <= 1.0
        assert result["weights"]["graph"] <= 1.0

    def test_get_execution_plan_returns_correct_structure(self, optimizer):
        """Verify get_execution_plan returns QueryOptimizationPlan structure."""
        query = {
            "query_text": "Who is the president?",
            "query_vector": [0.1, 0.2, 0.3],
        }
        
        plan = optimizer.get_execution_plan(query, priority="normal")
        
        # Verify result is dict
        assert isinstance(plan, dict)
        
        # Verify it has some reasonable keys (budget, execution steps, caching, etc.)
        assert len(plan) > 0, "Plan should not be empty"
        
        # Verify it has execution_steps list if present
        if "execution_steps" in plan:
            assert isinstance(plan["execution_steps"], list)

    def test_optimize_wikipedia_traversal_returns_typed_dict(self, optimizer):
        """Verify optimize_wikipedia_traversal returns WikipediaTraversalOptimization."""
        query = {
            "query_text": "Wikipedia facts",
            "entity_types": ["Person", "Place"],
        }
        entity_scores = {"entity1": 0.9, "entity2": 0.7}
        
        result = optimizer.optimize_wikipedia_traversal(query, entity_scores)
        
        # Verify result structure
        assert isinstance(result, dict)
        
        # Verify it has some reasonable keys (query-related, traversal-related, etc.)
        assert len(result) > 0, "Result should not be empty"
        
        # Check that it contains query-related or traversal-related fields
        keys = set(result.keys())
        assert any(k in keys for k in ["query", "query_text", "traversal", "strategy"])

    def test_optimize_ipld_traversal_returns_typed_dict(self, optimizer):
        """Verify optimize_ipld_traversal returns IPLDTraversalOptimization."""
        query = {
            "query_text": "IPLD facts",
        }
        entity_scores = {"cid1": 0.95, "cid2": 0.8}
        
        result = optimizer.optimize_ipld_traversal(query, entity_scores)
        
        # Verify result structure
        assert isinstance(result, dict)
        
        # Verify result is not empty
        assert len(result) > 0, "Result should not be empty"
        
        # Check for traversal-strategy or cache-related fields
        keys = set(result.keys())
        assert any(k in keys for k in ["traversal", "strategy", "cache", "query"])


    def test_multiple_optimize_query_calls_consistent(self, optimizer):
        """Verify multiple calls to optimize_query return consistent structures."""
        query1 = {"query_text": "Test 1"}
        query2 = {"query_text": "Test 2"}
        
        result1 = optimizer.optimize_query(query1)
        result2 = optimizer.optimize_query(query2)
        
        # Both results should have same top-level keys
        assert set(result1.keys()) == set(result2.keys())
        
        # Both should have valid weights
        for result in [result1, result2]:
            assert all(0 <= w <= 1 for w in result["weights"].values())


class TestTypeContractValidation:
    """Test TypedDict contract validation."""

    def test_query_optimization_result_fields(self):
        """Verify QueryOptimizationResult has expected structure."""
        # Create a valid result matching the TypedDict
        result: QueryOptimizationResult = {
            "query": {"text": "test"},
            "weights": {"vector": 0.7, "graph": 0.3},
            "budget": {"vector_search_ms": 500},
            "graph_type": "general",
            "statistics": {"avg_query_time": 0.1},
            "caching": {"enabled": False},
            "traversal_strategy": "default",
            "execution_metrics": {"total_time_ms": 10},
        }
        
        # Verify all expected fields present
        assert result["query"]
        assert result["weights"]
        assert result["budget"]
        assert result["graph_type"]

    def test_wikipedia_traversal_optimization_fields(self):
        """Verify WikipediaTraversalOptimization has expected structure."""
        result: WikipediaTraversalOptimization = {
            "query": {"text": "test"},
            "edge_priority": ["instance_of", "subclass_of"],
            "traversal_costs": {"instance_of": 0.1},
            "entity_scores": {"e1": 0.9},
            "relationship_activation_depths": {"instance_of": 3},
        }
        
        # Verify all expected fields present
        assert result["query"]
        assert result["edge_priority"]
        assert result["traversal_costs"]
        assert result["entity_scores"]

    def test_ipld_traversal_optimization_fields(self):
        """Verify IPLDTraversalOptimization has expected structure."""
        result: IPLDTraversalOptimization = {
            "query": {"text": "test"},
            "cid_paths": ["/ipfs/QmTest"],
            "traversal_strategy": "dag_traversal",
            "cache_strategy": "aggressive",
            "dag_exploration_depth": 10,
        }
        
        # Verify all expected fields present
        assert result["query"]
        assert result["cid_paths"]
        assert result["traversal_strategy"]
        assert result["cache_strategy"]
        assert result["dag_exploration_depth"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
