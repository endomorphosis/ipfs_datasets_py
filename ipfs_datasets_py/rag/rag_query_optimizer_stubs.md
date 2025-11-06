# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/rag/rag_query_optimizer.py'

Files last updated: 1748635923.4613795

Stub file last updated: 2025-07-07 01:59:52

## GraphRAGProcessor

```python
class GraphRAGProcessor:
    """
    Simple GraphRAG processor for testing purposes.
Provides basic query processing functionality.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## GraphRAGQueryStats

```python
class GraphRAGQueryStats:
    """
    Collects and analyzes query statistics for optimization purposes.

This class tracks metrics such as query execution time, cache hit rate,
and query patterns to inform the query optimizer's decisions.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## QueryMetricsCollector

```python
class QueryMetricsCollector:
    """
    Collects and analyzes detailed metrics for GraphRAG query execution.

This class provides comprehensive metrics collection and analysis capabilities
beyond the basic statistics tracked by GraphRAGQueryStats. It captures fine-grained
timing information, resource utilization, and effectiveness metrics for each query phase.

Key features:
- Phase-by-phase timing measurements with nested timing support
- Resource utilization tracking (memory, CPU)
- Query plan effectiveness scoring
- Metrics persistence and export capabilities
- Historical trend analysis
- Integration with monitoring systems
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## UnifiedGraphRAGQueryOptimizer

```python
class UnifiedGraphRAGQueryOptimizer:
    """
    Unified optimizer for Graph RAG queries
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, max_history_size: int = 1000, metrics_dir: Optional[str] = None, track_resources: bool = True):
    """
    Initialize the metrics collector.

Args:
    max_history_size (int): Maximum number of query metrics to retain in memory
    metrics_dir (str, optional): Directory to store persisted metrics
    track_resources (bool): Whether to track system resource usage during query execution
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## __init__

```python
def __init__(self):
    """
    Initialize the query statistics tracker.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryStats

## __init__

```python
def __init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** UnifiedGraphRAGQueryOptimizer

## __init__

```python
def __init__(self, graph_id = None):
    """
    Initialize the GraphRAG processor
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGProcessor

## _analyze_ipld_performance

```python
def _analyze_ipld_performance(self) -> Dict[str, Any]:
    """
    Analyze IPLD-specific performance metrics and provide recommendations.

Returns:
    Dict: IPLD-specific analysis and recommendations
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## _apply_pattern_to_optimization_defaults

```python
def _apply_pattern_to_optimization_defaults(self, pattern_name: str, pattern_data: Dict[str, Any]):
    """
    Applies a discovered pattern to the optimization default parameters.

Args:
    pattern_name: Name of the pattern
    pattern_data: Pattern characteristics and values
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## _calculate_entity_correlation

```python
def _calculate_entity_correlation(self, successful_queries: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    """
    Calculates correlation between entities in successful queries.

Args:
    successful_queries: List of successful query metrics

Returns:
    Dict: Entity correlation map
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## _check_learning_cycle

