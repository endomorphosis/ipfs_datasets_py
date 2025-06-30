# IPFS Embeddings Integration - Tool Reference Guide

## Newly Integrated MCP Tool Categories

### 🧠 Embedding Tools
**Location**: `ipfs_datasets_py/mcp_server/tools/embedding_tools/`
- **embedding_generation.py**: Core embedding generation
- **advanced_embedding_generation.py**: Batch and multimodal embeddings
- **advanced_search.py**: Semantic and hybrid search
- **shard_embeddings.py**: Large-scale embedding sharding
- **tool_registration.py**: Automatic tool discovery

### 📊 Analysis Tools
**Location**: `ipfs_datasets_py/mcp_server/tools/analysis_tools/`
- **Clustering**: K-means, DBSCAN, hierarchical clustering
- **Quality Assessment**: Embedding quality metrics
- **Dimensionality Reduction**: PCA, t-SNE, UMAP
- **Similarity Analysis**: Cosine, Euclidean, Manhattan distance
- **Drift Detection**: Embedding drift monitoring

### 🔄 Workflow Tools
**Location**: `ipfs_datasets_py/mcp_server/tools/workflow_tools/`
- **Orchestration**: Multi-step workflow management
- **Batch Processing**: Large dataset processing
- **Pipeline Execution**: Automated data pipelines
- **Task Scheduling**: Background task scheduling

### 👨‍💼 Admin Tools
**Location**: `ipfs_datasets_py/mcp_server/tools/admin_tools/`
- **User Management**: User CRUD operations
- **System Administration**: System configuration
- **Backup Operations**: Data backup and recovery
- **Maintenance**: System maintenance tasks

### 🗃️ Cache Tools
**Location**: `ipfs_datasets_py/mcp_server/tools/cache_tools/`
- **Cache Management**: Cache CRUD operations
- **Operations**: Cache warming, invalidation
- **Statistics**: Cache hit/miss metrics
- **Cleanup**: Automated cache cleanup
- **Configuration**: Cache configuration management

### 📡 Monitoring Tools
**Location**: `ipfs_datasets_py/mcp_server/tools/monitoring_tools/`
- **System Monitoring**: CPU, memory, disk usage
- **Performance Metrics**: Response times, throughput
- **Resource Tracking**: Resource utilization
- **Health Checks**: Service health monitoring

### 🔍 Sparse Embedding Tools
**Location**: `ipfs_datasets_py/mcp_server/tools/sparse_embedding_tools/`
- **SPLADE**: Sparse Lexical And Expansion model
- **BM25**: Best Matching 25 algorithm
- **TF-IDF**: Term Frequency-Inverse Document Frequency
- **Operations**: Sparse vector operations
- **Indexing**: Sparse vector indexing
- **Search**: Sparse vector search

### ⚙️ Background Task Tools
**Location**: `ipfs_datasets_py/mcp_server/tools/background_task_tools/`
- **Task Status**: Background task monitoring
- **Queue Management**: Task queue operations
- **Background Processing**: Long-running task execution
- **Progress Tracking**: Task progress monitoring

### 🔐 Auth Tools
**Location**: `ipfs_datasets_py/mcp_server/tools/auth_tools/`
- **Authentication**: User authentication
- **Authorization**: Permission checking
- **User Management**: User account operations
- **Security**: Security policy enforcement

### 📝 Session Tools
**Location**: `ipfs_datasets_py/mcp_server/tools/session_tools/`
- **Session Management**: User session handling
- **State Tracking**: Session state management
- **User Sessions**: Multi-user session support
- **Persistence**: Session persistence

### 🚦 Rate Limiting Tools
**Location**: `ipfs_datasets_py/mcp_server/tools/rate_limiting_tools/`
- **API Rate Limiting**: Request rate limiting
- **Throttling**: Request throttling
- **Quota Management**: Usage quota tracking
- **Policy Enforcement**: Rate limiting policies

### 🔄 Data Processing Tools
**Location**: `ipfs_datasets_py/mcp_server/tools/data_processing_tools/`
- **Text Chunking**: Text segmentation strategies
- **Preprocessing**: Data preprocessing pipelines
- **Data Transformation**: Data format conversion
- **Validation**: Data quality validation

### 📚 Index Management Tools
**Location**: `ipfs_datasets_py/mcp_server/tools/index_management_tools/`
- **Vector Index Creation**: Index building
- **Loading**: Index loading and initialization
- **Optimization**: Index performance optimization
- **Management**: Index lifecycle management

### 🗂️ Vector Store Tools
**Location**: `ipfs_datasets_py/mcp_server/tools/vector_store_tools/`
- **Vector Database Operations**: CRUD operations
- **Management**: Database configuration
- **Queries**: Vector similarity queries
- **Batch Operations**: Bulk vector operations

### 💾 Storage Tools
**Location**: `ipfs_datasets_py/mcp_server/tools/storage_tools/`
- **Data Storage**: Persistent data storage
- **Retrieval**: Data retrieval operations
- **Management**: Storage lifecycle management
- **Optimization**: Storage performance optimization

### 🌐 Web Archive Tools
**Location**: `ipfs_datasets_py/mcp_server/tools/web_archive_tools/`
- **Web Content Archiving**: Website archiving
- **Retrieval**: Archived content retrieval
- **Management**: Archive management
- **Search**: Archive search capabilities

### 🔗 IPFS Cluster Tools
**Location**: `ipfs_datasets_py/mcp_server/tools/ipfs_cluster_tools/`
- **IPFS Cluster Management**: Cluster operations
- **Node Management**: Cluster node administration
- **Operations**: Cluster maintenance tasks
- **Monitoring**: Cluster health monitoring

## Core Module Integration

### 🧠 Embeddings Module
**Location**: `ipfs_datasets_py/embeddings/`
- **core.py**: Core embedding generation logic
- **schema.py**: Data models and schemas
- **chunker.py**: Text chunking utilities
- **__init__.py**: Module exports and feature flags

### 🗄️ Vector Stores Module
**Location**: `ipfs_datasets_py/vector_stores/`
- **base.py**: Abstract base class for vector stores
- **qdrant_store.py**: Qdrant vector store implementation
- **elasticsearch_store.py**: Elasticsearch vector store implementation
- **faiss_store.py**: FAISS vector store implementation
- **__init__.py**: Module exports

## Usage Examples

### Basic Embedding Generation
```python
from ipfs_datasets_py.embeddings import generate_embeddings
from ipfs_datasets_py.mcp_server.tools.embedding_tools import embedding_generation

# Generate embeddings for text
embeddings = await embedding_generation.generate_embeddings({
    "text": "Your text here",
    "model": "sentence-transformers/all-MiniLM-L6-v2"
})
```

### Vector Store Operations
```python
from ipfs_datasets_py.vector_stores import QdrantVectorStore

# Initialize vector store
store = QdrantVectorStore(
    url="http://localhost:6333",
    collection_name="my_collection"
)

# Search for similar vectors
results = await store.search(query_vector, top_k=10)
```

### Advanced Search
```python
from ipfs_datasets_py.mcp_server.tools.embedding_tools import advanced_search

# Perform hybrid search
results = await advanced_search.hybrid_search({
    "query": "search query",
    "search_type": "hybrid",
    "vector_weight": 0.7,
    "text_weight": 0.3
})
```

## Feature Flags

The integration includes feature flags for optional functionality:

```python
from ipfs_datasets_py import (
    EMBEDDINGS_ENABLED,
    VECTOR_STORES_ENABLED, 
    MCP_TOOLS_ENABLED
)

# Check if features are available
if EMBEDDINGS_ENABLED:
    # Use embedding features
    pass

if VECTOR_STORES_ENABLED:
    # Use vector store features
    pass
```

## Next Steps

1. **Test Integration**: Run comprehensive validation tests
2. **FastAPI Integration**: Implement REST API layer
3. **Authentication**: Set up JWT-based authentication
4. **Performance Optimization**: Optimize embedding and search operations
5. **Production Deployment**: Deploy with proper monitoring and logging

## Support

For questions or issues with the integrated tools:
- Check the migration documentation in `IPFS_EMBEDDINGS_MIGRATION_PLAN.md`
- Review tool mapping in `IPFS_EMBEDDINGS_TOOL_MAPPING.md`
- Run validation tests with `comprehensive_validation.py`
