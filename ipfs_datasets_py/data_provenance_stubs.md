# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/data_provenance.py'

Files last updated: 1751507211.4208906

Stub file last updated: 2025-07-07 02:11:01

## MergeRecord

```python
@dataclass
class MergeRecord(ProvenanceRecord):
    """
    Record for merging multiple data sources.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ProvenanceContext

```python
class ProvenanceContext:
    """
    Context manager for tracking data provenance.

This class provides a convenient way to track data transformations
using a context manager.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ProvenanceManager

```python
class ProvenanceManager:
    """
    Manages data provenance tracking with detailed lineage.

This class provides the main interface for tracking provenance
throughout the data processing lifecycle.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ProvenanceRecord

```python
@dataclass
class ProvenanceRecord:
    """
    Base class for provenance records.

This class represents a fundamental unit of provenance information, tracking
the essential details of data operations and transformations within the system.
Each record captures metadata about what happened, when it happened, who or
what performed the operation, and how different data entities are related.

Attributes:
    id: Unique identifier for this provenance record
    record_type: Type of provenance operation (source, transformation, etc.)
    timestamp: When this record was created (Unix timestamp)
    agent_id: Identifier of the agent (user, system, tool) that performed the operation
    description: Human-readable description of what this record represents
    metadata: Additional key-value metadata for extensibility
    input_ids: List of data entity IDs that were inputs to this operation
    output_ids: List of data entity IDs that were outputs from this operation
    parameters: Operation-specific parameters and configuration
    cid: Content identifier for IPFS/IPLD storage integration
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ProvenanceRecordType

```python
class ProvenanceRecordType(Enum):
    """
    Types of records in the provenance tracking system.

This enumeration defines the different types of operations and events that can be
tracked in a data provenance system. Each type represents a specific kind of
data processing or handling operation.

Attributes:
    SOURCE: Represents the original data source or initial data ingestion point.
    TRANSFORMATION: Represents data transformation operations such as cleaning,
        normalization, or format conversion.
    MERGE: Represents operations that combine multiple data sources or datasets
        into a single dataset.
    FILTER: Represents operations that filter or subset data based on specific
        criteria or conditions.
    EXPORT: Represents operations that export data to external formats or systems.
    IMPORT: Represents operations that import data from external sources or formats.
    QUERY: Represents data query operations or database lookups.
    RESULT: Represents the outcome or result of a query, computation, or operation.
    CHECKPOINT: Represents checkpoints or snapshots of data state for recovery
        or versioning purposes.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## QueryRecord

```python
@dataclass
class QueryRecord(ProvenanceRecord):
    """
    Record for a query operation.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ResultRecord

```python
@dataclass
class ResultRecord(ProvenanceRecord):
    """
    Record for an operation result.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## SourceRecord

```python
@dataclass
class SourceRecord(ProvenanceRecord):
    """
    Record for an original data source.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## TransformationRecord

```python
@dataclass
class TransformationRecord(ProvenanceRecord):
    """
    Record for a data transformation operation.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __enter__

```python
def __enter__(self) -> "ProvenanceContext":
    """
    Begin tracking a data transformation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceContext

## __exit__

```python
def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
    """
    End tracking a data transformation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceContext

## __init__

```python
def __init__(self, storage_path: Optional[str] = None, enable_ipld_storage: bool = False, default_agent_id: Optional[str] = None, tracking_level: str = "detailed"):
    """
    Initialize the provenance manager.

Args:
    storage_path: Path to store provenance data, None for in-memory only
    enable_ipld_storage: Whether to use IPLD for provenance storage
    default_agent_id: Default agent ID for provenance records
    tracking_level: Level of detail for provenance tracking
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceManager

## __init__

```python
def __init__(self, provenance_manager: ProvenanceManager, description: str, transformation_type: str, tool: str = "", version: str = "", input_ids: Optional[List[str]] = None, parameters: Optional[Dict[str, Any]] = None, metadata: Optional[Dict[str, Any]] = None):
    """
    Initialize the provenance context.

Args:
    provenance_manager: Provenance manager to use
    description: Description of the transformation
    transformation_type: Type of transformation
    tool: Tool used for transformation
    version: Tool version
    input_ids: IDs of input data entities
    parameters: Transformation parameters
    metadata: Additional metadata
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceContext

## _generate_html_report

```python
def _generate_html_report(self, records: List[ProvenanceRecord], include_parameters: bool) -> str:
    """
    Generate an HTML audit report.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceManager

## _generate_json_report

```python
def _generate_json_report(self, records: List[ProvenanceRecord], include_parameters: bool) -> str:
    """
    Generate a JSON audit report.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceManager

## _generate_markdown_report

```python
def _generate_markdown_report(self, records: List[ProvenanceRecord], include_parameters: bool) -> str:
    """
    Generate a Markdown audit report.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceManager

## _generate_text_report

```python
def _generate_text_report(self, records: List[ProvenanceRecord], include_parameters: bool) -> str:
    """
    Generate a text audit report.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceManager

## begin_transformation

```python
def begin_transformation(self, description: str, transformation_type: str, tool: str = "", version: str = "", input_ids: Optional[List[str]] = None, parameters: Optional[Dict[str, Any]] = None, metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Begin tracking a data transformation.

Args:
    description: Description of the transformation
    transformation_type: Type of transformation
    tool: Tool used for transformation
    version: Tool version
    input_ids: IDs of input data entities
    parameters: Transformation parameters
    metadata: Additional metadata

Returns:
    str: ID of the created transformation record
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceManager

## end_transformation

```python
def end_transformation(self, transformation_id: str, output_ids: Optional[List[str]] = None, success: bool = True, error_message: Optional[str] = None) -> str:
    """
    End tracking a data transformation.

Args:
    transformation_id: ID of the transformation record
    output_ids: IDs of output data entities
    success: Whether transformation succeeded
    error_message: Error message if transformation failed

Returns:
    str: ID of the updated transformation record
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceManager

## example_usage

```python
def example_usage():
    """
    Example usage of the provenance tracking system.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## export_provenance_to_dict

```python
def export_provenance_to_dict(self) -> Dict[str, Any]:
    """
    Export all provenance records as a dictionary.

Returns:
    Dict: Provenance records and metadata
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceManager

## export_provenance_to_json

```python
def export_provenance_to_json(self, file_path: Optional[str] = None) -> Optional[str]:
    """
    Export all provenance records as JSON.

Args:
    file_path: Path to write JSON file, None to return JSON string

Returns:
    str: JSON string if file_path is None
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceManager

## from_dict

```python
@classmethod
def from_dict(cls, data: Dict[str, Any]) -> "ProvenanceRecord":
    """
    Create record from dictionary representation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceRecord

## generate_audit_report

```python
def generate_audit_report(self, data_ids: Optional[List[str]] = None, start_time: Optional[float] = None, end_time: Optional[float] = None, agent_id: Optional[str] = None, operation_types: Optional[List[str]] = None, include_parameters: bool = False, format: str = "text") -> str:
    """
    Generate an audit report for specified data entities.

Args:
    data_ids: List of data entity IDs to include, None for all
    start_time: Start time for filtering records
    end_time: End time for filtering records
    agent_id: Agent ID for filtering records
    operation_types: List of operation types to include
    include_parameters: Whether to include operation parameters
    format: Output format

Returns:
    str: Audit report in the specified format
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceManager

## get_data_lineage

```python
def get_data_lineage(self, data_id: str, max_depth: int = 10) -> Dict[str, Any]:
    """
    Get the lineage of a data entity.

Args:
    data_id: ID of the data entity
    max_depth: Maximum depth to trace back

Returns:
    Dict: Lineage information
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceManager

## import_provenance_from_dict

```python
def import_provenance_from_dict(self, provenance_dict: Dict[str, Any]) -> None:
    """
    Import provenance records from a dictionary.

Args:
    provenance_dict: Dictionary containing provenance records
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceManager

## import_provenance_from_file

```python
def import_provenance_from_file(self, file_path: str) -> None:
    """
    Import provenance records from a JSON file.

Args:
    file_path: Path to JSON file
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceManager

## import_provenance_from_json

```python
def import_provenance_from_json(self, json_str: str) -> None:
    """
    Import provenance records from a JSON string.

Args:
    json_str: JSON string containing provenance records
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceManager

## record_checkpoint

```python
def record_checkpoint(self, data_id: str, description: str = "", checkpoint_type: str = "snapshot", metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Record a checkpoint/snapshot of a data entity.

Args:
    data_id: ID of the data entity
    description: Description of the checkpoint
    checkpoint_type: Type of checkpoint
    metadata: Additional metadata

Returns:
    str: ID of the created checkpoint record
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceManager

## record_merge

```python
def record_merge(self, input_ids: List[str], output_id: str, merge_type: str, description: str = "", merge_keys: Optional[List[str]] = None, merge_strategy: str = "default", parameters: Optional[Dict[str, Any]] = None, metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Record a data merge operation.

Args:
    input_ids: IDs of input data entities
    output_id: ID of output data entity
    merge_type: Type of merge
    description: Description of the merge
    merge_keys: Keys used for joining if applicable
    merge_strategy: Strategy for conflict resolution
    parameters: Merge parameters
    metadata: Additional metadata

Returns:
    str: ID of the created merge record
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceManager

## record_query

```python
def record_query(self, input_ids: List[str], query_type: str, query_text: str, description: str = "", query_parameters: Optional[Dict[str, Any]] = None, metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Record a data query operation.

Args:
    input_ids: IDs of input data entities
    query_type: Type of query
    query_text: Raw query text or representation
    description: Description of the query
    query_parameters: Query parameters
    metadata: Additional metadata

Returns:
    str: ID of the created query record
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceManager

## record_query_result

```python
def record_query_result(self, query_id: str, output_id: str, result_count: Optional[int] = None, result_type: str = "", size: Optional[int] = None, fields: Optional[List[str]] = None, sample: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Record the result of a query operation.

Args:
    query_id: ID of the query record
    output_id: ID of output data entity
    result_count: Number of results returned
    result_type: Type of result
    size: Size of result in bytes if applicable
    fields: Fields in result if applicable
    sample: Sample of result if applicable
    metadata: Additional metadata

Returns:
    str: ID of the created result record
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceManager

## record_source

```python
def record_source(self, data_id: str, source_type: str, location: str, format: str = "", description: str = "", size: Optional[int] = None, hash: Optional[str] = None, metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Record an original data source.

Args:
    data_id: Identifier for the data entity
    source_type: Type of source (file, database, etc.)
    location: Source location (path, URL, etc.)
    format: Data format
    description: Description of the source
    size: Size in bytes if known
    hash: Content hash if available
    metadata: Additional metadata

Returns:
    str: ID of the created provenance record
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceManager

## set_output_ids

```python
def set_output_ids(self, output_ids: List[str]) -> None:
    """
    Set the output data entity IDs.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceContext

## to_dict

```python
def to_dict(self) -> Dict[str, Any]:
    """
    Convert record to dictionary representation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceRecord

## trace_parents

```python
def trace_parents(node_id, current_lineage, current_depth):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## visualize_provenance

```python
def visualize_provenance(self, data_ids: Optional[List[str]] = None, max_depth: int = 5, include_parameters: bool = False, show_timestamps: bool = True, file_path: Optional[str] = None, return_base64: bool = False) -> Optional[str]:
    """
    Visualize the provenance graph for specified data entities.

Args:
    data_ids: List of data entity IDs to visualize, None for all
    max_depth: Maximum depth to trace back
    include_parameters: Whether to include operation parameters
    show_timestamps: Whether to show timestamps
    file_path: Path to save the visualization
    return_base64: Whether to return the image as base64

Returns:
    str: Base64-encoded image if return_base64 is True
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceManager
