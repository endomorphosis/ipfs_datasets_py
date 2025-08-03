# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/unified_monitoring_dashboard.py'

Files last updated: 1751458121.6521692

Stub file last updated: 2025-07-07 02:11:02

## UnifiedDashboard

```python
class UnifiedDashboard:
    """
    Unified dashboard that integrates multiple monitoring components.

This class provides a comprehensive monitoring solution that combines:
- Learning metrics visualizations
- Alert notifications
- Performance statistics
- System health indicators
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, dashboard_dir: str, dashboard_title: str = "RAG Optimizer Monitoring Dashboard", refresh_interval: int = 300, auto_refresh: bool = True, max_alerts: int = 100, template_dir: Optional[str] = None) -> None:
    """
    Initialize the unified dashboard.

Args:
    dashboard_dir: Directory to store dashboard files
    dashboard_title: Title for the dashboard
    refresh_interval: Interval in seconds for automatic dashboard updates
    auto_refresh: Whether to enable automatic updates
    max_alerts: Maximum number of alerts to display
    template_dir: Directory containing custom templates (optional)

Attributes set during initialization:
    dashboard_dir (str): Directory to store dashboard files
    dashboard_title (str): Title for the dashboard
    refresh_interval (int): Interval in seconds for automatic dashboard updates
    auto_refresh (bool): Whether to enable automatic updates
    max_alerts (int): Maximum number of alerts to display
    template_dir (Optional[str]): Directory containing custom templates
    visualizations_dir (str): Directory for visualization outputs
    alerts_dir (str): Directory for alert files
    metrics_dir (str): Directory for metrics files
    assets_dir (str): Directory for dashboard assets
    last_update_time (Optional): Timestamp of last dashboard update
    dashboard_path (str): Path to the main dashboard HTML file
    alerts_json_path (str): Path to the alerts JSON file
    metrics_json_path (str): Path to the metrics JSON file
    config_json_path (str): Path to the configuration JSON file
    learning_visualizer: Reference to learning visualization component
    alert_system: Reference to alert system component
    metrics_collector: Reference to metrics collection component
    recent_alerts (list): List of recent alerts
    _stop_refresh (threading.Event): Event to control auto-refresh thread
    _refresh_thread: Thread for automatic dashboard refresh
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnifiedDashboard

## _alert_handler

```python
def _alert_handler(self, anomaly: LearningAnomaly):
    """
    Handle alerts from the alert system.

Args:
    anomaly: The detected anomaly
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnifiedDashboard

## _auto_refresh_loop

```python
def _auto_refresh_loop(self):
    """
    Background thread for automatic dashboard refreshing.
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnifiedDashboard

## _generate_dashboard_html

```python
def _generate_dashboard_html(self, viz_outputs: Dict[str, str], metrics_data: Dict[str, Any]):
    """
    Generate the main dashboard HTML.

Args:
    viz_outputs: Paths to visualization outputs
    metrics_data: Current metrics data
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnifiedDashboard

## _save_alerts

```python
def _save_alerts(self):
    """
    Save recent alerts to JSON file.
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnifiedDashboard

## _save_config

```python
def _save_config(self):
    """
    Save dashboard configuration to JSON file.
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnifiedDashboard

## create_unified_dashboard

```python
def create_unified_dashboard(dashboard_dir: str, dashboard_title: str = "RAG Optimizer Monitoring Dashboard", refresh_interval: int = 300, auto_refresh: bool = True, max_alerts: int = 100, template_dir: Optional[str] = None) -> UnifiedDashboard:
    """
    Create and set up a unified monitoring dashboard.

Args:
    dashboard_dir: Directory to store dashboard files
    dashboard_title: Title for the dashboard
    refresh_interval: Interval in seconds for automatic dashboard updates
    auto_refresh: Whether to enable automatic updates
    max_alerts: Maximum number of alerts to display
    template_dir: Directory containing custom templates (optional)

Returns:
    UnifiedDashboard: Configured dashboard instance
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## register_alert_system

```python
def register_alert_system(self, alert_system: LearningAlertSystem):
    """
    Register an alert system component.

Args:
    alert_system: The alert system to register
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnifiedDashboard

## register_learning_visualizer

```python
def register_learning_visualizer(self, visualizer: OptimizerLearningMetricsVisualizer):
    """
    Register a learning metrics visualizer component.

Args:
    visualizer: The metrics visualizer to register
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnifiedDashboard

## register_metrics_collector

```python
def register_metrics_collector(self, metrics_collector: MetricsCollector):
    """
    Register a metrics collector component.

Args:
    metrics_collector: The metrics collector to register
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnifiedDashboard

## start_auto_refresh

```python
def start_auto_refresh(self):
    """
    Start automatic dashboard refreshing.
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnifiedDashboard

## stop_auto_refresh

```python
def stop_auto_refresh(self):
    """
    Stop automatic dashboard refreshing.
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnifiedDashboard

## update_dashboard

```python
def update_dashboard(self):
    """
    Update the unified dashboard with current data from all components.
    """
```
* **Async:** False
* **Method:** True
* **Class:** UnifiedDashboard
