#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Entity Extractor

Core business logic for extracting entities and relationships from document corpus.
Reusable by CLI, MCP tools, and third-party packages.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List
from collections import defaultdict

logger = logging.getLogger(__name__)


class EntityExtractor:
    """
    Extracts entities and relationships from document corpora.
    
    Provides methods for:
    - Entity extraction and deduplication
    - Relationship extraction (co-occurrence, citation, semantic, temporal)
    - Entity mention tracking
    
    Example:
        >>> extractor = EntityExtractor()
        >>> entities = await extractor.extract_entities(corpus)
        >>> relationships = await extractor.extract_relationships(corpus, entities, ["co_occurrence"])
    """
    
    def __init__(self):
        """Initialize the EntityExtractor."""
        pass
    
    async def extract_entities_for_mapping(self, corpus: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Extract entities optimized for relationship mapping.
        
        Args:
            corpus: Dictionary containing document corpus data with 'documents' key
            
        Returns:
            List of entity dictionaries with deduplication and mention aggregation
        """
        entities = []
        
        if "documents" not in corpus:
            return entities
            
        entity_mentions = defaultdict(list)
        
        # Extract entity mentions from documents
        for doc_id, document in enumerate(corpus["documents"]):
            content = document.get("content", "") + " " + document.get("title", "")
            
            # Simple entity extraction (in production would use NER models)
            # Mock entities for demonstration
            for i in range(3):  # Generate sample entities
                entity = {
                    "id": f"entity_{doc_id}_{i}",
                    "name": f"Entity_{doc_id}_{i}",
                    "type": ["PERSON", "ORG", "GPE"][i % 3],
                    "document_id": doc_id,
                    "mentions": [{
                        "text": f"Entity_{doc_id}_{i}",
                        "start": i * 10,
                        "end": i * 10 + len(f"Entity_{doc_id}_{i}"),
                        "confidence": 0.85 + (i * 0.05)
                    }]
                }
                entity_mentions[entity["name"]].append(entity)
        
        # Deduplicate and merge entity mentions
        for entity_name, mentions in entity_mentions.items():
            merged_entity = {
                "id": mentions[0]["id"],
                "name": entity_name,
                "type": mentions[0]["type"],
                "document_count": len(set(m["document_id"] for m in mentions)),
                "total_mentions": sum(len(m["mentions"]) for m in mentions),
                "average_confidence": sum(
                    sum(mention["confidence"] for mention in m["mentions"]) / len(m["mentions"])
                    for m in mentions
                ) / len(mentions),
                "documents": list(set(m["document_id"] for m in mentions))
            }
            entities.append(merged_entity)
        
        return entities
    
    async def extract_relationships(
        self,
        corpus: Dict[str, Any],
        entities: List[Dict[str, Any]],
        relationship_types: List[str]
    ) -> List[Dict[str, Any]]:
        """
        Extract relationships between entities.
        
        Args:
            corpus: Dictionary containing document corpus data
            entities: List of extracted entities
            relationship_types: Types of relationships to extract
            
        Returns:
            List of relationship dictionaries with strength scores
        """
        relationships = []
        
        if "documents" not in corpus:
            return relationships
        
        entity_map = {e["id"]: e for e in entities}
        
        # Extract relationships based on types
        for rel_type in relationship_types:
            if rel_type == "co_occurrence":
                relationships.extend(self._extract_cooccurrence_relationships(corpus, entities))
            elif rel_type == "citation":
                relationships.extend(self._extract_citation_relationships(corpus, entities))
            elif rel_type == "semantic":
                relationships.extend(self._extract_semantic_relationships(corpus, entities))
            elif rel_type == "temporal":
                relationships.extend(self._extract_temporal_relationships(corpus, entities))
        
        return relationships
    
    def _extract_cooccurrence_relationships(
        self,
        corpus: Dict[str, Any],
        entities: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Extract co-occurrence relationships between entities."""
        relationships = []
        
        # Mock co-occurrence detection
        for i, entity1 in enumerate(entities[:5]):  # Limit for demo
            for entity2 in entities[i+1:min(i+3, len(entities))]:
                relationships.append({
                    "id": f"rel_cooccur_{entity1['id']}_{entity2['id']}",
                    "type": "co_occurrence",
                    "source_entity": entity1["id"],
                    "target_entity": entity2["id"],
                    "strength": 0.7 + (i * 0.05),
                    "evidence": {
                        "co_occurrence_count": 5 + i,
                        "shared_documents": 2
                    }
                })
        
        return relationships
    
    def _extract_citation_relationships(
        self,
        corpus: Dict[str, Any],
        entities: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Extract citation relationships between entities."""
        relationships = []
        
        # Mock citation detection
        for i, entity in enumerate(entities[:3]):
            relationships.append({
                "id": f"rel_citation_{entity['id']}",
                "type": "citation",
                "source_entity": entity["id"],
                "target_entity": entities[(i+1) % len(entities)]["id"] if len(entities) > 1 else entity["id"],
                "strength": 0.85,
                "evidence": {
                    "citation_count": 3,
                    "citation_context": "direct reference"
                }
            })
        
        return relationships
    
    def _extract_semantic_relationships(
        self,
        corpus: Dict[str, Any],
        entities: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Extract semantic relationships between entities."""
        relationships = []
        
        # Mock semantic relationship detection
        for i, entity in enumerate(entities[:3]):
            if i + 1 < len(entities):
                relationships.append({
                    "id": f"rel_semantic_{entity['id']}",
                    "type": "semantic",
                    "source_entity": entity["id"],
                    "target_entity": entities[i+1]["id"],
                    "strength": 0.75,
                    "evidence": {
                        "semantic_similarity": 0.8,
                        "relationship_label": "related_to"
                    }
                })
        
        return relationships
    
    def _extract_temporal_relationships(
        self,
        corpus: Dict[str, Any],
        entities: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Extract temporal relationships between entities."""
        relationships = []
        
        # Mock temporal relationship detection
        for i, entity in enumerate(entities[:2]):
            if i + 1 < len(entities):
                relationships.append({
                    "id": f"rel_temporal_{entity['id']}",
                    "type": "temporal",
                    "source_entity": entity["id"],
                    "target_entity": entities[i+1]["id"],
                    "strength": 0.65,
                    "evidence": {
                        "temporal_order": "before",
                        "time_difference": "5 days"
                    }
                })
        
        return relationships
