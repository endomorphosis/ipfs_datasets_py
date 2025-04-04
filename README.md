# IPFS Datasets Python

A unified interface for data processing and distribution across decentralized networks, with seamless conversion between formats and storage systems.

## Overview

IPFS Datasets Python serves as a facade to multiple data processing and storage libraries:
- DuckDB, Arrow, and HuggingFace Datasets for data manipulation
- IPLD for data structuring
- IPFS (via ipfs_datasets_py.ipfs_kit) for decentralized storage
- libp2p (via ipfs_datasets_py.libp2p_kit) for peer-to-peer data transfer
- InterPlanetary Wayback (IPWB) for web archive integration
- GraphRAG for knowledge graph-enhanced retrieval and reasoning
- Security and governance features for sensitive data
- Comprehensive audit logging for security, compliance, and operations
- Integrated security-provenance tracking for secure data lineage

## Installation

### Basic Installation
```bash
pip install ipfs-datasets-py
```

### Development Installation
```bash
git clone https://github.com/your-organization/ipfs_datasets_py.git
cd ipfs_datasets_py
pip install -e .
```

### Optional Dependencies
```bash
# For vector search capabilities
pip install ipfs-datasets-py[vector]

# For knowledge graph and RAG capabilities
pip install ipfs-datasets-py[graphrag]

# For web archive integration
pip install ipfs-datasets-py[web_archive]

# For security features
pip install ipfs-datasets-py[security]

# For audit logging capabilities
pip install ipfs-datasets-py[audit]

# For all features
pip install ipfs-datasets-py[all]
```

## Basic Usage

```python
from ipfs_datasets_py import ipfs_datasets

# Load a dataset (supports local and remote datasets)
dataset = ipfs_datasets.load_dataset("wikipedia", subset="20220301.en")
print(f"Loaded dataset with {len(dataset)} records")

# Process the dataset
processed_dataset = ipfs_datasets.process_dataset(
    dataset,
    operations=[
        {"type": "filter", "column": "length", "condition": ">", "value": 1000},
        {"type": "select", "columns": ["id", "title", "text"]}
    ]
)

# Save to different formats
ipfs_datasets.save_dataset(dataset, "output/dataset.parquet", format="parquet")
cid = ipfs_datasets.save_dataset(dataset, "output/dataset.car", format="car")
```

## Vector Search

```python
import numpy as np
from typing import List
from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndex

# Create sample vectors
vectors: List[np.ndarray] = [np.random.rand(768) for _ in range(100)]
metadata = [{"id": i, "source": "wikipedia", "title": f"Article {i}"} for i in range(100)]

# Create vector index
index = IPFSKnnIndex(dimension=768, metric="cosine")
vector_ids = index.add_vectors(vectors, metadata=metadata)

# Search for similar vectors
query_vector = np.random.rand(768)
results = index.search(query_vector, top_k=5)
for i, result in enumerate(results):
    print(f"Result {i+1}: ID={result.id}, Score={result.score:.4f}, Title={result.metadata['title']}")
```

## GraphRAG Integration

The GraphRAG system combines vector similarity search with knowledge graph traversal for enhanced retrieval and reasoning capabilities. It includes advanced query optimization for efficient cross-document reasoning.

