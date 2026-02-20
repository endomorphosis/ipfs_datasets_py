#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Entity Analysis MCP Tools

Thin MCP wrapper for entity analysis. Business logic has been extracted to:
    ipfs_datasets_py/processors/investigation/entity_analysis_engine.py
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..tool_wrapper import wrap_function_as_tool
from ipfs_datasets_py.processors.investigation.entity_analysis_engine import (  # noqa: F401
    extract_entities_from_document as _extract_entities_from_document,
    cluster_entities as _cluster_entities,
    analyze_entity_relationships as _analyze_entity_relationships,
    count_entity_types as _count_entity_types,
    analyze_confidence_distribution as _analyze_confidence_distribution,
    find_entity_in_corpus as _find_entity_in_corpus,
    get_entity_relationships as _get_entity_relationships,
    generate_entity_timeline as _generate_entity_timeline,
    get_entity_sources as _get_entity_sources,
)

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
    """Analyze entities in corpus data for investigation purposes."""
    try:
        corpus = json.loads(corpus_data) if isinstance(corpus_data, str) else corpus_data
        results: Dict[str, Any] = {
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

        entities = []
        if "documents" in corpus:
            for doc_id, doc in enumerate(corpus["documents"]):
                doc_entities = await _extract_entities_from_document(
                    doc, entity_types or ["PERSON", "ORG", "GPE", "EVENT"], confidence_threshold,
                )
                for entity in doc_entities:
                    entity["document_id"] = doc_id
                    entity["document_source"] = doc.get("source", "unknown")
                entities.extend(doc_entities)

        entity_clusters = _cluster_entities(entities)
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
        return {"error": str(e), "analysis_id": None, "timestamp": datetime.now().isoformat()}


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
    """Explore detailed information about a specific entity."""
    try:
        corpus = json.loads(corpus_data) if isinstance(corpus_data, str) else corpus_data
        results: Dict[str, Any] = {
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

        entity_details = await _find_entity_in_corpus(entity_id, corpus)
        if not entity_details:
            return {"error": f"Entity {entity_id} not found in corpus", "entity_id": entity_id,
                    "timestamp": datetime.now().isoformat()}

        results["entity_details"] = entity_details
        if include_relationships:
            results["relationships"] = await _get_entity_relationships(entity_id, corpus)
        if include_timeline:
            results["timeline"] = await _generate_entity_timeline(entity_id, corpus)
        if include_sources:
            results["sources"] = await _get_entity_sources(entity_id, corpus)

        logger.info(f"Entity exploration completed for {entity_id}")
        return results
    except Exception as e:
        logger.error(f"Entity exploration failed: {e}")
        return {"error": str(e), "entity_id": entity_id, "timestamp": datetime.now().isoformat()}
