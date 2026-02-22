"""Statistics and insights module for ontology analysis.

Provides comprehensive statistical analysis of ontologies including:
- Entity distribution and property coverage
- Relationship density and connectivity
- Quality indicators
- Summary reports
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set
from collections import Counter


@dataclass
class EntityStats:
    """Statistics about entities in an ontology."""
    
    total_count: int
    type_distribution: Dict[str, int]
    avg_properties_per_entity: float
    property_coverage_ratio: float  # Entities with at least one property / total
    orphaned_count: int = 0  # Entities with no relationships
    
    def has_diversity(self) -> bool:
        """Return True if entity types are diverse (>2 unique types)."""
        return len(self.type_distribution) > 2
    
    def __repr__(self) -> str:
        """Return concise representation."""
        return (
            f"EntityStats(count={self.total_count}, "
            f"types={len(self.type_distribution)}, "
            f"orphaned={self.orphaned_count})"
        )


@dataclass
class RelationshipStats:
    """Statistics about relationships in an ontology."""
    
    total_count: int
    type_distribution: Dict[str, int]
    avg_relationships_per_entity: float
    relationship_density: float  # Relationships / (entities^2)
    connected_components: int = 1
    
    def is_sparse(self) -> bool:
        """Return True if relationship density < 0.1 (sparse graph)."""
        return self.relationship_density < 0.1
    
    def is_dense(self) -> bool:
        """Return True if relationship density > 0.5 (dense graph)."""
        return self.relationship_density > 0.5
    
    def __repr__(self) -> str:
        """Return concise representation."""
        return (
            f"RelationshipStats(count={self.total_count}, "
            f"types={len(self.type_distribution)}, "
            f"density={self.relationship_density:.3f})"
        )


@dataclass
class OntologyStats:
    """Comprehensive statistics for an ontology."""
    
    entities: EntityStats
    relationships: RelationshipStats
    total_properties_count: int = 0
    unique_property_names: int = 0
    avg_confidence_score: float = 0.5
    
    def __repr__(self) -> str:
        """Return concise representation."""
        return (
            f"OntologyStats({self.entities.total_count} entities, "
            f"{self.relationships.total_count} relationships, "
            f"density={self.relationships.relationship_density:.3f})"
        )


@dataclass
class QualityMetrics:
    """Quality assessment metrics for ontologies."""
    
    completeness_score: float  # 0.0-1.0: Entity diversity, property coverage
    connectivity_score: float  # 0.0-1.0: Relationship density, connect components
    consistency_score: float   # 0.0-1.0: No orphaned entities, type diversity
    overall_quality: float     # Weighted average of above
    issues: List[str] = field(default_factory=list)  # Quality concern descriptions
    suggestions: List[str] = field(default_factory=list)  # Improvement suggestions
    
    def is_high_quality(self) -> bool:
        """Return True if overall quality >= 0.7."""
        return self.overall_quality >= 0.7
    
    def is_low_quality(self) -> bool:
        """Return True if overall quality <= 0.4."""
        return self.overall_quality <= 0.4
    
    def __repr__(self) -> str:
        """Return concise representation."""
        return (
            f"QualityMetrics(overall={self.overall_quality:.2f}, "
            f"completeness={self.completeness_score:.2f}, "
            f"connectivity={self.connectivity_score:.2f}, "
            f"consistency={self.consistency_score:.2f})"
        )


def compute_entity_stats(ontology: Dict[str, Any]) -> EntityStats:
    """Compute entity statistics.
    
    Args:
        ontology: Ontology dictionary with 'entities' and 'relationships' keys
        
    Returns:
        EntityStats dataclass with computed metrics
    """
    entities = ontology.get("entities", [])
    relationships = ontology.get("relationships", [])
    
    if not isinstance(entities, list):
        entities = []
    if not isinstance(relationships, list):
        relationships = []
    
    # Total count
    total = len(entities)
    
    # Type distribution
    type_dist = Counter()
    property_coverage = 0
    total_properties = 0
    
    entity_ids = set()
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        
        ent_id = entity.get("id")
        if ent_id:
            entity_ids.add(ent_id)
        
        ent_type = entity.get("type")
        if ent_type:
            type_dist[ent_type] += 1
        
        props = entity.get("properties")
        if isinstance(props, dict) and props:
            property_coverage += 1
            total_properties += len(props)
    
    # Orphaned entities
    related_ids = set()
    for rel in relationships:
        if isinstance(rel, dict):
            src = rel.get("source_id")
            tgt = rel.get("target_id")
            if src:
                related_ids.add(src)
            if tgt:
                related_ids.add(tgt)
    
    orphaned = len(entity_ids - related_ids)
    
    # Compute averages
    avg_properties = total_properties / total if total > 0 else 0.0
    coverage_ratio = property_coverage / total if total > 0 else 0.0
    
    return EntityStats(
        total_count=total,
        type_distribution=dict(type_dist),
        avg_properties_per_entity=avg_properties,
        property_coverage_ratio=coverage_ratio,
        orphaned_count=orphaned,
    )


def compute_relationship_stats(ontology: Dict[str, Any]) -> RelationshipStats:
    """Compute relationship statistics.
    
    Args:
        ontology: Ontology dictionary with 'entities' and 'relationships' keys
        
    Returns:
        RelationshipStats dataclass with computed metrics
    """
    entities = ontology.get("entities", [])
    relationships = ontology.get("relationships", [])
    
    if not isinstance(entities, list):
        entities = []
    if not isinstance(relationships, list):
        relationships = []
    
    # Total count
    entity_count = len(entities)
    rel_count = len(relationships)
    
    # Type distribution
    rel_type_dist = Counter()
    for rel in relationships:
        if isinstance(rel, dict):
            rel_type = rel.get("type")
            if rel_type:
                rel_type_dist[rel_type] += 1
    
    # Density (relationships / max_possible_relationships)
    # Max possible is entity_count * (entity_count - 1) for directed graph
    max_possible = entity_count * (entity_count - 1) if entity_count > 1 else 1
    density = rel_count / max_possible
    
    # Average relationships per entity
    avg_rel = rel_count / entity_count if entity_count > 0 else 0.0
    
    return RelationshipStats(
        total_count=rel_count,
        type_distribution=dict(rel_type_dist),
        avg_relationships_per_entity=avg_rel,
        relationship_density=density,
    )


def compute_quality_metrics(
    entity_stats: EntityStats,
    relationship_stats: RelationshipStats,
) -> QualityMetrics:
    """Compute quality metrics based on entity and relationship statistics.
    
    Args:
        entity_stats: EntityStats computed from ontology
        relationship_stats: RelationshipStats computed from ontology
        
    Returns:
        QualityMetrics with scores and recommendations
    """
    issues = []
    suggestions = []
    
    # Completeness: entity diversity + property coverage
    type_diversity_score = min(1.0, len(entity_stats.type_distribution) / 5.0)  # scale: 5+ types = 1.0
    property_score = entity_stats.property_coverage_ratio
    completeness = (type_diversity_score + property_score) / 2.0
    
    if type_diversity_score < 0.5:
        suggestions.append(f"Entity type diversity is low ({len(entity_stats.type_distribution)} types); add more entity types")
    if entity_stats.property_coverage_ratio < 0.5:
        issues.append("Less than 50% of entities have properties")
        suggestions.append("Add properties to more entities for better documentation")
    
    # Connectivity: relationship density + connected components
    # Ideal density is around 0.1-0.3 for most ontologies
    if relationship_stats.relationship_density < 0.01:
        connectivity = 0.2  # Very sparse
        issues.append("Ontology is extremely sparse (<<1% edge density)")
    elif relationship_stats.relationship_density < 0.05:
        connectivity = 0.5  # Sparse but acceptable
        suggestions.append("Consider adding more relationships to increase connectivity")
    elif relationship_stats.relationship_density < 0.5:
        connectivity = 1.0  # Good density
    else:
        connectivity = 0.8  # Dense, might be too connected
        suggestions.append("Ontology is densely connected; consider breaking into sub-ontologies")
    
    # Consistency: low orphaned count, type diversity
    if entity_stats.total_count > 0:
        orphan_ratio = entity_stats.orphaned_count / entity_stats.total_count
    else:
        orphan_ratio = 0.0
    
    if orphan_ratio > 0.3:
        consistency = 0.3
        issues.append(f"High orphan rate ({orphan_ratio:.1%} of entities have no relationships)")
        suggestions.append("Link orphaned entities to the main graph")
    elif orphan_ratio > 0.1:
        consistency = 0.6
        suggestions.append(f"Consider linking orphaned entities ({orphan_ratio:.1%} of total)")
    else:
        consistency = 0.9
    
    # Overall quality: weighted average
    overall = (completeness * 0.3 + connectivity * 0.4 + consistency * 0.3)
    
    return QualityMetrics(
        completeness_score=min(1.0, completeness),
        connectivity_score=min(1.0, connectivity),
        consistency_score=min(1.0, consistency),
        overall_quality=min(1.0, overall),
        issues=issues,
        suggestions=suggestions,
    )


def compute_ontology_stats(ontology: Dict[str, Any]) -> OntologyStats:
    """Compute comprehensive ontology statistics.
    
    Args:
        ontology: Ontology dictionary with 'entities' and 'relationships' keys
        
    Returns:
        OntologyStats with all metrics
    """
    entity_stats = compute_entity_stats(ontology)
    relationship_stats = compute_relationship_stats(ontology)
    
    # Property analysis
    entities = ontology.get("entities", [])
    prop_names = set()
    total_props = 0
    conf_scores = []
    
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        
        props = entity.get("properties")
        if isinstance(props, dict):
            total_props += len(props)
            prop_names.update(props.keys())
        
        conf = entity.get("confidence")
        if isinstance(conf, (int, float)):
            conf_scores.append(conf)
    
    avg_conf = sum(conf_scores) / len(conf_scores) if conf_scores else 0.5
    
    return OntologyStats(
        entities=entity_stats,
        relationships=relationship_stats,
        total_properties_count=total_props,
        unique_property_names=len(prop_names),
        avg_confidence_score=avg_conf,
    )


def generate_stats_report(
    ontology: Dict[str, Any],
    verbose: bool = False,
) -> str:
    """Generate a human-readable statistics report.
    
    Args:
        ontology: Ontology dictionary
        verbose: If True, include detailed suggestions and issues
        
    Returns:
        Formatted report string
    """
    stats = compute_ontology_stats(ontology)
    quality = compute_quality_metrics(stats.entities, stats.relationships)
    
    lines = [
        "=" * 70,
        "ONTOLOGY STATISTICS REPORT",
        "=" * 70,
        "",
        "ENTITY SUMMARY",
        f"  Total Entities: {stats.entities.total_count}",
        f"  Entity Types: {len(stats.entities.type_distribution)}",
        f"  Avg Properties/Entity: {stats.entities.avg_properties_per_entity:.2f}",
        f"  Property Coverage: {stats.entities.property_coverage_ratio:.1%}",
        f"  Orphaned Entities: {stats.entities.orphaned_count}",
        "",
        "RELATIONSHIP SUMMARY",
        f"  Total Relationships: {stats.relationships.total_count}",
        f"  Relationship Types: {len(stats.relationships.type_distribution)}",
        f"  Avg Rel/Entity: {stats.relationships.avg_relationships_per_entity:.2f}",
        f"  Density: {stats.relationships.relationship_density:.4f}",
        "",
        "PROPERTY SUMMARY",
        f"  Total Properties: {stats.total_properties_count}",
        f"  Unique Property Names: {stats.unique_property_names}",
        f"  Avg Confidence: {stats.avg_confidence_score:.2f}",
        "",
        "QUALITY ASSESSMENT",
        f"  Overall Quality: {quality.overall_quality:.2f}/1.00",
        f"  Completeness: {quality.completeness_score:.2f}",
        f"  Connectivity: {quality.connectivity_score:.2f}",
        f"  Consistency: {quality.consistency_score:.2f}",
    ]
    
    if verbose:
        if quality.issues:
            lines.extend(["", "ISSUES DETECTED"])
            for issue in quality.issues:
                lines.append(f"  ⚠️  {issue}")
        
        if quality.suggestions:
            lines.extend(["", "SUGGESTIONS"])
            for suggestion in quality.suggestions:
                lines.append(f"  💡 {suggestion}")
    
    lines.extend(["", "=" * 70])
    
    return "\n".join(lines)


def get_entity_type_distribution(ontology: Dict[str, Any]) -> Dict[str, float]:
    """Get entity type distribution as fractions.
    
    Args:
        ontology: Ontology dictionary
        
    Returns:
        Dict mapping type name to fraction (0.0-1.0)
    """
    stats = compute_entity_stats(ontology)
    total = stats.total_count
    
    if total == 0:
        return {}
    
    return {
        type_name: count / total
        for type_name, count in stats.type_distribution.items()
    }


def get_relationship_type_distribution(ontology: Dict[str, Any]) -> Dict[str, float]:
    """Get relationship type distribution as fractions.
    
    Args:
        ontology: Ontology dictionary
        
    Returns:
        Dict mapping type name to fraction (0.0-1.0)
    """
    stats = compute_relationship_stats(ontology)
    total = stats.total_count
    
    if total == 0:
        return {}
    
    return {
        type_name: count / total
        for type_name, count in stats.type_distribution.items()
    }


def identify_bottlenecks(ontology: Dict[str, Any]) -> Dict[str, Any]:
    """Identify entities or relationships that might be bottlenecks.
    
    Args:
        ontology: Ontology dictionary
        
    Returns:
        Dict with bottleneck analysis
    """
    entities = ontology.get("entities", [])
    relationships = ontology.get("relationships", [])
    
    if not isinstance(entities, list) or not isinstance(relationships, list):
        return {}
    
    # Count relationships per entity
    entity_rel_count = Counter()
    for rel in relationships:
        if isinstance(rel, dict):
            src = rel.get("source_id")
            tgt = rel.get("target_id")
            if src:
                entity_rel_count[src] += 1
            if tgt:
                entity_rel_count[tgt] += 1
    
    # Find high-degree entities (hubs)
    if entity_rel_count:
        avg_degree = sum(entity_rel_count.values()) / len(entity_rel_count)
        high_degree_entities = {
            ent_id: count
            for ent_id, count in entity_rel_count.most_common(5)
            if count > avg_degree * 2
        }
    else:
        high_degree_entities = {}
    
    # Count relationship types
    rel_type_count = Counter()
    for rel in relationships:
        if isinstance(rel, dict):
            rel_type = rel.get("type")
            if rel_type:
                rel_type_count[rel_type] += 1
    
    bottleneck_rel_types = {
        rel_type: count
        for rel_type, count in rel_type_count.most_common(3)
    }
    
    return {
        "high_degree_entities": high_degree_entities,
        "bottleneck_relationship_types": bottleneck_rel_types,
    }
