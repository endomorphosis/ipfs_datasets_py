# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/rag/rag_query_visualization.py'

Files last updated: 1748635923.4613795

Stub file last updated: 2025-07-07 01:59:52

## EnhancedQueryVisualizer

```python
class EnhancedQueryVisualizer(RAGQueryVisualizer):
    """
    Enhanced version of query visualizer with additional interactive
and advanced visualization capabilities.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## EnhancedQueryVisualizer

```python
class EnhancedQueryVisualizer(RAGQueryVisualizer):
    """
    Enhanced visualization tools for RAG query metrics with better audit integration.

This class extends the base RAGQueryVisualizer with additional methods for creating
more sophisticated visualizations and providing better integration with the audit
visualization system. It provides comprehensive visualization of query performance,
anomalies, and correlation with security events.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## MockLearningMetricsCollector

```python
class MockLearningMetricsCollector:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## OptimizerLearningMetricsCollector

```python
class OptimizerLearningMetricsCollector:
    """
    Collects and analyzes metrics from the RAG query optimizer's statistical learning process.

This class provides visualization and analysis of the optimizer's learning performance,
allowing monitoring of learning cycles, parameter adaptations, and optimization effectiveness.
    """
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

## PerformanceMetricsVisualizer

```python
class PerformanceMetricsVisualizer:
    """
    Specialized visualizer for query performance metrics analysis.

This class focuses on visualizing the detailed performance metrics of RAG queries,
including processing time breakdowns, component contributions to latency,
throughput analysis, and resource utilization patterns.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## PerformanceMetricsVisualizer

```python
class PerformanceMetricsVisualizer:
    """
    Specialized visualizer for query performance metrics analysis.

This class focuses on visualizing the detailed performance metrics of RAG queries,
including processing time breakdowns, component contributions to latency,
throughput analysis, and resource utilization patterns.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## QueryMetricsCollector

```python
class QueryMetricsCollector:
    """
    Collects and analyzes metrics for RAG queries.

This class records detailed metrics about query execution, including timing data,
query parameters, and results. It provides methods for analyzing query performance,
detecting anomalies, and generating statistical summaries.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## QueryMetricsCollector

```python
class QueryMetricsCollector:
    """
    Collects and aggregates metrics from RAG query executions.

This class tracks query performance, results, and patterns to identify trends,
anomalies, and optimization opportunities in RAG system usage.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## RAGQueryDashboard

```python
class RAGQueryDashboard:
    """
    Interactive dashboard for monitoring and analyzing RAG query performance.

This class integrates query metrics, visualization, and audit logs to
provide a comprehensive monitoring system.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## RAGQueryDashboard

```python
class RAGQueryDashboard:
    """
    Comprehensive dashboard for RAG queries with integrated audit and learning metrics.

This class provides a unified dashboard that combines RAG query metrics
with audit metrics and statistical learning metrics to provide a complete picture
of system performance, optimization effectiveness, and security behavior.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## RAGQueryVisualizer

```python
class RAGQueryVisualizer:
    """
    Visualizes metrics and performance data for RAG queries.

This class generates various visualizations for analyzing RAG query performance,
including timelines, histograms, and statistical charts.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## RAGQueryVisualizer

```python
class RAGQueryVisualizer:
    """
    Visualization tools for RAG query metrics.

This class provides methods for creating visualizations of query performance,
patterns, and optimization opportunities to help understand and improve
RAG system behavior.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, window_size = 3600):
    """
    Initialize the metrics collector.

Args:
    window_size (int): Time window for metrics in seconds (default: 1 hour)
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## __init__

```python
def __init__(self, metrics_collector):
    """
    Initialize the query visualizer.

Args:
    metrics_collector (QueryMetricsCollector): Metrics collector with query data
    """
```
* **Async:** False
* **Method:** True
* **Class:** RAGQueryVisualizer

## __init__

```python
def __init__(self, metrics_collector):
    """
    Initialize the enhanced query visualizer.

Args:
    metrics_collector (QueryMetricsCollector): Metrics collector with query data
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedQueryVisualizer

## __init__

```python
def __init__(self, metrics_collector, visualizer = None, dashboard_dir = None, audit_logger = None):
    """
    Initialize the RAG query dashboard.

Args:
    metrics_collector (QueryMetricsCollector): Query metrics collector
    visualizer (EnhancedQueryVisualizer, optional): Query visualizer
    dashboard_dir (str, optional): Directory for dashboard files
    audit_logger (object, optional): Audit logger for security events
    """
```
* **Async:** False
* **Method:** True
* **Class:** RAGQueryDashboard

## __init__

```python
def __init__(self, metrics_collector):
    """
    Initialize the performance metrics visualizer.

Args:
    metrics_collector: QueryMetricsCollector instance with query metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** PerformanceMetricsVisualizer

## __init__

```python
def __init__(self, window_size: int = 86400):
    """
    Initialize the query metrics collector.

Args:
    window_size: Time window in seconds for metrics retention
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## __init__

```python
def __init__(self, metrics_collector: QueryMetricsCollector):
    """
    Initialize the visualizer with a metrics collector.

Args:
    metrics_collector: QueryMetricsCollector instance with query metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** RAGQueryVisualizer

## __init__

```python
def __init__(self, max_history_size = 1000):
    """
    Initialize the learning metrics collector.

Args:
    max_history_size (int): Maximum number of learning events to store
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## __init__

```python
def __init__(self, metrics_collector: QueryMetricsCollector):
    """
    Initialize the performance metrics visualizer.

Args:
    metrics_collector: QueryMetricsCollector instance with query metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** PerformanceMetricsVisualizer

## __init__

```python
def __init__(self):
    """
    Initialize the metrics collector.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## __init__

```python
def __init__(self, metrics_collector: QueryMetricsCollector, audit_metrics = None, learning_metrics = None, dashboard_dir = None, refresh_interval = 60):
    """
    Initialize the dashboard with enhanced monitoring capabilities.

