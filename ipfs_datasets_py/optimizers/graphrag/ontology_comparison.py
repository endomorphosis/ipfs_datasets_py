"""Ontology comparison helpers for analyzing structural differences and similarities.

This module provides utilities to compare two ontologies side-by-side, compute
similarity metrics, and identify patterns in entity/relationship distributions.

Example usage::

    from ipfs_datasets_py.optimizers.graphrag.ontology_comparison import (
        compare_ontologies,
        compute_similarity,
        analyze_entity_distribution,
        analyze_relationship_distribution,
    )
    
    ontology1 = {"entities": [...], "relationships": [...]}
    ontology2 = {"entities": [...], "relationships": [...]}
    
    comparison = compare_ontologies(ontology1, ontology2)
    print(f"Similarity: {comparison['similarity']:.1%}")
    print(f"Common entities: {comparison['entity_overlap']}")

Functions:
    - compare_ontologies: Detailed comparison of two ontologies
    - compute_similarity: Jaccard similarity between ontologies
    - analyze_entity_distribution: Statistics about entity types
    - analyze_relationship_distribution: Statistics about relationship types
    - find_entity_overlap: Find entities appearing in both ontologies
    - find_relationship_overlap: Find relationships in both ontologies
    - extract_type_distribution: Get type counts from entities/relationships
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Set, Tuple


@dataclass
class ComparisonResult:
    """Result of comparing two ontologies.
    
    Attributes:
        entity_overlap: Count of entities (by ID) in both ontologies
        relationship_overlap: Count of relationships (by ID) in both ontologies
        entity_only_left: Entity IDs only in left ontology
        entity_only_right: Entity IDs only in right ontology
        entity_similarity: Jaccard similarity for entities (0.0 to 1.0)
        relationship_similarity: Jaccard similarity for relationships (0.0 to 1.0)
        overall_similarity: Weighted average of entity/relationship similarity
    """
    
    entity_overlap: int = 0
    relationship_overlap: int = 0
    entity_only_left: List[str] = field(default_factory=list)
    entity_only_right: List[str] = field(default_factory=list)
    rel_only_left: List[str] = field(default_factory=list)
    rel_only_right: List[str] = field(default_factory=list)
    entity_similarity: float = 0.0
    relationship_similarity: float = 0.0
    
    @property
    def overall_similarity(self) -> float:
        """Return weighted average of entity and relationship similarity."""
        return (self.entity_similarity + self.relationship_similarity) / 2.0
    
    @property
    def total_entities_union(self) -> int:
        """Return total unique entities across both ontologies."""
        return self.entity_overlap + len(self.entity_only_left) + len(self.entity_only_right)
    
    @property
    def total_relationships_union(self) -> int:
        """Return total unique relationships across both ontologies."""
        return self.relationship_overlap + len(self.rel_only_left) + len(self.rel_only_right)
    
    def __repr__(self) -> str:
        """Return concise representation."""
        return (
            f"ComparisonResult(entity_overlap={self.entity_overlap}, "
            f"rel_overlap={self.relationship_overlap}, "
            f"similarity={self.overall_similarity:.2f})"
        )


@dataclass
class DistributionStats:
    """Statistics about entity or relationship type distribution.
    
    Attributes:
        type_counts: Dict of type -> count
        total_items: Total number of items
        unique_types: Number of unique types
        dominant_type: Most common type
        dominant_type_percentage: Percentage of total for dominant type
    """
    
    type_counts: Dict[str, int] = field(default_factory=dict)
    total_items: int = 0
    
    @property
    def unique_types(self) -> int:
        """Return number of unique types."""
        return len(self.type_counts)
    
    @property
    def dominant_type(self) -> str:
        """Return most common type, or empty string if no items."""
        if not self.type_counts:
            return ""
        return max(self.type_counts, key=self.type_counts.get)
    
    @property
    def dominant_type_percentage(self) -> float:
        """Return percentage of items that are dominant type."""
        if not self.total_items or not self.type_counts:
            return 0.0
        max_count = self.type_counts.get(self.dominant_type, 0)
        return 100.0 * max_count / self.total_items
    
    def __repr__(self) -> str:
        """Return concise representation."""
        return (
            f"DistributionStats(total={self.total_items}, "
            f"types={self.unique_types}, "
            f"dominant={self.dominant_type} {self.dominant_type_percentage:.1f}%)"
        )


def compare_ontologies(
    ontology_left: Dict[str, Any],
    ontology_right: Dict[str, Any],
    entity_weight: float = 0.5,
    relationship_weight: float = 0.5,
) -> ComparisonResult:
    """Compare two ontologies and produce structured comparison.
    
    Computes:
    - Overlap counts (entities and relationships in both)
    - Only-left and only-right IDs
    - Jaccard similarity for both entity and relationship levels
    - Overall weighted similarity
    
    Args:
        ontology_left: First ontology dict
        ontology_right: Second ontology dict
        entity_weight: Weight for entity similarity in overall metric (0.0-1.0)
        relationship_weight: Weight for relationship similarity (should sum to ~1.0)
    
    Returns:
        ComparisonResult with detailed comparison metrics
    
    Example:
        >>> ont1 = {"entities": [{"id": "e1"}], "relationships": []}
        >>> ont2 = {"entities": [{"id": "e1"}], "relationships": []}
        >>> result = compare_ontologies(ont1, ont2)
        >>> result.entity_similarity
        1.0
    """
    result = ComparisonResult()
    
    # Extract entity and relationship IDs
    entities_left = set(
        e.get("id") for e in ontology_left.get("entities", []) if "id" in e
    )
    entities_right = set(
        e.get("id") for e in ontology_right.get("entities", []) if "id" in e
    )
    
    rels_left = set(
        r.get("id") for r in ontology_left.get("relationships", []) if "id" in r
    )
    rels_right = set(
        r.get("id") for r in ontology_right.get("relationships", []) if "id" in r
    )
    
    # Compute overlaps
    entity_overlap = entities_left & entities_right
    entity_union = entities_left | entities_right
    
    rel_overlap = rels_left & rels_right
    rel_union = rels_left | rels_right
    
    # Set result values
    result.entity_overlap = len(entity_overlap)
    result.relationship_overlap = len(rel_overlap)
    result.entity_only_left = sorted(list(entities_left - entities_right))
    result.entity_only_right = sorted(list(entities_right - entities_left))
    result.rel_only_left = sorted(list(rels_left - rels_right))
    result.rel_only_right = sorted(list(rels_right - rels_left))
    
    # Compute Jaccard similarity: |intersection| / |union|
    if entity_union:
        result.entity_similarity = len(entity_overlap) / len(entity_union)
    else:
        result.entity_similarity = 1.0  # Both empty -> identical
    
    if rel_union:
        result.relationship_similarity = len(rel_overlap) / len(rel_union)
    else:
        result.relationship_similarity = 1.0
    
    return result


def compute_similarity(
    ontology_left: Dict[str, Any],
    ontology_right: Dict[str, Any],
) -> float:
    """Compute Jaccard similarity between two ontologies.
    
    Returns a single float (0.0 to 1.0) representing the average
    Jaccard similarity of entities and relationships.
    
    Args:
        ontology_left: First ontology
        ontology_right: Second ontology
    
    Returns:
        Similarity score where 0.0 = completely different, 1.0 = identical
    
    Example:
        >>> ont1 = {"entities": [{"id": "e1"}], "relationships": []}
        >>> ont2 = {"entities": [{"id": "e2"}], "relationships": []}
        >>> similarity = compute_similarity(ont1, ont2)
        >>> 0.0 < similarity < 1.0
        True
    """
    result = compare_ontologies(ontology_left, ontology_right)
    return result.overall_similarity


def analyze_entity_distribution(
    ontology: Dict[str, Any],
) -> DistributionStats:
    """Analyze the distribution of entity types in an ontology.
    
    Counts how many entities of each type are present.
    
    Args:
        ontology: Ontology dict with 'entities' key
    
    Returns:
        DistributionStats with type counts and percentages
    
    Example:
        >>> ont = {
        ...     "entities": [
        ...         {"type": "Person", "id": "e1"},
        ...         {"type": "Person", "id": "e2"},
        ...         {"type": "Location", "id": "e3"},
        ...     ]
        ... }
        >>> dist = analyze_entity_distribution(ont)
        >>> dist.dominant_type
        'Person'
        >>> dist.dominant_type_percentage
        66.66...
    """
    stats = DistributionStats()
    
    entities = ontology.get("entities", [])
    stats.total_items = len(entities)
    
    for entity in entities:
        if isinstance(entity, dict) and "type" in entity:
            entity_type = entity["type"]
            stats.type_counts[entity_type] = stats.type_counts.get(entity_type, 0) + 1
    
    return stats


def analyze_relationship_distribution(
    ontology: Dict[str, Any],
) -> DistributionStats:
    """Analyze the distribution of relationship types in an ontology.
    
    Counts how many relationships of each type are present.
    
    Args:
        ontology: Ontology dict with 'relationships' key
    
    Returns:
        DistributionStats with type counts and percentages
    
    Example:
        >>> ont = {
        ...     "relationships": [
        ...         {"type": "knows", "id": "r1"},
        ...         {"type": "works_at", "id": "r2"},
        ...         {"type": "knows", "id": "r3"},
        ...     ]
        ... }
        >>> dist = analyze_relationship_distribution(ont)
        >>> dist.type_counts['knows']
        2
    """
    stats = DistributionStats()
    
    relationships = ontology.get("relationships", [])
    stats.total_items = len(relationships)
    
    for rel in relationships:
        if isinstance(rel, dict) and "type" in rel:
            rel_type = rel["type"]
            stats.type_counts[rel_type] = stats.type_counts.get(rel_type, 0) + 1
    
    return stats


def find_entity_overlap(
    ontology_left: Dict[str, Any],
    ontology_right: Dict[str, Any],
) -> List[str]:
    """Find entity IDs that appear in both ontologies.
    
    Args:
        ontology_left: First ontology
        ontology_right: Second ontology
    
    Returns:
        Sorted list of entity IDs present in both
    
    Example:
        >>> ont1 = {"entities": [{"id": "e1"}, {"id": "e2"}]}
        >>> ont2 = {"entities": [{"id": "e1"}, {"id": "e3"}]}
        >>> find_entity_overlap(ont1, ont2)
        ['e1']
    """
    entities_left = set(
        e.get("id") for e in ontology_left.get("entities", []) if "id" in e
    )
    entities_right = set(
        e.get("id") for e in ontology_right.get("entities", []) if "id" in e
    )
    
    overlap = entities_left & entities_right
    return sorted(list(overlap))


def find_relationship_overlap(
    ontology_left: Dict[str, Any],
    ontology_right: Dict[str, Any],
) -> List[str]:
    """Find relationship IDs that appear in both ontologies.
    
    Args:
        ontology_left: First ontology
        ontology_right: Second ontology
    
    Returns:
        Sorted list of relationship IDs present in both
    
    Example:
        >>> ont1 = {"relationships": [{"id": "r1"}, {"id": "r2"}]}
        >>> ont2 = {"relationships": [{"id": "r1"}, {"id": "r3"}]}
        >>> find_relationship_overlap(ont1, ont2)
        ['r1']
    """
    rels_left = set(
        r.get("id") for r in ontology_left.get("relationships", []) if "id" in r
    )
    rels_right = set(
        r.get("id") for r in ontology_right.get("relationships", []) if "id" in r
    )
    
    overlap = rels_left & rels_right
    return sorted(list(overlap))


def extract_type_distribution(items: List[Dict[str, Any]]) -> Dict[str, int]:
    """Extract type distribution from a list of items (entities or relationships).
    
    Args:
        items: List of dicts with 'type' field
    
    Returns:
        Dict mapping type -> count
    
    Example:
        >>> items = [{"type": "A"}, {"type": "B"}, {"type": "A"}]
        >>> extract_type_distribution(items)
        {'A': 2, 'B': 1}
    """
    distribution: Dict[str, int] = {}
    
    for item in items:
        if isinstance(item, dict) and "type" in item:
            item_type = item["type"]
            distribution[item_type] = distribution.get(item_type, 0) + 1
    
    return distribution


def format_comparison_result(result: ComparisonResult, verbose: bool = False) -> str:
    """Format comparison result as human-readable string.
    
    Args:
        result: ComparisonResult to format
        verbose: If True, include detailed breakdowns
    
    Returns:
        Formatted string
    
    Example:
        >>> result = ComparisonResult(entity_overlap=5, entity_similarity=0.8)
        >>> formatted = format_comparison_result(result)
        >>> "80.0%" in formatted
        True
    """
    lines = []
    lines.append("Ontology Comparison")
    lines.append("=" * 40)
    lines.append("")
    
    # Summary
    lines.append(f"Overall Similarity: {result.overall_similarity:.1%}")
    lines.append(f"  Entity Similarity:       {result.entity_similarity:.1%}")
    lines.append(f"  Relationship Similarity: {result.relationship_similarity:.1%}")
    lines.append("")
    
    # Overlap counts
    lines.append("Overlaps:")
    lines.append(f"  Shared Entities:       {result.entity_overlap}")
    lines.append(f"  Shared Relationships:  {result.relationship_overlap}")
    lines.append("")
    
    if verbose:
        # Only-left
        if result.entity_only_left:
            lines.append(f"Only in Left ({len(result.entity_only_left)} entities):")
            for eid in result.entity_only_left[:5]:  # Show first 5
                lines.append(f"  - {eid}")
            if len(result.entity_only_left) > 5:
                lines.append(f"  ... and {len(result.entity_only_left) - 5} more")
            lines.append("")
        
        # Only-right
        if result.entity_only_right:
            lines.append(f"Only in Right ({len(result.entity_only_right)} entities):")
            for eid in result.entity_only_right[:5]:
                lines.append(f"  - {eid}")
            if len(result.entity_only_right) > 5:
                lines.append(f"  ... and {len(result.entity_only_right) - 5} more")
    else:
        # Summary line
        left_count = len(result.entity_only_left)
        right_count = len(result.entity_only_right)
        if left_count or right_count:
            lines.append(
                f"Unique to Left: {left_count} entities, {len(result.rel_only_left)} relationships"
            )
            lines.append(
                f"Unique to Right: {right_count} entities, {len(result.rel_only_right)} relationships"
            )
    
    return "\n".join(lines)
