"""Completeness scoring for GraphRAG ontology critic."""

from __future__ import annotations

from typing import Any, Dict, Optional


def evaluate_completeness(
    ontology: Dict[str, Any],
    context: Any,
    source_data: Optional[Any],
) -> float:
    """Evaluate completeness of ontology.

    Assesses how well the ontology covers key concepts and relationships
    in the domain and source data.

    When *source_data* is a non-empty string, an extra sub-score measures
    what fraction of extracted entity texts appear verbatim in the source.
    """
    entities = ontology.get("entities", [])
    relationships = ontology.get("relationships", [])

    if not entities:
        return 0.0

    # Sub-score 1: entity count (target >= 10 for "complete")
    entity_count_score = min(len(entities) / 10.0, 1.0)

    # Sub-score 2: relationship density (>= 1 rel per entity)
    rel_density_score = min(len(relationships) / max(len(entities), 1), 1.0)

    # Sub-score 3: entity-type diversity (at least 3 distinct types)
    types = {e.get("type") for e in entities if isinstance(e, dict) and e.get("type")}
    diversity_score = min(len(types) / 3.0, 1.0)

    # Sub-score 4: orphan penalty (entities with no relationships)
    entity_ids_in_rels: set = set()
    for rel in relationships:
        if isinstance(rel, dict):
            entity_ids_in_rels.add(rel.get("source_id"))
            entity_ids_in_rels.add(rel.get("target_id"))
    entity_ids = {e.get("id") for e in entities if isinstance(e, dict)}
    orphan_ratio = len(entity_ids - entity_ids_in_rels) / max(len(entity_ids), 1)
    orphan_penalty = max(0.0, 1.0 - orphan_ratio)

    # Sub-score 5 (optional): source coverage -- fraction of entity texts found in source
    source_coverage_score: Optional[float] = None
    if isinstance(source_data, str) and source_data:
        src_lower = source_data.lower()
        covered = sum(
            1
            for e in entities
            if isinstance(e, dict)
            and (e.get("text") or "").lower()
            and (e.get("text") or "").lower() in src_lower
        )
        source_coverage_score = covered / len(entities)

    if source_coverage_score is not None:
        score = (
            entity_count_score * 0.25
            + rel_density_score * 0.25
            + diversity_score * 0.15
            + orphan_penalty * 0.15
            + source_coverage_score * 0.20
        )
    else:
        score = (
            entity_count_score * 0.3
            + rel_density_score * 0.3
            + diversity_score * 0.2
            + orphan_penalty * 0.2
        )
    return round(min(max(score, 0.0), 1.0), 4)
