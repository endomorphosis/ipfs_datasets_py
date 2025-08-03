# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/rag/rag_query_dashboard.py'

Files last updated: 1748635923.4613795

Stub file last updated: 2025-07-07 01:59:52

## DashboardWebSocketHandler

```python
class DashboardWebSocketHandler(tornado.websocket.WebSocketHandler):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## RealTimeDashboardServer

```python
class RealTimeDashboardServer:
    """
    WebSocket server that provides real-time dashboard updates.

This class manages WebSocket connections and broadcasts updates
to connected clients when new metrics data is available.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## UnifiedDashboard

```python
class UnifiedDashboard:
    """
    Unified dashboard that combines RAG query metrics and audit data.

This class provides methods to generate comprehensive dashboards
with both static and real-time components.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, port = 8888, update_interval = 5):
    """
    Initialize the real-time dashboard server.

Args:
    port: Port number for the WebSocket server
    update_interval: How often to check for updates (seconds)
    """
```
* **Async:** False
* **Method:** True
* **Class:** RealTimeDashboardServer

## __init__

```python
def __init__(self, dashboard_dir = None, enable_realtime = False, port = 8888):
    """
    Initialize the unified dashboard.

Args:
    dashboard_dir: Directory to store dashboard files
    enable_realtime: Whether to enable real-time updates
    port: Port for real-time server (if enabled)
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnifiedDashboard

## _collect_audit_metrics

```python
def _collect_audit_metrics(self, collector):
    """
    Collect metrics from an AuditMetricsAggregator.

Args:
    collector: AuditMetricsAggregator instance

Returns:
    dict: Audit metrics data
    """
```
* **Async:** False
* **Method:** True
* **Class:** RealTimeDashboardServer

## _collect_metrics

```python
def _collect_metrics(self):
    """
    Collect metrics from all registered collectors.

Returns:
    bool: True if there were updates, False otherwise
    """
```
* **Async:** False
* **Method:** True
* **Class:** RealTimeDashboardServer

## _collect_query_metrics

```python
def _collect_query_metrics(self, collector):
    """
    Collect metrics from a QueryMetricsCollector.

Args:
    collector: QueryMetricsCollector instance

Returns:
    dict: Query metrics data
    """
```
* **Async:** False
* **Method:** True
* **Class:** RealTimeDashboardServer

## _generate_basic_html

```python
def _generate_basic_html(self, title, theme, static_visualizations, interactive_visualizations, has_query_metrics, has_audit_metrics, enable_realtime, websocket_port):
    """
    Generate basic HTML for the dashboard without using Jinja2.

Args:
    title: Dashboard title
    theme: 'light' or 'dark'
    static_visualizations: Paths to static visualizations
    interactive_visualizations: Paths to interactive visualizations
    has_query_metrics: Whether query metrics are available
    has_audit_metrics: Whether audit metrics are available
    enable_realtime: Whether to include real-time updates
    websocket_port: Port for WebSocket connection

Returns:
    str: HTML content
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnifiedDashboard

## _generate_realtime_js

```python
def _generate_realtime_js(self):
    """
    Generate JavaScript for real-time dashboard updates.
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnifiedDashboard

## _generate_template_html

```python
def _generate_template_html(self, title, theme, static_visualizations, interactive_visualizations, has_query_metrics, has_audit_metrics, enable_realtime, websocket_port):
    """
    Generate HTML using Jinja2 templates.

Args:
    title: Dashboard title
    theme: 'light' or 'dark'
    static_visualizations: Paths to static visualizations
    interactive_visualizations: Paths to interactive visualizations
    has_query_metrics: Whether query metrics are available
    has_audit_metrics: Whether audit metrics are available
    enable_realtime: Whether to include real-time updates
    websocket_port: Port for WebSocket connection

Returns:
    str: HTML content
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnifiedDashboard

## _update_loop

```python
def _update_loop(self):
    """
    Background thread that periodically checks for updates and broadcasts to clients.
    """
```
* **Async:** False
* **Method:** True
* **Class:** RealTimeDashboardServer

## check_origin

```python
def check_origin(self, origin):
```
* **Async:** False
* **Method:** True
* **Class:** DashboardWebSocketHandler

## generate_dashboard

```python
def generate_dashboard(self, query_metrics_collector = None, audit_metrics_aggregator = None, title = "Unified Query & Audit Dashboard", theme = "light", include_performance = True, include_security = True, include_interactive = True, include_realtime = None):
    """
    Generate a comprehensive dashboard with both static and real-time components.

Args:
    query_metrics_collector: QueryMetricsCollector for query metrics
    audit_metrics_aggregator: AuditMetricsAggregator for audit metrics
    title: Dashboard title
    theme: Dashboard theme ('light' or 'dark')
    include_performance: Whether to include performance metrics
    include_security: Whether to include security insights
    include_interactive: Whether to include interactive visualizations
    include_realtime: Override whether to include real-time components

Returns:
    str: Path to the dashboard HTML file
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnifiedDashboard

## on_close

```python
def on_close(self):
```
* **Async:** False
* **Method:** True
* **Class:** DashboardWebSocketHandler

## open

```python
def open(self):
```
* **Async:** False
* **Method:** True
* **Class:** DashboardWebSocketHandler

## register_metrics_collector

```python
def register_metrics_collector(self, collector):
    """
    Register a metrics collector with the dashboard server.

Args:
    collector: QueryMetricsCollector or AuditMetricsAggregator
    """
```
* **Async:** False
* **Method:** True
* **Class:** RealTimeDashboardServer

## register_metrics_collector

```python
def register_metrics_collector(self, collector):
    """
    Register a metrics collector with the dashboard.

Args:
    collector: QueryMetricsCollector or AuditMetricsAggregator
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnifiedDashboard

## run_demonstration

```python
def run_demonstration(dashboard_dir = None, enable_realtime = True):
    """
    Run a demonstration of the unified dashboard.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## start

```python
def start(self):
    """
    Start the WebSocket server and updater thread.
    """
```
* **Async:** False
* **Method:** True
* **Class:** RealTimeDashboardServer

## stop

```python
def stop(self):
    """
    Stop the WebSocket server and updater thread.
    """
```
* **Async:** False
* **Method:** True
* **Class:** RealTimeDashboardServer
