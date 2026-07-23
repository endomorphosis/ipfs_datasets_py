"""Complaint-style case graph helpers built on the standard processor KG."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence

from ..protocol import Entity, KnowledgeGraph, Relationship


def build_case_knowledge_graph(
    *,
    entities: Sequence[Dict[str, Any]] | None = None,
    relationships: Sequence[Dict[str, Any]] | None = None,
    source: str = "case_analysis",
    properties: Optional[Dict[str, Any]] = None,
) -> KnowledgeGraph:
    """Build a standard processor knowledge graph from case-style rows."""

    graph = KnowledgeGraph(source=source, properties=dict(properties or {}))
    for entity in list(entities or []):
        if not isinstance(entity, dict):
            continue
        graph.add_entity(
            Entity(
                id=str(entity.get("id") or ""),
                type=str(entity.get("type") or "fact"),
                label=str(entity.get("label") or entity.get("name") or entity.get("id") or ""),
                properties=dict(entity.get("properties") or entity.get("attributes") or {}),
                confidence=float(entity.get("confidence", 1.0) or 1.0),
            )
        )
    for relationship in list(relationships or []):
        if not isinstance(relationship, dict):
            continue
        graph.add_relationship(
            Relationship(
                id=str(relationship.get("id") or ""),
                source=str(relationship.get("source") or relationship.get("source_id") or ""),
                target=str(relationship.get("target") or relationship.get("target_id") or ""),
                type=str(relationship.get("type") or relationship.get("relation_type") or "RELATED_TO"),
                properties=dict(relationship.get("properties") or relationship.get("attributes") or {}),
                confidence=float(relationship.get("confidence", 1.0) or 1.0),
                bidirectional=bool(relationship.get("bidirectional", False)),
            )
        )
    return graph


def analyze_case_graph_gaps(
    graph: KnowledgeGraph,
    *,
    confidence_threshold: float = 0.7,
) -> List[Dict[str, Any]]:
    """Identify common legal-case information gaps in a standard KG."""

    gaps: List[Dict[str, Any]] = []
    entities = list(graph.entities or [])
    relationships = list(graph.relationships or [])

    for entity in entities:
        if entity.confidence < confidence_threshold:
            gaps.append(
                {
                    "type": "low_confidence_entity",
                    "entity_id": entity.id,
                    "entity_type": entity.type,
                    "entity_name": entity.label,
                    "confidence": entity.confidence,
                    "suggested_question": f"Can you provide more details about {entity.label}?",
                }
            )

    for entity in entities:
        related = _relationships_for_entity(graph, entity.id)
        if not related and entity.type in {"person", "organization"}:
            gaps.append(
                {
                    "type": "isolated_entity",
                    "entity_id": entity.id,
                    "entity_type": entity.type,
                    "entity_name": entity.label,
                    "suggested_question": f"What is the relationship between {entity.label} and the complaint?",
                }
            )

    for claim in _entities_by_type(graph, "claim"):
        evidence_relationships = [
            rel
            for rel in _relationships_for_entity(graph, claim.id)
            if rel.type.lower() in {"supported_by", "supported-by"}
        ]
        if not evidence_relationships:
            gaps.append(
                {
                    "type": "unsupported_claim",
                    "entity_id": claim.id,
                    "claim_name": claim.label,
                    "suggested_question": f"What evidence supports the claim: {claim.label}?",
                }
            )

    has_dates = bool(_entities_by_type(graph, "date"))
    has_timeline_rel = any(
        rel.type.lower() in {"occurred_on", "has_timeline_detail"} for rel in relationships
    )
    has_timeline_fact = any(
        entity.type == "fact" and str(entity.properties.get("fact_type") or "").lower() == "timeline"
        for entity in entities
    )
    if not has_dates and not has_timeline_rel and not has_timeline_fact:
        gaps.append(
            {
                "type": "missing_timeline",
                "suggested_question": "When did the key events happen? Please share dates or a brief timeline.",
            }
        )

    timeline_fact_texts = [
        _entity_text(entity)
        for entity in entities
        if entity.type == "fact" and str(entity.properties.get("fact_type") or "").lower() == "timeline"
    ]
    decision_timeline_terms = (
        "decision",
        "decided",
        "approved",
        "denied",
        "terminated",
        "disciplined",
        "evicted",
        "notice",
        "email",
        "letter",
        "message",
    )
    has_decision_timeline_detail = any(
        any(term in text_value for term in decision_timeline_terms) and _has_date_signal(text_value)
        for text_value in timeline_fact_texts
    )
    if not has_decision_timeline_detail:
        gaps.append(
            {
                "type": "missing_decision_timeline",
                "suggested_question": (
                    "Please walk through an actor-by-actor decision timeline: who took each action, "
                    "what they did, and the exact date (or best estimate) for each step."
                ),
            }
        )

    has_org = any(entity.type == "organization" for entity in entities)
    has_respondent_person = any(
        entity.type == "person"
        and str(entity.properties.get("role") or "").lower()
        in {"respondent", "manager", "supervisor", "employer", "owner", "landlord"}
        for entity in entities
    )
    if not has_org and not has_respondent_person:
        gaps.append(
            {
                "type": "missing_responsible_party",
                "suggested_question": (
                    "Who is the person or organization you believe is responsible "
                    "(e.g., employer, manager, agency)?"
                ),
            }
        )

    has_impact = any(
        entity.type == "fact" and str(entity.properties.get("fact_type") or "").lower() == "impact"
        for entity in entities
    )
    has_remedy = any(
        entity.type == "fact" and str(entity.properties.get("fact_type") or "").lower() == "remedy"
        for entity in entities
    )
    if not has_impact or not has_remedy:
        gaps.append(
            {
                "type": "missing_impact_remedy",
                "missing_impact": not has_impact,
                "missing_remedy": not has_remedy,
                "suggested_question": "What harm did you experience, and what outcome or remedy are you seeking?",
            }
        )

    return gaps


def summarize_case_graph(graph: KnowledgeGraph, *, confidence_threshold: float = 0.7) -> Dict[str, Any]:
    """Summarize case-graph readiness and structural quality."""

    entity_count = len(graph.entities)
    relationship_count = len(graph.relationships)
    average_confidence = (
        sum(entity.confidence for entity in graph.entities) / entity_count if entity_count else 0.0
    )
    isolated_count = sum(1 for entity in graph.entities if not _relationships_for_entity(graph, entity.id))
    connection_counts = {
        entity.id: len(_relationships_for_entity(graph, entity.id)) for entity in graph.entities
    }
    most_connected_entity = (
        max(connection_counts.items(), key=lambda item: item[1])[0] if connection_counts else "none"
    )
    average_relationships_per_entity = (
        (sum(connection_counts.values()) / 2) / entity_count if entity_count else 0.0
    )
    gaps = analyze_case_graph_gaps(graph, confidence_threshold=confidence_threshold)

    return {
        "entity_count": entity_count,
        "relationship_count": relationship_count,
        "entity_types": _entity_type_counts(graph),
        "average_confidence": average_confidence,
        "low_confidence_entity_count": sum(
            1 for entity in graph.entities if entity.confidence < confidence_threshold
        ),
        "isolated_entity_count": isolated_count,
        "average_relationships_per_entity": average_relationships_per_entity,
        "most_connected_entity": most_connected_entity,
        "gap_count": len(gaps),
        "gap_types": sorted({gap["type"] for gap in gaps}),
    }


def _entity_type_counts(graph: KnowledgeGraph) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for entity in graph.entities:
        counts[entity.type] = counts.get(entity.type, 0) + 1
    return counts


def _entities_by_type(graph: KnowledgeGraph, entity_type: str) -> List[Entity]:
    return [entity for entity in graph.entities if entity.type == entity_type]


def _relationships_for_entity(graph: KnowledgeGraph, entity_id: str) -> List[Relationship]:
    return [
        relationship
        for relationship in graph.relationships
        if relationship.source == entity_id or relationship.target == entity_id
    ]


def _entity_text(entity: Entity) -> str:
    properties = entity.properties if isinstance(entity.properties, dict) else {}
    parts = [
        str(entity.label or ""),
        str(properties.get("description") or ""),
        str(properties.get("event_label") or ""),
        str(properties.get("event_date_or_range") or ""),
    ]
    return " ".join(part.strip() for part in parts if str(part).strip()).lower()


def _has_date_signal(text_value: str) -> bool:
    if not text_value:
        return False
    return bool(
        re.search(
            r"\b(?:19|20)\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b",
            text_value,
        )
    )


__all__ = [
    "analyze_case_graph_gaps",
    "build_case_knowledge_graph",
    "summarize_case_graph",
]
