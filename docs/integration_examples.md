# Integration Examples

This document provides examples of integrating various components of the IPFS Datasets library.

## Enhanced Cross-Document Lineage Integration

The enhanced lineage tracking system provides comprehensive capabilities for tracking data provenance across document boundaries and multiple domains:

```python
from ipfs_datasets_py.cross_document_lineage import EnhancedLineageTracker
from ipfs_datasets_py.data_provenance_enhanced import EnhancedProvenanceManager
from ipfs_datasets_py.audit.integration import AuditProvenanceIntegrator

# Create an enhanced lineage tracker with audit integration
lineage_tracker = EnhancedLineageTracker(
    config={
        "enable_audit_integration": True,
        "enable_semantic_detection": True,
        "enable_temporal_consistency": True,
        "enable_ipld_storage": True
    }
)

# Create domains for organizing lineage data
data_processing_domain = lineage_tracker.create_domain(
    name="DataProcessing",
    description="Domain for data transformation operations",
    domain_type="processing"
)

storage_domain = lineage_tracker.create_domain(
    name="Storage",
    description="Domain for data storage systems",
    domain_type="storage"
)

analytics_domain = lineage_tracker.create_domain(
    name="Analytics",
    description="Domain for analytics and reporting",
    domain_type="analytics",
    attributes={"compliance_level": "high"}
)

# Create domain boundaries to manage cross-domain data flow
lineage_tracker.create_domain_boundary(
    source_domain_id=data_processing_domain,
    target_domain_id=storage_domain,
    boundary_type="data_export",
    attributes={"encryption": "AES-256"}
)

lineage_tracker.create_domain_boundary(
    source_domain_id=storage_domain,
    target_domain_id=analytics_domain,
    boundary_type="data_import",
    attributes={"access_control": "role_based"}
)

# Create nodes representing data artifacts in different domains
raw_data_node = lineage_tracker.create_node(
    node_type="dataset",
    metadata={"format": "csv", "size": "2.3GB", "record_count": 1000000},
    domain_id=data_processing_domain,
    entity_id="raw_sales_data"
)

cleaned_data_node = lineage_tracker.create_node(
    node_type="dataset",
    metadata={"format": "parquet", "size": "1.8GB", "record_count": 950000},
    domain_id=data_processing_domain,
    entity_id="cleaned_sales_data"
)

transform_node = lineage_tracker.create_node(
    node_type="transformation",
    metadata={"tool": "pandas", "execution_time": "45min"},
    domain_id=data_processing_domain,
    entity_id="clean_transform_01"
)

# Record detailed transformation information
lineage_tracker.record_transformation_details(
    transformation_id=transform_node,
    operation_type="data_cleaning",
    inputs=[
        {"field": "sales_amount", "type": "float"},
        {"field": "transaction_date", "type": "date"}
    ],
    outputs=[
        {"field": "sales_amount", "type": "float", "null_count": 0},
        {"field": "transaction_date", "type": "date", "format": "yyyy-mm-dd"}
    ],
    parameters={"drop_na": True, "convert_dates": True},
    impact_level="field"
)

# Create relationships between nodes
lineage_tracker.create_link(
    source_id=raw_data_node,
    target_id=transform_node,
    relationship_type="input_to",
    metadata={"timestamp": "2023-04-01T08:15:00"}
)

lineage_tracker.create_link(
    source_id=transform_node,
    target_id=cleaned_data_node,
    relationship_type="output_from",
    metadata={"timestamp": "2023-04-01T09:00:00"}
)

# Create cross-domain relationships
storage_node = lineage_tracker.create_node(
    node_type="storage_system",
    metadata={"type": "object_store", "provider": "internal"},
    domain_id=storage_domain,
    entity_id="data_lake_01"
)

lineage_tracker.create_link(
    source_id=cleaned_data_node,
    target_id=storage_node,
    relationship_type="stored_in",
    metadata={"timestamp": "2023-04-01T09:30:00"},
    cross_domain=True
)

# Create version information
lineage_tracker.create_version(
    node_id=cleaned_data_node,
    version_number="1.0.2",
    change_description="Fixed date format inconsistencies",
    creator_id="data_engineer_1"
)

# Query the lineage graph for analytics domain dependencies
analytics_dependencies = lineage_tracker.query_lineage({
    "domain_id": analytics_domain,
    "node_type": ["dataset", "report"],
    "relationship_type": ["derived_from", "based_on"]
})

# Find all paths between raw data and analytics results
paths = lineage_tracker.find_paths(
    start_node_id=raw_data_node,
    end_node_id=analytics_node,
    max_depth=5
)

# Detect potential semantic relationships
semantic_relationships = lineage_tracker.detect_semantic_relationships()

# Generate a visualization of the lineage graph
lineage_tracker.visualize_lineage(
    output_path="cross_domain_lineage.html",
    visualization_type="interactive",
    include_domains=True
)

# Export lineage data to IPLD for decentralized storage
root_cid = lineage_tracker.export_to_ipld(
    include_domains=True,
    include_versions=True,
    include_transformation_details=True
)
print(f"Lineage graph stored on IPLD with root CID: {root_cid}")

# Generate comprehensive provenance report
report = lineage_tracker.generate_provenance_report(
    entity_id="cleaned_sales_data",
    include_visualization=True,
    format="html"
)
```

