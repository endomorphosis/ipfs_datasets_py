# Vector Stores - Multi-Backend Vector Database Support

This module provides comprehensive vector database implementations for storing and searching embeddings in the IPFS Datasets Python library.

## Overview

The vector_stores module offers unified interfaces and implementations for multiple vector database backends, enabling efficient storage, indexing, and similarity search of high-dimensional embeddings.

## Supported Vector Stores

### QdrantVectorStore (`qdrant_store.py`)
High-performance vector search engine optimized for production deployments.

**Features:**
- Native support for filtering and metadata
- Distributed clustering capabilities
- Real-time indexing and search
- Advanced query optimization
- Automatic index management

### FAISSVectorStore (`faiss_store.py`)
Facebook AI Similarity Search - optimized for speed and memory efficiency.

**Features:**
- Multiple index types (Flat, IVF, HNSW)
- GPU acceleration support
- Quantization for memory optimization
- Batch operations for large datasets
- Index serialization and persistence

### ElasticsearchVectorStore (`elasticsearch_store.py`)
Enterprise-grade search with vector capabilities.

**Features:**
- Full-text and vector hybrid search
- Advanced filtering and aggregations
- Scalable cluster support
- Rich query DSL
- Real-time analytics

### BaseVectorStore (`base.py`)
Abstract base class defining the common interface for all vector stores.

**Interface Methods:**
- `add_vectors()` - Store vectors with metadata
- `search()` - Similarity search with filtering
- `delete()` - Remove vectors by ID
- `update()` - Update vector metadata
- `get_stats()` - Retrieve store statistics

## Usage Examples

### Basic Vector Storage
```python
from ipfs_datasets_py.vector_stores import QdrantVectorStore

# Initialize store
store = QdrantVectorStore(
    host="localhost",
    port=6333,
    collection_name="documents"
)

# Add vectors
await store.add_vectors(
    vectors=embeddings,
    metadata=document_metadata,
    ids=document_ids
)

# Search for similar vectors
results = await store.search(
    query_vector=query_embedding,
    limit=10,
    filter_conditions={"category": "research"}
)
```

### Multi-Store Configuration
```python
from ipfs_datasets_py.vector_stores import FAISSVectorStore, QdrantVectorStore

# Configure multiple stores for different use cases
fast_store = FAISSVectorStore(index_type="Flat")  # Speed optimized
production_store = QdrantVectorStore()  # Feature rich
```

### Hybrid Search (Elasticsearch)
```python
from ipfs_datasets_py.vector_stores import ElasticsearchVectorStore

store = ElasticsearchVectorStore(
    hosts=["localhost:9200"],
    index_name="hybrid_search"
)

# Combine text and vector search
results = await store.hybrid_search(
    query_text="machine learning",
    query_vector=embedding,
    text_weight=0.3,
    vector_weight=0.7
)
```

## Configuration

Each vector store supports extensive configuration options:

### Common Parameters
- **Connection settings** - Host, port, authentication
- **Index configuration** - Dimension, metric, parameters
- **Performance tuning** - Batch size, timeouts, retries
- **Security settings** - SSL, authentication, access control

### Store-Specific Options
- **Qdrant**: Collection settings, payload indexing, quantization
- **FAISS**: Index type, training parameters, GPU settings
- **Elasticsearch**: Mapping configuration, analyzer settings, cluster options

## Performance Considerations

### Choosing the Right Store
- **FAISS**: Best for read-heavy workloads, local deployments
- **Qdrant**: Optimal for production with metadata filtering
- **Elasticsearch**: Ideal for hybrid text/vector search scenarios

### Optimization Tips
- Use appropriate index types for your data size and query patterns
- Configure batch sizes based on available memory
- Enable quantization for large-scale deployments
- Implement connection pooling for high-throughput scenarios

## Integration

The vector stores integrate with other IPFS Datasets components:

- **Embeddings module** - Stores generated embeddings
- **Search module** - Provides search backend capabilities  
- **RAG module** - Supports retrieval operations
- **IPLD module** - Content-addressed vector storage

## Dependencies

- `qdrant-client` - Qdrant vector database client
- `faiss-cpu` or `faiss-gpu` - FAISS similarity search
- `elasticsearch` - Elasticsearch client (optional)
- `numpy` - Numerical operations
- `asyncio` - Asynchronous operations

## See Also

- [Embeddings Module](../embeddings/README.md) - Generate embeddings for storage
- [Search Module](../search/README.md) - Search and retrieval operations
- [RAG Module](../rag/README.md) - Retrieval-augmented generation
- [Performance Optimization Guide](../../docs/performance_optimization.md) - Detailed optimization strategies