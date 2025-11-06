# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/provenance_dashboard.py'

Files last updated: 1751870100.3227623

Stub file last updated: 2025-07-07 02:11:02

## ProvenanceDashboard

```python
class ProvenanceDashboard:
    """
    Dashboard for data provenance visualization and analysis.

This class creates an interactive dashboard for exploring data provenance
information, including lineage graphs, audit events, and integration with
RAG query metrics.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, provenance_manager: ProvenanceManager, lineage_tracker: Optional[EnhancedLineageTracker] = None, query_visualizer: Optional[RAGQueryVisualizer] = None):
    """
    Initialize the provenance dashboard.

Args:
    provenance_manager: ProvenanceManager for tracking data provenance
    lineage_tracker: Optional EnhancedLineageTracker for cross-document lineage
    query_visualizer: Optional RAGQueryVisualizer for RAG query metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceDashboard

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
* **Class:** ProvenanceDashboard

## create_integrated_dashboard

```python
def create_integrated_dashboard(self, output_dir: str, data_ids: Optional[List[str]] = None, include_audit: bool = True, include_query: bool = True, include_cross_doc: bool = True, dashboard_name: str = "provenance_dashboard.html") -> str:
    """
    Create an integrated dashboard with provenance, audit, and query metrics.

Args:
    output_dir: Directory to save the dashboard files
    data_ids: Optional list of data IDs to focus on, None for all
    include_audit: Whether to include audit metrics
    include_query: Whether to include query metrics
    include_cross_doc: Whether to include cross-document lineage
    dashboard_name: Name of the main dashboard HTML file

Returns:
    str: Path to the main dashboard file
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceDashboard

## extract_nodes

```python
def extract_nodes(lin, depth = 0):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## format_json

```python
def format_json(data):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## format_timestamp

```python
def format_timestamp(timestamp):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## generate_provenance_report

```python
def generate_provenance_report(self, data_ids: List[str], format: str = "html", include_lineage_graph: bool = True, include_audit_events: bool = True, include_query_metrics: bool = True, output_file: Optional[str] = None) -> Optional[str]:
    """
    Generate a comprehensive provenance report for specified data entities.

Args:
    data_ids: List of data entity IDs to include in the report
    format: Report format ('html', 'md', 'json')
    include_lineage_graph: Whether to include lineage graph visualization
    include_audit_events: Whether to include related audit events
    include_query_metrics: Whether to include related query metrics
    output_file: Optional path to save the report

Returns:
    str: Report content or file path if output_file is specified
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceDashboard

## setup_provenance_dashboard

```python
def setup_provenance_dashboard(provenance_manager: Optional[ProvenanceManager] = None, lineage_tracker: Optional[Any] = None, query_metrics: Optional[Any] = None, audit_metrics: Optional[Any] = None) -> ProvenanceDashboard:
    """
    Set up a provenance dashboard with all available components.

Args:
    provenance_manager: Optional ProvenanceManager instance
    lineage_tracker: Optional EnhancedLineageTracker instance
    query_metrics: Optional QueryMetricsCollector instance
    audit_metrics: Optional AuditMetricsAggregator instance

Returns:
    ProvenanceDashboard: Configured dashboard instance
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## visualize_cross_document_lineage

```python
def visualize_cross_document_lineage(self, document_ids: List[str], relationship_types: Optional[List[str]] = None, max_depth: int = 3, output_file: Optional[str] = None, return_base64: bool = False, interactive: bool = False) -> Optional[str]:
    """
    Visualize cross-document lineage relationships.

Args:
    document_ids: List of document IDs to visualize
    relationship_types: Optional filter for relationship types
    max_depth: Maximum depth for relationship traversal
    output_file: Optional path to save the visualization
    return_base64: Whether to return the image as base64
    interactive: Whether to create an interactive visualization

Returns:
    str: Base64-encoded image or None if visualization not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceDashboard

## visualize_data_lineage

```python
def visualize_data_lineage(self, data_ids: List[str], max_depth: int = 5, include_parameters: bool = True, show_timestamps: bool = True, output_file: Optional[str] = None, return_base64: bool = False, interactive: bool = False) -> Optional[str]:
    """
    Visualize data lineage for specified data entities.

Args:
    data_ids: List of data entity IDs to visualize
    max_depth: Maximum depth to trace back
    include_parameters: Whether to include operation parameters
    show_timestamps: Whether to show timestamps
    output_file: Optional path to save the visualization
    return_base64: Whether to return the image as base64
    interactive: Whether to create an interactive visualization

Returns:
    str: Base64-encoded image or None if visualization not available
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceDashboard
