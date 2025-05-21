# RAG Optimizer Learning Metrics Integration Plan

## Overview

This plan outlines the integration of the `OptimizerLearningMetricsCollector` with the `GraphRAGQueryOptimizer` class to collect, visualize, and analyze learning metrics for the statistical learning process.

## Current Architecture

### GraphRAGQueryOptimizer
- Has statistical learning capabilities through the `enable_statistical_learning()` method
- Uses `_check_learning_cycle()` to determine when to trigger learning
- Performs learning with `_learn_from_query_statistics()`
- Already has a metrics collector reference (`self.metrics_collector`) but it's not clearly initialized
- Uses a circuit breaker pattern to disable learning after repeated failures

### GraphRAGQueryStats
- Tracks basic query statistics like execution time and cache hits
- Doesn't track learning-specific metrics

### OptimizerLearningMetricsCollector
- Designed to collect and visualize metrics related to the optimizer's learning process
- Tracks learning cycles, parameter adaptations, strategy effectiveness, and query patterns
- Supports both static and interactive visualizations
- Provides methods for analyzing learning trends and effectiveness

## Integration Approach

### 1. Add OptimizerLearningMetricsCollector to GraphRAGQueryOptimizer

Update the `GraphRAGQueryOptimizer.__init__` method to accept and initialize the learning metrics collector:

```python
def __init__(
    self, 
    query_stats: Optional[GraphRAGQueryStats] = None,
    vector_weight: float = 0.7,
    graph_weight: float = 0.3,
    cache_enabled: bool = True,
    cache_ttl: float = 300.0,
    cache_size_limit: int = 100,
    learning_metrics_collector: Optional[OptimizerLearningMetricsCollector] = None
):
    """
    Initialize the query optimizer.
    
    Args:
        query_stats (GraphRAGQueryStats, optional): Query statistics tracker
        vector_weight (float): Weight for vector similarity in hybrid queries
        graph_weight (float): Weight for graph structure in hybrid queries
        cache_enabled (bool): Whether to enable query caching
        cache_ttl (float): Time-to-live for cached results in seconds
        cache_size_limit (int): Maximum number of entries in the cache
        learning_metrics_collector (OptimizerLearningMetricsCollector, optional): 
            Collector for learning-related metrics
    """
    self.query_stats = query_stats or GraphRAGQueryStats()
    self.vector_weight = vector_weight
    self.graph_weight = graph_weight
    self.cache_enabled = cache_enabled
    self.cache_ttl = cache_ttl
    self.cache_size_limit = cache_size_limit
    self.cache = {}
    self.cache_stats = {"hits": 0, "misses": 0}
    
    # Initialize learning-related fields
    self.statistical_learning_enabled = False
    self.learning_interval = 50  # Learn after every 50 queries
    self.learning_history = []
    self.learning_cycle_count = 0
    self.learning_failures = 0
    self.max_failures = 3
    
    # Initialize learning metrics collector
    self.learning_metrics_collector = learning_metrics_collector
```

<!-- Additional content from the original integration plan file would go here -->
