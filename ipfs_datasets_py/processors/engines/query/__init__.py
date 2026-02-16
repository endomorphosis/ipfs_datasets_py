"""Query Processing Engines Package.

This package provides modular query processing capabilities split from the
monolithic query_engine.py file. The refactoring improves maintainability
while preserving all functionality.

Current implementation strategy:
- Facade pattern with imports from parent query_engine.py
- Maintains 100% backward compatibility
- Establishes architecture for future full extraction

Modules:
- engine: Main QueryEngine orchestration (facade)
- parser: Query parsing and analysis
- optimizer: Query optimization
- executor: Query execution engine
- formatter: Result formatting
- cache: Query caching

Type annotations:
All modules provide full type hints for IDE support and static analysis.
"""

from typing import TYPE_CHECKING

# Re-export main classes for convenience
from ipfs_datasets_py.processors.query_engine import QueryEngine

# Type exports
__all__ = [
    'QueryEngine',
]

# Type checking support
if TYPE_CHECKING:
    from typing import Any, Dict, List, Optional, Union
