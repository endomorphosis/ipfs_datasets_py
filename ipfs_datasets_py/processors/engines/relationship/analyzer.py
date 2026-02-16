"""Relationship Analyzer Module.

Provides core relationship analysis functionality including
entity relationship extraction, graph construction, and
relationship type classification.

Current implementation: Facade importing from parent relationship_analyzer.py
Future: Will contain extracted core analysis logic

Type Safety:
This module provides full type annotations for all exported classes,
enabling static type checking with mypy and IDE autocomplete support.
"""

from typing import TYPE_CHECKING

from ipfs_datasets_py.processors.relationship_analyzer import RelationshipAnalyzer

__all__ = [
    'RelationshipAnalyzer',
]

# Type annotations for static analysis
if TYPE_CHECKING:
    from typing import Any, Dict, List, Optional, Union
