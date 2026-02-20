"""Query statistics tracking for GraphRAG query optimization."""

from __future__ import annotations

import json
import time
from collections import defaultdict
from typing import Any, Dict, List, Tuple


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
        return self.cache_hits / self.query_count
        
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
        self.query_count += 1  # Cache hits are also queries
        self.query_timestamps.append(time.time())
        
    def record_query_pattern(self, pattern: Dict[str, Any]) -> None:
        """
        Record a query pattern for analysis.
        
        Args:
            pattern (Dict): Query pattern representation
        """
        # Convert the pattern to a hashable representation
        pattern_key = json.dumps(pattern, sort_keys=True)
        self.query_patterns[pattern_key] += 1
        
    def get_common_patterns(self, top_n: int = 5) -> List[Tuple[Dict[str, Any], int]]:
        """
        Get the most common query patterns.
        
        Args:
            top_n (int): Number of patterns to return
            
        Returns:
            List[Tuple[Dict, int]]: List of (pattern, count) tuples
        """
        # Sort patterns by frequency
        sorted_patterns = sorted(self.query_patterns.items(), key=lambda x: x[1], reverse=True)
        
        # Convert pattern keys back to dictionaries
        return [(json.loads(pattern), count) for pattern, count in sorted_patterns[:top_n]]
        
    def get_recent_query_times(self, window_seconds: float = 300.0) -> List[float]:
        """
        Get query times from the recent time window.
        
        Args:
            window_seconds (float): Time window in seconds
            
        Returns:
            List[float]: List of query execution times in the window
        """
        current_time = time.time()
        cutoff_time = current_time - window_seconds
        
        # Filter query times by timestamp
        recent_times = []
        for i, timestamp in enumerate(self.query_timestamps):
            if timestamp >= cutoff_time:
                recent_times.append(self.query_times[i])
                
        return recent_times
        
    def get_performance_summary(self) -> Dict[str, Any]:
        """
        Get a summary of query performance statistics.
        
        Returns:
            Dict: Summary statistics
        """
        recent_times = self.get_recent_query_times()
        
        return {
            "query_count": self.query_count,
            "cache_hit_rate": self.cache_hit_rate,
            "avg_query_time": self.avg_query_time,
            "min_query_time": min(self.query_times) if self.query_times else 0.0,
            "max_query_time": max(self.query_times) if self.query_times else 0.0,
            "recent_avg_time": sum(recent_times) / len(recent_times) if recent_times else 0.0,
            "common_patterns": self.get_common_patterns()
        }
        
    def reset(self) -> None:
        """Reset all statistics."""
        self.query_count = 0
        self.cache_hits = 0
        self.total_query_time = 0.0
        self.query_times = []
        self.query_patterns = defaultdict(int)
        self.query_timestamps = []

