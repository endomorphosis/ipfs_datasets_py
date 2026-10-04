# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/audit/audit_provenance_integration.py'

Files last updated: 1748635923.4113796

Stub file last updated: 2025-07-07 02:14:36

## AuditProvenanceDashboard

```python
class AuditProvenanceDashboard:
    """
    Integrated dashboard combining audit visualization with provenance tracking.

This class provides a unified view of audit events, data lineage, and query performance,
enabling comprehensive monitoring and analysis of data transformations and usage.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, audit_metrics: Optional[AuditMetricsAggregator] = None, provenance_dashboard: Optional[ProvenanceDashboard] = None, audit_logger: Optional[AuditLogger] = None, query_visualizer: Optional[RAGQueryVisualizer] = None):
    """
    Initialize the integrated audit-provenance dashboard.

Args:
    audit_metrics: Optional AuditMetricsAggregator for audit visualization
    provenance_dashboard: Optional ProvenanceDashboard for provenance tracking
    audit_logger: Optional AuditLogger for capturing new audit events
    query_visualizer: Optional RAGQueryVisualizer for GraphRAG query metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditProvenanceDashboard

## _get_audit_events_for_entities

```python
def _get_audit_events_for_entities(self, data_ids: List[str], hours: int = 24) -> List[Dict[str, Any]]:
    """
    Get audit events related to specific data entities.

Args:
    data_ids: List of data entity IDs
    hours: Number of hours to look back

Returns:
    List[Dict[str, Any]]: List of audit events
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditProvenanceDashboard

## _get_provenance_events

```python
def _get_provenance_events(self, data_ids: List[str]) -> List[Dict[str, Any]]:
    """
    Get provenance events for specific data entities.

Args:
    data_ids: List of data entity IDs

Returns:
    List[Dict[str, Any]]: List of provenance events
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditProvenanceDashboard

## _get_provenance_metrics

```python
def _get_provenance_metrics(self) -> Dict[str, Any]:
    """
    Get metrics about provenance tracking.

Returns:
    Dict[str, Any]: Provenance metrics summary
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditProvenanceDashboard

## _get_recent_entities

```python
def _get_recent_entities(self, limit: int = 10) -> List[str]:
    """
    Get the most recent data entities from the provenance manager.

Args:
    limit: Maximum number of entities to return

Returns:
    List[str]: List of recent entity IDs
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditProvenanceDashboard

## create_integrated_dashboard

```python
def create_integrated_dashboard(self, output_dir: str, data_ids: Optional[List[str]] = None, dashboard_name: str = "integrated_dashboard.html") -> str:
    """
    Create an integrated dashboard with audit, provenance, and query metrics.

Args:
    output_dir: Directory to save the dashboard files
    data_ids: Optional list of data IDs to focus on
    dashboard_name: Name of the main dashboard HTML file

Returns:
    str: Path to the main dashboard file
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditProvenanceDashboard

## create_provenance_audit_timeline

```python
def create_provenance_audit_timeline(self, data_ids: List[str], hours: int = 24, output_file: Optional[str] = None, return_base64: bool = False) -> Optional[str]:
    """
    Create a timeline visualization showing both provenance events and audit events.

Args:
    data_ids: List of data entity IDs to visualize
    hours: Number of hours to include in the timeline
    output_file: Optional path to save the visualization
    return_base64: Whether to return the image as base64

Returns:
    str: Base64-encoded image or file path if output_file is specified
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditProvenanceDashboard

## create_provenance_metrics_comparison

```python
def create_provenance_metrics_comparison(self, metrics_type: str = "overview", output_file: Optional[str] = None, return_base64: bool = False, interactive: bool = False) -> Optional[str]:
    """
    Create a visualization comparing provenance metrics with audit metrics.

Args:
    metrics_type: Type of metrics to compare ('overview', 'performance', 'security')
    output_file: Optional path to save the visualization
    return_base64: Whether to return the image as base64
    interactive: Whether to create an interactive visualization

Returns:
    str: Base64-encoded image or file path if output_file is specified
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditProvenanceDashboard

## setup_audit_provenance_dashboard

```python
def setup_audit_provenance_dashboard(audit_logger: Optional[AuditLogger] = None, provenance_manager: Optional[ProvenanceManager] = None, query_visualizer: Optional[RAGQueryVisualizer] = None) -> AuditProvenanceDashboard:
    """
    Set up an integrated audit-provenance dashboard with all available components.

Args:
    audit_logger: Optional AuditLogger instance
    provenance_manager: Optional ProvenanceManager instance
    query_visualizer: Optional RAGQueryVisualizer instance

Returns:
    AuditProvenanceDashboard: Configured dashboard instance
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A
