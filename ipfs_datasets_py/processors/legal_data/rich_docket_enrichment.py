"""Router-backed enrichment for CourtListener docket datasets."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import time
import threading
import concurrent.futures
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from ... import llm_router, multimodal_router
from .reasoner.models import IRReference, ProofCertificate, ProofObject, ProofStep, SourceProvenance
from .reasoner.prover_backends import FirstOrderProverAdapter, SMTStyleProverAdapter


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)
_PROMPT_ECHO_MARKERS = (
    "Return a JSON object only.",
    "Analyze this legal docket document and extract rich structured legal semantics.",
    "Required keys: classification, entities, relationships",
    "Document text follows:",
)


@dataclass
class RichDocumentAnalysis:
    classification: Dict[str, Any]
    entities: List[Dict[str, Any]]
    relationships: List[Dict[str, Any]]
    deontic_statements: List[Dict[str, Any]]
    events: List[Dict[str, Any]]
    frames: List[Dict[str, Any]]
    propositions: List[Dict[str, Any]]
    temporal_formulas: List[str]
    dcec_formulas: List[str]
    summary: str
    provenance: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "classification": dict(self.classification),
            "entities": [dict(item) for item in self.entities],
            "relationships": [dict(item) for item in self.relationships],
            "deontic_statements": [dict(item) for item in self.deontic_statements],
            "events": [dict(item) for item in self.events],
            "frames": [dict(item) for item in self.frames],
            "propositions": [dict(item) for item in self.propositions],
            "temporal_formulas": list(self.temporal_formulas),
            "dcec_formulas": list(self.dcec_formulas),
            "summary": self.summary,
            "provenance": dict(self.provenance),
        }


def enrich_docket_documents_with_routers(
    documents: Sequence[Any],
    *,
    docket_id: str,
    case_name: str,
    court: str,
    max_documents: int | None = None,
    max_chars: int = 900,
) -> Dict[str, Any]:
    """Analyze docket documents with llm/multimodal routers when available."""

    heartbeat_raw = str(os.getenv("IPFS_DATASETS_PY_LOGIC_HEARTBEAT_SECONDS", "30")).strip()
    try:
        heartbeat_seconds = max(0.0, float(heartbeat_raw))
    except Exception:
        heartbeat_seconds = 30.0
    timeout_raw = str(os.getenv("IPFS_DATASETS_PY_ROUTER_TIMEOUT_SECONDS", "60")).strip()
    try:
        router_timeout_seconds = max(0.0, float(timeout_raw))
    except Exception:
        router_timeout_seconds = 60.0
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
                "[router_enrichment] "
                f"stage={status['stage']} "
                f"document_id={status['document_id']} "
                f"processed={status['processed']} "
                f"skipped={status['skipped']} "
                f"total={status['total']}",
                flush=True,
            )

    heartbeat_thread = threading.Thread(target=_heartbeat, name="router-enrichment-heartbeat", daemon=True)
    heartbeat_thread.start()

    analyses: Dict[str, RichDocumentAnalysis] = {}
    aggregate_entities: List[Dict[str, Any]] = []
    aggregate_relationships: List[Dict[str, Any]] = []
    aggregate_temporal_formulas: List[str] = []
    aggregate_dcec_formulas: List[str] = []
    aggregate_frames: Dict[str, Any] = {}
    proof_objects: Dict[str, Dict[str, Any]] = {}
    processed_count = 0
    skipped_count = 0
    mock_count = 0

    selected_documents = list(documents)
    if max_documents is not None:
        selected_documents = selected_documents[: max(0, int(max_documents))]
    status["total"] = len(selected_documents)
    for document in selected_documents:
        document_id = str(getattr(document, "document_id", "") or getattr(document, "id", "") or "")
        title = str(getattr(document, "title", "") or "")
        text = str(getattr(document, "text", "") or "").strip()
        source_url = str(getattr(document, "source_url", "") or "")
        status["stage"] = "document_start"
        status["document_id"] = document_id
        status["processed"] = processed_count
        status["skipped"] = skipped_count
        if not document_id:
            skipped_count += 1
            status["skipped"] = skipped_count
            continue

        status["stage"] = "router_analyze"
        if router_timeout_seconds:
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = executor.submit(
                analyze_document_with_routers,
                docket_id=docket_id,
                case_name=case_name,
                court=court,
                document_id=document_id,
                title=title,
                text=text[:max_chars],
                source_url=source_url,
            )
            try:
                analysis = future.result(timeout=router_timeout_seconds)
            except concurrent.futures.TimeoutError:
                status["stage"] = "router_timeout"
                print(
                    f"[router_enrichment] timeout document_id={document_id} after {router_timeout_seconds}s",
                    flush=True,
                )
                skipped_count += 1
                status["skipped"] = skipped_count
                future.cancel()
                executor.shutdown(wait=False, cancel_futures=True)
                continue
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        else:
            analysis = analyze_document_with_routers(
                docket_id=docket_id,
                case_name=case_name,
                court=court,
                document_id=document_id,
                title=title,
                text=text[:max_chars],
                source_url=source_url,
            )
        if analysis is None:
            skipped_count += 1
            continue
        if str((analysis.provenance or {}).get("provider") or "").strip().lower() == "mock":
            mock_count += 1
            skipped_count += 1
            continue

        analyses[document_id] = analysis
        processed_count += 1
        status["processed"] = processed_count
        aggregate_entities.extend(analysis.entities)
        aggregate_relationships.extend(analysis.relationships)
        aggregate_temporal_formulas.extend(analysis.temporal_formulas)
        aggregate_dcec_formulas.extend(analysis.dcec_formulas)
        for frame in analysis.frames:
            frame_id = str(frame.get("frame_id") or frame.get("id") or f"{document_id}:frame")
            aggregate_frames[frame_id] = dict(frame)
        for proposition in analysis.propositions:
            proof = _build_proof_object(document_id=document_id, proposition=proposition)
            proof_objects[proof.proof_id] = _proof_to_dict(proof)

    result = {
        "document_analyses": {key: value.to_dict() for key, value in analyses.items()},
        "knowledge_graph": {
            "entities": _dedupe_dict_items(aggregate_entities, key_fields=("id", "label", "type")),
            "relationships": _dedupe_dict_items(aggregate_relationships, key_fields=("id", "source", "target", "type")),
        },
        "temporal_fol": {
            "backend": "llm_router_temporal_deontic_first_order_logic",
            "formulas": _dedupe_strings(aggregate_temporal_formulas),
        },
        "deontic_cognitive_event_calculus": {
            "backend": "llm_router_deontic_cognitive_event_calculus",
            "formulas": _dedupe_strings(aggregate_dcec_formulas),
        },
        "frame_logic": aggregate_frames,
        "proof_store": {
            "proofs": proof_objects,
            "certificates": [
                certificate
                for proof in proof_objects.values()
                for certificate in list((proof.get("certificates") or []))
            ],
            "summary": {
                "proof_count": len(proof_objects),
                "processed_document_count": processed_count,
                "skipped_document_count": skipped_count,
                "mock_provider_count": mock_count,
            },
            "metadata": {
                "backend": "router_enriched_proof_store",
                "zkp_status": "not_implemented",
            },
        },
        "summary": {
            "processed_document_count": processed_count,
            "skipped_document_count": skipped_count,
            "mock_provider_count": mock_count,
            "entity_count": len(_dedupe_dict_items(aggregate_entities, key_fields=("id", "label", "type"))),
            "relationship_count": len(_dedupe_dict_items(aggregate_relationships, key_fields=("id", "source", "target", "type"))),
            "temporal_formula_count": len(_dedupe_strings(aggregate_temporal_formulas)),
            "dcec_formula_count": len(_dedupe_strings(aggregate_dcec_formulas)),
            "frame_count": len(aggregate_frames),
            "proof_count": len(proof_objects),
        },
    }
    stop_event.set()
    if heartbeat_thread.is_alive():
        heartbeat_thread.join(timeout=1.0)
    return result


def analyze_document_with_routers(
    *,
    docket_id: str,
    case_name: str,
    court: str,
    document_id: str,
    title: str,
    text: str,
    source_url: str,
    provider: str | None = None,
    model_name: str | None = None,
    return_diagnostics: bool = False,
) -> RichDocumentAnalysis | None | tuple[RichDocumentAnalysis | None, Dict[str, Any]]:
    trace_enabled = str(os.getenv("IPFS_DATASETS_PY_ROUTER_TRACE", "")).strip().lower() in {"1", "true", "yes", "on"}
    trace_prefix = f"[router_trace] document_id={document_id}"
    stage_started = time.monotonic()
    _LAST_ROUTER_PROGRESS.update({"stage": "llm_generate", "document_id": document_id, "detail": "llm_generate start"})
    prompt = _build_analysis_prompt(
        docket_id=docket_id,
        case_name=case_name,
        court=court,
        document_id=document_id,
        title=title,
        text=text,
    )
    diagnostics: Dict[str, Any] = {
        "document_id": document_id,
        "provider_requested": provider,
        "model_name_requested": model_name,
        "status": "unknown",
    }
    try:
        if trace_enabled:
            print(f"{trace_prefix} stage=llm_generate start", flush=True)
        llm_started = time.monotonic()
        response = llm_router.generate_text(
            prompt,
            provider=provider,
            model_name=model_name,
            temperature=0.0,
            max_new_tokens=160,
            allow_local_fallback=False,
            disable_model_retry=True,
        )
        if trace_enabled:
            print(f"{trace_prefix} stage=llm_generate done elapsed={time.monotonic() - llm_started:.2f}s", flush=True)
        _LAST_ROUTER_PROGRESS.update({"stage": "parse_json", "document_id": document_id, "detail": "parse_json start"})
        trace = llm_router.get_last_generation_trace()
        provider = str(trace.get("provider_name") or "").strip().lower()
        model_name = str(trace.get("model_name") or "").strip()
        response_text = str(response or "").strip()
        diagnostics["provider_name"] = provider
        diagnostics["model_name"] = model_name
        diagnostics["raw_response_preview"] = response_text[:240]
        if provider == "mock":
            diagnostics["status"] = "mock_provider"
            result = None
            return (result, diagnostics) if return_diagnostics else result
        if response_text and any(marker in response_text for marker in _PROMPT_ECHO_MARKERS):
            diagnostics["status"] = "prompt_echo"
            result = None
            return (result, diagnostics) if return_diagnostics else result
        if trace_enabled:
            print(f"{trace_prefix} stage=parse_json start", flush=True)
        parse_started = time.monotonic()
        payload = _parse_json_response(response)
        if trace_enabled:
            print(f"{trace_prefix} stage=parse_json done elapsed={time.monotonic() - parse_started:.2f}s", flush=True)
        if not _payload_has_semantic_content(payload):
            diagnostics["status"] = "no_semantic_payload"
            diagnostics["payload_keys"] = sorted(str(key) for key in dict(payload).keys())
            result = None
            return (result, diagnostics) if return_diagnostics else result
        if source_url.lower().endswith(".pdf"):
            if trace_enabled:
                print(f"{trace_prefix} stage=multimodal_summary start", flush=True)
            _LAST_ROUTER_PROGRESS.update({"stage": "multimodal_summary", "document_id": document_id, "detail": "multimodal_summary start"})
            summary_started = time.monotonic()
            multimodal_summary = _try_multimodal_summary(title=title, text=text, source_url=source_url)
            if trace_enabled:
                print(f"{trace_prefix} stage=multimodal_summary done elapsed={time.monotonic() - summary_started:.2f}s", flush=True)
            if multimodal_summary:
                payload.setdefault("summary", multimodal_summary)
                payload.setdefault("provenance", {})["multimodal_summary"] = True
        diagnostics["status"] = "ok"
        if trace_enabled:
            print(f"{trace_prefix} stage=coerce done total_elapsed={time.monotonic() - stage_started:.2f}s", flush=True)
        _LAST_ROUTER_PROGRESS.update({"stage": "coerce", "document_id": document_id, "detail": "coerce done"})
        result = _coerce_analysis_payload(payload, provider=provider or "unknown", model_name=model_name)
        return (result, diagnostics) if return_diagnostics else result
    except Exception as exc:
        diagnostics["status"] = "exception"
        diagnostics["error"] = str(exc)
        result = None
        return (result, diagnostics) if return_diagnostics else result


def _build_analysis_prompt(
    *,
    docket_id: str,
    case_name: str,
    court: str,
    document_id: str,
    title: str,
    text: str,
) -> str:
    return (
        "Return a JSON object only. Analyze this legal docket document and extract rich structured legal semantics.\n"
        "Required keys: classification, entities, relationships, deontic_statements, events, frames, propositions, temporal_formulas, dcec_formulas, summary.\n"
        "classification must contain label and rationale.\n"
        "entities items must contain id,label,type.\n"
        "relationships items must contain source,target,type.\n"
        "deontic_statements items should capture party, modality, action, trigger, authority_text when present.\n"
        "events items should capture id,label,time when present.\n"
        "frames items should capture frame_id,label,slots.\n"
        "propositions items should capture statement and assumptions.\n"
        "temporal_formulas and dcec_formulas should contain concise symbolic strings grounded in the document text.\n\n"
        f"Docket ID: {docket_id}\n"
        f"Case: {case_name}\n"
        f"Court: {court}\n"
        f"Document ID: {document_id}\n"
        f"Title: {title}\n"
        "Document text follows:\n"
        f"{text or title}"
    )


def _try_multimodal_summary(*, title: str, text: str, source_url: str) -> str:
    try:
        prompt = (
            "Provide a one-sentence legal document summary based on this filing metadata and extracted text. "
            "Do not invent facts."
        )
        response = multimodal_router.generate_text(
            prompt,
            additional_text_blocks=[f"Title: {title}", f"Source URL: {source_url}", text[:800]],
            temperature=0.0,
            max_new_tokens=96,
            allow_local_fallback=False,
            disable_model_retry=True,
        )
        trace = llm_router.get_last_generation_trace()
        if str(trace.get("provider_name") or "").strip().lower() == "mock":
            return ""
        return str(response or "").strip()
    except Exception:
        return ""


def _coerce_analysis_payload(payload: Mapping[str, Any], *, provider: str, model_name: str) -> RichDocumentAnalysis:
    classification = dict(payload.get("classification") or {})
    classification.setdefault("label", "other")
    classification["backend"] = "llm_router"

    entities = [dict(item) for item in list(payload.get("entities") or []) if isinstance(item, Mapping)]
    relationships = [dict(item) for item in list(payload.get("relationships") or []) if isinstance(item, Mapping)]
    deontic_statements = [dict(item) for item in list(payload.get("deontic_statements") or []) if isinstance(item, Mapping)]
    events = [dict(item) for item in list(payload.get("events") or []) if isinstance(item, Mapping)]
    frames = [dict(item) for item in list(payload.get("frames") or []) if isinstance(item, Mapping)]
    propositions = [dict(item) for item in list(payload.get("propositions") or []) if isinstance(item, Mapping)]
    temporal_formulas = [str(item) for item in list(payload.get("temporal_formulas") or []) if str(item).strip()]
    dcec_formulas = [str(item) for item in list(payload.get("dcec_formulas") or []) if str(item).strip()]
    summary = str(payload.get("summary") or "").strip()
    return RichDocumentAnalysis(
        classification=classification,
        entities=entities,
        relationships=relationships,
        deontic_statements=deontic_statements,
        events=events,
        frames=frames,
        propositions=propositions,
        temporal_formulas=temporal_formulas,
        dcec_formulas=dcec_formulas,
        summary=summary,
        provenance={"backend": "llm_router", "provider": provider, "model_name": model_name},
    )


def _parse_json_response(response: str) -> Dict[str, Any]:
    text = str(response or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except Exception:
        match = _JSON_BLOCK_RE.search(text)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

def _payload_has_semantic_content(payload: Mapping[str, Any]) -> bool:
    if not payload:
        return False
    for key in ("entities", "relationships", "deontic_statements", "events", "frames", "propositions", "temporal_formulas", "dcec_formulas"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            return True
        if isinstance(value, dict) and value:
            return True
    summary = str(payload.get("summary") or "").strip()
    classification = dict(payload.get("classification") or {})
    if summary and len(summary) >= 24:
        return True
    return bool(str(classification.get("label") or "").strip() and len(classification) > 1)


def _build_proof_object(*, document_id: str, proposition: Mapping[str, Any]) -> ProofObject:
    statement = str(proposition.get("statement") or "").strip() or f"Derived proposition for {document_id}"
    assumptions = [str(item) for item in list(proposition.get("assumptions") or []) if str(item).strip()]
    step = ProofStep(
        step_id=f"{document_id}:step:1",
        rule_id="router_extracted_proposition",
        premises=list(assumptions),
        conclusion=statement,
        ir_refs=[IRReference(kind="derived", id=document_id)],
        provenance=[SourceProvenance(source_path="docket_document", source_id=document_id)],
    )
    certificates = _build_certificates(statement, assumptions)
    proof_id = _stable_id("proof", document_id, statement)
    return ProofObject(
        proof_id=proof_id,
        query={"document_id": document_id, "statement": statement},
        root_conclusion=statement,
        steps=[step],
        status="proved",
        proof_hash=_stable_id("hash", statement, *assumptions),
        certificates=certificates,
        certificate_trace_map={certificate.certificate_id: [IRReference(kind="derived", id=document_id)] for certificate in certificates},
    )


def _build_certificates(theorem: str, assumptions: Sequence[str]) -> List[ProofCertificate]:
    certificates: List[ProofCertificate] = []
    for backend in (SMTStyleProverAdapter(), FirstOrderProverAdapter()):
        result = backend.prove(theorem, list(assumptions))
        payload = dict(result.certificate or {})
        normalized_hash = _stable_id(result.backend, theorem, *assumptions)
        certificates.append(
            ProofCertificate(
                certificate_id=f"cert_{normalized_hash[:12]}",
                backend=result.backend,
                format=str(payload.get("format") or "unknown"),
                theorem=theorem,
                assumptions=list(assumptions),
                payload=payload,
                normalized_hash=normalized_hash,
            )
        )
    return certificates


def _proof_to_dict(proof: ProofObject) -> Dict[str, Any]:
    return {
        "proof_id": proof.proof_id,
        "query": dict(proof.query),
        "root_conclusion": proof.root_conclusion,
        "status": proof.status,
        "proof_hash": proof.proof_hash,
        "steps": [
            {
                "step_id": step.step_id,
                "rule_id": step.rule_id,
                "premises": list(step.premises),
                "conclusion": step.conclusion,
                "ir_refs": [{"kind": ref.kind, "id": ref.id} for ref in list(step.ir_refs or [])],
                "provenance": [
                    {"source_path": prov.source_path, "source_id": prov.source_id, "source_span": prov.source_span}
                    for prov in list(step.provenance or [])
                ],
                "timestamp": step.timestamp,
                "confidence": float(step.confidence),
            }
            for step in list(proof.steps or [])
        ],
        "certificates": [
            {
                "certificate_id": cert.certificate_id,
                "backend": cert.backend,
                "format": cert.format,
                "theorem": cert.theorem,
                "assumptions": list(cert.assumptions),
                "payload": dict(cert.payload),
                "normalized_hash": cert.normalized_hash,
            }
            for cert in list(proof.certificates or [])
        ],
    }


def _stable_id(prefix: str, *parts: str) -> str:
    import hashlib

    digest = hashlib.sha256("||".join(str(part or "") for part in parts).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest}"


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
        if not any(key):
            continue
        if key in seen:
            continue
        seen.add(key)
        output.append(payload)
    return output


__all__ = ["RichDocumentAnalysis", "analyze_document_with_routers", "enrich_docket_documents_with_routers"]
_LAST_ROUTER_PROGRESS: Dict[str, str] = {
    "stage": "",
    "document_id": "",
    "detail": "",
}


def get_router_enrichment_progress() -> Dict[str, str]:
    return dict(_LAST_ROUTER_PROGRESS)
