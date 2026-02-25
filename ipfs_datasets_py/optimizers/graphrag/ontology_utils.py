"""Utilities for ensuring deterministic ordering in ontology structures.

These helpers ensure that ontologies with identical content always produce
identical dict representations, regardless of insertion order. This is crucial
for reproducibility, testing, and deduplication.

Usage::

    from ipfs_datasets_py.optimizers.graphrag.ontology_utils import (
        sort_ontology,
        sort_entities,
        sort_relationships,
    )
    
    ontology = generator.generate_ontology(text, context)
    sorted_ontology = sort_ontology(ontology)
    
    # Now sorted_ontology will have deterministic entity/relationship ordering
    # based on (id, type, text) to break ties
"""

from typing import Any, Dict, List, Optional
import logging

_logger = logging.getLogger(__name__)


def sort_entities(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort entities list deterministically for reproducibility.
    
    Entities are sorted by:
    1. ID (primary key, must be unique or nearly so)
    2. Type (groups related entities)
    3. Text (breaks ties for display consistency)
    
    Args:
        entities: List of entity dicts
        
    Returns:
        New sorted list (original list is not modified)
    """
    if not entities:
        return []
    
    def entity_sort_key(e: Dict[str, Any]) -> tuple[str, str, str, float]:
        """Generate consistent sort key for an entity."""
        entity_id = str(e.get("id") or e.get("Id") or "")
        entity_type = str(e.get("type") or e.get("Type") or "Unknown")
        text = str(e.get("text") or e.get("Text") or "")
        confidence = float(e.get("confidence") or e.get("Confidence") or 0.0)
        
        # Sort by: id, then type, then text (ascending)
        # Secondary sorts ensure identical content always orders the same way
        return (entity_id, entity_type, text, -confidence)  # negative confidence for desc order
    
    sorted_entities = sorted(entities, key=entity_sort_key)
    return sorted_entities


def sort_relationships(relationships: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Sort relationships list deterministically for reproducibility.
    
    Relationships are sorted by:
    1. Source entity ID
    2. Target entity ID
    3. Relationship type
    4. Confidence (descending)
    
    Args:
        relationships: List of relationship dicts
        
    Returns:
        New sorted list (original list is not modified)
    """
    if not relationships:
        return []
    
    def relationship_sort_key(r: Dict[str, Any]) -> tuple[str, str, str, str, float]:
        """Generate consistent sort key for a relationship."""
        source = str(r.get("source") or r.get("Source") or "")
        target = str(r.get("target") or r.get("Target") or "")
        rel_type = str(r.get("type") or r.get("Type") or "unknown")
        confidence = float(r.get("confidence") or r.get("Confidence") or 0.0)
        rel_id = str(r.get("id") or r.get("Id") or "")
        
        # Sort by: source, target, type, rel_id, then confidence (desc)
        return (source, target, rel_type, rel_id, -confidence)
    
    sorted_relationships = sorted(relationships, key=relationship_sort_key)
    return sorted_relationships


def sort_ontology(ontology: Dict[str, Any]) -> Dict[str, Any]:
    """Sort entities and relationships in an ontology dict deterministically.
    
    This ensures that two ontologies with identical content will have identical
    ordering regardless of generation order. Essential for:
    - Snapshot testing
    - Deduplication (comparing dicts for equality)
    - Reproducible outputs
    
    Args:
        ontology: Ontology dict with 'entities' and 'relationships'
        
    Returns:
        New ontology dict with sorted lists (original is not modified)
        
    Raises:
        ValueError: If ontology structure is invalid (missing required keys)
    """
    if not isinstance(ontology, dict):
        raise ValueError(f"Expected dict, got {type(ontology).__name__}")
    
    if "entities" not in ontology or "relationships" not in ontology:
        raise ValueError("Ontology must have 'entities' and 'relationships' keys")
    
    entities = ontology.get("entities", [])
    relationships = ontology.get("relationships", [])
    
    if not isinstance(entities, list):
        raise ValueError(f"'entities' must be a list, got {type(entities).__name__}")
    if not isinstance(relationships, list):
        raise ValueError(f"'relationships' must be a list, got {type(relationships).__name__}")
    
    # Create new ontology with sorted lists
    sorted_ontology = dict(ontology)  # shallow copy
    sorted_ontology["entities"] = sort_entities(entities)
    sorted_ontology["relationships"] = sort_relationships(relationships)
    
    _logger.debug(
        f"Sorted ontology: {len(sorted_ontology['entities'])} entities, "
        f"{len(sorted_ontology['relationships'])} relationships"
    )
    
    return sorted_ontology


def is_sorted_ontology(ontology: Dict[str, Any]) -> bool:
    """Check if an ontology has deterministic ordering.
    
    Args:
        ontology: Ontology dict to check
        
    Returns:
        True if entities and relationships are in deterministic order
    """
    try:
        sorted_version = sort_ontology(ontology)
        
        # Check if entities are identical after sorting (same order)
        orig_entities = ontology.get("entities", [])
        sort_entities_result = sorted_version.get("entities", [])
        
        if len(orig_entities) != len(sort_entities_result):
            return False
        
        # Compare by ID to detect ordering differences
        orig_ids = [str(e.get("id") or e.get("Id") or "") for e in orig_entities]
        sort_ids = [str(e.get("id") or e.get("Id") or "") for e in sort_entities_result]
        
        if orig_ids != sort_ids:
            return False
        
        # Same for relationships
        orig_rels = ontology.get("relationships", [])
        sort_rels_result = sorted_version.get("relationships", [])
        
        if len(orig_rels) != len(sort_rels_result):
            return False
        
        orig_rel_keys = [
            (str(r.get("source") or r.get("Source") or ""),
             str(r.get("target") or r.get("Target") or ""))
            for r in orig_rels
        ]
        sort_rel_keys = [
            (str(r.get("source") or r.get("Source") or ""),
             str(r.get("target") or r.get("Target") or ""))
            for r in sort_rels_result
        ]
        
        return orig_rel_keys == sort_rel_keys
    except (ValueError, KeyError, TypeError):
        return False


__all__ = [
    "sort_entities",
    "sort_relationships",
    "sort_ontology",
    "is_sorted_ontology",
]
