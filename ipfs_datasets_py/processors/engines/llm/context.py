"""Context Management Module.

Manages context windows, overlap, and context-aware chunk generation
for optimal LLM processing.

Current implementation: Imports from parent llm_optimizer.py
Future: Will contain extracted context management logic
"""

from ipfs_datasets_py.processors.llm_optimizer import LLMChunkMetadata

__all__ = [
    'LLMChunkMetadata',
]
