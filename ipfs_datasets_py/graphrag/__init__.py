"""Core GraphRAG facade.

This module is the stable, package-level entrypoint for GraphRAG capabilities.
Downstream layers (finance, CLI, MCP tools, dashboards) should import GraphRAG
primitives from here, rather than importing from MCP tool modules.

Design goals:
- Keep imports lightweight and safe in minimal environments.
- Provide best-effort real implementations when dependencies are present.
- Provide stub fallbacks that keep the package importable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


GRAPHRAG_AVAILABLE: bool

try:
    from ipfs_datasets_py.graphrag.integrations.graphrag_integration import (  # type: ignore
        GraphRAGIntegration as GraphRAGIntegration,
    )

    from ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction import (  # type: ignore
        Entity as Entity,
        Relationship as Relationship,
        KnowledgeGraph as KnowledgeGraph,
    )

    GRAPHRAG_AVAILABLE = True
except Exception:  # pragma: no cover
    GRAPHRAG_AVAILABLE = False

    class GraphRAGIntegration:  # type: ignore
        def __init__(self, *_: Any, **__: Any):
            raise RuntimeError(
                "GraphRAG is not available in this environment (missing optional dependencies)."
            )

    @dataclass
    class Entity:  # type: ignore
        entity_id: str
        entity_type: str
        name: str
        properties: Dict[str, Any] = field(default_factory=dict)
        confidence: float = 1.0

        def to_dict(self) -> Dict[str, Any]:
            return {
                "entity_id": self.entity_id,
                "entity_type": self.entity_type,
                "name": self.name,
                "properties": self.properties,
                "confidence": self.confidence,
            }

    @dataclass
    class Relationship:  # type: ignore
        relationship_id: str
        relationship_type: str
        source_entity: Entity
        target_entity: Entity
        properties: Dict[str, Any] = field(default_factory=dict)
        confidence: float = 1.0

        def to_dict(self) -> Dict[str, Any]:
            return {
                "relationship_id": self.relationship_id,
                "relationship_type": self.relationship_type,
                "source_entity": self.source_entity.to_dict(),
                "target_entity": self.target_entity.to_dict(),
                "properties": self.properties,
                "confidence": self.confidence,
            }

    class KnowledgeGraph:  # type: ignore
        def __init__(self):
            self.entities: List[Entity] = []
            self.relationships: List[Relationship] = []

        def add_entity(self, entity: Entity) -> None:
            self.entities.append(entity)

        def add_relationship(self, relationship: Relationship) -> None:
            self.relationships.append(relationship)


def graphrag_status() -> Dict[str, Any]:
    """Return availability info without triggering warnings."""

    return {"available": GRAPHRAG_AVAILABLE}


__all__ = [
    "GRAPHRAG_AVAILABLE",
    "GraphRAGIntegration",
    "Entity",
    "Relationship",
    "KnowledgeGraph",
    "graphrag_status",
]
