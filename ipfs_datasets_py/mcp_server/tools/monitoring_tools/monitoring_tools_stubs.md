# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/mcp_server/tools/monitoring_tools/monitoring_tools.py'

Files last updated: 1751408933.7664564

Stub file last updated: 2025-07-07 01:10:14

## _check_cpu_health

```python
async def _check_cpu_health() -> Dict[str, Any]:
    """
    Check CPU health.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## _check_disk_health

```python
async def _check_disk_health() -> Dict[str, Any]:
    """
    Check disk health.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## _check_embeddings_health

```python
async def _check_embeddings_health() -> Dict[str, Any]:
    """
    Check embeddings service health.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## _check_memory_health

```python
async def _check_memory_health() -> Dict[str, Any]:
    """
    Check memory health.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## _check_network_health

```python
async def _check_network_health() -> Dict[str, Any]:
    """
    Check network health.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## _check_service_status

```python
async def _check_service_status(service_name: str) -> Dict[str, Any]:
    """
    Check status of a specific service.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## _check_services_health

```python
async def _check_services_health() -> Dict[str, Any]:
    """
    Check health of key services.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## _check_system_health

```python
async def _check_system_health() -> Dict[str, Any]:
    """
    Check overall system health.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## _check_vector_stores_health

```python
async def _check_vector_stores_health() -> Dict[str, Any]:
    """
    Check vector stores health.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## _generate_health_recommendations

```python
async def _generate_health_recommendations(health_results: Dict[str, Any]) -> List[str]:
    """
    Generate health recommendations based on results.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## _get_performance_metrics

```python
async def _get_performance_metrics() -> Dict[str, Any]:
    """
    Get current performance metrics.
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## generate_monitoring_report

```python
async def generate_monitoring_report(report_type: str = "summary", time_period: str = "24h") -> Dict[str, Any]:
    """
    Generate comprehensive monitoring reports.

Args:
    report_type: Type of report (summary, detailed, performance, alerts)
    time_period: Time period for the report (1h, 6h, 24h, 7d)
    
Returns:
    Dict containing monitoring report
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## get_performance_metrics

```python
async def get_performance_metrics(metric_types: Optional[List[str]] = None, time_range: str = "1h", include_history: bool = True) -> Dict[str, Any]:
    """
    Get system performance metrics and statistics.

Args:
    metric_types: Types of metrics to retrieve
    time_range: Time range for historical metrics (1h, 6h, 24h, 7d)
    include_history: Include historical metrics data
    
Returns:
    Dict containing performance metrics
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## health_check

```python
async def health_check(check_type: str = "basic", components: Optional[List[str]] = None, include_metrics: bool = True) -> Dict[str, Any]:
    """
    Perform comprehensive health checks on system components.

Args:
    check_type: Type of health check (basic, detailed, specific, all)
    components: Specific components to check
    include_metrics: Include detailed metrics in response
    
Returns:
    Dict containing health check results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A

## monitor_services

```python
async def monitor_services(services: Optional[List[str]] = None, check_interval: int = 30) -> Dict[str, Any]:
    """
    Monitor specific services and their health status.

Args:
    services: List of services to monitor
    check_interval: Interval between checks in seconds
    
Returns:
    Dict containing service monitoring results
    """
```
* **Async:** True
* **Method:** False
* **Class:** N/A