```python
from ipfs_datasets_py.ipld import IPLDStorage, IPLDVectorStore, IPLDKnowledgeGraph
from ipfs_datasets_py.graphrag_integration import GraphRAGQueryEngine
from ipfs_datasets_py.knowledge_graph_extraction import KnowledgeGraphExtractor
from ipfs_datasets_py.rag_query_optimizer import UnifiedGraphRAGQueryOptimizer
from ipfs_datasets_py.cross_document_reasoning import CrossDocumentReasoner
import numpy as np

# Initialize IPLD storage components
storage = IPLDStorage()
vector_store = IPLDVectorStore(dimension=768, metric="cosine", storage=storage)
knowledge_graph = IPLDKnowledgeGraph(name="my_graph", storage=storage, vector_store=vector_store)

# Extract knowledge graph from text
extractor = KnowledgeGraphExtractor()
text = "IPFS is a peer-to-peer hypermedia protocol designed to make the web faster, safer, and more open."
entities, relationships = extractor.extract_graph(text)

# Add entities and relationships to the knowledge graph
for entity in entities:
    knowledge_graph.add_entity(
        entity_type=entity.type,
        name=entity.name,
        properties=entity.properties,
        vector=np.random.rand(768)  # In practice, use actual embeddings
    )

for relationship in relationships:
    knowledge_graph.add_relationship(
        relationship_type=relationship.type,
        source=relationship.source_id,
        target=relationship.target_id,
        properties=relationship.properties
    )

# Initialize query optimizer with metrics collection and visualization
from ipfs_datasets_py.rag_query_optimizer import QueryMetricsCollector, QueryVisualizer

# Create metrics collector and visualizer
metrics_collector = QueryMetricsCollector(
    metrics_dir="metrics",
    track_resources=True
)
visualizer = QueryVisualizer(metrics_collector)

# Initialize query optimizer with metrics and visualization capabilities
query_optimizer = UnifiedGraphRAGQueryOptimizer(
    enable_query_rewriting=True,
    enable_budget_management=True,
    auto_detect_graph_type=True,
    metrics_collector=metrics_collector,
    visualizer=visualizer
)

# Initialize GraphRAG query engine with optimizer
query_engine = GraphRAGQueryEngine(
    vector_stores={"default": vector_store},
    knowledge_graph=knowledge_graph,
    query_optimizer=query_optimizer
)

# Perform a query
results = query_engine.query(
    query_text="How does IPFS work?",
    top_k=5,
    max_graph_hops=2
)

# Initialize cross-document reasoner
cross_doc_reasoner = CrossDocumentReasoner(
    query_optimizer=query_optimizer,
    reasoning_tracer=None,  # Optional LLMReasoningTracer can be provided
    min_connection_strength=0.6,
    max_reasoning_depth=3
)

# Advanced cross-document reasoning
reasoning_results = cross_doc_reasoner.reason_across_documents(
    query="What are the security benefits of content addressing in IPFS?",
    query_embedding=None,  # Will be computed if not provided
    vector_store=vector_store,
    knowledge_graph=knowledge_graph,
    reasoning_depth="deep",  # "basic", "moderate", or "deep"
    max_documents=10,
    min_relevance=0.6,
    max_hops=2,
    return_trace=True  # Include detailed reasoning trace
)

print(f"Answer: {reasoning_results['answer']}")
print(f"Confidence: {reasoning_results['confidence']}")

# View entity-mediated connections
for connection in reasoning_results["entity_connections"]:
    print(f"Connection through {connection['entity']} ({connection['type']}): {connection['relation']} relationship")

# Analyze reasoning trace
if "reasoning_trace" in reasoning_results:
    for step in reasoning_results["reasoning_trace"]["steps"]:
        print(f"Reasoning step: {step['content']}")
```

## Web Archive Integration

```python
from ipfs_datasets_py.web_archive_utils import archive_website, index_warc, extract_dataset_from_cdxj

# Archive a website
warc_file = archive_website("https://example.com/", output_dir="archives")

# Index WARC file to IPFS
cdxj_path = index_warc(warc_file, output_path="indexes/example.cdxj")

# Extract dataset from CDXJ index
dataset = extract_dataset_from_cdxj(cdxj_path)
```

## Security and Governance

IPFS Datasets provides comprehensive security and governance features including data classification, access control, security policy enforcement, and secure operations through an integrated design.

```python
from ipfs_datasets_py.audit.enhanced_security import (
    EnhancedSecurityManager, SecurityPolicy, AccessControlEntry, DataClassification, 
    DataEncryptionConfig, AccessDecision, SecuritySession, security_operation
)

# Get the security manager
security_manager = EnhancedSecurityManager.get_instance()

# Set data classifications
security_manager.set_data_classification(
    resource_id="customer_data",
    classification=DataClassification.CONFIDENTIAL,
    user_id="admin_user"
)

# Add access control entries
ace = AccessControlEntry(
    resource_id="customer_data",
    resource_type="dataset",
    principal_id="data_analyst",
    principal_type="user",
    permissions=["read"],
    conditions={"time_range": {"start": "08:00:00", "end": "18:00:00"}}
)
security_manager.add_access_control_entry(ace)

# Create security policies
policy = SecurityPolicy(
    policy_id="data_access_policy",
    name="Sensitive Data Access Policy",
    description="Controls access to sensitive data",
    enforcement_level="enforcing",
    rules=[
        {
            "type": "access_time",
            "allowed_hours": {"start": 8, "end": 18},
            "severity": "medium"
        },
        {
            "type": "data_volume",
            "threshold_bytes": 50 * 1024 * 1024,  # 50MB
            "severity": "high"
        }
    ]
)
security_manager.add_security_policy(policy)

# Secure operations with security decorator
@security_operation(user_id_arg="user_id", resource_id_arg="resource_id", action="process_data")
def process_data(user_id, resource_id, operation_type):
    # Function is automatically protected with access checks and auditing
    return f"Processed {resource_id} with {operation_type} operation"

# Security session context manager
with SecuritySession(
    user_id="data_analyst",
    resource_id="customer_data",
    action="analyze_data"
) as session:
    # Set context for the session
    session.set_context("purpose", "quarterly_analysis")
    
    session.set_context("client_ip", "192.168.1.100")
    
    # Check access within the session
    decision = session.check_access("read")
    
    # Perform operation if allowed
    if decision == AccessDecision.ALLOW:
        # Perform analysis operation
        pass
        
# Security-Provenance Integration for lineage-aware access control
from ipfs_datasets_py.audit.security_provenance_integration import (
    SecurityProvenanceIntegrator, secure_provenance_operation
)

# Initialize the integrator
integrator = SecurityProvenanceIntegrator()

# Function with lineage-aware access control
@secure_provenance_operation(user_id_arg="user", data_id_arg="data_id")
def access_data_with_lineage(user, data_id):
    """
    This function checks access based on both direct permissions
    and data lineage before execution.
    """
    # Only executes if access is allowed based on lineage checks
    return {"status": "success", "data_id": data_id}

# Legacy security API is still supported
from ipfs_datasets_py.security import SecurityManager, require_authentication, require_access

# Initialize security manager
security = SecurityManager()

# Create users with different roles
admin_id = security.create_user("admin", "admin_password", role="admin")
user_id = security.create_user("standard_user", "user_password", role="user")

# Use authentication and access control
@require_authentication
@require_access("dataset_id", "write")
def update_dataset(user_token, dataset_id, new_data):
    # Update logic here
    return True
```

## Audit Logging and Adaptive Security

```python
from ipfs_datasets_py.audit import AuditLogger, AuditCategory, AuditLevel
from ipfs_datasets_py.audit import FileAuditHandler, JSONAuditHandler

# Get the global audit logger
audit_logger = AuditLogger.get_instance()

# Configure handlers
audit_logger.add_handler(FileAuditHandler("file", "logs/audit.log"))
audit_logger.add_handler(JSONAuditHandler("json", "logs/audit.json"))

# Set thread-local context
audit_logger.set_context(user="current_user", session_id="session123")

# Log various types of events
audit_logger.auth("login", status="success", details={"ip": "192.168.1.100"})
audit_logger.data_access("read", resource_id="dataset123", resource_type="dataset")
audit_logger.security("permission_change", level=AuditLevel.WARNING,
                   details={"target_role": "admin", "changes": ["added_user"]})

# Generate compliance report
from ipfs_datasets_py.audit import GDPRComplianceReporter
reporter = GDPRComplianceReporter()
report = reporter.generate_report(events)
report.save_html("reports/gdpr_compliance.html")

# Setup adaptive security response system
from ipfs_datasets_py.audit import (
    AdaptiveSecurityManager, ResponseRule, ResponseAction, RuleCondition,
    IntrusionDetection, SecurityAlertManager
)

# Create security components
alert_manager = SecurityAlertManager(alert_storage_path="security_alerts.json")
intrusion_detection = IntrusionDetection(alert_manager=alert_manager)

# Create adaptive security manager
adaptive_security = AdaptiveSecurityManager(
    alert_manager=alert_manager,
    audit_logger=audit_logger,
    response_storage_path="security_responses.json"
)

# Define a security response rule for brute force login attempts
brute_force_rule = ResponseRule(
    rule_id="brute-force-response",
    name="Brute Force Login Response",
    alert_type="brute_force_login",
    severity_levels=["medium", "high"],
    actions=[
        {
            "type": "LOCKOUT",
            "duration_minutes": 30,
            "account": "{{alert.source_entity}}"
        },
        {
            "type": "NOTIFY",
            "message": "Brute force login detected from {{alert.source_entity}}",
            "recipients": ["security@example.com"]
        }
    ],
    conditions=[
        RuleCondition("alert.attempt_count", ">=", 5)
    ],
    description="Respond to brute force login attempts"
)

# Add rule to the security manager
adaptive_security.add_rule(brute_force_rule)

# Process any pending security alerts
processed_count = adaptive_security.process_pending_alerts()
print(f"Processed {processed_count} security alerts")
```

## Data Provenance and Lineage

IPFS Datasets provides comprehensive data provenance and lineage tracking features to understand the origin, transformations, and usage of data.

### Basic Provenance Tracking

