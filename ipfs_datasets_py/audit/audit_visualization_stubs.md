# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/audit/audit_visualization.py'

Files last updated: 1748635923.4213796

Stub file last updated: 2025-07-07 02:14:36

## AuditAlertManager

```python
class AuditAlertManager:
    """
    Manages audit alerts and integrates with the security system.

This class handles alerts generated from audit anomalies, sends notifications,
and integrates with the intrusion detection system to enable
automated security responses.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## AuditMetricsAggregator

```python
class AuditMetricsAggregator:
    """
    Collects and aggregates metrics from audit events for analysis and visualization.

This class processes audit events to generate statistical insights, trends analysis,
and aggregated metrics useful for security analysis, compliance reporting, and
operational monitoring.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## AuditVisualizer

```python
class AuditVisualizer:
    """
    Visualization tools for audit metrics.

This class provides methods for creating visualizations of audit metrics,
including charts, dashboards, and reports. It works with the AuditMetricsAggregator
to visualize the collected metrics.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## MetricsCollectionHandler

```python
class MetricsCollectionHandler(AuditHandler):
    """
    Audit handler that collects metrics from audit events.

This handler processes audit events and updates metrics in an AuditMetricsAggregator
for later analysis and visualization.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## OptimizerLearningMetricsVisualizer

```python
class OptimizerLearningMetricsVisualizer:
    """
    Visualizes metrics related to GraphRAG query optimizer's statistical learning process.

This class provides methods to create visualizations for various aspects of the
statistical learning process in the GraphRAG query optimizer, including learning cycles,
parameter adaptations, strategy effectiveness, query patterns, and learning performance.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, window_size: int = 3600, bucket_size: int = 60):
    """
    Initialize the metrics aggregator.

Args:
    window_size: Size of the time window in seconds for metrics storage
    bucket_size: Size of the time buckets in seconds for aggregation
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditMetricsAggregator

## __init__

```python
def __init__(self, metrics_aggregator: AuditMetricsAggregator):
    """
    Initialize the visualizer with a metrics aggregator.

Args:
    metrics_aggregator: AuditMetricsAggregator instance with collected metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditVisualizer

## __init__

```python
def __init__(self, name: str, metrics_aggregator: AuditMetricsAggregator, min_level: AuditLevel = AuditLevel.INFO, alert_on_anomalies: bool = False, alert_handler: Optional[Callable[[Dict[str, Any]], None]] = None):
    """
    Initialize the metrics collection handler.

Args:
    name: Handler name
    metrics_aggregator: AuditMetricsAggregator to update with events
    min_level: Minimum level of events to process
    alert_on_anomalies: Whether to generate alerts for detected anomalies
    alert_handler: Optional callback for handling anomaly alerts
    """
```
* **Async:** False
* **Method:** True
* **Class:** MetricsCollectionHandler

## __init__

```python
def __init__(self, audit_logger: Optional[AuditLogger] = None, intrusion_detection = None, security_manager = None):
    """
    Initialize the audit alert manager.

Args:
    audit_logger: AuditLogger instance (optional)
    intrusion_detection: IntrusionDetection instance (optional)
    security_manager: EnhancedSecurityManager instance (optional)
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditAlertManager

## __init__

```python
def __init__(self, metrics_collector = None, output_dir = None):
    """
    Initialize the metrics visualizer.

Args:
    metrics_collector: The metrics collector instance containing learning metrics
    output_dir: Directory to store visualization outputs
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsVisualizer

## _calculate_derived_metrics

```python
def _calculate_derived_metrics(self):
    """
    Calculate derived metrics from raw data.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditMetricsAggregator

## _calculate_severity

```python
def _calculate_severity(self, z_score: float) -> str:
    """
    Calculate severity level based on z-score.

Args:
    z_score: The Z-score value

Returns:
    str: Severity level ('low', 'medium', 'high', 'critical')
    """
```
* **Async:** False
* **Method:** True
* **Class:** MetricsCollectionHandler

## _clean_old_data

```python
def _clean_old_data(self):
    """
    Remove data older than the window size.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditMetricsAggregator

## _create_security_alert_from_anomaly

```python
def _create_security_alert_from_anomaly(self, anomaly: Dict[str, Any]) -> None:
    """
    Create a security alert from an audit anomaly.

