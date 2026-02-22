"""Ontology querying and searching utilities for finding entities and relationships.

This module provides utilities to query ontologies for specific entities, relationships,
and patterns. Includes searching by type, text, properties, and relationship patterns.

Example usage::

    from ipfs_datasets_py.optimizers.graphrag.ontology_search import (
        find_entities_by_type,
        find_entities_by_text,
        find_relationships_by_type,
        find_entity_neighbors,
    )
    
    ontology = {"entities": [...], "relationships": [...]}
    
    # Find all Person entities
    people = find_entities_by_type(ontology, "Person")
    
    # Find entities with "Alice" in the text
    matches = find_entities_by_text(ontology, "Alice")
    
    # Find all relationships involving a specific entity
    neighbors = find_entity_neighbors(ontology, "e1", direction="both")

Functions:
    - find_entities_by_type: Find entities matching a type
    - find_entities_by_text: Find entities with text matching a pattern
    - find_entities_by_property: Find entities with specific property values
    - find_relationships_by_type: Find relationships of a specific type
    - find_entity_neighbors: Find all relationships involving an entity
    - find_path_between: Find relationship chains connecting two entities
    - count_entities_by_type: Count entity type distribution
    - count_relationships_by_type: Count relationship type distribution
"""

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class SearchResult:
    """Result of an ontology search query.
    
    Attributes:
        matches: List of matched items (entities or relationships)
        count: Number of matches
        query: The search query that produced these results
    """
    
    matches: List[Dict[str, Any]] = field(default_factory=list)
    query: str = ""
    
    @property
    def count(self) -> int:
        """Return number of matches."""
        return len(self.matches)
    
    def __repr__(self) -> str:
        """Return concise representation."""
        return f"SearchResult(count={self.count}, query='{self.query}')"


@dataclass
class PathResult:
    """Result of a path search between two entities.
    
    Attributes:
        path: List of entity IDs forming the path from source to target
        relationships: List of relationship IDs connecting the path
        distance: Number of hops (relationships) in the path
        exists: True if a path was found
    """
    
    path: List[str] = field(default_factory=list)
    relationships: List[str] = field(default_factory=list)
    
    @property
    def distance(self) -> int:
        """Return number of hops in the path."""
        return len(self.relationships)
    
    @property
    def exists(self) -> bool:
        """Return True if a path was found."""
        return len(self.path) > 1
    
    def __repr__(self) -> str:
        """Return concise representation."""
        return f"PathResult(distance={self.distance}, exists={self.exists})"


def find_entities_by_type(
    ontology: Dict[str, Any],
    entity_type: str,
    case_sensitive: bool = True,
) -> SearchResult:
    """Find all entities matching a specific type.
    
    Args:
        ontology: Ontology dict with 'entities' key
        entity_type: Type to search for
        case_sensitive: If False, case-insensitive matching
    
    Returns:
        SearchResult with matching entities
    
    Example:
        >>> onto = {"entities": [{"type": "Person", "id": "e1"}]}
        >>> result = find_entities_by_type(onto, "Person")
        >>> result.count
        1
    """
    entities = ontology.get("entities", [])
    matches = []
    
    search_type = entity_type if case_sensitive else entity_type.lower()
    
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        
        et = entity.get("type")
        if case_sensitive:
            if et == search_type:
                matches.append(entity)
        else:
            if isinstance(et, str) and et.lower() == search_type:
                matches.append(entity)
    
    return SearchResult(matches=matches, query=f"type:{entity_type}")


def find_entities_by_text(
    ontology: Dict[str, Any],
    pattern: str,
    regex: bool = False,
    case_sensitive: bool = False,
) -> SearchResult:
    """Find entities with text matching a pattern.
    
    Args:
        ontology: Ontology dict with 'entities' key
        pattern: Text pattern to search for (or regex if regex=True)
        regex: If True, treat pattern as regex
        case_sensitive: If False, case-insensitive matching
    
    Returns:
        SearchResult with matching entities
    
    Example:
        >>> onto = {"entities": [{"text": "Alice Smith", "id": "e1"}]}
        >>> result = find_entities_by_text(onto, "alice", regex=False)
        >>> result.count
        1
    """
    entities = ontology.get("entities", [])
    matches = []
    
    try:
        if regex:
            flags = 0 if case_sensitive else re.IGNORECASE
            compiled_pattern = re.compile(pattern, flags)
            
            for entity in entities:
                if not isinstance(entity, dict):
                    continue
                text = entity.get("text", "")
                if isinstance(text, str) and compiled_pattern.search(text):
                    matches.append(entity)
        else:
            search_text = pattern if case_sensitive else pattern.lower()
            
            for entity in entities:
                if not isinstance(entity, dict):
                    continue
                text = entity.get("text", "")
                if isinstance(text, str):
                    entity_text = text if case_sensitive else text.lower()
                    if search_text in entity_text:
                        matches.append(entity)
    except re.error:
        # Invalid regex, search as literal string
        pass
    
    query = f"text~{pattern}" if regex else f"text:{pattern}"
    return SearchResult(matches=matches, query=query)


