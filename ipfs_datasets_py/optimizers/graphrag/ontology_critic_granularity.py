"""Granularity dimension evaluation for OntologyCritic."""

from __future__ import annotations

from typing import Any, Dict


def evaluate_granularity(ontology: Dict[str, Any], context: Any) -> float:
    """Evaluate appropriateness of detail level.

    Scores based on average properties-per-entity and relationship-to-entity ratio.
    """
    entities = ontology.get("entities", [])
    relationships = ontology.get("relationships", [])

    if not entities:
        return 0.0

    # Target: ~3 properties per entity is "good granularity"
    target_props = 3.0
    prop_counts = [
        len(e.get("properties", {}))
        for e in entities if isinstance(e, dict)
    ]
    avg_props = sum(prop_counts) / max(len(prop_counts), 1)
    prop_score = min(avg_props / target_props, 1.0)

    # Target: ~1.5 relationships per entity
    target_rels = 1.5
    rel_ratio = len(relationships) / max(len(entities), 1)
    rel_score = min(rel_ratio / target_rels, 1.0)

    # Penalty for entities with zero properties (too coarse)
    no_props = sum(1 for c in prop_counts if c == 0)
    coarseness_penalty = no_props / max(len(entities), 1) * 0.3

    score = prop_score * 0.45 + rel_score * 0.4 - coarseness_penalty
    return round(min(max(score, 0.0), 1.0), 4)
