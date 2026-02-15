"""
Graph Types for IPLD Storage

Provides Entity and Relationship classes for representing graph data
that will be stored in IPLD format.

These classes are extracted from the legacy ipld.py module and made
compatible with both the new Neo4j-compatible API and the existing
IPLDKnowledgeGraph system.
"""

import uuid
from typing import Dict, List, Any, Optional, Union


# Type aliases for clarity
EntityID = str
RelationshipID = str


class Entity:
    """
    Represents an entity (node) in a knowledge graph.

    Entities are nodes in the knowledge graph with a type, name,
    and optional properties. They map to Neo4j Node objects.

    Attributes:
        id: Unique identifier for the entity
        type: Type/label of the entity (e.g., "Person", "Company")
        name: Human-readable name of the entity
        properties: Additional properties as key-value pairs
        confidence: Confidence score for the entity (0.0 to 1.0)
        source_text: Optional source text from which entity was extracted
        cid: Content identifier when stored in IPLD (set by storage layer)

    Examples:
        >>> entity = Entity(
        ...     entity_type="Person",
        ...     name="Alice",
        ...     properties={"age": 30, "city": "SF"}
        ... )
        >>> print(entity)
        Entity(id=..., type=Person, name=Alice)
    """

    def __init__(
        self,
        entity_id: Optional[EntityID] = None,
        entity_type: str = "entity",
        name: str = "",
        properties: Optional[Dict[str, Any]] = None,
        confidence: float = 1.0,
        source_text: Optional[str] = None
    ):
        """
        Initialize an entity.

        Args:
            entity_id: Optional ID for the entity (auto-generated if None)
            entity_type: Type/label of the entity
            name: Name of the entity
            properties: Optional properties for the entity
            confidence: Confidence score for the entity (0.0 to 1.0)
            source_text: Optional source text from which entity was extracted
        """
        self.id = entity_id or str(uuid.uuid4())
        self.type = entity_type
        self.name = name
        self.properties = properties or {}
        self.confidence = confidence
        self.source_text = source_text
        self.cid: Optional[str] = None  # Will be set when stored in IPLD

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert entity to dictionary representation.

        Returns:
            Dictionary with all entity fields
        """
        return {
            "id": self.id,
            "type": self.type,
            "name": self.name,
            "properties": self.properties,
            "confidence": self.confidence,
            "source_text": self.source_text
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Entity':
        """
        Create entity from dictionary representation.

        Args:
            data: Dictionary with entity fields

        Returns:
            Entity instance
        """
        entity = cls(
            entity_id=data.get("id"),
            entity_type=data.get("type", "entity"),
            name=data.get("name", ""),
            properties=data.get("properties", {}),
            confidence=data.get("confidence", 1.0),
            source_text=data.get("source_text")
        )
        entity.cid = data.get("cid")
        return entity

    def __str__(self) -> str:
        """Get string representation of the entity."""
        return f"Entity(id={self.id}, type={self.type}, name={self.name})"

    def __repr__(self) -> str:
        """Get detailed representation of the entity."""
        return (
            f"Entity(id={self.id!r}, type={self.type!r}, name={self.name!r}, "
            f"properties={self.properties!r}, confidence={self.confidence})"
        )

    def __eq__(self, other) -> bool:
        """Check equality based on entity ID."""
        if not isinstance(other, Entity):
            return False
        return self.id == other.id

    def __hash__(self) -> int:
        """Hash based on entity ID."""
        return hash(self.id)


class Relationship:
    """
    Represents a relationship (edge) between entities in a knowledge graph.

    Relationships are directed edges in the knowledge graph connecting
    entities with a specific relationship type and optional properties.
    They map to Neo4j Relationship objects.

    Attributes:
        id: Unique identifier for the relationship
        type: Type of the relationship (e.g., "KNOWS", "WORKS_AT")
        source_id: ID of the source entity
        target_id: ID of the target entity
        properties: Additional properties as key-value pairs
        confidence: Confidence score for the relationship (0.0 to 1.0)
        source_text: Optional source text from which relationship was extracted
        cid: Content identifier when stored in IPLD (set by storage layer)

    Examples:
        >>> rel = Relationship(
        ...     relationship_type="KNOWS",
        ...     source="person-1",
        ...     target="person-2",
        ...     properties={"since": 2020}
        ... )
        >>> print(rel)
        Relationship(id=..., type=KNOWS, source=person-1, target=person-2)
    """

    def __init__(
        self,
        relationship_id: Optional[RelationshipID] = None,
        relationship_type: str = "related_to",
        source: Union['Entity', EntityID, None] = None,
        target: Union['Entity', EntityID, None] = None,
        properties: Optional[Dict[str, Any]] = None,
        confidence: float = 1.0,
        source_text: Optional[str] = None
    ):
        """
        Initialize a relationship.

        Args:
            relationship_id: Optional ID for the relationship (auto-generated if None)
            relationship_type: Type of the relationship
            source: Source entity or entity ID
            target: Target entity or entity ID
            properties: Optional properties for the relationship
            confidence: Confidence score for the relationship (0.0 to 1.0)
            source_text: Optional source text from which relationship was extracted
        """
        self.id = relationship_id or str(uuid.uuid4())
        self.type = relationship_type

        # Extract entity IDs if entities are provided
        if isinstance(source, Entity):
            self.source_id = source.id
        else:
            self.source_id = source

        if isinstance(target, Entity):
            self.target_id = target.id
        else:
            self.target_id = target

        self.properties = properties or {}
        self.confidence = confidence
        self.source_text = source_text
        self.cid: Optional[str] = None  # Will be set when stored in IPLD

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert relationship to dictionary representation.

        Returns:
            Dictionary with all relationship fields
        """
        return {
            "id": self.id,
            "type": self.type,
            "source_id": self.source_id,
            "target_id": self.target_id,
            "properties": self.properties,
            "confidence": self.confidence,
            "source_text": self.source_text
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Relationship':
        """
        Create relationship from dictionary representation.

        Args:
            data: Dictionary with relationship fields

        Returns:
            Relationship instance
        """
        relationship = cls(
            relationship_id=data.get("id"),
            relationship_type=data.get("type", "related_to"),
            source=data.get("source_id"),
            target=data.get("target_id"),
            properties=data.get("properties", {}),
            confidence=data.get("confidence", 1.0),
            source_text=data.get("source_text")
        )
        relationship.cid = data.get("cid")
        return relationship

    def __str__(self) -> str:
        """Get string representation of the relationship."""
        return (
            f"Relationship(id={self.id}, type={self.type}, "
            f"source={self.source_id}, target={self.target_id})"
        )

    def __repr__(self) -> str:
        """Get detailed representation of the relationship."""
        return (
            f"Relationship(id={self.id!r}, type={self.type!r}, "
            f"source_id={self.source_id!r}, target_id={self.target_id!r}, "
            f"properties={self.properties!r}, confidence={self.confidence})"
        )

    def __eq__(self, other) -> bool:
        """Check equality based on relationship ID."""
        if not isinstance(other, Relationship):
            return False
        return self.id == other.id

    def __hash__(self) -> int:
        """Hash based on relationship ID."""
        return hash(self.id)


# Convenience functions for type checking
def is_entity(obj: Any) -> bool:
    """Check if an object is an Entity instance."""
    return isinstance(obj, Entity)


def is_relationship(obj: Any) -> bool:
    """Check if an object is a Relationship instance."""
    return isinstance(obj, Relationship)