Args:
    metrics_collector: QueryMetricsCollector with query metrics
    audit_metrics: Optional AuditMetricsAggregator instance
    learning_metrics: Optional OptimizerLearningMetricsCollector instance
    dashboard_dir: Directory to store dashboard files
    refresh_interval: Dashboard refresh interval in seconds for auto-refresh
    """
```
* **Async:** False
* **Method:** True
* **Class:** RAGQueryDashboard

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

## __init__

```python
def __init__(self):
```
* **Async:** False
* **Method:** True
* **Class:** MockLearningMetricsCollector

## _analyze_query_patterns

```python
def _analyze_query_patterns(self) -> None:
    """
    Analyze query patterns to identify trends and optimization opportunities.
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## _calculate_change

```python
def _calculate_change(self, old_value, new_value):
    """
    Calculate relative change between values.

Args:
    old_value: Previous value
    new_value: New value

Returns:
    float: Relative change or None if not calculable
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## _calculate_delta

```python
def _calculate_delta(self, old_value, new_value):
    """
    Calculate delta between old and new values, handling different types.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## _calculate_hourly_trends

```python
def _calculate_hourly_trends(self, queries):
    """
    Calculate hourly trends from query data.

Args:
    queries (dict): Query data dictionary

Returns:
    dict: Hourly trends statistics
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## _check_for_anomalies

```python
def _check_for_anomalies(self, query_id, query_data):
    """
    Check if a query is anomalous based on defined thresholds.

Args:
    query_id (str): Query identifier
    query_data (dict): Query metrics data
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## _check_for_anomalies

```python
def _check_for_anomalies(self, query_id: str) -> None:
    """
    Check for anomalies in the query metrics.

Args:
    query_id: The ID of the query to check
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## _check_if_active

```python
def _check_if_active(self, events):
    """
    Check if learning appears to be active based on recent events.

Args:
    events: List of recent learning events

Returns:
    bool: True if learning appears active, False otherwise
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## _cleanup_old_queries

```python
def _cleanup_old_queries(self) -> None:
    """
    Remove queries older than the specified window size.
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## _convert_to_serializable

```python
def _convert_to_serializable(self, obj):
    """
    Convert objects to JSON serializable format.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## _create_dashboard_html

```python
def _create_dashboard_html(self, plotly_figure: str, title: str) -> str:
    """
    Create HTML dashboard from template.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PerformanceMetricsVisualizer

## _create_dashboard_html

```python
def _create_dashboard_html(self, metrics: Dict[str, Any], visualizations: List[Dict[str, str]], theme: str = "light") -> str:
    """
    Create HTML for the learning dashboard.

Args:
    metrics: Dictionary of learning metrics
    visualizations: List of visualization details
    theme: Dashboard theme ('light' or 'dark')

Returns:
    HTML content for the dashboard
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## _create_interactive_learning_visualization

```python
def _create_interactive_learning_visualization(self, output_file = None):
    """
    Create interactive Plotly visualization of learning metrics.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## _create_interactive_query_audit_timeline

```python
def _create_interactive_query_audit_timeline(self, audit_metrics_aggregator, hours_back: int = 24, interval_minutes: int = 30, theme: str = "light", title: str = "Interactive Query & Audit Timeline", output_file: Optional[str] = None, show_plot: bool = False) -> Optional[Any]:
    """
    Create an interactive timeline visualization with plotly.

Args:
    audit_metrics_aggregator: AuditMetricsAggregator with audit metrics
    hours_back: Number of hours to look back
    interval_minutes: Time interval in minutes for aggregation
    theme: 'light' or 'dark' color theme
    title: Title for the visualization
    output_file: Optional path to save the interactive HTML
    show_plot: Whether to display the plot

Returns:
    plotly.graph_objects.Figure: The interactive figure object
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedQueryVisualizer

## _create_interactive_security_correlation

```python
def _create_interactive_security_correlation(self, audit_metrics_aggregator, hours_back: int = 24, interval_minutes: int = 15, event_categories: List[str] = None, min_severity: str = "WARNING", output_file: Optional[str] = None, show_plot: bool = False) -> Optional[Any]:
    """
    Create an interactive visualization of security events and query performance correlation.

This advanced visualization combines query performance metrics with security events
to help identify potential correlations between security incidents and query performance
issues. The interactive plot allows drilling down into specific time periods and events
to investigate anomalies and understand the relationship between security posture and
system performance.

Args:
    audit_metrics_aggregator: AuditMetricsAggregator containing audit metrics
    hours_back: Number of hours to look back
    interval_minutes: Time interval in minutes for aggregation
    event_categories: List of audit event categories to include (None for all)
    min_severity: Minimum severity level to include
    output_file: Optional path to save the visualization
    show_plot: Whether to display the plot

Returns:
    plotly.graph_objects.Figure: The interactive figure
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedQueryVisualizer

## _create_pattern_key

```python
def _create_pattern_key(self, pattern):
    """
    Create a stable string key from a pattern dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## _create_static_learning_visualization

```python
def _create_static_learning_visualization(self, output_file = None):
    """
    Create static matplotlib visualization of learning metrics.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## _create_static_performance_dashboard

```python
def _create_static_performance_dashboard(self, title: str, processing_chart: str, latency_chart: str, throughput_chart: str, complexity_chart: str) -> str:
    """
    Create a static HTML dashboard from image files.

Args:
    title: Dashboard title
    processing_chart: Path to processing breakdown chart
    latency_chart: Path to latency distribution chart
    throughput_chart: Path to throughput chart
    complexity_chart: Path to complexity chart

Returns:
    str: HTML content for the dashboard
    """
```
* **Async:** False
* **Method:** True
* **Class:** RAGQueryDashboard

## _extract_summary_metrics

```python
def _extract_summary_metrics(self, time_window = None):
    """
    Extract summary metrics from query collector for dashboard display.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PerformanceMetricsVisualizer

## _generate_learning_cycles

```python
def _generate_learning_cycles(self):
    """
    Generate sample learning cycle data.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockLearningMetricsCollector

## _generate_parameter_adaptations

```python
def _generate_parameter_adaptations(self):
    """
    Generate sample parameter adaptation data.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockLearningMetricsCollector

## _generate_strategy_effectiveness

```python
def _generate_strategy_effectiveness(self):
    """
    Generate sample strategy effectiveness data.
    """
```
* **Async:** False
* **Method:** True
* **Class:** MockLearningMetricsCollector

## _get_complexity_data

```python
def _get_complexity_data(self) -> List[Dict[str, Any]]:
    """
    Get data for complexity visualization.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PerformanceMetricsVisualizer

## _get_latency_distribution_data

```python
def _get_latency_distribution_data(self) -> List[float]:
    """
    Get data for latency distribution visualization.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PerformanceMetricsVisualizer

## _get_processing_breakdown_data

```python
def _get_processing_breakdown_data(self) -> Dict[str, float]:
    """
    Get data for processing time breakdown visualization.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PerformanceMetricsVisualizer

## _get_throughput_data

```python
def _get_throughput_data(self, hours: int = 24, interval_minutes: int = 10) -> List[Dict[str, Any]]:
    """
    Get data for throughput visualization.
    """
```
* **Async:** False
* **Method:** True
* **Class:** PerformanceMetricsVisualizer

## _save_metrics_to_disk

```python
def _save_metrics_to_disk(self, filename, data):
    """
    Save metrics data to disk in JSON format.
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## add_alert_handler

```python
def add_alert_handler(self, handler: Callable[[Dict[str, Any]], None]) -> None:
    """
    Add a handler for query anomaly alerts.

Args:
    handler: Function that processes anomaly notifications
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## create_dashboard

```python
def create_dashboard(output_file: str, query_metrics: QueryMetricsCollector, audit_metrics = None, title: str = "RAG Query Dashboard", include_anomalies: bool = True) -> str:
    """
    Generate a comprehensive dashboard for RAG query analysis.

This function creates a dashboard HTML file with visualizations of query metrics,
anomaly information, and integrated audit data if available.

Args:
    output_file: Path to save the dashboard HTML file
    query_metrics: QueryMetricsCollector with query metrics
    audit_metrics: Optional AuditMetricsAggregator for integrated audit data
    title: Dashboard title
    include_anomalies: Whether to include anomaly information

Returns:
    str: Path to the generated dashboard file
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## create_integrated_monitoring_system

```python
def create_integrated_monitoring_system(dashboard_dir = None):
    """
    Create an integrated monitoring system for RAG queries.

Args:
    dashboard_dir (str, optional): Directory for dashboard files

Returns:
    tuple: (audit_logger, audit_metrics, query_metrics, dashboard)
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## create_integrated_monitoring_system

```python
def create_integrated_monitoring_system(dashboard_dir: str = None):
    """
    Create an integrated monitoring system with audit logging and query metrics.

Args:
    dashboard_dir: Optional directory for dashboard output

Returns:
    tuple: (audit_logger, audit_metrics, query_metrics, dashboard)
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## create_interactive_dashboard

```python
def create_interactive_dashboard(self, output_dir, time_window = None):
    """
    Create an interactive HTML dashboard with multiple visualizations.

Args:
    output_dir (str): Directory to save dashboard files
    time_window (int, optional): Time window in seconds

Returns:
    str: Path to the generated dashboard HTML file
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedQueryVisualizer

## create_interactive_learning_dashboard

```python
def create_interactive_learning_dashboard(self, output_file: str, theme: str = "light") -> Optional[str]:
    """
    Create an interactive HTML dashboard for all learning metrics.

Args:
    output_file: Path to save the HTML dashboard
    theme: Visualization theme ('light' or 'dark')

Returns:
    Path to the saved dashboard file or None if creation failed
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## create_interactive_learning_dashboard

```python
def create_interactive_learning_dashboard(self, output_file, show_plot = False):
    """
    Create an interactive dashboard for learning metrics visualization using Plotly.

Args:
    output_file (str): Path to save the HTML dashboard
    show_plot (bool): Whether to display the plot

Returns:
    str: Path to the generated dashboard
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## create_interactive_performance_dashboard

```python
def create_interactive_performance_dashboard(self, output_file: Optional[str] = None) -> Optional[str]:
    """
    Create an interactive HTML dashboard with plotly visualizations.

Args:
    output_file: Path to save the HTML dashboard

Returns:
    Path to the saved dashboard or None if required libraries not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** PerformanceMetricsVisualizer

## create_learning_metrics_visualizations

```python
def create_learning_metrics_visualizations(output_dir = None, theme = "light"):
    """
    Create example visualizations for RAG query optimizer learning metrics.

This function demonstrates the visualization capabilities for learning metrics
by creating sample visualizations using simulated data.

Args:
    output_dir: Directory to save visualizations
    theme: Color theme ('light' or 'dark')

Returns:
    Dict of visualization file paths
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## export_metrics_report

```python
def export_metrics_report(self, format: str = "html", output_file: Optional[str] = None) -> Union[str, Dict[str, Any]]:
    """
    Export metrics report in the specified format.

Args:
    format: Report format ("html" or "json")
    output_file: Optional path to save the report

Returns:
    str or Dict: Report content
    """
```
* **Async:** False
* **Method:** True
* **Class:** RAGQueryVisualizer

## generate_dashboard

```python
def generate_dashboard(self, time_window = None):
    """
    Generate the query monitoring dashboard.

Args:
    time_window (int, optional): Time window in seconds

Returns:
    str: Path to the generated dashboard
    """
```
* **Async:** False
* **Method:** True
* **Class:** RAGQueryDashboard

## generate_dashboard

```python
def generate_dashboard(self, output_file: str, title: str = "RAG Query Analytics Dashboard", include_audit_metrics: bool = True, include_performance_metrics: bool = True) -> str:
    """
    Generate a combined dashboard with query and audit metrics.

Args:
    output_file: Path to save the dashboard HTML
    title: Dashboard title
    include_audit_metrics: Whether to include audit metrics
    include_performance_metrics: Whether to include detailed performance metrics

Returns:
    str: Path to the generated dashboard
    """
