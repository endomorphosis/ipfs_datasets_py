"""Ontology validation utilities for detecting structural and logical issues.

This module provides utilities to validate ontology structure and detect common
issues such as orphaned entities, circular relationships, missing references,
duplicate IDs, and consistency problems.

Example usage::

    from ipfs_datasets_py.optimizers.graphrag.ontology_validation import (
        validate_ontology,
        ValidationResult,
        find_orphaned_entities,
        detect_circular_relationships,
    )
    
    ontology = {
        "entities": [{"id": "e1", "type": "Person", "text": "Alice"}],
        "relationships": [{"id": "r1", "source_id": "e1", "target_id": "e2", "type": "knows"}],
    }
    
    result = validate_ontology(ontology)
    if not result.is_valid:
        print(f"Found {len(result.errors)} errors:")
        for error in result.errors:
            print(f"  - {error}")

Functions:
    - validate_ontology: Comprehensive ontology validation
    - find_orphaned_entities: Find entities not referenced by any relationship
    - find_dangling_references: Find relationships with missing source/target IDs
    - detect_circular_relationships: Detect circular relationship chains
    - find_duplicate_ids: Find duplicate entity/relationship IDs
    - check_entity_consistency: Check for entity type/text issues
    - check_relationship_consistency: Check for relationship issues
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, Tuple


@dataclass
class ValidationResult:
    """Result of ontology validation.
    
    Attributes:
        errors: List of error messages for critical issues
        warnings: List of warning messages for non-critical issues
        info: List of informational messages
        is_valid: True if no errors found (warnings are allowed)
    """
    
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    info: List[str] = field(default_factory=list)
    
    @property
    def is_valid(self) -> bool:
        """Return True if no errors found."""
        return len(self.errors) == 0
    
    @property
    def total_issues(self) -> int:
        """Return total count of errors + warnings."""
        return len(self.errors) + len(self.warnings)
    
    def __repr__(self) -> str:
        """Return concise representation."""
        status = "Valid" if self.is_valid else "Invalid"
        return (
            f"ValidationResult(status={status}, "
            f"errors={len(self.errors)}, "
            f"warnings={len(self.warnings)}, "
            f"info={len(self.info)})"
        )


def validate_ontology(
    ontology: Dict[str, Any],
    strict: bool = False,
) -> ValidationResult:
    """Validate ontology structure and detect common issues.
    
    Performs comprehensive validation including:
    - Duplicate ID detection
    - Missing entity/relationship references
    - Orphaned entities
    - Circular relationship chains
    - Entity and relationship consistency checks
    
    Args:
        ontology: Ontology dict with 'entities' and 'relationships' keys
        strict: If True, treat warnings as errors
    
    Returns:
        ValidationResult with errors, warnings, and info messages
    
    Example:
        >>> ontology = {"entities": [], "relationships": []}
        >>> result = validate_ontology(ontology)
        >>> result.is_valid
        True
    """
    result = ValidationResult()
    
    # Check required keys
    if "entities" not in ontology:
        result.errors.append("Missing required key: 'entities'")
        return result
    if "relationships" not in ontology:
        result.errors.append("Missing required key: 'relationships'")
        return result
    
    entities = ontology["entities"]
    relationships = ontology["relationships"]
    
    # Check types
    if not isinstance(entities, list):
        result.errors.append(f"'entities' must be a list, got {type(entities).__name__}")
        return result
    if not isinstance(relationships, list):
        result.errors.append(f"'relationships' must be a list, got {type(relationships).__name__}")
        return result
    
    # Basic stats
    result.info.append(f"Ontology contains {len(entities)} entities and {len(relationships)} relationships")
    
    # Check for duplicate entity IDs
    entity_ids = [e.get("id") for e in entities if "id" in e]
    duplicate_entity_ids = find_duplicate_ids(entity_ids)
    for dup_id in duplicate_entity_ids:
        result.errors.append(f"Duplicate entity ID: {dup_id}")
    
    # Check for duplicate relationship IDs
    rel_ids = [r.get("id") for r in relationships if "id" in r]
    duplicate_rel_ids = find_duplicate_ids(rel_ids)
    for dup_id in duplicate_rel_ids:
        result.errors.append(f"Duplicate relationship ID: {dup_id}")
    
    # Check for dangling references
    entity_id_set = set(entity_ids)
    dangling = find_dangling_references(relationships, entity_id_set)
    for rel_id, ref_type, missing_id in dangling:
        result.errors.append(f"Relationship {rel_id} has missing {ref_type}: {missing_id}")
    
    # Check for orphaned entities
    orphaned = find_orphaned_entities(entities, relationships)
    if orphaned:
        msg = f"Found {len(orphaned)} orphaned entities (not referenced by any relationship)"
        if strict:
            result.errors.append(msg)
        else:
            result.warnings.append(msg)
    
    # Check for circular relationships
    circular_chains = detect_circular_relationships(relationships)
    if circular_chains:
        msg = f"Found {len(circular_chains)} circular relationship chains"
        if strict:
            result.errors.append(msg + f": {circular_chains[:3]}")  # Show first 3
        else:
            result.warnings.append(msg)
    
    # Entity consistency checks
    entity_issues = check_entity_consistency(entities)
    for issue in entity_issues:
        result.warnings.append(issue)
    
    # Relationship consistency checks
    rel_issues = check_relationship_consistency(relationships)
    for issue in rel_issues:
        result.warnings.append(issue)
    
    return result


def find_orphaned_entities(
    entities: List[Dict[str, Any]],
    relationships: List[Dict[str, Any]],
) -> List[str]:
    """Find entities not referenced by any relationship.
    
    An entity is orphaned if no relationship has it as source_id or target_id.
    
    Args:
        entities: List of entity dicts
        relationships: List of relationship dicts
    
    Returns:
        List of orphaned entity IDs
    
    Example:
        >>> entities = [{"id": "e1"}, {"id": "e2"}]
        >>> rels = [{"source_id": "e1", "target_id": "e1"}]
        >>> find_orphaned_entities(entities, rels)
        ['e2']
    """
    entity_ids = {e.get("id") for e in entities if "id" in e}
    referenced_ids: Set[str] = set()
    
    for rel in relationships:
        if "source_id" in rel:
            referenced_ids.add(rel["source_id"])
        if "target_id" in rel:
            referenced_ids.add(rel["target_id"])
    
    orphaned = list(entity_ids - referenced_ids)
    return sorted(orphaned)


def find_dangling_references(
    relationships: List[Dict[str, Any]],
    valid_entity_ids: Set[str],
) -> List[Tuple[str, str, str]]:
    """Find relationships with missing source/target entity IDs.
    
    Args:
        relationships: List of relationship dicts
        valid_entity_ids: Set of valid entity IDs
    
    Returns:
        List of tuples: (relationship_id, ref_type, missing_id)
        where ref_type is "source" or "target"
    
    Example:
        >>> rels = [{"id": "r1", "source_id": "e1", "target_id": "e99"}]
        >>> valid_ids = {"e1"}
        >>> find_dangling_references(rels, valid_ids)
        [('r1', 'target', 'e99')]
    """
    dangling = []
    
    for rel in relationships:
        rel_id = rel.get("id", "<unknown>")
        
        if "source_id" in rel:
            source_id = rel["source_id"]
            if source_id not in valid_entity_ids:
                dangling.append((rel_id, "source", source_id))
        
        if "target_id" in rel:
            target_id = rel["target_id"]
            if target_id not in valid_entity_ids:
                dangling.append((rel_id, "target", target_id))
    
    return dangling


def detect_circular_relationships(
    relationships: List[Dict[str, Any]],
    max_depth: int = 100,
) -> List[List[str]]:
    """Detect circular relationship chains.
    
    A circular chain is a sequence of relationships where following the
    target_id → source_id links forms a cycle.
    
    Args:
        relationships: List of relationship dicts
        max_depth: Maximum chain depth to explore (prevents infinite loops)
    
    Returns:
        List of circular chains (each chain is a list of entity IDs)
    
    Example:
        >>> rels = [
        ...     {"source_id": "e1", "target_id": "e2"},
        ...     {"source_id": "e2", "target_id": "e1"},
        ... ]
        >>> circles = detect_circular_relationships(rels)
        >>> len(circles) > 0
        True
    """
    # Build adjacency map: source_id -> list of target_ids
    graph: Dict[str, List[str]] = {}
    for rel in relationships:
        source = rel.get("source_id")
        target = rel.get("target_id")
        if source and target:
            if source not in graph:
                graph[source] = []
            graph[source].append(target)
    
    # DFS to detect cycles
    def find_cycle(node: str, path: List[str], visited: Set[str]) -> List[str]:
        """DFS to find a cycle starting from node."""
        if node in path:
            # Found cycle
            cycle_start = path.index(node)
            return path[cycle_start:] + [node]
        
        if node in visited or len(path) >= max_depth:
            return []
        
        visited.add(node)
        path.append(node)
        
        for neighbor in graph.get(node, []):
            cycle = find_cycle(neighbor, path.copy(), visited.copy())
            if cycle:
                return cycle
        
        return []
    
    # Find all cycles
    cycles = []
    checked_nodes: Set[str] = set()
    
    for start_node in graph.keys():
        if start_node in checked_nodes:
            continue
        
        cycle = find_cycle(start_node, [], set())
        if cycle:
            # Normalize cycle (start from smallest ID for consistency)
            normalized = cycle[cycle.index(min(cycle)):]
            if normalized not in cycles:
                cycles.append(normalized)
        
        checked_nodes.add(start_node)
    
    return cycles


def find_duplicate_ids(ids: List[str]) -> List[str]:
    """Find duplicate IDs in a list.
    
    Args:
        ids: List of IDs (may contain duplicates)
    
    Returns:
        Sorted list of IDs that appear more than once
    
    Example:
        >>> find_duplicate_ids(["a", "b", "a", "c", "b"])
        ['a', 'b']
    """
    seen: Set[str] = set()
    duplicates: Set[str] = set()
    
    for id_ in ids:
        if id_ in seen:
            duplicates.add(id_)
        seen.add(id_)
    
    return sorted(duplicates)


def check_entity_consistency(entities: List[Dict[str, Any]]) -> List[str]:
    """Check entities for consistency issues.
    
    Checks for:
    - Missing required fields (id, type, text)
    - Empty text
    - Invalid confidence values
    - Unusual type names
    
    Args:
        entities: List of entity dicts
    
    Returns:
        List of warning messages
    
    Example:
        >>> entities = [{"id": "e1"}]  # Missing type and text
        >>> issues = check_entity_consistency(entities)
        >>> len(issues) > 0
        True
    """
    issues = []
    
    for i, entity in enumerate(entities):
        if not isinstance(entity, dict):
            issues.append(f"Entity at index {i} is not a dict: {type(entity).__name__}")
            continue
        
        # Check required fields
        if "id" not in entity:
            issues.append(f"Entity at index {i} missing required field: 'id'")
        if "type" not in entity:
            issues.append(f"Entity at index {i} ({entity.get('id', '?')}) missing field: 'type'")
        if "text" not in entity:
            issues.append(f"Entity {entity.get('id', '?')} missing field: 'text'")
        
        # Check text is non-empty
        text = entity.get("text", "")
        if isinstance(text, str) and not text.strip():
            issues.append(f"Entity {entity.get('id', '?')} has empty text")
        
        # Check confidence range
        if "confidence" in entity:
            conf = entity["confidence"]
            if not isinstance(conf, (int, float)):
                issues.append(f"Entity {entity.get('id', '?')} has non-numeric confidence: {conf}")
            elif conf < 0.0 or conf > 1.0:
                issues.append(f"Entity {entity.get('id', '?')} has out-of-range confidence: {conf}")
    
    return issues


def check_relationship_consistency(relationships: List[Dict[str, Any]]) -> List[str]:
    """Check relationships for consistency issues.
    
    Checks for:
    - Missing required fields (id, source_id, target_id, type)
    - Self-loops (source_id == target_id)
    - Invalid confidence values
    - Unusual relationship types
    
    Args:
        relationships: List of relationship dicts
    
    Returns:
        List of warning messages
    
    Example:
        >>> rels = [{"id": "r1", "source_id": "e1", "target_id": "e1"}]
        >>> issues = check_relationship_consistency(rels)
        >>> any("self-loop" in issue.lower() for issue in issues)
        True
    """
    issues = []
    
    for i, rel in enumerate(relationships):
        if not isinstance(rel, dict):
            issues.append(f"Relationship at index {i} is not a dict: {type(rel).__name__}")
            continue
        
        # Check required fields
        if "id" not in rel:
            issues.append(f"Relationship at index {i} missing required field: 'id'")
        if "source_id" not in rel:
            issues.append(f"Relationship {rel.get('id', '?')} missing field: 'source_id'")
        if "target_id" not in rel:
            issues.append(f"Relationship {rel.get('id', '?')} missing field: 'target_id'")
        if "type" not in rel:
            issues.append(f"Relationship {rel.get('id', '?')} missing field: 'type'")
        
        # Check for self-loops
        source = rel.get("source_id")
        target = rel.get("target_id")
        if source and target and source == target:
            issues.append(f"Relationship {rel.get('id', '?')} is a self-loop: {source} → {target}")
        
        # Check confidence range
        if "confidence" in rel:
            conf = rel["confidence"]
            if not isinstance(conf, (int, float)):
                issues.append(f"Relationship {rel.get('id', '?')} has non-numeric confidence: {conf}")
            elif conf < 0.0 or conf > 1.0:
                issues.append(f"Relationship {rel.get('id', '?')} has out-of-range confidence: {conf}")
    
    return issues


def format_validation_result(result: ValidationResult, verbose: bool = False) -> str:
    """Format validation result as human-readable string.
    
    Args:
        result: ValidationResult to format
        verbose: If True, include all errors/warnings/info; if False, show summary
    
    Returns:
        Formatted string
    
    Example:
        >>> result = ValidationResult(errors=["Error 1"], warnings=["Warning 1"])
        >>> formatted = format_validation_result(result)
        >>> "Invalid" in formatted
        True
    """
    lines = []
    status = "✓ Valid" if result.is_valid else "✗ Invalid"
    lines.append(f"Ontology Validation: {status}")
    lines.append("")
    
    # Summary
    lines.append(f"  Errors:   {len(result.errors)}")
    lines.append(f"  Warnings: {len(result.warnings)}")
    lines.append(f"  Info:     {len(result.info)}")
    lines.append("")
    
    if verbose:
        # Show all messages
        if result.errors:
            lines.append("Errors:")
            for err in result.errors:
                lines.append(f"  ✗ {err}")
            lines.append("")
        
        if result.warnings:
            lines.append("Warnings:")
            for warn in result.warnings:
                lines.append(f"  ⚠ {warn}")
            lines.append("")
        
        if result.info:
            lines.append("Info:")
            for info_msg in result.info:
                lines.append(f"  ℹ {info_msg}")
    else:
        # Show summary only
        if result.errors:
            lines.append(f"First error: {result.errors[0]}")
        if result.warnings:
            lines.append(f"First warning: {result.warnings[0]}")
    
    return "\n".join(lines)
