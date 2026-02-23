"""Insight generation for GraphRAG ontology criticism.

This module provides functions to generate insights about ontology quality,
including identification of strengths and weaknesses and recommendations for
improvement based on dimension scores.

The functions here are designed to be used by OntologyCritic to provide
actionable feedback to users.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def identify_strengths(
    completeness: float,
    consistency: float,
    clarity: float,
    granularity: float,
    relationship_coherence: float,
    domain_alignment: float
) -> List[str]:
    """Identify ontology strengths based on dimension scores.

    Args:
        completeness: Completeness score in [0.0, 1.0].
        consistency: Consistency score in [0.0, 1.0].
        clarity: Clarity score in [0.0, 1.0].
        granularity: Granularity score in [0.0, 1.0].
        relationship_coherence: Relationship coherence score in [0.0, 1.0].
        domain_alignment: Domain alignment score in [0.0, 1.0].

    Returns:
        List of strength descriptions for dimensions scoring >= 0.8.
    """
    strengths = []

    threshold = 0.8

    if completeness >= threshold:
        strengths.append("Comprehensive entity and relationship coverage")
    if consistency >= threshold:
        strengths.append("Strong internal logical consistency")
    if clarity >= threshold:
        strengths.append("Clear and well-defined entities")
    if granularity >= threshold:
        strengths.append("Appropriate level of detail")
    if relationship_coherence >= threshold:
        strengths.append("High-quality, semantically coherent relationships")
    if domain_alignment >= threshold:
        strengths.append("Good adherence to domain conventions")

    return strengths


def identify_weaknesses(
    completeness: float,
    consistency: float,
    clarity: float,
    granularity: float,
    relationship_coherence: float,
    domain_alignment: float
) -> List[str]:
    """Identify ontology weaknesses based on dimension scores.

    Args:
        completeness: Completeness score in [0.0, 1.0].
        consistency: Consistency score in [0.0, 1.0].
        clarity: Clarity score in [0.0, 1.0].
        granularity: Granularity score in [0.0, 1.0].
        relationship_coherence: Relationship coherence score in [0.0, 1.0].
        domain_alignment: Domain alignment score in [0.0, 1.0].

    Returns:
        List of weakness descriptions for dimensions scoring < 0.6.
    """
    weaknesses = []

    threshold = 0.6

    if completeness < threshold:
        weaknesses.append("Incomplete coverage of key concepts")
    if consistency < threshold:
        weaknesses.append("Logical inconsistencies detected")
    if clarity < threshold:
        weaknesses.append("Unclear or ambiguous entity definitions")
    if granularity < threshold:
        weaknesses.append("Inappropriate level of detail")
    if relationship_coherence < threshold:
        weaknesses.append("Poor relationship quality or semantic incoherence")
    if domain_alignment < threshold:
        weaknesses.append("Poor alignment with domain conventions")

    return weaknesses


def generate_recommendations(
    ontology: Dict[str, Any],
    context: Any,
    completeness: float,
    consistency: float,
    clarity: float,
    granularity: float,
    relationship_coherence: float,
    domain_alignment: float
) -> List[str]:
    """Generate specific, actionable recommendations for improvement.

    Recommendations are tailored to the actual ontology content rather than
    being generic -- they cite entity counts, missing properties, dangling
    references, etc.

    Args:
        ontology: The ontology dict containing 'entities' and 'relationships'.
        context: The optimization context (used for domain info if available).
        completeness: Completeness score in [0.0, 1.0].
        consistency: Consistency score in [0.0, 1.0].
        clarity: Clarity score in [0.0, 1.0].
        granularity: Granularity score in [0.0, 1.0].
        relationship_coherence: Relationship coherence score in [0.0, 1.0].
        domain_alignment: Domain alignment score in [0.0, 1.0].

    Returns:
        List of actionable recommendation strings.
    """
    recommendations: List[str] = []

    entities = ontology.get('entities', [])
    relationships = ontology.get('relationships', [])
    entity_ids = {e.get('id') for e in entities if isinstance(e, dict) and e.get('id')}

    # -- Completeness recommendations -------------------------------------
    if completeness < 0.7:
        n = len(entities)
        if n == 0:
            recommendations.append(
                "No entities found. Extract key concepts and named entities from the source data."
            )
        elif n < 5:
            recommendations.append(
                f"Only {n} entit{'y' if n == 1 else 'ies'} extracted -- aim for at least 10 "
                "to ensure adequate coverage."
            )

        n_rels = len(relationships)
        if n > 0 and n_rels == 0:
            recommendations.append(
                f"No relationships defined for {n} entities. "
                "Add at least one relationship per entity to improve connectivity."
            )
        elif n > 0 and n_rels < n * 0.5:
            recommendations.append(
                f"Relationship density is low ({n_rels} relationships for {n} entities). "
                "Aim for at least one relationship per entity."
            )

        types = {e.get('type') for e in entities if isinstance(e, dict) and e.get('type')}
        if len(types) < 2:
            recommendations.append(
                "All entities share the same type. "
                "Introduce multiple entity types (e.g. Person, Organization, Concept) for richer semantics."
            )

    # -- Consistency recommendations ---------------------------------------
    if consistency < 0.7:
        dangling = [
            r for r in relationships
            if isinstance(r, dict)
            and (r.get('source_id') not in entity_ids or r.get('target_id') not in entity_ids)
        ]
        if dangling:
            rel_ids = [r.get('id', '?') for r in dangling[:3]]
            recommendations.append(
                f"{len(dangling)} relationship(s) have dangling references "
                f"(e.g. {', '.join(str(r) for r in rel_ids)}). "
                "Ensure all source_id / target_id values match existing entity IDs."
            )

        all_ids = [e.get('id') for e in entities if isinstance(e, dict) and e.get('id')]
        dupes = len(all_ids) - len(set(all_ids))
        if dupes > 0:
            recommendations.append(
                f"{dupes} duplicate entity ID(s) detected. "
                "Assign unique IDs to prevent ambiguous references."
            )

    # -- Clarity recommendations -------------------------------------------
    if clarity < 0.7:
        no_props = [e for e in entities if isinstance(e, dict) and not e.get('properties')]
        if len(no_props) > len(entities) * 0.5:
            recommendations.append(
                f"{len(no_props)} of {len(entities)} entities lack properties. "
                "Add descriptive properties (e.g. role, description, domain) to improve interpretability."
            )

        no_text = [e for e in entities if isinstance(e, dict) and not e.get('text')]
        if no_text:
            recommendations.append(
                f"{len(no_text)} entit{'y' if len(no_text) == 1 else 'ies'} missing the 'text' field. "
                "Populate 'text' with the original surface form for traceability."
            )

        short = [
            e for e in entities
            if isinstance(e, dict) and len((e.get('text') or '').strip()) < 3
        ]
        if short:
            recommendations.append(
                f"{len(short)} entit{'y' if len(short) == 1 else 'ies'} have very short names "
                "(< 3 characters). Review these for extraction noise."
            )

    # -- Granularity recommendations ---------------------------------------
    if granularity < 0.7:
        prop_counts = [len(e.get('properties', {})) for e in entities if isinstance(e, dict)]
        avg_props = sum(prop_counts) / max(len(prop_counts), 1)
        if avg_props < 1.0:
            recommendations.append(
                f"Average {avg_props:.1f} properties per entity is very low. "
                "Enrich entities with domain-specific attributes."
            )

        n_rels = len(relationships)
        rel_ratio = n_rels / max(len(entities), 1)
        if rel_ratio > 5.0:
            recommendations.append(
                "Relationship count is very high relative to entity count -- consider merging redundant entities "
                "or collapsing similar relationship types."
            )

    # -- Relationship coherence recommendations ----------------------------
    if relationship_coherence < 0.7:
        _GENERIC_RELS = {'relates_to', 'related_to', 'links', 'connected', 'associated', 'rel'}
        rel_types = [r.get('type', '') for r in relationships if isinstance(r, dict)]
        generic_count = sum(1 for rt in rel_types if rt.lower() in _GENERIC_RELS)

        if generic_count > len(rel_types) * 0.3:
            recommendations.append(
                f"{generic_count} of {len(rel_types)} relationships use generic types "
                "(e.g. 'relates_to', 'connected'). Replace with specific verbs like 'manages', 'causes', 'implements'."
            )

        unique_types = set(rt for rt in rel_types if rt)
        if len(unique_types) == 1 and len(relationships) > 5:
            recommendations.append(
                "All relationships use the same type. Add variety by using domain-specific relationship types."
            )

        no_type = [r for r in relationships if isinstance(r, dict) and not r.get('type')]
        if no_type:
            recommendations.append(
                f"{len(no_type)} relationship(s) missing type field. "
                "Assign meaningful types to all relationships."
            )

    # -- Domain alignment recommendations ---------------------------------
    if domain_alignment < 0.7:
        domain = (getattr(context, 'domain', None) or ontology.get('domain', 'general')).lower()
        recommendations.append(
            f"Many entity/relationship types don't align with '{domain}' domain vocabulary. "
            "Review type names and replace generic labels with domain-specific terms."
        )

    return recommendations
