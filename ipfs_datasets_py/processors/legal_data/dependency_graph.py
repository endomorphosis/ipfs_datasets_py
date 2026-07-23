"""Dependency graph helpers for claims, evidence, and legal requirements."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from ..protocol import Entity, KnowledgeGraph, Relationship
from .claim_intake import normalize_claim_type, registry_for_claim_type


def _utc_now_isoformat() -> str:
    return datetime.now(UTC).isoformat()


class NodeType(Enum):
    CLAIM = "claim"
    EVIDENCE = "evidence"
    REQUIREMENT = "requirement"
    FACT = "fact"
    LEGAL_ELEMENT = "legal_element"


class DependencyType(Enum):
    REQUIRES = "requires"
    SUPPORTS = "supports"
    CONTRADICTS = "contradicts"
    IMPLIES = "implies"
    DEPENDS_ON = "depends_on"


@dataclass
class DependencyNode:
    id: str
    node_type: NodeType
    name: str
    description: str = ""
    satisfied: bool = False
    confidence: float = 0.0
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["node_type"] = self.node_type.value
        return payload


@dataclass
class Dependency:
    id: str
    source_id: str
    target_id: str
    dependency_type: DependencyType
    required: bool = True
    strength: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["dependency_type"] = self.dependency_type.value
        return payload


class DependencyGraph:
    """Dependency graph for tracking claim requirements and support."""

    def __init__(self) -> None:
        self.nodes: Dict[str, DependencyNode] = {}
        self.dependencies: Dict[str, Dependency] = {}
        self.metadata = {
            "created_at": _utc_now_isoformat(),
            "last_updated": _utc_now_isoformat(),
            "version": "1.0",
        }

    def add_node(self, node: DependencyNode) -> str:
        self.nodes[node.id] = node
        self._update_metadata()
        return node.id

    def add_dependency(self, dependency: Dependency) -> str:
        if dependency.source_id not in self.nodes:
            raise ValueError(f"Source node {dependency.source_id} not found")
        if dependency.target_id not in self.nodes:
            raise ValueError(f"Target node {dependency.target_id} not found")
        self.dependencies[dependency.id] = dependency
        self._update_metadata()
        return dependency.id

    def get_node(self, node_id: str) -> Optional[DependencyNode]:
        return self.nodes.get(node_id)

    def get_dependencies_for_node(self, node_id: str, direction: str = "both") -> List[Dependency]:
        results: List[Dependency] = []
        for dependency in self.dependencies.values():
            if direction in {"incoming", "both"} and dependency.target_id == node_id:
                results.append(dependency)
            if direction in {"outgoing", "both"} and dependency.source_id == node_id:
                results.append(dependency)
        return results

    def get_nodes_by_type(self, node_type: NodeType) -> List[DependencyNode]:
        return [node for node in self.nodes.values() if node.node_type == node_type]

    def check_satisfaction(self, node_id: str) -> Dict[str, Any]:
        node = self.get_node(node_id)
        if not node:
            return {"error": "Node not found"}
        requirements = self.get_dependencies_for_node(node_id, direction="incoming")
        required_dependencies = [dependency for dependency in requirements if dependency.required]
        satisfied_count = 0
        missing_dependencies: List[Dict[str, Any]] = []
        for dependency in required_dependencies:
            source_node = self.get_node(dependency.source_id)
            if source_node and source_node.satisfied:
                satisfied_count += 1
            else:
                missing_dependencies.append(
                    {
                        "dependency_id": dependency.id,
                        "source_node_id": dependency.source_id,
                        "source_name": source_node.name if source_node else "Unknown",
                        "dependency_type": dependency.dependency_type.value,
                    }
                )
        total_required = len(required_dependencies)
        satisfaction_ratio = satisfied_count / total_required if total_required else 1.0
        return {
            "node_id": node_id,
            "node_name": node.name,
            "satisfied": satisfaction_ratio >= 1.0,
            "satisfaction_ratio": satisfaction_ratio,
            "satisfied_count": satisfied_count,
            "total_required": total_required,
            "missing_dependencies": missing_dependencies,
        }

    def find_unsatisfied_requirements(self) -> List[Dict[str, Any]]:
        return [
            check
            for node in self.nodes.values()
            for check in [self.check_satisfaction(node.id)]
            if not check.get("satisfied", False) and check.get("total_required", 0) > 0
        ]

    def get_claim_readiness(self) -> Dict[str, Any]:
        claims = self.get_nodes_by_type(NodeType.CLAIM)
        ready_claims: List[Dict[str, Any]] = []
        not_ready_claims: List[Dict[str, Any]] = []
        for claim in claims:
            status = self.check_satisfaction(claim.id)
            payload = {
                "claim_id": claim.id,
                "claim_name": claim.name,
                "satisfied": status.get("satisfied", False),
                "satisfaction_ratio": status.get("satisfaction_ratio", 0.0),
                "missing_dependencies": status.get("missing_dependencies", []),
            }
            if payload["satisfied"]:
                ready_claims.append(payload)
            else:
                not_ready_claims.append(payload)
        return {
            "total_claims": len(claims),
            "ready_claims": ready_claims,
            "not_ready_claims": not_ready_claims,
            "ready_count": len(ready_claims),
            "not_ready_count": len(not_ready_claims),
        }

    def summary(self) -> Dict[str, Any]:
        node_counts: Dict[str, int] = {}
        for node in self.nodes.values():
            node_counts[node.node_type.value] = node_counts.get(node.node_type.value, 0) + 1
        dependency_counts: Dict[str, int] = {}
        for dependency in self.dependencies.values():
            dependency_counts[dependency.dependency_type.value] = dependency_counts.get(dependency.dependency_type.value, 0) + 1
        return {
            "total_nodes": len(self.nodes),
            "total_dependencies": len(self.dependencies),
            "node_types": node_counts,
            "dependency_types": dependency_counts,
            "unsatisfied_requirements": len(self.find_unsatisfied_requirements()),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metadata": dict(self.metadata),
            "nodes": {node_id: node.to_dict() for node_id, node in self.nodes.items()},
            "dependencies": {
                dependency_id: dependency.to_dict() for dependency_id, dependency in self.dependencies.items()
            },
            "summary": self.summary(),
        }

    def to_knowledge_graph(self, *, source: str = "dependency_graph") -> KnowledgeGraph:
        graph = KnowledgeGraph(source=source, properties={"summary": self.summary()})
        for node in self.nodes.values():
            graph.add_entity(
                Entity(
                    id=node.id,
                    type=node.node_type.value,
                    label=node.name,
                    properties={
                        "description": node.description,
                        "satisfied": node.satisfied,
                        **dict(node.attributes),
                    },
                    confidence=node.confidence,
                )
            )
        for dependency in self.dependencies.values():
            graph.add_relationship(
                Relationship(
                    id=dependency.id,
                    source=dependency.source_id,
                    target=dependency.target_id,
                    type=dependency.dependency_type.value.upper(),
                    properties={"required": dependency.required, "strength": dependency.strength},
                )
            )
        return graph

    def _update_metadata(self) -> None:
        self.metadata["last_updated"] = _utc_now_isoformat()


class DependencyGraphBuilder:
    """Build dependency graphs from claim type registries and support rows."""

    def __init__(self) -> None:
        self.node_counter = 0
        self.dependency_counter = 0

    def build_for_claim(self, claim_type: Any, *, claim_id: str = "", claim_name: str = "") -> DependencyGraph:
        normalized_claim_type = normalize_claim_type(claim_type)
        registry = registry_for_claim_type(normalized_claim_type)
        graph = DependencyGraph()

        resolved_claim_id = claim_id or self._next_node_id("claim")
        graph.add_node(
            DependencyNode(
                id=resolved_claim_id,
                node_type=NodeType.CLAIM,
                name=claim_name or str(registry.get("label") or normalized_claim_type.replace("_", " ").title()),
                satisfied=False,
                confidence=1.0,
                attributes={"claim_type": normalized_claim_type},
            )
        )

        for element in registry.get("elements", []):
            element_id = str(element.get("element_id") or self._next_node_id("requirement"))
            requirement_node_id = f"requirement:{normalized_claim_type}:{element_id}"
            graph.add_node(
                DependencyNode(
                    id=requirement_node_id,
                    node_type=NodeType.REQUIREMENT,
                    name=str(element.get("label") or element_id),
                    satisfied=False,
                    confidence=1.0,
                    attributes=dict(element),
                )
            )
            graph.add_dependency(
                Dependency(
                    id=self._next_dependency_id(),
                    source_id=requirement_node_id,
                    target_id=resolved_claim_id,
                    dependency_type=DependencyType.REQUIRES,
                    required=bool(element.get("blocking", False)),
                    strength=1.0,
                )
            )
        return graph

    def apply_element_statuses(
        self,
        graph: DependencyGraph,
        *,
        required_elements: List[Dict[str, Any]],
        claim_type: Any,
    ) -> DependencyGraph:
        normalized_claim_type = normalize_claim_type(claim_type)
        for element in required_elements:
            element_id = str(element.get("element_id") or "").strip()
            if not element_id:
                continue
            node_id = f"requirement:{normalized_claim_type}:{element_id}"
            node = graph.get_node(node_id)
            if node is None:
                continue
            node.satisfied = str(element.get("status") or "").lower() == "present"
            if "blocking" in element:
                node.attributes["blocking"] = bool(element.get("blocking"))
        return graph

    def _next_node_id(self, prefix: str) -> str:
        self.node_counter += 1
        return f"{prefix}_{self.node_counter}"

    def _next_dependency_id(self) -> str:
        self.dependency_counter += 1
        return f"dependency_{self.dependency_counter}"


__all__ = [
    "Dependency",
    "DependencyGraph",
    "DependencyGraphBuilder",
    "DependencyNode",
    "DependencyType",
    "NodeType",
]
