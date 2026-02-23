"""Schema validation for ontology dictionaries.

This module provides tools to validate ontology structure and semantics:
- Required field presence (id, type, description)
- Type constraints (IDs are strings, confidence is float, etc.)
- Confidence range validation (0.0 to 1.0)
- Entity reference integrity (relationships reference existing entities)
- No duplicate entity/relationship IDs

Usage::

    from ipfs_datasets_py.optimizers.graphrag.schema_validator import (
        validate_ontology_schema,
        OntologySchemaError,
    )
    
    ontology = {
        "entities": [{"id": "e1", "type": "Person", "description": "..."}],
        "relationships": [{"source": "e1", "target": "e2", "type": "knows"}],
    }
    
    try:
        validate_ontology_schema(ontology)
    except OntologySchemaError as e:
        print(f"Validation failed: {e}")
        for error in e.errors:
            print(f"  - {error}")
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from .exceptions import OntologyValidationError


class OntologySchemaError(OntologyValidationError):
    """Raised when ontology schema validation fails."""


def validate_ontology_schema(
    ontology: Dict[str, Any],
    *,
    strict: bool = False,
    check_references: bool = True,
) -> None:
    """Validate ontology schema structure and semantics.
    
    Args:
        ontology: Ontology dict with 'entities' and 'relationships' keys.
        strict: If True, require confidence scores on all entities/relationships.
        check_references: If True, validate that relationships reference existing entities.
        
    Raises:
        OntologySchemaError: If validation fails. The exception's `errors` attribute
            contains a list of specific validation errors found.
    """
    errors: List[str] = []
    
    # Top-level structure validation
    if not isinstance(ontology, dict):
        raise OntologySchemaError(
            "Ontology must be a dictionary",
            errors=["Expected dict, got " + type(ontology).__name__]
        )
    
    if "entities" not in ontology:
        errors.append("Missing required key 'entities'")
    if "relationships" not in ontology:
        errors.append("Missing required key 'relationships'")
    
    if errors:
        raise OntologySchemaError("Top-level structure validation failed", errors=errors)
    
    entities = ontology["entities"]
    relationships = ontology["relationships"]
    
    if not isinstance(entities, list):
        errors.append("'entities' must be a list")
    if not isinstance(relationships, list):
        errors.append("'relationships' must be a list")
    
    if errors:
        raise OntologySchemaError("Top-level type validation failed", errors=errors)
    
    # Validate entities
    entity_ids: Set[str] = set()
    for i, entity in enumerate(entities):
        _validate_entity(entity, i, errors, entity_ids, strict=strict)
    
    # Validate relationships
    relationship_ids: Set[str] = set()
    for i, rel in enumerate(relationships):
        _validate_relationship(rel, i, errors, relationship_ids, entity_ids, strict=strict, check_references=check_references)
    
    if errors:
        raise OntologySchemaError(
            f"Schema validation failed with {len(errors)} error(s)",
            errors=errors
        )


def _validate_entity(
    entity: Any,
    index: int,
    errors: List[str],
    entity_ids: Set[str],
    strict: bool,
) -> None:
    """Validate a single entity structure.
    
    Args:
        entity: Entity dict to validate.
        index: Position in entities list (for error messages).
        errors: List to append validation errors to.
        entity_ids: Set of entity IDs seen so far (for duplicate detection).
        strict: If True, require confidence score.
    """
    ctx = f"Entity[{index}]"
    
    if not isinstance(entity, dict):
        errors.append(f"{ctx}: must be a dict, got {type(entity).__name__}")
        return
    
    # Check required fields
    entity_id = entity.get("id") or entity.get("Id")
    if not entity_id:
        errors.append(f"{ctx}: missing required field 'id'")
    else:
        if not isinstance(entity_id, str):
            errors.append(f"{ctx}: 'id' must be a string, got {type(entity_id).__name__}")
        elif entity_id in entity_ids:
            errors.append(f"{ctx}: duplicate entity ID '{entity_id}'")
        else:
            entity_ids.add(entity_id)
    
    entity_type = entity.get("type") or entity.get("Type")
    if not entity_type:
        errors.append(f"{ctx}: missing required field 'type'")
    elif not isinstance(entity_type, str):
        errors.append(f"{ctx}: 'type' must be a string, got {type(entity_type).__name__}")
    
    description = entity.get("description") or entity.get("Description")
    if not description:
        errors.append(f"{ctx}: missing required field 'description'")
    elif not isinstance(description, str):
        errors.append(f"{ctx}: 'description' must be a string, got {type(description).__name__}")
    
    # Validate confidence if present
    confidence = entity.get("confidence") or entity.get("Confidence")
    if confidence is not None:
        _validate_confidence(confidence, ctx, errors)
    elif strict:
        errors.append(f"{ctx}: missing required field 'confidence' (strict mode)")


def _validate_relationship(
    rel: Any,
    index: int,
    errors: List[str],
    relationship_ids: Set[str],
    entity_ids: Set[str],
    strict: bool,
    check_references: bool,
) -> None:
    """Validate a single relationship structure.
    
    Args:
        rel: Relationship dict to validate.
        index: Position in relationships list (for error messages).
        errors: List to append validation errors to.
        relationship_ids: Set of relationship IDs seen so far (for duplicate detection).
        entity_ids: Set of valid entity IDs (for reference validation).
        strict: If True, require confidence score.
        check_references: If True, validate source/target reference existing entities.
    """
    ctx = f"Relationship[{index}]"
    
    if not isinstance(rel, dict):
        errors.append(f"{ctx}: must be a dict, got {type(rel).__name__}")
        return
    
    # Check ID (optional for relationships, but if present must be unique)
    rel_id = rel.get("id") or rel.get("Id")
    if rel_id is not None:
        if not isinstance(rel_id, str):
            errors.append(f"{ctx}: 'id' must be a string, got {type(rel_id).__name__}")
        elif rel_id in relationship_ids:
            errors.append(f"{ctx}: duplicate relationship ID '{rel_id}'")
        else:
            relationship_ids.add(rel_id)
    
    # Check required fields
    source = rel.get("source") or rel.get("Source")
    if not source:
        errors.append(f"{ctx}: missing required field 'source'")
    elif not isinstance(source, str):
        errors.append(f"{ctx}: 'source' must be a string, got {type(source).__name__}")
    elif check_references and source not in entity_ids:
        errors.append(f"{ctx}: 'source' references non-existent entity '{source}'")
    
    target = rel.get("target") or rel.get("Target")
    if not target:
        errors.append(f"{ctx}: missing required field 'target'")
    elif not isinstance(target, str):
        errors.append(f"{ctx}: 'target' must be a string, got {type(target).__name__}")
    elif check_references and target not in entity_ids:
        errors.append(f"{ctx}: 'target' references non-existent entity '{target}'")
    
    rel_type = rel.get("type") or rel.get("Type")
    if not rel_type:
        errors.append(f"{ctx}: missing required field 'type'")
    elif not isinstance(rel_type, str):
        errors.append(f"{ctx}: 'type' must be a string, got {type(rel_type).__name__}")
    
    # Validate confidence if present
    confidence = rel.get("confidence") or rel.get("Confidence")
    if confidence is not None:
        _validate_confidence(confidence, ctx, errors)
    elif strict:
        errors.append(f"{ctx}: missing required field 'confidence' (strict mode)")


def _validate_confidence(confidence: Any, ctx: str, errors: List[str]) -> None:
    """Validate confidence score type and range.
    
    Args:
        confidence: Confidence value to validate.
        ctx: Context string for error messages.
        errors: List to append validation errors to.
    """
    if not isinstance(confidence, (int, float)):
        errors.append(f"{ctx}: 'confidence' must be a number, got {type(confidence).__name__}")
    elif not (0.0 <= confidence <= 1.0):
        errors.append(f"{ctx}: 'confidence' must be in range [0.0, 1.0], got {confidence}")


__all__ = [
    "validate_ontology_schema",
    "OntologySchemaError",
]
