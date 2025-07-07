# IPFS Datasets Python User Guide

## Introduction

IPFS Datasets Python provides a unified interface for data processing and distribution across decentralized networks, with seamless conversion between formats and storage systems. This user guide will help you understand how to effectively use the library for various data processing, storage, and retrieval tasks.

## Core Concepts

### Data Sources and Formats

IPFS Datasets Python supports multiple data sources and formats:

- **HuggingFace Datasets**: Access pre-built datasets or create custom ones
- **DuckDB**: Efficient analytical processing with SQL queries
- **Apache Arrow**: Memory-efficient in-memory data processing
- **Parquet Files**: Columnar storage format for efficient data access
- **CAR Files**: Content-addressed archives for IPFS storage
- **Web Archives**: WARC files and CDX indexes

### Storage and Distribution

- **IPFS Storage**: Content-addressed storage on the IPFS network
- **IPLD Structures**: Structured data representation with content addressing
- **P2P Distribution**: Peer-to-peer sharing of datasets
- **Vector Indexes**: Similarity search for embedding vectors

### Knowledge and Retrieval

- **Knowledge Graphs**: Entity and relationship modeling
- **GraphRAG**: Graph-enhanced retrieval augmented generation
- **Cross-Document Reasoning**: Connect information across documents
- **Vector Search**: Semantic search with embedding vectors

## Getting Started

### Installation

```bash
# Install from PyPI
pip install ipfs-datasets-py

# Install with optional dependencies
pip install ipfs-datasets-py[all]
```

For development installation:

```bash
git clone https://github.com/yourusername/ipfs_datasets_py.git
cd ipfs_datasets_py
pip install -e .
pip install -r requirements.txt
```

### Basic Usage

```python
import numpy as np
from typing import List
from ipfs_datasets_py import ipfs_datasets
from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndex

# Load a dataset
dataset = ipfs_datasets.load_dataset("wikipedia", subset="20220301.en")
print(f"Loaded dataset with {len(dataset)} records")

# Create vector index
index = IPFSKnnIndex(dimension=768, metric="cosine")
vectors = [np.random.rand(768) for _ in range(100)]
metadata = [{"id": i, "source": "wikipedia", "title": f"Article {i}"} for i in range(100)]
vector_ids = index.add_vectors(vectors, metadata=metadata)

# Search for similar vectors
query_vector = np.random.rand(768)
results = index.search(query_vector, top_k=5)
for i, result in enumerate(results):
    print(f"Result {i+1}: ID={result.id}, Score={result.score:.4f}, Title={result.metadata['title']}")
```

## Working with Datasets

### Loading Datasets

```python
from ipfs_datasets_py import ipfs_datasets

# Load from HuggingFace Datasets
dataset = ipfs_datasets.load_dataset("wikipedia", subset="20220301.en")

# Load from Parquet file
dataset = ipfs_datasets.load_from_parquet("path/to/data.parquet")

# Load from IPFS (by CID)
dataset = ipfs_datasets.load_from_ipfs("QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco")

# Load from CAR file
dataset = ipfs_datasets.load_from_car("path/to/data.car")
```

### Processing Datasets

```python
# Transform dataset
processed_dataset = dataset.map(lambda example: {
    "text": example["text"].lower(),
    "word_count": len(example["text"].split())
})

# Filter dataset
filtered_dataset = dataset.filter(lambda example: example["word_count"] > 100)

# Sort dataset
sorted_dataset = dataset.sort("word_count", reverse=True)

# Select columns
selected_dataset = dataset.select(["id", "text", "word_count"])
```

### Saving Datasets

```python
# Save to Parquet file
dataset.save_to_parquet("path/to/output.parquet")

# Save to IPFS
cid = dataset.save_to_ipfs(pin=True)
print(f"Dataset saved to IPFS with CID: {cid}")

# Save to CAR file
dataset.save_to_car("path/to/output.car")

# Upload to HuggingFace Hub
dataset.push_to_hub("your-username/dataset-name")
```

## Vector Search and Embedding

### Creating Embeddings

```python
from ipfs_datasets_py.embeddings import EmbeddingGenerator

# Initialize embedding generator
generator = EmbeddingGenerator(model_name="sentence-transformers/all-MiniLM-L6-v2")

# Generate embeddings for a text
text = "This is a sample text for embedding generation."
embedding = generator.generate(text)

# Generate embeddings for multiple texts
texts = ["Text 1", "Text 2", "Text 3"]
embeddings = generator.generate_batch(texts)

# Generate embeddings for a dataset
dataset_with_embeddings = generator.add_embeddings_to_dataset(
    dataset, text_column="text", embedding_column="embeddings"
)
```

