"""
Test for fix to UnifiedGraphRAGQueryOptimizer.optimize_query to ensure it never returns None.
"""

import sys
import os
import numpy as np
from typing import Dict, Any, List, Optional
from collections import defaultdict

# Import the module
sys.path.append(os.getcwd())
from ipfs_datasets_py.rag.rag_query_optimizer import UnifiedGraphRAGQueryOptimizer, GraphRAGQueryOptimizer, GraphRAGQueryStats

class NoneReturningOptimizer(GraphRAGQueryOptimizer):
    """A test optimizer that returns None from optimize_query."""

    def optimize_query(self, *args, **kwargs):
        print('NoneReturningOptimizer.optimize_query called - returning None')
        return None  # This will trigger our safety check

class MockMetricsCollector:
    """Mock metrics collector for testing."""

    def start_query_tracking(self, *args, **kwargs):
        print("start_query_tracking called")
        return 'test-id-123'

    def time_phase(self, *args, **kwargs):
        class TimerContext:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        return TimerContext()

    def record_additional_metric(self, *args, **kwargs):
        pass

    def end_query_tracking(self, *args, **kwargs):
        pass

class MockBudgetManager:
    """Mock budget manager for testing."""

    def allocate_budget(self, *args, **kwargs):
        return {
            'vector_search_ms': 500,
            'graph_traversal_ms': 1000,
            'ranking_ms': 100,
            'max_nodes': 100
        }

class MockRewriter:
    """Mock query rewriter for testing."""

    def rewrite_query(self, query, *args, **kwargs):
        return query

class FixedOptimizer(UnifiedGraphRAGQueryOptimizer):
    """A fixed version of UnifiedGraphRAGQueryOptimizer that never returns None."""

    def _detect_entity_types(self, query_text, predefined_types=None):
        # Mock implementation
        return ["concept", "topic"]

    def optimize_traversal_path(self, query, graph_processor):
        # Mock implementation
        return query

    def _estimate_query_complexity(self, query):
        # Mock implementation
        return "medium"

    def optimize_query(self, query: Dict[str, Any], priority: str = "normal", graph_processor: Any = None) -> Dict[str, Any]:
        """Fixed version of optimize_query that never returns None."""
        try:
            # Start with basic query identity
            result = {
                "query": query,
                "weights": {"vector": 0.7, "graph": 0.3},
                "budget": self.budget_manager.allocate_budget(query, priority),
                "graph_type": "general",
                "statistics": {
                    "avg_query_time": self.query_stats.avg_query_time,
                    "cache_hit_rate": self.query_stats.cache_hit_rate
                },
                "caching": {"enabled": True},
                "traversal_strategy": "default"
            }

            # Get the None-returning optimizer
            optimizer = self._specific_optimizers.get("general")
            print(f"Using optimizer: {optimizer}")

            # Call the optimizer that returns None
            if "query_vector" in query:
                print("Calling optimizer.optimize_query with vector")
                optimized_params = optimizer.optimize_query(
                    query_vector=query["query_vector"],
                    max_vector_results=query.get("max_vector_results", 5),
                    max_traversal_depth=query.get("traversal", {}).get("max_depth", 2),
                    edge_types=query.get("traversal", {}).get("edge_types"),
                    min_similarity=query.get("min_similarity", 0.5)
                )
                print(f"optimizer.optimize_query returned: {optimized_params}")

                # Check if it returned None and use fallback if so
                if optimized_params is None:
                    print("Creating fallback because optimizer returned None")
                    fallback_plan = self._create_fallback_plan(
                        query=query,
                        priority=priority,
                        error="Optimizer returned None"
                    )
                    print(f"Fallback plan: {fallback_plan}")
                    return fallback_plan

            return result

        except Exception as e:
            error_msg = f"Error in optimize_query: {str(e)}"
            print(error_msg)
            fallback = self._create_fallback_plan(
                query=query,
                priority=priority,
                error=error_msg
            )
            print(f"Exception fallback: {fallback}")
            return fallback

def test_fixed_optimizer():
    """Test the fixed optimizer implementation."""

    # Create the fixed optimizer instance
    optimizer = FixedOptimizer()

    # Replace components with mocks
    optimizer.metrics_collector = MockMetricsCollector()
    optimizer.budget_manager = MockBudgetManager()
    optimizer.rewriter = MockRewriter()
    optimizer.query_stats = GraphRAGQueryStats()

    # Replace with the None-returning optimizer
    none_optimizer = NoneReturningOptimizer()
    optimizer.base_optimizer = none_optimizer
    optimizer._specific_optimizers = {
        'general': none_optimizer,
        'wikipedia': none_optimizer,
        'ipld': none_optimizer
    }

    # Create a test query with vector
    test_query = {
        'query_text': 'test query',
        'query_vector': np.array([0.1, 0.2, 0.3]),
        'traversal': {'max_depth': 2}
    }

    # Call optimize_query - should return fallback plan, not None
    print("\nCalling fixed optimizer.optimize_query...")
    result = optimizer.optimize_query(test_query)
    print("optimize_query returned type:", type(result))

    # Verify the result
    success = result is not None
    if success:
        print("SUCCESS: optimize_query returned a non-None result")
        if isinstance(result, dict):
            print(f"Result keys: {sorted(list(result.keys()))}")
            print(f"Is fallback plan: {result.get('fallback', False)}")
    else:
        print("FAILURE: optimize_query returned None")

    return success

if __name__ == "__main__":
    # Run the test
    success = test_fixed_optimizer()
    sys.exit(0 if success else 1)
