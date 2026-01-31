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

IPFS Datasets Python provides comprehensive web scraping and archiving capabilities through multiple integrated services and tools.

### InterPlanetary Wayback Machine (IPWB)

Archive websites directly to IPFS with decentralized access:

```python
from ipfs_datasets_py.web_archiving.web_archive_utils import WebArchiveProcessor

processor = WebArchiveProcessor()

# Archive a website locally
warc_file = processor.create_warc(
    url="https://example.com",
    output_path="archives/example.warc.gz",
    options={
        "agent": "wget",  # or "squidwarc" for dynamic sites
        "depth": 2,
        "compress": True
    }
)

# Index WARC to IPFS using IPWB
index_result = processor.index_warc(
    warc_path=warc_file,
    output_path="indexes/example.cdxj"
)

print(f"IPFS hash: {index_result['ipfs_hash']}")
print(f"Record count: {index_result['record_count']}")

# Extract structured data from archive
text_data = processor.extract_text_from_warc(warc_file)
link_data = processor.extract_links_from_warc(warc_file)
metadata = processor.extract_metadata_from_warc(warc_file)
```

### Multiple Archive Services

Archive content to multiple web archive services simultaneously:

```python
from archivenow import archivenow

# Archive to Internet Archive
ia_url = archivenow.push("https://example.com", "ia")
print(f"Internet Archive: {ia_url}")

# Archive to Archive.is (archive.today)
is_url = archivenow.push("https://example.com", "is")
print(f"Archive.is: {is_url}")

# Archive to Perma.cc
cc_url = archivenow.push("https://example.com", "cc") 
print(f"Perma.cc: {cc_url}")

# Create local WARC file
warc_url = archivenow.push("https://example.com", "warc", {"warc": "example"})
print(f"Local WARC: {warc_url}")
```

### Internet Archive Wayback Machine

Query and download historical web content:

```python
import requests

def query_wayback_machine(url, from_date="20200101", to_date="20240101"):
    """Query Wayback Machine for historical captures."""
    cdx_url = "http://web.archive.org/cdx/search/cdx"
    params = {
        'url': url,
        'from': from_date,
        'to': to_date,
        'output': 'json',
        'limit': 100
    }
    
    response = requests.get(cdx_url, params=params)
    captures = response.json()[1:]  # Skip header row
    
    return captures

# Query historical captures
captures = query_wayback_machine("example.com")
print(f"Found {len(captures)} historical captures")

# Access specific historical version
if captures:
    timestamp, original_url = captures[0][0], captures[0][1]
    wayback_url = f"http://web.archive.org/web/{timestamp}/{original_url}"
    print(f"Access historical version: {wayback_url}")
```

### Common Crawl Integration

Access large-scale web crawl data:

```python
def query_common_crawl(domain, crawl_id="CC-MAIN-2024-10"):
    """Query Common Crawl for domain content."""
    cc_url = f"https://index.commoncrawl.org/{crawl_id}-index"
    params = {
        'url': f"*.{domain}/*",
        'output': 'json',
        'limit': 100
    }
    
    response = requests.get(cc_url, params=params)
    results = []
    for line in response.text.strip().split('\n'):
        if line:
            results.append(json.loads(line))
    
    return results

# Query Common Crawl data
cc_results = query_common_crawl("example.com")
print(f"Found {len(cc_results)} Common Crawl records")

# Download specific WARC records from Common Crawl
for result in cc_results[:3]:  # First 3 results
    warc_url = result['url']
    offset = result['offset']
    length = result['length']
    print(f"WARC record: {warc_url} (offset: {offset}, length: {length})")
```

### Archive.is Integration

```python
import requests
import time

def archive_to_archive_is(url):
    """Archive URL to archive.is service."""
    response = requests.post(
        'https://archive.is/submit/',
        data={'url': url},
        headers={'User-Agent': 'IPFS Datasets Archive Bot 1.0'},
        timeout=30
    )
    
    if response.status_code == 200:
        return response.url  # Archive URL
    else:
        raise Exception(f"Archive failed with status: {response.status_code}")

# Archive to archive.is
try:
    archive_url = archive_to_archive_is("https://example.com")
    print(f"Archived to archive.is: {archive_url}")
except Exception as e:
    print(f"Archive.is error: {e}")
```

## Media Scraping Integration  

### Video and Audio Downloads

Download content from 1000+ platforms using YT-DLP:

```python
from ipfs_datasets_py.mcp_server.tools.media_tools import (
    ytdlp_download_video, ytdlp_download_playlist, ytdlp_extract_info
)

# Download single video with metadata
video_result = await ytdlp_download_video(
    url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    output_dir="downloads",
    quality="best[height<=720]",
    download_info_json=True,
    download_thumbnails=True,
    subtitle_langs=["en", "auto"]
)

# Download playlist
playlist_result = await ytdlp_download_playlist(
    url="https://www.youtube.com/playlist?list=PLrAXtmRdnEQy5JBZM-0P3KKiMxz5e3fXr",
    output_dir="downloads/playlists",
    quality="best[height<=480]",
    max_downloads=10
)

# Extract video information without downloading
info_result = await ytdlp_extract_info(
    url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    extract_flat=False
)

print(f"Video title: {info_result['title']}")
print(f"Duration: {info_result['duration']} seconds")
print(f"View count: {info_result['view_count']}")
```

### Media Processing with FFmpeg

Process downloaded media with professional tools:

```python
from ipfs_datasets_py.mcp_server.tools.media_tools import (
    ffmpeg_convert, ffmpeg_probe, ffmpeg_apply_filters, ffmpeg_batch_process
)

# Convert video to standard format
conversion_result = await ffmpeg_convert(
    input_file="downloads/video.webm",
    output_file="processed/video.mp4",
    video_codec="libx264",
    audio_codec="aac",
    resolution="1280x720",
    quality="medium"
)

# Extract audio from video
audio_result = await ffmpeg_convert(
    input_file="downloads/video.mp4",
    output_file="processed/audio.mp3",
    video_codec=None,  # Remove video stream
    audio_codec="mp3",
    audio_bitrate="320k"
)

# Apply filters and effects
filtered_result = await ffmpeg_apply_filters(
    input_file="processed/video.mp4",
    output_file="processed/enhanced.mp4",
    video_filters=["scale=1920:1080", "brightness=0.1"],
    audio_filters=["volume=1.2", "highpass=f=100"]
)

# Batch process multiple files
batch_result = await ffmpeg_batch_process(
    input_files=["file1.mp4", "file2.webm", "file3.avi"],
    output_directory="processed/batch/",
    operation="convert",
    operation_params={
        "video_codec": "libx264",
        "audio_codec": "aac",
        "quality": "medium"
    },
    max_parallel=3
)
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

- [API Reference](guides/reference/api_reference.md)
- [Installation Guide](installation.md)
- [Performance Optimization](guides/performance_optimization.md)
- [IPLD Optimization](guides/ipld_optimization.md)
- [Query Optimization](guides/query_optimization.md)
- [Security & Governance](guides/security/security_governance.md)
- [Data Provenance](guides/data_provenance.md)
- [Audit Logging](guides/security/audit_logging.md)
- [Distributed Features](guides/distributed_features.md)

For additional examples and tutorials, check out the `examples/` directory in the repository.


---

## Best Practices

### Performance Optimization
- **Use hardware acceleration**: Enable `ipfs_accelerate_py` for 2-20x performance improvements
- **Batch processing**: Process data in batches for better throughput
- **Caching**: Leverage caching mechanisms to avoid redundant operations
- **Async operations**: Use async/await for I/O-bound operations

### IPFS Integration
- **Pin important content**: Use `ipfs_kit_py` to pin content for persistence
- **Content addressing**: Leverage CID-based deduplication
- **CAR files**: Use CAR archives for bulk storage and transfer
- **Pinning services**: Configure remote pinning for reliability

### Code Organization
- **Follow reorganized structure**: Use correct import paths after refactoring
  ```python
  # Correct imports
  from ipfs_datasets_py.dashboards.mcp_dashboard import MCPDashboard
  from ipfs_datasets_py.caching.cache import GitHubAPICache
  from ipfs_datasets_py.web_archiving.web_archive import create_web_archive
  ```

### Error Handling
- **Graceful degradation**: Handle missing dependencies gracefully
- **Retry logic**: Implement retry for network operations
- **Logging**: Use structured logging for debugging
- **Validation**: Validate inputs before processing

### Security
- **Secrets management**: Use environment variables for sensitive data
- **Input validation**: Sanitize and validate all user inputs
- **Access control**: Implement proper authentication/authorization
- **Audit logging**: Track important operations

### Common Pitfalls to Avoid
- ❌ Don't use old import paths (pre-refactoring)
- ❌ Don't hardcode file paths
- ❌ Don't ignore error handling
- ❌ Don't skip dependency version pinning
- ❌ Don't commit sensitive data

### Integration Tips
- **MCP Tools**: Use the unified CLI for tool execution
- **Docker**: Use provided Dockerfiles in `docker/` directory
- **Testing**: Run `pytest` with parallel execution for faster tests
- **Documentation**: Refer to guides in `docs/guides/` for detailed info

