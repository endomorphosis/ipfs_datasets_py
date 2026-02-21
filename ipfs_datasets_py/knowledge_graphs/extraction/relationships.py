"""
Relationship Module

This module provides the Relationship class for representing edges in a knowledge graph.

Classes:
    Relationship: Represents a directed relationship between two entities
"""

import uuid
from dataclasses import dataclass, field
from typing import Dict, Any, Optional

from .types import RelationshipID, RelationshipType, DEFAULT_CONFIDENCE
from .entities import Entity


@dataclass
class Relationship:
    """Represents a relationship between entities in a knowledge graph.

    Relationships are directed edges in the knowledge graph with a type,
    source and target entities, and optional properties.

    Attributes:
        relationship_id (str): Unique identifier for the relationship
        relationship_type (str): Type of the relationship
        source_entity (Entity): Source entity (head)
        target_entity (Entity): Target entity (tail)
        properties (Dict, optional): Additional properties of the relationship
        confidence (float): Confidence score (0.0 to 1.0)
        source_text (str, optional): Source text from which the relationship was extracted
        bidirectional (bool): Whether the relationship is bidirectional

    Methods:
        create(source, target, relationship_type, **kwargs) -> 'Relationship':
            Factory method for intuitive relationship creation.
        to_dict(include_entities: bool = True) -> Dict[str, Any]:
            Convert the relationship to a dictionary representation.
        from_dict(data: Dict[str, Any], entity_map: Dict[str, Entity] = None) -> 'Relationship':
            Create a relationship from a dictionary representation.
    
    Properties:
        source_id: ID of the source entity
        target_id: ID of the target entity
    
    Examples:
        >>> person = Entity(entity_type="person", name="Alice")
        >>> org = Entity(entity_type="organization", name="ACME Corp")
        >>> rel = Relationship.create(person, org, "works_at")
        >>> rel.relationship_type
        'works_at'
        >>> rel.source_id == person.entity_id
        True
    """
    relationship_id: RelationshipID = field(default_factory=lambda: str(uuid.uuid4()))
    relationship_type: RelationshipType = "related_to"
    source_entity: Optional[Entity] = None
    target_entity: Optional[Entity] = None
    properties: Optional[Dict[str, Any]] = field(default_factory=dict)
    confidence: float = DEFAULT_CONFIDENCE
    source_text: Optional[str] = None
    bidirectional: bool = False
    extraction_method: Optional[str] = None

    def __post_init__(self):
        """Handle flexible constructor patterns.
        
        This method fixes cases where the relationship was created with
        the old calling pattern: Relationship(source, target, type)
        """
        # If relationship_id is actually an Entity (wrong calling pattern), fix it
        if isinstance(self.relationship_id, Entity):
            # This means the call was Relationship(source, target, type)
            source_entity = self.relationship_id
            target_entity = self.relationship_type
            relationship_type = self.source_entity
            
            # Fix the fields
            self.relationship_id = str(uuid.uuid4())
            self.source_entity = source_entity
            self.target_entity = target_entity
            self.relationship_type = relationship_type

    @classmethod
    def create(cls, source: Entity, target: Entity, relationship_type: str, **kwargs) -> 'Relationship':
        """Create relationship with intuitive parameter order.
        
        This is the preferred way to create relationships.
        
        Args:
            source: Source entity (head of the relationship)
            target: Target entity (tail of the relationship)
            relationship_type: Type of the relationship
            **kwargs: Additional keyword arguments (properties, confidence, etc.)
        
        Returns:
            Relationship: The created relationship instance
        
        Examples:
            >>> person = Entity(entity_type="person", name="Bob")
            >>> city = Entity(entity_type="location", name="New York")
            >>> rel = Relationship.create(person, city, "lives_in", confidence=0.9)
            >>> rel.confidence
            0.9
        """
        return cls(
            source_entity=source,
            target_entity=target,
            relationship_type=relationship_type,
            **kwargs
        )

    @property
    def source_id(self) -> Optional[str]:
        """Get the ID of the source entity.
        
        Returns:
            str: Entity ID of the source entity, or None if no source
        """
        return self.source_entity.entity_id if self.source_entity else None

    @property
    def target_id(self) -> Optional[str]:
        """Get the ID of the target entity.
        
        Returns:
            str: Entity ID of the target entity, or None if no target
        """
        return self.target_entity.entity_id if self.target_entity else None

    def to_dict(self, include_entities: bool = True) -> Dict[str, Any]:
        """Convert the relationship to a dictionary representation.

        Args:
            include_entities (bool): Whether to include full entity details.
                If True, includes complete entity dictionaries.
                If False, only includes entity IDs.

        Returns:
            Dict: Dictionary representation of the relationship with fields:
                - relationship_id: Unique identifier
                - relationship_type: Type classification
                - source: Source entity (dict or ID)
                - target: Target entity (dict or ID)
                - properties: Additional properties
                - confidence: Confidence score
                - bidirectional: Whether bidirectional
                - source_text: Original text (if available)
        """
        rel_dict = {
            "relationship_id": self.relationship_id,
            "relationship_type": self.relationship_type,
            "properties": self.properties,
            "confidence": self.confidence,
            "bidirectional": self.bidirectional
        }

        if self.source_text:
            rel_dict["source_text"] = self.source_text

        if include_entities:
            rel_dict["source"] = self.source_entity.to_dict() if self.source_entity else None
            rel_dict["target"] = self.target_entity.to_dict() if self.target_entity else None
        else:
            rel_dict["source"] = self.source_id
            rel_dict["target"] = self.target_id

        return rel_dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any], entity_map: Optional[Dict[str, Entity]] = None) -> 'Relationship':
        """Create a relationship from a dictionary representation.

        Args:
            data (Dict): Dictionary representation of the relationship with fields:
                - relationship_id (optional): Unique identifier
                - relationship_type: Type classification
                - source: Source entity (dict or ID)
                - target: Target entity (dict or ID)
                - properties (optional): Additional properties
                - confidence (optional): Confidence score
                - bidirectional (optional): Whether bidirectional
                - source_text (optional): Original text
            entity_map (Dict, optional): Map from entity IDs to Entity objects.
                Used to resolve entity references by ID.

        Returns:
            Relationship: The created relationship instance
        """
        entity_map = entity_map or {}

        # Handle source and target entities
        source = None
        target = None

        if isinstance(data.get("source"), dict):
            source = Entity.from_dict(data["source"])
        elif data.get("source") in entity_map:
            source = entity_map[data["source"]]

        if isinstance(data.get("target"), dict):
            target = Entity.from_dict(data["target"])
        elif data.get("target") in entity_map:
            target = entity_map[data["target"]]

        return cls(
            relationship_id=data.get("relationship_id"),
            relationship_type=data.get("relationship_type", "related_to"),
            source_entity=source,
            target_entity=target,
            properties=data.get("properties", {}),
            confidence=data.get("confidence", DEFAULT_CONFIDENCE),
            source_text=data.get("source_text"),
            bidirectional=data.get("bidirectional", False)
        )
