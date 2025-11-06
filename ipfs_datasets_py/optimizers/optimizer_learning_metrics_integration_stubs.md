# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/optimizers/optimizer_learning_metrics_integration.py'

Files last updated: 1751466627.7321968

Stub file last updated: 2025-07-07 02:00:12

## MetricsCollectorAdapter

```python
class MetricsCollectorAdapter:
    """
    Adapter that combines query metrics collection with learning metrics collection.

This adapter ensures backward compatibility with existing code that expects
specific methods on the metrics collector, while also providing access to
learning metrics functionality.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, query_metrics_collector = None, learning_metrics_collector: Optional[OptimizerLearningMetricsCollector] = None, metrics_dir: Optional[str] = None):
    """
    Initialize the metrics collector adapter.

Args:
    query_metrics_collector: Existing metrics collector for query metrics
    learning_metrics_collector: Collector for learning metrics
    metrics_dir: Directory to store metrics data
    """
```
* **Async:** False
* **Method:** True
* **Class:** MetricsCollectorAdapter

## create_learning_dashboard

```python
def create_learning_dashboard(self, output_file = None, interactive = True):
    """
    Create a dashboard for learning metrics.

Args:
    output_file: Path to save the dashboard HTML file
    interactive: Whether to create an interactive dashboard

Returns:
    str: Path to the generated dashboard file
    """
```
* **Async:** False
* **Method:** True
* **Class:** MetricsCollectorAdapter

## create_optimizer_with_learning_metrics

```python
def create_optimizer_with_learning_metrics(**kwargs):
    """
    Create a new GraphRAGQueryOptimizer with learning metrics collection.

This function creates a new optimizer instance with learning metrics
collection capabilities.

Args:
    **kwargs: Arguments to pass to the GraphRAGQueryOptimizer constructor

Returns:
    A new GraphRAGQueryOptimizer instance with learning metrics collection
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## end_query_tracking

```python
def end_query_tracking(self, results_count: int = 0, quality_score: float = 0.0, error: str = None) -> None:
    """
    End tracking for the current query.

Args:
    results_count: Number of results returned
    quality_score: Quality score for the results (0.0-1.0)
    error: Error message if the query failed
    """
```
* **Async:** False
* **Method:** True
* **Class:** MetricsCollectorAdapter

## enhance_optimizer_with_learning_metrics

```python
def enhance_optimizer_with_learning_metrics(optimizer, metrics_dir = None):
    """
    Enhance an existing GraphRAGQueryOptimizer with learning metrics collection.

This function adds learning metrics collection capabilities to an existing
optimizer without changing its interface, ensuring backward compatibility.

Args:
    optimizer: The GraphRAGQueryOptimizer instance to enhance
    metrics_dir: Directory to store metrics data

Returns:
    The enhanced optimizer
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## export_metrics_csv

```python
def export_metrics_csv(self, output_file: str = None) -> str:
    """
    Export metrics to a CSV file.

Args:
    output_file: Path to output file, or None to use default

Returns:
    str: Path to the exported file
    """
```
* **Async:** False
* **Method:** True
* **Class:** MetricsCollectorAdapter

## generate_performance_report

```python
def generate_performance_report(self, output_file: str = None) -> str:
    """
    Generate a performance report.

Args:
    output_file: Path to output file, or None to use default

Returns:
    str: Path to the report file
    """
```
* **Async:** False
* **Method:** True
* **Class:** MetricsCollectorAdapter

## get_learning_metrics

```python
def get_learning_metrics(self):
    """
    Get aggregated learning metrics.

Returns:
    LearningMetrics: Object containing aggregated metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** MetricsCollectorAdapter

## get_phase_timing_summary

```python
def get_phase_timing_summary(self, query_id: str = None) -> Dict[str, float]:
    """
    Get a summary of phase timings for a query.

Args:
    query_id: ID of the query to get timings for, or None for current query

Returns:
    Dict: Phase timing summary
    """
```
* **Async:** False
* **Method:** True
* **Class:** MetricsCollectorAdapter

## get_query_metrics

