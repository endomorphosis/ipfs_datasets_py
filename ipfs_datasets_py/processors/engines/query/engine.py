"""Query Engine - Main orchestration facade.

This module provides the main QueryEngine class that orchestrates
query parsing, optimization, execution, and result formatting.

Current implementation: Facade importing from parent query_engine.py
Future: Will contain extracted orchestration logic
"""

from ipfs_datasets_py.processors.query_engine import QueryEngine

__all__ = [
    'QueryEngine',
]
