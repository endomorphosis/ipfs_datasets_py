"""Text Chunking Module.

Provides text chunking strategies for optimal LLM processing.
Handles semantic chunking, size optimization, and overlap management.

Current implementation: Imports from parent llm_optimizer.py
Future: Will contain extracted chunking logic
"""

from ipfs_datasets_py.processors.llm_optimizer import ChunkOptimizer, LLMChunk

__all__ = [
    'ChunkOptimizer',
    'LLMChunk',
]
