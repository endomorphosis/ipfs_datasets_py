"""Reusable source -> fact -> rule -> filing support-map helpers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from ...logic.deontic import DeonticGraph
from ..protocol import Entity, KnowledgeGraph, Relationship


@dataclass(frozen=True)
class SupportFact:
    """A fact proposition and the evidence sources that support it."""

    fact_id: str
    predicate: str
    status: str = "alleged"
    source_ids: List[str] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FilingSupportReference:
    """Identifies a filing and the proposition the filing relies on."""

    filing_id: str
    filing_type: str
    proposition: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class SupportMapEntry:
    """One rule-centered support-map entry."""

    rule_id: str
    target_id: str
    target_label: str
    modality: str
    predicate: str
    active: bool
    facts: List[SupportFact] = field(default_factory=list)
    filings: List[FilingSupportReference] = field(default_factory=list)
    authority_ids: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "target_id": self.target_id,
            "target_label": self.target_label,
            "modality": self.modality,
            "predicate": self.predicate,
            "active": self.active,
            "facts": [fact.to_dict() for fact in self.facts],
            "filings": [filing.to_dict() for filing in self.filings],
            "authority_ids": list(self.authority_ids),
            "evidence_ids": list(self.evidence_ids),
        }


@dataclass
class MotionSupportMap:
    """Collection wrapper for support-map entries."""

    entries: List[SupportMapEntry] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_count": len(self.entries),
            "entries": [entry.to_dict() for entry in self.entries],
        }

    def to_knowledge_graph(self, *, source: str = "support_map") -> KnowledgeGraph:
        """Convert support-map entries to the standard processor KG format."""

        graph = KnowledgeGraph(source=source)
        for entry in self.entries:
            rule_entity_id = f"rule:{entry.rule_id}"
            graph.add_entity(
                Entity(
                    id=rule_entity_id,
                    type="deontic_rule",
                    label=entry.target_label or entry.predicate,
                    properties={
                        "rule_id": entry.rule_id,
                        "modality": entry.modality,
                        "predicate": entry.predicate,
                        "active": entry.active,
                        "authority_ids": list(entry.authority_ids),
                        "evidence_ids": list(entry.evidence_ids),
                    },
                )
            )
            target_entity_id = f"target:{entry.target_id}"
            graph.add_entity(
                Entity(
                    id=target_entity_id,
                    type="governed_target",
                    label=entry.target_label,
                    properties={"target_id": entry.target_id},
                )
            )
            graph.add_relationship(
                Relationship(
                    id=f"rel:{entry.rule_id}:targets",
                    source=rule_entity_id,
                    target=target_entity_id,
                    type="TARGETS",
                )
            )

            for fact in entry.facts:
                fact_entity_id = f"fact:{fact.fact_id}"
                graph.add_entity(
                    Entity(
                        id=fact_entity_id,
                        type="support_fact",
                        label=fact.predicate,
                        properties={
                            "status": fact.status,
                            "source_ids": list(fact.source_ids),
                            **dict(fact.attributes),
                        },
                    )
                )
                graph.add_relationship(
                    Relationship(
                        id=f"rel:{entry.rule_id}:supported_by:{fact.fact_id}",
                        source=rule_entity_id,
                        target=fact_entity_id,
                        type="SUPPORTED_BY",
                    )
                )

            for filing in entry.filings:
                filing_entity_id = f"filing:{filing.filing_id}"
                graph.add_entity(
                    Entity(
                        id=filing_entity_id,
                        type="filing",
                        label=filing.proposition or filing.filing_type,
                        properties={
                            "filing_id": filing.filing_id,
                            "filing_type": filing.filing_type,
                            "proposition": filing.proposition,
                        },
                    )
                )
                graph.add_relationship(
                    Relationship(
                        id=f"rel:{entry.rule_id}:used_in:{filing.filing_id}",
                        source=rule_entity_id,
                        target=filing_entity_id,
                        type="USED_IN",
                    )
                )
        return graph


class SupportMapBuilder:
    """Build support maps from deontic graphs and fact catalogs."""

    def build_from_deontic_graph(
        self,
        graph: DeonticGraph,
        *,
        fact_catalog: Mapping[str, Mapping[str, Any]] | None = None,
        filing_map: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
        only_active: bool = True,
    ) -> MotionSupportMap:
        fact_catalog = fact_catalog or {}
        filing_map = filing_map or {}
        entries: List[SupportMapEntry] = []

        for rule in graph.rules.values():
            if only_active and not rule.active:
                continue
            target = graph.get_node(rule.target_id)
            facts = self._build_fact_entries(rule.source_ids, fact_catalog)
            filings = self._build_filing_entries(rule.id, filing_map.get(rule.id, ()))
            entries.append(
                SupportMapEntry(
                    rule_id=rule.id,
                    target_id=rule.target_id,
                    target_label=target.label if target else rule.target_id,
                    modality=rule.modality.value,
                    predicate=rule.predicate,
                    active=rule.active,
                    facts=facts,
                    filings=filings,
                    authority_ids=list(rule.authority_ids),
                    evidence_ids=list(rule.evidence_ids),
                )
            )

        entries.sort(key=lambda item: (item.active is False, item.rule_id))
        return MotionSupportMap(entries=entries)

    def _build_fact_entries(
        self,
        source_ids: Iterable[str],
        fact_catalog: Mapping[str, Mapping[str, Any]],
    ) -> List[SupportFact]:
        facts: List[SupportFact] = []
        for source_id in source_ids:
            if not str(source_id).startswith("fact:"):
                continue
            payload = fact_catalog.get(str(source_id), {})
            facts.append(
                SupportFact(
                    fact_id=str(source_id),
                    predicate=str(payload.get("predicate") or source_id),
                    status=str(payload.get("status") or "alleged"),
                    source_ids=[
                        str(value)
                        for value in list(payload.get("source_ids") or payload.get("evidence_ids") or [])
                    ],
                    attributes=dict(payload.get("attributes") or {}),
                )
            )
        return facts

    def _build_filing_entries(
        self,
        rule_id: str,
        filings: Sequence[Mapping[str, Any]],
    ) -> List[FilingSupportReference]:
        entries: List[FilingSupportReference] = []
        for item in filings:
            if not isinstance(item, Mapping):
                continue
            entries.append(
                FilingSupportReference(
                    filing_id=str(item.get("filing_id") or rule_id),
                    filing_type=str(item.get("filing_type") or "motion"),
                    proposition=str(item.get("proposition") or ""),
                )
            )
        return entries


__all__ = [
    "FilingSupportReference",
    "MotionSupportMap",
    "SupportFact",
    "SupportMapBuilder",
    "SupportMapEntry",
]
