# Data Provenance in IPFS Datasets

## Overview
This document describes the data provenance tracking functionality in the IPFS Datasets library. The provenance system records the origin, transformations, and usage of data entities, providing a comprehensive history of data lineage.

## Basic Usage

```python
from ipfs_datasets_py.data_provenance import ProvenanceManager

# Initialize a provenance manager
manager = ProvenanceManager()

# Record a data source
source_id = manager.record_source(
    output_id="dataset_1",
    source_type="file",
    format="csv",
    location="/path/to/data.csv",
    description="Original dataset from source"
)

# Record a transformation
transform_id = manager.record_transformation(
    input_ids=["dataset_1"],
    output_id="dataset_2",
    transformation_type="clean",
    tool="pandas",
    parameters={"drop_na": True},
    description="Clean dataset by removing NA values"
)

# Record a merge operation
merge_id = manager.record_merge(
    input_ids=["dataset_2", "other_dataset"],
    output_id="merged_dataset",
    merge_type="inner_join",
    parameters={"on": "id"},
    description="Merge datasets by ID"
)

# Get lineage of a data entity
lineage = manager.get_lineage("merged_dataset")
print(lineage)

# Visualize the provenance graph
manager.visualize(data_ids=["merged_dataset"], file_path="provenance.png")
```

## Enhanced Provenance Manager

For advanced features, use the EnhancedProvenanceManager class with its expanded capabilities:

```python
from ipfs_datasets_py.data_provenance_enhanced import EnhancedProvenanceManager

# Initialize with advanced features
manager = EnhancedProvenanceManager(
    storage_path="/path/to/storage",
    enable_ipld_storage=True,  # Store provenance data using IPLD with advanced features
    default_agent_id="process-123",
    tracking_level="detailed",  # Options: minimal, standard, detailed, comprehensive
    visualization_engine="plotly",  # Options: matplotlib, plotly, dash
    enable_crypto_verification=True,  # Enable cryptographic verification
    ipfs_api="/ip4/127.0.0.1/tcp/5001"  # IPFS API endpoint
)

# Additional record types
verify_id = manager.record_verification(
    data_id="dataset_2",
    verification_type="schema",
    schema={"id": "integer", "name": "string"},
    pass_count=1000,
    fail_count=0,
    description="Verify dataset schema"
)

# Semantic search
results = manager.semantic_search("cleaning data", limit=5)
for result in results:
    print(f"{result['record_id']}: {result['description']} (Score: {result['score']})")

# Time-based query
yesterday = time.time() - 86400
records = manager.temporal_query(
    start_time=yesterday,
    time_bucket="hourly",
    record_types=["transformation", "merge"]
)

# Advanced lineage tracking with detailed traversal control
lineage = manager.get_lineage_graph("final_dataset", depth=3)
print(f"Basic lineage has {len(lineage.nodes)} nodes")

# Advanced traversal with fine-grained control
downstream = manager.traverse_provenance(
    record_id="raw_data",
    max_depth=3,
    direction="out",  # Only follow downstream (outputs)
    relation_filter=["transformation", "verification"]  # Only specific relation types
)
print(f"Downstream traversal has {len(downstream.nodes)} nodes")

# Incremental loading for large provenance graphs
recent_transformations = manager.incremental_load_provenance({
    "time_start": yesterday,
    "record_types": ["transformation"]
})

# Enhanced visualization
manager.visualize_provenance_enhanced(
    data_ids=["merged_dataset"],
    max_depth=3,
    include_parameters=True,
    show_timestamps=True,
    layout="hierarchical",
    highlight_critical_path=True,
    file_path="provenance_detailed.html",
    format="html"
)
```

## Enhanced IPLD Storage Integration

The enhanced provenance system now features advanced IPLD-based storage with detailed lineage tracking capabilities:

