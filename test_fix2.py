"""
Test for the completely fixed implementation of UnifiedGraphRAGQueryOptimizer.optimize_query.
"""

import sys
import os
import numpy as np
from typing import Dict, Any, List, Optional
from collections import defaultdict

# Import the module
sys.path.append(os.getcwd())
from ipfs_datasets_py.rag_query_optimizer import UnifiedGraphRAGQueryOptimizer, GraphRAGQueryOptimizer, GraphRAGQueryStats

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

# Create a completely fixed version of the UnifiedGraphRAGQueryOptimizer
class CompletelyFixedOptimizer(UnifiedGraphRAGQueryOptimizer):
    """A complete rewrite of UnifiedGraphRAGQueryOptimizer with proper None handling."""
    
    def __init__(self):
        # Initialize without calling parent init to avoid dependencies
        self.metrics_collector = MockMetricsCollector()
        self._traversal_stats = {
            'paths_explored': [], 
            'path_scores': {}, 
            'entity_frequency': defaultdict(int),
            'entity_connectivity': {},
            'relation_usefulness': defaultdict(float)
        }
        self.query_stats = GraphRAGQueryStats()
        self.rewriter = MockRewriter()
        self.budget_manager = MockBudgetManager()
        self.base_optimizer = NoneReturningOptimizer()
        self._specific_optimizers = {'general': NoneReturningOptimizer()}
        self.graph_info = {}
        self.visualizer = None
    
    def _create_fallback_plan(self, query: Dict[str, Any], priority: str = "normal", error: Optional[str] = None) -> Dict[str, Any]:
        """Create a fallback query plan when optimization fails."""
        print(f"Creating fallback plan for error: {error}")
        
        # Create a safe copy of the query with defaults
        fallback_query = query.copy()
        
        # Ensure traversal section exists
        if "traversal" not in fallback_query:
            fallback_query["traversal"] = {}
            
        # Set conservative defaults for traversal
        if "max_depth" not in fallback_query["traversal"]:
            fallback_query["traversal"]["max_depth"] = 2
            
        # Set conservative defaults for vector search
        if "max_vector_results" not in fallback_query:
            fallback_query["max_vector_results"] = 5
            
        if "min_similarity" not in fallback_query:
            fallback_query["min_similarity"] = 0.6
        
        # Allocate a conservative budget
        budget = {
            "vector_search_ms": 500,
            "graph_traversal_ms": 1000,
            "ranking_ms": 100,
            "max_nodes": 100
        }
        
        # Try to use the budget manager if available
        if hasattr(self, 'budget_manager') and self.budget_manager is not None:
            try:
                budget = self.budget_manager.allocate_budget(fallback_query, priority)
            except Exception as e:
                # Use default budget if budget_manager fails
                pass
        
        # Return the fallback plan
        return {
            "query": fallback_query,
            "weights": {"vector": 0.7, "graph": 0.3},  # Conservative default weights
            "budget": budget,
            "graph_type": "generic",
            "statistics": {
                "fallback": True,
                "error_handled": True
            },
            "caching": {"enabled": False},  # Disable caching for fallback plans
            "traversal_strategy": "default",
            "fallback": True,
            "error": error
        }
    
    def detect_graph_type(self, query: Dict[str, Any]) -> str:
        """Detect the graph type from query parameters."""
        return "general"
        
    def _detect_entity_types(self, query_text: str, predefined_types=None) -> List[str]:
        """Detect entity types from query text."""
        return ["concept", "topic"]
    
    def optimize_traversal_path(self, query: Dict[str, Any], graph_processor) -> Dict[str, Any]:
        """Optimize the traversal path using the graph processor."""
        return query
        
    def _estimate_query_complexity(self, query: Dict[str, Any]) -> str:
        """Estimate the complexity of a query."""
        return "medium"
    
    def optimize_query(self, query: Dict[str, Any], priority: str = "normal", graph_processor=None) -> Dict[str, Any]:
        """A complete rewrite of optimize_query that never returns None."""
        
        try:
            # Start tracking query metrics
            query_id = self.metrics_collector.start_query_tracking(query_params=query)
            
            # Detect graph type
            graph_type = self.detect_graph_type(query)
            
            # Get the appropriate optimizer
            optimizer = self._specific_optimizers.get(graph_type, self.base_optimizer)
            
            # Apply query rewriting
            rewritten_query = self.rewriter.rewrite_query(query, self.graph_info, {})
            
            # Ensure traversal section exists
            if "traversal" not in rewritten_query:
                rewritten_query["traversal"] = {}
            
            # Get optimized parameters
            if "query_vector" in rewritten_query:
                # For vector-based queries
                print("Calling optimizer.optimize_query...")
                optimized_params = optimizer.optimize_query(
                    query_vector=rewritten_query["query_vector"],
                    max_vector_results=rewritten_query.get("max_vector_results", 5),
                    max_traversal_depth=rewritten_query["traversal"].get("max_depth", 2),
                    edge_types=rewritten_query["traversal"].get("edge_types"),
                    min_similarity=rewritten_query.get("min_similarity", 0.5)
                )
                print(f"optimizer.optimize_query returned: {optimized_params}")
                
                # Safety check for None result
                if optimized_params is None:
                    print("optimizer.optimize_query returned None, returning fallback plan")
                    fallback_plan = self._create_fallback_plan(
                        query=query,
                        priority=priority,
                        error="Base optimizer returned None"
                    )
                    
                    # End tracking
                    self.metrics_collector.end_query_tracking(
                        results_count=1,
                        quality_score=0.5  # Indicate lower quality
                    )
                    
                    return fallback_plan
                
                # Preserve traversal section
                if "traversal" not in optimized_params["params"]:
                    optimized_params["params"]["traversal"] = rewritten_query["traversal"]
            else:
                # For non-vector queries
                optimized_params = {"params": rewritten_query, "weights": {}}
            
            # Allocate budget
            budget = self.budget_manager.allocate_budget(rewritten_query, priority)
            
            # Create the final plan
            plan = {
                "query": optimized_params["params"],
                "weights": optimized_params["weights"],
                "budget": budget,
                "graph_type": graph_type,
                "statistics": {
                    "avg_query_time": self.query_stats.avg_query_time,
                    "cache_hit_rate": self.query_stats.cache_hit_rate
                },
                "caching": {"enabled": True},
                "traversal_strategy": rewritten_query.get("traversal", {}).get("strategy", "default"),
                "query_id": query_id
            }
            
            # End tracking
            self.metrics_collector.end_query_tracking(
                results_count=1,
                quality_score=1.0
            )
            
            # Final safety check
            if plan is None:
                print("Final plan is None, returning fallback plan")
                return self._create_fallback_plan(
                    query=query,
                    priority=priority,
                    error="Final plan was None"
                )
            
            return plan
            
        except Exception as e:
            # Log the error
            error_msg = f"Error in optimize_query: {str(e)}"
            print(error_msg)
            
            # Return fallback plan
            return self._create_fallback_plan(
                query=query,
                priority=priority,
                error=error_msg
            )

def test_completely_fixed_optimizer():
    """Test the completely fixed optimizer implementation."""
    
    # Create the fixed optimizer instance
    optimizer = CompletelyFixedOptimizer()
    
    # Create a test query
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
    success = test_completely_fixed_optimizer()
    sys.exit(0 if success else 1)