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

# Import from core module
from .core import (
    IPFSEmbeddings,
    EmbeddingConfig as CoreEmbeddingConfig,
    PerformanceMetrics,
    MemoryMonitor,
    AdaptiveBatchProcessor,
    ipfs_embeddings_py
)

# Import from schema module  
from .schema import (
    BaseComponent,
    DocumentChunk,
    Document,
    EmbeddingResult,
    SearchResult,
    ChunkingStrategy,
    VectorStoreType,
    EmbeddingConfig,
    VectorStoreConfig,
    ImageType,
    DEFAULT_TEXT_NODE_TMPL,
    DEFAULT_METADATA_TMPL,
    TRUNCATE_LENGTH,
    WRAP_WIDTH
)

# Import from chunker module
from .chunker import (
    BaseChunker,
    Chunker,
    FixedSizeChunker,
    SentenceChunker,
    SlidingWindowChunker,
    SemanticChunker,
    chunker,
    CHUNKING_STRATEGIES
)

# Import from create_embeddings module
from .create_embeddings import (
    create_embeddings,
    CreateEmbeddingsProcessor
)

__all__ = [
    # Core functionality
    'IPFSEmbeddings',
    'CoreEmbeddingConfig',
    'PerformanceMetrics',
    'MemoryMonitor', 
    'AdaptiveBatchProcessor',
    'ipfs_embeddings_py',
    
    # Schema classes
    'BaseComponent',
    'DocumentChunk',
    'Document',
    'EmbeddingResult',
    'SearchResult',
    'ChunkingStrategy',
    'VectorStoreType',
    'EmbeddingConfig',
    'VectorStoreConfig',
    'ImageType',
    'DEFAULT_TEXT_NODE_TMPL',
    'DEFAULT_METADATA_TMPL',
    'TRUNCATE_LENGTH',
    'WRAP_WIDTH',
    
    # Chunking functionality
    'BaseChunker',
    'Chunker',
    'FixedSizeChunker',
    'SentenceChunker',
    'SlidingWindowChunker',
    'SemanticChunker',
    'chunker',
    'CHUNKING_STRATEGIES',
    
    # Embedding creation
    'create_embeddings',
    'CreateEmbeddingsProcessor'
]

__version__ = "1.0.0"

