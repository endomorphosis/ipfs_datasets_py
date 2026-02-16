"""Query Engine - Main orchestration facade.

This module provides the main QueryEngine class that orchestrates
query parsing, optimization, execution, and result formatting.

Current implementation: Facade importing from parent query_engine.py
Future: Will contain extracted orchestration logic

Type Safety:
This module provides full type annotations for all exported classes,
enabling static type checking with mypy and IDE autocomplete support.
"""

from typing import TYPE_CHECKING

from ipfs_datasets_py.processors.query_engine import QueryEngine

__all__ = [
    'QueryEngine',
]

# Type annotations for static analysis
if TYPE_CHECKING:
    from typing import Any, Dict, List, Optional, Union