```python
# Initialize with enhanced IPLD storage enabled
manager = EnhancedProvenanceManager(
    enable_ipld_storage=True,
    ipfs_api="/ip4/127.0.0.1/tcp/5001",
    enable_crypto_verification=True  # Enable cryptographic verification
)

# Record provenance events (automatically stored in IPLD)
source_id = manager.record_source(
    output_id="dataset_1",
    source_type="file",
    format="csv",
    description="Original dataset"
)

transform_id = manager.record_transformation(
    input_ids=[source_id],
    output_id="processed_dataset",
    transformation_type="normalize",
    parameters={"method": "min-max"},
    description="Normalize dataset values to [0,1] range"
)

# Advanced graph traversal with direction control
upstream_graph = manager.traverse_provenance(
    record_id="processed_dataset",
    max_depth=3,
    direction="in",  # Only traverse upstream (inputs)
    relation_filter=["transformation"]  # Only follow transformation relationships
)
print(f"Upstream graph has {len(upstream_graph.nodes)} nodes and {len(upstream_graph.edges)} edges")

# Incremental loading based on criteria
recent_records = manager.incremental_load_provenance({
    "time_start": time.time() - 3600,  # Last hour
    "record_types": ["transformation"],
    "data_ids": ["dataset_1", "processed_dataset"]
})

# Export the entire provenance graph to a CAR file with selective options
root_cid = manager.export_to_car("provenance.car")
print(f"Exported provenance graph with root CID: {root_cid}")

# Create a new manager to import from CAR file
new_manager = EnhancedProvenanceManager(enable_ipld_storage=True)
success = new_manager.import_from_car("provenance.car")

if success:
    print(f"Imported {len(new_manager.records)} records")
    
    # Verify the cryptographic integrity of imported records
    if new_manager.enable_crypto_verification:
        verification_results = new_manager.verify_all_records()
        valid_count = sum(1 for v in verification_results.values() if v)
        print(f"Valid records: {valid_count}/{len(verification_results)}")
```

Benefits of Enhanced IPLD Storage Integration:
- Content-addressed provenance records with efficient DAG-PB encoding
- Advanced graph traversal with direction and relation filtering
- Incremental loading of partial provenance graphs based on criteria
- Graph partitioning for efficient storage of large provenance datasets
- Batch operations for high-performance record processing
- Cryptographic verification of linked data integrity
- Selective CAR file export/import with filtering options
- Seamless integration with IPFS ecosystem for distributed provenance

## Record Types

The provenance system supports several record types:

1. **Source Record**: Records the origin of a data entity
2. **Transformation Record**: Records a transformation applied to data
3. **Merge Record**: Records a merge operation between multiple data entities
4. **Query Record**: Records a query executed on data
5. **Result Record**: Records the result of a query or operation
6. **Verification Record** (Enhanced): Records data validation/verification
7. **Annotation Record** (Enhanced): Records manual notes about data
8. **Model Training Record** (Enhanced): Records model training events
9. **Model Inference Record** (Enhanced): Records model inference events

## Integration with Audit Logging

The provenance system can be integrated with the audit logging system:

```python
from ipfs_datasets_py.audit.audit_logger import AuditLogger
from ipfs_datasets_py.audit.integration import AuditProvenanceIntegrator

# Create audit logger
audit_logger = AuditLogger(log_file="audit.log")

# Create provenance manager with audit integration
manager = EnhancedProvenanceManager(audit_logger=audit_logger)

# Set up bidirectional integration
integrator = AuditProvenanceIntegrator(
    audit_logger=audit_logger,
    provenance_manager=manager
)
integrator.setup_audit_event_listener()

# Now audit events will automatically create provenance records when appropriate
```

## Cryptographic Verification

The enhanced provenance system supports cryptographic verification of records:

```python
# Initialize with cryptographic verification enabled
manager = EnhancedProvenanceManager(
    enable_crypto_verification=True,
    crypto_secret_key="my-secret-key"  # Optional, generated if not provided
)

# Records are automatically signed when created
record_id = manager.record_source(...)

# Verify a specific record
is_valid = manager.verify_record(record_id)
print(f"Record {record_id} valid: {is_valid}")

# Verify all records
verification_results = manager.verify_all_records()
for record_id, is_valid in verification_results.items():
    print(f"Record {record_id} valid: {is_valid}")
```

## Visualization Options

The provenance system offers various visualization options:

1. **Basic Visualization**: Simple directed graph using matplotlib
2. **Enhanced Visualization**: 
   - Multiple layout options: hierarchical, spring, circular, spectral
   - Different output formats: PNG, SVG, HTML, JSON
   - Interactive visualizations with Plotly and Dash
   - Highlighting of critical paths
   - Inclusion of metrics and parameters

Example:
```python
# Interactive HTML visualization
manager.visualize_provenance_enhanced(
    data_ids=["final_dataset"],
    layout="hierarchical",
    format="html",
    file_path="provenance_interactive.html",
    width=1200,
    height=800,
    include_metrics=True
)
```

## Provenance Analysis

The enhanced provenance system offers analytical capabilities:

```python
# Calculate complexity metrics for a data entity
metrics = manager.calculate_data_metrics("final_dataset")
print(f"Complexity: {metrics['complexity']['node_count']} nodes, {metrics['complexity']['max_depth']} depth")
print(f"Impact: {metrics['impact']}")
print(f"Verification: {metrics['verification']['passed']} passed, {metrics['verification']['failed']} failed")
```

Available metrics include:
- Structural complexity (node count, edge count, max depth, branch factor)
- Data impact (influence on downstream entities)
- Verification statistics (validation pass/fail counts)
- Temporal metrics (age, update frequency)
- Record type distribution