### Benefits of Enhanced Lineage Tracking

1. **Cross-Domain Visibility**: Track data as it moves across logical domains and system boundaries.

2. **Hierarchical Organization**: Organize lineage data into domains and subdomains for better management.

3. **Detailed Transformation Tracking**: Record granular details about transformation operations.

4. **Temporal Consistency Checking**: Ensure data flows make logical sense in time.

5. **Version Tracking**: Track versions of data artifacts with full history.

6. **Semantic Relationship Detection**: Discover potential relationships beyond explicit links.

7. **Interactive Visualization**: Visualize complex data flows with domain highlighting.

8. **IPLD Integration**: Store lineage data in content-addressable format for decentralized access.

9. **Audit Trail Integration**: Link lineage information with audit events for compliance.

10. **Comprehensive Querying**: Find paths, subgraphs, and relationships with flexible criteria.

## IPLD Storage Integration with Data Provenance

The IPLD storage system can be integrated with the enhanced data provenance system to enable content-addressed storage and portability of provenance records:

```python
from ipfs_datasets_py.data_provenance_enhanced import EnhancedProvenanceManager
import os
import tempfile

# Create a temporary directory for storage
temp_dir = tempfile.mkdtemp()

# Initialize provenance manager with IPLD storage and cryptographic verification
manager = EnhancedProvenanceManager(
    storage_path=temp_dir,
    enable_ipld_storage=True,  # Enable IPLD storage
    default_agent_id="ipld-integration-example",
    tracking_level="detailed",
    enable_crypto_verification=True,  # Enable cryptographic verification
    ipfs_api="/ip4/127.0.0.1/tcp/5001"  # IPFS API endpoint
)

# Record provenance events (automatically stored in IPLD)
source_id = manager.record_source(
    output_id="dataset-001",
    source_type="file",
    format="csv",
    location="/path/to/dataset.csv",
    description="Original CSV dataset"
)

# Transformation
transform_id = manager.record_transformation(
    input_ids=["dataset-001"],
    output_id="dataset-002",
    transformation_type="clean",
    tool="pandas",
    parameters={"drop_na": True, "drop_duplicates": True},
    description="Clean dataset by removing NA values and duplicates"
)

# Verification
verify_id = manager.record_verification(
    data_id="dataset-002",
    verification_type="schema",
    schema={"id": "integer", "name": "string", "value": "float"},
    pass_count=1000,
    fail_count=0,
    description="Verify data schema"
)

# Check IPLD storage status
print(f"Records stored in IPLD: {len(manager.record_cids)}")
for record_id, cid in list(manager.record_cids.items())[:3]:
    print(f"- {record_id}: {cid}")

# Export provenance graph to CAR file
car_path = os.path.join(temp_dir, "provenance.car")
root_cid = manager.export_to_car(car_path)
print(f"Exported provenance graph to CAR file: {car_path}")
print(f"Root CID: {root_cid}")

# Create a new manager to import the CAR file
import_manager = EnhancedProvenanceManager(
    storage_path=os.path.join(temp_dir, "import"),
    enable_ipld_storage=True,
    enable_crypto_verification=True
)

# Import the provenance graph from CAR file
success = import_manager.import_from_car(car_path)
if success:
    print(f"Successfully imported provenance graph with {len(import_manager.records)} records")
    
    # Verify the integrity of the imported records
    verification_results = import_manager.verify_all_records()
    valid_count = sum(1 for v in verification_results.values() if v)
    print(f"Valid records: {valid_count}/{len(verification_results)}")
    
    # Run a query on the imported graph
    lineage = import_manager.get_lineage("dataset-002")
    print(f"Lineage of dataset-002: {len(lineage)} records")
```

