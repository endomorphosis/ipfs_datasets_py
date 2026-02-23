"""Connectivity scoring for GraphRAG ontology critic."""

from __future__ import annotations

from typing import Any, Dict


def evaluate_relationship_coherence(
    ontology: Dict[str, Any],
    context: Any,
) -> float:
    """Evaluate the semantic coherence and quality of relationships.

    Checks for well-formed relationship types, appropriate directionality,
    balanced relationship distribution, and semantic consistency.
    """
    entities = ontology.get("entities", [])
    relationships = ontology.get("relationships", [])

    if not relationships:
        # No relationships to evaluate
        return 0.3 if entities else 0.5

    # Sub-score 1: Type quality - check for meaningful relationship types
    rel_types = [r.get("type", "") for r in relationships if isinstance(r, dict)]
    _GENERIC_RELS = {"relates_to", "related_to", "links", "connected", "associated", "rel"}
    _MEANINGFUL_PATTERNS = {
        "has_",
        "is_",
        "contains_",
        "performs_",
        "implements_",
        "manages_",
        "causes_",
        "affects_",
        "depends_on",
        "requires_",
        "uses_",
        "provides_",
    }

    meaningful = sum(
        1
        for rt in rel_types
        if rt
        and len(rt) > 3
        and rt.lower() not in _GENERIC_RELS
        and any(pattern in rt.lower() for pattern in _MEANINGFUL_PATTERNS)
    )
    specific_but_not_generic = sum(
        1 for rt in rel_types if rt and len(rt) > 3 and rt.lower() not in _GENERIC_RELS
    )
    type_quality_score = (
        (meaningful / len(rel_types)) * 0.7 + (specific_but_not_generic / len(rel_types)) * 0.3
    ) if rel_types else 0.0

    # Sub-score 2: Directionality
    directed_count = sum(
        1
        for r in relationships
        if isinstance(r, dict) and r.get("source_id") != r.get("target_id")
    )
    directionality_score = directed_count / len(relationships) if relationships else 0.5

    # Sub-score 3: Distribution balance
    unique_types = set(rt for rt in rel_types if rt)
    if len(relationships) < 5:
        distribution_score = min(len(unique_types) / 2.0, 1.0)
    elif len(relationships) < 10:
        distribution_score = min(len(unique_types) / 3.0, 1.0)
    else:
        distribution_score = min(len(unique_types) / 5.0, 1.0)

    # Sub-score 4: Semantic consistency
    _TYPE_AFFINITY: Dict[str, set] = {
        "manages": {"person", "organization", "manager", "team", "department"},
        "located_in": {"location", "place", "address", "city", "region"},
        "has_symptom": {"patient", "person", "condition", "disease"},
        "implements": {"component", "module", "service", "interface", "class"},
        "part_of": {"component", "organization", "location", "structure"},
    }

    entity_type_map = {
        e.get("id"): (e.get("type", "") or "").lower()
        for e in entities
        if isinstance(e, dict) and e.get("id")
    }

    coherent_relationships = 0
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        rel_type = (rel.get("type", "") or "").lower()
        src_id = rel.get("source_id")
        tgt_id = rel.get("target_id")

        if not rel_type or not src_id or not tgt_id:
            continue

        for pattern, expected_types in _TYPE_AFFINITY.items():
            if pattern in rel_type:
                src_type = entity_type_map.get(src_id, "")
                tgt_type = entity_type_map.get(tgt_id, "")
                if any(et in src_type or et in tgt_type for et in expected_types):
                    coherent_relationships += 1
                    break
        else:
            coherent_relationships += 0.5

    semantic_consistency_score = coherent_relationships / len(relationships) if relationships else 0.5

    overall = (
        type_quality_score * 0.35
        + directionality_score * 0.20
        + distribution_score * 0.25
        + semantic_consistency_score * 0.20
    )

    return round(min(max(overall, 0.0), 1.0), 4)