```python
from ipfs_datasets_py.data_provenance_enhanced import EnhancedProvenanceManager

# Initialize provenance manager with IPLD optimization
provenance = EnhancedProvenanceManager(
    storage_path="provenance_data",
    enable_ipld_storage=True,             # Enable IPLD-based storage
    enable_crypto_verification=True,      # Enable cryptographic verification
    default_agent_id="data_scientist",
    tracking_level="detailed",
    visualization_engine="plotly"         # Use interactive visualizations
)

# Record a data source
source_id = provenance.record_source(
    data_id="customer_data",
    source_type="csv", 
    location="/data/customers.csv",
    format="csv",
    description="Raw customer data",
    size=1024 * 1024 * 5,  # 5MB
    hash="sha256:abc123def456...",
    metadata={"document_id": "customer_dataset"}  # Associate with document
)

# Record data cleaning with context manager
with provenance.begin_transformation(
    description="Clean customer data",
    transformation_type="data_cleaning",
    tool="pandas",
    version="1.5.3",
    input_ids=["customer_data"],
    parameters={"dropna": True, "normalize": True},
    metadata={"document_id": "customer_dataset"}  # Same document ID
) as context:
    # Actual data cleaning code would go here
    # ...
    
    # Set output ID
    context.set_output_ids(["cleaned_data"])

# Record data validation with proper semantic indexing
verification_id = provenance.record_verification(
    data_id="cleaned_data",
    verification_type="schema",
    schema={"required": ["customer_id", "name", "email"]},
    validation_rules=[{"field": "email", "rule": "email_format"}],
    pass_count=950,
    fail_count=50,
    description="Customer data schema validation",  # Improved for semantic search
    metadata={"document_id": "data_validation"}  # Different document ID
)
```

### Enhanced Cross-Document Lineage Tracking

The enhanced lineage tracking system provides sophisticated capabilities for tracking data flows across document and domain boundaries with comprehensive metadata and relationship tracking:

