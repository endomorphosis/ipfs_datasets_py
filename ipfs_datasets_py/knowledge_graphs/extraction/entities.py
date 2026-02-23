"""
Entity Module

This module provides the Entity class for representing nodes in a knowledge graph.

Classes:
    Entity: Represents an entity with type, name, and properties
"""

import uuid
from dataclasses import dataclass, field
from typing import Dict, Any, Optional

from .types import EntityID, EntityType, DEFAULT_CONFIDENCE


@dataclass
class Entity:
    """Represents an entity in a knowledge graph.

    Entities are nodes in the knowledge graph with a type, name,
    and optional properties.

    Attributes:
        entity_id (str, optional): Unique identifier for the entity
        entity_type (str): Type of the entity (e.g., "person", "organization")
        name (str): Name or label of the entity
        properties (Dict, optional): Additional properties of the entity
        confidence (float): Confidence score (0.0 to 1.0)
        source_text (str, optional): Source text from which the entity was extracted

    Methods:
        to_dict() -> Dict[str, Any]:
            Convert the entity to a dictionary representation.
        from_dict(data: Dict[str, Any]) -> 'Entity':
            Create an entity from a dictionary representation.
    
    Examples:
        >>> entity = Entity(entity_type="person", name="John Doe")
        >>> entity.entity_id
        '...'  # UUID
        >>> entity.to_dict()
        {'entity_id': '...', 'entity_type': 'person', 'name': 'John Doe', ...}
        
        >>> data = {'entity_type': 'organization', 'name': 'ACME Corp'}
        >>> entity2 = Entity.from_dict(data)
        >>> entity2.name
        'ACME Corp'
    """
    entity_id: EntityID = field(default_factory=lambda: str(uuid.uuid4()))
    entity_type: EntityType = "entity"
    name: str = ""
    properties: Optional[Dict[str, Any]] = field(default_factory=dict)
    confidence: float = DEFAULT_CONFIDENCE
    source_text: Optional[str] = None
    extraction_method: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert the entity to a dictionary representation.

        Returns:
            Dict: Dictionary representation of the entity with fields:
                - entity_id: Unique identifier
                - entity_type: Type classification
                - name: Entity name
                - properties: Additional properties
                - confidence: Confidence score
                - source_text: Original text (if available)
        """
        entity_dict = {
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "name": self.name,
            "properties": self.properties,
            "confidence": self.confidence
        }

        if self.source_text:
            entity_dict["source_text"] = self.source_text

        return entity_dict

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Entity':
        """Create an entity from a dictionary representation.

        Args:
            data (Dict): Dictionary representation of the entity with fields:
                - entity_id (optional): Unique identifier
                - entity_type: Type classification
                - name: Entity name  
                - properties (optional): Additional properties
                - confidence (optional): Confidence score
                - source_text (optional): Original text

        Returns:
            Entity: The created entity instance
        """
        return cls(
            entity_id=data.get("entity_id"),
            entity_type=data.get("entity_type", "entity"),
            name=data.get("name", ""),
            properties=data.get("properties", {}),
            confidence=data.get("confidence", DEFAULT_CONFIDENCE),
            source_text=data.get("source_text")
        )
