"""Reusable legal requirements graph helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
import json
from typing import Any, Dict, List, Optional, Sequence

from ..protocol import Entity, KnowledgeGraph, Relationship


def _utc_now_isoformat() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class LegalElement:
    """Represents a legal element or requirement."""

    id: str
    element_type: str
    name: str
    description: str = ""
    citation: str = ""
    jurisdiction: str = ""
    required: bool = True
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LegalRelation:
    """Represents a relationship between legal elements."""

    id: str
    source_id: str
    target_id: str
    relation_type: str
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class LegalRequirementsGraph:
    """Graph representation of legal requirements and relationships."""

    def __init__(self) -> None:
        self.elements: Dict[str, LegalElement] = {}
        self.relations: Dict[str, LegalRelation] = {}
        self.metadata = {
            "created_at": _utc_now_isoformat(),
            "last_updated": _utc_now_isoformat(),
            "version": "1.0",
        }

    def add_element(self, element: LegalElement) -> str:
        self.elements[element.id] = element
        self._update_metadata()
        return element.id

    def add_relation(self, relation: LegalRelation) -> str:
        self.relations[relation.id] = relation
        self._update_metadata()
        return relation.id

    def get_element(self, element_id: str) -> Optional[LegalElement]:
        return self.elements.get(element_id)

    def get_relations_for_element(self, element_id: str) -> List[LegalRelation]:
        return [
            relation
            for relation in self.relations.values()
            if relation.source_id == element_id or relation.target_id == element_id
        ]

    def get_elements_by_type(self, element_type: str) -> List[LegalElement]:
        return [element for element in self.elements.values() if element.element_type == element_type]

    def get_requirements_for_claim_type(self, claim_type: str) -> List[LegalElement]:
        requirements: List[LegalElement] = []
        for element in self.elements.values():
            if element.element_type not in {"requirement", "procedural_requirement"}:
                continue
            applicable_claims = element.attributes.get("applicable_claim_types", [])
            if claim_type in applicable_claims:
                requirements.append(element)
        return requirements

    def summary(self) -> Dict[str, Any]:
        element_counts: Dict[str, int] = {}
        for element in self.elements.values():
            element_counts[element.element_type] = element_counts.get(element.element_type, 0) + 1
        relation_counts: Dict[str, int] = {}
        for relation in self.relations.values():
            relation_counts[relation.relation_type] = relation_counts.get(relation.relation_type, 0) + 1
        return {
            "total_elements": len(self.elements),
            "total_relations": len(self.relations),
            "element_types": element_counts,
            "relation_types": relation_counts,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metadata": dict(self.metadata),
            "elements": {eid: element.to_dict() for eid, element in self.elements.items()},
            "relations": {rid: relation.to_dict() for rid, relation in self.relations.items()},
            "summary": self.summary(),
        }

    def to_json(self, filepath: str) -> None:
        with open(filepath, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LegalRequirementsGraph":
        graph = cls()
        graph.metadata = dict(data.get("metadata") or graph.metadata)
        for element_id, element_data in (data.get("elements") or {}).items():
            graph.elements[element_id] = LegalElement(**dict(element_data))
        for relation_id, relation_data in (data.get("relations") or {}).items():
            graph.relations[relation_id] = LegalRelation(**dict(relation_data))
        return graph

    def to_knowledge_graph(self, *, source: str = "legal_requirements") -> KnowledgeGraph:
        graph = KnowledgeGraph(source=source, properties={"summary": self.summary()})
        for element in self.elements.values():
            graph.add_entity(
                Entity(
                    id=element.id,
                    type=element.element_type,
                    label=element.name,
                    properties={
                        "description": element.description,
                        "citation": element.citation,
                        "jurisdiction": element.jurisdiction,
                        "required": element.required,
                        **dict(element.attributes),
                    },
                )
            )
        for relation in self.relations.values():
            graph.add_relationship(
                Relationship(
                    id=relation.id,
                    source=relation.source_id,
                    target=relation.target_id,
                    type=relation.relation_type.upper(),
                    properties=dict(relation.attributes),
                )
            )
        return graph

    def _update_metadata(self) -> None:
        self.metadata["last_updated"] = _utc_now_isoformat()


class LegalRequirementsGraphBuilder:
    """Build legal requirement graphs from statutes and procedural templates."""

    def __init__(self) -> None:
        self.element_counter = 0
        self.relation_counter = 0

    def build_from_statutes(
        self,
        statutes: Sequence[Dict[str, Any]],
        claim_types: Sequence[str],
    ) -> LegalRequirementsGraph:
        graph = LegalRequirementsGraph()
        statute_elements: List[LegalElement] = []

        for statute in statutes:
            element = LegalElement(
                id=self._get_element_id(),
                element_type="statute",
                name=str(statute.get("name") or "Unnamed Statute"),
                description=str(statute.get("description") or ""),
                citation=str(statute.get("citation") or ""),
                jurisdiction=str(statute.get("jurisdiction") or "US"),
                attributes={"text": str(statute.get("text") or "")},
            )
            graph.add_element(element)
            statute_elements.append(element)

        for statute_element in statute_elements:
            requirements = self._extract_requirements_from_statute(statute_element, list(claim_types))
            for requirement in requirements:
                req_element = LegalElement(
                    id=self._get_element_id(),
                    element_type="requirement",
                    name=requirement["name"],
                    description=requirement.get("description", ""),
                    citation=statute_element.citation,
                    jurisdiction=statute_element.jurisdiction,
                    required=requirement.get("required", True),
                    attributes={
                        "applicable_claim_types": list(claim_types),
                        "source_statute": statute_element.id,
                    },
                )
                graph.add_element(req_element)
                graph.add_relation(
                    LegalRelation(
                        id=self._get_relation_id(),
                        source_id=statute_element.id,
                        target_id=req_element.id,
                        relation_type="provides",
                    )
                )
        return graph

    def build_rules_of_procedure(self, jurisdiction: str = "federal") -> LegalRequirementsGraph:
        graph = LegalRequirementsGraph()
        procedural_requirements = [
            {
                "name": "Statement of Jurisdiction",
                "description": "Must state the basis for the court's jurisdiction",
                "rule": "FRCP 8(a)(1)",
            },
            {
                "name": "Statement of Claim",
                "description": "Must contain a short and plain statement of the claim showing entitlement to relief",
                "rule": "FRCP 8(a)(2)",
            },
            {
                "name": "Demand for Relief",
                "description": "Must state the relief sought",
                "rule": "FRCP 8(a)(3)",
            },
            {
                "name": "Plausible Claim",
                "description": "Facts must plausibly suggest entitlement to relief",
                "rule": "Twombly/Iqbal Standard",
            },
        ]

        for requirement in procedural_requirements:
            graph.add_element(
                LegalElement(
                    id=self._get_element_id(),
                    element_type="procedural_requirement",
                    name=requirement["name"],
                    description=requirement["description"],
                    citation=requirement["rule"],
                    jurisdiction=jurisdiction,
                    required=True,
                    attributes={"category": "civil_procedure"},
                )
            )
        return graph

    def _extract_requirements_from_statute(
        self,
        statute: LegalElement,
        claim_types: List[str],
    ) -> List[Dict[str, Any]]:
        requirements: List[Dict[str, Any]] = []
        claim_type_text = " ".join(claim_types).lower()
        statute_text = f"{statute.name} {statute.description} {statute.attributes.get('text', '')}".lower()

        if "discrimination" in claim_type_text or "discrimination" in statute_text:
            requirements.extend(
                [
                    {
                        "name": "Protected Class Membership",
                        "description": "Plaintiff must be member of protected class",
                        "required": True,
                    },
                    {
                        "name": "Adverse Action",
                        "description": "Plaintiff suffered adverse employment or housing action",
                        "required": True,
                    },
                    {
                        "name": "Causal Connection",
                        "description": "Protected class status was motivating factor",
                        "required": True,
                    },
                ]
            )

        if "contract" in claim_type_text or "contract" in statute_text:
            requirements.extend(
                [
                    {
                        "name": "Valid Contract",
                        "description": "A valid contract existed between the parties",
                        "required": True,
                    },
                    {
                        "name": "Breach",
                        "description": "Defendant breached a contractual duty",
                        "required": True,
                    },
                    {
                        "name": "Damages",
                        "description": "Plaintiff suffered resulting damages",
                        "required": True,
                    },
                ]
            )

        if not requirements:
            requirements.append(
                {
                    "name": "Statutory Applicability",
                    "description": "The cited statute applies to the asserted claim",
                    "required": True,
                }
            )
        return requirements

    def _get_element_id(self) -> str:
        self.element_counter += 1
        return f"legal_elem_{self.element_counter}"

    def _get_relation_id(self) -> str:
        self.relation_counter += 1
        return f"legal_rel_{self.relation_counter}"


__all__ = [
    "LegalElement",
    "LegalRelation",
    "LegalRequirementsGraph",
    "LegalRequirementsGraphBuilder",
]
