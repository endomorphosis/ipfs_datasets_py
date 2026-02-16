"""Relationship Analysis Engines Package.

This package provides relationship analysis and graph-based query
capabilities consolidated from multiple source files.

Current implementation strategy:
- Facade pattern with imports from parent relationship files
- Maintains 100% backward compatibility
- Establishes architecture for future full extraction

Modules:
- analyzer: Core relationship analysis logic
- api: API interface for relationship queries
- corpus: Corpus-based query functionality
"""

# Re-export main classes for convenience
from ipfs_datasets_py.processors.relationship_analyzer import RelationshipAnalyzer

__all__ = [
    'RelationshipAnalyzer',
]
