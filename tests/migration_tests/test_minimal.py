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

    def test_execute_query_with_caching(self):
        """Test query execution with caching."""
        # Create a random query vector
        query_vector = np.random.rand(768)

        # Create a mock query function
        def query_func(query_vector, params):
            return {"result": "test"}

        # Execute query
        params = {"max_vector_results": 5, "max_traversal_depth": 2}
        result1 = self.optimizer.execute_query_with_caching(
            query_func=query_func,
            query_vector=query_vector,
            params=params
        )

        # Execute same query again
        result2 = self.optimizer.execute_query_with_caching(
            query_func=query_func,
            query_vector=query_vector,
            params=params
        )

        # Check that results are the same
        self.assertEqual(result1, result2)

    def test_analyze_query_performance(self):
        """Test query performance analysis."""
        # Record some query statistics
        self.optimizer.query_stats.record_query_time(0.5)
        self.optimizer.query_stats.record_query_time(0.7)
        self.optimizer.query_stats.record_cache_hit()

        # Analyze performance
        analysis = self.optimizer.analyze_query_performance()

        # Check that analysis has expected structure
        self.assertIn("statistics", analysis)
        self.assertIn("recommendations", analysis)
        self.assertIn("weights", analysis)

        # Check statistics
        stats = analysis["statistics"]
        self.assertEqual(stats["query_count"], 2)
        self.assertEqual(stats["cache_hit_rate"], 0.5)
        self.assertAlmostEqual(stats["avg_query_time"], 0.6)

if __name__ == "__main__":
    unittest.main()
