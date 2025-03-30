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