### Benefits of IPLD Storage Integration

1. **Content-Addressed Storage**: All provenance records are stored with content-based identifiers (CIDs), ensuring cryptographic verification of data integrity.

2. **Decentralized Storage**: Provenance records can be stored on the IPFS network, enabling decentralized and resilient storage.

3. **Portable Provenance Graphs**: Complete provenance graphs can be exported to CAR files and imported into other systems, enabling easy sharing of provenance information.

4. **Cryptographic Verification**: Records can be cryptographically signed and verified for authenticity.

5. **Efficient Storage**: IPLD's content-addressing provides natural deduplication of identical data.

6. **Seamless Integration**: The integration is automatic - when IPLD storage is enabled, all provenance records are automatically stored in IPLD.

## Audit Logging Integration

### Integration with Data Provenance

The audit logging system can be integrated with the data provenance system to automatically create provenance records from audit events:

```python
from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditCategory, AuditLevel
from ipfs_datasets_py.audit.integration import AuditProvenanceIntegrator
from ipfs_datasets_py.data_provenance_enhanced import EnhancedProvenanceManager

# Create the audit logger
audit_logger = AuditLogger(
    log_file="audit.log",
    console_level=AuditLevel.WARNING
)

# Create the provenance manager
provenance_manager = EnhancedProvenanceManager(
    storage_path="provenance_data",
    default_agent_id="integration-example"
)

# Set up the integration
integrator = AuditProvenanceIntegrator(
    audit_logger=audit_logger,
    provenance_manager=provenance_manager
)

# Set up bidirectional integration
integrator.setup_audit_event_listener()

# Now whenever an audit event with the appropriate category is logged,
# a provenance record will be automatically created

# Example of triggering provenance creation via audit
audit_logger.log_event(
    level=AuditLevel.INFO,
    category=AuditCategory.DATA_MODIFICATION,
    operation="transform",
    subject="input_dataset",
    object="output_dataset",
    status="success",
    details={
        "transformation_type": "clean",
        "tool": "pandas",
        "parameters": {"drop_na": True}
    }
)

# The above audit event will automatically create a transformation record in the provenance system
# We can verify this by checking the provenance records
provenance_records = list(provenance_manager.records.values())
print(f"Number of provenance records: {len(provenance_records)}")

# We can also go from provenance to audit
# Get the latest provenance record
latest_record = provenance_records[-1]

# Find linked audit events
audit_events = integrator.get_audit_events_for_provenance(latest_record.id)
print(f"Number of linked audit events: {len(audit_events)}")
```

### Integration with Dataset Processing

The audit logging system can be used to track dataset processing operations:

```python
from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditCategory, AuditLevel
import pandas as pd

# Create the audit logger
audit_logger = AuditLogger(log_file="dataset_processing.log")

# Function that uses audit logging
def process_dataset(df, operations, dataset_name):
    """Process a dataset with auditing."""
    result_df = df.copy()
    
    # Log the start of processing
    audit_logger.log_event(
        level=AuditLevel.INFO,
        category=AuditCategory.DATA_ACCESS,
        operation="read",
        subject=dataset_name,
        object=None,
        status="success",
        details={"shape": str(df.shape), "columns": list(df.columns)}
    )
    
    # Apply each operation with audit logging
    for op_name, op_func, op_args in operations:
        try:
            # Apply the operation
            result_df = op_func(result_df, **op_args)
            
            # Log the operation
            audit_logger.log_event(
                level=AuditLevel.INFO,
                category=AuditCategory.DATA_MODIFICATION,
                operation=op_name,
                subject=dataset_name,
                object=f"{dataset_name}_{op_name}",
                status="success",
                details={
                    "operation": op_name,
                    "args": op_args,
                    "result_shape": str(result_df.shape)
                }
            )
        except Exception as e:
            # Log the failure
            audit_logger.log_event(
                level=AuditLevel.ERROR,
                category=AuditCategory.DATA_MODIFICATION,
                operation=op_name,
                subject=dataset_name,
                object=None,
                status="failure",
                details={
                    "operation": op_name,
                    "args": op_args,
                    "error": str(e)
                }
            )
            raise
    
    # Log the completion of processing
    audit_logger.log_event(
        level=AuditLevel.INFO,
        category=AuditCategory.PROCESS,
        operation="complete",
        subject=dataset_name,
        object=f"{dataset_name}_processed",
        status="success",
        details={"final_shape": str(result_df.shape)}
    )
    
    return result_df

# Example usage
df = pd.DataFrame({
    "id": range(1, 11),
    "value": [1, 2, None, 4, 5, 6, None, 8, 9, 10],
    "category": ["A", "B", "A", "B", "A", "B", "A", "B", "A", "B"]
})

# Define operations
operations = [
    ("drop_na", lambda df, **kwargs: df.dropna(), {}),
    ("filter", lambda df, **kwargs: df[df["value"] > kwargs["threshold"]], {"threshold": 5}),
    ("aggregate", lambda df, **kwargs: df.groupby(kwargs["by"]).sum().reset_index(), {"by": "category"})
]

# Process the dataset with audit logging
result = process_dataset(df, operations, "test_dataset")
print(result)
```

