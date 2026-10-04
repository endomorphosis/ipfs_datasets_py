# Function and Class stubs from '<repo-root>/ipfs_datasets_py/ipfs_datasets_py/audit/provenance_consumer.py'

Files last updated: 1748635923.4213796

Stub file last updated: 2025-07-07 02:14:36

## IntegratedProvenanceRecord

```python
@dataclass
class IntegratedProvenanceRecord:
    """
    Unified representation of a provenance record with audit information.

This class combines data from both the provenance system and audit logging
system into a single record for easier consumption by applications.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ProvenanceConsumer

```python
class ProvenanceConsumer:
    """
    Unified interface for consuming integrated provenance information.

This class provides methods to access, query, and process provenance
information from both the audit logging and data provenance systems.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __init__

```python
def __init__(self, provenance_manager: Optional[Any] = None, audit_logger: Optional[Any] = None, integrator: Optional[Any] = None):
    """
    Initialize the provenance consumer.

Args:
    provenance_manager: EnhancedProvenanceManager instance
    audit_logger: AuditLogger instance
    integrator: AuditProvenanceIntegrator instance
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceConsumer

## _add_lineage_records

```python
def _add_lineage_records(self, record_id: str, results: List[IntegratedProvenanceRecord], limit: int, depth: int = 0, visited: Optional[Set[str]] = None) -> None:
    """
    Helper method to add lineage records recursively.

Args:
    record_id: Starting record ID
    results: List to add results to
    limit: Maximum number of records to add
    depth: Current recursion depth
    visited: Set of already visited record IDs
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceConsumer

## _build_lineage_graph

```python
def _build_lineage_graph(self, record_id: str, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]], visited: Set[str], depth: int, max_depth: int, include_audit_events: bool) -> None:
    """
    Helper method to build lineage graph recursively.

Args:
    record_id: Current record ID
    nodes: List to add nodes to
    edges: List to add edges to
    visited: Set of already visited record IDs
    depth: Current recursion depth
    max_depth: Maximum recursion depth
    include_audit_events: Whether to include audit events
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceConsumer

## export_provenance

```python
def export_provenance(self, data_id: str, format: str = "json", include_audit_events: bool = True, max_depth: int = 10) -> Union[str, Dict[str, Any]]:
    """
    Export provenance information for a data entity.

Args:
    data_id: ID of the data entity
    format: Export format ("json", "dict", "graph")
    include_audit_events: Whether to include audit events
    max_depth: Maximum depth of the lineage graph

Returns:
    Union[str, Dict[str, Any]]: Exported provenance information
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceConsumer

## get_integrated_record

```python
def get_integrated_record(self, record_id: str) -> Optional[IntegratedProvenanceRecord]:
    """
    Get an integrated provenance record by ID.

Args:
    record_id: ID of the provenance record

Returns:
    IntegratedProvenanceRecord or None if not found
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceConsumer

## get_lineage_graph

```python
def get_lineage_graph(self, data_id: str, max_depth: int = 5, include_audit_events: bool = True) -> Dict[str, Any]:
    """
    Get lineage graph for a data entity.

Args:
    data_id: ID of the data entity
    max_depth: Maximum depth of the lineage graph
    include_audit_events: Whether to include audit events in the graph

Returns:
    Dict[str, Any]: Graph representation with nodes and edges
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceConsumer

## search_integrated_records

```python
def search_integrated_records(self, query: str = "", record_types: Optional[List[str]] = None, start_time: Optional[float] = None, end_time: Optional[float] = None, data_ids: Optional[List[str]] = None, limit: int = 100) -> List[IntegratedProvenanceRecord]:
    """
    Search for integrated provenance records.

Args:
    query: Search query string
    record_types: Types of records to include
    start_time: Start timestamp
    end_time: End timestamp
    data_ids: Data entity IDs to filter by
    limit: Maximum number of results

Returns:
    List[IntegratedProvenanceRecord]: Matching records
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceConsumer

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert the integrated record to a dictionary.
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntegratedProvenanceRecord

## to_json

```python
def to_json(self, pretty = False) -> str:
    """
    Serialize the integrated record to JSON.
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntegratedProvenanceRecord

## verify_data_lineage

```python
def verify_data_lineage(self, data_id: str) -> Dict[str, Any]:
    """
    Verify the integrity and authenticity of a data entity's lineage.

Args:
    data_id: ID of the data entity

Returns:
    Dict[str, Any]: Verification results with details
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceConsumer
