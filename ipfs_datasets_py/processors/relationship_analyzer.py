"""Relationship analysis helpers for PDF GraphRAG tooling."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple


class RelationshipAnalyzer:
    """Lightweight relationship analysis facade for PDF tools."""

    def __init__(self) -> None:
        self._last_processing_time: float = 0.0

    async def analyze_entity_relationships(
        self,
        *,
        documents: List[Dict[str, Any]],
        min_confidence: float = 0.6,
        max_relationships: int = 100,
        relationship_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        start = time.monotonic()
        entities = self._collect_entities(documents)
        relationships = self._collect_relationships(documents)

        if relationship_types:
            rel_types = {str(t).lower() for t in relationship_types}
            relationships = [
                rel
                for rel in relationships
                if str(rel.get("relationship_type") or rel.get("type") or "").lower() in rel_types
            ]

        relationships = [
            rel
            for rel in relationships
            if float(rel.get("confidence", 1.0) or 1.0) >= min_confidence
        ][: max(0, int(max_relationships))]

        self._last_processing_time = time.monotonic() - start
        return {
            "entities": entities,
            "relationships": relationships,
            "processing_time": self._last_processing_time,
        }

    async def analyze_citation_network(
        self,
        *,
        documents: List[Dict[str, Any]],
        include_cross_document: bool = True,
        min_confidence: float = 0.6,
    ) -> Dict[str, Any]:
        start = time.monotonic()
        citations: List[Dict[str, Any]] = []
        for doc in documents or []:
            doc_citations = doc.get("citations")
            if isinstance(doc_citations, list):
                citations.extend([c for c in doc_citations if isinstance(c, dict)])
            network = doc.get("citation_network") or {}
            network_citations = network.get("citations") if isinstance(network, dict) else None
            if isinstance(network_citations, list):
                citations.extend([c for c in network_citations if isinstance(c, dict)])

        citations = [
            c
            for c in citations
            if float(c.get("confidence", 1.0) or 1.0) >= min_confidence
        ]

        self._last_processing_time = time.monotonic() - start
        return {
            "citations": citations,
            "include_cross_document": bool(include_cross_document),
            "processing_time": self._last_processing_time,
        }

    async def analyze_thematic_relationships(
        self,
        *,
        documents: List[Dict[str, Any]],
        include_cross_document: bool = True,
        min_confidence: float = 0.6,
    ) -> Dict[str, Any]:
        start = time.monotonic()
        themes: List[Dict[str, Any]] = []
        relationships: List[Dict[str, Any]] = []

        for doc in documents or []:
            doc_themes = doc.get("themes")
            if isinstance(doc_themes, list):
                themes.extend([t for t in doc_themes if isinstance(t, dict)])
            thematic = doc.get("thematic_relationships") or {}
            if isinstance(thematic, dict):
                thematic_themes = thematic.get("themes")
                if isinstance(thematic_themes, list):
                    themes.extend([t for t in thematic_themes if isinstance(t, dict)])
                thematic_relationships = thematic.get("relationships")
                if isinstance(thematic_relationships, list):
                    relationships.extend([r for r in thematic_relationships if isinstance(r, dict)])

        relationships = [
            rel
            for rel in relationships
            if float(rel.get("confidence", 1.0) or 1.0) >= min_confidence
        ]

        self._last_processing_time = time.monotonic() - start
        return {
            "themes": themes,
            "relationships": relationships,
            "include_cross_document": bool(include_cross_document),
            "processing_time": self._last_processing_time,
        }

    async def find_cross_document_relationships(
        self,
        *,
        source_document_id: str,
        min_confidence: float = 0.6,
        max_relationships: int = 100,
    ) -> Dict[str, Any]:
        start = time.monotonic()
        relationships: List[Dict[str, Any]] = []
        if source_document_id:
            # Placeholder for future cross-document indexing.
            relationships = []

        relationships = [
            rel
            for rel in relationships
            if float(rel.get("confidence", 1.0) or 1.0) >= min_confidence
        ][: max(0, int(max_relationships))]

        self._last_processing_time = time.monotonic() - start
        return {
            "relationships": relationships,
            "processing_time": self._last_processing_time,
        }

    async def build_relationship_graph(
        self,
        results: Dict[str, Any],
        *,
        include_cross_document: bool = True,
    ) -> Dict[str, Any]:
        nodes: Dict[str, Dict[str, Any]] = {}
        edges: List[Dict[str, Any]] = []

        entity_results = results.get("entity_relationships") or {}
        entities = entity_results.get("entities") if isinstance(entity_results, dict) else None
        relationships = entity_results.get("relationships") if isinstance(entity_results, dict) else None

        for entity in entities or []:
            entity_id = self._entity_id(entity)
            if not entity_id:
                continue
            nodes.setdefault(entity_id, {"id": entity_id, "label": self._entity_label(entity)})

        for rel in relationships or []:
            source_id, target_id = self._relationship_endpoints(rel)
            if not source_id or not target_id:
                continue
            nodes.setdefault(source_id, {"id": source_id, "label": source_id})
            nodes.setdefault(target_id, {"id": target_id, "label": target_id})
            edges.append({
                "source": source_id,
                "target": target_id,
                "type": rel.get("relationship_type") or rel.get("type") or "related_to",
            })

        if include_cross_document:
            cross_doc = results.get("cross_document_relationships") or []
            for rel in cross_doc:
                if not isinstance(rel, dict):
                    continue
                source_id, target_id = self._relationship_endpoints(rel)
                if not source_id or not target_id:
                    continue
                nodes.setdefault(source_id, {"id": source_id, "label": source_id})
                nodes.setdefault(target_id, {"id": target_id, "label": target_id})
                edges.append({
                    "source": source_id,
                    "target": target_id,
                    "type": rel.get("relationship_type") or rel.get("type") or "cross_document",
                })

        return {
            "nodes": list(nodes.values()),
            "edges": edges,
        }

    def _collect_entities(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        entities: List[Dict[str, Any]] = []
        seen = set()
        for doc in documents or []:
            doc_entities = doc.get("entities")
            if isinstance(doc_entities, list):
                candidates = doc_entities
            else:
                entity_bundle = doc.get("entity_relationships") or {}
                candidates = entity_bundle.get("entities") if isinstance(entity_bundle, dict) else []
            for entity in candidates or []:
                if not isinstance(entity, dict):
                    continue
                key = self._entity_key(entity)
                if key in seen:
                    continue
                seen.add(key)
                entities.append(entity)
        return entities

    def _collect_relationships(self, documents: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        relationships: List[Dict[str, Any]] = []
        for doc in documents or []:
            doc_relationships = doc.get("relationships")
            if isinstance(doc_relationships, list):
                relationships.extend([r for r in doc_relationships if isinstance(r, dict)])
            entity_bundle = doc.get("entity_relationships") or {}
            bundle_relationships = entity_bundle.get("relationships") if isinstance(entity_bundle, dict) else None
            if isinstance(bundle_relationships, list):
                relationships.extend([r for r in bundle_relationships if isinstance(r, dict)])
        return relationships

    def _entity_key(self, entity: Dict[str, Any]) -> Tuple[str, str]:
        entity_id = str(entity.get("entity_id") or entity.get("id") or "").strip()
        name = str(entity.get("name") or entity.get("label") or "").strip()
        return (entity_id, name)

    def _entity_id(self, entity: Dict[str, Any]) -> Optional[str]:
        entity_id = entity.get("entity_id") or entity.get("id")
        if entity_id:
            return str(entity_id)
        name = entity.get("name") or entity.get("label")
        if name:
            return str(name)
        return None

    def _entity_label(self, entity: Dict[str, Any]) -> str:
        return str(entity.get("name") or entity.get("label") or self._entity_id(entity) or "")

    def _relationship_endpoints(self, relationship: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        source = relationship.get("source_entity_id") or relationship.get("source")
        target = relationship.get("target_entity_id") or relationship.get("target")

        if isinstance(source, dict):
            source = self._entity_id(source)
        if isinstance(target, dict):
            target = self._entity_id(target)

        if relationship.get("entity1_id"):
            source = relationship.get("entity1_id")
        if relationship.get("entity2_id"):
            target = relationship.get("entity2_id")

        return (
            str(source) if source else None,
            str(target) if target else None,
        )