```
* **Async:** False
* **Method:** True
* **Class:** RAGQueryDashboard

## generate_dashboard_html

```python
def generate_dashboard_html(self, title: str = "RAG Query Performance Dashboard", include_optimization: bool = True, include_patterns: bool = True, include_security_correlation: bool = True, anomalies: List[Dict[str, Any]] = None, audit_metrics = None) -> str:
    """
    Generate an HTML dashboard with query metrics and visualizations.

Args:
    title: Dashboard title
    include_optimization: Whether to include optimization suggestions
    include_patterns: Whether to include query pattern analysis
    include_security_correlation: Whether to include security correlation visualization
    anomalies: Optional list of query anomalies to display
    audit_metrics: Optional AuditMetricsAggregator for integrated audit data

Returns:
    str: HTML dashboard content
    """
```
* **Async:** False
* **Method:** True
* **Class:** RAGQueryVisualizer

## generate_integrated_dashboard

```python
def generate_integrated_dashboard(self, output_file: str, audit_metrics_aggregator = None, learning_metrics_collector = None, title: str = "Integrated Query Performance & Security Dashboard", include_performance: bool = True, include_security: bool = True, include_security_correlation: bool = True, include_query_audit_timeline: bool = True, include_learning_metrics: bool = True, interactive: bool = True, theme: str = "light") -> str:
    """
    Generate a comprehensive dashboard integrating RAG query metrics with audit security and learning metrics.

This dashboard provides a unified view of performance, security, and learning aspects,
enabling correlation analysis between performance issues, security events, and
optimization learning statistics.

Args:
    output_file: Path to save the dashboard HTML
    audit_metrics_aggregator: Optional metrics aggregator (uses self.audit_metrics if None)
    learning_metrics_collector: Optional learning metrics collector (uses self.learning_metrics if None)
    title: Dashboard title
    include_performance: Whether to include performance metrics
    include_security: Whether to include security metrics
    include_security_correlation: Whether to include security correlation visualization
    include_query_audit_timeline: Whether to include combined timeline
    include_learning_metrics: Whether to include optimizer learning metrics
    interactive: Whether to generate interactive visualizations
    theme: 'light' or 'dark' color theme

Returns:
    str: Path to the generated dashboard
    """
```
* **Async:** False
* **Method:** True
* **Class:** RAGQueryDashboard

## generate_interactive_audit_trends

```python
def generate_interactive_audit_trends(self, output_file = None):
    """
    Generate interactive audit trend visualization.

Args:
    output_file (str, optional): Output file path

Returns:
    str: Path to the generated visualization
    """
```
* **Async:** False
* **Method:** True
* **Class:** RAGQueryDashboard

## generate_interactive_audit_trends

```python
def generate_interactive_audit_trends(self, output_file: str, audit_metrics_aggregator = None, period: str = "daily", lookback_days: int = 7, categories: List[str] = None, theme: str = "light", title: str = "Interactive Audit Event Trends", show_plot: bool = False) -> Optional[Any]:
    """
    Generate interactive visualization of audit trends.

Args:
    output_file: Path to save the visualization
    audit_metrics_aggregator: Optional metrics aggregator (uses self.audit_metrics if None)
    period: Aggregation period ('hourly', 'daily', 'weekly')
    lookback_days: Number of days to look back
    categories: Optional list of specific categories to include
    theme: 'light' or 'dark' color theme
    title: Title for the visualization
    show_plot: Whether to display the plot

Returns:
    Optional[Any]: Plotly figure object if successful
    """
```
* **Async:** False
* **Method:** True
* **Class:** RAGQueryDashboard

## generate_performance_dashboard

```python
def generate_performance_dashboard(self, output_file: str) -> Optional[str]:
    """
    Generate a comprehensive performance metrics dashboard.

This dashboard focuses on detailed performance analysis of RAG queries,
including processing time breakdowns, latency distributions, throughput
analysis, and complexity correlations.

Args:
    output_file: Path to save the dashboard HTML

Returns:
    str: Path to the generated dashboard or None if failure
    """
```
* **Async:** False
* **Method:** True
* **Class:** RAGQueryDashboard

## generate_performance_report

```python
def generate_performance_report(self, output_file = None, time_window = None):
    """
    Generate a comprehensive performance report with visualizations.

Args:
    output_file (str, optional): Output file path
    time_window (int, optional): Time window in seconds

Returns:
    str: Path to the generated report
    """
```
* **Async:** False
* **Method:** True
* **Class:** RAGQueryDashboard

## get_learning_metrics

```python
def get_learning_metrics(self) -> Dict[str, Any]:
    """
    Get summary metrics about the learning process.

Returns:
    Dict containing learning metrics and statistics
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## get_learning_metrics

```python
def get_learning_metrics(self):
    """
    Get aggregated learning metrics.

Returns:
    dict: Aggregated metrics about the learning process
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## get_learning_performance_metrics

```python
def get_learning_performance_metrics(self, window_seconds = 86400):
    """
    Get performance metrics for learning cycles within a time window.

Args:
    window_seconds: Time window in seconds (default: 24 hours)

Returns:
    dict: Learning performance metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## get_optimization_opportunities

```python
def get_optimization_opportunities(self) -> Dict[str, Any]:
    """
    Get recommended optimization opportunities based on query patterns.

Returns:
    Dict[str, Any]: Optimization suggestions
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## get_parameter_history

```python
def get_parameter_history(self, param_name = None, limit = None):
    """
    Get parameter adaptation history.

Args:
    param_name (str, optional): Specific parameter to get history for
    limit (int, optional): Maximum number of entries to return

Returns:
    dict: Parameter adaptation history
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## get_performance_metrics

```python
def get_performance_metrics(self, time_window = None):
    """
    Get performance metrics based on recorded queries.

Args:
    time_window (int, optional): Time window in seconds, defaults to instance window_size

Returns:
    dict: Performance metrics and statistics
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## get_performance_metrics

```python
def get_performance_metrics(self) -> Dict[str, Any]:
    """
    Get performance metrics summary.

Returns:
    Dict[str, Any]: Summary of query performance metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## get_query_patterns

```python
def get_query_patterns(self) -> Dict[str, Any]:
    """
    Get query pattern insights.

Returns:
    Dict[str, Any]: Information about query patterns and trends
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## get_relative_path

```python
def get_relative_path(path):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## get_strategy_metrics

```python
def get_strategy_metrics(self, strategy_name = None):
    """
    Get metrics for optimization strategies.

Args:
    strategy_name (str, optional): Specific strategy to get metrics for

Returns:
    dict: Strategy effectiveness metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## get_top_query_patterns

```python
def get_top_query_patterns(self, top_n = 10):
    """
    Get the most common query patterns.

Args:
    top_n (int): Number of top patterns to return

Returns:
    list: Top query patterns with their metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## integrate_with_audit_system

```python
def integrate_with_audit_system(query_metrics: QueryMetricsCollector, audit_alert_manager: Any, audit_logger: Any) -> None:
    """
    Integrate query metrics with the audit system.

This function sets up bidirectional integration between the query metrics
system and the audit logging/alerting system, allowing both systems to
share information about anomalies.

Args:
    query_metrics: QueryMetricsCollector instance
    audit_alert_manager: AuditAlertManager instance from audit system
    audit_logger: AuditLogger instance for logging query events
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## plot_query_duration_distribution

```python
def plot_query_duration_distribution(self, figsize: Tuple[int, int] = (10, 6), output_file: Optional[str] = None, show_plot: bool = False) -> Optional[Any]:
    """
    Create a histogram of query durations.

Args:
    figsize: Figure size (width, height) in inches
    output_file: Optional path to save the plot
    show_plot: Whether to display the plot

Returns:
    matplotlib.figure.Figure or None if visualization not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** RAGQueryVisualizer

## plot_query_performance

```python
def plot_query_performance(self, time_window = None, figsize = None, output_file = None, show_plot = True):
    """
    Create a performance visualization for RAG queries.

Args:
    time_window (int, optional): Time window in seconds
    figsize (tuple, optional): Figure size (width, height) in inches
    output_file (str, optional): Path to save the visualization
    show_plot (bool): Whether to display the plot

Returns:
    matplotlib.figure.Figure: The generated figure
    """
```
* **Async:** False
* **Method:** True
* **Class:** RAGQueryVisualizer

## plot_query_performance

```python
def plot_query_performance(self, period: str = "hourly", days: int = 1, figsize: Tuple[int, int] = (10, 6), output_file: Optional[str] = None, show_plot: bool = False) -> Optional[Any]:
    """
    Create a plot of query performance over time.

Args:
    period: Aggregation period ('hourly', 'daily')
    days: Number of days to include
    figsize: Figure size (width, height) in inches
    output_file: Optional path to save the plot
    show_plot: Whether to display the plot

Returns:
    matplotlib.figure.Figure or None if visualization not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** RAGQueryVisualizer

## plot_query_term_frequency

```python
def plot_query_term_frequency(self, max_terms = 20, figsize = None, output_file = None, show_plot = True):
    """
    Plot frequency of terms used in queries.

Args:
    max_terms (int): Maximum number of terms to include
    figsize (tuple, optional): Figure size (width, height) in inches
    output_file (str, optional): Path to save the visualization
    show_plot (bool): Whether to display the plot

Returns:
    matplotlib.figure.Figure: The generated figure
    """
```
* **Async:** False
* **Method:** True
* **Class:** RAGQueryVisualizer

## plot_query_term_frequency

```python
def plot_query_term_frequency(self, top_n: int = 15, figsize: Tuple[int, int] = (10, 8), output_file: Optional[str] = None, show_plot: bool = False) -> Optional[Any]:
    """
    Create a bar chart of most frequent query terms.

Args:
    top_n: Number of top terms to include
    figsize: Figure size (width, height) in inches
    output_file: Optional path to save the plot
    show_plot: Whether to display the plot

Returns:
    matplotlib.figure.Figure or None if visualization not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** RAGQueryVisualizer

## query_anomaly_to_audit

```python
def query_anomaly_to_audit(anomaly: Dict[str, Any]) -> None:
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## record_circuit_breaker_event

```python
def record_circuit_breaker_event(self, event_type, reason, backoff_minutes = None):
    """
    Record circuit breaker activation or reset.

Args:
    event_type: Type of event ('tripped' or 'reset')
    reason: Reason for the event
    backoff_minutes: Backoff period in minutes if tripped
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## record_learning_cycle

```python
def record_learning_cycle(self, cycle_id, time_started, query_count, is_success = True, duration = None, results = None, error = None):
    """
    Record metrics from a learning cycle.

Args:
    cycle_id: Unique identifier for the learning cycle
    time_started: When the cycle started (timestamp)
    query_count: Number of queries analyzed in this cycle
    is_success: Whether the cycle completed successfully
    duration: How long the cycle took (seconds)
    results: Dictionary of learning results
    error: Error message if the cycle failed
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## record_learning_cycle

```python
def record_learning_cycle(self, cycle_id: str, start_time: float, end_time: float, analyzed_queries: int, learned_patterns: Dict[str, Any], parameter_changes: Dict[str, Tuple[float, float]], success: bool = True, error: Optional[str] = None) -> None:
    """
    Record metrics for a completed learning cycle.

Args:
    cycle_id: Unique identifier for the learning cycle
    start_time: Start timestamp of the cycle
    end_time: End timestamp of the cycle
    analyzed_queries: Number of queries analyzed in this cycle
    learned_patterns: Patterns identified during learning
    parameter_changes: Parameter values before and after learning
    success: Whether the learning cycle was successful
    error: Optional error message if the cycle failed
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## record_learning_cycle

```python
def record_learning_cycle(self, cycle_data):
    """
    Record a completed learning cycle.

Args:
    cycle_data (dict): Data about the learning cycle including:
        - timestamp: When the cycle completed
        - analyzed_queries: Number of queries analyzed
        - optimization_rules: Rules derived from learning
        - error: Any error encountered during learning (optional)
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## record_optimization_improvement

```python
def record_optimization_improvement(self, query_id: str, before_metrics: Dict[str, Any], after_metrics: Dict[str, Any]) -> None:
    """
    Record improvement metrics for an optimized query.

Args:
    query_id: Unique identifier for the query
    before_metrics: Performance metrics before optimization
    after_metrics: Performance metrics after optimization
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## record_parameter_adaptation

```python
def record_parameter_adaptation(self, parameter_name, old_value, new_value, confidence, cycle_id = None):
    """
    Record parameter adaptation from the learning process.

Args:
    parameter_name: Name of the parameter that was adapted
    old_value: Previous parameter value
    new_value: New parameter value
    confidence: Confidence in this adaptation (0.0-1.0)
    cycle_id: Learning cycle that triggered this adaptation
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## record_parameter_adaptation

```python
def record_parameter_adaptation(self, parameter_name: str, old_value: float, new_value: float, adaptation_reason: str, confidence: float, affected_strategies: List[str], timestamp: Optional[float] = None) -> None:
    """
    Record a parameter adaptation event.

Args:
    parameter_name: Name of the parameter that was adapted
    old_value: Parameter value before adaptation
    new_value: Parameter value after adaptation
    adaptation_reason: Reason for the adaptation
    confidence: Confidence level in the adaptation (0.0-1.0)
    affected_strategies: List of strategies affected by this parameter
    timestamp: Optional timestamp for the adaptation (defaults to now)
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## record_parameter_adaptation

```python
def record_parameter_adaptation(self, param_name, old_value, new_value, timestamp = None):
    """
    Record a parameter adaptation from learning.

Args:
    param_name (str): Name of the parameter that was adapted
    old_value: Previous parameter value
    new_value: New parameter value after adaptation
    timestamp (datetime, optional): Timestamp for the adaptation, defaults to now
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## record_query_end

```python
def record_query_end(self, query_id, results = None, error = None, metrics = None):
    """
    Record the end of a query execution with results or error.

Args:
    query_id (str): Unique identifier for the query
    results (list, optional): Query results
    error (str, optional): Error message if query failed
    metrics (dict, optional): Additional metrics from the query execution
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## record_query_end

```python
def record_query_end(self, query_id: str, results: Optional[List[Dict[str, Any]]] = None, error: Optional[str] = None, metrics: Optional[Dict[str, Any]] = None) -> None:
    """
    Record the completion of a query execution.

Args:
    query_id: Unique identifier for the query
    results: Optional query results
    error: Optional error message if query failed
    metrics: Optional additional metrics about the query execution
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## record_query_pattern

```python
def record_query_pattern(self, pattern_type: str, pattern_details: Dict[str, Any]) -> None:
    """
    Record an identified query pattern.

Args:
    pattern_type: Type of the identified pattern
    pattern_details: Details about the pattern
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## record_query_pattern

```python
def record_query_pattern(self, pattern):
    """
    Record a recognized query pattern.

Args:
    pattern (dict): Query pattern information
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## record_query_start

```python
def record_query_start(self, query_id, query_params):
    """
    Record the start of a query execution.

Args:
    query_id (str): Unique identifier for the query
    query_params (dict): Parameters of the query
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## record_query_start

```python
def record_query_start(self, query_id: str, query_params: Dict[str, Any]) -> None:
    """
    Record the start of a query execution.

Args:
    query_id: Unique identifier for the query
    query_params: Parameters of the query including query text, filters, etc.
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## record_strategy_effectiveness

```python
def record_strategy_effectiveness(self, strategy_name: str, query_count: int, success_rate: float, avg_performance_score: float, improvement_over_baseline: float) -> None:
    """
    Record effectiveness metrics for an optimization strategy.

Args:
    strategy_name: Name of the optimization strategy
    query_count: Number of queries using this strategy
    success_rate: Success rate of the strategy (0.0-1.0)
    avg_performance_score: Average performance score
    improvement_over_baseline: Improvement compared to baseline strategy
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## record_strategy_effectiveness

```python
def record_strategy_effectiveness(self, strategy_name, success, execution_time):
    """
    Record effectiveness of an optimization strategy.

Args:
    strategy_name (str): Name of the optimization strategy
    success (bool): Whether the strategy was successful
    execution_time (float): Time taken to execute the query with this strategy
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## set_audit_logger

```python
def set_audit_logger(self, audit_logger):
    """
    Set the audit logger for recording learning events.

Args:
    audit_logger: AuditLogger instance
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## set_theme

```python
def set_theme(self, theme = "light"):
    """
    Set visualization theme (light or dark).

Args:
    theme: Theme name ('light' or 'dark')
    """
```
* **Async:** False
* **Method:** True
* **Class:** PerformanceMetricsVisualizer

## to_json

```python
def to_json(self) -> Dict[str, Any]:
    """
    Convert metrics to JSON-serializable format.

Returns:
    Dict[str, Any]: Complete metrics in JSON-serializable format
    """
```
* **Async:** False
* **Method:** True
* **Class:** QueryMetricsCollector

## visualize_latency_distribution

```python
def visualize_latency_distribution(self, time_window = None, figsize = None, output_file = None, show_plot = True, interactive = False):
    """
    Visualize the distribution of query latency.

Args:
    time_window: Optional time window in seconds to include
    figsize: Figure size (width, height) in inches
    output_file: Path to save the visualization
    show_plot: Whether to display the plot
    interactive: Whether to create an interactive plot

Returns:
    Figure object or None if visualization libraries not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** PerformanceMetricsVisualizer

## visualize_latency_distribution

