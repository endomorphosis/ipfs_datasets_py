"""
Test for the fixed implementation of UnifiedGraphRAGQueryOptimizer.optimize_query.
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

class TestOptimizer(UnifiedGraphRAGQueryOptimizer):
    """A test version of UnifiedGraphRAGQueryOptimizer."""
    
    def __init__(self):
        # Initialize with mocks
        self.metrics_collector = MockMetricsCollector()
        self._traversal_stats = {
            'paths_explored': [], 
            'path_scores': {}, 
            'entity_frequency': defaultdict(int),
            'entity_connectivity': {},
            'relation_usefulness': defaultdict(float)
        }
        self.query_stats = GraphRAGQueryStats()
        self.budget_manager = MockBudgetManager()
        self.rewriter = MockRewriter()
        
        # Replace with the None-returning optimizer
        none_optimizer = NoneReturningOptimizer()
        self.base_optimizer = none_optimizer
        self._specific_optimizers = {
            'general': none_optimizer,
            'wikipedia': none_optimizer,
            'ipld': none_optimizer
        }
        
        # Other required attributes
        self.graph_info = {}
        self.visualizer = None
        self.last_query_id = None
    
    def detect_graph_type(self, query):
        return 'general'
    
    def _detect_entity_types(self, query_text, predefined_types=None):
        return ['concept', 'topic']
    
    def optimize_traversal_path(self, query, graph_processor):
        return query
    
    def _estimate_query_complexity(self, query):
        return 'medium'

def test_fixed_optimizer():
    """Test that the fixed optimizer never returns None."""
    
    # Create a test instance
    optimizer = TestOptimizer()
    
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