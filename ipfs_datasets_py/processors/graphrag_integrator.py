"""Backward-compatible GraphRAG integrator.

This module preserves the legacy ``GraphRAGIntegrator`` API expected by the
PDF processing pipeline. The newer GraphRAG package exposes a different class
(``GraphRAGIntegration``) with a dataset-patching interface, which is not a
drop-in replacement for the historical document-centric integrator used by the
PDF processor.

The compatibility class below keeps the legacy surface area working for the
parts of the codebase that still call ``integrate_document(...)`` and related
helpers while the rest of the GraphRAG stack continues to migrate.
"""

from __future__ import annotations

import asyncio
import logging
import re
import uuid
import warnings
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

import networkx as nx

warnings.warn(
    "processors.graphrag_integrator is deprecated. "
    "Use processors.specialized.graphrag for new code. "
    "This compatibility layer remains for legacy document-centric callers.",
    DeprecationWarning,
    stacklevel=2,
)

try:
    from ipfs_datasets_py.processors.storage.ipld import IPLDStorage
except Exception:
    IPLDStorage = None


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def _coerce_chunk_text(chunk: Any) -> str:
    if isinstance(chunk, dict):
        value = chunk.get("text") or chunk.get("content") or chunk.get("chunk_text") or ""
        return str(value or "")
    return str(getattr(chunk, "text", "") or getattr(chunk, "content", "") or "")


def _coerce_chunk_id(chunk: Any, fallback_index: int) -> str:
    if isinstance(chunk, dict):
        value = chunk.get("chunk_id") or chunk.get("id")
    else:
        value = getattr(chunk, "chunk_id", None) or getattr(chunk, "id", None)
    return str(value or f"chunk_{fallback_index}")


@dataclass
class Entity:
    id: str = field(default_factory=lambda: _new_id("ent"))
    text: str = ""
    type: str = "entity"
    confidence: float = 0.6
    source_chunk: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def entity_id(self) -> str:
        return self.id

    @property
    def entity_type(self) -> str:
        return self.type

    @property
    def name(self) -> str:
        return self.text

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "text": self.text,
            "type": self.type,
            "confidence": self.confidence,
            "source_chunk": self.source_chunk,
            "metadata": dict(self.metadata),
        }


@dataclass
class Relationship:
    id: str = field(default_factory=lambda: _new_id("rel"))
    source_entity_id: str = ""
    target_entity_id: str = ""
    relationship_type: str = "related_to"
    confidence: float = 0.7
    source_chunk: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def source_id(self) -> str:
        return self.source_entity_id

    @property
    def target_id(self) -> str:
        return self.target_entity_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source_entity_id": self.source_entity_id,
            "target_entity_id": self.target_entity_id,
            "relationship_type": self.relationship_type,
            "confidence": self.confidence,
            "source_chunk": self.source_chunk,
            "metadata": dict(self.metadata),
        }


@dataclass
class KnowledgeGraph:
    document_id: str
    title: str = ""
    chunks: List[Any] = field(default_factory=list)
    entities: List[Entity] = field(default_factory=list)
    relationships: List[Relationship] = field(default_factory=list)
    graph_id: str = field(default_factory=lambda: _new_id("kg"))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "document_id": self.document_id,
            "title": self.title,
            "chunks": list(self.chunks),
            "entities": [entity.to_dict() for entity in self.entities],
            "relationships": [relationship.to_dict() for relationship in self.relationships],
            "metadata": dict(self.metadata),
        }


