"""
Knowledge Graph Indexing

This module provides indexing capabilities for fast queries.
"""

from .types import IndexType, IndexDefinition, IndexEntry, IndexStats
from .btree import BTreeIndex, PropertyIndex, LabelIndex, CompositeIndex
from .specialized import FullTextIndex, SpatialIndex, VectorIndex, RangeIndex
from .manager import IndexManager

__all__ = [
    # Types
    "IndexType",
    "IndexDefinition",
    "IndexEntry",
    "IndexStats",
    # B-tree indexes
    "BTreeIndex",
    "PropertyIndex",
    "LabelIndex",
    "CompositeIndex",
    # Specialized indexes
    "FullTextIndex",
    "SpatialIndex",
    "VectorIndex",
    "RangeIndex",
    # Manager
    "IndexManager",
]

__version__ = "1.0.0"
__status__ = "stable"
