# Embeddings - Comprehensive Embedding Generation and Management

This module provides complete embedding generation, chunking, and schema functionality for the IPFS Datasets Python library.

## Overview

The embeddings module offers a unified interface for generating, managing, and processing text embeddings using various models and strategies. It includes sophisticated chunking algorithms, embedding schemas, and integration with multiple vector stores.

## Components

### EmbeddingCore (`core.py`)
Core embedding generation engine with support for multiple models and backends.

**Key Features:**
- Multi-model embedding generation (OpenAI, HuggingFace, local models)
- Batch processing for efficiency
- Automatic model selection and optimization
- Error handling and retry mechanisms
- Memory-efficient processing for large datasets

**Main Functions:**
- `generate_embeddings()` - Generate embeddings for text or documents
- `create_embedding_instance()` - Factory function for embedding instances
- `get_available_models()` - List supported embedding models

### TextChunker (`chunker.py`)
Advanced text chunking with multiple strategies for optimal embedding generation.

**Chunking Strategies:**
- `FixedSizeChunker` - Fixed character/token length chunks
- `SentenceChunker` - Sentence-boundary aware chunking
- `SemanticChunker` - Semantic similarity-based chunking
- `TextChunker` - Configurable base chunker

**Key Features:**
- Overlap management for context preservation
- Dynamic chunk size adjustment
- Quality metrics for chunk evaluation
- Memory-efficient streaming processing

### Schema Definitions (`schema.py`)
Comprehensive data schemas for embedding operations and vector search.

**Schema Classes:**
- `EmbeddingRequest` - Request format for embedding generation
- `EmbeddingResponse` - Standardized embedding response format
- `ChunkingStrategy` - Configuration for chunking operations
- `VectorSearchRequest` - Vector search query format
- `VectorSearchResponse` - Search result format
- `SimilarityMetric` - Supported similarity metrics

## Usage Examples

### Basic Embedding Generation
```python
from ipfs_datasets_py.embeddings import generate_embeddings, EmbeddingRequest

# Generate embeddings for text
request = EmbeddingRequest(
    texts=["Your text here", "Another document"],
    model="sentence-transformers/all-MiniLM-L6-v2",
    chunk_size=512
)

embeddings = await generate_embeddings(request)
print(f"Generated {len(embeddings.vectors)} embeddings")
```

### Advanced Chunking
```python
from ipfs_datasets_py.embeddings import SemanticChunker, ChunkingConfig

# Configure semantic chunking
config = ChunkingConfig(
    max_chunk_size=512,
    overlap_size=50,
    similarity_threshold=0.8
)

chunker = SemanticChunker(config)
chunks = chunker.chunk_text(long_document)
```

### Schema-Based Operations
```python
from ipfs_datasets_py.embeddings import VectorSearchRequest, SimilarityMetric

# Structured vector search
search_request = VectorSearchRequest(
    query_vector=query_embedding,
    limit=10,
    similarity_metric=SimilarityMetric.COSINE,
    filters={"category": "research"}
)
```

## Configuration

### Model Configuration
```python
embedding_config = {
    "model_name": "sentence-transformers/all-MiniLM-L6-v2",
    "device": "cuda",  # or "cpu"
    "batch_size": 32,
    "max_length": 512
}
```

### Chunking Configuration
```python
chunking_config = {
    "strategy": "semantic",
    "max_size": 512,
    "overlap": 50,
    "preserve_sentences": True
}
```

## Supported Models

### HuggingFace Models
- Sentence Transformers (all-MiniLM, all-mpnet-base)
- BERT variants (bert-base, distilbert)
- Custom fine-tuned models

### OpenAI Models
- text-embedding-ada-002
- text-embedding-3-small
- text-embedding-3-large

### Local Models
- Support for locally hosted embedding models
- Custom model integration capabilities

## Performance Optimization

### Batch Processing
- Automatic batch size optimization
- Memory-aware batch sizing
- GPU utilization optimization

### Chunking Optimization
- Intelligent chunk size selection
- Context preservation strategies
- Memory-efficient streaming

### Caching
- Model caching for repeated operations
- Embedding result caching
- Chunk reuse optimization

## Integration

The embeddings module integrates with:

- **Vector Stores** - Direct storage of generated embeddings
- **Search Module** - Embedding-based search capabilities
- **RAG Module** - Retrieval-augmented generation workflows
- **PDF Processing** - Embedding of extracted document content
- **IPLD Module** - Content-addressed embedding storage

## Dependencies

- `transformers` - HuggingFace model support
- `torch` - PyTorch backend
- `sentence-transformers` - Specialized embedding models
- `numpy` - Numerical operations
- `asyncio` - Asynchronous operations

## See Also

- [Vector Stores](../vector_stores/README.md) - Storage backends for embeddings
- [Search Module](../search/README.md) - Search and retrieval using embeddings
- [RAG Module](../rag/README.md) - Retrieval-augmented generation
- [Utils Module](../utils/README.md) - Text processing utilities
- [Performance Guide](../../docs/performance_optimization.md) - Optimization strategies