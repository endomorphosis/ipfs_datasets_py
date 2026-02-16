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

Type annotations:
All modules provide full type hints for IDE support and static analysis.
"""

from typing import TYPE_CHECKING

# Re-export main classes for convenience
from ipfs_datasets_py.processors.relationship_analyzer import RelationshipAnalyzer

# Type exports
__all__ = [
    'RelationshipAnalyzer',
]

# Type checking support
if TYPE_CHECKING:
    from typing import Any, Dict, List, Optional, Union
