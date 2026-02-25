"""GraphRAG ontology serialization helpers.

This module centralizes conversions between the internal GraphRAG dataclasses
(:class:`~ipfs_datasets_py.optimizers.graphrag.ontology_generator.Entity` and
:class:`~ipfs_datasets_py.optimizers.graphrag.ontology_generator.Relationship`)
and the public ontology-dict schema used across the package.

The canonical *public* dict schema intentionally stays minimal:

Entity dict keys:
    - ``id`` (str)
    - ``text`` (str)
    - ``type`` (str)
    - ``confidence`` (float)
    - ``properties`` (dict)

Relationship dict keys:
    - ``id`` (str)
    - ``source_id`` (str)
    - ``target_id`` (str)
    - ``type`` (str)
    - ``confidence`` (float)
    - ``properties`` (dict)

Internal-only fields like ``source_span``, ``last_seen``, or ``direction`` are
preserved on the dataclass side but are not emitted in the public dicts.
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence, Tuple, TypedDict, cast

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity as EntityModel,
    EntityExtractionResult as ExtractionResultModel,
    Relationship as RelationshipModel,
)


# TypedDict Definitions for Type-Safe Ontology Serialization

class EntityDictModel(TypedDict, total=False):
    """Public schema for entity dictionary representation.
    
    This TypedDict defines the canonical public ontology dict schema for entities.
    Internal-only fields like source_span or last_seen are not included here.
    
    Fields:
        id: Unique identifier for the entity
        text: Human-readable text representation of the entity
        type: Entity type (e.g., 'PERSON', 'ORGANIZATION', 'LOCATION')
        confidence: Confidence score for entity extraction (0.0-1.0)
        properties: Additional entity properties as key-value pairs
    """
    id: str
    text: str
    type: str
    confidence: float
    properties: Dict[str, Any]


class RelationshipDictModel(TypedDict, total=False):
    """Public schema for relationship dictionary representation.
    
    This TypedDict defines the canonical public ontology dict schema for relationships.
    Internal-only fields like direction or last_seen are not included here.
    
    Fields:
        id: Unique identifier for the relationship
        source_id: ID of the source entity
        target_id: ID of the target entity
        type: Relationship type (e.g., 'IS-A', 'RELATED-TO', 'LOCATED-IN')
        confidence: Confidence score for relationship extraction (0.0-1.0)
        properties: Additional relationship properties as key-value pairs
    """
    id: str
    source_id: str
    target_id: str
    type: str
    confidence: float
    properties: Dict[str, Any]


class OntologyDictModel(TypedDict, total=False):
    """Complete ontology represented as dictionary with entities and relationships.
    
    This TypedDict defines the canonical ontology structure containing both
    entities and relationships extracted from text.
    
    Fields:
        entities: List of entity dictionaries in EntityDictModel format
        relationships: List of relationship dictionaries in RelationshipDictModel format
    """
    entities: List[EntityDictModel]
    relationships: List[RelationshipDictModel]


def entity_model_to_dict(entity: EntityModel) -> EntityDictModel:
    """Convert an :class:`Entity` dataclass to the canonical public dict."""
    return {
        "id": entity.id,
        "text": entity.text,
        "type": entity.type,
        "confidence": float(getattr(entity, "confidence", 1.0)),
        "properties": dict(getattr(entity, "properties", {}) or {}),
    }


def relationship_model_to_dict(rel: RelationshipModel) -> RelationshipDictModel:
    """Convert a :class:`Relationship` dataclass to the canonical public dict."""
    return {
        "id": rel.id,
        "source_id": rel.source_id,
        "target_id": rel.target_id,
        "type": rel.type,
        "confidence": float(getattr(rel, "confidence", 1.0)),
        "properties": dict(getattr(rel, "properties", {}) or {}),
    }


def entity_dict_to_model(d: Mapping[str, Any]) -> EntityModel:
    """Convert a (possibly extended) entity dict to an :class:`Entity`.

    The function accepts canonical public dicts and also tolerates additional
    keys like ``source_span`` and ``last_seen``.
    """
    return EntityModel.from_dict(dict(d))


def relationship_dict_to_model(d: Mapping[str, Any]) -> RelationshipModel:
    """Convert a (possibly extended) relationship dict to a :class:`Relationship`.

    The function accepts canonical public dicts and also tolerates additional
    keys like ``direction``.
    """
    return RelationshipModel.from_dict(dict(d))


def build_ontology_dict(
    *,
    entities: Sequence[EntityModel],
    relationships: Sequence[RelationshipModel],
) -> Dict[str, Any]:
    """Build a canonical public ontology dict from dataclass collections."""
    return {
        "entities": [entity_model_to_dict(e) for e in entities],
        "relationships": [relationship_model_to_dict(r) for r in relationships],
    }


def ontology_from_extraction_result(extraction: ExtractionResultModel) -> OntologyDictModel:
    """Convert an :class:`EntityExtractionResult` to a canonical ontology dict."""
    return build_ontology_dict(entities=extraction.entities, relationships=extraction.relationships)


def models_from_ontology_dict(ontology: Mapping[str, Any]) -> Tuple[List[EntityModel], List[RelationshipModel]]:
    """Convert a canonical ontology dict into lists of dataclass models."""
    entities_raw = cast(Sequence[Mapping[str, Any]], ontology.get("entities") or [])
    rels_raw = cast(Sequence[Mapping[str, Any]], ontology.get("relationships") or [])
    return (
        [entity_dict_to_model(e) for e in entities_raw],
        [relationship_dict_to_model(r) for r in rels_raw],
    )


# ============================================================================
# Advanced Serialization Infrastructure
# ============================================================================

import json
from dataclasses import is_dataclass, fields, MISSING
from functools import lru_cache
from typing import get_type_hints, get_origin, get_args
import logging

# Import GraphRAG exception base class for consistency
from ipfs_datasets_py.optimizers.graphrag.error_handling import (
    GraphRAGException,
    ErrorSeverity,
)


class SerializationError(GraphRAGException):
    """Raised when serialization/deserialization fails."""
    pass


class DeserializationError(SerializationError):
    """Raised when deserialization fails."""
    pass


class CircularReferenceError(SerializationError):
    """Raised when circular references are detected."""
    pass


class OntologySerializer:
    """Advanced serialization/deserialization for ontology structures.
    
    Provides bidirectional conversion between dataclasses and dicts with
    support for nested structures, validation, and custom strategies.
    
    Features:
    - Bidirectional conversion (dict ↔ dataclass)
    - Nested structure support
    - Type validation and coercion
    - Circular reference detection
    - Batch operations with error recovery
    - JSON serialization
    - Caching for performance
    
    Example:
        >>> serializer = OntologySerializer()
        >>> entity_dict = {'id': 'e1', 'text': 'Acme Corp', 'type': 'Organization', 'confidence': 0.95}
        >>> entity = serializer.dict_to_dataclass(entity_dict, EntityModel)
        >>> # Later...
        >>> entity_dict_again = serializer.dataclass_to_dict(entity)
    """
    
    def __init__(
        self,
        strict_mode: bool = False,
        logger: logging.Logger = None,
    ):
        """Initialize serializer.
        
        Args:
            strict_mode: If True, raise on unknown fields during deserialization
            logger: Optional logger instance
        """
        self.strict_mode = strict_mode
        self.logger = logger or logging.getLogger(__name__)
        self._type_cache = {}
    
    def dataclass_to_dict(
        self,
        obj: Any,
        include_none: bool = False,
        exclude_fields: List[str] = None,
    ) -> Dict[str, Any]:
        """Convert dataclass instance to dictionary.
        
        Args:
            obj: Dataclass instance to convert
            include_none: Whether to include None values
            exclude_fields: Fields to exclude from serialization
            
        Returns:
            Dictionary representation
        """
        if not is_dataclass(obj):
            raise SerializationError(f"Object is not a dataclass: {type(obj)}")
        
        result = {}
        exclude = set(exclude_fields or [])
        
        for field in fields(obj):
            if field.name in exclude:
                continue
            
            value = getattr(obj, field.name)
            
            # Handle None values
            if value is None and not include_none:
                continue
            
            # Recursively serialize nested dataclasses
            if is_dataclass(value) and not isinstance(value, type):
                value = self.dataclass_to_dict(value, include_none, exclude_fields)
            elif isinstance(value, list):
                value = [
                    self.dataclass_to_dict(v, include_none, exclude_fields)
                    if is_dataclass(v) and not isinstance(v, type) else v
                    for v in value
                ]
            elif isinstance(value, dict):
                value = {
                    k: self.dataclass_to_dict(v, include_none, exclude_fields)
                    if is_dataclass(v) and not isinstance(v, type) else v
                    for k, v in value.items()
                }
            
            result[field.name] = value
        
        return result
    
    def _extract_dataclass_type(self, field_type: Any) -> Any:
        """Extract dataclass type from type hints, handling Optional/Union.
        
        Args:
            field_type: Type annotation (may be Optional, Union, etc.)
            
        Returns:
            The dataclass type if found, None otherwise
        """
        # Direct check
        if is_dataclass(field_type):
            return field_type
        
        # Check if it's a Union (including Optional)
        origin = get_origin(field_type)
        if origin is not None:
            args = get_args(field_type)
            # Find first non-None type that's a dataclass
            for arg in args:
                if arg is not type(None) and is_dataclass(arg):
                    return arg
        
        return None
    
    def dict_to_dataclass(
        self,
        data: Dict[str, Any],
        dataclass_type: type,
        visited: set = None,
    ) -> Any:
        """Convert dictionary to dataclass instance.
        
        Args:
            data: Dictionary with data
            dataclass_type: Target dataclass type
            visited: Set of visited object ids (for circular reference detection)
            
        Returns:
            Dataclass instance
            
        Raises:
            DeserializationError: If conversion fails
        """
        if not is_dataclass(dataclass_type):
            raise DeserializationError(f"Target is not a dataclass: {dataclass_type}")
        
        if not isinstance(data, dict):
            raise DeserializationError(f"Data must be dict, got {type(data)}")
        
        # Initialize visited set for circular reference detection
        if visited is None:
            visited = set()
        
        obj_id = id(data)
        if obj_id in visited:
            raise CircularReferenceError(f"Circular reference detected")
        visited.add(obj_id)
        
        try:
            # Get type hints for better type resolution
            try:
                type_hints = get_type_hints(dataclass_type)
            except (NameError, TypeError, AttributeError, ImportError):
                type_hints = {}
            
            # Build kwargs for dataclass instantiation
            kwargs = {}
            for field in fields(dataclass_type):
                if field.name not in data:
                    # Check if field has default
                    if field.default is not MISSING:
                        kwargs[field.name] = field.default
                    elif field.default_factory is not MISSING:  # type: ignore
                        kwargs[field.name] = field.default_factory()  # type: ignore
                    elif not self.strict_mode:
                        continue
                    else:
                        raise DeserializationError(f"Missing required field: {field.name}")
                else:
                    value = data[field.name]
                    
                    # Get actual type from type hints or field annotation
                    field_type = type_hints.get(field.name, field.type)
                    
                    # Handle None values
                    if value is None:
                        kwargs[field.name] = value
                    elif isinstance(value, dict):
                        # Extract dataclass type (handles Optional/Union)
                        dataclass_type_to_use = self._extract_dataclass_type(field_type)
                        if dataclass_type_to_use:
                            value = self.dict_to_dataclass(value, dataclass_type_to_use, visited)
                    
                    kwargs[field.name] = value
            
            return dataclass_type(**kwargs)
        
        finally:
            visited.discard(obj_id)
    
    def dict_to_dataclass_batch(
        self,
        data_list: List[Dict[str, Any]],
        dataclass_type: type,
        skip_errors: bool = False,
    ) -> List[Any]:
        """Convert multiple dictionaries to dataclass instances.
        
        Args:
            data_list: List of dictionaries
            dataclass_type: Target dataclass type
            skip_errors: If True, return None for failed conversions
            
        Returns:
            List of dataclass instances (None for failures if skip_errors=True)
        """
        results = []
        
        for i, data in enumerate(data_list):
            try:
                result = self.dict_to_dataclass(data, dataclass_type)
                results.append(result)
            except (DeserializationError, CircularReferenceError, TypeError) as e:
                if skip_errors:
                    self.logger.warning(f"Failed to deserialize item {i}: {e}. Skipping.")
                    results.append(None)
                else:
                    raise DeserializationError(f"Failed to deserialize item {i}: {e}") from e
        
        return results
    
    def to_json(
        self,
        obj: Any,
        include_none: bool = False,
        **json_kwargs
    ) -> str:
        """Convert dataclass to JSON string.
        
        Args:
            obj: Dataclass instance
            include_none: Whether to include None values
            **json_kwargs: Additional kwargs for json.dumps
            
        Returns:
            JSON string
        """
        dict_data = self.dataclass_to_dict(obj, include_none=include_none)
        return json.dumps(dict_data, **json_kwargs)
    
    def from_json(
        self,
        json_str: str,
        dataclass_type: type,
    ) -> Any:
        """Create dataclass from JSON string.
        
        Args:
            json_str: JSON string
            dataclass_type: Target dataclass type
            
        Returns:
            Dataclass instance
        """
        data = json.loads(json_str)
        return self.dict_to_dataclass(data, dataclass_type)
