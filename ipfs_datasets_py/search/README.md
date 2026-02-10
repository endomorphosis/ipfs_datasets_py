# Search - Advanced Embedding-Based Search Capabilities

This module provides comprehensive search functionality using embeddings and vector similarity for the IPFS Datasets Python library.

## Overview

The search module implements advanced embedding-based search capabilities, enabling semantic search, similarity matching, and intelligent retrieval across document collections stored in IPFS and other decentralized systems.

## Components

### SearchEmbeddings (`search_embeddings.py`)
Core search engine implementing embedding-based similarity search with advanced ranking and filtering capabilities.

**Key Features:**
- Semantic similarity search using vector embeddings
- Hybrid search combining text and vector matching
- Advanced ranking algorithms with relevance scoring
- Metadata filtering and faceted search
- Real-time indexing and search capabilities
- Distributed search across IPFS clusters

**Main Methods:**
- `search()` - Perform semantic similarity search
- `index_documents()` - Add documents to search index
- `update_index()` - Update existing document embeddings
- `get_similar()` - Find similar documents by embedding
- `filter_results()` - Apply advanced filtering to search results

## Usage Examples

### Basic Semantic Search
```python
from ipfs_datasets_py.search import SearchEmbeddings

# Initialize search engine
search_engine = SearchEmbeddings(
    vector_store="qdrant",
    embedding_model="sentence-transformers/all-MiniLM-L6-v2"
)

# Index documents
await search_engine.index_documents(
    documents=document_collection,
    metadata=document_metadata
)

# Perform semantic search
results = await search_engine.search(
    query="machine learning algorithms",
    limit=10,
    filters={"category": "research"}
)

for result in results:
    print(f"Score: {result.score}, Title: {result.metadata['title']}")
```

### Advanced Search with Filtering
```python
# Complex search with multiple filters
results = await search_engine.search(
    query="neural networks deep learning",
    limit=20,
    filters={
        "date_range": {"start": "2020-01-01", "end": "2024-12-31"},
        "authors": ["Smith", "Johnson"],
        "min_score": 0.7
    },
    sort_by="relevance",
    include_metadata=True
)
```

### Hybrid Search (Text + Vector)
```python
# Combine traditional text search with vector similarity
hybrid_results = await search_engine.hybrid_search(
    text_query="artificial intelligence",
    vector_query=query_embedding,
    text_weight=0.3,
    vector_weight=0.7,
    limit=15
)
```

## Configuration

### Search Engine Configuration
```python
search_config = {
    "vector_store": {
        "type": "qdrant",
        "host": "localhost",
        "port": 6333,
        "collection": "documents"
    },
    "embedding": {
        "model": "sentence-transformers/all-MiniLM-L6-v2",
        "device": "cuda",
        "batch_size": 32
    },
    "search": {
        "default_limit": 10,
        "max_limit": 100,
        "similarity_threshold": 0.5
    }
}
```

### Index Configuration
```python
index_config = {
    "chunk_size": 512,
    "overlap": 50,
    "metadata_fields": ["title", "author", "category", "date"],
    "enable_real_time": True,
    "compression": True
}
```

## Advanced Features

### Distributed Search
- Search across multiple IPFS nodes
- Federated search across different collections
- Load balancing and failover capabilities
- Consensus-based result aggregation

### Real-Time Indexing
- Stream processing for continuous document updates
- Incremental index updates
- Change detection and re-indexing
- Performance optimization for high-throughput scenarios

### Analytics and Monitoring
- Search query analytics and logging
- Performance metrics collection
- User behavior analysis
- Index health monitoring

## Search Strategies

### Similarity Metrics
- Cosine similarity (default)
- Euclidean distance
- Dot product similarity
- Custom similarity functions

### Ranking Algorithms
- TF-IDF enhanced vector scoring
- Learning-to-rank models
- Personalization-based ranking
- Time-decay scoring for fresh content

## Integration

The search module integrates with:

- **Vector Stores** - Backend storage for searchable embeddings
- **Embeddings** - Generation of query and document embeddings
- **GraphRAG Module** - Retrieval component for GraphRAG workflows
- **IPFS** - Distributed storage and retrieval
- **PDF Processing** - Search within processed document content

## Dependencies

- `numpy` - Numerical operations and vector calculations
- `asyncio` - Asynchronous search operations
- `sklearn` - Additional similarity metrics and ML utilities
- Vector store clients (qdrant-client, faiss, elasticsearch)

## Performance Considerations

### Optimization Tips
- Use appropriate vector store for your scale and requirements
- Configure batch sizes based on available memory
- Enable caching for frequently accessed results
- Use metadata filtering to reduce search space
- Consider index sharding for very large collections

### Monitoring
- Track query latency and throughput
- Monitor index size and memory usage
- Analyze search result quality metrics
- Set up alerts for performance degradation

## See Also

- [Vector Stores](../vector_stores/README.md) - Backend storage systems
- [Embeddings](../embeddings/README.md) - Embedding generation
- [GraphRAG Optimizers](../optimizers/graphrag/README.md) - Graph-enhanced retrieval
- [IPLD Module](../ipld/README.md) - Content-addressed data structures
- [Performance Optimization](../../docs/performance_optimization.md) - Detailed optimization guide