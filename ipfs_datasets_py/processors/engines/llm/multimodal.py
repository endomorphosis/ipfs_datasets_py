"""Multi-modal Content Handling Module.

Handles multi-modal content processing including text, images,
and other media types for LLM consumption.

Current implementation: Imports from parent llm_optimizer.py
Future: Will contain extracted multi-modal logic
"""

from ipfs_datasets_py.processors.llm_optimizer import TextProcessor

__all__ = [
    'TextProcessor',
]
