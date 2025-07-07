# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/optimizers/optimizer_learning_metrics.py'

Files last updated: 1748635923.4613795

Stub file last updated: 2025-07-07 02:00:12

## LearningMetrics

```python
class LearningMetrics:
    """
    Container for aggregated learning metrics.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## NumpyEncoder

```python
class NumpyEncoder(json.JSONEncoder):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## OptimizerLearningMetricsCollector

```python
class OptimizerLearningMetricsCollector:
    """
    Collects and aggregates metrics for statistical learning in the RAG query optimizer.

This class tracks metrics related to the optimizer's learning process, including:
- Learning cycles completion
- Parameter adaptations over time
- Strategy effectiveness
- Query pattern recognition

It provides visualization capabilities for these metrics to help understand
the optimizer's learning behavior and performance improvements over time.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, total_learning_cycles = 0, total_analyzed_queries = 0, total_patterns_identified = 0, total_parameters_adjusted = 0, average_cycle_time = 0.0, total_optimizations = 0):
    """
    Initialize with metrics values.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LearningMetrics

## __init__

```python
def __init__(self, metrics_dir = None, max_history_size = 1000):
    """
    Initialize the learning metrics collector.

Args:
    metrics_dir (str, optional): Directory to store metrics data
    max_history_size (int): Maximum number of learning events to keep in memory
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## _save_learning_metrics

```python
def _save_learning_metrics(self):
    """
    Save learning metrics to JSON file in metrics directory.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## create_interactive_learning_dashboard

```python
def create_interactive_learning_dashboard(self, output_file = None):
    """
    Create an interactive dashboard of learning metrics using Plotly.

Args:
    output_file (str, optional): Path to save the HTML dashboard

Returns:
    str: Path to the generated HTML file, or HTML string if no path provided
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## default

```python
def default(self, obj):
```
* **Async:** False
* **Method:** True
* **Class:** NumpyEncoder

## from_json

```python
@classmethod
def from_json(cls, json_data):
    """
    Create a metrics collector from JSON data.

Args:
    json_data (str): JSON string with metrics data

Returns:
    OptimizerLearningMetricsCollector: Populated metrics collector
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## get_effectiveness_by_query_type

```python
def get_effectiveness_by_query_type(self) -> Dict[str, Dict[str, Any]]:
    """
    Get effectiveness metrics aggregated by query type.

Returns:
    Dict: Query type metrics with counts, average scores, and execution times
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## get_effectiveness_by_strategy

```python
def get_effectiveness_by_strategy(self) -> Dict[str, Dict[str, Any]]:
    """
    Get effectiveness metrics aggregated by strategy.

Returns:
    Dict: Strategy metrics with counts, average scores, and execution times
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## get_learning_metrics

```python
def get_learning_metrics(self) -> LearningMetrics:
    """
    Get aggregated learning metrics.

Returns:
    LearningMetrics: Object containing aggregated metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## get_patterns_by_type

```python
def get_patterns_by_type(self) -> Dict[str, Dict[str, Any]]:
    """
    Get query patterns aggregated by pattern type.

Returns:
    Dict: Pattern type metrics with counts and query matches
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## record_learning_cycle

```python
def record_learning_cycle(self, cycle_id, analyzed_queries, patterns_identified, parameters_adjusted, execution_time, timestamp = None):
    """
    Record metrics from a completed learning cycle.

Args:
    cycle_id (str): Unique identifier for the learning cycle
    analyzed_queries (int): Number of queries analyzed in this cycle
    patterns_identified (int): Number of patterns identified in this cycle
    parameters_adjusted (dict): Parameters adjusted as a result of learning
    execution_time (float): How long the cycle took to execute (seconds)
    timestamp (float, optional): Timestamp of the cycle completion
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## record_parameter_adaptation

```python
def record_parameter_adaptation(self, parameter_name, old_value, new_value, adaptation_reason, confidence, timestamp = None):
    """
    Record a parameter adaptation from the learning process.

Args:
    parameter_name (str): Name of the parameter that was adapted
    old_value (Any): Previous value of the parameter
    new_value (Any): New value of the parameter
    adaptation_reason (str): Reason for the adaptation
    confidence (float): Confidence level for the adaptation (0.0-1.0)
    timestamp (float, optional): When the adaptation occurred
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## record_query_pattern

```python
def record_query_pattern(self, pattern_id, pattern_type, matching_queries, average_performance, parameters, timestamp = None):
    """
    Record a query pattern identified by the optimizer.

Args:
    pattern_id (str): Unique identifier for the pattern
    pattern_type (str): Type of pattern (e.g., "semantic", "lexical", "structural")
    matching_queries (int): Number of queries matching this pattern
    average_performance (float): Average performance metric for this pattern
    parameters (dict): Parameters associated with this pattern
    timestamp (float, optional): When the pattern was identified
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## record_strategy_effectiveness

```python
def record_strategy_effectiveness(self, strategy_name, query_type, effectiveness_score, execution_time, result_count, timestamp = None):
    """
    Record the effectiveness of a search strategy.

Args:
    strategy_name (str): Name of the strategy (e.g., "depth_first", "breadth_first")
    query_type (str): Type of query the strategy was applied to
    effectiveness_score (float): Score indicating how effective the strategy was (0.0-1.0)
    execution_time (float): Time taken to execute the strategy (seconds)
    result_count (int): Number of results returned
    timestamp (float, optional): When the strategy was evaluated
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## to_json

```python
def to_json(self):
    """
    Convert metrics data to JSON for serialization.

Returns:
    str: JSON string representation of metrics data
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## visualize_learning_cycles

```python
def visualize_learning_cycles(self, output_file = None, show_plot = False):
    """
    Visualize learning cycles over time.

Args:
    output_file (str, optional): Path to save the visualization
    show_plot (bool): Whether to display the plot (not recommended for headless environments)

Returns:
    matplotlib.figure.Figure: The generated figure
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## visualize_learning_performance

```python
def visualize_learning_performance(self, output_file = None, show_plot = False):
    """
    Visualize the performance of the learning process over time.

Args:
    output_file (str, optional): Path to save the visualization
    show_plot (bool): Whether to display the plot

Returns:
    matplotlib.figure.Figure: The generated figure
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## visualize_parameter_adaptations

```python
def visualize_parameter_adaptations(self, output_file = None, show_plot = False):
    """
    Visualize parameter adaptations over time.

Args:
    output_file (str, optional): Path to save the visualization
    show_plot (bool): Whether to display the plot

Returns:
    matplotlib.figure.Figure: The generated figure
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## visualize_query_patterns

```python
def visualize_query_patterns(self, output_file = None, show_plot = False):
    """
    Visualize the query patterns identified by the optimizer.

Args:
    output_file (str, optional): Path to save the visualization
    show_plot (bool): Whether to display the plot

Returns:
    matplotlib.figure.Figure: The generated figure
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## visualize_strategy_effectiveness

```python
def visualize_strategy_effectiveness(self, output_file = None, show_plot = False):
    """
    Visualize the effectiveness of different search strategies.

Args:
    output_file (str, optional): Path to save the visualization
    show_plot (bool): Whether to display the plot

Returns:
    matplotlib.figure.Figure: The generated figure
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector
