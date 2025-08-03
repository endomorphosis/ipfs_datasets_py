# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/optimizers/optimizer_visualization_integration.py'

Files last updated: 1751436474.4466398

Stub file last updated: 2025-07-07 02:00:12

## LiveOptimizerVisualization

```python
class LiveOptimizerVisualization:
    """
    Integrates metrics collection with real-time visualization for the RAG query optimizer.

This class connects the learning metrics collector to the visualization system,
enabling real-time monitoring and analysis of the optimizer's learning process.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, optimizer = None, metrics_dir: Optional[str] = None, visualization_dir: Optional[str] = None, visualization_interval: int = 3600, dashboard_filename: str = "rag_optimizer_dashboard.html", metrics_source = None):
    """
    Initialize the live visualization integration.

Args:
    optimizer: The RAG query optimizer instance to monitor
    metrics_dir: Directory for storing metrics data
    visualization_dir: Directory for storing visualization outputs
    visualization_interval: Interval in seconds for automatic visualization updates
    dashboard_filename: Filename for the HTML dashboard
    metrics_source: Optional function that returns metrics directly (for simulation)
    """
```
* **Async:** False
* **Method:** True
* **Class:** LiveOptimizerVisualization

## _auto_update_loop

```python
def _auto_update_loop(self):
    """
    Background thread that periodically updates visualizations.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LiveOptimizerVisualization

## add_alert_marker

```python
def add_alert_marker(self, timestamp, alert_type, message):
    """
    Add an alert marker to be displayed on visualizations.

Args:
    timestamp (datetime): When the alert occurred
    alert_type (str): Type of alert (e.g., "oscillation", "performance")
    message (str): Alert message
    """
```
* **Async:** False
* **Method:** True
* **Class:** LiveOptimizerVisualization

## get_learning_metrics_collector

```python
def get_learning_metrics_collector(self) -> OptimizerLearningMetricsCollector:
    """
    Get the learning metrics collector instance.

Returns:
    OptimizerLearningMetricsCollector: The metrics collector
    """
```
* **Async:** False
* **Method:** True
* **Class:** LiveOptimizerVisualization

## inject_sample_data

```python
def inject_sample_data(self, num_cycles = 10, num_adaptations = 20, num_strategies = 30):
    """
    Inject sample data into the metrics collector for testing/demo purposes.

Args:
    num_cycles: Number of learning cycles to simulate
    num_adaptations: Number of parameter adaptations to simulate
    num_strategies: Number of strategy effectiveness entries to simulate
    """
```
* **Async:** False
* **Method:** True
* **Class:** LiveOptimizerVisualization

## setup_metrics_collector

```python
def setup_metrics_collector(self):
    """
    Set up the metrics collector integration with the optimizer.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LiveOptimizerVisualization

## setup_optimizer_visualization

```python
def setup_optimizer_visualization(optimizer = None, metrics_dir = None, visualization_dir = None, auto_update = True, visualization_interval = 3600, dashboard_filename = "rag_optimizer_dashboard.html") -> LiveOptimizerVisualization:
    """
    Set up live visualization for a RAG query optimizer.

Args:
    optimizer: RAG query optimizer instance to visualize
    metrics_dir: Directory for storing metrics data
    visualization_dir: Directory for storing visualization outputs
    auto_update: Whether to enable automatic visualization updates
    visualization_interval: Interval in seconds for visualization updates
    dashboard_filename: Filename for the HTML dashboard

Returns:
    LiveOptimizerVisualization: The configured visualization system
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## start_auto_update

```python
def start_auto_update(self):
    """
    Start automatic periodic updates of visualizations.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LiveOptimizerVisualization

## stop_auto_update

```python
def stop_auto_update(self):
    """
    Stop the automatic visualization updates.
    """
```
* **Async:** False
* **Method:** True
* **Class:** LiveOptimizerVisualization

## update_visualizations

```python
def update_visualizations(self, create_dashboard: bool = True) -> Dict[str, str]:
    """
    Update all visualizations based on current metrics.

Args:
    create_dashboard: Whether to generate a comprehensive dashboard

Returns:
    Dict[str, str]: Paths to generated visualization files
    """
```
* **Async:** False
* **Method:** True
* **Class:** LiveOptimizerVisualization
