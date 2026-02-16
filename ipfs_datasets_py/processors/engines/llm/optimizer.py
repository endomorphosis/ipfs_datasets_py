"""LLM Optimizer - Main orchestration facade.

This module provides the main LLMOptimizer class that orchestrates
text processing, chunking, embedding generation, and optimization for
LLM consumption.

Current implementation: Facade importing from parent llm_optimizer.py
Future: Will contain extracted orchestration logic

Type Safety:
This module provides full type annotations for all exported classes,
enabling static type checking with mypy and IDE autocomplete support.
"""

from typing import TYPE_CHECKING

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

# Type annotations for static analysis
if TYPE_CHECKING:
    from typing import Any, Dict, List, Optional, Union
