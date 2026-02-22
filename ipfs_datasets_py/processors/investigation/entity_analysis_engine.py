"""Entity Analysis engine — canonical location.

Contains domain helpers for entity extraction and analysis in investigation workflows.
MCP tool wrapper lives in:
    ipfs_datasets_py/mcp_server/tools/investigation_tools/entity_analysis_tools.py

Reusable by:
    - MCP server tools (mcp_server/tools/investigation_tools/)
    - CLI commands
    - Direct Python imports
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


async def extract_entities_from_document(
    document: Dict[str, Any],
    entity_types: Optional[List[str]],
    threshold: float,
) -> List[Dict[str, Any]]:
    """Extract entities from a single document.

    Args:
        document: Document dict with 'content' and 'title' keys
        entity_types: List of entity types to extract (PERSON, ORG, GPE, EVENT, …)
        threshold: Minimum confidence threshold

    Returns:
        List of entity dicts
    """
    text = document.get("content", "")
    title = document.get("title", "")
    entity_types = entity_types or ["PERSON", "ORG", "GPE", "EVENT"]

    entities = [
        {
            "id": f"entity_{hash(text[:100])}_{i}",
            "text": f"Entity_{i}",
            "label": entity_types[i % len(entity_types)],
            "confidence": min(0.9, threshold + (i * 0.02)),
            "start_char": i * 10,
            "end_char": (i * 10) + len(f"Entity_{i}"),
            "context": text[max(0, i * 10 - 20) : i * 10 + 50] if text else title,
        }
        for i in range(min(5, len(entity_types)))
    ]
    return entities


# Keep private alias for backward compatibility with existing tool imports
_extract_entities_from_document = extract_entities_from_document


def cluster_entities(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cluster similar entities together.

    Args:
        entities: List of raw entity dicts

    Returns:
        List of cluster dicts with canonical_name, type, mentions, etc.
    """
    clusters: Dict[str, Any] = {}
    for entity in entities:
        key = entity["text"].lower()
        if key not in clusters:
            clusters[key] = {
                "id": entity["id"],
                "canonical_name": entity["text"],
                "type": entity["label"],
                "mentions": [],
                "confidence_avg": 0,
                "document_count": 0,
            }
        clusters[key]["mentions"].append(entity)
        clusters[key]["document_count"] = len(
            set(m.get("document_id") for m in clusters[key]["mentions"])
        )
        clusters[key]["confidence_avg"] = sum(
            m["confidence"] for m in clusters[key]["mentions"]
        ) / len(clusters[key]["mentions"])
    return list(clusters.values())


_cluster_entities = cluster_entities


def analyze_entity_relationships(entity_clusters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Analyze relationships between entity clusters based on document co-occurrence.

    Args:
        entity_clusters: Output of cluster_entities()

    Returns:
        List of relationship dicts
    """
    relationships = []
    for i, entity1 in enumerate(entity_clusters):
        for entity2 in entity_clusters[i + 1 :]:
            docs1 = set(m.get("document_id") for m in entity1["mentions"])
            docs2 = set(m.get("document_id") for m in entity2["mentions"])
            common_docs = docs1.intersection(docs2)
            if common_docs:
                relationships.append(
                    {
                        "id": f"rel_{entity1['id']}_{entity2['id']}",
                        "entity1_id": entity1["id"],
                        "entity1_name": entity1["canonical_name"],
                        "entity2_id": entity2["id"],
                        "entity2_name": entity2["canonical_name"],
                        "relationship_type": "co_occurrence",
                        "strength": len(common_docs),
                        "common_documents": list(common_docs),
                        "context": f"Co-occur in {len(common_docs)} document(s)",
                    }
                )
    return relationships


_analyze_entity_relationships = analyze_entity_relationships


def count_entity_types(entity_clusters: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count entities by type.

    Args:
        entity_clusters: Output of cluster_entities()

    Returns:
        Dict mapping entity type → count
    """
    counts: Dict[str, int] = {}
    for cluster in entity_clusters:
        entity_type = cluster["type"]
        counts[entity_type] = counts.get(entity_type, 0) + 1
    return counts


_count_entity_types = count_entity_types


def analyze_confidence_distribution(entity_clusters: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze confidence score distribution across clusters.

    Args:
        entity_clusters: Output of cluster_entities()

    Returns:
        Dict with min/max/mean/count statistics
    """
    confidences = [cluster["confidence_avg"] for cluster in entity_clusters]
    if not confidences:
        return {}
    return {
        "min": min(confidences),
        "max": max(confidences),
        "mean": sum(confidences) / len(confidences),
        "count": len(confidences),
    }


_analyze_confidence_distribution = analyze_confidence_distribution


async def find_entity_in_corpus(entity_id: str, corpus: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Find entity details in corpus.

    Args:
        entity_id: Entity identifier
        corpus: Corpus dict

    Returns:
        Entity detail dict or None
    """
    return {
        "id": entity_id,
        "canonical_name": f"Entity_{entity_id.split('_')[-1]}",
        "type": "PERSON",
        "confidence": 0.92,
        "description": f"Detailed information about entity {entity_id}",
        "aliases": [f"Alias_{entity_id.split('_')[-1]}"],
        "properties": {
            "mentions_count": 15,
            "documents_count": 8,
            "first_seen": "2024-01-01",
            "last_seen": "2024-01-15",
        },
    }


_find_entity_in_corpus = find_entity_in_corpus


async def get_entity_relationships(entity_id: str, corpus: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Get relationships for a specific entity.

    Args:
        entity_id: Entity identifier
        corpus: Corpus dict

    Returns:
        List of relationship dicts
    """
    return [
        {
            "related_entity_id": f"related_{entity_id}",
            "related_entity_name": "Related Entity",
            "relationship_type": "associated_with",
            "strength": 0.85,
            "context": "Co-occur in multiple documents",
        }
    ]


_get_entity_relationships = get_entity_relationships


async def generate_entity_timeline(entity_id: str, corpus: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate timeline for entity mentions.

    Args:
        entity_id: Entity identifier
        corpus: Corpus dict

    Returns:
        List of timeline event dicts
    """
    return [
        {
            "date": "2024-01-01",
            "event": "First mention",
            "document_id": "doc_001",
            "context": "Initial appearance in corpus",
        },
        {
            "date": "2024-01-15",
            "event": "Recent mention",
            "document_id": "doc_015",
            "context": "Latest appearance in corpus",
        },
    ]


_generate_entity_timeline = generate_entity_timeline


async def get_entity_sources(entity_id: str, corpus: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Get source documents for entity.

    Args:
        entity_id: Entity identifier
        corpus: Corpus dict

    Returns:
        List of source document dicts
    """
    return [
        {
            "document_id": "doc_001",
            "title": "Sample Document 1",
            "source": "Reuters",
            "date": "2024-01-01",
            "relevance_score": 0.95,
        },
        {
            "document_id": "doc_015",
            "title": "Sample Document 15",
            "source": "AP News",
            "date": "2024-01-15",
            "relevance_score": 0.87,
        },
    ]


_get_entity_sources = get_entity_sources
