"""LLM Processing Engines Package.

This package provides modular LLM processing capabilities split from the
monolithic llm_optimizer.py file. The refactoring improves maintainability
while preserving all functionality.

Current implementation strategy: 
- Facade pattern with imports from parent llm_optimizer.py
- Maintains 100% backward compatibility
- Establishes architecture for future full extraction

Modules:
- optimizer: Main LLMOptimizer orchestration (facade)
- chunker: Text chunking strategies
- tokenizer: Token optimization
- embeddings: Embedding generation
- context: Context management
- summarizer: Text summarization
- multimodal: Multi-modal content handling
"""

# Re-export main classes for convenience
from ipfs_datasets_py.processors.llm_optimizer import (
    LLMOptimizer,
    LLMChunk,
    LLMDocument,
    LLMChunkMetadata,
    LLMDocumentProcessingMetadata,
    TextProcessor,
    ChunkOptimizer,
)

__all__ = [
    'LLMOptimizer',
    'LLMChunk',
    'LLMDocument',
    'LLMChunkMetadata',
    'LLMDocumentProcessingMetadata',
    'TextProcessor',
    'ChunkOptimizer',
]