```python
from ipfs_datasets_py.cross_document_lineage import EnhancedLineageTracker, LineageDomain, LineageNode
import time
import datetime

# Initialize the enhanced lineage tracker with comprehensive features
tracker = EnhancedLineageTracker(
    config={
        "enable_audit_integration": True,         # Link with audit logging system
        "enable_temporal_consistency": True,      # Ensure logical timing in data flows
        "enable_semantic_detection": True,        # Detect relationships automatically
        "enable_ipld_storage": True,              # Store lineage data using IPLD
        "domain_validation_level": "strict"       # Enforce domain boundary validation
    }
)

# Create hierarchical domains to organize lineage data
org_domain = tracker.create_domain(
    name="OrganizationData",
    description="Root domain for all organizational data",
    domain_type="organization",
    attributes={"compliance_level": "high"}
)

# Create sub-domains with hierarchical organization
finance_domain = tracker.create_domain(
    name="FinanceSystem",
    description="Financial data processing system",
    domain_type="business",
    parent_domain_id=org_domain,  # Define hierarchical relationship
    attributes={
        "organization": "Finance Department",
        "compliance_frameworks": ["SOX", "GDPR"],
        "data_owner": "finance_team",
        "classification": "restricted"
    },
    metadata_schema={  # Define validation schema for metadata
        "required": ["retention_period", "classification"],
        "properties": {
            "retention_period": {"type": "string"},
            "classification": {"enum": ["public", "internal", "confidential", "restricted"]}
        }
    }
)

analytics_domain = tracker.create_domain(
    name="AnalyticsSystem",
    description="Data analytics platform",
    domain_type="business",
    parent_domain_id=org_domain,  # Define hierarchical relationship
    attributes={
        "organization": "Data Science Team",
        "compliance_frameworks": ["GDPR"],
        "data_owner": "analytics_team",
        "classification": "internal"
    }
)

# Create a boundary between domains with security constraints
finance_to_analytics = tracker.create_domain_boundary(
    source_domain_id=finance_domain,
    target_domain_id=analytics_domain,
    boundary_type="data_transfer",
    attributes={
        "protocol": "SFTP", 
        "encryption": "AES-256",
        "access_control": "role_based",
        "data_masking": "enabled",
        "requires_approval": True
    },
    constraints=[
        {"type": "field_level", "fields": ["account_number", "ssn"], "action": "mask"},
        {"type": "time_constraint", "hours": "8-17", "days": "mon-fri"},
        {"type": "approval", "approvers": ["data_governance_team"]}
    ]
)

# Create nodes in specific domains with rich metadata
finance_data = tracker.create_node(
    node_type="dataset",
    metadata={
        "name": "Financial Transactions",
        "format": "parquet",
        "retention_period": "7 years",
        "classification": "restricted",
        "record_count": 1500000,
        "created_at": datetime.datetime.now().isoformat(),
        "source_system": "SAP Financial",
        "schema_version": "2.3",
        "contains_pii": True,
        "data_quality": {
            "completeness": 0.98,
            "accuracy": 0.95,
            "consistency": 0.97
        },
        "security_controls": {
            "encryption": "column-level",
            "access_restriction": "need-to-know",
            "masking_rules": ["account_number", "ssn"]
        }
    },
    domain_id=finance_domain,
    entity_id="financial_data_001"
)

# Create transformation node with detailed tracking and versioning
transform_node = tracker.create_node(
    node_type="transformation",
    metadata={
        "name": "Transaction Analysis",
        "tool": "pandas",
        "version": "1.5.2",
        "execution_time": "45m",
        "executor": "data_scientist_1",
        "execution_id": "job-12345",
        "git_commit": "a7c3b2e1",
        "environment": "production",
        "configuration": {
            "threads": 8,
            "timeout": 3600,
            "incremental": True
        },
        "security_context": {
            "authentication": "mfa",
            "authorization": "role_based",
            "security_clearance": "confidential"
        }
    },
    domain_id=analytics_domain,
    entity_id="analysis_001"
)

# Create relationships with rich context and boundary crossing information
tracker.create_link(
    source_id=finance_data,
    target_id=transform_node,
    relationship_type="input_to",
    metadata={
        "timestamp": datetime.datetime.now().isoformat(),
        "dataflow_id": "flow-23456",
        "filter_conditions": "transaction_date >= '2023-01-01'",
        "quality_checks_passed": True,
        "record_count": 1500000,
        "boundary_crossing": {
            "approved_by": "data_governance_team",
            "approval_date": datetime.datetime.now().isoformat(),
            "security_validation": "passed",
            "transfer_purpose": "quarterly financial analysis"
        }
    },
    confidence=0.95,
    cross_domain=True  # Explicitly mark as cross-domain
)

# Record detailed transformation information with field-level impacts
tracker.record_transformation_details(
    transformation_id=transform_node,
    operation_type="data_aggregation",
    inputs=[
        {"field": "transaction_date", "type": "date", "nullable": False, "format": "yyyy-MM-dd"},
        {"field": "amount", "type": "decimal(10,2)", "nullable": False, "business_entity": "transaction"},
        {"field": "account_number", "type": "string", "nullable": False, "sensitivity": "high", "pii": True},
        {"field": "transaction_type", "type": "string", "nullable": False, "enum": ["debit", "credit"]}
    ],
    outputs=[
        {"field": "daily_total", "type": "decimal(12,2)", "nullable": False, "aggregation": "sum", "business_entity": "daily_summary"},
        {"field": "transaction_count", "type": "integer", "nullable": False, "aggregation": "count"},
        {"field": "avg_transaction_amount", "type": "decimal(10,2)", "nullable": False, "aggregation": "avg"},
        {"field": "transaction_date", "type": "date", "nullable": False, "granularity": "day"},
        {"field": "account_category", "type": "string", "nullable": False, "derived": True}
    ],
    parameters={
        "group_by": ["transaction_date", "account_category"],
        "aggregations": {
            "amount": ["sum", "avg", "min", "max"],
            "transaction_id": ["count"]
        },
        "filters": {
            "amount": "> 0",
            "transaction_status": "= 'completed'"
        },
        "derivations": {
            "account_category": "CASE WHEN account_number LIKE '1%' THEN 'savings' ELSE 'checking' END"
        }
    },
    impact_level="field"
)

# Create version information for lineage nodes
analysis_version = tracker.create_version(
    node_id=transform_node,
    version_number="1.2.0",
    change_description="Added account categorization and improved aggregation logic",
    parent_version_id="v1.1.0",  # Previous version
    creator_id="data_scientist_1",
    attributes={
        "release_notes": "Enhanced transaction analysis with account categorization",
        "quality_score": 0.98,
        "verification_status": "verified",
        "verification_date": datetime.datetime.now().isoformat(),
        "verified_by": "data_quality_team"
    }
)

# Automatically detect semantic relationships between lineage nodes
relationships = tracker.detect_semantic_relationships(
    confidence_threshold=0.7,
    max_candidates=100,
    methods=["content_similarity", "metadata_overlap", "name_matching", "pattern_recognition"]
)
print(f"Detected {len(relationships)} semantic relationships")
for rel in relationships[:3]:  # Show first three for example
    print(f"- {rel['source_id']} → {rel['target_id']} ({rel['relationship_type']}, confidence: {rel['confidence']:.2f})")

# Generate comprehensive provenance report with impact analysis
report = tracker.generate_provenance_report(
    entity_id="financial_data_001",
    include_visualization=True,
    include_impact_analysis=True,
    include_security_context=True,
    include_transformation_details=True,
    include_audit_trail=True,
    format="html"
)
print(f"Generated {report['format']} report: {report['title']}")
print(f"Report includes {report['statistics']['node_count']} nodes and {report['statistics']['relationship_count']} relationships")

# Export lineage to IPLD for decentralized storage with enhanced metadata
root_cid = tracker.export_to_ipld(
    include_domains=True,
    include_boundaries=True,
    include_versions=True,
    include_transformation_details=True,
    include_semantic_relationships=True,
    encrypt_sensitive_data=True  # Enable encryption for sensitive data
)
print(f"Exported lineage graph to IPLD with root CID: {root_cid}")
```

