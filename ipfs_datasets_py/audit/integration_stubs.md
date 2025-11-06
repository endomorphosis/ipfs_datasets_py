# Function and Class stubs from '/home/kylerose1946/ipfs_datasets_py/ipfs_datasets_py/audit/integration.py'

Files last updated: 1748635923.4213796

Stub file last updated: 2025-07-07 02:14:36

## AuditContextManager

```python
class AuditContextManager:
    """
    Context manager for comprehensive audit logging in code blocks.

This class provides a convenient way to log the beginning and end
of operations, including timing information and exceptions.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## AuditDatasetIntegrator

```python
class AuditDatasetIntegrator:
    """
    Integrates audit logging with dataset operations.

This class provides utilities for tracking dataset operations
through the audit logging system.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## AuditProvenanceIntegrator

```python
class AuditProvenanceIntegrator:
    """
    Integrates audit logging with data provenance tracking.

This class provides bidirectional integration between audit logging and
data provenance tracking systems, enabling comprehensive tracking and
correlation of system activities.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## IntegratedComplianceReporter

```python
class IntegratedComplianceReporter:
    """
    Integrated compliance reporting with audit logs and provenance data.

This class provides advanced compliance reporting capabilities by combining
audit log data with provenance information, enabling comprehensive
analysis for regulatory compliance.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## ProvenanceAuditSearchIntegrator

```python
class ProvenanceAuditSearchIntegrator:
    """
    Integrated search across audit logs and provenance records.

This class provides unified search capabilities across both audit logs
and provenance records, enabling comprehensive data lineage and compliance
tracing across the system. The enhanced version supports cross-document
lineage-aware searching for better understanding of data flows across
document boundaries.
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## __enter__

```python
def __enter__(self):
    """
    Begin the audited operation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditContextManager

## __exit__

```python
def __exit__(self, exc_type, exc_val, exc_tb):
    """
    End the audited operation.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditContextManager

## __init__

```python
def __init__(self, audit_logger = None, provenance_manager = None):
    """
    Initialize the integrator.

Args:
    audit_logger: AuditLogger instance (optional, will use global instance if None)
    provenance_manager: EnhancedProvenanceManager instance (optional)
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditProvenanceIntegrator

## __init__

```python
def __init__(self, audit_logger = None):
    """
    Initialize the dataset integrator.

Args:
    audit_logger: AuditLogger instance (optional, will use global instance if None)
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditDatasetIntegrator

## __init__

```python
def __init__(self, standard: ComplianceStandard, audit_logger = None, provenance_manager = None):
    """
    Initialize the integrated compliance reporter.

Args:
    standard: The compliance standard to report against
    audit_logger: AuditLogger instance (optional, will use global instance if None)
    provenance_manager: EnhancedProvenanceManager instance (optional)
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntegratedComplianceReporter

## __init__

```python
def __init__(self, category: AuditCategory, action: str, resource_id: Optional[str] = None, resource_type: Optional[str] = None, level: AuditLevel = AuditLevel.INFO, details: Optional[Dict[str, Any]] = None, audit_logger = None):
    """
    Initialize the audit context manager.

Args:
    category: Audit category
    action: Action being performed
    resource_id: ID of the resource being acted upon (optional)
    resource_type: Type of the resource being acted upon (optional)
    level: Audit level
    details: Additional details about the operation (optional)
    audit_logger: AuditLogger instance (optional, will use global instance if None)
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditContextManager

## __init__

```python
def __init__(self, audit_logger = None, provenance_manager = None):
    """
    Initialize the search integrator.

Args:
    audit_logger: AuditLogger instance (optional, will use global instance if None)
    provenance_manager: EnhancedProvenanceManager instance (optional)
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceAuditSearchIntegrator

## _add_compliance_insights