Args:
    anomaly: Anomaly data
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditAlertManager

## _detect_error_rate_anomalies

```python
def _detect_error_rate_anomalies(self) -> List[Dict[str, Any]]:
    """
    Detect anomalies in error rates.

Returns:
    List[Dict[str, Any]]: Detected anomalies
    """
```
* **Async:** False
* **Method:** True
* **Class:** MetricsCollectionHandler

## _detect_frequency_anomalies

```python
def _detect_frequency_anomalies(self) -> List[Dict[str, Any]]:
    """
    Detect anomalies in event frequency by category and action.

Returns:
    List[Dict[str, Any]]: Detected anomalies
    """
```
* **Async:** False
* **Method:** True
* **Class:** MetricsCollectionHandler

## _detect_user_activity_anomalies

```python
def _detect_user_activity_anomalies(self) -> List[Dict[str, Any]]:
    """
    Detect anomalies in user activity patterns.

Returns:
    List[Dict[str, Any]]: Detected anomalies
    """
```
* **Async:** False
* **Method:** True
* **Class:** MetricsCollectionHandler

## _get_alert_description

```python
def _get_alert_description(self, anomaly: Dict[str, Any]) -> str:
    """
    Get a human-readable description for an anomaly.

Args:
    anomaly: Anomaly data

Returns:
    str: Human-readable description
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditAlertManager

## _get_audit_level_for_severity

```python
def _get_audit_level_for_severity(self, severity: str) -> "AuditLevel":
    """
    Map severity string to AuditLevel.

Args:
    severity: Severity string ('low', 'medium', 'high', 'critical')

Returns:
    AuditLevel: Corresponding audit level
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditAlertManager

## _get_bucket_timestamp

```python
def _get_bucket_timestamp(self, timestamp: float) -> int:
    """
    Get the bucket timestamp for a given timestamp.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditMetricsAggregator

## _reset_metrics

```python
def _reset_metrics(self):
    """
    Reset all metrics to initial state.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditMetricsAggregator

## add_notification_handler

```python
def add_notification_handler(self, handler: Callable[[Dict[str, Any]], None]) -> None:
    """
    Add a handler for alert notifications.

Args:
    handler: Function that processes alert notifications
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditAlertManager

## check_for_anomalies

```python
def check_for_anomalies(self) -> List[Dict[str, Any]]:
    """
    Check for anomalies in the collected metrics.

Returns:
    List[Dict[str, Any]]: Detected anomalies
    """
```
* **Async:** False
* **Method:** True
* **Class:** MetricsCollectionHandler

## create_interactive_audit_trends

```python
def create_interactive_audit_trends(metrics_aggregator: AuditMetricsAggregator, period: str = "daily", lookback_days: int = 30, categories: Optional[List[str]] = None, levels: Optional[List[str]] = None, output_file: Optional[str] = None) -> Optional[Any]:
    """
    Create interactive visualizations of audit event trends over time.

This function generates an interactive visualization showing trends of audit events
over time, with filtering capabilities by category and level. The visualization
allows zooming, panning, and hovering for detailed information.

Args:
    metrics_aggregator: AuditMetricsAggregator instance containing the audit data
    period: Time period for aggregation ('hourly', 'daily', 'weekly')
    lookback_days: Number of days to include in the visualization
    categories: Optional list of categories to include (None for all/top categories)
    levels: Optional list of audit levels to include (None for all)
    output_file: Optional file path to save the visualization (HTML format recommended)

Returns:
    plotly.graph_objects.Figure or None: Interactive figure object if successful
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## create_interactive_audit_trends

```python
def create_interactive_audit_trends(metrics_aggregator: "AuditMetricsAggregator", period: str = "daily", lookback_days: int = 7, output_file: Optional[str] = None, theme: str = "light") -> Optional[Any]:
    """
    Create an interactive visualization of audit event trends over time.

This function generates an interactive Plotly-based visualization showing
trends in audit events, categorized by level, category, and other attributes.

Args:
    metrics_aggregator: AuditMetricsAggregator with audit metrics
    period: Aggregation period ('hourly', 'daily', 'weekly')
    lookback_days: Number of days to include in visualization
    output_file: Optional path to save HTML output
    theme: Visualization theme ('light' or 'dark')

Returns:
    plotly.graph_objects.Figure or None if visualization not available
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## create_query_audit_timeline

```python
def create_query_audit_timeline(query_metrics_collector, audit_metrics, hours_back: int = 24, interval_minutes: int = 30, theme: str = "light", figsize: Tuple[int, int] = (12, 8), output_file: Optional[str] = None, show_plot: bool = False) -> Optional[Any]:
    """
    Create a comprehensive visualization showing both GraphRAG query performance and audit events.

This function creates a timeline visualization with three subplots:
1. Query durations and counts
2. Audit events by category
3. Audit events by severity level

Args:
    query_metrics_collector: QueryMetricsCollector instance with query metrics
    audit_metrics: AuditMetricsAggregator instance with audit events
    hours_back: Number of hours to look back
    interval_minutes: Time interval in minutes for aggregation
    theme: 'light' or 'dark' color theme
    figsize: Figure size (width, height) in inches
    output_file: Optional path to save the visualization
    show_plot: Whether to display the plot

Returns:
    matplotlib.figure.Figure or None: The generated figure
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## create_query_audit_timeline

```python
def create_query_audit_timeline(self, query_metrics_collector, hours_back: int = 24, interval_minutes: int = 30, theme: str = "light", figsize: Tuple[int, int] = (12, 8), output_file: Optional[str] = None, show_plot: bool = False) -> Optional[Any]:
    """
    Create a timeline visualization showing both audit events and GraphRAG queries.

Args:
    query_metrics_collector: QueryMetricsCollector containing query metrics
    hours_back: Number of hours to look back
    interval_minutes: Time interval in minutes for aggregation
    theme: 'light' or 'dark' color theme
    figsize: Figure size (width, height) in inches
    output_file: Optional path to save the plot
    show_plot: Whether to display the plot

Returns:
    matplotlib.figure.Figure or None if visualization not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditVisualizer

## create_query_audit_timeline

```python
def create_query_audit_timeline(query_metrics_collector, audit_metrics: "AuditMetricsAggregator", output_file: Optional[str] = None, hours_back: int = 24, theme: str = "light", figsize: Tuple[int, int] = (14, 8)) -> Optional[Any]:
    """
    Create a visualization showing the relationship between GraphRAG queries and audit events.

This function generates a timeline visualization that shows GraphRAG query executions
alongside audit events, making it easier to correlate performance issues with
system events or security incidents.

Args:
    query_metrics_collector: QueryMetricsCollector instance with query metrics
    audit_metrics: AuditMetricsAggregator instance with audit data
    output_file: Optional path to save the visualization
    hours_back: Number of hours of history to include
    theme: Plot theme ("light" or "dark")
    figsize: Figure size (width, height) in inches

Returns:
    matplotlib.figure.Figure or None if visualization libraries not available
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## create_query_audit_timeline

```python
def create_query_audit_timeline(query_metrics_collector, audit_metrics, hours_back: int = 24, interval_minutes: int = 30, theme: str = "light", figsize: Tuple[int, int] = (12, 8), output_file: Optional[str] = None, show_plot: bool = False) -> Optional[Any]:
    """
    Create a comprehensive visualization showing both GraphRAG query performance and audit events.

This function creates a timeline visualization with three subplots:
1. Query durations and counts
2. Audit events by category
3. Audit events by severity level

Args:
    query_metrics_collector: QueryMetricsCollector instance with query metrics
    audit_metrics: AuditMetricsAggregator instance with audit events
    hours_back: Number of hours to look back
    interval_minutes: Time interval in minutes for aggregation
    theme: 'light' or 'dark' color theme
    figsize: Figure size (width, height) in inches
    output_file: Optional path to save the visualization
    show_plot: Whether to display the plot

Returns:
    matplotlib.figure.Figure or None: The generated figure
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
* **Class:** AuditVisualizer

## generate_audit_dashboard

```python
def generate_audit_dashboard(output_file: str, audit_logger: Optional[AuditLogger] = None, metrics: Optional[AuditMetricsAggregator] = None, alert_manager: Optional[AuditAlertManager] = None, title: str = "Audit Metrics Dashboard", include_security_alerts: bool = True, include_anomalies: bool = True) -> str:
    """
    Generate an audit metrics dashboard.

