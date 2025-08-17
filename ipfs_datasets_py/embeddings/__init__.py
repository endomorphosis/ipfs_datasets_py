"""
IPFS Datasets Embeddings Module

Provides comprehensive embedding generation, chunking, and schema functionality
migrated from the ipfs_embeddings_py project.

This module includes:
- Core embedding generation and management
- Text chunking strategies and utilities
- Data schemas for embeddings and vector operations
- Integration with multiple vector stores
"""

from .core import (
    EmbeddingCore, 
    generate_embeddings,
    create_embedding_instance,
    get_available_models
)

from .schema import (
    EmbeddingRequest,
    EmbeddingResponse,
    ChunkingStrategy,
    VectorSearchRequest,
    VectorSearchResponse,
    SimilarityMetric
)

from .chunker import (
    TextChunker,
    FixedSizeChunker,
    SentenceChunker,
    SemanticChunker,
    ChunkingConfig,
    chunk_text,
    create_chunker
)

__all__ = [
    # Core functionality
    'EmbeddingCore',
    'generate_embeddings',
    'create_embedding_instance',  
    'get_available_models',
    
    # Schema classes
    'EmbeddingRequest',
    'EmbeddingResponse', 
    'ChunkingStrategy',
    'VectorSearchRequest',
    'VectorSearchResponse',
    'SimilarityMetric',
    
    # Chunking functionality
    'TextChunker',
    'FixedSizeChunker',
    'SentenceChunker', 
    'SemanticChunker',
    'ChunkingConfig',
    'chunk_text',
    'create_chunker'
]

__version__ = "1.0.0"