### Vector Indexing

```python
from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndex
import numpy as np

# Create vector index
index = IPFSKnnIndex(dimension=768, metric="cosine")

# Add vectors
vectors = [...]  # List of numpy arrays
metadata = [...]  # List of dictionaries
vector_ids = index.add_vectors(vectors, metadata=metadata)

# Search
query_vector = np.random.rand(768)
results = index.search(query_vector, top_k=10)

# Save and load index
index.save("path/to/index")
loaded_index = IPFSKnnIndex.load("path/to/index")

# Export to IPFS
cid = index.export_to_ipfs(pin=True)
print(f"Index saved to IPFS with CID: {cid}")
```

### Multi-Model Vector Search

```python
from ipfs_datasets_py.ipfs_knn_index import MultiModelSearch

# Create multi-model searcher
searcher = MultiModelSearch(
    models={
        "miniLM": {"dimension": 384, "weight": 0.3},
        "mpnet": {"dimension": 768, "weight": 0.7}
    }
)

# Add vectors for each model
searcher.add_vectors(
    model_name="miniLM",
    vectors=vectors_miniLM,
    metadata=metadata
)
searcher.add_vectors(
    model_name="mpnet",
    vectors=vectors_mpnet,
    metadata=metadata
)

# Perform multi-model search
results = searcher.search(
    query_vectors={
        "miniLM": query_vector_miniLM,
        "mpnet": query_vector_mpnet
    },
    top_k=10,
    aggregation_method="weighted"
)
```

## Knowledge Graphs

### Creating a Knowledge Graph

```python
from ipfs_datasets_py.knowledge_graph import IPLDKnowledgeGraph

# Create a knowledge graph
kg = IPLDKnowledgeGraph()

# Add entities
entity1_cid = kg.add_entity({
    "name": "IPFS",
    "type": "technology",
    "properties": {"description": "InterPlanetary File System"}
})

entity2_cid = kg.add_entity({
    "name": "Content Addressing",
    "type": "concept",
    "properties": {"description": "Addressing content by its hash"}
})

# Add relationships
relationship_cid = kg.add_relationship(
    source_cid=entity1_cid,
    target_cid=entity2_cid,
    relationship_type="uses",
    properties={"confidence": 0.95}
)
```

### Querying a Knowledge Graph

```python
# Simple query
results = kg.query(
    start_entity=entity1_cid,
    relationship_path=["uses", "related_to"]
)

# Vector-augmented query
query_vector = embedding_generator.generate("How does IPFS use content addressing?")
results = kg.vector_augmented_query(
    query_vector=query_vector,
    relationship_constraints=[
        {"type": "uses", "direction": "outgoing"},
        {"type": "related_to", "direction": "any"}
    ]
)
```

### Knowledge Graph Extraction

```python
from ipfs_datasets_py.knowledge_graph_extraction import KnowledgeGraphExtractor

# Create extractor
extractor = KnowledgeGraphExtractor(
    extraction_temperature=0.7,
    structure_temperature=0.5
)

# Extract knowledge graph from text
text = "IPFS is a peer-to-peer hypermedia protocol designed to preserve and grow humanity's knowledge..."
extracted_kg = extractor.extract(text)

# Merge with existing knowledge graph
kg.merge(extracted_kg)
```

## GraphRAG

### GraphRAG Setup

```python
from ipfs_datasets_py.llm.llm_graphrag import GraphRAGLLMProcessor
from ipfs_datasets_py.knowledge_graph import IPLDKnowledgeGraph
from ipfs_datasets_py.ipfs_knn_index import IPFSKnnIndex

# Create components
kg = IPLDKnowledgeGraph.from_cid("bafy...")
index = IPFSKnnIndex.load("path/to/index")

# Create GraphRAG processor
processor = GraphRAGLLMProcessor(
    knowledge_graph=kg,
    vector_index=index,
    embedding_model="sentence-transformers/all-MiniLM-L6-v2"
)
```

### GraphRAG Query

```python
# Simple query
results = processor.query(
    query_text="How does IPFS implement content addressing?",
    max_results=5
)

# Cross-document reasoning
reasoning_result = processor.cross_document_reasoning(
    query="Compare how IPFS and Git implement content addressing",
    max_hops=2,
    min_relevance=0.7,
    reasoning_depth="deep"
)

print(reasoning_result["answer"])
for doc in reasoning_result["documents"]:
    print(f"Document: {doc['title']}, Relevance: {doc['relevance']}")
```

