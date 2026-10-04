# Search Module Architecture

## Overview

The search module provides embedding-based search functionality for the IPFS Datasets Python library. It serves as a high-level interface for searching through datasets using vector embeddings with support for both Qdrant and FAISS backends.

## Core Components

### search_embeddings.py

The main class that orchestrates embedding generation and vector search operations.

#### Key Responsibilities:
- **Embedding Generation**: Generate embeddings for queries using various models
- **Vector Search**: Perform similarity search using Qdrant or FAISS backends
- **Backend Management**: Automatically detect and switch between Qdrant and FAISS
- **Resource Management**: Handle different endpoint types (local, OpenVINO, TEI)
- **Testing Framework**: Provide memory-based testing capabilities

## Architecture Patterns

### 1. Backend Abstraction
```
search_embeddings class
├── Qdrant Integration (primary)
│   ├── start_qdrant()
│   ├── load_qdrant_iter()
│   └── ingest_qdrant_iter()
└── FAISS Fallback (secondary)
    ├── start_faiss()
    ├── load_faiss()
    └── search_faiss()
```

### 2. Delegation Pattern
The class delegates most operations to underlying services:
- **ipfs_kit**: Handles IPFS operations and FAISS backend
- **qdrant_kit_py**: Manages Qdrant vector database operations

### 3. Async/Await Architecture
All search operations are asynchronous to handle:
- Large dataset processing
- Network operations (TEI endpoints)
- Concurrent embedding generation

## Data Flow

### Search Process:
1. **Query Input** → Query validation and normalization
2. **Embedding Generation** → Transform query to vector embeddings
3. **Backend Selection** → Choose Qdrant (preferred) or FAISS (fallback)
4. **Vector Search** → Perform similarity search
5. **Result Return** → Return ranked search results

### Initialization Process:
1. **Resource Configuration** → Load endpoint configurations
2. **Metadata Setup** → Configure models and dataset parameters
3. **Backend Detection** → Check Qdrant availability (port 6333)
4. **Fallback Setup** → Initialize FAISS if Qdrant unavailable

## Configuration

### Supported Endpoints:
- **Local Endpoints**: CPU, CUDA, OpenVINO, LlamaCPP, IPEX
- **OpenVINO Endpoints**: Remote OpenVINO model servers
- **TEI Endpoints**: Text Embedding Inference servers

### Supported Models:
- thenlper/gte-small
- Alibaba-NLP/gte-large-en-v1.5
- Alibaba-NLP/gte-Qwen2-1.5B-instruct

## Error Handling Strategy

### 1. Graceful Degradation
- Qdrant unavailable → Fallback to FAISS
- Remote endpoints unreachable → Use local endpoints
- Model loading failure → Try alternative models

### 2. Input Validation
- Query type checking (string/list)
- Parameter validation for all methods
- Resource availability verification

### 3. Resource Management
- Automatic cache cleanup (rm_cache method)
- Memory-efficient processing options
- Configurable batch sizes

## Testing Architecture

### Memory Testing Modes:
- **Low Memory Mode**: Processes datasets in pairs, suitable for resource-constrained environments
- **High Memory Mode**: Loads full datasets for comprehensive testing
- **Query Testing**: Validates search functionality with sample queries

### Test Coverage:
- Backend switching (Qdrant ↔ FAISS)
- Embedding generation
- Search accuracy
- Resource utilization

## Dependencies

### External Dependencies:
- **ipfs_kit_py**: IPFS operations and FAISS backend
- **qdrant_kit_py**: Qdrant vector database (commented out - integration pending)
- **datasets**: HuggingFace datasets library
- **asyncio**: Asynchronous programming support

### System Dependencies:
- Qdrant server (optional, port 6333)
- Network connectivity for remote endpoints
- Sufficient memory for embedding models

## Performance Considerations

### Optimization Strategies:
1. **Endpoint Selection**: Automatically choose fastest available endpoint
2. **Batch Processing**: Process multiple queries efficiently
3. **Caching**: Minimize redundant embedding computations
4. **Async Operations**: Prevent blocking on I/O operations

### Scalability Features:
- Multiple endpoint support for load distribution
- Memory-efficient dataset iteration
- Configurable search result limits
- Resource pooling capabilities

## Future Enhancements

### Planned Improvements:
1. **Full Qdrant Integration**: Complete qdrant_kit_py integration
2. **Advanced Caching**: Persistent embedding cache
3. **Model Management**: Dynamic model loading/unloading
4. **Monitoring**: Performance metrics and health checks
5. **Configuration**: External configuration file support

### Extension Points:
- Additional vector database backends
- Custom embedding models
- Advanced search algorithms
- Result post-processing pipelines