### Advanced Query and Analysis Capabilities

The enhanced lineage tracking system provides powerful query capabilities with fine-grained filters and comprehensive analysis:

```python
# Query for all transformations in the analytics domain that process PII data
query_results = tracker.query_lineage({
    "node_type": "transformation",
    "domain_id": analytics_domain,
    "start_time": datetime.datetime(2023, 1, 1).timestamp(),
    "end_time": datetime.datetime(2023, 12, 31).timestamp(),
    "metadata_filters": {
        "security_context.security_clearance": "confidential"
    },
    "include_domains": True,
    "include_versions": True,
    "include_transformation_details": True,
    "relationship_filter": {
        "types": ["input_to", "derived_from"],
        "cross_domain": True,
        "min_confidence": 0.8
    }
})
print(f"Query found {len(query_results.nodes)} nodes and {len(query_results.links)} relationships")

# Find all paths between two nodes with detailed analysis
paths = tracker.find_paths(
    start_node_id=finance_data,
    end_node_id=transform_node,
    max_depth=5,
    relationship_filter=["input_to", "derived_from", "version_of"],
    include_metrics=True  # Include path metrics like reliability, latency, etc.
)
print(f"Found {len(paths)} paths with the following metrics:")
for i, path in enumerate(paths):
    print(f"Path {i+1}: Length={len(path)}, Confidence={path['metrics']['confidence']:.2f}, Cross-domain boundaries={path['metrics']['boundary_count']}")

# Temporal consistency validation
inconsistencies = tracker.validate_temporal_consistency()
if inconsistencies:
    print(f"Found {len(inconsistencies)} temporal inconsistencies")
    for issue in inconsistencies[:3]:  # Show first three for example
        print(f"- Inconsistency between {issue['source_id']} and {issue['target_id']}: {issue['description']}")

# Analyze impact of a specific node
impact_analysis = tracker.analyze_impact(
    node_id=finance_data,
    max_depth=3, 
    include_domain_analysis=True,
    include_security_implications=True
)
print(f"Impact analysis shows this node affects {impact_analysis['affected_node_count']} downstream nodes")
print(f"Critical downstream nodes: {', '.join(impact_analysis['critical_nodes'])}")

# Create an interactive visualization of the lineage subgraph
visualization = tracker.visualize_lineage(
    subgraph=query_results,
    output_path="lineage_visualization.html",
    visualization_type="interactive",
    include_domains=True,
    highlight_critical_path=True,
    highlight_boundaries=True,
    include_transformation_details=True,
    include_security_context=True,
    layout="hierarchical"
)
```

## Monitoring and Administration

IPFS Datasets provides comprehensive monitoring and administration capabilities:

```python
from ipfs_datasets_py.monitoring import MonitoringSystem, MetricsCollector
from ipfs_datasets_py.admin_dashboard import AdminDashboard

# Initialize monitoring system
monitoring = MonitoringSystem(
    metrics_path="metrics",
    log_path="logs",
    monitoring_interval=60,  # seconds
    enable_prometheus=True,
    enable_alerts=True
)

# Start collecting system metrics
metrics = monitoring.start_metrics_collection(
    collect_system_metrics=True,
    collect_ipfs_metrics=True,
    collect_application_metrics=True
)

# Track a specific operation
with monitoring.track_operation("data_processing", tags=["high_priority"]):
    # perform operation
    process_data()

# Initialize admin dashboard
dashboard = AdminDashboard(
    monitoring_system=monitoring,
    port=8080,
    enable_user_management=True,
    enable_ipfs_management=True
)

# Launch dashboard
dashboard.start()
```