This function creates a dashboard HTML file with visualizations of audit metrics,
security alerts, and detected anomalies. Either an AuditLogger or an
AuditMetricsAggregator must be provided.

Args:
    output_file: Path to save the dashboard HTML file
    audit_logger: Optional AuditLogger to collect metrics from
    metrics: Optional AuditMetricsAggregator with existing metrics
    alert_manager: Optional AuditAlertManager for security alerts
    title: Dashboard title
    include_security_alerts: Whether to include security alerts section
    include_anomalies: Whether to include anomalies section

Returns:
    str: Path to the generated dashboard file
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## generate_dashboard_html

```python
def generate_dashboard_html(self, title: str = "Audit Metrics Dashboard", include_performance: bool = True, include_security: bool = True, include_compliance: bool = True, security_alerts: List[Dict[str, Any]] = None, anomaly_alerts: List[Dict[str, Any]] = None) -> str:
    """
    Generate an HTML dashboard with metrics, visualizations, and security alerts.

Args:
    title: Dashboard title
    include_performance: Whether to include performance metrics
    include_security: Whether to include security metrics
    include_compliance: Whether to include compliance metrics
    security_alerts: Optional list of security alerts to display
    anomaly_alerts: Optional list of anomaly alerts to display

Returns:
    str: HTML dashboard content
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditVisualizer

## generate_learning_metrics_dashboard

```python
def generate_learning_metrics_dashboard(self, output_file: Optional[str] = None, theme: str = "light") -> Optional[str]:
    """
    Generate a comprehensive dashboard for learning metrics.

This dashboard combines multiple visualizations into a single HTML page
with interactive elements.

Args:
    output_file: Path to save the dashboard HTML file
    theme: Color theme ('light' or 'dark')

Returns:
    Path to the dashboard HTML file
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsVisualizer

## get_compliance_metrics

```python
def get_compliance_metrics(self) -> Dict[str, Any]:
    """
    Get compliance-related metrics.

Returns:
    Dict[str, Any]: Compliance violation metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditMetricsAggregator

## get_metrics_summary

```python
def get_metrics_summary(self) -> Dict[str, Any]:
    """
    Get a summary of the collected metrics.

Returns:
    Dict[str, Any]: Summary of metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditMetricsAggregator

## get_performance_metrics

```python
def get_performance_metrics(self) -> Dict[str, Any]:
    """
    Get performance metrics for operations.

Returns:
    Dict[str, Any]: Performance metrics by action
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditMetricsAggregator

## get_recent_alerts

```python
def get_recent_alerts(self, limit: int = 10, min_severity: str = "low") -> List[Dict[str, Any]]:
    """
    Get recent alerts, optionally filtered by severity.

Args:
    limit: Maximum number of alerts to return
    min_severity: Minimum severity level

Returns:
    List[Dict[str, Any]]: Recent alerts
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditAlertManager

## get_security_insights

```python
def get_security_insights(self) -> Dict[str, Any]:
    """
    Get security insights derived from audit events.

Returns:
    Dict[str, Any]: Security insights and anomalies
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditMetricsAggregator

## get_time_series_data

```python
def get_time_series_data(self) -> Dict[str, Any]:
    """
    Get time series data for visualization.

Returns:
    Dict[str, Any]: Time series data organized for charts
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditMetricsAggregator

## handle

```python
def handle(self, event: AuditEvent) -> bool:
    """
    Handle an audit event by updating metrics.

Args:
    event: The audit event to handle

Returns:
    bool: Whether the event was handled
    """
```
* **Async:** False
* **Method:** True
* **Class:** MetricsCollectionHandler

## handle_anomaly_alert

```python
def handle_anomaly_alert(self, anomaly: Dict[str, Any]) -> None:
    """
    Handle an anomaly alert from the metrics collector.

Args:
    anomaly: Anomaly data
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditAlertManager

## plot_event_timeline

```python
def plot_event_timeline(self, hours: int = 24, interval_minutes: int = 15, figsize: Tuple[int, int] = (12, 6), output_file: Optional[str] = None, show_plot: bool = False) -> Optional[Any]:
    """
    Create a timeline visualization of audit events.

Args:
    hours: Number of hours to include in the timeline
    interval_minutes: Interval in minutes for the timeline buckets
    figsize: Figure size (width, height) in inches
    output_file: Optional path to save the plot
    show_plot: Whether to display the plot

Returns:
    matplotlib.figure.Figure or None if visualization not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditVisualizer

## plot_events_by_category

```python
def plot_events_by_category(self, top: int = 10, figsize: Tuple[int, int] = (10, 6), output_file: Optional[str] = None, show_plot: bool = False) -> Optional[Any]:
    """
    Create a bar chart of events by category.

Args:
    top: Number of top categories to include
    figsize: Figure size (width, height) in inches
    output_file: Optional path to save the plot
    show_plot: Whether to display the plot

Returns:
    matplotlib.figure.Figure or None if visualization not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditVisualizer

## plot_events_by_level

```python
def plot_events_by_level(self, figsize: Tuple[int, int] = (8, 6), output_file: Optional[str] = None, show_plot: bool = False) -> Optional[Any]:
    """
    Create a pie chart of events by severity level.

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
* **Class:** AuditVisualizer

## plot_operation_durations

```python
def plot_operation_durations(self, top: int = 10, figsize: Tuple[int, int] = (10, 6), output_file: Optional[str] = None, show_plot: bool = False) -> Optional[Any]:
    """
    Create a bar chart of operation durations.

Args:
    top: Number of top operations to include
    figsize: Figure size (width, height) in inches
    output_file: Optional path to save the plot
    show_plot: Whether to display the plot

Returns:
    matplotlib.figure.Figure or None if visualization not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditVisualizer

## process_event

```python
def process_event(self, event: AuditEvent) -> None:
    """
    Process an audit event and update metrics.

Args:
    event: The audit event to process
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditMetricsAggregator

## setup_audit_visualization

```python
def setup_audit_visualization(audit_logger: AuditLogger, enable_anomaly_detection: bool = True, intrusion_detection = None, security_manager = None) -> Tuple[AuditMetricsAggregator, AuditVisualizer, AuditAlertManager]:
    """
    Set up the audit visualization system.

This creates a metrics aggregator, visualizer, and alert manager, and registers a metrics
collection handler with the audit logger.

Args:
    audit_logger: AuditLogger instance to collect events from
    enable_anomaly_detection: Whether to enable anomaly detection
    intrusion_detection: Optional IntrusionDetection instance
    security_manager: Optional EnhancedSecurityManager instance

Returns:
    Tuple[AuditMetricsAggregator, AuditVisualizer, AuditAlertManager]: metrics, visualizer, alerts
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

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
* **Class:** AuditMetricsAggregator

## visualize_learning_cycles

```python
def visualize_learning_cycles(self, output_file: Optional[str] = None, theme: str = "light", interactive: bool = False) -> Optional[Any]:
    """
    Create a visualization of learning cycles over time.

Args:
    output_file: Path to save the visualization
    theme: Color theme ('light' or 'dark')
    interactive: Whether to generate an interactive plot

Returns:
    Path to the visualization file or the figure object
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsVisualizer

## visualize_parameter_adaptations

```python
def visualize_parameter_adaptations(self, output_file: Optional[str] = None, theme: str = "light", interactive: bool = False) -> Optional[Any]:
    """
    Create a visualization of parameter adaptations over time.

Args:
    output_file: Path to save the visualization
    theme: Color theme ('light' or 'dark')
    interactive: Whether to generate an interactive plot

Returns:
    Path to the visualization file or the figure object
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsVisualizer

## visualize_strategy_effectiveness

```python
def visualize_strategy_effectiveness(self, output_file: Optional[str] = None, theme: str = "light", interactive: bool = False) -> Optional[Any]:
    """
    Create a visualization of strategy effectiveness for different query types.

Args:
    output_file: Path to save the visualization
    theme: Color theme ('light' or 'dark')
    interactive: Whether to generate an interactive plot

Returns:
    Path to the visualization file or the figure object
    """
```
* **Async:** False
* **Method:** True
* **Class:** OptimizerLearningMetricsVisualizer
