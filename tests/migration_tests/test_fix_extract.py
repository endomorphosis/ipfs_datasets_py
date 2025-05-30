#\!/usr/bin/env python3

import unittest
import sys
import time
from collections import defaultdict
import datetime
import json

sys.path.insert(0, '.')
from ipfs_datasets_py.rag_query_optimizer import GraphRAGQueryStats

class TestRagQueryStats(unittest.TestCase):

    def test_query_stats(self):
        """Test that GraphRAGQueryStats works correctly with cache hits."""
        stats = GraphRAGQueryStats()

        # Initial state
        self.assertEqual(stats.query_count, 0)
        self.assertEqual(stats.cache_hits, 0)

        # Record a query (simulating a cache miss)
        stats.record_query_time(0.1)
        self.assertEqual(stats.query_count, 1)
        self.assertEqual(stats.cache_hits, 0)

        # Record a cache hit
        stats.record_cache_hit()
        # The query count should not change
        self.assertEqual(stats.query_count, 1)
        self.assertEqual(stats.cache_hits, 1)

        # Cache hit rate should be 1/2 = 0.5
        self.assertEqual(stats.cache_hit_rate, 0.5)

        print("Query stats test passed")

if __name__ == "__main__":
    unittest.main()