## Learn More

For more detailed information, see our comprehensive documentation:

- [Getting Started Guide](docs/getting_started.md)
- [API Reference](docs/api_reference.md)
- [Integration Examples](docs/integration_examples.md)
- [Advanced Examples](docs/advanced_examples.md)
- [Security and Governance](docs/security_governance.md)
- [Audit Logging](docs/audit_logging.md)
- [Data Provenance](docs/data_provenance.md)
- [IPLD Optimization](docs/ipld_optimization.md)
- [Performance Optimization](docs/performance_optimization.md)

# Search provenance records semantically (now works correctly with all record types)
results = provenance.semantic_search(
    "schema validation", 
    limit=5,
    include_record_types=["verification", "annotation", "transformation"]
)

# Calculate enhanced data metrics (improved to include source records)
metrics = provenance.calculate_data_metrics(
    data_id="cleaned_data",
    include_source_records=True,       # Properly include source records
    include_impact_analysis=True,
    include_temporal_metrics=True
)

impact_score = metrics["impact"]["score"]
complexity = metrics["complexity"]["complexity_score"]
print(f"Data impact score: {impact_score:.2f}")
print(f"Processing depth: {complexity['max_depth']}")
print(f"Source count: {complexity['source_count']}")

# Advanced temporal query with precise date filtering
import datetime
quarterly_records = provenance.temporal_query(
    start_time=datetime.datetime(2023, 1, 1),
    end_time=datetime.datetime(2023, 3, 31),
    record_types=["source", "transformation", "verification"],
    time_bucket="daily",
    sort_by="timestamp",
    sort_order="descending"
)

# Export provenance to CAR file with selective options
export_stats = provenance.export_to_car(
    output_path="provenance.car",
    include_records=True,
    include_graph=True,
    selective_record_ids=["customer_data", "cleaned_data"]  # Only export specific records
)

print(f"Exported {export_stats['record_count']} records with root CID: {export_stats['root_cid']}")

# Import from CAR file with integrity verification
new_provenance = EnhancedProvenanceManager(enable_ipld_storage=True)
import_stats = new_provenance.import_from_car(
    car_path="provenance.car",
    verify_integrity=True,
    skip_existing=True
)

print(f"Imported {import_stats['record_count']} records and {import_stats['edge_count']} edges")
```

## Query Optimization Metrics and Visualization

The rag_query_optimizer module provides comprehensive metrics collection and visualization capabilities to analyze and improve GraphRAG query performance.

```python
from ipfs_datasets_py.rag_query_optimizer import (
    UnifiedGraphRAGQueryOptimizer, 
    QueryMetricsCollector, 
    QueryVisualizer
)
import numpy as np
import os

# Initialize metrics collector and visualizer
metrics_collector = QueryMetricsCollector(
    metrics_dir="query_metrics",
    track_resources=True,
    max_history_size=1000
)
visualizer = QueryVisualizer(metrics_collector)

# Create optimizer with metrics capabilities
optimizer = UnifiedGraphRAGQueryOptimizer(
    metrics_collector=metrics_collector,
    visualizer=visualizer
)

# Execute a query (simplified example)
query_vector = np.random.rand(768)
results, execution_info = optimizer.execute_query(
    processor=graph_processor,
    query={
        "query_vector": query_vector,
        "max_vector_results": 5,
        "max_traversal_depth": 2,
        "edge_types": ["related_to", "part_of"]
    }
)

# Get the query ID from execution info
query_id = execution_info.get("query_id")

# Visualize query execution plan
optimizer.visualize_query_plan(
    query_id=query_id,
    output_file="visualizations/query_plan.png",
    show_plot=True
)

# Visualize resource usage during query execution
optimizer.visualize_resource_usage(
    query_id=query_id,
    output_file="visualizations/resource_usage.png"
)

# Generate an interactive dashboard for query analysis
dashboard_path = optimizer.visualize_metrics_dashboard(
    query_id=query_id,
    output_file="visualizations/query_dashboard.html"
)

# Compare multiple queries
query_ids = [execution_info.get("query_id") for _ in range(3)]  # From multiple executions
optimizer.visualize_performance_comparison(
    query_ids=query_ids,
    labels=["Original", "Optimized", "Simplified"],
    output_file="visualizations/query_comparison.png"
)

# Export metrics to CSV for external analysis
optimizer.export_metrics_to_csv("query_metrics.csv")

