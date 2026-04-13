"""Agentic proof-assistant artifacts for docket-centered legal reasoning."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence

_LAST_PROOF_PROGRESS: Dict[str, str] = {
    "stage": "",
    "detail": "",
}


def get_proof_assistant_progress() -> Dict[str, str]:
    return dict(_LAST_PROOF_PROGRESS)

from ...logic.deontic import DeonticGraph
from ..protocol import Entity, KnowledgeGraph, Relationship
from .frames import FrameKnowledgeBase
from .proof_tactician import build_proof_tactician_manifest


def _utc_now_isoformat() -> str:
    return datetime.now(UTC).isoformat()


def _safe_identifier(value: Any) -> str:
    text = "".join(ch.lower() if str(ch).isalnum() else "_" for ch in str(value or "")).strip("_")
    return text or "item"


def _normalize_timepoint(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


def _modality_symbol(modality: str) -> str:
    normalized = str(modality or "").strip().lower()
    return {
        "obligation": "O_t",
        "permission": "P_t",
        "prohibition": "F_t",
        "entitlement": "E_t",
    }.get(normalized, "O_t")


@dataclass
class ProofAssistantWorkItem:
    """A queued analysis item maintained by the docket proof assistant."""

    work_item_id: str
    trigger_id: str
    party: str
    source_type: str
    source_id: str
    title: str
    modality: str
    action: str
    status: str = "pending"
    authority_ids: List[str] = field(default_factory=list)
    predicate_refs: List[str] = field(default_factory=list)
    formula_refs: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=_utc_now_isoformat)
    last_updated: str = field(default_factory=_utc_now_isoformat)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DocketProofAssistant:
    """Serializable proof-assistant artifact bundle."""

    dataset_id: str
    docket_id: str
    case_name: str
    court: str
    agenda: List[ProofAssistantWorkItem] = field(default_factory=list)
    temporal_fol: Dict[str, Any] = field(default_factory=dict)
    deontic_cognitive_event_calculus: Dict[str, Any] = field(default_factory=dict)
    knowledge_graph: Dict[str, Any] = field(default_factory=dict)
    frames: Dict[str, Any] = field(default_factory=dict)
    extractors: Dict[str, Any] = field(default_factory=dict)
    trigger_state: Dict[str, Any] = field(default_factory=dict)
    tactician: Dict[str, Any] = field(default_factory=dict)
    party_analysis: Dict[str, Any] = field(default_factory=dict)
    summary: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "docket_id": self.docket_id,
            "case_name": self.case_name,
            "court": self.court,
            "agenda": [item.to_dict() for item in self.agenda],
            "temporal_fol": dict(self.temporal_fol),
            "deontic_temporal_first_order_logic": dict(self.temporal_fol),
            "deontic_cognitive_event_calculus": dict(self.deontic_cognitive_event_calculus),
            "knowledge_graph": dict(self.knowledge_graph),
            "frames": dict(self.frames),
            "frame_logic": dict(self.frames),
            "extractors": dict(self.extractors),
            "trigger_state": dict(self.trigger_state),
            "tactician": dict(self.tactician),
            "party_analysis": dict(self.party_analysis),
            "summary": dict(self.summary),
            "metadata": dict(self.metadata),
        }


class DocketProofAssistantBuilder:
    """Build proof-oriented legal reasoning artifacts from a docket dataset."""

    def build(
        self,
        *,
        dataset_id: str,
        docket_id: str,
        case_name: str,
        court: str,
        documents: Sequence[Any],
        plaintiff_docket: Sequence[Dict[str, Any]],
        defendant_docket: Sequence[Dict[str, Any]],
        authorities: Sequence[Dict[str, Any]],
        knowledge_graph: Optional[Dict[str, Any]] = None,
        deontic_graph: Optional[Dict[str, Any]] = None,
        deontic_triggers: Optional[Dict[str, Any]] = None,
        bm25_index: Optional[Dict[str, Any]] = None,
        vector_index: Optional[Dict[str, Any]] = None,
    ) -> DocketProofAssistant:
        graph = DeonticGraph.from_dict(dict(deontic_graph or {})) if deontic_graph else DeonticGraph()
        trigger_state = dict(deontic_triggers or {})
        trigger_entries = list(trigger_state.get("entries") or [])
        party_analysis = dict(trigger_state.get("party_analysis") or {})
        _LAST_PROOF_PROGRESS.update({"stage": "agenda", "detail": f"entries={len(trigger_entries)}"})
        agenda = self._build_agenda(graph, trigger_entries, party_analysis)
        _LAST_PROOF_PROGRESS.update({"stage": "frames", "detail": f"agenda={len(agenda)}"})
        frames = self._build_frames(
            dataset_id=dataset_id,
            docket_id=docket_id,
            case_name=case_name,
            court=court,
            documents=documents,
            plaintiff_docket=plaintiff_docket,
            defendant_docket=defendant_docket,
            authorities=authorities,
            agenda=agenda,
        )
        _LAST_PROOF_PROGRESS.update({"stage": "temporal_fol", "detail": f"agenda={len(agenda)}"})
        temporal_fol = self._build_temporal_fol(docket_id=docket_id, documents=documents, agenda=agenda)
        _LAST_PROOF_PROGRESS.update({"stage": "dcec", "detail": f"agenda={len(agenda)}"})
        dcec = self._build_dcec(docket_id=docket_id, documents=documents, agenda=agenda)
        _LAST_PROOF_PROGRESS.update({"stage": "proof_kg", "detail": f"agenda={len(agenda)}"})
        proof_kg = self._build_proof_knowledge_graph(
            dataset_id=dataset_id,
            docket_id=docket_id,
            case_name=case_name,
            court=court,
            base_knowledge_graph=knowledge_graph,
            graph=graph,
            trigger_entries=trigger_entries,
            agenda=agenda,
        )
        _LAST_PROOF_PROGRESS.update({"stage": "tactician", "detail": f"agenda={len(agenda)}"})
        tactician = build_proof_tactician_manifest(
            dataset_id=dataset_id,
            docket_id=docket_id,
            agenda=[item.to_dict() for item in agenda],
            documents=documents,
            authorities=authorities,
            bm25_index=bm25_index,
            vector_index=vector_index,
        )
        _LAST_PROOF_PROGRESS.update({"stage": "party_analysis", "detail": f"agenda={len(agenda)}"})
        enriched_party_analysis = self._enrich_party_analysis(party_analysis=party_analysis, agenda=agenda)
        extractor_status = {
            "deontic_temporal_first_order_logic": {
                "name": "deontic_temporal_first_order_logic",
                "status": "ready",
                "formula_count": len(list(temporal_fol.get("formulas") or [])),
                "fact_count": len(list(temporal_fol.get("facts") or [])),
            },
            "knowledge_graph": {
                "name": "knowledge_graph",
                "status": "ready",
                "entity_count": len(list((proof_kg or {}).get("entities") or [])),
                "relationship_count": len(list((proof_kg or {}).get("relationships") or [])),
            },
            "deontic_cognitive_event_calculus": {
                "name": "deontic_cognitive_event_calculus",
                "status": "ready",
                "event_count": len(list(dcec.get("events") or [])),
                "formula_count": len(list(dcec.get("formulas") or [])),
            },
            "frame_logic": {
                "name": "frame_logic",
                "status": "ready",
                "frame_count": len(frames),
            },
            "trigger_monitor": {
                "name": "trigger_monitor",
                "status": "ready",
                "work_item_count": len(agenda),
                "pending_work_item_count": sum(1 for item in agenda if item.status == "pending"),
            },
            "proof_tactician": {
                "name": "proof_tactician",
                "status": "ready",
                "plan_count": len(list(tactician.get("plans") or [])),
            },
        }
        summary = {
            "work_item_count": len(agenda),
            "pending_work_item_count": sum(1 for item in agenda if item.status == "pending"),
            "party_count": len(enriched_party_analysis),
            "frame_count": len(frames),
            "temporal_formula_count": len(list(temporal_fol.get("formulas") or [])),
            "dcec_formula_count": len(list(dcec.get("formulas") or [])),
            "tactician_plan_count": len(list(tactician.get("plans") or [])),
            "proof_knowledge_graph_entity_count": len(list((proof_kg or {}).get("entities") or [])),
            "proof_knowledge_graph_relationship_count": len(list((proof_kg or {}).get("relationships") or [])),
            "extractor_count": len(extractor_status),
        }
        _LAST_PROOF_PROGRESS.update({"stage": "finalize", "detail": f"work_items={len(agenda)}"})
        return DocketProofAssistant(
            dataset_id=dataset_id,
            docket_id=docket_id,
            case_name=case_name,
            court=court,
            agenda=agenda,
            temporal_fol=temporal_fol,
            deontic_cognitive_event_calculus=dcec,
            knowledge_graph=proof_kg,
            frames=frames,
            extractors=extractor_status,
            trigger_state=trigger_state,
            tactician=tactician,
            party_analysis=enriched_party_analysis,
            summary=summary,
            metadata={
                "built_at": _utc_now_isoformat(),
                "artifact_version": "1.1",
                "agent_kind": "docket_proof_assistant",
                "agent_mode": "triggered_refresh",
            },
        )

    def _build_agenda(
        self,
        graph: DeonticGraph,
        trigger_entries: Sequence[Dict[str, Any]],
        party_analysis: Dict[str, Any],
    ) -> List[ProofAssistantWorkItem]:
        authority_map = {rule.id: list(rule.authority_ids) for rule in graph.rules.values()}
        formula_map = self._rule_formula_refs(graph)
        agenda: List[ProofAssistantWorkItem] = []
        for entry in trigger_entries:
            if not entry.get("needs_analysis"):
                continue
            party = str(entry.get("party") or "").strip().lower()
            target_parties = [
                str(value or "").strip().lower()
                for value in list(entry.get("target_parties") or [])
                if str(value or "").strip()
            ]
            parties = [party] if party in {"plaintiff", "defendant"} else []
            for target_party in target_parties:
                if target_party in {"plaintiff", "defendant"} and target_party not in parties:
                    parties.append(target_party)
            for subject in parties or ["all"]:
                rule_ids = [
                    rule.id
                    for rule in graph.rules.values()
                    if str((rule.attributes or {}).get("trigger_id") or "") == str(entry.get("trigger_id") or "")
                    and (
                        str((rule.attributes or {}).get("party") or "").strip().lower() == subject
                        or subject == "all"
                    )
                ]
                authority_ids: List[str] = []
                for rule_id in rule_ids:
                    for authority_id in authority_map.get(rule_id, []):
                        if authority_id not in authority_ids:
                            authority_ids.append(authority_id)
                work_item = ProofAssistantWorkItem(
                    work_item_id=f"{entry.get('trigger_id')}:proof:{subject}",
                    trigger_id=str(entry.get("trigger_id") or ""),
                    party=subject,
                    source_type=str(entry.get("source_type") or ""),
                    source_id=str(entry.get("source_id") or ""),
                    title=str(entry.get("title") or ""),
                    modality=str(entry.get("modality") or "obligation"),
                    action=str(entry.get("action") or "analyze docket obligation"),
                    authority_ids=authority_ids,
                    predicate_refs=[
                        f"{subject}_{_safe_identifier(entry.get('action') or 'obligation')}",
                        f"trigger_{_safe_identifier(entry.get('trigger_id') or '')}",
                    ],
                    formula_refs=[ref for rule_id in rule_ids for ref in formula_map.get(rule_id, [])],
                )
                agenda.append(work_item)
        for party, analysis in sorted(party_analysis.items()):
            normalized_party = str(party or "").strip().lower()
            if normalized_party not in {"plaintiff", "defendant"}:
                continue
            for trigger_type, reason_key, status in (
                ("source_gap_review", "source_gap_count", "pending"),
                ("conflict_review", "conflict_count", "pending"),
            ):
                count = int(analysis.get(reason_key) or 0)
                if count <= 0:
                    continue
                work_item_id = f"proof_followup:{normalized_party}:{trigger_type}"
                if any(existing.work_item_id == work_item_id for existing in agenda):
                    continue
                agenda.append(
                    ProofAssistantWorkItem(
                        work_item_id=work_item_id,
                        trigger_id=work_item_id,
                        party=normalized_party,
                        source_type="party_analysis",
                        source_id=normalized_party,
                        title=f"{normalized_party.title()} {trigger_type.replace('_', ' ')}",
                        modality="obligation",
                        action=f"review {count} {trigger_type.replace('_', ' ')} item(s)",
                        status=status,
                        authority_ids=list(analysis.get("authority_ids") or []),
                        predicate_refs=[f"{normalized_party}_{trigger_type}"],
                        formula_refs=[f"tdfol:{normalized_party}:{trigger_type}", f"dcec:{normalized_party}:{trigger_type}"],
                    )
                )
        return agenda

    def _build_frames(
        self,
        *,
        dataset_id: str,
        docket_id: str,
        case_name: str,
        court: str,
        documents: Sequence[Any],
        plaintiff_docket: Sequence[Dict[str, Any]],
        defendant_docket: Sequence[Dict[str, Any]],
        authorities: Sequence[Dict[str, Any]],
        agenda: Sequence[ProofAssistantWorkItem],
    ) -> Dict[str, Any]:
        kb = FrameKnowledgeBase()
        kb.add_fact(f"{dataset_id}:case", "Docket case", "case_name", case_name, "dataset")
        kb.add_fact(f"{dataset_id}:case", "Docket case", "court", court, "dataset")
        kb.add_fact(f"{dataset_id}:case", "Docket case", "docket_id", docket_id, "dataset")

        for document in documents:
            document_id = str(getattr(document, "document_id", "") or getattr(document, "id", "") or "document")
            kb.add_fact(f"{dataset_id}:document:{_safe_identifier(document_id)}", "Docket document", "title", str(getattr(document, "title", "") or ""), "document")
            if str(getattr(document, "date_filed", "") or "").strip():
                kb.add_fact(
                    f"{dataset_id}:document:{_safe_identifier(document_id)}",
                    "Docket document",
                    "date_filed",
                    str(getattr(document, "date_filed", "") or ""),
                    "document",
                )

        for party, items in (("plaintiff", plaintiff_docket), ("defendant", defendant_docket)):
            for item in items:
                item_id = str(item.get("id") or item.get("title") or item.get("text") or "")
                frame_id = f"{dataset_id}:{party}:docket:{_safe_identifier(item_id)}"
                kb.add_fact(frame_id, f"{party.title()} docket entry", "title", str(item.get("title") or ""), party)
                kb.add_fact(frame_id, f"{party.title()} docket entry", "text", str(item.get("text") or ""), party)

        for authority in authorities:
            authority_id = str(authority.get("id") or authority.get("title") or authority.get("text") or "")
            frame_id = f"{dataset_id}:authority:{_safe_identifier(authority_id)}"
            kb.add_fact(frame_id, "Authority", "title", str(authority.get("title") or authority.get("label") or ""), "authority")
            kb.add_fact(frame_id, "Authority", "text", str(authority.get("text") or ""), "authority")

        for item in agenda:
            frame_id = f"{dataset_id}:proof:{_safe_identifier(item.work_item_id)}"
            kb.add_fact(frame_id, "Proof task", "party", item.party, "proof_assistant")
            kb.add_fact(frame_id, "Proof task", "modality", item.modality, "proof_assistant")
            kb.add_fact(frame_id, "Proof task", "action", item.action, "proof_assistant")
            kb.add_fact(frame_id, "Proof task", "trigger_id", item.trigger_id, "proof_assistant")
            for authority_id in item.authority_ids:
                kb.add_fact(frame_id, "Proof task", "authority_id", authority_id, "proof_assistant")
        return kb.to_dict()

    def _build_temporal_fol(
        self,
        *,
        docket_id: str,
        documents: Sequence[Any],
        agenda: Sequence[ProofAssistantWorkItem],
    ) -> Dict[str, Any]:
        formulas: List[str] = []
        facts: List[str] = []
        for document in documents:
            document_id = str(getattr(document, "document_id", "") or getattr(document, "id", "") or "document")
            timepoint = _normalize_timepoint(getattr(document, "date_filed", ""), "t_unknown")
            facts.append(f"Filed({document_id}, {timepoint}).")
        for item in agenda:
            predicate = f"{item.party.title()}Action({_safe_identifier(item.action)}, t)"
            trigger_predicate = f"DocketTrigger({_safe_identifier(item.trigger_id)}, t)"
            formulas.append(f"forall t. {trigger_predicate} -> {_modality_symbol(item.modality)}({predicate}).")
            formulas.append(
                f"forall t. {_modality_symbol(item.modality)}({predicate}) -> AnalyzeDuty({item.party.title()}, {_safe_identifier(item.source_id)}, t)."
            )
        return {
            "backend": "temporal_deontic_first_order_logic",
            "docket_id": docket_id,
            "facts": facts,
            "formulas": formulas,
        }

    def _build_dcec(
        self,
        *,
        docket_id: str,
        documents: Sequence[Any],
        agenda: Sequence[ProofAssistantWorkItem],
    ) -> Dict[str, Any]:
        events: List[Dict[str, Any]] = []
        formulas: List[str] = []
        for document in documents:
            document_id = str(getattr(document, "document_id", "") or getattr(document, "id", "") or "document")
            timepoint = _normalize_timepoint(getattr(document, "date_filed", ""), "t_unknown")
            events.append({"event_id": f"filing_{_safe_identifier(document_id)}", "kind": "document_filed", "time": timepoint})
            formulas.append(f"Happens(DocumentFiled({_safe_identifier(document_id)}), {timepoint}).")
        for item in agenda:
            event_name = f"TriggerObserved({_safe_identifier(item.trigger_id)})"
            status_name = f"{item.modality.title()}({_safe_identifier(item.party)}_{_safe_identifier(item.action)})"
            formulas.append(f"Happens({event_name}, t).")
            formulas.append(f"Initiates({event_name}, {status_name}, t).")
            formulas.append(f"HoldsAt({status_name}, t) -> NeedsProofReview({_safe_identifier(item.work_item_id)}, t).")
        return {
            "backend": "deontic_cognitive_event_calculus",
            "docket_id": docket_id,
            "events": events,
            "formulas": formulas,
        }

    def _build_proof_knowledge_graph(
        self,
        *,
        dataset_id: str,
        docket_id: str,
        case_name: str,
        court: str,
        base_knowledge_graph: Optional[Dict[str, Any]],
        graph: DeonticGraph,
        trigger_entries: Sequence[Dict[str, Any]],
        agenda: Sequence[ProofAssistantWorkItem],
    ) -> Dict[str, Any]:
        proof_kg = KnowledgeGraph(source=f"{dataset_id}:proof_assistant")
        docket_node_id = f"{dataset_id}:proof:docket"
        assistant_node_id = f"{dataset_id}:proof:assistant"
        proof_kg.add_entity(Entity(id=docket_node_id, type="docket", label=case_name, properties={"docket_id": docket_id, "court": court}))
        proof_kg.add_entity(Entity(id=assistant_node_id, type="proof_assistant", label="Agentic proof assistant", properties={"dataset_id": dataset_id}))
        proof_kg.add_relationship(Relationship(id=f"{assistant_node_id}:monitors", source=assistant_node_id, target=docket_node_id, type="MONITORS"))

        for entity in list((base_knowledge_graph or {}).get("entities") or []):
            entity_id = str(entity.get("id") or "")
            if not entity_id:
                continue
            proof_kg.add_entity(
                Entity(
                    id=entity_id,
                    type=str(entity.get("type") or "entity"),
                    label=str(entity.get("label") or entity_id),
                    properties=dict(entity.get("properties") or {}),
                )
            )
        for relationship in list((base_knowledge_graph or {}).get("relationships") or []):
            rel_id = str(relationship.get("id") or "")
            source = str(relationship.get("source") or "")
            target = str(relationship.get("target") or "")
            if not rel_id or not source or not target:
                continue
            proof_kg.add_relationship(
                Relationship(
                    id=rel_id,
                    source=source,
                    target=target,
                    type=str(relationship.get("type") or "RELATED_TO"),
                )
            )

        for entry in trigger_entries:
            trigger_id = str(entry.get("trigger_id") or "")
            if not trigger_id:
                continue
            proof_kg.add_entity(
                Entity(
                    id=trigger_id,
                    type="deontic_trigger",
                    label=str(entry.get("title") or trigger_id),
                    properties={
                        "party": entry.get("party"),
                        "source_type": entry.get("source_type"),
                        "modality": entry.get("modality"),
                        "action": entry.get("action"),
                    },
                )
            )
            proof_kg.add_relationship(
                Relationship(
                    id=f"{assistant_node_id}:tracks:{_safe_identifier(trigger_id)}",
                    source=assistant_node_id,
                    target=trigger_id,
                    type="TRACKS_TRIGGER",
                )
            )

        for rule in graph.rules.values():
            rule_id = f"{dataset_id}:proof:rule:{_safe_identifier(rule.id)}"
            proof_kg.add_entity(
                Entity(
                    id=rule_id,
                    type="deontic_rule",
                    label=rule.predicate,
                    properties={
                        "modality": rule.modality.value,
                        "active": rule.active,
                        "rule_id": rule.id,
                    },
                )
            )
            proof_kg.add_relationship(
                Relationship(
                    id=f"{assistant_node_id}:governs:{_safe_identifier(rule.id)}",
                    source=assistant_node_id,
                    target=rule_id,
                    type="GOVERNS",
                )
            )
            trigger_id = str((rule.attributes or {}).get("trigger_id") or "")
            if trigger_id:
                proof_kg.add_relationship(
                    Relationship(
                        id=f"{rule_id}:trigger:{_safe_identifier(trigger_id)}",
                        source=trigger_id,
                        target=rule_id,
                        type="TRIGGERED_RULE",
                    )
                )

        for item in agenda:
            work_item_id = f"{dataset_id}:proof:task:{_safe_identifier(item.work_item_id)}"
            proof_kg.add_entity(
                Entity(
                    id=work_item_id,
                    type="proof_task",
                    label=item.title,
                    properties={
                        "party": item.party,
                        "modality": item.modality,
                        "action": item.action,
                        "status": item.status,
                    },
                )
            )
            proof_kg.add_relationship(
                Relationship(
                    id=f"{assistant_node_id}:agenda:{_safe_identifier(item.work_item_id)}",
                    source=assistant_node_id,
                    target=work_item_id,
                    type="QUEUES_ANALYSIS",
                )
            )
            if item.trigger_id:
                proof_kg.add_relationship(
                    Relationship(
                        id=f"{work_item_id}:from:{_safe_identifier(item.trigger_id)}",
                        source=item.trigger_id,
                        target=work_item_id,
                        type="TRIGGERS_ANALYSIS",
                    )
                )
        return proof_kg.to_dict()

    def _enrich_party_analysis(
        self,
        *,
        party_analysis: Dict[str, Any],
        agenda: Sequence[ProofAssistantWorkItem],
    ) -> Dict[str, Any]:
        enriched = {str(key): dict(value or {}) for key, value in party_analysis.items()}
        for item in agenda:
            analysis = enriched.setdefault(item.party, {"party": item.party})
            analysis.setdefault("proof_work_item_ids", [])
            analysis.setdefault("proof_formula_refs", [])
            analysis.setdefault("proof_predicate_refs", [])
            analysis["proof_work_item_ids"].append(item.work_item_id)
            analysis["proof_formula_refs"].extend(ref for ref in item.formula_refs if ref not in analysis["proof_formula_refs"])
            analysis["proof_predicate_refs"].extend(
                ref for ref in item.predicate_refs if ref not in analysis["proof_predicate_refs"]
            )
            analysis["proof_work_item_count"] = len(list(analysis.get("proof_work_item_ids") or []))
        return enriched

    def _rule_formula_refs(self, graph: DeonticGraph) -> Dict[str, List[str]]:
        refs: Dict[str, List[str]] = {}
        for rule in graph.rules.values():
            refs[rule.id] = [
                f"tdfol:{_safe_identifier(rule.id)}",
                f"dcec:{_safe_identifier(rule.id)}",
            ]
        return refs


def build_docket_proof_assistant(
    *,
    dataset_id: str,
    docket_id: str,
    case_name: str,
    court: str,
    documents: Sequence[Any],
    plaintiff_docket: Sequence[Dict[str, Any]],
    defendant_docket: Sequence[Dict[str, Any]],
    authorities: Sequence[Dict[str, Any]],
    knowledge_graph: Optional[Dict[str, Any]] = None,
    deontic_graph: Optional[Dict[str, Any]] = None,
    deontic_triggers: Optional[Dict[str, Any]] = None,
    bm25_index: Optional[Dict[str, Any]] = None,
    vector_index: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build the docket proof-assistant artifact bundle."""

    assistant = DocketProofAssistantBuilder().build(
        dataset_id=dataset_id,
        docket_id=docket_id,
        case_name=case_name,
        court=court,
        documents=documents,
        plaintiff_docket=plaintiff_docket,
        defendant_docket=defendant_docket,
        authorities=authorities,
        knowledge_graph=knowledge_graph,
        deontic_graph=deontic_graph,
        deontic_triggers=deontic_triggers,
        bm25_index=bm25_index,
        vector_index=vector_index,
    )
    return assistant.to_dict()


__all__ = [
    "DocketProofAssistant",
    "DocketProofAssistantBuilder",
    "ProofAssistantWorkItem",
    "build_docket_proof_assistant",
]
