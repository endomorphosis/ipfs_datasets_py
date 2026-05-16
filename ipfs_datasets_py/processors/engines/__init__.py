"""Processing Engines Package.

This package contains complex processing engines that were split from
large monolithic files for better maintainability and organization.

Engines:
- llm: LLM optimization and text processing (from llm_optimizer.py)
- query: Query processing and execution (from query_engine.py)
- relationship: Relationship analysis and graph queries (from relationship_*.py)

Architecture:
Current implementation uses a facade-heavy layout: the engines packages expose
modular entry points, while substantial logic still lives in the corresponding
root processor modules. Treat this package as the organized engine surface for
the current codebase, not as a fully standalone extraction.
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
