"""LLM Optimizer - Main orchestration facade.

This module provides the main LLMOptimizer class that orchestrates
text processing, chunking, embedding generation, and optimization for
LLM consumption.

Current implementation: Facade importing from parent llm_optimizer.py
Future: Will contain extracted orchestration logic
"""

from ipfs_datasets_py.processors.llm_optimizer import (
    LLMOptimizer,
    LLMChunk,
    LLMDocument,
    LLMChunkMetadata,
    LLMDocumentProcessingMetadata,
)

__all__ = [
    'LLMOptimizer',
    'LLMChunk',
    'LLMDocument',
    'LLMChunkMetadata',
    'LLMDocumentProcessingMetadata',
]