```python
def visualize_latency_distribution(self, output_file: Optional[str] = None, bins: int = 20, theme: str = "light") -> Union[plt.Figure, None]:
    """
    Create a visualization of query latency distribution.

Shows the distribution of query execution times with outlier detection.

Args:
    output_file: Optional path to save the visualization
    bins: Number of bins for histogram
    theme: 'light' or 'dark' theme for visualization

Returns:
    Matplotlib figure or None if visualization libraries not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** PerformanceMetricsVisualizer

## visualize_learning_cycles

```python
def visualize_learning_cycles(self, output_file: Optional[str] = None, interactive: bool = False, theme: str = "light") -> Any:
    """
    Visualize learning cycles over time.

Args:
    output_file: Optional path to save the visualization
    interactive: Whether to generate an interactive visualization
    theme: Visualization theme ('light' or 'dark')

Returns:
    The visualization figure object
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## visualize_learning_cycles

```python
def visualize_learning_cycles(self, output_file = None, show_plot = True, figsize = None):
    """
    Visualize learning cycles over time.

Args:
    output_file (str, optional): Path to save the visualization
    show_plot (bool): Whether to display the plot
    figsize (tuple, optional): Figure size (width, height) in inches

Returns:
    matplotlib.figure.Figure: The generated figure
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## visualize_learning_metrics

```python
def visualize_learning_metrics(self, output_file = None, interactive = True, **kwargs):
    """
    Visualize statistical learning metrics from the optimizer.

Creates a comprehensive visualization of the learning process metrics,
including cycle performance, parameter adaptations, and circuit breaker status.

Args:
    output_file: File to save visualization to
    interactive: Whether to create interactive visualization
    **kwargs: Additional arguments for the visualization

Returns:
    Figure or path to saved file
    """
```
* **Async:** False
* **Method:** True
* **Class:** RAGQueryDashboard

## visualize_learning_performance

```python
def visualize_learning_performance(self, output_file = None, interactive = True):
    """
    Create visualization of learning performance metrics.

Args:
    output_file: Optional file path to save the visualization
    interactive: Whether to create an interactive visualization

Returns:
    matplotlib.Figure or plotly.Figure: The generated visualization
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## visualize_learning_performance

```python
def visualize_learning_performance(self, output_file: Optional[str] = None, interactive: bool = False, theme: str = "light") -> Any:
    """
    Visualize overall learning performance improvements.

Args:
    output_file: Optional path to save the visualization
    interactive: Whether to generate an interactive visualization
    theme: Visualization theme ('light' or 'dark')

Returns:
    The visualization figure object
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## visualize_learning_performance

```python
def visualize_learning_performance(self, output_file = None, interactive = True, **kwargs):
    """
    Create a comprehensive visualization of learning performance metrics.

This is a high-level method that combines multiple visualizations
into a single output for easy analysis of the learning process.

Args:
    output_file (str, optional): Path to save the visualization
    interactive (bool): Whether to create interactive visualization
    **kwargs: Additional arguments for specific visualizations

Returns:
    Object: Figure object or path to saved file
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## visualize_parameter_adaptations

```python
def visualize_parameter_adaptations(self, output_file: Optional[str] = None, interactive: bool = False, parameters: Optional[List[str]] = None, theme: str = "light") -> Any:
    """
    Visualize parameter adaptations over time.

Args:
    output_file: Optional path to save the visualization
    interactive: Whether to generate an interactive visualization
    parameters: Optional list of parameters to include (None for all)
    theme: Visualization theme ('light' or 'dark')

Returns:
    The visualization figure object
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## visualize_parameter_adaptations

```python
def visualize_parameter_adaptations(self, param_names = None, output_file = None, show_plot = True, figsize = None):
    """
    Visualize parameter adaptations over time.

Args:
    param_names (list, optional): List of parameter names to include
    output_file (str, optional): Path to save the visualization
    show_plot (bool): Whether to display the plot
    figsize (tuple, optional): Figure size (width, height) in inches

Returns:
    matplotlib.figure.Figure: The generated figure
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## visualize_performance_by_query_complexity

```python
def visualize_performance_by_query_complexity(self, output_file: Optional[str] = None, theme: str = "light") -> Union[plt.Figure, None]:
    """
    Create a scatter plot of query performance vs complexity.

Shows how execution time correlates with query complexity measures.

Args:
    output_file: Optional path to save the visualization
    theme: 'light' or 'dark' theme for visualization

Returns:
    Matplotlib figure or None if visualization libraries not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** PerformanceMetricsVisualizer

## visualize_processing_time_breakdown

```python
def visualize_processing_time_breakdown(self, time_window = None, figsize = None, output_file = None, show_plot = True, interactive = False):
    """
    Visualize the breakdown of processing time across query phases.

Args:
    time_window: Optional time window in seconds to include
    figsize: Figure size (width, height) in inches
    output_file: Path to save the visualization
    show_plot: Whether to display the plot
    interactive: Whether to create an interactive plot

Returns:
    Figure object or None if visualization libraries not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** PerformanceMetricsVisualizer

## visualize_processing_time_breakdown

```python
def visualize_processing_time_breakdown(self, output_file: Optional[str] = None, top_n: int = 10, theme: str = "light") -> Union[plt.Figure, None]:
    """
    Create a visualization of processing time breakdown by component.

Shows the relative contribution of different processing phases (vector search,
graph traversal, result ranking, etc.) to total query execution time.

Args:
    output_file: Optional path to save the visualization
    top_n: Number of most recent queries to include
    theme: 'light' or 'dark' theme for visualization

Returns:
    Matplotlib figure or None if visualization libraries not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** PerformanceMetricsVisualizer

## visualize_query_audit_metrics

```python
def visualize_query_audit_metrics(self, time_window = None, output_file = None, show_plot = True):
    """
    Visualize audit metrics related to queries.

Args:
    time_window (int, optional): Time window in seconds
    output_file (str, optional): Output file path
    show_plot (bool): Whether to display the plot

Returns:
    object: The generated visualization
    """
```
* **Async:** False
* **Method:** True
* **Class:** RAGQueryDashboard

## visualize_query_audit_metrics

```python
def visualize_query_audit_metrics(self, output_file: str, hours_back: int = 24) -> str:
    """
    Generate a visualization combining query metrics with audit metrics.