## Integration with Security and Governance

The enhanced lineage tracking system can be integrated with security and governance components for comprehensive data governance:

```python
from ipfs_datasets_py.cross_document_lineage import EnhancedLineageTracker
from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditCategory, AuditLevel
from ipfs_datasets_py.security import SecurityManager

# Initialize security manager
security_manager = SecurityManager(
    config={
        "enable_encryption": True,
        "enable_access_control": True,
        "key_storage": "secure_storage"
    }
)

# Create encryption keys for sensitive data
encryption_key_id = security_manager.create_encryption_key(
    key_name="lineage-sensitive-data",
    key_description="Key for encrypting sensitive lineage metadata"
)

# Set up access policies for lineage data
security_manager.create_resource_policy(
    resource_id="lineage-graph",
    policy={
        "admin": ["read", "write", "delete", "grant"],
        "data_steward": ["read", "write"],
        "analyst": ["read"],
        "auditor": ["read"]
    }
)

# Initialize audit logger with security integration
audit_logger = AuditLogger(
    log_file="lineage_audit.log",
    console_level=AuditLevel.WARNING,
    security_manager=security_manager
)

# Create enhanced lineage tracker with security and audit integration
lineage_tracker = EnhancedLineageTracker(
    config={
        "enable_audit_integration": True,
        "enable_ipld_storage": True,
        "security_manager": security_manager,
        "audit_logger": audit_logger,
        "encryption_key_id": encryption_key_id
    }
)

# Create domains with appropriate security controls
finance_domain = lineage_tracker.create_domain(
    name="Finance",
    domain_type="business",
    attributes={
        "sensitivity": "high",
        "compliance_frameworks": ["SOX", "GDPR"],
        "data_owners": ["finance_team"],
        "security_classification": "restricted"
    }
)

analytics_domain = lineage_tracker.create_domain(
    name="Analytics",
    domain_type="business",
    attributes={
        "sensitivity": "medium",
        "data_owners": ["analytics_team"],
        "security_classification": "internal"
    }
)

# Set up secure boundary between domains
lineage_tracker.create_domain_boundary(
    source_domain_id=finance_domain,
    target_domain_id=analytics_domain,
    boundary_type="data_transfer",
    attributes={
        "encryption": "AES-256",
        "access_control": "role_based",
        "data_masking": "enabled",
        "approval_required": True
    },
    constraints=[
        {"type": "field_level", "fields": ["ssn", "account_number"], "action": "mask"},
        {"type": "time_constraint", "hours": "8-17", "days": "mon-fri"},
        {"type": "approval", "approvers": ["data_governance_team"]}
    ]
)

# Create sensitive data node with security controls
sensitive_data = lineage_tracker.create_node(
    node_type="dataset",
    metadata={
        "format": "parquet",
        "record_count": 50000,
        "contains_pii": True,
        "security_controls": {
            "encryption": "column-level",
            "access_restriction": "need-to-know",
            "retention_policy": "3 years"
        }
    },
    domain_id=finance_domain,
    entity_id="financial_transactions"
)

# Record access to sensitive data with audit trail
with audit_logger.audit_context(
    category=AuditCategory.DATA_ACCESS,
    operation="read",
    subject="financial_transactions",
    status="success"
):
    # Create a transformation with security context
    transform_node = lineage_tracker.create_node(
        node_type="transformation",
        metadata={
            "tool": "secure_etl",
            "user_id": "data_engineer_1",
            "security_context": {
                "authentication": "mfa",
                "authorization": "role_based",
                "security_clearance": "confidential"
            }
        },
        domain_id=finance_domain,
        entity_id="anonymize_transform"
    )
    
    # Record detailed transformation with security controls
    lineage_tracker.record_transformation_details(
        transformation_id=transform_node,
        operation_type="anonymization",
        inputs=[
            {"field": "customer_id", "type": "string", "sensitivity": "high"},
            {"field": "transaction_amount", "type": "decimal", "sensitivity": "medium"}
        ],
        outputs=[
            {"field": "customer_hash", "type": "string", "sensitivity": "low"},
            {"field": "transaction_amount", "type": "decimal", "sensitivity": "medium"}
        ],
        parameters={
            "anonymization_method": "sha256",
            "salt": "secure-random-salt",
            "k_anonymity": 5
        },
        impact_level="field"
    )

# Create cross-domain link with security controls for data crossing boundary
anonymized_data = lineage_tracker.create_node(
    node_type="dataset",
    metadata={
        "format": "parquet",
        "record_count": 50000,
        "contains_pii": False,
        "security_controls": {
            "encryption": "transport-only",
            "access_restriction": "department-level",
            "retention_policy": "1 year"
        }
    },
    domain_id=analytics_domain,
    entity_id="anonymized_transactions"
)

# Create link that crosses domain boundary with security context
lineage_tracker.create_link(
    source_id=transform_node,
    target_id=anonymized_data,
    relationship_type="output_from",
    metadata={
        "timestamp": datetime.datetime.now().isoformat(),
        "security_context": {
            "boundary_crossing_approved_by": "data_governance_team",
            "security_validation": "passed",
            "compliance_check": "passed"
        }
    },
    cross_domain=True
)

# Generate comprehensive security-enhanced provenance report
report = lineage_tracker.generate_provenance_report(
    entity_id="anonymized_transactions",
    include_visualization=True,
    format="html",
    include_security_context=True,
    include_audit_trail=True
)

# Export secured lineage data to IPLD with encrypted sensitive information
root_cid = lineage_tracker.export_to_ipld(
    include_domains=True,
    include_versions=True,
    include_transformation_details=True,
    encrypt_sensitive_data=True
)
print(f"Secure lineage graph stored on IPLD with root CID: {root_cid}")
```

