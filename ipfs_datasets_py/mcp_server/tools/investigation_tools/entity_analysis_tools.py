#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Entity Analysis MCP Tools

Provides MCP tools for entity analysis and investigation workflows.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..tool_wrapper import wrap_function_as_tool

logger = logging.getLogger(__name__)


@wrap_function_as_tool(
    name="analyze_entities",
    description="Analyze entities in a corpus of documents for investigation purposes",
    category="investigation"
)
async def analyze_entities(
    corpus_data: str,
    analysis_type: str = "comprehensive",
    entity_types: Optional[List[str]] = None,
    confidence_threshold: float = 0.85,
    user_context: Optional[str] = None
) -> Dict[str, Any]:
    """
    Analyze entities in corpus data for investigation purposes.
    
    Args:
        corpus_data: JSON string containing document corpus data
        analysis_type: Type of analysis (comprehensive, targeted, relationships)
        entity_types: List of entity types to focus on (PERSON, ORG, GPE, etc.)
        confidence_threshold: Minimum confidence score for entity extraction
        user_context: User context for personalized analysis
        
    Returns:
        Dictionary containing entity analysis results
    """
    try:
        # Parse corpus data
        if isinstance(corpus_data, str):
            corpus = json.loads(corpus_data)
        else:
            corpus = corpus_data
            
        # Initialize entity analysis results
        results = {
            "analysis_id": f"entity_analysis_{datetime.now().isoformat()}",
            "analysis_type": analysis_type,
            "entity_types": entity_types or ["PERSON", "ORG", "GPE", "EVENT"],
            "confidence_threshold": confidence_threshold,
            "entities": [],
            "relationships": [],
            "clusters": [],
            "statistics": {},
            "timestamp": datetime.now().isoformat()
        }
        
        # Simulate entity extraction (in real implementation, would use NLP models)
        entities = []
        if "documents" in corpus:
            for doc_id, doc in enumerate(corpus["documents"]):
                doc_entities = await _extract_entities_from_document(
                    doc, 
                    entity_types, 
                    confidence_threshold
                )
                for entity in doc_entities:
                    entity["document_id"] = doc_id
                    entity["document_source"] = doc.get("source", "unknown")
                entities.extend(doc_entities)
        
        # Group and deduplicate entities
        entity_clusters = _cluster_entities(entities)
        
        # Analyze relationships between entities
        relationships = _analyze_entity_relationships(entity_clusters)
        
        results.update({
            "entities": entity_clusters,
            "relationships": relationships,
            "statistics": {
                "total_entities": len(entity_clusters),
                "total_relationships": len(relationships),
                "entity_type_counts": _count_entity_types(entity_clusters),
                "confidence_distribution": _analyze_confidence_distribution(entity_clusters)
            }
        })
        
        logger.info(f"Entity analysis completed: {len(entity_clusters)} entities, {len(relationships)} relationships")
        return results
        
    except Exception as e:
        logger.error(f"Entity analysis failed: {e}")
        return {
            "error": str(e),
            "analysis_id": None,
            "timestamp": datetime.now().isoformat()
        }


@wrap_function_as_tool(
    name="explore_entity",
    description="Explore detailed information about a specific entity",
    category="investigation"
)
async def explore_entity(
    entity_id: str,
    corpus_data: str,
    include_relationships: bool = True,
    include_timeline: bool = True,
    include_sources: bool = True
) -> Dict[str, Any]:
    """
    Explore detailed information about a specific entity.
    
    Args:
        entity_id: Unique identifier for the entity
        corpus_data: JSON string containing document corpus data
        include_relationships: Whether to include entity relationships
        include_timeline: Whether to include entity timeline
        include_sources: Whether to include source documents
        
    Returns:
        Dictionary containing detailed entity information
    """
    try:
        # Parse corpus data
        if isinstance(corpus_data, str):
            corpus = json.loads(corpus_data)
        else:
            corpus = corpus_data
            
        results = {
            "entity_id": entity_id,
            "entity_details": {},
            "relationships": [],
            "timeline": [],
            "sources": [],
            "analysis_metadata": {
                "include_relationships": include_relationships,
                "include_timeline": include_timeline,
                "include_sources": include_sources,
                "timestamp": datetime.now().isoformat()
            }
        }
        
        # Find entity details in corpus
        entity_details = await _find_entity_in_corpus(entity_id, corpus)
        if not entity_details:
            return {
                "error": f"Entity {entity_id} not found in corpus",
                "entity_id": entity_id,
                "timestamp": datetime.now().isoformat()
            }
            
        results["entity_details"] = entity_details
        
        # Include relationships if requested
        if include_relationships:
            relationships = await _get_entity_relationships(entity_id, corpus)
            results["relationships"] = relationships
            
        # Include timeline if requested
        if include_timeline:
            timeline = await _generate_entity_timeline(entity_id, corpus)
            results["timeline"] = timeline
            
        # Include sources if requested
        if include_sources:
            sources = await _get_entity_sources(entity_id, corpus)
            results["sources"] = sources
            
        logger.info(f"Entity exploration completed for {entity_id}")
        return results
        
    except Exception as e:
        logger.error(f"Entity exploration failed: {e}")
        return {
            "error": str(e),
            "entity_id": entity_id,
            "timestamp": datetime.now().isoformat()
        }


# Helper functions for entity analysis

async def _extract_entities_from_document(document: Dict[str, Any], entity_types: List[str], threshold: float) -> List[Dict[str, Any]]:
    """Extract entities from a single document."""
    # Simulate entity extraction - in real implementation would use spaCy/transformers
    text = document.get("content", "")
    title = document.get("title", "")
    
    # Mock entity extraction results
    entities = [
        {
            "id": f"entity_{hash(text[:100])}_{i}",
            "text": f"Entity_{i}",
            "label": entity_types[i % len(entity_types)],
            "confidence": min(0.9, threshold + (i * 0.02)),
            "start_char": i * 10,
            "end_char": (i * 10) + len(f"Entity_{i}"),
            "context": text[max(0, i*10-20):i*10+50] if text else title
        }
        for i in range(min(5, len(entity_types)))  # Generate sample entities
    ]
    
    return entities


def _cluster_entities(entities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Cluster similar entities together."""
    # Simple clustering by entity text (in real implementation would use embeddings)
    clusters = {}
    for entity in entities:
        key = entity["text"].lower()
        if key not in clusters:
            clusters[key] = {
                "id": entity["id"],
                "canonical_name": entity["text"],
                "type": entity["label"],
                "mentions": [],
                "confidence_avg": 0,
                "document_count": 0
            }
        
        clusters[key]["mentions"].append(entity)
        clusters[key]["document_count"] = len(set(m.get("document_id") for m in clusters[key]["mentions"]))
        clusters[key]["confidence_avg"] = sum(m["confidence"] for m in clusters[key]["mentions"]) / len(clusters[key]["mentions"])
    
    return list(clusters.values())


def _analyze_entity_relationships(entity_clusters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Analyze relationships between entity clusters."""
    relationships = []
    
    for i, entity1 in enumerate(entity_clusters):
        for j, entity2 in enumerate(entity_clusters[i+1:], i+1):
            # Check if entities co-occur in same documents
            docs1 = set(m.get("document_id") for m in entity1["mentions"])
            docs2 = set(m.get("document_id") for m in entity2["mentions"])
            common_docs = docs1.intersection(docs2)
            
            if common_docs:
                relationships.append({
                    "id": f"rel_{entity1['id']}_{entity2['id']}",
                    "entity1_id": entity1["id"],
                    "entity1_name": entity1["canonical_name"],
                    "entity2_id": entity2["id"],
                    "entity2_name": entity2["canonical_name"],
                    "relationship_type": "co_occurrence",
                    "strength": len(common_docs),
                    "common_documents": list(common_docs),
                    "context": f"Co-occur in {len(common_docs)} document(s)"
                })
    
    return relationships


def _count_entity_types(entity_clusters: List[Dict[str, Any]]) -> Dict[str, int]:
    """Count entities by type."""
    counts = {}
    for cluster in entity_clusters:
        entity_type = cluster["type"]
        counts[entity_type] = counts.get(entity_type, 0) + 1
    return counts


def _analyze_confidence_distribution(entity_clusters: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Analyze confidence score distribution."""
    confidences = [cluster["confidence_avg"] for cluster in entity_clusters]
    if not confidences:
        return {}
        
    return {
        "min": min(confidences),
        "max": max(confidences),
        "mean": sum(confidences) / len(confidences),
        "count": len(confidences)
    }


async def _find_entity_in_corpus(entity_id: str, corpus: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Find entity details in corpus."""
    # Mock implementation - search through corpus for entity
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
            "last_seen": "2024-01-15"
        }
    }


async def _get_entity_relationships(entity_id: str, corpus: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Get relationships for a specific entity."""
    # Mock relationships
    return [
        {
            "related_entity_id": f"related_{entity_id}",
            "related_entity_name": f"Related Entity",
            "relationship_type": "associated_with",
            "strength": 0.85,
            "context": "Co-occur in multiple documents"
        }
    ]


async def _generate_entity_timeline(entity_id: str, corpus: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Generate timeline for entity mentions."""
    return [
        {
            "date": "2024-01-01",
            "event": "First mention",
            "document_id": "doc_001",
            "context": "Initial appearance in corpus"
        },
        {
            "date": "2024-01-15",
            "event": "Recent mention", 
            "document_id": "doc_015",
            "context": "Latest appearance in corpus"
        }
    ]


async def _get_entity_sources(entity_id: str, corpus: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Get source documents for entity."""
    return [
        {
            "document_id": "doc_001",
            "title": "Sample Document 1",
            "source": "Reuters",
            "date": "2024-01-01",
            "relevance_score": 0.95
        },
        {
            "document_id": "doc_015",
            "title": "Sample Document 15",
            "source": "AP News",
            "date": "2024-01-15",
            "relevance_score": 0.87
        }
    ]