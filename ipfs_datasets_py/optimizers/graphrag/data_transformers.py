"""
Ontology data transformation and mapping utilities.

This module provides utilities for converting between different representations
of ontology data, including entity extraction results, relationship structures,
critic scores, and session data. Features include:

- Transformation pipelines with composed mappings
- Schema migration and data normalization
- Format converters (dict ↔ TypedDict ↔ dataclass)
- Data enrichment and filtering utilities
- Batch transformation with progress tracking
- Reversible transformations where applicable

Usage:
    >>> extractor_result = {'entities': [...], 'relationships': [...]}
    >>> transformed = transform_entity_result(extractor_result)
    >>> normalized = normalize_entity(entity_data)
    
    >>> # Use transformation pipeline
    >>> pipeline = TransformationPipeline()
    >>> pipeline.add_mapping(normalize_entity)
    >>> pipeline.add_filter(lambda e: e['confidence'] > 0.7)
    >>> results = pipeline.transform_batch(entities)

Examples:
    >>> # Convert extraction result formats
    >>> old_format = {'entities': [{'text': '...', 'type': '...'}]}
    >>> new_format = convert_extraction_result_format_v1_to_v2(old_format)
    
    >>> # Normalize entities
    >>> entity = {'id': 'E1', 'name': '  John Smith  ', 'type': 'person'}
    >>> normalized = normalize_entity(entity)
    >>> assert normalized['name'] == 'John Smith'

Transformation Stages:
1. Extraction → Normalization (clean/standardize data)
2. Normalization → Enrichment (add derived fields)
3. Enrichment → Filtering (apply constraints)
4. Filtering → Output (serialize/export)
"""

from typing import Any, Dict, List, Optional, Callable, TypeVar, Generic, Protocol
from dataclasses import dataclass, field, asdict, fields as dataclass_fields
from enum import Enum
import functools
import json
from abc import ABC, abstractmethod


T = TypeVar('T')
U = TypeVar('U')


class TransformationError(Exception):
    """Raised when data transformation fails."""
    pass


class TransformationDirection(Enum):
    """Direction of transformation."""
    FORWARD = "forward"
    REVERSE = "reverse"
    BIDIRECTIONAL = "bidirectional"


class Transformation(ABC, Generic[T, U]):
    """Abstract base for data transformations."""
    
    @abstractmethod
    def transform(self, data: T) -> U:
        """Transform data from input to output format."""
        pass
    
    def transform_batch(self, data_items: List[T], skip_errors: bool = False) -> List[U]:
        """Transform a batch of items.
        
        Args:
            data_items: List of items to transform
            skip_errors: If True, skip items that fail transformation
            
        Returns:
            List of transformed items
            
        Raises:
            TransformationError: If any item fails and skip_errors=False
        """
        results = []
        errors = []
        
        for i, item in enumerate(data_items):
            try:
                results.append(self.transform(item))
            except Exception as e:
                if skip_errors:
                    errors.append((i, item, str(e)))
                else:
                    raise TransformationError(f"Transformation failed at item {i}: {e}") from e
        
        if errors and skip_errors:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Skipped {len(errors)} items during batch transformation")
        
        return results


def normalize_string(text: Optional[str]) -> Optional[str]:
    """Normalize string by trimming and deduplicating whitespace.
    
    Args:
        text: String to normalize
        
    Returns:
        Normalized string or None
    """
    if text is None:
        return None
    if not isinstance(text, str):
        text = str(text)
    return ' '.join(text.split())


def normalize_entity(entity: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize entity data.
    
    Operations:
    - Normalize string fields (strip, deduplicate whitespace)
    - Convert type to lowercase
    - Ensure confidence is in [0, 1] range
    - Remove empty properties
    
    Args:
        entity: Entity dictionary
        
    Returns:
        Normalized entity
    """
    normalized = dict(entity)
    
    # Normalize string fields
    for field in ['name', 'text', 'description']:
        if field in normalized:
            normalized[field] = normalize_string(normalized[field])
    
    # Normalize type
    if 'type' in normalized:
        if isinstance(normalized['type'], str):
            normalized['type'] = normalized['type'].lower()
    
    # Ensure confidence is in range
    if 'confidence' in normalized:
        confidence = normalized['confidence']
        if isinstance(confidence, (int, float)):
            normalized['confidence'] = max(0.0, min(1.0, float(confidence)))
    
    # Remove empty properties
    if 'properties' in normalized and isinstance(normalized['properties'], dict):
        normalized['properties'] = {
            k: v for k, v in normalized['properties'].items() 
            if v is not None and (not isinstance(v, str) or v.strip())
        }
    
    return normalized


def normalize_relationship(rel: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize relationship data.
    
    Operations:
    - Normalize string fields
    - Convert type to lowercase
    - Ensure confidence values in [0, 1]
    - Validate source != target
    
    Args:
        rel: Relationship dictionary
        
    Returns:
        Normalized relationship
    """
    normalized = dict(rel)
    
    # Normalize string fields
    for field in ['type', 'evidence', 'description']:
        if field in normalized:
            normalized[field] = normalize_string(normalized[field])
    
    # Normalize type
    if 'type' in normalized:
        if isinstance(normalized['type'], str):
            normalized['type'] = normalized['type'].lower()
    
    # Ensure confidence values in range
    for field in ['confidence', 'type_confidence']:
        if field in normalized and isinstance(normalized[field], (int, float)):
            normalized[field] = max(0.0, min(1.0, float(normalized[field])))
    
    # Validate source != target
    if 'source' in normalized and 'target' in normalized:
        if normalized['source'] == normalized['target']:
            raise TransformationError(f"Self-relationship detected: {normalized['source']}")
    
    return normalized


def normalize_extraction_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize complete extraction result.
    
    Args:
        result: Extraction result dictionary
        
    Returns:
        Normalized result
    """
    normalized = dict(result)
    
    # Normalize entities
    if 'entities' in normalized and isinstance(normalized['entities'], list):
        normalized['entities'] = [
            normalize_entity(e) for e in normalized['entities']
        ]
    
    # Normalize relationships
    if 'relationships' in normalized and isinstance(normalized['relationships'], list):
        normalized['relationships'] = [
            normalize_relationship(r) for r in normalized['relationships']
        ]
    
    return normalized


def denormalize_entity(entity: Dict[str, Any]) -> Dict[str, Any]:
    """Denormalize entity back to original format.
    
    Reverse operation of normalize_entity where applicable.
    """
    return dict(entity)


def filter_entities_by_confidence(
    entities: List[Dict[str, Any]], 
    threshold: float = 0.5,
) -> List[Dict[str, Any]]:
    """Filter entities by confidence threshold.
    
    Args:
        entities: List of entity dictionaries
        threshold: Minimum confidence (0-1)
        
    Returns:
        Filtered list of entities meeting threshold
    """
    return [
        e for e in entities 
        if e.get('confidence', 0) >= threshold
    ]


def filter_relationships_by_confidence(
    relationships: List[Dict[str, Any]], 
    threshold: float = 0.5,
) -> List[Dict[str, Any]]:
    """Filter relationships by confidence threshold.
    
    Args:
        relationships: List of relationship dictionaries
        threshold: Minimum confidence (0-1)
        
    Returns:
        Filtered list of relationships meeting threshold
    """
    return [
        r for r in relationships 
        if r.get('confidence', 0) >= threshold
    ]


def enrich_entity(entity: Dict[str, Any], **enrichment) -> Dict[str, Any]:
    """Enrich entity with additional metadata.
    
    Args:
        entity: Entity dictionary
        **enrichment: Additional fields to add
        
    Returns:
        Enriched entity
    """
    result = dict(entity)
    result.update(enrichment)
    return result


def merge_entities(
    entities: List[Dict[str, Any]], 
    merge_strategy: str = 'highest_confidence'
) -> Dict[str, Any]:
    """Merge duplicate entities.
    
    Args:
        entities: List of entity dictionaries
        merge_strategy: How to merge ('highest_confidence', 'first', 'average')
        
    Returns:
        Merged entities by ID
    """
    merged = {}
    
    for entity in entities:
        entity_id = entity.get('id')
        if not entity_id:
            continue
        
        if entity_id not in merged:
            merged[entity_id] = dict(entity)
        else:
            existing = merged[entity_id]
            
            if merge_strategy == 'highest_confidence':
                if entity.get('confidence', 0) > existing.get('confidence', 0):
                    merged[entity_id] = dict(entity)
            elif merge_strategy == 'average':
                # Average confidence if both have it
                if 'confidence' in entity and 'confidence' in existing:
                    avg_conf = (entity['confidence'] + existing['confidence']) / 2
                    merged[entity_id]['confidence'] = avg_conf
    
    return merged


def deduplicaterelationships(
    relationships: List[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Deduplicate relationships, keeping highest confidence version.
    
    Args:
        relationships: List of relationship dictionaries
        
    Returns:
        Deduplicated relationships
    """
    seen = {}
    
    for rel in relationships:
        # Use (source, target, type) as dedup key
        key = (rel.get('source'), rel.get('target'), rel.get('type'))
        
        if key not in seen:
            seen[key] = dict(rel)
        else:
            existing = seen[key]
            if rel.get('confidence', 0) > existing.get('confidence', 0):
                seen[key] = dict(rel)
    
    return list(seen.values())


@dataclass
class TransformationPipeline:
    """Pipeline for chaining multiple transformations."""
    
    transformations: List[Callable[[Any], Any]] = field(default_factory=list)
    
    def add_step(self, transform: Callable[[Any], Any]) -> 'TransformationPipeline':
        """Add a transformation step to pipeline.
        
        Args:
            transform: Callable that transforms data
            
        Returns:
            Self for chaining
        """
        self.transformations.append(transform)
        return self
    
    def transform(self, data: Any) -> Any:
        """Apply all transformations in sequence.
        
        Args:
            data: Data to transform
            
        Returns:
            Transformed data
        """
        result = data
        for transform in self.transformations:
            result = transform(result)
        return result
    
    def transform_batch(self, data_items: List[Any]) -> List[Any]:
        """Transform batch of items through pipeline.
        
        Args:
            data_items: Items to transform
            
        Returns:
            Transformed items
        """
        return [self.transform(item) for item in data_items]


class EntityTransformer(Transformation[Dict[str, Any], Dict[str, Any]]):
    """Transformer for entity data."""
    
    def __init__(self, normalize: bool = True, filter_confidence: Optional[float] = None):
        self.normalize = normalize
        self.filter_confidence = filter_confidence
    
    def transform(self, entity: Dict[str, Any]) -> Dict[str, Any]:
        """Transform entity."""
        result = entity
        
        if self.normalize:
            result = normalize_entity(result)
        
        # No entity-level filtering (filtering is batch-level)
        
        return result


class ExtractionResultTransformer(Transformation[Dict[str, Any], Dict[str, Any]]):
    """Transformer for complete extraction results."""
    
    def __init__(
        self, 
        normalize: bool = True,
        confidence_threshold: Optional[float] = None,
        deduplicate: bool = True,
    ):
        self.normalize = normalize
        self.confidence_threshold = confidence_threshold
        self.deduplicate = deduplicate
    
    def transform(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """Transform extraction result."""
        transformed = dict(result)
        
        if self.normalize:
            transformed = normalize_extraction_result(transformed)
        
        # Filter by confidence
        if self.confidence_threshold is not None:
            entities = transformed.get('entities', [])
            relationships = transformed.get('relationships', [])
            
            transformed['entities'] = filter_entities_by_confidence(
                entities, self.confidence_threshold
            )
            transformed['relationships'] = filter_relationships_by_confidence(
                relationships, self.confidence_threshold
            )
        
        # Deduplicate
        if self.deduplicate:
            entities = transformed.get('entities', [])
            relationships = transformed.get('relationships', [])
            
            # For entities, merge by ID
            merged_entities = merge_entities(entities)
            transformed['entities'] = list(merged_entities.values())
            
            # For relationships, deduplicate
            transformed['relationships'] = deduplicaterelationships(relationships)
        
        return transformed


def dict_to_dataclass(data: Dict[str, Any], dataclass_type: type) -> Any:
    """Convert dictionary to dataclass instance.
    
    Args:
        data: Dictionary with dataclass fields
        dataclass_type: Dataclass type to create
        
    Returns:
        Dataclass instance
        
    Raises:
        TypeError: If data type is invalid
    """
    if not hasattr(dataclass_type, '__dataclass_fields__'):
        raise TypeError(f"{dataclass_type} is not a dataclass")
    
    # Filter to only valid fields
    field_names = {f.name for f in dataclass_fields(dataclass_type)}
    valid_data = {k: v for k, v in data.items() if k in field_names}
    
    return dataclass_type(**valid_data)


def dataclass_to_dict(obj: Any) -> Dict[str, Any]:
    """Convert dataclass instance to dictionary.
    
    Args:
        obj: Dataclass instance
        
    Returns:
        Dictionary representation
        
    Raises:
        TypeError: If not a dataclass instance
    """
    if not hasattr(obj, '__dataclass_fields__'):
        raise TypeError(f"{obj} is not a dataclass instance")
    
    return asdict(obj)


if __name__ == '__main__':
    # Example usage
    entity = {
        'id': 'e1',
        'name': '  John Smith  ',
        'type': 'PERSON',
        'confidence': 1.5,
    }
    
    normalized = normalize_entity(entity)
    print(f"Original: {entity}")
    print(f"Normalized: {normalized}")
    
    # Pipeline example
    result = {
        'entities': [
            {'id': 'e1', 'name': 'John', 'type': 'Person', 'confidence': 0.9},
            {'id': 'e2', 'name': 'Jane', 'type': 'Person', 'confidence': 0.3},
        ],
        'relationships': []
    }
    
    transformer = ExtractionResultTransformer(
        normalize=True,
        confidence_threshold=0.5,
        deduplicate=True
    )
    transformed=transformer.transform(result)
    print(f"Transformed: {transformed}")