### Query Optimization

```python
from ipfs_datasets_py.rag.rag_query_optimizer import UnifiedGraphRAGQueryOptimizer

# Create optimizer
optimizer = UnifiedGraphRAGQueryOptimizer(auto_detect_graph_type=True)

# Optimize query
query_text = "How does IPFS implement content addressing?"
query_vector = embedding_generator.generate(query_text)

optimized_plan = optimizer.optimize_query(
    query_vector=query_vector,
    query_text=query_text,
    trace_id="trace-123",  # For Wikipedia KG
    root_cids=["bafy..."],  # For IPLD KG
)

# Execute with optimized plan
results = processor.execute_optimized_query(query_text, optimized_plan)
```

## Web Archive Integration

### Archiving Websites

```python
from ipfs_datasets_py.web_archive_utils import archive_website, index_warc

# Archive a website
warc_file = archive_website(
    url="https://example.com",
    output_dir="archives",
    agent="wget"
)

# Index WARC to IPFS
cdxj_path = index_warc(warc_file)

# Extract structured data
dataset = extract_dataset_from_cdxj(cdxj_path)
```

### Searching Web Archives

```python
from ipfs_datasets_py.web_archive_utils import query_wayback_machine, download_wayback_captures

# Query Wayback Machine
captures = query_wayback_machine(
    url="example.com",
    from_date="20150101",
    to_date="20220101",
    match_type="domain",
    limit=500
)

# Download captures
warc_data = download_wayback_captures(captures)

# Process into dataset
dataset = wayback_to_dataset(warc_data)
```

## DuckDB Integration

### DuckDB Queries

```python
from ipfs_datasets_py.duckdb_connector import DuckDBConnector

# Create connector
db = DuckDBConnector(database_path="analytics.duckdb")

# Execute query and get Arrow table
result = db.query_to_arrow("""
    SELECT 
        category,
        COUNT(*) as count,
        AVG(value) as avg_value
    FROM my_table
    GROUP BY category
    ORDER BY count DESC
""")

# Export to Parquet
db.export_to_parquet(
    query="SELECT * FROM my_table WHERE value > 100",
    output_path="filtered.parquet"
)

# Import from Parquet
db.import_from_parquet("data.parquet", "imported_table")
```

### DuckDB with IPFS Integration

```python
# Export to CAR file
db.export_to_car(
    query="SELECT * FROM my_table WHERE category = 'science'",
    output_path="science_data.car",
    hash_columns=["id", "timestamp"]
)

# Import from CAR file
db.import_from_car("data.car", "imported_table")

# Execute query and store result to IPFS
cid = db.query_to_ipfs(
    query="SELECT * FROM analytics WHERE date BETWEEN '2023-01-01' AND '2023-12-31'",
    pin=True
)
```

## Security & Governance

### Data Provenance

```python
from ipfs_datasets_py.data_provenance import EnhancedProvenanceManager

# Create provenance manager
provenance = EnhancedProvenanceManager()

# Record transformation
transform_id = provenance.record_transformation(
    source_id="dataset123",
    transformation_type="filter",
    parameters={"column": "quality", "operator": ">", "value": 0.8},
    output_id="filtered_dataset456"
)

# Record data access
access_id = provenance.record_access(
    data_id="filtered_dataset456",
    access_type="read",
    user_id="user789",
    purpose="analysis"
)

# Get lineage
lineage = provenance.get_lineage("filtered_dataset456")

# Generate provenance report
report = provenance.generate_report("filtered_dataset456")
```

### Audit Logging

```python
from ipfs_datasets_py.audit import AuditLogger, AuditLevel, AuditCategory

# Get audit logger
audit_logger = AuditLogger.get_instance()

# Configure audit logger
audit_logger.min_level = AuditLevel.INFO
audit_logger.default_application = "ipfs_datasets_example"

# Add handlers
audit_logger.add_file_handler(
    name="file",
    file_path="logs/audit.log",
    min_level=AuditLevel.INFO
)

# Log events
audit_logger.log(
    level=AuditLevel.INFO,
    category=AuditCategory.DATA_ACCESS,
    message="User accessed dataset",
    context={
        "user_id": "user123",
        "dataset_id": "dataset456",
        "access_type": "read"
    }
)

# Use with context manager
with audit_logger.create_context(
    category=AuditCategory.DATA_MODIFICATION,
    context={"operation": "transform"}
) as audit_ctx:
    # Perform operations
    audit_ctx.log(AuditLevel.INFO, "Starting transformation")
    # ...
    audit_ctx.log(AuditLevel.INFO, "Completed transformation")
```

