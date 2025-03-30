# Integration Examples

This document provides examples of integrating various components of the IPFS Datasets library.

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