class GraphRAGIntegrator:
    """Legacy document-centric GraphRAG integration API."""

    def __init__(
        self,
        storage: Any = None,
        similarity_threshold: float = 0.8,
        entity_extraction_confidence: float = 0.6,
        logger: Optional[logging.Logger] = None,
        config: Optional[Dict[str, Any]] = None,
        use_real_models: bool = False,
        **_: Any,
    ) -> None:
        config = dict(config or {})
        self.storage = storage if storage is not None else self._build_default_storage()
        self.similarity_threshold = float(config.get("similarity_threshold", similarity_threshold))
        self.entity_extraction_confidence = float(
            config.get("entity_extraction_confidence", entity_extraction_confidence)
        )
        self.use_real_models = bool(config.get("use_real_models", use_real_models))
        self.logger = logger or logging.getLogger(__name__)

        self.knowledge_graphs: Dict[str, KnowledgeGraph] = {}
        self.document_graphs: Dict[str, nx.DiGraph] = {}
        self.global_graph = nx.DiGraph()
        self.global_entities: Dict[str, List[str]] = {}
        self.cross_document_relationships: List[Dict[str, Any]] = []
        self.entity_cache: Dict[str, List[Entity]] = {}
        self.relationship_cache: Dict[str, List[Relationship]] = {}

    def _build_default_storage(self) -> Any:
        if IPLDStorage is None:
            return None
        try:
            return IPLDStorage()
        except Exception:
            return None

    async def integrate_document(self, llm_document: Any, document_id: Optional[str] = None) -> KnowledgeGraph:
        if llm_document is None:
            raise ValueError("llm_document must not be None")

        resolved_document_id = str(document_id or getattr(llm_document, "document_id", "") or "").strip()
        if not resolved_document_id:
            raise ValueError("llm_document must define a document_id")

        title = str(getattr(llm_document, "title", "") or "").strip()
        if not title:
            raise ValueError("llm_document must define a title")

        chunks = getattr(llm_document, "chunks", None)
        if not isinstance(chunks, list):
            raise ValueError("llm_document.chunks must be a list")

        entities = self._extract_entities_from_chunks(chunks)
        relationships = self._extract_cross_chunk_relationships(chunks, entities)
        knowledge_graph = self.build_knowledge_graph(
            resolved_document_id,
            entities,
            relationships,
            title=title,
            chunks=chunks,
            metadata={"chunk_count": len(chunks)},
        )

        self.knowledge_graphs[resolved_document_id] = knowledge_graph
        doc_graph = self._create_networkx_graph(knowledge_graph)
        self.document_graphs[resolved_document_id] = doc_graph
        self._merge_into_global_graph(knowledge_graph)
        self._discover_cross_document_relationships(knowledge_graph)
        await self._store_knowledge_graph_ipld(knowledge_graph)
        return knowledge_graph

    def _extract_entities_from_chunks(self, chunks: List[Any]) -> List[Entity]:
        extracted: List[Entity] = []
        seen: Dict[str, Entity] = {}
        for index, chunk in enumerate(chunks):
            chunk_id = _coerce_chunk_id(chunk, index)
            text = _coerce_chunk_text(chunk)
            for entity in self._extract_entities_from_text(text, source_chunk=chunk_id):
                key = entity.text.strip().lower()
                if key in seen:
                    continue
                seen[key] = entity
                extracted.append(entity)
        return extracted

    def _extract_entities_from_text(self, text: str, source_chunk: Optional[str] = None) -> List[Entity]:
        text = str(text or "").strip()
        if not text:
            return []

        patterns = [
            r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\b",
            r"\b[A-Z]{2,}(?:-[A-Z0-9]+)*\b",
            r"\bR\d+(?:-\d+)+\b",
        ]

        candidates: List[Entity] = []
        seen: set[str] = set()
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                value = match.group(0).strip(" ,.;:()[]{}")
                normalized = value.lower()
                if len(value) < 3 or normalized in seen:
                    continue
                seen.add(normalized)
                candidates.append(
                    Entity(
                        text=value,
                        type=self._classify_entity(value),
                        confidence=self.entity_extraction_confidence,
                        source_chunk=source_chunk,
                        metadata={"offset": match.start()},
                    )
                )
        return candidates

    def _classify_entity(self, value: str) -> str:
        if re.match(r"^R\d+(?:-\d+)+$", value):
            return "rule"
        if any(token in value for token in ["Department", "Office", "Board", "Commission", "Agency"]):
            return "organization"
        if len(value.split()) >= 2 and value.split()[0][0].isupper():
            return "named_entity"
        return "entity"

    def _extract_relationships(
        self,
        entities: List[Entity],
        text: str,
        source_chunk: Optional[str] = None,
    ) -> List[Relationship]:
        if len(entities) < 2:
            return []
        relationship_type = self._infer_relationship_type(text)
        relationships: List[Relationship] = []
        for left, right in zip(entities, entities[1:]):
            if left.id == right.id:
                continue
            relationships.append(
                Relationship(
                    source_entity_id=left.id,
                    target_entity_id=right.id,
                    relationship_type=relationship_type,
                    confidence=min(left.confidence, right.confidence),
                    source_chunk=source_chunk,
                    metadata={"source_text": text[:240]},
                )
            )
        return relationships

    def _extract_chunk_relationships(self, chunk: Any, chunk_entities: List[Entity]) -> List[Relationship]:
        return self._extract_relationships(
            chunk_entities,
            _coerce_chunk_text(chunk),
            source_chunk=_coerce_chunk_id(chunk, 0),
        )

    def _infer_relationship_type(self, text: str) -> str:
        lowered = str(text or "").lower()
        if any(token in lowered for token in ["authorizes", "authority", "pursuant"]):
            return "authorizes"
        if any(token in lowered for token in ["defines", "definition", "means"]):
            return "defines"
        if any(token in lowered for token in ["adopts", "incorporates", "references"]):
            return "references"
        return "related_to"

    def _extract_cross_chunk_relationships(self, chunks: List[Any], entities: List[Entity]) -> List[Relationship]:
        by_chunk: Dict[str, List[Entity]] = {}
        for entity in entities:
            if entity.source_chunk is None:
                continue
            by_chunk.setdefault(entity.source_chunk, []).append(entity)

        relationships: List[Relationship] = []
        for index, chunk in enumerate(chunks):
            chunk_id = _coerce_chunk_id(chunk, index)
            relationships.extend(self._extract_chunk_relationships(chunk, by_chunk.get(chunk_id, [])))

        sequences = self._find_chunk_sequences(chunks)
        for left_chunk_id, right_chunk_id in zip(sequences, sequences[1:]):
            left_entities = by_chunk.get(left_chunk_id, [])
            right_entities = by_chunk.get(right_chunk_id, [])
            if not left_entities or not right_entities:
                continue
            relationships.append(
                Relationship(
                    source_entity_id=left_entities[-1].id,
                    target_entity_id=right_entities[0].id,
                    relationship_type="adjacent_chunk",
                    confidence=0.5,
                    source_chunk=right_chunk_id,
                )
            )
        return self._dedupe_relationships(relationships)

    def _find_chunk_sequences(self, chunks: List[Any]) -> List[str]:
        return [_coerce_chunk_id(chunk, index) for index, chunk in enumerate(chunks)]

    def _create_networkx_graph(self, knowledge_graph: KnowledgeGraph) -> nx.DiGraph:
        graph = nx.DiGraph()
        for entity in knowledge_graph.entities:
            graph.add_node(entity.id, **entity.to_dict())
        for relationship in knowledge_graph.relationships:
            graph.add_edge(
                relationship.source_entity_id,
                relationship.target_entity_id,
                relationship_id=relationship.id,
                relationship_type=relationship.relationship_type,
                confidence=relationship.confidence,
            )
        return graph

    def _merge_into_global_graph(self, knowledge_graph: KnowledgeGraph) -> None:
        for entity in knowledge_graph.entities:
            self.global_graph.add_node(entity.id, **entity.to_dict(), document_id=knowledge_graph.document_id)
            self.global_entities.setdefault(entity.text.lower(), []).append(entity.id)
        for relationship in knowledge_graph.relationships:
            self.global_graph.add_edge(
                relationship.source_entity_id,
                relationship.target_entity_id,
                relationship_id=relationship.id,
                relationship_type=relationship.relationship_type,
                confidence=relationship.confidence,
                document_id=knowledge_graph.document_id,
            )

    def _discover_cross_document_relationships(self, knowledge_graph: KnowledgeGraph) -> List[Dict[str, Any]]:
        discovered: List[Dict[str, Any]] = []
        for entity in knowledge_graph.entities:
            existing_ids = self.global_entities.get(entity.text.lower(), [])
            for other_id in existing_ids:
                if other_id == entity.id:
                    continue
                other_doc = self.global_graph.nodes.get(other_id, {}).get("document_id")
                if other_doc == knowledge_graph.document_id:
                    continue
                record = {
                    "entity_text": entity.text,
                    "source_document_id": knowledge_graph.document_id,
                    "target_document_id": other_doc,
                    "relationship_type": "shared_entity",
                }
                if record not in self.cross_document_relationships:
                    self.cross_document_relationships.append(record)
                    discovered.append(record)
        return discovered

    def _find_similar_entities(self, entity: Entity, candidates: Optional[Iterable[Entity]] = None) -> List[Entity]:
        pool = list(candidates or self.iter_entities())
        return [
            candidate
            for candidate in pool
            if candidate.id != entity.id and self.compute_entity_similarity(entity, candidate) >= self.similarity_threshold
        ]

    def _calculate_text_similarity(self, left: str, right: str) -> float:
        left_tokens = set(re.findall(r"[a-z0-9]+", str(left or "").lower()))
        right_tokens = set(re.findall(r"[a-z0-9]+", str(right or "").lower()))
        if not left_tokens or not right_tokens:
            return 0.0
        union = left_tokens | right_tokens
        if not union:
            return 0.0
        return len(left_tokens & right_tokens) / len(union)

    async def _store_knowledge_graph_ipld(self, knowledge_graph: KnowledgeGraph) -> Optional[str]:
        if self.storage is None or not hasattr(self.storage, "store_json"):
            return None
        payload = knowledge_graph.to_dict()
        try:
            return await asyncio.to_thread(self.storage.store_json, payload)
        except Exception:
            return None

    def build_knowledge_graph(
        self,
        document_id: str,
        entities: List[Entity],
        relationships: List[Relationship],
        *,
        title: str = "",
        chunks: Optional[List[Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> KnowledgeGraph:
        return KnowledgeGraph(
            document_id=document_id,
            title=title,
            chunks=list(chunks or []),
            entities=list(entities),
            relationships=list(self._dedupe_relationships(relationships)),
            metadata=dict(metadata or {}),
        )

    def compute_entity_similarity(self, left: Entity, right: Entity) -> float:
        similarity = self._calculate_text_similarity(left.text, right.text)
        if left.type == right.type:
            similarity = min(1.0, similarity + 0.1)
        return similarity

    def analyze_cross_document_relationships(self, document_ids: List[str]) -> List[Dict[str, Any]]:
        wanted = set(document_ids)
        return [
            rel for rel in self.cross_document_relationships
            if rel.get("source_document_id") in wanted or rel.get("target_document_id") in wanted
        ]

    def query_graph(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        normalized = str(query or "").lower().strip()
        results: List[Dict[str, Any]] = []
        for knowledge_graph in self.knowledge_graphs.values():
            for entity in knowledge_graph.entities:
                if normalized and normalized not in entity.text.lower():
                    continue
                results.append(
                    {
                        "document_id": knowledge_graph.document_id,
                        "entity": entity,
                        "score": self._calculate_text_similarity(query, entity.text),
                    }
                )
        results.sort(key=lambda item: item["score"], reverse=True)
        return results[:limit]

    def query_entities(self, query: str, limit: int = 10) -> List[Entity]:
        return [item["entity"] for item in self.query_graph(query, limit=limit)]

    def get_entity_neighborhood(self, entity_id: str, depth: int = 1) -> Dict[str, Any]:
        if not isinstance(entity_id, str):
            raise TypeError("entity_id must be a string")
        if not entity_id.strip():
            raise ValueError("entity_id must not be empty")
        if not isinstance(depth, int):
            raise TypeError("depth must be an integer")
        if depth < 0:
            raise ValueError("depth must be non-negative")
        if entity_id not in self.global_graph:
            return {"center_entity_id": entity_id, "entities": [], "relationships": []}

        subgraph = nx.ego_graph(self.global_graph, entity_id, radius=depth, undirected=True)
        entity_ids = list(subgraph.nodes)
        relationships = []
        for source_id, target_id, edge_data in subgraph.edges(data=True):
            relationships.append(
                {
                    "source_entity_id": source_id,
                    "target_entity_id": target_id,
                    "relationship_type": edge_data.get("relationship_type", "related_to"),
                    "confidence": edge_data.get("confidence", 0.0),
                }
            )
        return {
            "center_entity_id": entity_id,
            "entities": [subgraph.nodes[node_id] for node_id in entity_ids],
            "relationships": relationships,
        }

    def extract_entities(self, text: str) -> List[Entity]:
        return self._extract_entities_from_text(text)

    def discover_relationships(self, entities: List[Entity], context: str = "") -> List[Relationship]:
        return self._extract_relationships(entities, context)

    def iter_entities(self) -> Iterable[Entity]:
        for knowledge_graph in self.knowledge_graphs.values():
            yield from knowledge_graph.entities

    def _dedupe_relationships(self, relationships: Iterable[Relationship]) -> List[Relationship]:
        deduped: List[Relationship] = []
        seen: set[tuple[str, str, str, Optional[str]]] = set()
        for relationship in relationships:
            key = (
                relationship.source_entity_id,
                relationship.target_entity_id,
                relationship.relationship_type,
                relationship.source_chunk,
            )
            if key in seen:
                continue
            seen.add(key)
            deduped.append(relationship)
        return deduped


def make_graphrag_integrator(*args: Any, **kwargs: Any) -> GraphRAGIntegrator:
    warnings.warn(
        "make_graphrag_integrator is deprecated. Instantiate GraphRAGIntegrator directly.",
        DeprecationWarning,
        stacklevel=2,
    )
    return GraphRAGIntegrator(*args, **kwargs)


__all__ = [
    "GraphRAGIntegrator",
    "Entity",
    "Relationship",
    "KnowledgeGraph",
    "make_graphrag_integrator",
]