# Analyze performance with detailed metrics
performance_analysis = optimizer.analyze_performance()
print(f"Average Query Time: {performance_analysis['avg_query_time']:.3f}s")
print(f"Cache Hit Rate: {performance_analysis['cache_hit_rate']:.2f}")

# View bottlenecks
if "detailed_metrics" in performance_analysis:
    phases = performance_analysis["detailed_metrics"]["phase_breakdown"]
    sorted_phases = sorted(phases.items(), key=lambda x: x[1]["avg_duration"], reverse=True)
    for phase_name, stats in sorted_phases[:3]:
        print(f"Bottleneck: {phase_name}, Avg Time: {stats['avg_duration']:.3f}s")

# View optimization recommendations
for rec in performance_analysis.get("recommendations", []):
    print(f"{rec['importance'].upper()}: {rec['message']}")
```

## Resilient Distributed Operations

```python
from ipfs_datasets_py.resilient_operations import ResilienceManager, resilient

# Create resilience manager
resilience_manager = ResilienceManager()

# Use resilient operations
result = await resilience_manager.resilient_operation(
    operation_func=complex_operation,
    max_retries=3,
    fallback_func=fallback_operation
)

# Use decorator for resilient functions
@resilient(max_retries=3)
def critical_operation():
    # Operation that might fail
    pass
```

## Docker Deployment

```bash
# Build Docker image
docker build -t ipfs-datasets-app .

# Run container
docker run -p 8000:8000 -v /path/to/data:/app/data ipfs-datasets-app

# Run with Docker Compose for multi-service deployment
docker-compose up -d
```

## Documentation

- [Getting Started](docs/getting_started.md): Basic concepts and quick start guide
- [User Guide](docs/user_guide.md): Comprehensive guide for using the library
- [Installation Guide](docs/installation.md): Detailed installation instructions
- [API Reference](docs/api_reference.md): Complete API documentation
- [Advanced Examples](docs/advanced_examples.md): Complex usage patterns
- [Docker Deployment](docs/docker_deployment.md): Containerization guide
- [Tutorials](docs/tutorials/): Step-by-step guides for specific features
- [Security & Governance](docs/security_governance.md): Security features guide
- [Audit Logging](docs/audit_logging.md): Comprehensive audit logging 
- [Data Provenance](docs/data_provenance.md): Enhanced data provenance tracking
- [Performance Optimization](docs/performance_optimization.md): Optimizing for large datasets
- [Distributed Features](docs/distributed_features.md): Multi-node capabilities
- [IPLD Optimization](docs/ipld_optimization.md): IPLD encoding/decoding optimizations
- [Query Optimization](docs/query_optimization.md): Optimizing graph and vector queries
- [Query Metrics and Visualization](docs/query_optimization.md#metrics-and-visualization): Advanced metrics collection and visualization for query analysis

## Testing

```bash
python3 test/test.py                                        # Run all tests
python3 -c "from test.test import test; test()"             # Run single test function
python3 -c "from test.test import download_test; download_test()"  # Test downloads
python3 -c "from test.phase1.run_llm_tests import run_all"  # Run LLM integration tests
```

## Project Status

This project has completed all planned implementation phases:
- ✅ Phase 0: Foundation
- ✅ Phase 1: Core Infrastructure Integration
- ✅ Phase 2: Processing & Analysis
- ✅ Phase 3: Advanced Features
- ✅ Phase 4: Optimization and Scaling
- ✅ Phase 5: Production Readiness

## Related Projects

- [IPFS Transformers](https://github.com/endomorphosis/ipfs_transformers/): Transformers library with IPFS support
- [IPFS Transformers JS](https://github.com/endomorphosis/ipfs_transformers_js/): JavaScript client for IPFS Transformers
- [OrbitDB Kit](https://github.com/endomorphosis/orbitdb_kit/): NodeJS library for OrbitDB
- [Fireproof Kit](https://github.com/endomorphosis/fireproof_kit): NodeJS library for Fireproof
- [IPFS FAISS](https://github.com/endomorphosis/ipfs_faiss/): FAISS vector search with IPFS support
- [IPFS Model Manager](https://github.com/endomorphosis/ipfs_model_manager/): Python model manager for IPFS
- [IPFS Model Manager JS](https://github.com/endomorphosis/ipfs_model_manager_js/): JavaScript model manager for IPFS
- [IPFS Huggingface Scraper](https://github.com/endomorphosis/ipfs_huggingface_scraper/): NodeJS scraper with pinning services

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Authors

- Benjamin Barber - Creator
- Kevin De Haan - QA