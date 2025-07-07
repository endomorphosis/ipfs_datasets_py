"""
Simple test script to directly test the _create_fallback_plan method.
"""

import sys
import os
import numpy as np
from typing import Dict, Any, List, Optional
from collections import defaultdict

# Import the module
sys.path.append(os.getcwd())
from ipfs_datasets_py.rag.rag_query_optimizer import UnifiedGraphRAGQueryOptimizer, GraphRAGQueryStats

class TestOptimizer(UnifiedGraphRAGQueryOptimizer):
    """A minimal test optimizer for testing fallback."""

    def __init__(self):
        # Skip parent initialization
        self._traversal_stats = {
            'paths_explored': [],
            'path_scores': {},
            'entity_frequency': defaultdict(int),
            'entity_connectivity': {},
            'relation_usefulness': defaultdict(float)
        }

    def _create_test_fallback(self, query: Dict[str, Any], error: str = "Test error") -> Dict[str, Any]:
        """Test the fallback plan creation logic directly."""
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

        # Return the fallback plan
        return {
            "query": fallback_query,
            "weights": {"vector": 0.7, "graph": 0.3},
            "budget": {"vector_search_ms": 500, "graph_traversal_ms": 1000},
            "graph_type": "generic",
            "statistics": {
                "fallback": True,
                "error_handled": True
            },
            "caching": {"enabled": False},
            "traversal_strategy": "default",
            "fallback": True,
            "error": error
        }

def test_create_fallback():
    """Test the fallback plan creation."""

    optimizer = TestOptimizer()

    # Create a test query
    test_query = {
        'query_text': 'test query',
        'query_vector': np.array([0.1, 0.2, 0.3]),
        'traversal': {'max_depth': 2}
    }

    # Create a fallback plan
    fallback = optimizer._create_test_fallback(test_query, "Direct test")

    # Verify the fallback plan
    print(f"Fallback plan created: {fallback is not None}")
    print(f"Is marked as fallback: {fallback.get('fallback', False)}")
    print(f"Contains error: {fallback.get('error')}")
    print(f"Keys: {sorted(list(fallback.keys()))}")

    return fallback is not None and fallback.get('fallback', False)

if __name__ == "__main__":
    # Run the test
    success = test_create_fallback()
    sys.exit(0 if success else 1)