def find_entities_by_property(
    ontology: Dict[str, Any],
    property_name: str,
    property_value: Any = None,
    operator: str = "eq",
) -> SearchResult:
    """Find entities with specific property values.
    
    Args:
        ontology: Ontology dict with 'entities' key
        property_name: Name of the property to search
        property_value: Value to search for (optional for exists check)
        operator: Comparison operator: 'eq', 'ne', 'gt', 'lt', 'contains'
    
    Returns:
        SearchResult with matching entities
    
    Example:
        >>> onto = {"entities": [{"id": "e1", "properties": {"age": 30}}]}
        >>> result = find_entities_by_property(onto, "age", 30)
        >>> result.count
        1
    """
    entities = ontology.get("entities", [])
    matches = []
    
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        
        properties = entity.get("properties", {})
        if not isinstance(properties, dict):
            continue
        
        if property_name not in properties:
            continue
        
        prop_val = properties[property_name]
        
        # Apply operator
        match = False
        if operator == "eq":
            match = prop_val == property_value
        elif operator == "ne":
            match = prop_val != property_value
        elif operator == "gt":
            try:
                match = prop_val > property_value
            except TypeError:
                pass
        elif operator == "lt":
            try:
                match = prop_val < property_value
            except TypeError:
                pass
        elif operator == "contains":
            if isinstance(prop_val, str) and isinstance(property_value, str):
                match = property_value in prop_val
        
        if match:
            matches.append(entity)
    
    query = f"prop[{property_name}] {operator} {property_value}"
    return SearchResult(matches=matches, query=query)


def find_relationships_by_type(
    ontology: Dict[str, Any],
    rel_type: str,
    case_sensitive: bool = True,
) -> SearchResult:
    """Find all relationships matching a specific type.
    
    Args:
        ontology: Ontology dict with 'relationships' key
        rel_type: Type to search for
        case_sensitive: If False, case-insensitive matching
    
    Returns:
        SearchResult with matching relationships
    
    Example:
        >>> onto = {"relationships": [{"type": "knows", "id": "r1"}]}
        >>> result = find_relationships_by_type(onto, "knows")
        >>> result.count
        1
    """
    relationships = ontology.get("relationships", [])
    matches = []
    
    search_type = rel_type if case_sensitive else rel_type.lower()
    
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        
        rt = rel.get("type")
        if case_sensitive:
            if rt == search_type:
                matches.append(rel)
        else:
            if isinstance(rt, str) and rt.lower() == search_type:
                matches.append(rel)
    
    return SearchResult(matches=matches, query=f"type:{rel_type}")


def find_entity_neighbors(
    ontology: Dict[str, Any],
    entity_id: str,
    direction: str = "both",
) -> List[Dict[str, Any]]:
    """Find all relationships involving a specific entity.
    
    Args:
        ontology: Ontology dict with 'relationships' key
        entity_id: Entity ID to search for
        direction: 'in' (incoming), 'out' (outgoing), or 'both'
    
    Returns:
        List of relationship dicts involving the entity
    
    Example:
        >>> onto = {"relationships": [
        ...     {"id": "r1", "source_id": "e1", "target_id": "e2"}
        ... ]}
        >>> neighbors = find_entity_neighbors(onto, "e1", "out")
        >>> len(neighbors)
        1
    """
    relationships = ontology.get("relationships", [])
    matches = []
    
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        
        source = rel.get("source_id")
        target = rel.get("target_id")
        
        if direction == "both":
            if entity_id in (source, target):
                matches.append(rel)
        elif direction == "out":
            if source == entity_id:
                matches.append(rel)
        elif direction == "in":
            if target == entity_id:
                matches.append(rel)
    
    return matches