```python
def _check_learning_cycle(self):
    """
    Check if it's time to trigger a statistical learning cycle.

This method should be called at the beginning of optimize_query to
determine if enough queries have been processed since the last
learning cycle to trigger a new learning cycle.

The method ensures robust error handling around the learning process,
preventing any learning-related errors from affecting query optimization.

Implements a circuit breaker pattern to disable learning after repeated failures.
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## _cluster_queries_by_performance

```python
def _cluster_queries_by_performance(self, query_metrics: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    """
    Clusters queries into performance categories based on their execution characteristics.

Args:
    query_metrics: List of query metrics data

Returns:
    Dict: Mapping of performance cluster names to lists of queries
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## _derive_wikipedia_specific_rules

```python
def _derive_wikipedia_specific_rules(self, successful_queries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Derives Wikipedia-specific optimization rules from successful query patterns
with robust error handling.

This enhanced version includes comprehensive error handling to ensure the rule
generation process never fails, even with unexpected or malformed input data.

Args:
    successful_queries: List of successful query metrics

Returns:
    List: Wikipedia-specific optimization rules
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## _evaluate_relation_effectiveness

```python
def _evaluate_relation_effectiveness(self, successful_queries: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Evaluates effectiveness of different relation types based on query success.

Args:
    successful_queries: List of successful query metrics

Returns:
    Dict: Relation effectiveness metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## _extract_entities_from_query

```python
def _extract_entities_from_query(self, query: Dict[str, Any]) -> List[str]:
    """
    Extracts entities from a query for correlation analysis.

Args:
    query: Query metrics data

Returns:
    List: Extracted entity IDs
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## _extract_query_patterns

```python
def _extract_query_patterns(self, successful_queries: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
        Extracts common patterns from successful queries with robust error handling.

    This enhanced version includes comprehensive error handling to ensure the pattern
extraction process never fails, even with unexpected or malformed input data.

    Args:
        successful_queries: List of successful query metrics

    Returns:
        Dict: Mapping of pattern names to pattern characteristics
    
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## _generate_optimization_rules

```python
def _generate_optimization_rules(self, patterns: Dict[str, Dict[str, Any]], successful_queries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Generates optimization rules based on discovered patterns.

Args:
    patterns: Dictionary of discovered patterns
    successful_queries: List of successful query metrics

Returns:
    List: Optimization rules derived from patterns
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## _learn_from_query_statistics

```python
def _learn_from_query_statistics(self, recent_queries_count: int = 50) -> Dict[str, Any]:
    """
    Learn from recent query statistics to improve optimization.

Analyzes recent query performance and patterns to generate optimization
rules that can be applied to future queries. Specifically focuses on
Wikipedia-derived knowledge graph patterns.

This enhanced implementation features:
- Transaction safety with backup and rollback capabilities
- Improved error isolation between different processing stages
- Structured logging with categorization (info, warning, error)
- Better data validation and sanitization
- More comprehensive metrics collection for error visibility

Args:
    recent_queries_count: Number of recent queries to analyze

Returns:
    Dict: Learning results and generated optimization rules
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## _numpy_json_serializable

```python
def _numpy_json_serializable(self, obj):
    """
    Convert numpy arrays and types to JSON serializable Python types.
This enhanced version handles nested structures and all numpy types.

Args:
    obj: Any object to make JSON serializable

Returns:
    JSON serializable version of the object
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## _persist_metrics

```python
def _persist_metrics(self, metrics_record: Dict[str, Any]) -> None:
    """
    Persist a single metrics record to a file.

Args:
    metrics_record (Dict): The metrics record to persist.
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## _start_resource_sampling

```python
def _start_resource_sampling(self) -> None:
    """
    Start periodic resource usage sampling.
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## _stop_resource_sampling

```python
def _stop_resource_sampling(self) -> None:
    """
    Stop resource usage sampling and finalize metrics.
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## _update_adaptive_parameters

```python
def _update_adaptive_parameters(self, successful_queries: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """
    Updates adaptive parameters based on successful query patterns.

Args:
    successful_queries: List of successful query metrics

Returns:
    Dict: Updated adaptive parameters
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## avg_query_time

```python
@property
def avg_query_time(self) -> float:
    """
    Calculate the average query execution time.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryStats

## cache_hit_rate

```python
@property
def cache_hit_rate(self) -> float:
    """
    Calculate the cache hit rate.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryStats

## enable_statistical_learning

```python
def enable_statistical_learning(self, enabled: bool = True, learning_cycle: int = 50) -> None:
    """
    Enable or disable statistical learning from past query performance.

When enabled, the optimizer will periodically analyze query performance
and adapt optimization parameters to improve future query results.

Args:
    enabled: Whether to enable statistical learning
    learning_cycle: Number of recent queries to analyze for learning
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## end_phase_timer

```python
def end_phase_timer(self, phase_name: str) -> float:
    """
    End timing for a query execution phase.

Args:
    phase_name (str): Name of the phase to end

Returns:
    float: Duration of the phase in seconds
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## end_query_tracking

```python
def end_query_tracking(self, results_count: int = 0, quality_score: float = 0.0) -> Dict[str, Any]:
    """
    End tracking for the current query and record results.

Args:
    results_count (int): Number of results returned
    quality_score (float): Score indicating quality of results (0.0-1.0)

Returns:
    Dict: The completed metrics record
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## example_usage

```python
def example_usage():
    """
    Example usage of the RAG Query Optimizer components.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## execute_query_with_caching

```python
def execute_query_with_caching(self, query_func: Callable[[np.ndarray, Dict[str, Any]], Any], query_vector: np.ndarray, params: Dict[str, Any], graph_processor: Any = None) -> Any:
    """
    Execute a query with caching and performance tracking.

Args:
    query_func (Callable): Function that executes the query
    query_vector (np.ndarray): Query vector
    params (Dict): Query parameters
    graph_processor (Any, optional): GraphRAG processor for advanced optimizations

Returns:
    Any: Query results
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## export_metrics_csv

```python
def export_metrics_csv(self, filepath: Optional[str] = None) -> Optional[str]:
    """
    Export collected metrics to CSV format.

Args:
    filepath (str, optional): Path to save the CSV file, or None to return as string

Returns:
    str or None: CSV content as string if filepath is None
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## export_metrics_json

```python
def export_metrics_json(self, filepath: Optional[str] = None) -> Optional[str]:
    """
    Export collected metrics to JSON format, handling NumPy arrays properly.

Args:
    filepath (str, optional): Path to save the JSON file, or None to return as string

Returns:
    str or None: JSON content as string if filepath is None
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## export_metrics_to_csv

```python
def export_metrics_to_csv(self, filepath = None):
    """
    Export collected metrics to CSV format.

Args:
    filepath (str, optional): Path to save the CSV file

Returns:
    str or None: CSV content as string if filepath is None, otherwise None
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## generate_performance_report

```python
def generate_performance_report(self, query_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Generate a comprehensive performance report.

Args:
    query_id (str, optional): Specific query ID, or None for all queries

Returns:
    Dict: Performance report
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## get_common_patterns

```python
def get_common_patterns(self, top_n: int = 5) -> List[Tuple[Dict[str, Any], int]]:
    """
    Get the most common query patterns.

Args:
    top_n (int): Number of patterns to return

Returns:
    List[Tuple[Dict, int]]: List of (pattern, count) tuples
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryStats

## get_execution_plan

```python
def get_execution_plan(self, query: Dict[str, Any], priority: str = "normal", graph_processor: Any = None) -> Dict[str, Any]:
    """
    Generate a detailed execution plan without executing the query.

Args:
    query (Dict): Query to plan
    priority (str): Query priority
    graph_processor (Any, optional): GraphRAG processor for advanced optimizations

Returns:
    Dict: Detailed execution plan
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## get_performance_summary

```python
def get_performance_summary(self) -> Dict[str, Any]:
    """
    Get a summary of query performance statistics.

Returns:
    Dict: Summary statistics
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryStats

## get_phase_timing_summary

```python
def get_phase_timing_summary(self, query_id: Optional[str] = None) -> Dict[str, Dict[str, float]]:
    """
    Get a summary of phase timing statistics.

Args:
    query_id (str, optional): Specific query ID, or None for all queries

Returns:
    Dict: Phase timing statistics
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## get_query_metrics

```python
def get_query_metrics(self, query_id: str) -> Optional[Dict[str, Any]]:
    """
    Get metrics for a specific query by ID.

Args:
    query_id (str): The query ID

Returns:
    Dict or None: The metrics record if found
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## get_recent_metrics

```python
def get_recent_metrics(self, count: int = 10) -> List[Dict[str, Any]]:
    """
    Get metrics for the most recent queries.

Args:
    count (int): Maximum number of records to return

Returns:
    List[Dict]: List of recent metrics records
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## get_recent_query_times

```python
def get_recent_query_times(self, window_seconds: float = 300.0) -> List[float]:
    """
    Get query times from the recent time window.

Args:
    window_seconds (float): Time window in seconds

Returns:
    List[float]: List of query execution times in the window
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryStats

## load_learning_state

```python
def load_learning_state(self, filepath = None):
    """
    Load learning state from disk.

Args:
    filepath (str, optional): Path to the state file. If None, uses default location.

Returns:
    bool: True if state was loaded successfully, False otherwise
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## log_event

```python
def log_event(self, level: str, category: str, message: str, data: dict = None):
    """
    Helper function for structured logging with error handling
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## optimize_query

```python
def optimize_query(self, query: Dict[str, Any], priority: str = "normal", graph_processor: Any = None) -> Dict[str, Any]:
    """
    Generate an optimized query plan for execution.

This method analyzes the query and automatically applies optimizations based on graph type,
query characteristics, and historical performance data.

Args:
query: Original query parameters
priority: Query priority level (low, normal, high)
graph_processor: Optional graph processor for entity lookups

Returns:
Dict: Optimized query plan
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## optimize_query

```python
def optimize_query(self, query, context = None):
    """
    Optimize a query for Graph RAG
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnifiedGraphRAGQueryOptimizer

## optimize_traversal

```python
def optimize_traversal(self, start_nodes, target_nodes = None, max_depth = 3):
    """
    Optimize graph traversal between nodes.

Args:
    start_nodes: Starting nodes for traversal
    target_nodes: Optional target nodes
    max_depth: Maximum traversal depth

Returns:
    Dict: Optimized traversal plan
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGProcessor

## process_query

```python
def process_query(self, query, context = None):
    """
    Process a query with GraphRAG functionality.

Args:
    query: The query to process
    context: Optional context for the query

Returns:
    Dict: Processed query results
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGProcessor

## process_results

```python
def process_results(self, results, query):
    """
    Process and rank results
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnifiedGraphRAGQueryOptimizer

## query

```python
def query(self, query_string, query_type = "sparql", max_results = 100):
    """
    Execute a query against the knowledge graph.

Args:
    query_string: The query to execute
    query_type: Type of query (sparql, cypher, etc.)
    max_results: Maximum number of results to return

Returns:
    Dict: Query results with status and data
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGProcessor

## record_additional_metric

```python
def record_additional_metric(self, name: str, value: Any, category: str = "custom") -> None:
    """
    Record an additional custom metric for the current query.

Args:
    name (str): Metric name
    value (Any): Metric value
    category (str): Metric category for organization
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## record_cache_hit

```python
def record_cache_hit(self) -> None:
    """
    Record a cache hit.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryStats

## record_path_performance

```python
def record_path_performance(self, path: List[str], success_score: float, relation_types: List[str] = None) -> None:
    """
    Record the performance of a specific traversal path.

This helps track which paths through the graph are most successful
and can inform future traversal strategy choices.

Args:
    path: List of node IDs in the path
    success_score: How successful this path was (0.0-1.0)
    relation_types: Optional list of relation types in this path
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## record_query_pattern

```python
def record_query_pattern(self, pattern: Dict[str, Any]) -> None:
    """
    Record a query pattern for analysis.

Args:
    pattern (Dict): Query pattern representation
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryStats

## record_query_time

```python
def record_query_time(self, execution_time: float) -> None:
    """
    Record the execution time of a query.

Args:
    execution_time (float): Query execution time in seconds
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryStats

## record_resource_usage

```python
def record_resource_usage(self) -> Dict[str, float]:
    """
    Record current resource usage for the active query.

Returns:
    Dict: Current resource usage metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## reset

```python
def reset(self) -> None:
    """
    Reset all statistics.
    """
```
* **Async:** False
* **Method:** True
* **Class:** GraphRAGQueryStats

## save_learning_state

```python
def save_learning_state(self, filepath = None):
    """
    Save the current learning state to disk.

Args:
    filepath (str, optional): Path to save the state file. If None, uses default location.

Returns:
    str: Path where the state was saved, or None if not saved
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## start_phase_timer

```python
def start_phase_timer(self, phase_name: str, metadata: Optional[Dict[str, Any]] = None) -> None:
    """
    Start timing a query execution phase.

Args:
    phase_name (str): Name of the phase to time
    metadata (Dict, optional): Additional metadata for this phase
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## start_query_tracking

```python
def start_query_tracking(self, query_id: Optional[str] = None, query_params: Optional[Dict[str, Any]] = None) -> str:
    """
    Start tracking a new query execution.

Args:
    query_id (str): Unique identifier for the query
    query_params (Dict): Query parameters

Returns:
    str: The query ID
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## time_phase

```python
@contextmanager
def time_phase(self, phase_name: str, metadata: Optional[Dict[str, Any]] = None) -> Iterator[None]:
    """
    Context manager for timing a specific query phase.

Args:
    phase_name (str): Name of the phase to time
    metadata (Dict, optional): Additional metadata for this phase

Yields:
    None
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## update_relation_usefulness

```python
def update_relation_usefulness(self, relation_type: str, query_success: float) -> None:
    """
    Update the usefulness score for a relation type based on query success.

This method tracks which relation types contribute to successful queries
and helps prioritize the most useful relations in future traversals.

Args:
    relation_type: The type of relation to update
    query_success: Success score (0.0-1.0) for this relation in a query
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## visualize_metrics_dashboard

```python
def visualize_metrics_dashboard(self, query_id = None, output_file = None, include_all_metrics = False):
    """
    Generate a comprehensive metrics dashboard for visualization.

Args:
    query_id (str, optional): Specific query ID to focus on
    output_file (str, optional): Path to save the dashboard
    include_all_metrics (bool): Whether to include all available metrics

Returns:
    str or None: Path to the generated dashboard if successful
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## visualize_performance_comparison

```python
def visualize_performance_comparison(self, query_ids = None, labels = None, output_file = None, show_plot = True):
    """
    Compare performance metrics across multiple queries.

Args:
    query_ids (List[str], optional): List of query IDs to compare
    labels (List[str], optional): Labels for each query
    output_file (str, optional): Optional path to save the visualization
    show_plot (bool): Whether to display the plot

Returns:
    Figure or None: The matplotlib figure if available
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## visualize_query_patterns

```python
def visualize_query_patterns(self, limit = 10, output_file = None, show_plot = True):
    """
    Visualize common query patterns from collected metrics.

Args:
    limit (int): Maximum number of patterns to display
    output_file (str, optional): Path to save the visualization
    show_plot (bool): Whether to display the plot

Returns:
    Figure or None: The matplotlib figure if available
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## visualize_query_plan

```python
def visualize_query_plan(self, query_id = None, output_file = None, show_plot = True, figsize = (12, 8)):
    """
    Visualize the execution plan of a query.

Args:
    query_id (str, optional): Query ID to visualize, most recent if None
    output_file (str, optional): Path to save the visualization
    show_plot (bool): Whether to display the plot
    figsize (tuple): Figure size in inches

Returns:
    Figure or None: The matplotlib figure if available
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## visualize_resource_usage

```python
def visualize_resource_usage(self, query_id = None, output_file = None, show_plot = True):
    """
    Visualize resource usage (memory and CPU) for a specific query.

Args:
    query_id (str, optional): Query ID to visualize, most recent if None
    output_file (str, optional): Path to save the visualization
    show_plot (bool): Whether to display the plot

Returns:
    Figure or None: The matplotlib figure if available
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector
