# Audit Logging System

The IPFS Datasets Python library includes a comprehensive audit logging system that provides detailed tracking of all operations performed on datasets, with particular emphasis on security, compliance, and data lineage.

## Overview

The audit logging system is designed to:

1. Record all significant operations on datasets and system components
2. Provide detailed context for each operation, including who, what, when, and how
3. Enable compliance with regulations and internal policies
4. Integrate with data provenance tracking for complete lineage information
5. Support security monitoring and intrusion detection
6. Enable cryptographic verification of audit records

## Core Components

### AuditLogger

The central component that records and manages audit events:

```python
from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditLevel, AuditCategory

# Get the singleton instance
audit_logger = AuditLogger.get_instance()

# Log an audit event
event_id = audit_logger.log(
    level=AuditLevel.INFO,
    category=AuditCategory.DATA_MODIFICATION,
    action="dataset_transform",
    resource_id="example_dataset",
    resource_type="dataset",
    details={
        "transformation": "normalization",
        "parameters": {"method": "z-score"}
    }
)
```

### AuditEvent

A comprehensive data structure capturing all relevant information about an operation:

```python
from ipfs_datasets_py.audit.audit_logger import AuditEvent

# Create an audit event directly
event = AuditEvent(
    event_id="unique-id-123",
    timestamp="2023-10-25T14:30:00Z",
    level=AuditLevel.INFO,
    category=AuditCategory.DATA_ACCESS,
    action="dataset_load",
    user="user123",
    resource_id="example_dataset",
    resource_type="dataset",
    details={"source": "huggingface"}
)
```

### AuditHandler

Base class for handling audit events (e.g., storing to files, databases, or sending to external systems):

```python
from ipfs_datasets_py.audit.handlers import FileAuditHandler, ConsoleAuditHandler

# Add handlers to the logger
audit_logger.add_handler(FileAuditHandler(
    name="file_handler",
    filename="audit_log.jsonl"
))

audit_logger.add_handler(ConsoleAuditHandler(
    name="console_handler"
))
```

## Event Categories and Levels

### Categories

Audit events are categorized to enable efficient filtering and analysis:

- `AUTHENTICATION`: User login/logout events
- `AUTHORIZATION`: Permission checks and access control
- `DATA_ACCESS`: Reading data or metadata
- `DATA_MODIFICATION`: Writing, updating, or deleting data
- `CONFIGURATION`: System configuration changes
- `RESOURCE`: Resource creation, deletion, modification
- `SECURITY`: Security-related events
- `SYSTEM`: System-level events
- `API`: API calls and responses
- `COMPLIANCE`: Compliance-related events
- `PROVENANCE`: Data provenance tracking
- `OPERATIONAL`: General operational events
- `INTRUSION_DETECTION`: Possible security breaches
- `CUSTOM`: Custom event categories

### Levels

Events are assigned severity levels:

- `DEBUG`: Detailed information for debugging
- `INFO`: Regular operational information
- `NOTICE`: Significant but normal events
- `WARNING`: Potential issues that don't affect operation
- `ERROR`: Errors that affect specific operations
- `CRITICAL`: Serious errors that affect multiple operations
- `EMERGENCY`: System is unusable

## Integration with Data Provenance

The audit logging system integrates tightly with the data provenance tracking system to provide comprehensive lineage information:

### AuditProvenanceIntegrator

The AuditProvenanceIntegrator provides bidirectional integration between audit logging and data provenance systems:

```python
from ipfs_datasets_py.audit.integration import AuditProvenanceIntegrator
from ipfs_datasets_py.data_provenance_enhanced import EnhancedProvenanceManager

# Initialize components
audit_logger = AuditLogger.get_instance()
provenance_manager = EnhancedProvenanceManager(
    audit_logger=audit_logger,
    enable_ipld_storage=True  # Enable IPLD storage for provenance records
)

# Create integrator
integrator = AuditProvenanceIntegrator(
    audit_logger=audit_logger,
    provenance_manager=provenance_manager
)

# Set up event listener for automatic provenance record creation
integrator.setup_audit_event_listener()

# Generate audit event from provenance record
record = provenance_manager.records[record_id]
audit_event_id = integrator.audit_from_provenance_record(record)

# Generate provenance record from audit event
event = audit_logger.get_event(event_id)
record_id = integrator.provenance_from_audit_event(event)

# Link audit event to provenance record
integrator.link_audit_to_provenance(audit_event_id, record_id)

# Export provenance records to CAR file for offline storage or transfer
car_path = "/path/to/provenance.car"
root_cid = provenance_manager.export_to_car(car_path)
print(f"Exported provenance to {car_path} with root CID: {root_cid}")
```

### Integrated Compliance Reporting with Cross-Document Lineage

The enhanced IntegratedComplianceReporter generates comprehensive compliance reports that leverage our improved cross-document lineage capabilities to provide detailed insights into data flows across document boundaries:

```python
from ipfs_datasets_py.audit.integration import IntegratedComplianceReporter
from ipfs_datasets_py.audit.compliance import ComplianceStandard, ComplianceRequirement

# Create reporter with bidirectional integration
reporter = IntegratedComplianceReporter(
    standard=ComplianceStandard.GDPR,
    audit_logger=audit_logger,
    provenance_manager=provenance_manager
)

# Add compliance requirements
reporter.add_requirement(ComplianceRequirement(
    id="GDPR-Art30",
    standard=ComplianceStandard.GDPR,
    description="Records of processing activities",
    audit_categories=[AuditCategory.DATA_ACCESS, AuditCategory.DATA_MODIFICATION],
    actions=["read", "write", "update", "delete"]
))

# Generate report with enhanced cross-document lineage analysis
report = reporter.generate_report(
    start_time="2023-01-01T00:00:00Z",
    end_time="2023-12-31T23:59:59Z",
    include_cross_document_analysis=True,  # Enable cross-document analysis
    include_lineage_metrics=True           # Include metrics about lineage graph
)

# The enhanced report now includes:
# - Document boundary detection and analysis
# - Relationship analysis across document boundaries
# - Compliance-specific insights based on cross-document flows
# - Visualization data for interactive representations

# Example of accessing enhanced cross-document lineage information
cross_doc_info = report.details.get("cross_document_lineage", {})
print(f"Document count: {cross_doc_info.get('document_count', 0)}")

# Document boundaries information
if "document_boundaries" in cross_doc_info:
    boundaries = cross_doc_info["document_boundaries"]
    print(f"Boundary count: {boundaries.get('count', 0)}")
    print(f"Cross-boundary flows: {boundaries.get('cross_boundary_flow_count', 0)}")
    
# Document relationships information
if "document_relationships" in cross_doc_info:
    relationships = cross_doc_info["document_relationships"]
    print(f"Relationship count: {relationships.get('relationship_count', 0)}")
    print(f"High-risk relationships: {relationships.get('high_risk_relationships', 0)}")

# Compliance-specific insights from cross-document analysis
if "provenance_insights" in report.details:
    print("Compliance insights from cross-document analysis:")
    for insight in report.details["provenance_insights"]:
        print(f"- {insight}")

# Save report in various formats
report.save_json("gdpr_compliance.json")
report.save_html("gdpr_compliance.html")
report.save_csv("gdpr_compliance.csv")

# Helper function for easy report generation
from ipfs_datasets_py.audit.integration import generate_integrated_compliance_report

gdpr_report = generate_integrated_compliance_report(
    standard_name="GDPR",
    start_time="2023-01-01T00:00:00Z",
    end_time="2023-12-31T23:59:59Z",
    output_format="json",
    output_path="gdpr_report.json"
)
```

The enhanced compliance reports provide standard-specific insights based on cross-document lineage analysis:

#### GDPR-Specific Insights
- Identification of cross-document data flows requiring data sharing agreements (Article 26/28)
- Detection of international transfers requiring appropriate safeguards (Articles 44-50)
- Analysis of data sharing relationships across document boundaries
- Identification of high-risk data processing requiring DPIA (Article 35)

#### HIPAA-Specific Insights
- Identification of PHI data flows crossing document boundaries
- Analysis of technical safeguards for PHI boundaries
- Detection of PHI sharing relationships requiring Business Associate Agreements
- Monitoring of de-identification processes across document boundaries

#### SOC2-Specific Insights
- Identification of critical data transit points requiring enhanced monitoring
- Analysis of data transformation processes for processing integrity
- Detection of boundary controls required for logical access security
- Monitoring of data processing relationships for input validation

### Enhanced Cross-Document Search Capabilities

The enhanced ProvenanceAuditSearchIntegrator provides unified search across audit logs and provenance records, with advanced support for cross-document lineage-aware searching:

```python
from ipfs_datasets_py.audit.integration import ProvenanceAuditSearchIntegrator

# Create search integrator
search = ProvenanceAuditSearchIntegrator(
    audit_logger=audit_logger,
    provenance_manager=provenance_manager
)

# Basic search by time range and resource type
results = search.search(
    query={
        "timerange": {
            "start": "2023-01-01T00:00:00Z",
            "end": "2023-12-31T23:59:59Z"
        },
        "resource_type": "dataset",
        "resource_id": "example_dataset",
        "action": "transform"
    },
    include_audit=True,
    include_provenance=True,
    correlation_mode="auto"  # Automatically detect correlations
)

# Enhanced cross-document lineage-aware search
cross_doc_results = search.search(
    query={
        "document_id": "source_document",  # Start search from this document
        "max_depth": 3,                   # Search up to 3 hops across documents
        "link_types": ["derived_from", "exported_from", "processes"],  # Filter by link types
        "timerange": {
            "start": "2023-01-01T00:00:00Z",
            "end": "2023-12-31T23:59:59Z"
        },
        "keywords": ["sensitive", "pii", "personal"]  # Optional keyword filters
    },
    include_audit=True,
    include_provenance=True,
    include_cross_document=True,  # Enable cross-document search
    correlation_mode="auto"
)

# Compliance-focused cross-document search
compliance_results = search.search(
    query={
        "document_id": "sensitive_data_document",
        "max_depth": 2,
        "link_types": ["contains_pii", "processes_pii", "anonymizes"],  # Focus on PII-related links
        "timerange": {
            "start": "2023-01-01T00:00:00Z",
            "end": "2023-12-31T23:59:59Z"
        }
    },
    include_audit=True,
    include_provenance=True,
    include_cross_document=True
)

# Access standard search results
print(f"Found {results.get('audit_count', 0)} audit events")
print(f"Found {results.get('provenance_count', 0)} provenance records")
print(f"Established {results.get('correlation_count', 0)} correlations")

# Access enhanced cross-document search results
print(f"Found {cross_doc_results.get('provenance_count', 0)} provenance records across document boundaries")
print(f"Documents involved: {cross_doc_results.get('cross_document_analysis', {}).get('document_count', 0)}")

# Analyze cross-document search results
if "cross_document_analysis" in cross_doc_results:
    analysis = cross_doc_results["cross_document_analysis"]
    print(f"Document boundaries crossed: {len(analysis.get('documents', []))}")
    
    # Relationship types found in the search
    if "relationship_types" in analysis:
        print("Relationship types across documents:")
        for rel_type, count in analysis.get("relationship_types", {}).items():
            print(f"- {rel_type}: {count}")
    
    # Distribution of records across documents
    if "records_by_document" in analysis:
        print("Records by document:")
        for doc_id, count in analysis.get("records_by_document", {}).items():
            print(f"- {doc_id}: {count}")

# Examine records with cross-document metadata
for record in cross_doc_results.get("provenance_records", []):
    if "cross_document_info" in record:
        doc_info = record["cross_document_info"]
        print(f"Record {record['record_id']} in document {doc_info.get('document_id')}")
        print(f"  Distance from source: {doc_info.get('distance_from_source')}")
        
        # Show relationship path from source record/document
        if "relationship_path" in doc_info:
            path = doc_info["relationship_path"]
            print("  Relationship path:")
            for step in path:
                print(f"    {step['from']} --({step['type']})--> {step['to']}")
```

The enhanced cross-document search capabilities enable comprehensive tracking of data flows across document boundaries with features specifically designed for compliance and security use cases:

1. **Document boundary traversal**: Discover how data flows across document boundaries, enabling complete lineage understanding regardless of document structure
2. **Relationship type filtering**: Focus searches on specific types of relationships (e.g., PII processing, data transformations)
3. **Path analysis**: See the exact path from source to target records across document boundaries
4. **Document relationship metrics**: Get statistical information about cross-document relationships
5. **Compliance-focused filtering**: Use specialized link types for compliance-focused searches (e.g., GDPR, HIPAA, SOC2)

### Dataset Operation Integration

The AuditDatasetIntegrator simplifies audit logging for dataset operations:

```python
from ipfs_datasets_py.audit.integration import AuditDatasetIntegrator

# Create dataset integrator
dataset_integrator = AuditDatasetIntegrator(audit_logger=audit_logger)

# Record dataset operations
load_event_id = dataset_integrator.record_dataset_load(
    dataset_name="example_dataset",
    dataset_id="ds123",
    source="huggingface",
    user="user123"
)

transform_event_id = dataset_integrator.record_dataset_transform(
    input_dataset="ds123",
    output_dataset="ds123_transformed",
    transformation_type="normalize",
    parameters={"columns": ["col1", "col2"], "method": "z-score"},
    user="user123"
)

save_event_id = dataset_integrator.record_dataset_save(
    dataset_name="example_dataset_transformed",
    dataset_id="ds123_transformed",
    destination="ipfs",
    format="car",
    user="user123"
)

query_event_id = dataset_integrator.record_dataset_query(
    dataset_name="ds123_transformed",
    query="SELECT * FROM dataset WHERE value > 0.5",
    query_type="sql",
    user="user123"
)
```

### Event Listeners

The audit logger supports event listeners for real-time integration with other systems:

```python
# Add event listener for specific category
audit_logger.add_event_listener(
    listener=my_listener_function,
    category=AuditCategory.DATA_MODIFICATION
)

# Add global listener for all events
audit_logger.add_event_listener(
    listener=my_global_listener
)

# Remove an event listener
audit_logger.remove_event_listener(
    listener=my_listener_function,
    category=AuditCategory.DATA_MODIFICATION
)
```

## Convenient Usage Patterns

### Context Manager

```python
from ipfs_datasets_py.audit.integration import AuditContextManager

# Use context manager to log operation start and end
with AuditContextManager(
    category=AuditCategory.DATA_MODIFICATION,
    action="dataset_transform",
    resource_id="example_dataset",
    resource_type="dataset",
    details={"transformation": "normalization"}
):
    # Perform the operation
    # Timing and exceptions are automatically logged
    transform_dataset(example_dataset)
```

### Function Decorator

```python
from ipfs_datasets_py.audit.integration import audit_function

# Decorate function to automatically log calls
@audit_function(
    category=AuditCategory.DATA_ACCESS,
    action="dataset_load",
    resource_id_arg="dataset_id",
    resource_type="dataset"
)
def load_dataset(dataset_id, **kwargs):
    # Function logic
    return dataset
```

## Standardized Consumer Interface

For applications that need to access integrated audit and provenance information, a standardized consumer interface is provided:

```python
from ipfs_datasets_py.audit.provenance_consumer import ProvenanceConsumer

# Create consumer
consumer = ProvenanceConsumer(
    provenance_manager=provenance_manager,
    audit_logger=audit_logger,
    integrator=integrator
)

# Get integrated record
integrated_record = consumer.get_integrated_record(record_id)

# Search for records
records = consumer.search_integrated_records(
    query="transform",
    record_types=["transformation"],
    start_time=yesterday,
    end_time=now,
    limit=10
)

# Get lineage graph
lineage_graph = consumer.get_lineage_graph(
    data_id="example_dataset",
    max_depth=5,
    include_audit_events=True
)

# Verify data lineage
verification_result = consumer.verify_data_lineage("example_dataset")

# Export provenance information
export_data = consumer.export_provenance(
    data_id="example_dataset",
    format="json",
    include_audit_events=True
)
```

## Cryptographic Verification

The system supports cryptographic verification of provenance records to ensure integrity and authenticity:

```python
from ipfs_datasets_py.data_provenance_enhanced import EnhancedProvenanceManager

# Initialize provenance manager with cryptographic verification
provenance_manager = EnhancedProvenanceManager(
    enable_crypto_verification=True,
    crypto_secret_key="your-secret-key"  # Optional, generated if not provided
)

# Verify a record
is_valid = provenance_manager.verify_record(record_id)

# Verify all records
verification_results = provenance_manager.verify_all_records()

# Sign all unsigned records
sign_results = provenance_manager.sign_all_records()
```

## Configuration

The audit logging system can be configured through code:

```python
# Configure audit logger
audit_logger.configure({
    "enabled": True,
    "min_level": "INFO",
    "default_user": "system",
    "default_application": "ipfs_datasets_py",
    "included_categories": ["DATA_ACCESS", "DATA_MODIFICATION"],
    "excluded_categories": ["DEBUG"]
})
```

## Best Practices

1. **Configure appropriate handlers**: Set up handlers that match your security and compliance requirements.
2. **Use context managers and decorators**: These provide automatic timing and exception handling.
3. **Set appropriate detail level**: Include enough details for troubleshooting and audit, but avoid sensitive information.
4. **Include relevant identifiers**: Always include resource IDs and user information when available.
5. **Use integration with provenance**: Set up the integrator to automatically create provenance records from audit events.
6. **Enable cryptographic verification**: For sensitive data or regulatory requirements, enable cryptographic verification.
7. **Regularly review audit logs**: Set up a process for regular review of audit logs for security and compliance.

## Example: Comprehensive Audit Logging

```python
from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditLevel, AuditCategory
from ipfs_datasets_py.audit.handlers import FileAuditHandler, ConsoleAuditHandler
from ipfs_datasets_py.audit.integration import AuditContextManager
from ipfs_datasets_py.data_provenance_enhanced import EnhancedProvenanceManager
from ipfs_datasets_py.audit.integration import AuditProvenanceIntegrator

# Initialize components
audit_logger = AuditLogger.get_instance()
audit_logger.add_handler(FileAuditHandler(name="file", filename="audit.jsonl"))
audit_logger.add_handler(ConsoleAuditHandler(name="console", min_level=AuditLevel.INFO))

# Set up provenance manager with cryptographic verification and IPLD storage
provenance_manager = EnhancedProvenanceManager(
    audit_logger=audit_logger,
    enable_crypto_verification=True,
    enable_ipld_storage=True  # Store provenance data in IPLD
)

# Set up integrator
integrator = AuditProvenanceIntegrator(
    audit_logger=audit_logger,
    provenance_manager=provenance_manager
)
integrator.setup_audit_event_listener()

# Record data source in provenance system
source_id = "example_dataset"
record_id = provenance_manager.record_source(
    source_id=source_id,
    source_type="huggingface",
    source_uri="huggingface:dataset/example",
    description="Example dataset from HuggingFace"
)

# Use context manager for transformation
transformed_id = "transformed_dataset"
with AuditContextManager(
    category=AuditCategory.DATA_MODIFICATION,
    action="dataset_transform",
    resource_id=transformed_id,
    resource_type="dataset",
    details={
        "input_dataset": source_id,
        "transformation": "normalization",
        "parameters": {"method": "z-score"}
    },
    audit_logger=audit_logger
):
    # Perform transformation
    # Record in provenance system
    transform_record_id = provenance_manager.record_transformation(
        input_ids=[source_id],
        output_id=transformed_id,
        transformation_type="normalization",
        parameters={"method": "z-score"},
        description="Normalize data using z-score"
    )

# Verify lineage integrity
from ipfs_datasets_py.audit.provenance_consumer import ProvenanceConsumer

consumer = ProvenanceConsumer(
    provenance_manager=provenance_manager,
    audit_logger=audit_logger,
    integrator=integrator
)

verification_result = consumer.verify_data_lineage(transformed_id)
print(f"Lineage verified: {verification_result['verified']}")

# Export provenance information
export_data = consumer.export_provenance(
    data_id=transformed_id,
    format="json",
    include_audit_events=True
)

# Export provenance to CAR file for decentralized storage
car_path = "provenance_export.car"
root_cid = provenance_manager.export_to_car(car_path)
print(f"Exported provenance graph to {car_path}")
print(f"Root CID: {root_cid}")

# To later import the provenance data:
new_manager = EnhancedProvenanceManager(enable_ipld_storage=True, enable_crypto_verification=True)
success = new_manager.import_from_car(car_path)
if success:
    print(f"Successfully imported {len(new_manager.records)} provenance records")
```

## Compliance Features

The audit logging system includes features specifically designed to support compliance with regulations like GDPR, HIPAA, and SOX:

1. **Complete operation history**: All data access and modifications are logged
2. **User attribution**: Operations are linked to specific users
3. **Temporal tracking**: Precise timestamps for all operations
4. **Cryptographic integrity**: Verification of record integrity
5. **Data lineage**: Complete lineage tracking with provenance integration
6. **Export capabilities**: Data can be exported for compliance reporting
7. **Segregation of duties**: Different handlers can route events to different systems

## Security Features

The audit system supports security monitoring and intrusion detection:

1. **Real-time event listeners**: Can trigger alerts on suspicious activity
2. **Cryptographic verification**: Detect tampering with audit or provenance records
3. **Complete context**: Full details about operations for forensic analysis
4. **Integration with security systems**: Events can be routed to SIEM systems

## API Reference

For complete API reference, see the code documentation in:
- `ipfs_datasets_py.audit.audit_logger`
- `ipfs_datasets_py.audit.handlers`
- `ipfs_datasets_py.audit.integration`
- `ipfs_datasets_py.audit.provenance_consumer`