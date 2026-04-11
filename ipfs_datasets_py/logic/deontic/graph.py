"""
Reusable deontic graph primitives.

This module provides a lightweight graph for tracking obligations,
permissions, prohibitions, and entitlements in a form that can be
serialized, inspected, and reused across legal-reasoning pipelines.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional


def _utc_now_isoformat() -> str:
    return datetime.now(UTC).isoformat()


class DeonticNodeType(Enum):
    """Types of nodes used in the deontic graph."""

    ACTOR = "actor"
    FACT = "fact"
    CONDITION = "condition"
    ACTION = "action"
    OUTCOME = "outcome"
    AUTHORITY = "authority"


class DeonticModality(Enum):
    """Supported deontic modalities."""

    OBLIGATION = "obligation"
    PROHIBITION = "prohibition"
    PERMISSION = "permission"
    ENTITLEMENT = "entitlement"


@dataclass
class DeonticNode:
    """A node in the deontic graph."""

    id: str
    node_type: DeonticNodeType
    label: str
    active: bool = False
    confidence: float = 0.0
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["node_type"] = self.node_type.value
        return payload


@dataclass
class DeonticRule:
    """A deontic rule connecting source nodes to a governed target node."""

    id: str
    modality: DeonticModality
    source_ids: List[str]
    target_id: str
    predicate: str
    active: bool = False
    confidence: float = 0.0
    authority_ids: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)
    attributes: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["modality"] = self.modality.value
        return payload


@dataclass
class DeonticConflict:
    """Potential conflict between two deontic rules over the same target."""

    rule_id: str
    conflicting_rule_id: str
    target_id: str
    modalities: List[str]
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DeonticRuleAssessment:
    """Assessment of whether rule sources are satisfied or missing."""

    rule_id: str
    target_id: str
    modality: str
    active: bool
    satisfied_sources: List[str] = field(default_factory=list)
    missing_sources: List[str] = field(default_factory=list)
    authority_ids: List[str] = field(default_factory=list)
    evidence_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class DeonticGraph:
    """Graph container for deontic rules and their supporting nodes."""

    def __init__(self) -> None:
        self.nodes: Dict[str, DeonticNode] = {}
        self.rules: Dict[str, DeonticRule] = {}
        self.metadata = {
            "created_at": _utc_now_isoformat(),
            "last_updated": _utc_now_isoformat(),
            "version": "1.0",
        }

    def add_node(self, node: DeonticNode) -> str:
        self.nodes[node.id] = node
        self._update_metadata()
        return node.id

    def add_rule(self, rule: DeonticRule) -> str:
        self.rules[rule.id] = rule
        self._update_metadata()
        return rule.id

    def get_node(self, node_id: str) -> Optional[DeonticNode]:
        return self.nodes.get(node_id)

    def rules_for_target(self, target_id: str) -> List[DeonticRule]:
        return [rule for rule in self.rules.values() if rule.target_id == target_id]

    def rules_for_source(self, source_id: str) -> List[DeonticRule]:
        return [rule for rule in self.rules.values() if source_id in rule.source_ids]

    def active_rules(self) -> List[DeonticRule]:
        return [rule for rule in self.rules.values() if rule.active]

    def inactive_rules(self) -> List[DeonticRule]:
        return [rule for rule in self.rules.values() if not rule.active]

    def modality_distribution(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for rule in self.rules.values():
            counts[rule.modality.value] = counts.get(rule.modality.value, 0) + 1
        return counts

    def active_modality_distribution(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for rule in self.active_rules():
            counts[rule.modality.value] = counts.get(rule.modality.value, 0) + 1
        return counts

    def node_type_distribution(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for node in self.nodes.values():
            counts[node.node_type.value] = counts.get(node.node_type.value, 0) + 1
        return counts

    def governed_targets(self) -> List[str]:
        seen: List[str] = []
        for rule in self.rules.values():
            if rule.target_id not in seen:
                seen.append(rule.target_id)
        return seen

    def summary(self) -> Dict[str, Any]:
        return {
            "total_nodes": len(self.nodes),
            "total_rules": len(self.rules),
            "active_rule_count": len(self.active_rules()),
            "inactive_rule_count": len(self.inactive_rules()),
            "node_types": self.node_type_distribution(),
            "modalities": self.modality_distribution(),
            "active_modalities": self.active_modality_distribution(),
            "governed_target_count": len(self.governed_targets()),
        }

    def assess_rules(self) -> List[DeonticRuleAssessment]:
        assessments: List[DeonticRuleAssessment] = []
        for rule in self.rules.values():
            satisfied_sources: List[str] = []
            missing_sources: List[str] = []
            for source_id in rule.source_ids:
                node = self.nodes.get(source_id)
                if node is None:
                    missing_sources.append(source_id)
                elif node.active:
                    satisfied_sources.append(source_id)
                else:
                    missing_sources.append(source_id)
            assessments.append(
                DeonticRuleAssessment(
                    rule_id=rule.id,
                    target_id=rule.target_id,
                    modality=rule.modality.value,
                    active=rule.active,
                    satisfied_sources=satisfied_sources,
                    missing_sources=missing_sources,
                    authority_ids=list(rule.authority_ids),
                    evidence_ids=list(rule.evidence_ids),
                )
            )
        return assessments

    def source_gap_summary(self) -> Dict[str, Any]:
        assessments = self.assess_rules()
        return {
            "rule_count": len(assessments),
            "fully_supported_rule_count": sum(1 for item in assessments if not item.missing_sources),
            "rules_with_gaps": [item.to_dict() for item in assessments if item.missing_sources],
        }

    def detect_conflicts(self, *, only_active: bool = True) -> List[DeonticConflict]:
        conflicts: List[DeonticConflict] = []
        rules = [rule for rule in self.rules.values() if rule.active or not only_active]
        seen_pairs: set[tuple[str, str]] = set()
        for index, left in enumerate(rules):
            for right in rules[index + 1 :]:
                if left.target_id != right.target_id:
                    continue
                if left.predicate != right.predicate:
                    continue
                if not _modalities_conflict(left.modality, right.modality):
                    continue
                pair = tuple(sorted((left.id, right.id)))
                if pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                conflicts.append(
                    DeonticConflict(
                        rule_id=left.id,
                        conflicting_rule_id=right.id,
                        target_id=left.target_id,
                        modalities=[left.modality.value, right.modality.value],
                        reason="Rules govern the same target and predicate with incompatible modalities.",
                    )
                )
        return conflicts

    def export_reasoning_rows(self) -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for assessment in self.assess_rules():
            target = self.nodes.get(assessment.target_id)
            rows.append(
                {
                    "rule_id": assessment.rule_id,
                    "target_id": assessment.target_id,
                    "target_label": target.label if target else assessment.target_id,
                    "modality": assessment.modality,
                    "active": assessment.active,
                    "satisfied_sources": list(assessment.satisfied_sources),
                    "missing_sources": list(assessment.missing_sources),
                    "authority_ids": list(assessment.authority_ids),
                    "evidence_ids": list(assessment.evidence_ids),
                }
            )
        return rows

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metadata": dict(self.metadata),
            "nodes": {node_id: node.to_dict() for node_id, node in self.nodes.items()},
            "rules": {rule_id: rule.to_dict() for rule_id, rule in self.rules.items()},
            "summary": self.summary(),
        }

    def to_json(self, filepath: str) -> None:
        with open(filepath, "w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DeonticGraph":
        graph = cls()
        graph.metadata = dict(data.get("metadata") or graph.metadata)
        for node_id, node_data in (data.get("nodes") or {}).items():
            graph.nodes[node_id] = DeonticNode(
                id=str(node_data.get("id") or node_id),
                node_type=DeonticNodeType(
                    str(node_data.get("node_type") or DeonticNodeType.FACT.value)
                ),
                label=str(node_data.get("label") or ""),
                active=bool(node_data.get("active", False)),
                confidence=float(node_data.get("confidence", 0.0) or 0.0),
                attributes=dict(node_data.get("attributes") or {}),
            )
        for rule_id, rule_data in (data.get("rules") or {}).items():
            graph.rules[rule_id] = DeonticRule(
                id=str(rule_data.get("id") or rule_id),
                modality=DeonticModality(
                    str(rule_data.get("modality") or DeonticModality.OBLIGATION.value)
                ),
                source_ids=[str(value) for value in list(rule_data.get("source_ids") or [])],
                target_id=str(rule_data.get("target_id") or ""),
                predicate=str(rule_data.get("predicate") or ""),
                active=bool(rule_data.get("active", False)),
                confidence=float(rule_data.get("confidence", 0.0) or 0.0),
                authority_ids=[str(value) for value in list(rule_data.get("authority_ids") or [])],
                evidence_ids=[str(value) for value in list(rule_data.get("evidence_ids") or [])],
                attributes=dict(rule_data.get("attributes") or {}),
            )
        return graph

    @classmethod
    def from_json(cls, filepath: str) -> "DeonticGraph":
        with open(filepath, "r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))

    def _update_metadata(self) -> None:
        self.metadata["last_updated"] = _utc_now_isoformat()


class DeonticGraphBuilder:
    """Helpers for building reusable deontic graphs from extracted rule rows."""

    def __init__(self) -> None:
        self._node_counter = 0
        self._rule_counter = 0

    def build_from_matrix(self, rows: Iterable[Dict[str, Any]]) -> DeonticGraph:
        graph = DeonticGraph()
        for row in rows:
            if not isinstance(row, dict):
                continue

            target_id = self._ensure_node(
                graph,
                row.get("target_id"),
                label=str(row.get("target_label") or row.get("predicate") or "Governed action"),
                node_type=DeonticNodeType(
                    str(row.get("target_type") or DeonticNodeType.ACTION.value)
                ),
                active=bool(row.get("target_active", False)),
                confidence=float(row.get("target_confidence", 0.0) or 0.0),
                attributes=dict(row.get("target_attributes") or {}),
            )

            source_ids: List[str] = []
            for source in list(row.get("sources") or []):
                if isinstance(source, dict):
                    source_ids.append(
                        self._ensure_node(
                            graph,
                            source.get("id"),
                            label=str(source.get("label") or source.get("id") or "Condition"),
                            node_type=DeonticNodeType(
                                str(source.get("node_type") or DeonticNodeType.CONDITION.value)
                            ),
                            active=bool(source.get("active", False)),
                            confidence=float(source.get("confidence", 0.0) or 0.0),
                            attributes=dict(source.get("attributes") or {}),
                        )
                    )
                else:
                    source_ids.append(
                        self._ensure_node(
                            graph,
                            str(source),
                            label=str(source),
                            node_type=DeonticNodeType.CONDITION,
                        )
                    )

            authority_ids: List[str] = []
            for authority in list(row.get("authorities") or []):
                authority_ids.append(
                    self._ensure_node(
                        graph,
                        authority.get("id") if isinstance(authority, dict) else str(authority),
                        label=(
                            str(authority.get("label") or authority.get("id") or "Authority")
                            if isinstance(authority, dict)
                            else str(authority)
                        ),
                        node_type=DeonticNodeType.AUTHORITY,
                        attributes=dict(authority.get("attributes") or {}) if isinstance(authority, dict) else {},
                    )
                )

            graph.add_rule(
                DeonticRule(
                    id=str(row.get("rule_id") or self._next_rule_id()),
                    modality=DeonticModality(
                        str(row.get("modality") or DeonticModality.OBLIGATION.value)
                    ),
                    source_ids=source_ids,
                    target_id=target_id,
                    predicate=str(row.get("predicate") or row.get("target_label") or "governs"),
                    active=bool(row.get("active", False)),
                    confidence=float(row.get("confidence", 0.0) or 0.0),
                    authority_ids=authority_ids,
                    evidence_ids=[str(value) for value in list(row.get("evidence_ids") or [])],
                    attributes=dict(row.get("attributes") or {}),
                )
            )
        return graph

    def build_from_findings(
        self,
        findings: Iterable[Dict[str, Any]],
        *,
        default_modality: DeonticModality = DeonticModality.OBLIGATION,
    ) -> DeonticGraph:
        rows: List[Dict[str, Any]] = []
        for index, finding in enumerate(findings):
            if not isinstance(finding, dict):
                continue
            rows.append(
                {
                    "rule_id": finding.get("id") or f"finding_rule_{index + 1}",
                    "modality": finding.get("modality", default_modality.value),
                    "predicate": finding.get("predicate") or finding.get("label") or "governs",
                    "target_id": finding.get("target_id") or finding.get("action_id") or f"action_{index + 1}",
                    "target_label": finding.get("target_label") or finding.get("action") or "Governed action",
                    "target_type": finding.get("target_type") or DeonticNodeType.ACTION.value,
                    "sources": finding.get("sources")
                    or finding.get("conditions")
                    or finding.get("actors")
                    or [],
                    "authorities": finding.get("authorities") or [],
                    "evidence_ids": finding.get("evidence_ids") or [],
                    "confidence": finding.get("confidence", 0.0),
                    "active": finding.get("active", False),
                    "attributes": dict(finding.get("attributes") or {}),
                }
            )
        return self.build_from_matrix(rows)

    def build_from_statements(
        self,
        statements: Iterable[Dict[str, Any]],
        *,
        include_context_as_evidence: bool = True,
    ) -> DeonticGraph:
        """Build a deontic graph directly from analyzer-style statements."""

        rows: List[Dict[str, Any]] = []
        for index, statement in enumerate(statements, start=1):
            if not isinstance(statement, dict):
                continue

            entity_label = str(statement.get("entity") or f"Entity {index}").strip()
            action_label = str(statement.get("action") or "Governed action").strip()
            source_nodes: List[Dict[str, Any]] = [
                {
                    "id": f"actor_{_safe_identifier(entity_label)}",
                    "label": entity_label,
                    "node_type": DeonticNodeType.ACTOR.value,
                    "confidence": float(statement.get("confidence", 0.0) or 0.0),
                }
            ]

            for condition_index, condition in enumerate(statement.get("conditions") or [], start=1):
                source_nodes.append(
                    {
                        "id": f"condition_{index}_{condition_index}",
                        "label": str(condition).strip(),
                        "node_type": DeonticNodeType.CONDITION.value,
                    }
                )

            authority_nodes: List[Dict[str, Any]] = []
            source_name = str(statement.get("document_source") or "").strip()
            if source_name:
                authority_nodes.append(
                    {
                        "id": f"authority_{_safe_identifier(source_name)}",
                        "label": source_name,
                    }
                )

            evidence_ids: List[str] = []
            if include_context_as_evidence:
                context = str(statement.get("context") or "").strip()
                if context:
                    evidence_ids.append(f"context_{index}")

            rows.append(
                {
                    "rule_id": str(statement.get("id") or f"statement_rule_{index}"),
                    "modality": str(statement.get("modality") or DeonticModality.OBLIGATION.value),
                    "predicate": action_label,
                    "target_id": f"action_{_safe_identifier(action_label)}_{index}",
                    "target_label": action_label,
                    "target_type": DeonticNodeType.ACTION.value,
                    "sources": source_nodes,
                    "authorities": authority_nodes,
                    "evidence_ids": evidence_ids,
                    "confidence": float(statement.get("confidence", 0.0) or 0.0),
                    "attributes": {
                        "exceptions": list(statement.get("exceptions") or []),
                        "document_date": statement.get("document_date"),
                        "document_id": statement.get("document_id"),
                        "document_source": statement.get("document_source"),
                        "context": statement.get("context"),
                    },
                }
            )
        return self.build_from_matrix(rows)

    def _ensure_node(
        self,
        graph: DeonticGraph,
        node_id: Any,
        *,
        label: str,
        node_type: DeonticNodeType,
        active: bool = False,
        confidence: float = 0.0,
        attributes: Optional[Dict[str, Any]] = None,
    ) -> str:
        resolved_id = str(node_id or self._next_node_id(node_type))
        existing = graph.get_node(resolved_id)
        if existing is not None:
            return existing.id
        graph.add_node(
            DeonticNode(
                id=resolved_id,
                node_type=node_type,
                label=label,
                active=active,
                confidence=confidence,
                attributes=dict(attributes or {}),
            )
        )
        return resolved_id

    def _next_node_id(self, node_type: DeonticNodeType) -> str:
        self._node_counter += 1
        return f"{node_type.value}_{self._node_counter}"

    def _next_rule_id(self) -> str:
        self._rule_counter += 1
        return f"rule_{self._rule_counter}"


def _safe_identifier(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "_" for char in str(value)).strip("_") or "item"


def _modalities_conflict(left: DeonticModality, right: DeonticModality) -> bool:
    return {
        frozenset((DeonticModality.OBLIGATION, DeonticModality.PROHIBITION)),
        frozenset((DeonticModality.ENTITLEMENT, DeonticModality.PROHIBITION)),
    }.__contains__(frozenset((left, right)))


# ---------------------------------------------------------------------------
# Opportunistic bridge — when lib.deontic_logic is on sys.path (e.g. inside
# the complaint-generator repo), replace the standalone primitives with the
# canonical lib implementations so every consumer shares a single type object.
# DeonticGraphBuilder (unique to this module) is kept as-is; its methods look
# up DeonticGraph/DeonticNode/etc. lazily from module globals, so they
# transparently use the lib classes after this override.
# ---------------------------------------------------------------------------
try:
    from lib.deontic_logic import (  # noqa: E402
        DeonticConflict,
        DeonticGraph,
        DeonticModality,
        DeonticNode,
        DeonticNodeType,
        DeonticRule,
        DeonticRuleAssessment,
    )
except ImportError:  # pragma: no cover - standalone path; definitions above apply
    pass
