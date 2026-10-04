"""Embedding engines, source-preserving chunkers and schemas.

Optional model engines are loaded on demand so importing a chunker does not
require the Hugging Face datasets SDK, vector stores or model runtimes.
"""
from __future__ import annotations

from importlib import import_module
from typing import Any

_EXPORTS = {
    'IPFSEmbeddings': ('core', 'IPFSEmbeddings'),
    'CoreEmbeddingConfig': ('core', 'EmbeddingConfig'),
    'PerformanceMetrics': ('core', 'PerformanceMetrics'),
    'MemoryMonitor': ('core', 'MemoryMonitor'),
    'AdaptiveBatchProcessor': ('core', 'AdaptiveBatchProcessor'),
    'BaseComponent': ('schema', 'BaseComponent'),
    'DocumentChunk': ('schema', 'DocumentChunk'),
    'Document': ('schema', 'Document'),
    'EmbeddingResult': ('schema', 'EmbeddingResult'),
    'SearchResult': ('schema', 'SearchResult'),
    'ChunkingStrategy': ('schema', 'ChunkingStrategy'),
    'VectorStoreType': ('schema', 'VectorStoreType'),
    'EmbeddingConfig': ('schema', 'EmbeddingConfig'),
    'VectorStoreConfig': ('schema', 'VectorStoreConfig'),
    'ImageType': ('schema', 'ImageType'),
    'DEFAULT_TEXT_NODE_TMPL': ('schema', 'DEFAULT_TEXT_NODE_TMPL'),
    'DEFAULT_METADATA_TMPL': ('schema', 'DEFAULT_METADATA_TMPL'),
    'TRUNCATE_LENGTH': ('schema', 'TRUNCATE_LENGTH'),
    'WRAP_WIDTH': ('schema', 'WRAP_WIDTH'),
    'BaseChunker': ('chunker', 'BaseChunker'),
    'Chunker': ('chunker', 'Chunker'),
    'FixedSizeChunker': ('chunker', 'FixedSizeChunker'),
    'SentenceChunker': ('chunker', 'SentenceChunker'),
    'SlidingWindowChunker': ('chunker', 'SlidingWindowChunker'),
    'SemanticChunker': ('chunker', 'SemanticChunker'),
    'chunker': ('chunker', 'chunker'),
    'CHUNKING_STRATEGIES': ('chunker', 'CHUNKING_STRATEGIES'),
    'create_embeddings': ('create_embeddings', 'create_embeddings'),
    'CreateEmbeddingsProcessor': ('create_embeddings', 'CreateEmbeddingsProcessor'),
}

__all__ = list(_EXPORTS)
__version__ = "1.0.0"


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute = target
    module = import_module(f"{__name__}.{module_name}")
    value = getattr(module, attribute)
    # Importing a submodule sets a same-named package attribute. Restore the
    # documented class aliases alongside the other exports from that module.
    for export, (owner, member) in _EXPORTS.items():
        if owner == module_name:
            globals()[export] = getattr(module, member)
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))


# Keep this historical callable alias stable even after a direct submodule
# import. Chunking itself has no model-engine or Hugging Face SDK imports.
from .chunker import chunker as chunker
