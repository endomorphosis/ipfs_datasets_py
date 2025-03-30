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

# Initialize query optimizer
query_optimizer = UnifiedGraphRAGQueryOptimizer(
    enable_query_rewriting=True,
    enable_budget_management=True,
    auto_detect_graph_type=True
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

```python
from ipfs_datasets_py.security import SecurityManager, require_authentication, require_access

# Initialize security manager
security = SecurityManager()

# Create users with different roles
admin_id = security.create_user("admin", "admin_password", role="admin")
user_id = security.create_user("standard_user", "user_password", role="user")

# Encrypt sensitive data
key_id = security.create_encryption_key("my-secret-key")
encrypted_data = security.encrypt_data("This is confidential".encode(), key_id)

# Use authentication and access control
@require_authentication
@require_access("dataset_id", "write")
def update_dataset(user_token, dataset_id, new_data):
    # Update logic here
    return True
```

## Audit Logging

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
```

## Data Provenance and Lineage

```python
from ipfs_datasets_py.data_provenance_enhanced import EnhancedProvenanceManager

# Initialize provenance manager
provenance = EnhancedProvenanceManager(
    storage_path="provenance_data",
    enable_ipld_storage=True,
    default_agent_id="data_scientist",
    tracking_level="detailed",
    visualization_engine="matplotlib"
)

# Record a data source
source_id = provenance.record_source(
    data_id="customer_data",
    source_type="csv", 
    location="/data/customers.csv",
    format="csv",
    description="Raw customer data",
    size=1024 * 1024 * 5,  # 5MB
    hash="sha256:abc123def456..."
)

# Record data cleaning with context manager
with provenance.begin_transformation(
    description="Clean customer data",
    transformation_type="data_cleaning",
    tool="pandas",
    version="1.5.3",
    input_ids=["customer_data"],
    parameters={"dropna": True, "normalize": True}
) as context:
    # Actual data cleaning code would go here
    # ...
    
    # Set output ID
    context.set_output_ids(["cleaned_data"])

# Record data validation
verification_id = provenance.record_verification(
    data_id="cleaned_data",
    verification_type="schema",
    schema={"required": ["customer_id", "name", "email"]},
    validation_rules=[{"field": "email", "rule": "email_format"}],
    pass_count=950,
    fail_count=50,
    description="Customer data validation"
)

# Generate enhanced visualization
provenance.visualize_provenance_enhanced(
    data_ids=["cleaned_data"],
    max_depth=5,
    include_parameters=True,
    show_timestamps=True,
    layout="hierarchical",
    highlight_critical_path=True,
    include_metrics=True,
    file_path="visualizations/data_lineage.png",
    format="png",
    width=1200,
    height=800
)

# Search provenance records semantically
results = provenance.semantic_search("customer validation schema", limit=5)

# Calculate data metrics
metrics = provenance.calculate_data_metrics("cleaned_data")
impact_score = metrics["impact"]
complexity = metrics["complexity"]
print(f"Data impact score: {impact_score:.2f}")
print(f"Processing depth: {complexity['max_depth']}")

# Export provenance to CAR file for distributed verification
provenance.export_to_car("provenance.car")
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