```python
def _add_compliance_insights(self, report: ComplianceReport, analysis: Dict[str, Any]) -> None:
    """
    Add compliance-specific insights based on provenance analysis.

This enhanced version leverages the improved cross-document lineage
analysis to provide more detailed compliance insights, focusing on
document boundaries, cross-document relationships, and data flow patterns.

Args:
    report: The compliance report to enhance
    analysis: The lineage analysis results
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntegratedComplianceReporter

## _add_cross_document_analysis

```python
def _add_cross_document_analysis(self, report: ComplianceReport, records: List[Any], include_lineage_metrics: bool = True) -> None:
    """
    Add cross-document lineage analysis to the compliance report.

This enhanced version uses the improved cross-document lineage features
to provide more comprehensive analysis of data flows across document
boundaries, including document relationship analysis and boundary detection.

Args:
    report: The compliance report to enhance
    records: The provenance records to analyze
    include_lineage_metrics: Whether to include lineage graph metrics
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntegratedComplianceReporter

## _analyze_cross_document_records

```python
def _analyze_cross_document_records(self, source_id: str, records: List[Dict[str, Any]], max_depth: int = 2, link_types: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Analyze cross-document relationships in the search results.

Args:
    source_id: Starting resource ID
    records: List of provenance records
    max_depth: Maximum traversal depth used
    link_types: Link types used for filtering

Returns:
    Dict[str, Any]: Analysis of cross-document relationships
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceAuditSearchIntegrator

## _correlate_results

```python
def _correlate_results(self, audit_events: List[Dict[str, Any]], provenance_records: List[Dict[str, Any]], mode: str = "auto") -> List[Dict[str, Any]]:
    """
    Correlate audit events and provenance records.

This enhanced version improves correlation with support for
document boundary awareness.

Args:
    audit_events: List of audit events
    provenance_records: List of provenance records
    mode: Correlation mode

Returns:
    List[Dict[str, Any]]: Correlated records
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceAuditSearchIntegrator

## _filter_relevant_insights

```python
def _filter_relevant_insights(self, requirement_id: str, insights: List[str]) -> List[str]:
    """
    Filter insights relevant to a specific compliance requirement.

Args:
    requirement_id: ID of the compliance requirement
    insights: List of all insights

Returns:
    List[str]: Insights relevant to the requirement
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntegratedComplianceReporter

## _get_distance_from_source

```python
def _get_distance_from_source(self, graph, source_id, target_id) -> int:
    """
    Get shortest path length between source and target in the graph.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceAuditSearchIntegrator

## _get_document_id_for_record

```python
def _get_document_id_for_record(self, record) -> Optional[str]:
    """
    Extract document ID from a provenance record.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceAuditSearchIntegrator

## _get_relationship_path

```python
def _get_relationship_path(self, graph, source_id, target_id) -> List[Dict[str, str]]:
    """
    Get the relationship path from source to target in the graph.
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceAuditSearchIntegrator

## _provenance_record_to_dict

```python
def _provenance_record_to_dict(self, record: Any) -> Dict[str, Any]:
    """
    Convert a provenance record to a dictionary.

Args:
    record: Provenance record instance

Returns:
    Dict[str, Any]: Dictionary representation of the record
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceAuditSearchIntegrator

## _search_audit_logs

```python
def _search_audit_logs(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Search audit logs based on query parameters.

Args:
    query: Search query parameters

Returns:
    List[Dict[str, Any]]: Matching audit events as dictionaries
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceAuditSearchIntegrator

## _search_cross_document_provenance

```python
def _search_cross_document_provenance(self, resource_id: str, max_depth: int = 2, link_types: Optional[List[str]] = None, start_time: Optional[str] = None, end_time: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Search for provenance records across document boundaries.

This method builds a cross-document lineage graph starting from the specified
resource and traverses document boundaries to find related records.

Args:
    resource_id: Starting resource ID (can be a record ID or document ID)
    max_depth: Maximum traversal depth across documents
    link_types: Optional list of link types to filter by
    start_time: Optional start time for temporal filtering
    end_time: Optional end time for temporal filtering

Returns:
    List[Dict[str, Any]]: Related provenance records across document boundaries
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceAuditSearchIntegrator

## _search_provenance_records

```python
def _search_provenance_records(self, query: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Search provenance records based on query parameters.

Args:
    query: Search query parameters

Returns:
    List[Dict[str, Any]]: Matching provenance records as dictionaries
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceAuditSearchIntegrator

## add_requirement

```python
def add_requirement(self, requirement: ComplianceRequirement) -> None:
    """
    Add a compliance requirement to check.

Args:
    requirement: The compliance requirement to add
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntegratedComplianceReporter

## audit_from_provenance_record

```python
def audit_from_provenance_record(self, record: Any, additional_details: Dict[str, Any] = None) -> Optional[str]:
    """
    Generate an audit event from a provenance record.

Args:
    record: Provenance record (SourceRecord, TransformationRecord, etc.)
    additional_details: Additional details to include in the audit event

Returns:
    str: Event ID of the generated audit event, or None if failed
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditProvenanceIntegrator

## audit_function

```python
def audit_function(category: AuditCategory, action: str, resource_id_arg: Optional[str] = None, resource_type: Optional[str] = None, level: AuditLevel = AuditLevel.INFO, details_extractor: Optional[Callable] = None):
    """
    Decorator for auditing function calls.

This decorator logs the start and end of function execution,
including timing information and exceptions.

Args:
    category: Audit category
    action: Action being performed
    resource_id_arg: Name of the argument containing the resource ID (optional)
    resource_type: Type of the resource being acted upon (optional)
    level: Audit level
    details_extractor: Function to extract additional details from arguments (optional)

Returns:
    Callable: Decorated function
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## audit_to_provenance_handler

```python
def audit_to_provenance_handler(event: AuditEvent):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## decorator

```python
def decorator(func):
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## generate_integrated_compliance_report

```python
def generate_integrated_compliance_report(standard_name: str, start_time: Optional[str] = None, end_time: Optional[str] = None, output_format: str = "json", output_path: Optional[str] = None) -> Optional[Union[str, Dict[str, Any]]]:
    """
    Generate an integrated compliance report combining audit and provenance data.

This function demonstrates the use of the IntegratedComplianceReporter to
generate comprehensive compliance reports.

Args:
    standard_name: Name of the compliance standard (GDPR, HIPAA, SOC2, etc.)
    start_time: Start time for the report period (ISO format, optional)
    end_time: End time for the report period (ISO format, optional)
    output_format: Format for the report output (json, html, csv)
    output_path: Path to save the report (optional)

Returns:
    Optional[Union[str, Dict[str, Any]]]: The report data in the requested format,
                                     or None if saved to a file
    """
```
* **Async:** False
* **Method:** False
* **Class:** N/A

## generate_report

```python
def generate_report(self, start_time: Optional[str] = None, end_time: Optional[str] = None, include_cross_document_analysis: bool = True, include_lineage_metrics: bool = True) -> ComplianceReport:
    """
    Generate an integrated compliance report using both audit and provenance data.

Args:
    start_time: Start time for the report period (ISO format)
    end_time: End time for the report period (ISO format)
    include_cross_document_analysis: Whether to include cross-document lineage analysis
    include_lineage_metrics: Whether to include lineage graph metrics

Returns:
    ComplianceReport: The generated compliance report
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntegratedComplianceReporter

## get_audit_events

```python
def get_audit_events(self, start_time: Optional[str] = None, end_time: Optional[str] = None) -> List[AuditEvent]:
    """
    Get audit events for a specific time period.

This method should be implemented by derived classes that know
how to fetch audit events from various storage backends.

Args:
    start_time: Start time for the report period (ISO format)
    end_time: End time for the report period (ISO format)

Returns:
    List[AuditEvent]: The retrieved audit events
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntegratedComplianceReporter

## get_provenance_records

```python
def get_provenance_records(self, start_time: Optional[str] = None, end_time: Optional[str] = None) -> List[Any]:
    """
    Get provenance records for a specific time period.

Args:
    start_time: Start time for the report period (ISO format)
    end_time: End time for the report period (ISO format)

Returns:
    List[Any]: The retrieved provenance records
    """
```
* **Async:** False
* **Method:** True
* **Class:** IntegratedComplianceReporter

## initialize_provenance_manager

```python
def initialize_provenance_manager(self):
    """
    Initialize the provenance manager if not already done.
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditProvenanceIntegrator

## link_audit_to_provenance

```python
def link_audit_to_provenance(self, audit_event_id: str, provenance_record_id: str) -> bool:
    """
    Create a link between an audit event and a provenance record.

Args:
    audit_event_id: ID of the audit event
    provenance_record_id: ID of the provenance record

Returns:
    bool: Whether the linking was successful
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditProvenanceIntegrator

## provenance_from_audit_event

```python
def provenance_from_audit_event(self, event: AuditEvent) -> Optional[str]:
    """
    Generate a provenance record from an audit event.

Args:
    event: The audit event to convert

Returns:
    str: Record ID of the generated provenance record, or None if failed
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditProvenanceIntegrator

## record_dataset_load

```python
def record_dataset_load(self, dataset_name: str, dataset_id: Optional[str] = None, source: Optional[str] = None, user: Optional[str] = None) -> Optional[str]:
    """
    Record dataset loading operation in audit log.

Args:
    dataset_name: Name of the dataset
    dataset_id: ID of the dataset (optional)
    source: Source of the dataset (e.g., "local", "huggingface", "ipfs")
    user: User performing the operation (optional)

Returns:
    str: Event ID of the generated audit event, or None if failed
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditDatasetIntegrator

## record_dataset_query

```python
def record_dataset_query(self, dataset_name: str, query: str, query_type: Optional[str] = None, user: Optional[str] = None) -> Optional[str]:
    """
    Record dataset query operation in audit log.

Args:
    dataset_name: Name or ID of the dataset
    query: The query executed
    query_type: Type of query (e.g., "sql", "vector", "graph")
    user: User performing the operation (optional)

Returns:
    str: Event ID of the generated audit event, or None if failed
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditDatasetIntegrator

## record_dataset_save

```python
def record_dataset_save(self, dataset_name: str, dataset_id: Optional[str] = None, destination: Optional[str] = None, format: Optional[str] = None, user: Optional[str] = None) -> Optional[str]:
    """
    Record dataset saving operation in audit log.

Args:
    dataset_name: Name of the dataset
    dataset_id: ID of the dataset (optional)
    destination: Destination for saving (e.g., "local", "huggingface", "ipfs")
    format: Format of the saved dataset (e.g., "parquet", "car", "arrow")
    user: User performing the operation (optional)

Returns:
    str: Event ID of the generated audit event, or None if failed
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditDatasetIntegrator

## record_dataset_transform

```python
def record_dataset_transform(self, input_dataset: str, output_dataset: str, transformation_type: str, parameters: Optional[Dict[str, Any]] = None, user: Optional[str] = None) -> Optional[str]:
    """
    Record dataset transformation operation in audit log.

Args:
    input_dataset: Name or ID of the input dataset
    output_dataset: Name or ID of the output dataset
    transformation_type: Type of transformation applied
    parameters: Parameters of the transformation (optional)
    user: User performing the operation (optional)

Returns:
    str: Event ID of the generated audit event, or None if failed
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditDatasetIntegrator

## search

```python
def search(self, query: Dict[str, Any], include_audit: bool = True, include_provenance: bool = True, correlation_mode: str = "auto", include_cross_document: bool = False) -> Dict[str, Any]:
    """
    Perform a unified search across audit logs and provenance records.

This enhanced version supports cross-document lineage-aware searching,
allowing for discovery of related records across document boundaries.

Args:
    query: Dictionary containing search parameters
        - timerange: Dict with 'start' and 'end' timestamps
        - user: Optional user to filter by
        - resource_id: Optional resource ID to filter by
        - resource_type: Optional resource type to filter by
        - action: Optional action to filter by
        - status: Optional status to filter by
        - details: Optional dict of details to filter by
        - keywords: Optional list of keywords to search for
        - document_id: Optional document ID for cross-document search
        - link_types: Optional list of link types to filter by
        - max_results: Optional maximum number of results to return
        - max_depth: Optional maximum traversal depth for cross-document search
    include_audit: Whether to include audit events in results
    include_provenance: Whether to include provenance records in results
    correlation_mode: How to correlate audit and provenance records
        - "auto": Automatically detect and establish correlations
        - "linked": Only show records with explicit links
        - "none": Do not correlate records
    include_cross_document: Whether to include cross-document analysis

Returns:
    Dict[str, Any]: Search results with integrated audit and provenance data
    """
```
* **Async:** False
* **Method:** True
* **Class:** ProvenanceAuditSearchIntegrator

## setup_audit_event_listener

```python
def setup_audit_event_listener(self) -> bool:
    """
    Set up automatic provenance record creation from audit events.

This method adds a listener to the audit logger that automatically
creates corresponding provenance records for relevant audit events.

Returns:
    bool: Whether the listener was successfully set up
    """
```
* **Async:** False
* **Method:** True
* **Class:** AuditProvenanceIntegrator

## wrapper

```python
def wrapper(*args, **kwargs):
```
* **Async:** False
* **Method:** False
* **Class:** N/A