def find_path_between(
    ontology: Dict[str, Any],
    source_id: str,
    target_id: str,
    max_depth: int = 10,
) -> PathResult:
    """Find a path of relationships connecting two entities.
    
    Uses breadth-first search to find the shortest path between source
    and target entities via relationship edges.
    
    Args:
        ontology: Ontology dict with 'relationships' key
        source_id: Starting entity ID
        target_id: Target entity ID
        max_depth: Maximum search depth
    
    Returns:
        PathResult with path information (empty if no path found)
    
    Example:
        >>> onto = {"relationships": [
        ...     {"id": "r1", "source_id": "e1", "target_id": "e2"},
        ...     {"id": "r2", "source_id": "e2", "target_id": "e3"},
        ... ]}
        >>> path = find_path_between(onto, "e1", "e3")
        >>> path.distance
        2
    """
    if source_id == target_id:
        return PathResult(path=[source_id], relationships=[])
    
    relationships = ontology.get("relationships", [])
    
    # Build adjacency map
    graph: Dict[str, List[Tuple[str, str]]] = {}  # entity_id -> [(neighbor_id, rel_id)]
    
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        
        source = rel.get("source_id")
        target = rel.get("target_id")
        rel_id = rel.get("id")
        
        if source and target and rel_id:
            # Add both directions
            if source not in graph:
                graph[source] = []
            graph[source].append((target, rel_id))
            
            if target not in graph:
                graph[target] = []
            graph[target].append((source, rel_id))
    
    # BFS to find shortest path
    from collections import deque
    
    queue: deque = deque([(source_id, [source_id], [])])
    visited: Set[str] = {source_id}
    
    while queue and len(visited) <= max_depth:
        current, path, rel_path = queue.popleft()
        
        for neighbor, rel_id in graph.get(current, []):
            if neighbor == target_id:
                # Found target
                final_path = path + [neighbor]
                final_rel_path = rel_path + [rel_id]
                return PathResult(path=final_path, relationships=final_rel_path)
            
            if neighbor not in visited and len(visited) < max_depth:
                visited.add(neighbor)
                queue.append((neighbor, path + [neighbor], rel_path + [rel_id]))
    
    # No path found
    return PathResult()


def count_entities_by_type(ontology: Dict[str, Any]) -> Dict[str, int]:
    """Count entities by their type.
    
    Args:
        ontology: Ontology dict with 'entities' key
    
    Returns:
        Dict mapping type -> count
    
    Example:
        >>> onto = {"entities": [{"type": "Person"}, {"type": "Person"}]}
        >>> counts = count_entities_by_type(onto)
        >>> counts["Person"]
        2
    """
    entities = ontology.get("entities", [])
    counts: Dict[str, int] = {}
    
    for entity in entities:
        if isinstance(entity, dict) and "type" in entity:
            entity_type = entity["type"]
            counts[entity_type] = counts.get(entity_type, 0) + 1
    
    return counts


def count_relationships_by_type(ontology: Dict[str, Any]) -> Dict[str, int]:
    """Count relationships by their type.
    
    Args:
        ontology: Ontology dict with 'relationships' key
    
    Returns:
        Dict mapping type -> count
    
    Example:
        >>> onto = {"relationships": [{"type": "knows"}, {"type": "works_at"}]}
        >>> counts = count_relationships_by_type(onto)
        >>> counts["knows"]
        1
    """
    relationships = ontology.get("relationships", [])
    counts: Dict[str, int] = {}
    
    for rel in relationships:
        if isinstance(rel, dict) and "type" in rel:
            rel_type = rel["type"]
            counts[rel_type] = counts.get(rel_type, 0) + 1
    
    return counts


def get_related_entities(
    ontology: Dict[str, Any],
    entity_id: str,
    relationship_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Get all entities related to a given entity via relationships.
    
    Args:
        ontology: Ontology dict
        entity_id: Entity ID to find neighbors of
        relationship_type: Optional filter by relationship type
    
    Returns:
        List of related entity dicts
    
    Example:
        >>> onto = {
        ...     "entities": [{"id": "e1"}, {"id": "e2"}],
        ...     "relationships": [{"source_id": "e1", "target_id": "e2"}]
        ... }
        >>> related = get_related_entities(onto, "e1")
        >>> len(related)
        1
    """
    relationships = find_entity_neighbors(ontology, entity_id, direction="both")
    
    if relationship_type:
        relationships = [r for r in relationships if r.get("type") == relationship_type]
    
    # Extract entity IDs from relationships
    entity_ids: Set[str] = set()
    for rel in relationships:
        source = rel.get("source_id")
        target = rel.get("target_id")
        
        if source != entity_id:
            entity_ids.add(source)
        if target != entity_id:
            entity_ids.add(target)
    
    # Find matching entities
    entities = ontology.get("entities", [])
    related = [e for e in entities if isinstance(e, dict) and e.get("id") in entity_ids]
    
    return related
