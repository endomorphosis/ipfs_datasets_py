"""
Indexing Types for Knowledge Graphs

This module defines the core types for indexing functionality.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class IndexType(Enum):
    """Types of indexes."""
    PROPERTY = "property"  # Index on entity properties
    LABEL = "label"  # Index on entity types/labels
    COMPOSITE = "composite"  # Index on multiple properties
    FULLTEXT = "fulltext"  # Full-text search index
    SPATIAL = "spatial"  # Geospatial index
    VECTOR = "vector"  # Vector/embedding index
    RANGE = "range"  # Range-based index


@dataclass
class IndexDefinition:
    """
    Definition of an index.
    
    Attributes:
        name: Unique name for the index
        index_type: Type of index
        properties: Properties to index
        label: Optional label/type filter
        options: Index-specific options
    """
    name: str
    index_type: IndexType
    properties: List[str] = field(default_factory=list)
    label: Optional[str] = None
    options: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "name": self.name,
            "index_type": self.index_type.value,
            "properties": self.properties,
            "label": self.label,
            "options": self.options
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IndexDefinition":
        """Create from dictionary representation."""
        return cls(
            name=data["name"],
            index_type=IndexType(data["index_type"]),
            properties=data.get("properties", []),
            label=data.get("label"),
            options=data.get("options", {})
        )


@dataclass
class IndexEntry:
    """
    A single entry in an index.
    
    Attributes:
        key: Index key (value being indexed)
        entity_id: ID of the entity
        metadata: Optional metadata about the entry
    """
    key: Any
    entity_id: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __hash__(self):
        """Make hashable for set operations."""
        # Convert key to hashable form
        if isinstance(self.key, (list, dict)):
            key_hash = str(self.key)
        else:
            key_hash = self.key
        return hash((key_hash, self.entity_id))
    
    def __eq__(self, other):
        """Equality comparison."""
        if not isinstance(other, IndexEntry):
            return False
        return self.key == other.key and self.entity_id == other.entity_id


@dataclass
class IndexStats:
    """
    Statistics about an index.
    
    Attributes:
        name: Index name
        entry_count: Number of entries
        unique_keys: Number of unique keys
        memory_bytes: Estimated memory usage
        last_updated: Last update timestamp
    """
    name: str
    entry_count: int = 0
    unique_keys: int = 0
    memory_bytes: int = 0
    last_updated: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "name": self.name,
            "entry_count": self.entry_count,
            "unique_keys": self.unique_keys,
            "memory_bytes": self.memory_bytes,
            "last_updated": self.last_updated
        }


# Export types
__all__ = [
    "IndexType",
    "IndexDefinition",
    "IndexEntry",
    "IndexStats",
]
