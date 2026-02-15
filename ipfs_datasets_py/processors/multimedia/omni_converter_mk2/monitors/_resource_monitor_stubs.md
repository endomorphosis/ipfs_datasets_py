# Function and Class stubs from '/home/kylerose1946/omni_converter_mk2/monitors/_resource_monitor.py'

Files last updated: 1751108774.0444002

Stub file last updated: 2025-07-17 05:28:21

## ResourceMonitor

```python
class ResourceMonitor:
    """
    Resource monitor for the Omni-Converter.

This class monitors system resources such as CPU and memory usage, and
provides methods to check if resources are available for processing.

Attributes:
    cpu_limit_percent (float): Maximum CPU usage percentage (0-100).
    memory_limit (int): Maximum memory usage in MB.
    current_resource_usage (dict[str, float]): Current resource usage.
    active_monitoring (bool): Whether active monitoring is enabled.
    monitoring_thread: Thread for active monitoring.
    monitoring_interval (float): Interval for active monitoring in seconds.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, configs: Configs = None, resources: dict[str, Callable] = None):
    """
    Initialize a resource monitor.

Args:
    cpu_limit_percent: Maximum CPU usage percentage (0-100).
    memory_limit: Maximum memory usage in MB.
    monitoring_interval: Interval for active monitoring in seconds.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResourceMonitor

## _get_resource_usage

```python
def _get_resource_usage(self) -> dict[str, float]:
    """
    Get current resource usage for the entire program.

Returns:
    A dictionary with current CPU and memory usage.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResourceMonitor

## _log_detailed_memory_information_for_debug_purposes

```python
def _log_detailed_memory_information_for_debug_purposes(self):
    """
    Log detailed memory usage information for debugging purposes.

This method logs comprehensive memory statistics including RSS (Resident Set Size),
VMS (Virtual Memory Size), shared memory usage, system memory percentage, and
the configured memory limit. It also checks for potential memory leak indicators
by warning when memory usage approaches 80% of the configured limit.

The method handles exceptions gracefully and logs any errors that occur during
the memory information gathering process.

Logs:
    DEBUG: Detailed memory usage statistics with RSS, VMS, shared memory,
           system percentage, and memory limit information
    WARNING: When memory usage exceeds 80% of the configured limit
    ERROR: If any exception occurs during memory information logging

Raises:
    None: All exceptions are caught and logged as errors
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResourceMonitor

## _monitoring_loop

```python
def _monitoring_loop(self) -> None:
    """
    Internal monitoring loop.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResourceMonitor

## are_resources_available

```python
@property
def are_resources_available(self) -> tuple[bool, Optional[str]]:
    """
    Check if resources are available for processing.

Returns:
    A tuple of (is_available, reason), where reason is None if resources are available.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResourceMonitor

## current_resource_usage

```python
@property
def current_resource_usage(self) -> dict[str, float]:
    """
    Get current resource usage.

Returns:
    A dictionary with current resource usage.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResourceMonitor

## resource_summary

```python
@property
def resource_summary(self) -> dict[str, Any]:
    """
    Get a summary of resource usage and limits.

Returns:
    A dictionary with resource usage summary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResourceMonitor

## set_resource_limits

```python
def set_resource_limits(self, cpu_limit_percent: Optional[float] = None, memory_limit: Optional[int] = None) -> None:
    """
    Set resource limits.

Args:
    cpu_limit_percent: Maximum CPU usage percentage (0-100).
    memory_limit: Maximum memory usage in MB.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResourceMonitor

## start_monitoring

```python
def start_monitoring(self) -> bool:
    """
    Start active resource monitoring.

Returns:
    True if monitoring started successfully, False otherwise.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResourceMonitor

## stop_monitoring

```python
def stop_monitoring(self) -> None:
    """
    Stop active resource monitoring.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ResourceMonitor