### Access Control

```python
from ipfs_datasets_py.access_control import AccessControlManager

# Create access control manager
acm = AccessControlManager()

# Grant permissions
acm.grant_permission(
    resource_id="dataset123",
    user_id="user456",
    permission="read"
)

# Check permissions
has_permission = acm.check_permission(
    resource_id="dataset123",
    user_id="user456",
    permission="write"
)

# Use with datasets
with acm.require_permission("dataset123", "read"):
    dataset = ipfs_datasets.load_dataset("dataset123")
```

## Distributed Features

### P2P Dataset Sharing

```python
from ipfs_datasets_py.p2p import DatasetPublisher, DatasetSubscriber

# Publish dataset
publisher = DatasetPublisher()
topic = publisher.publish(
    dataset=dataset,
    topic="science-datasets",
    metadata={"name": "Climate Data 2023", "version": "1.0"}
)

# Subscribe to datasets
subscriber = DatasetSubscriber()
subscription = subscriber.subscribe(
    topic="science-datasets",
    callback=lambda dataset, metadata: process_dataset(dataset, metadata)
)
```

### Federated Search

```python
from ipfs_datasets_py.federated_search import FederatedSearch

# Create federated search
searcher = FederatedSearch(
    nodes=["node1", "node2", "node3"],
    timeout_seconds=30
)

# Search across nodes
results = searcher.search(
    query_vector=query_vector,
    top_k=10,
    combine_method="score_based"
)
```

### Distributed Processing

```python
from ipfs_datasets_py.distributed import DistributedProcessor

# Create distributed processor
processor = DistributedProcessor(
    worker_nodes=["node1", "node2", "node3"],
    task_timeout=60
)

# Process dataset in distributed manner
result = processor.map_reduce(
    dataset=large_dataset,
    map_function=lambda chunk: process_chunk(chunk),
    reduce_function=lambda results: combine_results(results)
)
```

## Advanced Features

### Streaming Processing

```python
from ipfs_datasets_py.streaming import StreamingProcessor

# Process a large dataset in streaming fashion
processor = StreamingProcessor(chunk_size=10000)

# Process Parquet file to CAR file
processor.stream_parquet_to_car(
    parquet_path="large_dataset.parquet",
    car_path="large_dataset.car"
)
```

### Query Profiling

```python
from ipfs_datasets_py.profiling import QueryProfiler

# Create query profiler
profiler = QueryProfiler()

# Profile query execution
with profiler.profile() as profile:
    results = index.search(query_vector, top_k=10)

# Get performance metrics
metrics = profile.get_metrics()
print(f"Execution time: {metrics['execution_time']} ms")
print(f"Memory usage: {metrics['memory_usage']} MB")

# Get optimization recommendations
recommendations = profile.get_recommendations()
for recommendation in recommendations:
    print(f"Recommendation: {recommendation}")
```

### Result Caching

```python
from ipfs_datasets_py.query_optimizer import QueryResultCache

# Create query result cache
cache = QueryResultCache(max_size=1000, ttl_seconds=3600)

# Query with caching
query_key = cache.generate_key(query_vector, params)
cached_result = cache.get(query_key)

if cached_result:
    return cached_result
else:
    result = execute_query(query_vector, params)
    cache.put(query_key, result)
    return result
```

## Configuration

```python
from ipfs_datasets_py.config import Config

# Load configuration
config = Config.load_from_file("config.toml")

# Get configuration values
ipfs_endpoint = config.get("ipfs.api_endpoint")
cache_dir = config.get("storage.cache_dir")
vector_dimension = config.get("vector_index.default_dimension")

# Set configuration values
config.set("ipfs.pin", True)
config.set("vector_index.use_memory_mapping", True)

# Save configuration
config.save_to_file("config.toml")
```

## Conclusion

This user guide covered the main features and functionality of IPFS Datasets Python. For more detailed information, please refer to the following resources:

- [API Reference](api_reference.md)
- [Installation Guide](installation.md)
- [Performance Optimization](performance_optimization.md)
- [IPLD Optimization](ipld_optimization.md)
- [Query Optimization](query_optimization.md)
- [Security & Governance](security_governance.md)
- [Data Provenance](data_provenance.md)
- [Audit Logging](audit_logging.md)
- [Distributed Features](distributed_features.md)

For additional examples and tutorials, check out the `examples/` directory in the repository.