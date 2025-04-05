#\!/usr/bin/env python3

import unittest
import sys
import time
import numpy as np
from collections import defaultdict
import datetime
import json

# Define a simplified version of the GraphRAGQueryStats class with our fixes
class GraphRAGQueryStats:
    """
    Collects and analyzes query statistics for optimization purposes.
    
    This class tracks metrics such as query execution time, cache hit rate,
    and query patterns to inform the query optimizer's decisions.
    """
    
    def __init__(self):
        """Initialize the query statistics tracker."""
        self.query_count = 0
        self.cache_hits = 0
        self.total_query_time = 0.0
        self.query_times = []
        self.query_patterns = defaultdict(int)
        self.query_timestamps = []
        
    @property
    def avg_query_time(self) -> float:
        """Calculate the average query execution time."""
        if self.query_count == 0:
            return 0.0
        return self.total_query_time / self.query_count
        
    @property
    def cache_hit_rate(self) -> float:
        """Calculate the cache hit rate."""
        if self.query_count == 0:
            return 0.0
        # Calculate hit rate as hits / (hits + misses)
        total_operations = self.query_count + self.cache_hits
        return self.cache_hits / total_operations
        
    def record_query_time(self, execution_time: float) -> None:
        """
        Record the execution time of a query.
        
        Args:
            execution_time (float): Query execution time in seconds
        """
        self.query_count += 1
        self.total_query_time += execution_time
        self.query_times.append(execution_time)
        self.query_timestamps.append(time.time())
        
    def record_cache_hit(self) -> None:
        """Record a cache hit."""
        self.cache_hits += 1
        
    def record_query_pattern(self, pattern: dict) -> None:
        """
        Record a query pattern for analysis.
        
        Args:
            pattern (dict): Query pattern representation
        """
        # Convert the pattern to a hashable representation
        pattern_key = json.dumps(pattern, sort_keys=True)
        self.query_patterns[pattern_key] += 1
        
    def get_common_patterns(self, top_n: int = 5):
        """
        Get the most common query patterns.
        
        Args:
            top_n (int): Number of patterns to return
            
        Returns:
            List of (pattern, count) tuples
        """
        # Sort patterns by frequency
        sorted_patterns = sorted(self.query_patterns.items(), key=lambda x: x[1], reverse=True)
        
        # Convert pattern keys back to dictionaries
        return [(json.loads(pattern), count) for pattern, count in sorted_patterns[:top_n]]

# Create simplified optimizer class that demonstrates the cache handling logic
class SimplifiedOptimizer:
    """A simplified optimizer for testing cache logic"""
    
    def __init__(self):
        self.query_stats = GraphRAGQueryStats()
        self.query_cache = {}  # {query_key: (result, timestamp)}
        self.cache_enabled = True
        
    def execute_query_with_caching(self, query_key: str, query_func):
        """Execute a query with caching and statistics tracking."""
        # Check if the query is in cache
        if self.cache_enabled and self.is_in_cache(query_key):
            cached_result = self.get_from_cache(query_key)
            
            # Our fix: Track query statistics for cache hits without incrementing query_count
            if hasattr(self, "query_stats") and self.query_stats is not None:
                # Record cache hit (don't increment query_count for cache hits)
                self.query_stats.record_cache_hit()
                
                # Do NOT call record_query_time for cache hits to avoid incrementing query_count
                # Instead, update other statistics directly
                self.query_stats.total_query_time += 0.001  # Minimal time for cached results
                self.query_stats.query_times.append(0.001)
                self.query_stats.query_timestamps.append(time.time())
            
            return cached_result
        
        # Execute the query
        start_time = time.time()
        result = query_func()
        execution_time = time.time() - start_time
        
        # Track statistics
        if hasattr(self, "query_stats") and self.query_stats is not None:
            self.query_stats.record_query_time(execution_time)
        
        # Cache the result
        if self.cache_enabled:
            self.add_to_cache(query_key, result)
        
        return result
    
    def is_in_cache(self, query_key: str) -> bool:
        """Check if a query is in the cache."""
        return query_key in self.query_cache
    
    def get_from_cache(self, query_key: str):
        """Get a query result from cache."""
        if not self.is_in_cache(query_key):
            raise KeyError(f"Query {query_key} not in cache")
        
        # Record cache hit - this was the issue, but is fixed now in execute_query_with_caching
        # We're not incrementing query_count for cache hits anymore
        return self.query_cache[query_key]
    
    def add_to_cache(self, query_key: str, result) -> None:
        """Add a query result to the cache."""
        self.query_cache[query_key] = result

class TestCaching(unittest.TestCase):
    """Test that caching works correctly."""
    
    def setUp(self):
        """Set up a fresh optimizer for each test."""
        self.optimizer = SimplifiedOptimizer()
    
    def test_query_stats(self):
        """Test that GraphRAGQueryStats correctly tracks query counts and cache hits."""
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
    
    def test_caching_integration(self):
        """Test that caching works correctly in the optimizer."""
        # Create a unique query key
        query_key = "test_query"
        
        # Define a simple query function that returns a value
        def query_func():
            return "test_result"
        
        # Execute the query (should be a cache miss)
        result1 = self.optimizer.execute_query_with_caching(query_key, query_func)
        self.assertEqual(result1, "test_result")
        
        # Check stats after first execution
        self.assertEqual(self.optimizer.query_stats.query_count, 1)
        self.assertEqual(self.optimizer.query_stats.cache_hits, 0)
        
        # Execute the same query again (should be a cache hit)
        result2 = self.optimizer.execute_query_with_caching(query_key, query_func)
        self.assertEqual(result2, "test_result")
        
        # Check stats after second execution - should increment cache_hits but not query_count
        self.assertEqual(self.optimizer.query_stats.query_count, 1)  # Should still be 1
        self.assertEqual(self.optimizer.query_stats.cache_hits, 1)   # Should be 1
        
        # Cache hit rate should be 1/2 = 0.5
        self.assertEqual(self.optimizer.query_stats.cache_hit_rate, 0.5)
        
        print("Caching integration test passed")

if __name__ == "__main__":
    unittest.main()
