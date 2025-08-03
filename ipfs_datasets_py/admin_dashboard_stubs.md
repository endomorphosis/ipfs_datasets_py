# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/admin_dashboard.py'

Files last updated: 1751500891.6750643

Stub file last updated: 2025-07-07 02:11:01

## AdminDashboard

```python
class AdminDashboard:
    """
    Administration dashboard for IPFS Datasets.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## DashboardConfig

```python
@dataclass
class DashboardConfig:
    """
    Configuration for the admin dashboard.

Attributes:
    enabled (bool): Whether the dashboard is enabled. Defaults to True.
    host (str): The host address to bind the dashboard server to. Defaults to DEFAULT_HOST.
    port (int): The port number to bind the dashboard server to. Defaults to DEFAULT_PORT.
    refresh_interval (int): The interval in seconds for dashboard auto-refresh. Defaults to DEFAULT_REFRESH_INTERVAL.
    open_browser (bool): Whether to automatically open the browser when starting the dashboard. Defaults to True.
    data_dir (str): The directory path for storing dashboard data. Defaults to DEFAULT_DATA_DIR.
    max_log_lines (int): Maximum number of log lines to display in the dashboard. Defaults to DEFAULT_LOG_LINES.
    require_auth (bool): Whether authentication is required to access the dashboard. Defaults to False.
    username (Optional[str]): Username for dashboard authentication. Defaults to None.
    password (Optional[str]): Password for dashboard authentication. Defaults to None.
    monitoring_config (Optional[MonitoringConfig]): Configuration for monitoring features. Defaults to None.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self):
    """
    Initialize the admin dashboard.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdminDashboard

## _check_auth

```python
def _check_auth(self) -> bool:
    """
    Check if the user is authenticated.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdminDashboard

## _create_default_static_files

```python
def _create_default_static_files(self) -> None:
    """
    Create default static files if they don't exist.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdminDashboard

## _create_default_templates

```python
def _create_default_templates(self) -> None:
    """
    Create default template files if they don't exist.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdminDashboard

## _get_recent_logs

```python
def _get_recent_logs(self) -> List[Dict[str, Any]]:
    """
    Get recent log entries.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdminDashboard

## _get_system_stats

```python
def _get_system_stats(self) -> Dict[str, Any]:
    """
    Get system statistics.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdminDashboard

## _initialize_flask_app

```python
def _initialize_flask_app(self) -> None:
    """
    Initialize the Flask web application.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdminDashboard

## _run_server

```python
def _run_server(self) -> None:
    """
    Run the Flask server.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdminDashboard

## _setup_routes

```python
def _setup_routes(self) -> None:
    """
    Set up Flask routes for the dashboard.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdminDashboard

## api_logs

```python
@self.app.route("/api/logs")
def api_logs():
    """
    Return recent logs as JSON.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## api_metrics

```python
@self.app.route("/api/metrics")
def api_metrics():
    """
    Return metrics data as JSON.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## api_operations

```python
@self.app.route("/api/operations")
def api_operations():
    """
    Return operations data as JSON.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## api_system

```python
@self.app.route("/api/system")
def api_system():
    """
    Return system stats as JSON.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## configure

```python
def configure(self, config: DashboardConfig) -> None:
    """
    Configure the admin dashboard.

Args:
    config: Configuration for the dashboard
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdminDashboard

## example_main

```python
def example_main():
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## get_dashboard_status

```python
def get_dashboard_status() -> Dict[str, Any]:
    """
    Get the status of the admin dashboard.

Returns:
    dict: Dashboard status
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## get_instance

```python
@classmethod
def get_instance(cls) -> "AdminDashboard":
    """
    Get the singleton instance.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdminDashboard

## get_status

```python
def get_status(self) -> Dict[str, Any]:
    """
    Get the status of the admin dashboard.

Returns:
    dict: Dashboard status
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdminDashboard

## index

```python
@self.app.route("/")
def index():
    """
    Render the main dashboard page.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## initialize

```python
@classmethod
def initialize(cls, config: Optional[DashboardConfig] = None) -> "AdminDashboard":
    """
    Initialize the admin dashboard.

Args:
    config: Configuration for the dashboard

Returns:
    AdminDashboard: The initialized dashboard
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdminDashboard

## login

```python
@self.app.route("/login", methods=['GET', 'POST'])
def login():
    """
    Handle login.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## start

```python
def start(self) -> bool:
    """
    Start the admin dashboard.

Returns:
    bool: Whether the dashboard was started successfully
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdminDashboard

## start_dashboard

```python
def start_dashboard(config: Optional[DashboardConfig] = None) -> AdminDashboard:
    """
    Start the admin dashboard with the given configuration.

Args:
    config: Dashboard configuration

Returns:
    AdminDashboard: The dashboard instance
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## stop

```python
def stop(self) -> bool:
    """
    Stop the admin dashboard.

Returns:
    bool: Whether the dashboard was stopped successfully
    """
```
* **Async:** False
* **Method:** True
* **Class:** AdminDashboard

## stop_dashboard

```python
def stop_dashboard() -> bool:
    """
    Stop the admin dashboard.

Returns:
    bool: Whether the dashboard was stopped successfully
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