Args:
    output_file: Path to save the visualization
    hours_back: Number of hours to look back

Returns:
    str: Path to the generated visualization
    """
```
* **Async:** False
* **Method:** True
* **Class:** RAGQueryDashboard

## visualize_query_audit_timeline

```python
def visualize_query_audit_timeline(self, audit_metrics_aggregator, hours_back: int = 24, interval_minutes: int = 30, theme: str = "light", title: str = "Query Performance & Audit Events Timeline", figsize: Tuple[int, int] = (12, 8), output_file: Optional[str] = None, interactive: bool = False, show_plot: bool = False) -> Optional[Any]:
    """
    Create an integrated timeline showing both RAG queries and audit events.

Args:
    audit_metrics_aggregator: AuditMetricsAggregator containing audit metrics
    hours_back: Number of hours to look back
    interval_minutes: Time interval in minutes for aggregation
    theme: 'light' or 'dark' color theme
    title: Title for the visualization
    figsize: Figure size (width, height) in inches
    output_file: Optional path to save the visualization
    interactive: Whether to create an interactive plot (requires plotly)
    show_plot: Whether to display the plot

Returns:
    matplotlib.figure.Figure or plotly.graph_objects.Figure: The generated figure
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedQueryVisualizer

## visualize_query_patterns

```python
def visualize_query_patterns(self, output_file: Optional[str] = None, interactive: bool = False, theme: str = "light") -> Any:
    """
    Visualize discovered query patterns.

Args:
    output_file: Optional path to save the visualization
    interactive: Whether to generate an interactive visualization
    theme: Visualization theme ('light' or 'dark')

Returns:
    The visualization figure object
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## visualize_query_patterns

```python
def visualize_query_patterns(self, output_file = None, top_n = 5, show_plot = True, figsize = None):
    """
    Visualize the distribution of query patterns recognized by the optimizer.

Args:
    output_file (str, optional): Path to save the visualization
    top_n (int): Number of top patterns to include
    show_plot (bool): Whether to display the plot
    figsize (tuple, optional): Figure size (width, height) in inches

Returns:
    matplotlib.figure.Figure: The generated figure
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## visualize_query_performance_timeline

```python
def visualize_query_performance_timeline(self, time_window = None, figsize = None, output_file = None, show_plot = True):
    """
    Create a timeline visualization of query performance.

Args:
    time_window (int, optional): Time window in seconds
    figsize (tuple, optional): Figure size (width, height) in inches
    output_file (str, optional): Path to save the visualization
    show_plot (bool): Whether to display the plot

Returns:
    matplotlib.figure.Figure: The generated figure
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedQueryVisualizer

## visualize_query_performance_timeline

```python
def visualize_query_performance_timeline(self, hours_back: int = 24, interval_minutes: int = 30, include_error_events: bool = True, output_file: Optional[str] = None, show_plot: bool = False) -> Any:
    """
    Create a timeline visualization of query performance.

Args:
    hours_back: Number of hours to look back
    interval_minutes: Time interval in minutes for aggregation
    include_error_events: Whether to highlight error events
    output_file: Optional path to save the visualization
    show_plot: Whether to display the plot

Returns:
    matplotlib.figure.Figure: The generated figure
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedQueryVisualizer

## visualize_query_performance_with_security_events

```python
def visualize_query_performance_with_security_events(self, audit_metrics_aggregator, hours_back: int = 24, interval_minutes: int = 15, event_categories: List[str] = None, min_severity: str = "WARNING", output_file: Optional[str] = None, interactive: bool = True, show_plot: bool = False) -> Optional[Any]:
    """
    Create a specialized visualization showing query performance correlation with security events.

This visualization highlights the relationship between RAG query performance and security
events, helping identify if security incidents impact query performance or if performance
anomalies correlate with security events.

Args:
    audit_metrics_aggregator: AuditMetricsAggregator containing audit metrics
    hours_back: Number of hours to look back
    interval_minutes: Time interval in minutes for aggregation
    event_categories: List of audit event categories to include (None for all)
    min_severity: Minimum severity level to include ("INFO", "WARNING", "ERROR", "CRITICAL")
    output_file: Optional path to save the visualization
    interactive: Whether to create an interactive plot
    show_plot: Whether to display the plot

Returns:
    matplotlib.figure.Figure or plotly.graph_objects.Figure: The generated figure
    """
```
* **Async:** False
* **Method:** True
* **Class:** EnhancedQueryVisualizer

## visualize_strategy_effectiveness

```python
def visualize_strategy_effectiveness(self, output_file: Optional[str] = None, interactive: bool = False, theme: str = "light") -> Any:
    """
    Visualize the effectiveness of different optimization strategies.

Args:
    output_file: Optional path to save the visualization
    interactive: Whether to generate an interactive visualization
    theme: Visualization theme ('light' or 'dark')

Returns:
    The visualization figure object
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## visualize_strategy_effectiveness

```python
def visualize_strategy_effectiveness(self, output_file = None, show_plot = True, figsize = None):
    """
    Visualize the effectiveness of different optimization strategies.

Args:
    output_file (str, optional): Path to save the visualization
    show_plot (bool): Whether to display the plot
    figsize (tuple, optional): Figure size (width, height) in inches

Returns:
    matplotlib.figure.Figure: The generated figure
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsCollector

## visualize_throughput_over_time

```python
def visualize_throughput_over_time(self, output_file: Optional[str] = None, interval_minutes: int = 10, hours: int = 24, theme: str = "light") -> Union[plt.Figure, None]:
    """
    Create a visualization of query throughput over time.

Shows query throughput (queries per minute) over a time window.

Args:
    output_file: Optional path to save the visualization
    interval_minutes: Size of time buckets in minutes
    hours: Number of hours to look back
    theme: 'light' or 'dark' theme for visualization

Returns:
    Matplotlib figure or None if visualization libraries not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** PerformanceMetricsVisualizer