```python
def get_query_metrics(self, query_id: str = None) -> Dict[str, Any]:
    """
    Get metrics for a specific query.

Args:
    query_id: ID of the query to get metrics for, or None for current query

Returns:
    Dict: Query metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** MetricsCollectorAdapter

## get_recent_metrics

```python
def get_recent_metrics(self, count: int = 10) -> List[Dict[str, Any]]:
    """
    Get metrics for the most recent queries.

Args:
    count: Number of recent queries to get metrics for

Returns:
    List[Dict]: List of query metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** MetricsCollectorAdapter

## instrumented_learn_from_query_statistics

```python
def instrumented_learn_from_query_statistics(self, recent_queries_count = 50):
    """
    Instrumented version of _learn_from_query_statistics.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## record_additional_metric

```python
def record_additional_metric(self, name: str, value: Any, category: str = "custom") -> None:
    """
    Record an additional metric that is not tied to a specific query phase.

Args:
    name: Name of the metric
    value: Value of the metric
    category: Category of the metric
    """
```
* **Async:** False
* **Method:** True
* **Class:** MetricsCollectorAdapter

## record_learning_cycle

```python
def record_learning_cycle(self, cycle_id: str, analyzed_queries: int, patterns_identified: int, parameters_adjusted: Dict[str, Any], execution_time: float) -> None:
    """
    Record metrics from a learning cycle.

Args:
    cycle_id: Unique identifier for the learning cycle
    analyzed_queries: Number of queries analyzed in this cycle
    patterns_identified: Number of patterns identified in this cycle
    parameters_adjusted: Parameters that were adjusted
    execution_time: Time taken to execute the learning cycle
    """
```
* **Async:** False
* **Method:** True
* **Class:** MetricsCollectorAdapter

## record_parameter_adaptation

```python
def record_parameter_adaptation(self, parameter_name: str, old_value: Any, new_value: Any, adaptation_reason: str, confidence: float) -> None:
    """
    Record a parameter adaptation.

Args:
    parameter_name: Name of the parameter that was adapted
    old_value: Previous value of the parameter
    new_value: New value of the parameter
    adaptation_reason: Reason for the adaptation
    confidence: Confidence level for the adaptation
    """
```
* **Async:** False
* **Method:** True
* **Class:** MetricsCollectorAdapter

## record_query_pattern

```python
def record_query_pattern(self, pattern_id: str, pattern_type: str, matching_queries: int, average_performance: float, parameters: Dict[str, Any]) -> None:
    """
    Record a query pattern.

Args:
    pattern_id: Unique identifier for the pattern
    pattern_type: Type of pattern
    matching_queries: Number of queries matching this pattern
    average_performance: Average performance metric for this pattern
    parameters: Parameters associated with this pattern
    """
```
* **Async:** False
* **Method:** True
* **Class:** MetricsCollectorAdapter

## record_strategy_effectiveness

```python
def record_strategy_effectiveness(self, strategy_name: str, query_type: str, effectiveness_score: float, execution_time: float, result_count: int) -> None:
    """
    Record the effectiveness of a search strategy.

Args:
    strategy_name: Name of the strategy
    query_type: Type of query the strategy was applied to
    effectiveness_score: Score indicating how effective the strategy was
    execution_time: Time taken to execute the strategy
    result_count: Number of results returned
    """
```
* **Async:** False
* **Method:** True
* **Class:** MetricsCollectorAdapter

## start_query_tracking

```python
def start_query_tracking(self, query_params: Dict[str, Any]) -> str:
    """
    Start tracking a query execution.

Args:
    query_params: Parameters of the query to track

Returns:
    str: Unique identifier for the query
    """
```
* **Async:** False
* **Method:** True
* **Class:** MetricsCollectorAdapter

## time_phase

```python
@contextlib.contextmanager
def time_phase(self, phase_name: str, metadata: Dict[str, Any] = None) -> Generator[None, None, None]:
    """
    Context manager to time a phase of query execution.

Args:
    phase_name: Name of the phase to time
    metadata: Additional metadata about the phase

Yields:
    None
    """
```
* **Async:** False
* **Method:** True
* **Class:** MetricsCollectorAdapter
