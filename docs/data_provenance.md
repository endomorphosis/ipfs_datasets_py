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

# Enhanced temporal query with precise date filtering
import datetime
records = manager.temporal_query(
    start_time=datetime.datetime(2023, 1, 1),  # Supports datetime objects
    end_time=datetime.datetime(2023, 6, 30),   # End date (inclusive)
    time_bucket="daily",                       # Daily aggregation
    record_types=["source", "transformation", "verification"],
    data_ids=["dataset_1", "processed_dataset"],  # Filter by data IDs
    include_metadata=True,                     # Include full metadata
    sort_by="timestamp",                       # Sort results by timestamp
    sort_order="descending"                    # Most recent first
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
export_stats = manager.export_to_car(
    output_path="provenance.car",
    include_records=True,
    include_graph=True,
    selective_record_ids=["dataset_1", "processed_dataset"]  # Only export specific records
)
print(f"Exported provenance graph with root CID: {export_stats['root_cid']}")
print(f"Exported {export_stats['record_count']} records and {export_stats['edge_count']} relationships")

# Create a new manager to import from CAR file
new_manager = EnhancedProvenanceManager(enable_ipld_storage=True)
import_stats = new_manager.import_from_car(
    car_path="provenance.car",
    verify_integrity=True,
    skip_existing=True
)

if import_stats['success']:
    print(f"Imported {import_stats['record_count']} records and {import_stats['edge_count']} edges")
    print(f"Root CID: {import_stats['root_cid']}")
    
    # Verify the cryptographic integrity of imported records
    if new_manager.enable_crypto_verification:
        verification_results = new_manager.verify_all_records()
        valid_count = sum(1 for v in verification_results.values() if v)
        print(f"Valid records: {valid_count}/{len(verification_results)}")
```

### Optimized Batch Operations

The enhanced storage system supports efficient batch operations for high-throughput scenarios:

```python
# Initialize storage
storage = manager.storage

# Batch store multiple records
record_batch = [
    {"id": "record1", "type": "source", "data": {...}},
    {"id": "record2", "type": "transformation", "data": {...}},
    {"id": "record3", "type": "verification", "data": {...}}
]
cids = storage.store_batch(record_batch)

# Batch retrieve records
records = storage.get_batch(cids)

# Batch update metadata
updates = [
    {"id": "record1", "metadata": {"quality": "high"}},
    {"id": "record2", "metadata": {"runtime": 0.5}}
]
storage.update_metadata_batch(updates)
```

### Semantic Indexing for Record Types

The system now properly handles semantic indexing for all record types, including verification and annotation records:

```python
# Record verification with proper semantic indexing
verify_id = manager.record_verification(
    data_id="dataset_2",
    verification_type="schema",
    schema={"id": "integer", "name": "string"},
    pass_count=1000,
    fail_count=0,
    description="Verify dataset schema conforms to specification"
)

# Record annotation with proper semantic indexing
annotation_id = manager.record_annotation(
    data_id="dataset_1",
    annotation_type="quality",
    content="Dataset contains high-quality labeled examples",
    metadata={"confidence": 0.95, "reviewer": "data_scientist_1"}
)

# Semantic search across all record types
results = manager.semantic_search("schema verification", include_record_types=["verification", "annotation", "transformation"])
for result in results:
    print(f"{result['record_id']} ({result['record_type']}): {result['description']} (Score: {result['score']})")
```

Benefits of Enhanced IPLD Storage Integration:
- Content-addressed provenance records with efficient DAG-PB encoding
- Advanced graph traversal with direction and relation filtering
- Incremental loading of partial provenance graphs based on criteria
- Graph partitioning for efficient storage of large provenance datasets
- Enhanced cross-document lineage tracking with document boundary detection
- Document relationship analysis with comprehensive boundary metrics
- Cross-document data flow visualization with interactive representations
- Optimized batch operations for high-performance record processing
- Semantic indexing for all record types including verification and annotation records
- Cryptographic verification of linked data integrity
- Selective CAR file export/import with advanced filtering options
- Advanced temporal queries with precise date-based filtering
- Proper depth assignment for graph visualization with multipartite layouts
- Improved metrics calculations with source record inclusion
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

## Cross-Document Lineage Tracking

The enhanced provenance system provides comprehensive cross-document lineage tracking, enabling you to trace data flows across document boundaries, domains, and multiple systems. With the latest implementation, you get sophisticated semantic relationship detection, domain-aware boundary analysis, detailed transformation tracking, temporal consistency verification, version-aware lineage, and interactive visualizations.

### Overview

Cross-document lineage tracking offers the following key capabilities:

- **Hierarchical Domain Organization**: Group lineage data into logical domains with multi-level hierarchies
- **Boundary Management**: Define controlled interfaces between domains with constraints and security properties
- **Detailed Transformation Decomposition**: Track field-level impacts and transformation parameters
- **Version-Aware Lineage**: Track changes to data artifacts with full history and parent-child relationships
- **Temporal Consistency Checking**: Ensure data flows adhere to logical time sequence
- **Semantic Relationship Detection**: Discover implicit relationships using content analysis
- **Bidirectional Audit Integration**: Link lineage information with audit events for compliance
- **IPLD Storage Integration**: Store lineage data in content-addressable format for decentralized access
- **Comprehensive Query Capabilities**: Find paths, extract subgraphs, and analyze lineage patterns
- **Flexible Visualization**: Generate both interactive and static visualizations of lineage flows
- **Metadata Inheritance**: Propagate metadata through lineage hierarchies based on rules
- **Fine-Grained Permission Controls**: Manage access to lineage data with security

### Enhanced Lineage Tracking with Domains and Boundaries

The newly enhanced implementation brings powerful features for granular lineage tracking with complete domain awareness and boundary crossing capabilities:

```python
from ipfs_datasets_py.cross_document_lineage import EnhancedLineageTracker, LineageDomain, LineageLink, LineageNode

# Initialize the enhanced lineage tracker
tracker = EnhancedLineageTracker(
    config={
        "enable_audit_integration": True,
        "enable_temporal_consistency": True,
        "enable_semantic_detection": True,
        "enable_ipld_storage": True
    }
)

# Create domains to organize lineage data
source_domain_id = tracker.create_domain(
    name="SourceSystem",
    description="Original data source system",
    domain_type="system",
    attributes={"organization": "Data Provider Inc."}
)

processing_domain_id = tracker.create_domain(
    name="ProcessingSystem",
    description="Data transformation system",
    domain_type="system",
    attributes={"organization": "Analytics Team"}
)

analytics_domain_id = tracker.create_domain(
    name="AnalyticsSystem",
    description="Data analysis system",
    domain_type="system",
    attributes={"organization": "Analytics Team"}
)

# Create boundaries between domains
source_to_processing = tracker.create_domain_boundary(
    source_domain_id=source_domain_id,
    target_domain_id=processing_domain_id,
    boundary_type="api_call",
    attributes={"protocol": "REST", "auth_required": True}
)

processing_to_analytics = tracker.create_domain_boundary(
    source_domain_id=processing_domain_id,
    target_domain_id=analytics_domain_id,
    boundary_type="data_transfer",
    attributes={"format": "parquet", "encryption": True}
)

# Create lineage nodes in specific domains
source_node = tracker.create_node(
    node_type="dataset",
    metadata={
        "name": "Original Data",
        "format": "csv",
        "size_bytes": 1024000
    },
    domain_id=source_domain_id,
    entity_id="original_data_001"
)

transform_node = tracker.create_node(
    node_type="transformation",
    metadata={
        "name": "Data Cleaning Process",
        "tool": "pandas",
        "version": "1.5.2"
    },
    domain_id=processing_domain_id,
    entity_id="transform_001"
)

processed_node = tracker.create_node(
    node_type="dataset",
    metadata={
        "name": "Processed Data",
        "format": "parquet",
        "size_bytes": 850000
    },
    domain_id=processing_domain_id,
    entity_id="processed_data_001"
)

analytics_node = tracker.create_node(
    node_type="analysis",
    metadata={
        "name": "Sales Analysis",
        "type": "trend_analysis",
        "author": "data_scientist_1"
    },
    domain_id=analytics_domain_id,
    entity_id="analysis_001"
)

# Create relationships between nodes
tracker.create_link(
    source_id=source_node,
    target_id=transform_node,
    relationship_type="input_to",
    metadata={"timestamp": time.time()},
    confidence=1.0
)

# Record detailed transformation information
tracker.record_transformation_details(
    transformation_id=transform_node,
    operation_type="clean",
    inputs=[
        {"field": "customer_id", "type": "string"},
        {"field": "purchase_date", "type": "date"}
    ],
    outputs=[
        {"field": "customer_id", "type": "string"},
        {"field": "purchase_date", "type": "datetime"}
    ],
    parameters={"drop_na": True, "convert_dates": True},
    impact_level="field"
)

# Create cross-domain link
tracker.create_link(
    source_id=transform_node,
    target_id=processed_node,
    relationship_type="output_from",
    metadata={"quality_score": 0.95},
    confidence=1.0
)

# Create another cross-domain link
tracker.create_link(
    source_id=processed_node,
    target_id=analytics_node,
    relationship_type="analyzed_by",
    metadata={"priority": "high"},
    confidence=0.9,
    cross_domain=True  # Explicitly mark as cross-domain
)

# Create versions for tracking changes
version_id = tracker.create_version(
    node_id=processed_node,
    version_number="1.0",
    change_description="Initial processed version",
    creator_id="data_engineer_1"
)
```

### Advanced Lineage Querying and Analysis

The enhanced implementation offers sophisticated querying and analysis capabilities:

```python
# Executing a flexible query against the lineage graph
query_results = tracker.query_lineage({
    "node_type": ["dataset", "transformation"],
    "domain_id": processing_domain_id,
    "start_time": time.time() - 86400,  # Last 24 hours
    "end_time": time.time(),
    "metadata_filters": {"format": "parquet"},
    "include_domains": True,
    "include_versions": True,
    "include_transformation_details": True
})

print(f"Query returned {len(query_results.nodes)} nodes and {len(query_results.links)} links")

# Finding all paths between two nodes
paths = tracker.find_paths(
    start_node_id=source_node,
    end_node_id=analytics_node,
    max_depth=5,
    relationship_filter=["input_to", "output_from", "analyzed_by"]
)

print(f"Found {len(paths)} paths from source to analytics")
for path in paths:
    print(f"Path with {len(path)} nodes: {' -> '.join(path)}")

# Detect semantic relationships between nodes based on content similarity
semantic_relationships = tracker.detect_semantic_relationships(
    confidence_threshold=0.7,
    max_candidates=100
)

print(f"Detected {len(semantic_relationships)} semantic relationships")
for rel in semantic_relationships:
    print(f"Relationship: {rel['source_id']} -> {rel['target_id']}")
    print(f"Type: {rel['relationship_type']}, Confidence: {rel['confidence']}")
    print(f"Common features: {rel['common_features']}")

# Extract a subgraph for visualization and analysis
subgraph = tracker.extract_subgraph(
    root_id=processed_node,
    max_depth=3,
    direction="both",
    include_domains=True,
    include_versions=True,
    include_transformation_details=True,
    relationship_types=["input_to", "output_from", "analyzed_by"]
)

# Check temporal consistency
inconsistencies = tracker.validate_temporal_consistency()
if inconsistencies:
    print(f"Found {len(inconsistencies)} temporal inconsistencies")
    for issue in inconsistencies:
        print(f"Inconsistency between {issue['source_id']} and {issue['target_id']}")
        print(f"Time difference: {issue['time_difference']} seconds")

# Apply metadata inheritance
propagated_count = tracker.apply_metadata_inheritance()
print(f"Propagated {propagated_count} metadata values")

# Generate a comprehensive provenance report
report = tracker.generate_provenance_report(
    entity_id="processed_data_001",
    include_visualization=True,
    format="html"
)

print(f"Report generated with {report['statistics']['node_count']} nodes")
print(f"Report subject: {report['report_subject']}")
print(f"Node types: {report['statistics']['node_types']}")
```

### IPLD Integration for Content-Addressable Storage

The EnhancedLineageTracker now includes comprehensive IPLD integration for decentralized, content-addressable storage:

```python
# Export the entire lineage graph to IPLD format
root_cid = tracker.export_to_ipld(
    include_domains=True,
    include_versions=True,
    include_transformation_details=True
)

print(f"Exported lineage graph to IPLD with root CID: {root_cid}")

# Import a lineage graph from IPLD storage
from ipfs_datasets_py.ipld.storage import IPLDStorage
imported_tracker = EnhancedLineageTracker.from_ipld(
    root_cid=root_cid,
    ipld_storage=IPLDStorage(),
    config={"enable_ipld_storage": True}
)

# Extract a specific entity's lineage with complete provenance
entity_lineage = tracker.get_entity_lineage(
    entity_id="processed_data_001",
    include_semantic=True
)

print(f"Entity lineage contains {len(entity_lineage.nodes)} nodes and {len(entity_lineage.links)} links")
```

### Interactive Visualization

The enhanced lineage tracking offers powerful visualization capabilities:

```python
# Create interactive visualization of the lineage graph
visualization = tracker.visualize_lineage(
    subgraph=subgraph,
    output_path="lineage_visualization.html",
    visualization_type="interactive",
    include_domains=True
)

# Create static visualization for reports
static_viz = tracker.visualize_lineage(
    subgraph=entity_lineage,
    output_path="entity_lineage.png",
    visualization_type="static"
)
```

### Merging Lineage Graphs

The enhanced tracking system supports merging multiple lineage trackers:

```python
# Create a new tracker for a different system
other_tracker = EnhancedLineageTracker(
    config={"enable_ipld_storage": True}
)

# Add some nodes and relationships to the other tracker
# ...

# Merge the other tracker into the main tracker
merge_stats = tracker.merge_lineage(
    other_tracker=other_tracker,
    conflict_resolution="newer",
    allow_domain_merging=True
)

print(f"Merged trackers: {merge_stats}")
print(f"Added {merge_stats['nodes_added']} nodes and {merge_stats['links_added']} links")
print(f"Added {merge_stats['domains_added']} domains and {merge_stats['boundaries_added']} boundaries")
```

### Enhanced Cross-Document Lineage Features

The enhanced cross-document lineage tracking system provides several advanced features:

1. **Domain-Based Organization**: Logical grouping of lineage data with domain hierarchies
2. **Boundary Management**: Explicit handling of boundaries between domains with detailed attributes
3. **Semantic Relationship Detection**: Sophisticated detection of relationships using NLP techniques
4. **Detailed Transformation Tracking**: Fine-grained tracking of transformation operations with field-level detail
5. **Temporal Consistency Checking**: Validation of logical data flow timing across the entire graph
6. **Version Tracking**: Complete tracking of node versions with change history
7. **Metadata Inheritance**: Automatic propagation of metadata across related nodes
8. **Flexible Querying**: Powerful query capabilities with filtering by various attributes
9. **IPLD Storage Integration**: Decentralized, content-addressable storage of lineage graphs
10. **Interactive Visualization**: Comprehensive visualization options with domain awareness
11. **Path Analysis**: Advanced path finding between nodes with relationship filtering
12. **Entity-Centric Lineage**: Complete lineage extraction for specific entities
13. **Comprehensive Reporting**: Detailed provenance reports with statistics and visualizations
14. **Graph Merging**: Combining lineage graphs from different sources with conflict resolution
15. **Audit Trail Integration**: Bidirectional linking with the audit logging system

### Boundary Types and Domain Classification

The enhanced system supports various domain and boundary types for comprehensive organization:

- **System**: Logical system boundaries (e.g., "SourceSystem", "AnalyticsSystem")
- **Dataset**: Domains representing distinct datasets or data collections
- **Application**: Software application domains
- **Organization**: Organizational boundaries
- **Workflow**: Process or workflow domains
- **Security**: Security context domains with access control implications

Boundary types include:
- **api_call**: API calls between systems
- **data_transfer**: Data movement between systems
- **etl_process**: Extract-Transform-Load processes
- **export**: Data export operations
- **security**: Security-related boundaries
- **pii_boundary**: Personal Identifiable Information boundaries
- **phi_boundary**: Protected Health Information boundaries
- **international**: International data transfer boundaries

## Integration with Audit Logging

The provenance system integrates tightly with the audit logging system for comprehensive tracking, search, and compliance reporting:

```python
from ipfs_datasets_py.audit.audit_logger import AuditLogger, AuditEvent, AuditCategory
from ipfs_datasets_py.audit.integration import AuditProvenanceIntegrator
from ipfs_datasets_py.audit.integration import IntegratedComplianceReporter
from ipfs_datasets_py.audit.integration import ProvenanceAuditSearchIntegrator

# Initialize components
audit_logger = AuditLogger.get_instance()
manager = EnhancedProvenanceManager(enable_ipld_storage=True)

# Set up bidirectional integration
integrator = AuditProvenanceIntegrator(
    audit_logger=audit_logger,
    provenance_manager=manager
)

# Configure automatic conversion of audit events to provenance records
integrator.setup_audit_event_listener()

# Create provenance record from audit event
audit_event = AuditEvent(
    event_id="event-123",
    level=AuditLevel.INFO,
    category=AuditCategory.DATA_ACCESS,
    action="dataset_load",
    resource_id="example_dataset",
    timestamp=datetime.datetime.now().isoformat()
)
record_id = integrator.provenance_from_audit_event(audit_event)

# Create audit event from provenance record
source_record = manager.create_source_record(
    source_id="source_dataset",
    source_type="file",
    source_uri="ipfs://bafy..."
)
event_id = integrator.audit_from_provenance_record(source_record)

# Explicitly link existing records
integrator.link_audit_to_provenance(
    audit_event_id="event-456",
    provenance_record_id="record-789"
)

# Dataset-specific audit logging integration
from ipfs_datasets_py.audit.integration import AuditDatasetIntegrator

dataset_integrator = AuditDatasetIntegrator(audit_logger=audit_logger)
load_event_id = dataset_integrator.record_dataset_load(
    dataset_name="example_dataset",
    dataset_id="ds123",
    source="ipfs",
    user="user123"
)

# Integrated search across audit logs and provenance records
search = ProvenanceAuditSearchIntegrator(
    audit_logger=audit_logger,
    provenance_manager=manager
)

# Basic search by time range and resource
results = search.search(
    query={
        "timerange": {
            "start": (datetime.datetime.now() - datetime.timedelta(days=7)).isoformat(),
            "end": datetime.datetime.now().isoformat()
        },
        "resource_id": "example_dataset"
    },
    include_audit=True,
    include_provenance=True,
    correlation_mode="auto"  # Automatically correlate related records
)

# Enhanced cross-document lineage-aware search
cross_doc_results = search.search(
    query={
        "document_id": "document_1",  # Start search from this document
        "max_depth": 3,               # Search up to 3 hops across documents
        "link_types": ["derived_from", "exported_from", "processes"],  # Filter by link types
        "timerange": {
            "start": (datetime.datetime.now() - datetime.timedelta(days=30)).isoformat(),
            "end": datetime.datetime.now().isoformat()
        }
    },
    include_audit=True,
    include_provenance=True,
    include_cross_document=True,  # Enable cross-document search
    correlation_mode="auto"
)

# Analyze cross-document search results
if "cross_document_analysis" in cross_doc_results:
    analysis = cross_doc_results["cross_document_analysis"]
    print(f"Documents involved: {analysis.get('document_count', 0)}")
    
    # Relationship types found in the search
    if "relationship_types" in analysis:
        print("Relationship types across documents:")
        for rel_type, count in analysis.get("relationship_types", {}).items():
            print(f"- {rel_type}: {count}")

# Compliance-focused cross-document search (e.g., for GDPR)
compliance_results = search.search(
    query={
        "document_id": "sensitive_document",
        "max_depth": 2,
        "link_types": ["contains_pii", "processes_pii", "anonymizes"],  # Focus on PII-related links
    },
    include_audit=True,
    include_provenance=True,
    include_cross_document=True
)

# Integrated compliance reporting
reporter = IntegratedComplianceReporter(
    standard=ComplianceStandard.GDPR,
    audit_logger=audit_logger,
    provenance_manager=manager
)

# Generate compliance report with cross-document lineage analysis
report = reporter.generate_report(
    include_cross_document_analysis=True,
    include_lineage_metrics=True
)

# Export the compliance report
report.save_html("gdpr_compliance_report.html")
```

### Enhanced Cross-Document Lineage Analysis

The integration enables powerful cross-document lineage analysis:

```python
# Initialize the storage with IPLD support
manager = EnhancedProvenanceManager(enable_ipld_storage=True)

# ... record various provenance events ...

# Method 1: Using the DetailedLineageIntegrator for comprehensive analysis
lineage_report = manager.create_cross_document_lineage(
    output_path="cross_document_report.html",
    include_visualization=True
)

# Access the report with detailed cross-document insights
print(f"Report contains {lineage_report['record_count']} records")
print(f"Cross-document boundaries: {lineage_report.get('cross_document', {}).get('boundary_count', 0)}")

# Analyze the flow patterns
if 'flow_patterns' in lineage_report:
    patterns = lineage_report['flow_patterns']
    print("\nCommon data flow patterns:")
    for pattern, count in patterns.get('flow_patterns', {}).items():
        print(f"- {pattern}: {count} occurrences")
    
    # Identify data flow bottlenecks
    print("\nData flow bottlenecks:")
    for bottleneck in patterns.get('bottlenecks', []):
        print(f"- {bottleneck['id']} (score: {bottleneck['bottleneck_score']})")
    
    # Check for circular dependencies
    if 'cycles' in patterns and patterns['cycles']:
        print("\nCircular dependencies detected:")
        for cycle in patterns['cycles']:
            print(f"- Cycle: {' -> '.join(cycle['cycle'])}")

# Method 2: Using storage directly for more control
lineage_graph = manager.storage.build_cross_document_lineage_graph(
    record_ids=["dataset1", "dataset2"],
    max_depth=3,
    link_types=["transformation", "derivation"]
)

# Analyze the cross-document lineage
analysis = manager.storage.analyze_cross_document_lineage(lineage_graph)

# Key metrics from the analysis
print(f"Graph has {analysis['node_count']} nodes and {analysis['edge_count']} edges")
print(f"Documents involved: {analysis['document_count']}")
print(f"Cross-document connections: {analysis['cross_document_connections']}")
print(f"Critical paths: {len(analysis['critical_paths'])}")
print(f"Hub records: {len(analysis['hub_records'])}")

# Visualize cross-document lineage
manager.storage.visualize_cross_document_lineage(
    lineage_graph=lineage_graph,
    highlight_cross_document=True,
    show_metrics=True,
    file_path="cross_document_lineage.html",
    format="html"
)

# Export cross-document lineage in various formats
lineage_data = manager.storage.export_cross_document_lineage(
    lineage_graph=lineage_graph,
    format="json",
    include_records=True
)
```

### Semantic Enhancement with DetailedLineageIntegrator

The new `DetailedLineageIntegrator` provides advanced capabilities for enriching cross-document lineage with semantic context:

```python
from ipfs_datasets_py.cross_document_lineage_enhanced import DetailedLineageIntegrator, CrossDocumentLineageEnhancer

# Initialize components
manager = EnhancedProvenanceManager(enable_ipld_storage=True)
lineage_enhancer = CrossDocumentLineageEnhancer(manager.ipld_storage)
integrator = DetailedLineageIntegrator(
    provenance_manager=manager,
    lineage_enhancer=lineage_enhancer
)

# Get the provenance graph
provenance_graph = manager.get_provenance_graph()

# Integrate provenance with lineage
integrated_graph = integrator.integrate_provenance_with_lineage(provenance_graph)

# Enrich with semantic information
enriched_graph = integrator.enrich_lineage_semantics(integrated_graph)

# Create a comprehensive unified report
lineage_report = integrator.create_unified_lineage_report(
    integrated_graph=enriched_graph,
    include_visualization=True,
    output_path="enhanced_lineage_report.json"
)

# Analyze data flow patterns
flow_patterns = integrator.analyze_data_flow_patterns(enriched_graph)

# Track document lineage evolution over time
evolution = integrator.track_document_lineage_evolution(
    document_id="document_1",
    time_range=(time.time() - 30*86400, time.time())  # Last 30 days
)

# Get growth metrics
growth = evolution['growth_metrics']
print(f"Document growth over 30 days:")
print(f"- Records added: {growth['record_growth']}")
print(f"- Relationships added: {growth['relationship_growth']}")
print(f"- Growth rate: {growth['records_per_day']} records/day")

# Check key events in evolution
print("\nKey events in document evolution:")
for event in evolution['key_events']:
    print(f"- {event['formatted_time']}: {event.get('key_event_reason', 'Unknown event')}")
```
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
   - Multiple layout options: hierarchical, spring, circular, spectral, multipartite
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

### Improved Multipartite Layout

The enhanced provenance system now features improved visualization with automatic node depth assignment for proper multipartite graph layouts:

```python
# Visualize with multipartite layout (nodes arranged in layers)
manager.visualize_provenance_enhanced(
    data_ids=["processed_dataset"],
    layout="multipartite",
    file_path="multipartite_layout.html",
    format="html",
    include_timestamps=True,
    include_parameters=True
)
```

The `multipartite` layout organizes nodes in distinct layers based on their depth in the provenance graph, providing clear visualization of data flow from sources through transformations to final outputs. The system automatically calculates node depth using a topological sorting algorithm, ensuring proper visualization of complex provenance graphs.

### Custom Visualization Options

You can customize the visualization with various options:

```python
# Customize visualization with advanced features
manager.visualize_provenance_enhanced(
    data_ids=["final_dataset"],
    max_depth=3,                 # Limit depth of traversal
    layout="multipartite",       # Layered layout by node depth
    highlight_critical_path=True, # Highlight the most important path
    node_size_by="impact",       # Size nodes by their impact metric
    edge_width_by="weight",      # Width of edges based on weight
    color_scheme="record_type",  # Color nodes by record type
    include_parameters=True,     # Show transformation parameters
    include_timestamps=True,     # Show timestamps on nodes
    include_metrics=True,        # Include complexity metrics
    format="html",               # Output as interactive HTML
    file_path="detailed_viz.html",
    width=1200,
    height=800
)
```

### Interactive Visualization

Interactive visualizations provide rich exploration capabilities:

```python
# Create an interactive dashboard for provenance exploration
manager.create_interactive_dashboard(
    base_record_ids=["dataset_1", "processed_dataset"],
    port=8050,                   # Local port for dashboard
    enable_filtering=True,       # Allow filtering by record type
    enable_search=True,          # Enable search functionality
    enable_time_slider=True,     # Include time-based filtering
    include_metrics_panel=True   # Show metrics panel
)
```

The interactive dashboard allows you to:
- Expand/collapse nodes to explore the graph
- Filter by record type, time period, or other criteria
- Search for specific records by keyword
- View detailed information about each record
- Download visualization in various formats
- Analyze provenance metrics and statistics

## Provenance Analysis

The enhanced provenance system offers comprehensive analytical capabilities:

```python
# Calculate complexity metrics for a data entity
metrics = manager.calculate_data_metrics("final_dataset")
print(f"Complexity: {metrics['complexity']['node_count']} nodes, {metrics['complexity']['max_depth']} depth")
print(f"Impact: {metrics['impact']}")
print(f"Verification: {metrics['verification']['passed']} passed, {metrics['verification']['failed']} failed")
```

### Enhanced Metrics Calculation

The metrics calculation system now properly includes source records and provides more detailed analysis:

```python
# Get comprehensive metrics with enhanced calculation
enhanced_metrics = manager.calculate_data_metrics(
    data_id="processed_dataset",
    include_source_records=True,      # Include source records in metrics
    include_impact_analysis=True,     # Include detailed impact analysis
    include_temporal_metrics=True,    # Include time-based metrics
    include_verification_metrics=True # Include verification metrics
)

# Access detailed complexity metrics
complexity = enhanced_metrics["complexity"]
print(f"Node count: {complexity['node_count']}")
print(f"Edge count: {complexity['edge_count']}")
print(f"Max depth: {complexity['max_depth']}")
print(f"Branch factor: {complexity['branch_factor']}")
print(f"Complexity score: {complexity['complexity_score']}")
print(f"Source records: {complexity['source_count']}")
print(f"Transformation records: {complexity['transformation_count']}")

# Access impact metrics
impact = enhanced_metrics["impact"]
print(f"Impact score: {impact['score']}")
print(f"Downstream entities: {impact['downstream_count']}")
print(f"Critical path length: {impact['critical_path_length']}")
print(f"Direct dependencies: {impact['direct_dependencies']}")

# Access temporal metrics
temporal = enhanced_metrics["temporal"]
print(f"Age (days): {temporal['age_days']}")
print(f"Last update: {temporal['last_update']}")
print(f"Update frequency: {temporal['update_frequency']}")
print(f"Created at: {temporal['created_at']}")

# Access verification metrics
verification = enhanced_metrics["verification"]
print(f"Verification coverage: {verification['coverage']}")
print(f"Passed verifications: {verification['passed']}")
print(f"Failed verifications: {verification['failed']}")
print(f"Verification types: {verification['types']}")
```

### Comparative Metrics Analysis

The system supports comparing metrics across multiple datasets:

```python
# Compare metrics across multiple datasets
comparison = manager.compare_data_metrics(
    data_ids=["dataset_1", "processed_dataset", "final_dataset"],
    metrics=["complexity", "impact", "verification"]
)

# Display comparison results
for data_id, metrics in comparison.items():
    print(f"\nMetrics for {data_id}:")
    print(f"  Complexity score: {metrics['complexity']['complexity_score']}")
    print(f"  Impact score: {metrics['impact']['score']}")
    print(f"  Verification coverage: {metrics['verification']['coverage']}")
```

Available metrics include:
- **Structural complexity**: Node count, edge count, max depth, branch factor, source count
- **Data impact**: Influence on downstream entities, critical path length, dependency count
- **Verification metrics**: Validation pass/fail counts, coverage percentage, types of verification
- **Temporal metrics**: Age, update frequency, creation/modification timestamps
- **Record type distribution**: Breakdown of record types in the provenance graph
- **Enhanced scores**: Normalized complexity and impact scores for easy comparison

### Enhanced Temporal Queries

The enhanced provenance system provides advanced temporal query capabilities with precise date filtering:

```python
import datetime
from ipfs_datasets_py.data_provenance_enhanced import EnhancedProvenanceManager

# Initialize manager
manager = EnhancedProvenanceManager(enable_ipld_storage=True)

# Query records in a specific date range
quarterly_records = manager.temporal_query(
    start_time=datetime.datetime(2023, 1, 1),
    end_time=datetime.datetime(2023, 3, 31),
    time_bucket="daily",
    record_types=["source", "transformation"]
)

# Analyze records by time bucket
for bucket, bucket_records in quarterly_records.items():
    print(f"{bucket}: {len(bucket_records)} records")
    
# Get records from the last 30 days with detailed filtering
recent_records = manager.temporal_query(
    start_time=datetime.datetime.now() - datetime.timedelta(days=30),
    record_types=["verification", "annotation"],
    filter_function=lambda record: record.get("pass_count", 0) > 0,
    include_metadata=True,
    sort_by="timestamp",
    sort_order="descending"
)

# Time-series analysis of provenance activities
activity_timeseries = manager.analyze_temporal_activity(
    start_time=datetime.datetime(2023, 1, 1),
    end_time=datetime.datetime(2023, 12, 31),
    time_bucket="monthly",
    group_by="record_type"
)

# Plot activity time series
manager.plot_temporal_activity(
    activity_timeseries,
    title="Provenance Activity by Month",
    x_label="Month",
    y_label="Record Count",
    include_cumulative=True,
    output_path="activity_timeseries.png"
)
```

The temporal query system supports:
- Precise date filtering with datetime objects
- Multiple time bucket aggregations (hourly, daily, weekly, monthly, yearly)
- Filtering by record types, data IDs, and custom filter functions
- Sorting and pagination of results
- Time-series analysis of provenance activities
- Visualization of temporal patterns and trends