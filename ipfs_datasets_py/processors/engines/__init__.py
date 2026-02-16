"""Processing Engines Package.

This package contains complex processing engines that were split from
large monolithic files for better maintainability and organization.

Engines:
- llm: LLM optimization and text processing (from llm_optimizer.py)
- query: Query processing and execution (from query_engine.py)
- relationship: Relationship analysis and graph queries (from relationship_*.py)

Architecture:
Current implementation uses facade pattern with imports from parent files,
maintaining 100% backward compatibility while establishing modular structure
for future full extraction of functionality.
"""

# Import subpackages to make them accessible as attributes
from . import llm
from . import query
from . import relationship

__all__ = [
    'llm',
    'query',
    'relationship',
]
