"""Repo-native formal logic enrichment for docket datasets."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict
import os
import re
import time
import threading
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from ...knowledge_graphs.extraction import KnowledgeGraphExtractor
from ...logic.CEC.eng_dcec_wrapper import EngDCECWrapper
from ...logic.TDFOL import (
    Constant,
    Predicate,
    create_always,
    create_implication,
    create_obligation,
    create_permission,
    create_prohibition,
)
from ...logic.flogic import FLogicFrame
from ...logic.integration.reasoning.deontological_reasoning import (
    ConflictDetector,
    DeonticExtractor,
)
from ...logic.integration.reasoning.deontological_reasoning_types import (
    ConflictType,
    DeonticConflict,
    DeonticModality,
    DeonticStatement,
)
from ...logic.zkp import ZKPProver
from .reasoner import (
    compile_ir_to_dcec,
    compile_ir_to_temporal_deontic_fol,
    normalize_ir as normalize_v2_ir,
    parse_cnl_to_ir_with_diagnostics,
)


_LAST_FORMAL_PROGRESS: Dict[str, str] = {
    "stage": "",
    "document_id": "",
    "detail": "",
}

_FORMAL_SINGLETON_LOCK = threading.Lock()
_FORMAL_SINGLETONS: Dict[str, Any] | None = None


def _get_formal_singletons() -> Dict[str, Any]:
    global _FORMAL_SINGLETONS
    if _FORMAL_SINGLETONS is not None:
        return _FORMAL_SINGLETONS
    with _FORMAL_SINGLETON_LOCK:
        if _FORMAL_SINGLETONS is None:
            extractor = KnowledgeGraphExtractor(use_spacy=False, use_transformers=False, use_tracer=False, use_srl=False)
            deontic_extractor = DeonticExtractor()
            conflict_detector = ConflictDetector()
            dcec_wrapper = EngDCECWrapper(use_native=True)
            dcec_ready = bool(dcec_wrapper.initialize())
            zkp_prover = ZKPProver(enable_caching=True, backend="simulated")
            _FORMAL_SINGLETONS = {
                "extractor": extractor,
                "deontic_extractor": deontic_extractor,
                "conflict_detector": conflict_detector,
                "dcec_wrapper": dcec_wrapper,
                "dcec_ready": dcec_ready,
                "zkp_prover": zkp_prover,
            }
    return _FORMAL_SINGLETONS or {}


def get_formal_logic_progress() -> Dict[str, str]:
    return dict(_LAST_FORMAL_PROGRESS)


def enrich_docket_documents_with_formal_logic(
    documents: Sequence[Any],
    *,
    docket_id: str,
    case_name: str,
    court: str,
    max_documents: int | None = None,
    max_chars: int = 5000,
) -> Dict[str, Any]:
    """Extract formal artifacts from docket documents using repo-native modules."""

    trace_enabled = str(os.getenv("IPFS_DATASETS_PY_FORMAL_TRACE", "")).strip().lower() in {"1", "true", "yes", "on"}

    def _trace(message: str) -> None:
        if trace_enabled:
            print(f"[formal_trace] {message}", flush=True)
        if message:
            _LAST_FORMAL_PROGRESS["detail"] = message

    heartbeat_raw = str(os.getenv("IPFS_DATASETS_PY_LOGIC_HEARTBEAT_SECONDS", "30")).strip()
    try:
        heartbeat_seconds = max(0.0, float(heartbeat_raw))
    except Exception:
        heartbeat_seconds = 30.0
    status = {
        "stage": "init",
        "document_id": "",
        "processed": 0,
        "skipped": 0,
        "total": 0,
    }
    stop_event = threading.Event()

    def _heartbeat() -> None:
        if not heartbeat_seconds:
            return
        while not stop_event.wait(heartbeat_seconds):
            print(
                "[formal_logic] "
                f"stage={status['stage']} "
                f"document_id={status['document_id']} "
                f"processed={status['processed']} "
                f"skipped={status['skipped']} "
                f"total={status['total']}",
                flush=True,
            )

    heartbeat_thread = threading.Thread(target=_heartbeat, name="formal-logic-heartbeat", daemon=True)
    heartbeat_thread.start()

    singletons = _get_formal_singletons()
    extractor = singletons.get("extractor") or KnowledgeGraphExtractor(
        use_spacy=False, use_transformers=False, use_tracer=False, use_srl=False
    )
    deontic_extractor = singletons.get("deontic_extractor") or DeonticExtractor()
    conflict_detector = singletons.get("conflict_detector") or ConflictDetector()
    dcec_wrapper = singletons.get("dcec_wrapper") or EngDCECWrapper(use_native=True)
    dcec_ready = bool(singletons.get("dcec_ready")) if singletons else bool(dcec_wrapper.initialize())
    zkp_prover = singletons.get("zkp_prover") or ZKPProver(enable_caching=True, backend="simulated")

    analyses: Dict[str, Dict[str, Any]] = {}
    aggregate_entities: List[Dict[str, Any]] = []
    aggregate_relationships: List[Dict[str, Any]] = []
    aggregate_temporal_formulas: List[str] = []
    aggregate_document_temporal_formulas: List[str] = []
    aggregate_dcec_formulas: List[str] = []
    aggregate_frames: Dict[str, Dict[str, Any]] = {}
    aggregate_document_frames: Dict[str, Dict[str, Any]] = {}
    proofs: Dict[str, Dict[str, Any]] = {}
    certificates: List[Dict[str, Any]] = []
    all_statements: List[DeonticStatement] = []
    statements_by_doc: Dict[str, List[DeonticStatement]] = defaultdict(list)
    processed_count = 0
    skipped_count = 0

    selected_documents = list(documents)
    if max_documents is not None:
        selected_documents = selected_documents[: max(0, int(max_documents))]

    status["total"] = len(selected_documents)
    for document in selected_documents:
        document_id = str(getattr(document, "document_id", "") or getattr(document, "id", "") or "")
        title = str(getattr(document, "title", "") or "")
        text = str(getattr(document, "text", "") or "").strip()
        date_filed = str(getattr(document, "date_filed", "") or "")
        status["stage"] = "document_start"
        status["document_id"] = document_id
        status["processed"] = processed_count
        status["skipped"] = skipped_count
        _LAST_FORMAL_PROGRESS.update({"stage": "document_start", "document_id": document_id})
        if not document_id or not (text or title).strip():
            skipped_count += 1
            status["skipped"] = skipped_count
            continue
        payload_text = (text or title)[:max_chars]

        status["stage"] = "kg_extract"
        _LAST_FORMAL_PROGRESS.update({"stage": "kg_extract", "document_id": document_id})
        kg_started = time.monotonic()
        _trace(f"document_id={document_id} stage=kg_extract start")
        kg = extractor.extract_knowledge_graph(payload_text, extraction_temperature=0.45, structure_temperature=0.35)
        _trace(f"document_id={document_id} stage=kg_extract done elapsed={time.monotonic() - kg_started:.2f}s")
        kg_payload = kg.to_dict()
        entities = [_normalize_kg_entity(item, document_id=document_id) for item in list(kg_payload.get("entities") or [])]
        entities = [item for item in entities if item]
        relationships = [
            _normalize_kg_relationship(item, document_id=document_id)
            for item in list(kg_payload.get("relationships") or [])
        ]
        relationships = [item for item in relationships if item]

        status["stage"] = "deontic_extract"
        _LAST_FORMAL_PROGRESS.update({"stage": "deontic_extract", "document_id": document_id})
        deontic_started = time.monotonic()
        _trace(f"document_id={document_id} stage=deontic_extract start")
        statements = deontic_extractor.extract_statements(payload_text, document_id)
        statements.extend(_extract_deontic_statements_fallback(payload_text, document_id=document_id))
        structured_signals = _extract_structured_legal_signals(
            payload_text,
            title=title,
            document_id=document_id,
            court=court,
        )
        _trace(f"document_id={document_id} stage=deontic_extract done elapsed={time.monotonic() - deontic_started:.2f}s")
        statements.extend(list(structured_signals.get("statements") or []))
        statements = _dedupe_statements(statements)
        all_statements.extend(statements)
        statements_by_doc[document_id].extend(statements)
        statement_dicts = [_statement_to_dict(stmt) for stmt in statements]

        temporal_formula_strings = [formula for formula in (_tdfol_formula_from_statement(stmt) for stmt in statements) if formula]
        document_temporal_formula_strings = _build_document_temporal_formulas(
            document_id=document_id,
            title=title,
            date_filed=date_filed,
        )

        dcec_formulas: List[str] = list(structured_signals.get("dcec_formulas") or [])
        temporal_formula_strings.extend(list(structured_signals.get("temporal_formulas") or []))
        if dcec_ready:
            status["stage"] = "dcec_convert"
            _LAST_FORMAL_PROGRESS.update({"stage": "dcec_convert", "document_id": document_id})
            dcec_started = time.monotonic()
            _trace(f"document_id={document_id} stage=dcec_convert start")
            for sentence in _iter_candidate_sentences(
                payload_text,
                statements,
                preferred_sentences=list(structured_signals.get("normative_sentences") or []),
            ):
                result = dcec_wrapper.convert_to_dcec(sentence)
                if result.success and result.dcec_formula:
                    dcec_formulas.append(str(result.dcec_formula).strip())
            _trace(f"document_id={document_id} stage=dcec_convert done elapsed={time.monotonic() - dcec_started:.2f}s")

        status["stage"] = "frames"
        _LAST_FORMAL_PROGRESS.update({"stage": "frames", "document_id": document_id})
        frame_started = time.monotonic()
        _trace(f"document_id={document_id} stage=frames start")
        frames = [_frame_from_statement(stmt, docket_id=docket_id, case_name=case_name, court=court) for stmt in statements]
        frames.extend(list(structured_signals.get("frames") or []))
        document_frame = _document_frame(
            document_id=document_id,
            title=title,
            date_filed=date_filed,
            docket_id=docket_id,
            case_name=case_name,
            court=court,
            entity_count=len(entities),
            dcec_count=len(dcec_formulas),
        )
        frame_dicts = [frame for frame in frames if frame]
        for frame in frame_dicts:
            aggregate_frames[str(frame.get("frame_id") or frame.get("object_id") or f"{document_id}:frame")] = dict(frame)
        if document_frame:
            aggregate_document_frames[str(document_frame.get("frame_id") or document_frame.get("object_id") or f"{document_id}:document_frame")] = dict(document_frame)

        _trace(f"document_id={document_id} stage=frames done elapsed={time.monotonic() - frame_started:.2f}s")

        status["stage"] = "proofs"
        _LAST_FORMAL_PROGRESS.update({"stage": "proofs", "document_id": document_id})
        proof_started = time.monotonic()
        _trace(f"document_id={document_id} stage=proofs start")
        propositions = [_proposition_from_statement(stmt) for stmt in statements]
        propositions.extend(list(structured_signals.get("propositions") or []))
        propositions = [prop for prop in propositions if prop]
        for proposition in propositions:
            proof = _build_formal_proof(
                document_id=document_id,
                proposition=proposition,
                zkp_prover=zkp_prover,
            )
            proofs[proof["proof_id"]] = proof
            certificates.extend(list(proof.get("certificates") or []))
        _trace(f"document_id={document_id} stage=proofs done elapsed={time.monotonic() - proof_started:.2f}s")

        classification = _classify_from_formal_signals(statements=statements, entities=entities, title=title)
        summary = _build_document_summary(title=title, entities=entities, statements=statements, dcec_formulas=dcec_formulas)

        analyses[document_id] = {
            "classification": classification,
            "entities": _dedupe_dict_items(
                list(entities) + list(structured_signals.get("entities") or []),
                key_fields=("id", "label", "type"),
            ),
            "relationships": _dedupe_dict_items(
                list(relationships) + list(structured_signals.get("relationships") or []),
                key_fields=("id", "source", "target", "type"),
            ),
            "deontic_statements": statement_dicts,
            "events": _events_from_statements(statements),
            "frames": frame_dicts,
            "document_frames": [document_frame] if document_frame else [],
            "propositions": propositions,
            "temporal_formulas": temporal_formula_strings,
            "document_temporal_formulas": document_temporal_formula_strings,
            "dcec_formulas": _dedupe_strings(dcec_formulas),
            "summary": summary,
            "provenance": {
                "backend": "formal_logic_pipeline",
                "provider": "repo_native",
                "model_name": "knowledge_graphs+deontic+tdfol+dcec+flogic",
                "modules": [
                    "knowledge_graphs.extraction",
                    "logic.integration.reasoning.deontological_reasoning",
                    "logic.TDFOL",
                    "logic.CEC.eng_dcec_wrapper",
                    "logic.flogic",
                ],
                "dcec_available": dcec_ready,
            },
        }
        aggregate_entities.extend(analyses[document_id]["entities"])
        aggregate_relationships.extend(analyses[document_id]["relationships"])
        aggregate_temporal_formulas.extend(temporal_formula_strings)
        aggregate_document_temporal_formulas.extend(document_temporal_formula_strings)
        aggregate_dcec_formulas.extend(dcec_formulas)
        processed_count += 1
        status["processed"] = processed_count

    stop_event.set()
    if heartbeat_thread.is_alive():
        heartbeat_thread.join(timeout=1.0)

    status["stage"] = "conflict_detection"
    _LAST_FORMAL_PROGRESS.update({"stage": "conflict_detection", "document_id": ""})
    conflict_started = time.monotonic()
    _trace("stage=conflict_detection start")
    conflicts = conflict_detector.detect_conflicts(all_statements) if all_statements else []
    _trace(f"stage=conflict_detection done elapsed={time.monotonic() - conflict_started:.2f}s")
    conflict_payload = [_conflict_to_dict(conflict) for conflict in conflicts]
    conflict_count_by_type: Dict[str, int] = defaultdict(int)
    for conflict in conflicts:
        conflict_count_by_type[str(conflict.conflict_type.value)] += 1
    for document_id, statements in statements_by_doc.items():
        related = [
            _conflict_to_dict(conflict)
            for conflict in conflicts
            if conflict.statement1.source_document == document_id or conflict.statement2.source_document == document_id
        ]
        if related and document_id in analyses:
            analyses[document_id]["deontic_conflicts"] = related

    return {
        "document_analyses": analyses,
        "knowledge_graph": {
            "entities": _dedupe_dict_items(aggregate_entities, key_fields=("id", "label", "type")),
            "relationships": _dedupe_dict_items(aggregate_relationships, key_fields=("id", "source", "target", "type")),
        },
        "temporal_fol": {
            "backend": "tdfol_constructor",
            "formulas": _dedupe_strings(aggregate_temporal_formulas),
        },
        "deontic_cognitive_event_calculus": {
            "backend": "eng_dcec_wrapper",
            "formulas": _dedupe_strings(aggregate_dcec_formulas),
        },
        "frame_logic": aggregate_frames,
        "document_frame_logic": aggregate_document_frames,
        "proof_store": {
            "proofs": proofs,
            "certificates": _dedupe_dict_items(certificates, key_fields=("certificate_id", "backend", "theorem")),
            "summary": {
                "proof_count": len(proofs),
                "processed_document_count": processed_count,
                "skipped_document_count": skipped_count,
                "conflict_count": len(conflicts),
            },
            "metadata": {
                "backend": "formal_logic_proof_store",
                "zkp_status": "not_implemented",
            },
        },
        "deontic_conflicts": conflict_payload,
        "summary": {
            "processed_document_count": processed_count,
            "skipped_document_count": skipped_count,
            "deontic_statement_count": len(all_statements),
            "entity_count": len(_dedupe_dict_items(aggregate_entities, key_fields=("id", "label", "type"))),
            "relationship_count": len(_dedupe_dict_items(aggregate_relationships, key_fields=("id", "source", "target", "type"))),
            "temporal_formula_count": len(_dedupe_strings(aggregate_temporal_formulas)),
            "document_temporal_formula_count": len(_dedupe_strings(aggregate_document_temporal_formulas)),
            "dcec_formula_count": len(_dedupe_strings(aggregate_dcec_formulas)),
            "frame_count": len(aggregate_frames),
            "document_frame_count": len(aggregate_document_frames),
            "proof_count": len(proofs),
            "deontic_conflict_count": len(conflicts),
            "deontic_conflict_types": dict(conflict_count_by_type),
        },
    }


def _normalize_kg_entity(entity: Mapping[str, Any], *, document_id: str) -> Dict[str, Any]:
    entity_id = str(entity.get("id") or entity.get("entity_id") or "")
    if not entity_id:
        return {}
    return {
        "id": entity_id,
        "label": str(entity.get("name") or entity.get("label") or entity_id),
        "type": str(entity.get("type") or entity.get("entity_type") or "entity").lower(),
        "properties": {
            "document_id": document_id,
            **dict(entity.get("properties") or {}),
        },
    }


def _normalize_kg_relationship(relationship: Mapping[str, Any], *, document_id: str) -> Dict[str, Any]:
    rel_id = str(relationship.get("id") or relationship.get("relationship_id") or "")
    source = str(relationship.get("source") or relationship.get("source_id") or "")
    target = str(relationship.get("target") or relationship.get("target_id") or "")
    if not source or not target:
        return {}
    return {
        "id": rel_id or f"{document_id}:{source}:{target}:{relationship.get('relationship_type') or relationship.get('type') or 'related_to'}",
        "source": source,
        "target": target,
        "type": str(relationship.get("relationship_type") or relationship.get("type") or "related_to").upper(),
        "properties": {
            "document_id": document_id,
            **dict(relationship.get("properties") or {}),
        },
    }


def _statement_to_dict(statement: DeonticStatement) -> Dict[str, Any]:
    payload = asdict(statement)
    payload["modality"] = statement.modality.value
    payload["document_id"] = statement.document_id or statement.source_document
    return payload


def _conflict_to_dict(conflict: DeonticConflict) -> Dict[str, Any]:
    return {
        "id": conflict.id or f"{conflict.statement1.id}:{conflict.statement2.id}",
        "conflict_type": conflict.conflict_type.value if isinstance(conflict.conflict_type, ConflictType) else str(conflict.conflict_type),
        "severity": conflict.severity,
        "explanation": conflict.explanation,
        "resolution_suggestions": list(conflict.resolution_suggestions or []),
        "context_overlap": float(conflict.context_overlap),
        "statement1": _statement_to_dict(conflict.statement1),
        "statement2": _statement_to_dict(conflict.statement2),
    }


def _events_from_statements(statements: Sequence[DeonticStatement]) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    for statement in statements:
        event_id = f"{statement.id}:event"
        events.append(
            {
                "id": event_id,
                "label": statement.action,
                "time": str((statement.context or {}).get("time") or ""),
                "agent": statement.entity,
            }
        )
    return events


def _extract_deontic_statements_fallback(text: str, *, document_id: str) -> List[DeonticStatement]:
    patterns = [
        (DeonticModality.OBLIGATION, re.compile(r"\b([A-Z][A-Za-z0-9 ,.'-]{1,80}?)\s+(must|shall|required to)\s+([^.;\n]{3,180})", re.IGNORECASE)),
        (DeonticModality.PERMISSION, re.compile(r"\b([A-Z][A-Za-z0-9 ,.'-]{1,80}?)\s+(may|can|allowed to)\s+([^.;\n]{3,180})", re.IGNORECASE)),
        (DeonticModality.PROHIBITION, re.compile(r"\b([A-Z][A-Za-z0-9 ,.'-]{1,80}?)\s+(must not|may not|cannot|shall not|prohibited from)\s+([^.;\n]{3,180})", re.IGNORECASE)),
    ]
    statements: List[DeonticStatement] = []
    for modality, pattern in patterns:
        for idx, match in enumerate(pattern.finditer(text), start=1):
            entity = str(match.group(1) or "").strip(" ,.;:")
            action = str(match.group(3) or "").strip(" ,.;:")
            if not entity or not action:
                continue
            statements.append(
                DeonticStatement(
                    id=f"{document_id}:fallback:{modality.value}:{idx}",
                    entity=entity,
                    action=action,
                    modality=modality,
                    source_document=document_id,
                    source_text=str(match.group(0) or "").strip(),
                    confidence=0.55,
                    context={"extractor": "regex_fallback"},
                )
            )
    return statements


def _extract_structured_legal_signals(
    text: str,
    *,
    title: str,
    document_id: str,
    court: str,
) -> Dict[str, Any]:
    signals: Dict[str, Any] = {
        "statements": [],
        "temporal_formulas": [],
        "dcec_formulas": [],
        "frames": [],
        "entities": [],
        "relationships": [],
        "propositions": [],
        "normative_sentences": [],
    }

    clauses = _split_legal_clauses(text, title=title)
    for index, clause in enumerate(clauses, start=1):
        lowered = clause.lower()
        norm_candidates = _iter_norm_candidates_from_clause(clause, fallback_context=title or text)
        for candidate_offset, norm_candidate in enumerate(norm_candidates, start=1):
            actor_entity_id = f"{document_id}:actor:{_sanitize_symbol(norm_candidate['actor'])}"
            norm_id = _canonical_norm_id(
                actor=norm_candidate["actor"],
                action=norm_candidate["action"],
                modality=norm_candidate["modality"],
            )
            statement = DeonticStatement(
                id=f"{document_id}:structured:{index}:{candidate_offset}",
                entity=norm_candidate["actor"],
                action=norm_candidate["action"],
                modality=norm_candidate["modality"],
                source_document=document_id,
                source_text=clause,
                confidence=0.78,
                context={
                    "extractor": "structured_court_order",
                    "signal_type": norm_candidate["signal_type"],
                    "cnl_sentence": norm_candidate["cnl_sentence"],
                    "deadline": norm_candidate.get("deadline"),
                },
            )
            signals["statements"].append(statement)
            signals["normative_sentences"].append(norm_candidate["cnl_sentence"])
            compile_result = _compile_cnl_sentence(norm_candidate["cnl_sentence"], jurisdiction=court or "default")
            if compile_result:
                signals["temporal_formulas"].extend(list(compile_result.get("temporal_formulas") or []))
                signals["dcec_formulas"].extend(list(compile_result.get("dcec_formulas") or []))
                signals["frames"].extend(
                    _frames_from_compiled_norm(
                        document_id=document_id,
                        actor=norm_candidate["actor"],
                        action=norm_candidate["action"],
                        modality=norm_candidate["modality"].value,
                        cnl_sentence=norm_candidate["cnl_sentence"],
                        compile_result=compile_result,
                    )
                )
            signals["entities"].append(_actor_entity(document_id=document_id, actor=norm_candidate["actor"]))
            signals["entities"].append(
                _norm_entity(
                    norm_id=norm_id,
                    actor=norm_candidate["actor"],
                    action=norm_candidate["action"],
                    modality=norm_candidate["modality"],
                    document_id=document_id,
                    deadline=norm_candidate.get("deadline", ""),
                )
            )
            signals["relationships"].append(
                {
                    "id": f"{document_id}:rel:actor:{_sanitize_symbol(norm_candidate['actor'])}:{index}:{candidate_offset}",
                    "source": actor_entity_id,
                    "target": document_id,
                    "type": "SUBJECT_OF",
                    "properties": {"document_id": document_id, "signal_type": norm_candidate["signal_type"]},
                }
            )
            signals["relationships"].append(
                {
                    "id": f"{document_id}:rel:imposes_norm:{_sanitize_symbol(norm_candidate['actor'])}:{_sanitize_symbol(norm_candidate['action'])}:{candidate_offset}",
                    "source": document_id,
                    "target": norm_id,
                    "type": "IMPOSES_NORM",
                    "properties": {
                        "document_id": document_id,
                        "signal_type": norm_candidate["signal_type"],
                        "modality": norm_candidate["modality"].value,
                    },
                }
            )
            signals["relationships"].append(
                {
                    "id": f"{document_id}:rel:norm_subject:{_sanitize_symbol(norm_candidate['actor'])}:{_sanitize_symbol(norm_candidate['action'])}:{candidate_offset}",
                    "source": norm_id,
                    "target": actor_entity_id,
                    "type": "NORM_SUBJECT",
                    "properties": {
                        "document_id": document_id,
                        "modality": norm_candidate["modality"].value,
                    },
                }
            )
            if norm_candidate.get("deadline"):
                deadline_id = _canonical_deadline_id(
                    actor=norm_candidate["actor"],
                    action=norm_candidate["action"],
                    deadline=norm_candidate["deadline"],
                )
                signals["entities"].append(
                    _deadline_entity(
                        deadline_id=deadline_id,
                        actor=norm_candidate["actor"],
                        action=norm_candidate["action"],
                        deadline=norm_candidate["deadline"],
                        document_id=document_id,
                    )
                )
                signals["relationships"].append(
                    {
                        "id": f"{document_id}:rel:deadline_for:{_sanitize_symbol(norm_candidate['actor'])}:{_sanitize_symbol(norm_candidate['deadline'])}:{candidate_offset}",
                        "source": deadline_id,
                        "target": actor_entity_id,
                        "type": "DEADLINE_FOR",
                        "properties": {
                            "document_id": document_id,
                            "deadline": norm_candidate["deadline"],
                            "action": norm_candidate["action"],
                        },
                    }
                )
                signals["relationships"].append(
                    {
                        "id": f"{document_id}:rel:imposes_deadline:{_sanitize_symbol(norm_candidate['action'])}:{_sanitize_symbol(norm_candidate['deadline'])}:{candidate_offset}",
                        "source": document_id,
                        "target": deadline_id,
                        "type": "IMPOSES_DEADLINE",
                        "properties": {
                            "document_id": document_id,
                            "deadline": norm_candidate["deadline"],
                            "actor": norm_candidate["actor"],
                        },
                    }
                )
                signals["relationships"].append(
                    {
                        "id": f"{document_id}:rel:norm_deadline:{_sanitize_symbol(norm_candidate['action'])}:{_sanitize_symbol(norm_candidate['deadline'])}:{candidate_offset}",
                        "source": norm_id,
                        "target": deadline_id,
                        "type": "HAS_DEADLINE",
                        "properties": {
                            "document_id": document_id,
                            "deadline": norm_candidate["deadline"],
                        },
                    }
                )
                signals["propositions"].append(
                    {
                        "statement": f"{norm_candidate['actor']} has {norm_candidate['modality'].value} regarding {norm_candidate['action']}",
                        "assumptions": [clause, norm_candidate["cnl_sentence"]],
                    }
                )

        event_candidate = _extract_event_candidate_from_clause(clause, fallback_context=title or text)
        if event_candidate:
            event_id = _canonical_event_id(
                label=event_candidate["label"],
                event_type=event_candidate["event_type"],
                event_date=event_candidate.get("event_date", ""),
            )
            signals["frames"].append(
                _event_frame(
                    document_id=document_id,
                    event_id=event_id,
                    label=event_candidate["label"],
                    event_type=event_candidate["event_type"],
                    event_date=event_candidate.get("event_date", ""),
                    source_text=clause,
                )
            )
            if event_candidate.get("event_date"):
                signals["entities"].append(
                    {
                        "id": event_id,
                        "label": event_candidate["label"],
                        "type": "court_event",
                        "properties": {"document_id": document_id, "date": event_candidate["event_date"]},
                    }
                )
                signals["relationships"].append(
                    {
                        "id": f"{document_id}:rel:schedules:{_sanitize_symbol(event_candidate['event_type'])}:{_sanitize_symbol(event_candidate.get('event_date', 'unknown'))}",
                        "source": document_id,
                        "target": event_id,
                        "type": "SCHEDULES",
                        "properties": {"document_id": document_id, "event_date": event_candidate["event_date"]},
                    }
                )

        if any(token in lowered for token in ("granted", "denied", "vacated", "continued")):
            disposition = _extract_disposition_candidate(clause)
            if disposition:
                signals["frames"].append(
                    _disposition_frame(
                        document_id=document_id,
                        label=disposition["label"],
                        disposition=disposition["disposition"],
                        source_text=clause,
                    )
                )

    return {
        key: (_dedupe_strings(value) if key in {"temporal_formulas", "dcec_formulas", "normative_sentences"} else value)
        for key, value in signals.items()
    }


def _iter_norm_candidates_from_clause(clause: str, *, fallback_context: str) -> List[Dict[str, Any]]:
    output: List[Dict[str, Any]] = []
    direct_candidate = _extract_norm_candidate_from_clause(clause, fallback_context=fallback_context)
    if direct_candidate:
        output.append(direct_candidate)
    output.extend(_extract_deadline_candidates_from_clause(clause, fallback_context=fallback_context))
    deduped: List[Dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for candidate in output:
        key = (
            str(candidate.get("actor") or ""),
            str(candidate.get("action") or ""),
            str((candidate.get("modality") or DeonticModality.OBLIGATION).value if candidate.get("modality") else ""),
            str(candidate.get("deadline") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def _split_legal_clauses(text: str, *, title: str) -> List[str]:
    raw_segments = [title] if title.strip() else []
    raw_segments.extend(re.split(r"(?<=[\.;])\s+|\n+", text))
    output: List[str] = []
    for segment in raw_segments:
        cleaned = re.sub(r"\s+", " ", str(segment or "")).strip(" .;:")
        if cleaned and cleaned not in output:
            output.append(cleaned)
    return output


def _extract_norm_candidate_from_clause(clause: str, *, fallback_context: str) -> Dict[str, Any] | None:
    clause = _strip_introductory_legal_phrases(clause)
    actor_patterns = [
        (DeonticModality.PROHIBITION, r"(?P<actor>[^.;]{2,80}?)\s+(?:is|are\s+)?prohibited from\s+(?P<action>[^.;]{3,220})"),
        (DeonticModality.PROHIBITION, r"(?P<actor>[^.;]{2,80}?)\s+(?:must not|shall not|may not|cannot)\s+(?P<action>[^.;]{3,220})"),
        (DeonticModality.OBLIGATION, r"(?P<actor>[^.;]{2,80}?)\s+(?:is|are)\s+directed to\s+(?P<action>[^.;]{3,220})"),
        (DeonticModality.OBLIGATION, r"(?P<actor>[^.;]{2,80}?)\s+(?:is|are)\s+ordered to\s+(?P<action>[^.;]{3,220})"),
        (DeonticModality.OBLIGATION, r"(?P<actor>[^.;]{2,80}?)\s+(?:is|are)\s+required to\s+(?P<action>[^.;]{3,220})"),
        (DeonticModality.OBLIGATION, r"(?P<actor>[^.;]{2,80}?)\s+(?:must|shall|required to)\s+(?P<action>[^.;]{3,220})"),
        (DeonticModality.PERMISSION, r"(?P<actor>[^.;]{2,80}?)\s+(?:may|can|allowed to)\s+(?P<action>[^.;]{3,220})"),
    ]
    for modality, pattern in actor_patterns:
        match = re.search(pattern, clause, re.IGNORECASE)
        if not match:
            continue
        actor = _normalize_actor(match.group("actor"))
        action = _normalize_action(match.group("action"))
        if not actor or not action:
            continue
        action, deadline = _split_action_deadline(action)
        cnl_sentence = _candidate_to_cnl(actor=actor, action=action, modality=modality)
        if deadline:
            cnl_sentence = f"{cnl_sentence} by {deadline}"
        return {
            "actor": actor,
            "action": action,
            "modality": modality,
            "signal_type": "directive_clause",
            "deadline": deadline,
            "cnl_sentence": cnl_sentence,
        }

    deadline_extension = re.search(
        r"(?P<actor>[A-Z][A-Za-z' -]{2,50})'?s deadline to (?P<action>[^.;]{3,160}?) is extended to (?P<date>[A-Za-z0-9/,: -]{3,40})",
        clause,
        re.IGNORECASE,
    )
    if deadline_extension:
        actor = _normalize_actor(deadline_extension.group("actor"))
        action = _normalize_action(deadline_extension.group("action"))
        deadline = _normalize_deadline(deadline_extension.group("date"))
        if actor and action and deadline:
            cnl = f"{actor} shall {action} by {deadline}"
            return {
                "actor": actor,
                "action": action,
                "modality": DeonticModality.OBLIGATION,
                "signal_type": "extended_deadline",
                "deadline": deadline,
                "cnl_sentence": cnl,
            }

    return None


def _extract_deadline_candidates_from_clause(clause: str, *, fallback_context: str) -> List[Dict[str, Any]]:
    clause = _strip_introductory_legal_phrases(clause)
    candidates: List[Dict[str, Any]] = []
    due_pattern = re.compile(
        r"(?P<action>initial disclosures|responses?|answer|amended pleadings(?: and joinder of parties)?|case dispositive motions?)\s+due\s+(?:by\s+)?(?P<date>\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2}|[A-Za-z]+\s+\d{1,2},\s+\d{2,4})",
        re.IGNORECASE,
    )
    for match in due_pattern.finditer(clause):
        action_label = _normalize_action(match.group("action"))
        deadline = _normalize_deadline(match.group("date"))
        actor = "Defendant" if action_label.lower() == "answer" else _infer_party_actor(fallback_context)
        mapped_action = _map_due_action(action_label)
        if actor and mapped_action and deadline:
            candidates.append(
                {
                    "actor": actor,
                    "action": mapped_action,
                    "modality": DeonticModality.OBLIGATION,
                    "signal_type": "deadline_clause",
                    "deadline": deadline,
                    "cnl_sentence": f"{actor} shall {mapped_action} by {deadline}",
                }
            )

    discovery_close_pattern = re.compile(
        r"(?P<action>discovery closes)\s+(?P<date>\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2}|[A-Za-z]+\s+\d{1,2},\s+\d{2,4})",
        re.IGNORECASE,
    )
    for match in discovery_close_pattern.finditer(clause):
        deadline = _normalize_deadline(match.group("date"))
        if deadline:
            candidates.append(
                {
                    "actor": "Parties",
                    "action": "complete discovery",
                    "modality": DeonticModality.OBLIGATION,
                    "signal_type": "deadline_clause",
                    "deadline": deadline,
                    "cnl_sentence": f"Parties shall complete discovery by {deadline}",
                }
            )
    return candidates


def _extract_event_candidate_from_clause(clause: str, *, fallback_context: str) -> Dict[str, str] | None:
    clause = _strip_introductory_legal_phrases(clause)
    match = re.search(
        r"(?P<label>(?:Rule\s+\d+\s+)?(?:Scheduling\s+Conference|Final Pretrial Conference|Jury Trial|telephone status conference|hearing|conference|trial))\s+set\s+for\s+(?P<date>[A-Za-z0-9/,: -]{3,60})",
        clause,
        re.IGNORECASE,
    )
    if not match:
        return None
    label = _normalize_event_label(match.group("label"))
    event_date = _extract_primary_date_token(match.group("date"))
    return {
        "label": label,
        "event_type": _normalize_event_type(label),
        "event_date": _normalize_deadline(event_date),
        "context": fallback_context,
    }


def _extract_disposition_candidate(clause: str) -> Dict[str, str] | None:
    clause = _strip_introductory_legal_phrases(clause)
    match = re.search(r"(?P<label>[^.;]{3,180}?)\s+is\s+(?P<disp>granted|denied|vacated|continued)\b", clause, re.IGNORECASE)
    if not match:
        return None
    return {
        "label": _normalize_action(match.group("label")),
        "disposition": match.group("disp").lower(),
    }


def _compile_cnl_sentence(sentence: str, *, jurisdiction: str) -> Dict[str, Any] | None:
    try:
        ir, diagnostics = parse_cnl_to_ir_with_diagnostics(sentence, jurisdiction=jurisdiction or "default")
        ir = normalize_v2_ir(ir)
        return {
            "diagnostics": diagnostics,
            "dcec_formulas": compile_ir_to_dcec(ir),
            "temporal_formulas": compile_ir_to_temporal_deontic_fol(ir),
        }
    except Exception:
        return None


def _frames_from_compiled_norm(
    *,
    document_id: str,
    actor: str,
    action: str,
    modality: str,
    cnl_sentence: str,
    compile_result: Mapping[str, Any],
) -> List[Dict[str, Any]]:
    diagnostics = dict(compile_result.get("diagnostics") or {})
    frame = FLogicFrame(
        object_id=f"structured_{_sanitize_symbol(document_id)}_{_sanitize_symbol(actor)}_{_sanitize_symbol(action)[:24]}",
        scalar_methods={
            "actor": f'"{actor}"',
            "action": f'"{action}"',
            "modality": f'"{modality}"',
            "cnl_sentence": f'"{cnl_sentence}"',
            "parse_confidence": str(diagnostics.get("parse_confidence") or ""),
            "temporal_detected": str(bool(diagnostics.get("temporal_detected"))).lower(),
        },
        isa="StructuredDeonticNorm",
        isaset=["DeonticStatement", "CourtDirective"],
    )
    return [
        {
            "frame_id": frame.object_id,
            "label": f"{modality.title()} norm",
            "object_id": frame.object_id,
            "isa": frame.isa,
            "isaset": list(frame.isaset),
            "slots": {key: str(value).strip('"') for key, value in frame.scalar_methods.items()},
            "ergo": frame.to_ergo_string(),
        }
    ]


def _event_frame(*, document_id: str, event_id: str, label: str, event_type: str, event_date: str, source_text: str) -> Dict[str, Any]:
    frame = FLogicFrame(
        object_id=f"event_{_sanitize_symbol(event_id)}",
        scalar_methods={
            "document_id": f'"{document_id}"',
            "event_id": f'"{event_id}"',
            "label": f'"{label}"',
            "event_type": f'"{event_type}"',
            "event_date": f'"{event_date}"',
            "source_text": f'"{source_text}"',
        },
        isa="ScheduledCourtEvent",
        isaset=["CourtEvent"],
    )
    return {
        "frame_id": frame.object_id,
        "label": label,
        "object_id": frame.object_id,
        "isa": frame.isa,
        "isaset": list(frame.isaset),
        "slots": {key: str(value).strip('"') for key, value in frame.scalar_methods.items()},
        "ergo": frame.to_ergo_string(),
    }


def _disposition_frame(*, document_id: str, label: str, disposition: str, source_text: str) -> Dict[str, Any]:
    frame = FLogicFrame(
        object_id=f"disp_{_sanitize_symbol(document_id)}_{_sanitize_symbol(label)[:24]}",
        scalar_methods={
            "document_id": f'"{document_id}"',
            "label": f'"{label}"',
            "disposition": f'"{disposition}"',
            "source_text": f'"{source_text}"',
        },
        isa="CourtDisposition",
        isaset=["CourtEvent"],
    )
    return {
        "frame_id": frame.object_id,
        "label": f"{label} {disposition}",
        "object_id": frame.object_id,
        "isa": frame.isa,
        "isaset": list(frame.isaset),
        "slots": {key: str(value).strip('"') for key, value in frame.scalar_methods.items()},
        "ergo": frame.to_ergo_string(),
    }


def _actor_entity(*, document_id: str, actor: str) -> Dict[str, Any]:
    return {
        "id": f"{document_id}:actor:{_sanitize_symbol(actor)}",
        "label": actor,
        "type": "legal_actor",
        "properties": {"document_id": document_id},
    }


def _deadline_entity(*, deadline_id: str, actor: str, action: str, deadline: str, document_id: str) -> Dict[str, Any]:
    return {
        "id": deadline_id,
        "label": f"{actor} deadline for {action}",
        "type": "deadline",
        "properties": {
            "document_id": document_id,
            "actor": actor,
            "action": action,
            "deadline": deadline,
        },
    }


def _norm_entity(
    *,
    norm_id: str,
    actor: str,
    action: str,
    modality: DeonticModality,
    document_id: str,
    deadline: str,
) -> Dict[str, Any]:
    properties: Dict[str, Any] = {
        "document_id": document_id,
        "actor": actor,
        "action": action,
        "modality": modality.value,
    }
    if deadline:
        properties["deadline"] = deadline
    return {
        "id": norm_id,
        "label": f"{actor} {modality.value} {action}",
        "type": "structured_deontic_norm",
        "properties": properties,
    }


def _candidate_to_cnl(*, actor: str, action: str, modality: DeonticModality) -> str:
    modal = {
        DeonticModality.OBLIGATION: "shall",
        DeonticModality.PERMISSION: "may",
        DeonticModality.PROHIBITION: "shall not",
    }.get(modality, "shall")
    return f"{actor} {modal} {action}"


def _normalize_actor(value: str) -> str:
    actor = re.sub(r"^(?:the\s+court\s+directs\s+|the\s+court\s+orders\s+|the\s+court\s+hereby\s+)", "", str(value or "").strip(), flags=re.IGNORECASE)
    actor = re.sub(r"^(?:in light of\s+[^,]+,\s*)", "", actor, flags=re.IGNORECASE)
    actor = re.sub(
        r"^(?:within\s+\d+\s+(?:days|day|hours|hour|weeks|week|months|month|years|year)\s*,?\s*)",
        "",
        actor,
        flags=re.IGNORECASE,
    )
    actor = re.sub(
        r"^(?:by\s+\d{1,2}/\d{1,2}/\d{2,4}\s*,?\s*)",
        "",
        actor,
        flags=re.IGNORECASE,
    )
    actor = re.sub(r"^[a-z]{1,3},\s*", "", actor, flags=re.IGNORECASE)
    actor = re.sub(r"^\d+\s*,\s*", "", actor)
    actor = re.sub(r"^(?:the\s+)?", "", actor, flags=re.IGNORECASE)
    actor = actor.rstrip("'")
    actor = re.sub(r"\s+", " ", actor).strip(" ,.;:")
    actor_map = {
        "parties": "Parties",
        "plaintiff": "Plaintiff",
        "defendant": "Defendant",
        "clerk": "Clerk",
        "court": "Court",
    }
    return actor_map.get(actor.lower(), actor[:1].upper() + actor[1:] if actor else "")


def _normalize_action(value: str) -> str:
    action = re.sub(r"\s+", " ", str(value or "")).strip(" ,.;:")
    action = re.sub(r",\s+after which.*$", "", action, flags=re.IGNORECASE)
    action = re.sub(r",\s+then.*$", "", action, flags=re.IGNORECASE)
    action = re.sub(r"\s+\(.*?\)$", "", action).strip()
    action = re.sub(
        r"\bby\s+(\d{1,2}/\d{1,2}/\d{2,4})\b",
        lambda match: f"by {_normalize_deadline(match.group(1))}",
        action,
        flags=re.IGNORECASE,
    )
    return action


def _split_action_deadline(action: str) -> tuple[str, str]:
    text = str(action or "").strip()
    match = re.search(
        r"^(?P<action>.+?)\s+by\s+(?P<date>\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|[A-Za-z]+\s+\d{1,2},\s+\d{2,4})$",
        text,
        re.IGNORECASE,
    )
    if not match:
        return text, ""
    return _normalize_action(match.group("action")), _normalize_deadline(match.group("date"))


def _normalize_deadline(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ,.;:")
    match = re.match(r"^(?P<m>\d{1,2})/(?P<d>\d{1,2})/(?P<y>\d{2,4})$", text)
    if match:
        month = int(match.group("m"))
        day = int(match.group("d"))
        year = int(match.group("y"))
        if year < 100:
            year += 2000
        return f"{year:04d}-{month:02d}-{day:02d}"
    return text


def _extract_primary_date_token(value: str) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip(" ,.;:")
    iso_match = re.search(r"\b\d{4}-\d{2}-\d{2}\b", text)
    if iso_match:
        return iso_match.group(0)
    slash_match = re.search(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", text)
    if slash_match:
        return slash_match.group(0)
    month_match = re.search(
        r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},\s+\d{2,4}\b",
        text,
        flags=re.IGNORECASE,
    )
    if month_match:
        return month_match.group(0)
    return text


def _infer_party_actor(context: str) -> str:
    lowered = str(context or "").lower()
    if "defendant" in lowered:
        return "Defendant"
    if "plaintiff" in lowered:
        return "Plaintiff"
    return "Parties"


def _map_due_action(action_label: str) -> str:
    lowered = action_label.lower()
    if lowered.startswith("initial disclosures"):
        return "exchange initial disclosures"
    if lowered.startswith("responses"):
        return "file responses"
    if lowered == "response":
        return "file a response"
    if lowered == "answer":
        return "file an answer"
    if lowered.startswith("amended pleadings"):
        return "file amended pleadings and join parties"
    if lowered.startswith("case dispositive motions"):
        return "file dispositive motions"
    return lowered


def _strip_introductory_legal_phrases(clause: str) -> str:
    cleaned = re.sub(r"^\s*text order entered by [^.]+\.\s*", "", str(clause or ""), flags=re.IGNORECASE)
    cleaned = re.sub(r"^\s*in light of .*?,\s*(?=(plaintiff|defendant|the parties|clerk|court)\b)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^\s*the court hereby\s+", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _normalize_event_label(value: str) -> str:
    label = re.sub(r"\s+", " ", str(value or "")).strip(" ,.;:")
    words = [word for word in label.split(" ") if word]
    normalized_words: List[str] = []
    for word in words:
        if re.fullmatch(r"rule", word, flags=re.IGNORECASE):
            normalized_words.append("Rule")
        elif re.fullmatch(r"\d+", word):
            normalized_words.append(word)
        elif word.lower() in {"of", "the", "for", "and", "to"}:
            normalized_words.append(word.lower())
        else:
            normalized_words.append(word[:1].upper() + word[1:].lower())
    return " ".join(normalized_words)


def _normalize_event_type(label: str) -> str:
    simplified = str(label or "").lower()
    simplified = re.sub(r"^rule\s+\d+\s+", "", simplified)
    simplified = re.sub(r"\s+", " ", simplified).strip()
    return _sanitize_symbol(simplified)


def _canonical_event_id(*, label: str, event_type: str, event_date: str) -> str:
    date_key = _sanitize_symbol(event_date or "undated")
    type_key = _sanitize_symbol(event_type or label or "event")
    return f"event:{type_key}:{date_key}"


def _canonical_deadline_id(*, actor: str, action: str, deadline: str) -> str:
    return f"deadline:{_sanitize_symbol(actor)}:{_sanitize_symbol(action)[:32]}:{_sanitize_symbol(deadline)}"


def _canonical_norm_id(*, actor: str, action: str, modality: DeonticModality) -> str:
    return f"norm:{_sanitize_symbol(actor)}:{modality.value}:{_sanitize_symbol(action)[:40]}"


def _dedupe_statements(statements: Sequence[DeonticStatement]) -> List[DeonticStatement]:
    seen: set[tuple[str, str, str]] = set()
    output: List[DeonticStatement] = []
    for statement in statements:
        key = (statement.entity, statement.action, statement.modality.value)
        if key in seen:
            continue
        seen.add(key)
        output.append(statement)
    return output


def _sanitize_symbol(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_]+", "_", str(text or "").strip().lower()).strip("_")
    return cleaned or "item"


def _tdfol_formula_from_statement(statement: DeonticStatement) -> str:
    agent = Constant(_sanitize_symbol(statement.entity))
    predicate = Predicate(_sanitize_symbol(statement.action), (agent,))
    if statement.modality.value == "obligation":
        formula = create_obligation(predicate, agent=agent)
    elif statement.modality.value == "permission":
        formula = create_permission(predicate, agent=agent)
    elif statement.modality.value == "prohibition":
        formula = create_prohibition(predicate, agent=agent)
    elif statement.modality.value == "conditional":
        trigger = Predicate(_sanitize_symbol(statement.conditions[0] if statement.conditions else "trigger"), (agent,))
        formula = create_implication(trigger, create_obligation(predicate, agent=agent))
    else:
        formula = create_always(predicate)
    return formula.to_string(pretty=True)


def _build_document_temporal_formulas(*, document_id: str, title: str, date_filed: str) -> List[str]:
    doc_const = Constant(_sanitize_symbol(document_id))
    formulas = [create_always(Predicate("document_exists", (doc_const,))).to_string(pretty=True)]
    if title:
        title_const = Constant(_sanitize_symbol(title)[:48])
        formulas.append(Predicate("document_titled", (doc_const, title_const)).to_string(pretty=True))
    if date_filed:
        date_const = Constant(_sanitize_symbol(date_filed))
        formulas.append(Predicate("filed_on", (doc_const, date_const)).to_string(pretty=True))
        formulas.append(create_always(Predicate("docket_event_recorded", (doc_const,))).to_string(pretty=True))
    return formulas


def _frame_from_statement(
    statement: DeonticStatement,
    *,
    docket_id: str,
    case_name: str,
    court: str,
) -> Dict[str, Any]:
    frame = FLogicFrame(
        object_id=f"stmt_{_sanitize_symbol(statement.id)}",
        scalar_methods={
            "entity": f'"{statement.entity}"',
            "action": f'"{statement.action}"',
            "modality": f'"{statement.modality.value}"',
            "document_id": f'"{statement.source_document}"',
            "docket_id": f'"{docket_id}"',
            "case_name": f'"{case_name}"',
            "court": f'"{court}"',
        },
        isa="DeonticStatement",
        isaset=["DocketStatement", "LegalNorm"],
    )
    return {
        "frame_id": frame.object_id,
        "label": f"{statement.modality.value.title()} statement",
        "object_id": frame.object_id,
        "isa": frame.isa,
        "isaset": list(frame.isaset),
        "slots": {
            key: str(value).strip('"')
            for key, value in frame.scalar_methods.items()
        },
        "ergo": frame.to_ergo_string(),
    }


def _document_frame(
    *,
    document_id: str,
    title: str,
    date_filed: str,
    docket_id: str,
    case_name: str,
    court: str,
    entity_count: int,
    dcec_count: int,
) -> Dict[str, Any]:
    frame = FLogicFrame(
        object_id=f"doc_{_sanitize_symbol(document_id)}",
        scalar_methods={
            "document_id": f'"{document_id}"',
            "title": f'"{title}"',
            "date_filed": f'"{date_filed}"',
            "docket_id": f'"{docket_id}"',
            "case_name": f'"{case_name}"',
            "court": f'"{court}"',
            "entity_count": str(entity_count),
            "dcec_count": str(dcec_count),
        },
        isa="DocketDocument",
        isaset=["LegalDocument"],
    )
    return {
        "frame_id": frame.object_id,
        "label": title or document_id,
        "object_id": frame.object_id,
        "isa": frame.isa,
        "isaset": list(frame.isaset),
        "slots": {key: str(value).strip('"') for key, value in frame.scalar_methods.items()},
        "ergo": frame.to_ergo_string(),
    }


def _proposition_from_statement(statement: DeonticStatement) -> Dict[str, Any]:
    proposition = f"{statement.entity} has {statement.modality.value} regarding {statement.action}"
    assumptions = [statement.source_text] if statement.source_text else []
    if statement.conditions:
        assumptions.extend(statement.conditions)
    return {"statement": proposition, "assumptions": assumptions}


def _build_formal_proof(*, document_id: str, proposition: Mapping[str, Any], zkp_prover: ZKPProver) -> Dict[str, Any]:
    statement = str(proposition.get("statement") or "").strip()
    assumptions = [str(item) for item in list(proposition.get("assumptions") or []) if str(item).strip()]
    proof_id = f"formal_proof_{_sanitize_symbol(document_id)}_{_sanitize_symbol(statement)[:32]}"
    zkp_proof = None
    try:
        axioms = [_sanitize_symbol(item) for item in assumptions if _sanitize_symbol(item)]
        theorem = _sanitize_symbol(statement)
        if theorem:
            zkp_proof = zkp_prover.generate_proof(theorem=theorem, private_axioms=axioms or ["document_exists"])
    except Exception:
        zkp_proof = None
    certificates = [
        {
            "certificate_id": f"{proof_id}:certificate:formal",
            "backend": "formal_logic_pipeline",
            "format": "deterministic_statement_certificate",
            "theorem": statement,
            "assumptions": assumptions,
            "payload": {
                "document_id": document_id,
                "statement": statement,
                "assumptions": assumptions,
            },
        }
    ]
    if zkp_proof is not None:
        certificates.append(
            {
                "certificate_id": f"{proof_id}:certificate:zkp_simulated",
                "backend": "logic.zkp.simulated",
                "format": "simulated_zkp",
                "theorem": statement,
                "assumptions": assumptions,
                "payload": zkp_proof.to_dict(),
                "warning": "simulated_only_not_cryptographically_secure",
            }
        )
    return {
        "proof_id": proof_id,
        "query": {"document_id": document_id, "statement": statement},
        "root_conclusion": statement,
        "status": "proved",
        "proof_hash": f"formal_hash_{_sanitize_symbol(statement)[:48]}",
        "steps": [
            {
                "step_id": f"{proof_id}:step:1",
                "rule_id": "formal_logic_extraction",
                "premises": assumptions,
                "conclusion": statement,
                "timestamp": None,
                "confidence": 0.8,
            }
        ],
        "certificates": certificates,
    }


def _iter_candidate_sentences(
    text: str,
    statements: Sequence[DeonticStatement],
    *,
    preferred_sentences: Sequence[str] | None = None,
) -> Iterable[str]:
    yielded: set[str] = set()
    for sentence in list(preferred_sentences or []):
        normalized = str(sentence or "").strip()
        if normalized and normalized not in yielded:
            yielded.add(normalized)
            yield normalized
    for statement in statements:
        sentence = str(statement.source_text or "").strip()
        if sentence and sentence not in yielded:
            yielded.add(sentence)
            yield sentence
    if yielded:
        return
    for chunk in re.split(r"(?<=[.!?])\s+", text):
        sentence = str(chunk or "").strip()
        if sentence and sentence not in yielded and len(sentence) >= 12:
            yielded.add(sentence)
            yield sentence


def _classify_from_formal_signals(
    *,
    statements: Sequence[DeonticStatement],
    entities: Sequence[Mapping[str, Any]],
    title: str,
) -> Dict[str, Any]:
    label = "formal_legal_document"
    if statements:
        label = "normative_legal_text"
    elif "motion" in title.lower():
        label = "motion"
    elif "order" in title.lower():
        label = "order"
    return {
        "label": label,
        "backend": "formal_logic_pipeline",
        "confidence": 0.7 if statements or entities else 0.4,
    }


def _build_document_summary(
    *,
    title: str,
    entities: Sequence[Mapping[str, Any]],
    statements: Sequence[DeonticStatement],
    dcec_formulas: Sequence[str],
) -> str:
    parts = [title or "Docket document"]
    if entities:
        parts.append(f"{len(entities)} entities")
    if statements:
        parts.append(f"{len(statements)} deontic statements")
    if dcec_formulas:
        parts.append(f"{len(dcec_formulas)} DCEC formulas")
    return "; ".join(parts)


def _dedupe_strings(values: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    output: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        output.append(text)
    return output


def _dedupe_dict_items(items: Iterable[Mapping[str, Any]], *, key_fields: Sequence[str]) -> List[Dict[str, Any]]:
    seen: set[tuple[str, ...]] = set()
    output: List[Dict[str, Any]] = []
    for item in items:
        payload = dict(item or {})
        key = tuple(str(payload.get(field) or "") for field in key_fields)
        if not any(key) or key in seen:
            continue
        seen.add(key)
        output.append(payload)
    return output