## Complete Integration: IPLD Storage + Provenance + Audit Logging

The following example demonstrates the integration of IPLD storage, data provenance, and audit logging:

```python
from ipfs_datasets_py.data_provenance_enhanced import EnhancedProvenanceManager
from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditCategory, AuditLevel
from ipfs_datasets_py.audit.integration import AuditProvenanceIntegrator
import os
import tempfile
import time

# Create temporary directories
temp_dir = tempfile.mkdtemp()
audit_log_path = os.path.join(temp_dir, "audit.log")

# Create audit logger
audit_logger = AuditLogger(
    log_file=audit_log_path,
    console_level=AuditLevel.INFO
)

# Create provenance manager with IPLD storage and audit integration
provenance_manager = EnhancedProvenanceManager(
    storage_path=temp_dir,
    enable_ipld_storage=True,
    default_agent_id="integrated-example",
    tracking_level="detailed",
    audit_logger=audit_logger,
    enable_crypto_verification=True
)

# Set up bidirectional integration
integrator = AuditProvenanceIntegrator(
    audit_logger=audit_logger,
    provenance_manager=provenance_manager
)
integrator.setup_audit_event_listener()

# Log an audit event that will create a provenance record
audit_logger.log_event(
    level=AuditLevel.INFO,
    category=AuditCategory.DATA_MODIFICATION,
    operation="transform",
    subject="dataset_a",
    object="dataset_b",
    status="success",
    details={
        "transformation_type": "normalize",
        "tool": "sklearn",
        "parameters": {"method": "minmax"}
    }
)

# The above audit event will automatically:
# 1. Create a provenance record
# 2. Store the record in IPLD
# 3. Add a cryptographic signature to the record

# Wait for the listener to process the event
time.sleep(0.1)

# Check the provenance records
records = list(provenance_manager.records.values())
print(f"Number of provenance records: {len(records)}")

# Check IPLD storage
print(f"Records stored in IPLD: {len(provenance_manager.record_cids)}")

# Export to CAR file
car_path = os.path.join(temp_dir, "integrated_provenance.car")
root_cid = provenance_manager.export_to_car(car_path)
print(f"Exported provenance graph to {car_path}")
print(f"Root CID: {root_cid}")

# Verify the records
verification_results = provenance_manager.verify_all_records()
valid_count = sum(1 for v in verification_results.values() if v)
print(f"Valid records: {valid_count}/{len(verification_results)}")
```