import unittest
import numpy as np

from ipfs_datasets_py.rag.rag_query_optimizer import (
    GraphRAGQueryStats,
    GraphRAGQueryOptimizer,
)

class TestGraphRAGQueryOptimizerMethods(unittest.TestCase):
    """Test case for GraphRAGQueryOptimizer."""

    def setUp(self):
        """Set up test case."""
        self.optimizer = GraphRAGQueryOptimizer()

    def test_optimize_query_method(self):
        """Test the optimize_query method that actually exists."""
        # Create a random query vector
        query_vector = np.random.rand(768)
        
        # Test query optimization with individual parameters
        optimized_params = self.optimizer.optimize_query(
            query_vector=query_vector,
            max_vector_results=5,
            max_traversal_depth=2,
            min_similarity=0.5
        )
        
        # Check that we get optimized parameters back
        self.assertIsInstance(optimized_params, dict)
        self.assertIn("params", optimized_params)
        
    def test_cache_functionality(self):
        """Test cache-related methods that actually exist."""
        query_key = "test_query_key"
        
        # Test cache operations
        self.assertFalse(self.optimizer.is_in_cache(query_key))
        
        # Add something to cache
        test_result = {"result": "test_data"}
        self.optimizer.add_to_cache(query_key, test_result)
        
        # Check it's in cache
        self.assertTrue(self.optimizer.is_in_cache(query_key))
        
        # Retrieve from cache
        cached_result = self.optimizer.get_from_cache(query_key)
        self.assertEqual(cached_result, test_result)

if __name__ == "__main__":
    unittest.main()
