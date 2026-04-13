#!/usr/bin/env python3
"""Build an end-to-end single-parquet bundle for a CourtListener docket."""

from __future__ import annotations

import argparse
import json
import os
import time
import threading
from pathlib import Path

from ipfs_datasets_py.processors.legal_data import (
    DocketDatasetObject,
    DocketDatasetBuilder,
    attach_available_courtlistener_recap_evidence_to_docket,
    attach_public_courtlistener_filing_pdfs_to_docket,
    audit_docket_dataset_citation_sources,
    docket_dataset,
    export_docket_dataset_single_parquet,
    fetch_courtlistener_docket,
    formal_docket_enrichment,
    proof_assistant as proof_assistant_module,
    rich_docket_enrichment,
    bluebook_citation_linker,
)
from ipfs_datasets_py import llm_router
from ipfs_datasets_py import embeddings_router


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a CourtListener docket as a single parquet bundle with evidence-aware indexing."
    )
    parser.add_argument(
        "--prefer-hacc-venv",
        action="store_true",
        help="Rerun the export with /home/barberb/HACC/.venv when available to ensure CUDA-enabled embeddings.",
    )
    parser.add_argument("--docket-id", required=True, help="CourtListener docket id.")
    parser.add_argument(
        "--input-enriched-json",
        default="",
        help="Optional path to a cached enriched docket JSON payload to skip refetching.",
    )
    parser.add_argument(
        "--filing-url",
        default="",
        help="Optional CourtListener filing page URL to harvest public filing PDFs from.",
    )
    parser.add_argument(
        "--output-parquet",
        required=True,
        help="Path to the output single-bundle parquet file.",
    )
    parser.add_argument(
        "--write-enriched-json",
        default="",
        help="Optional path to persist the enriched docket JSON payload.",
    )
    parser.add_argument(
        "--max-recap-documents",
        type=int,
        default=0,
        help="Optional cap on attached public recap evidence documents (0 = no cap).",
    )
    parser.add_argument(
        "--max-filing-pdfs",
        type=int,
        default=10,
        help="Maximum number of public filing-page PDFs to attach when --filing-url is provided.",
    )
    parser.add_argument(
        "--request-timeout-seconds",
        type=float,
        default=30.0,
        help="HTTP timeout for public evidence fetches.",
    )
    parser.add_argument(
        "--strict-evidence-mode",
        action="store_true",
        help="Restrict the bundled corpus to the plain_text+ retrieval subset before indexing/export.",
    )
    parser.add_argument(
        "--vector-dimension",
        type=int,
        default=16,
        help="Vector dimension for local hashed projection embeddings.",
    )
    parser.add_argument(
        "--full-logic-audit",
        action="store_true",
        help="Run full formal-logic, deontic, proof-assistant, and router enrichment before export.",
    )
    parser.add_argument(
        "--router-preflight",
        action="store_true",
        help="Run a lightweight llm_router preflight before router enrichment.",
    )
    parser.add_argument(
        "--no-router-enrichment",
        action="store_true",
        help="Skip llm_router enrichment to avoid long-running model calls.",
    )
    parser.add_argument(
        "--formal-logic-max-documents",
        type=int,
        default=None,
        help="Override formal logic max document count (default uses builder setting).",
    )
    parser.add_argument(
        "--router-max-documents",
        type=int,
        default=None,
        help="Override router enrichment max document count (default uses builder setting).",
    )
    parser.add_argument(
        "--citation-source-audit",
        action="store_true",
        help="Run the Bluebook citation source audit across docket documents.",
    )
    parser.add_argument(
        "--low-memory",
        action="store_true",
        help="Enable low-memory mode (disable router caches, EU audit, and cap citation audit text).",
    )
    parser.add_argument("--embeddings-provider", default="", help="Embeddings router provider override.")
    parser.add_argument("--embeddings-model", default="", help="Embeddings model name override.")
    parser.add_argument("--embeddings-device", default="", help="Embeddings device override (cpu/cuda).")
    parser.add_argument("--embeddings-batch-size", type=int, default=128, help="Batch size for embeddings_router.")
    parser.add_argument("--embeddings-parallel-batches", type=int, default=1, help="Parallel batch workers for embeddings_router.")
    parser.add_argument(
        "--embeddings-chunking-strategy",
        default="",
        help="Chunking strategy for embeddings (semantic, sentences, fixed, sliding_window).",
    )
    parser.add_argument("--embeddings-chunk-size", type=int, default=512, help="Chunk size for embeddings chunking.")
    parser.add_argument("--embeddings-chunk-overlap", type=int, default=50, help="Chunk overlap for embeddings chunking.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output.",
    )
    return parser.parse_args()


def _strip_document_raw_metadata(documents: list) -> None:
    keep_raw = str(os.getenv("IPFS_DATASETS_PY_EXPORT_KEEP_RAW_METADATA", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if keep_raw:
        return
    for document in documents:
        metadata = getattr(document, "metadata", None)
        if isinstance(metadata, dict):
            metadata.pop("raw", None)


def _serialize_dataset_payload(dataset_obj: DocketDatasetObject, status: dict) -> dict:
    documents = []
    total_documents = len(list(getattr(dataset_obj, "documents", []) or []))
    for index, document in enumerate(getattr(dataset_obj, "documents", []) or [], start=1):
        documents.append(document.to_dict())
        if index == total_documents or index % 25 == 0:
            status["detail"] = f"documents={index}/{total_documents}"
    return {
        "dataset_id": dataset_obj.dataset_id,
        "docket_id": dataset_obj.docket_id,
        "case_name": dataset_obj.case_name,
        "court": dataset_obj.court,
        "documents": documents,
        "plaintiff_docket": [dict(item) for item in list(dataset_obj.plaintiff_docket or [])],
        "defendant_docket": [dict(item) for item in list(dataset_obj.defendant_docket or [])],
        "authorities": [dict(item) for item in list(dataset_obj.authorities or [])],
        "knowledge_graph": dict(dataset_obj.knowledge_graph or {}),
        "deontic_graph": dict(dataset_obj.deontic_graph or {}),
        "deontic_triggers": dict(dataset_obj.deontic_triggers or {}),
        "proof_assistant": dict(dataset_obj.proof_assistant or {}),
        "bm25_index": dict(dataset_obj.bm25_index or {}),
        "vector_index": dict(dataset_obj.vector_index or {}),
        "metadata": dict(dataset_obj.metadata or {}),
    }


def _truthy_env(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "on"}


def _auto_cuda_device(requested: str | None, *, enable: bool) -> str | None:
    if str(requested or "").strip():
        return str(requested)
    if not enable:
        return None
    try:
        import torch  # type: ignore

        if torch.cuda.is_available():
            return "cuda"
    except Exception:
        return None
    return None


def _build_strict_subset(enriched: dict, builder: DocketDatasetBuilder) -> dict:
    preview = builder.preview_retrieval_index(enriched, min_evidence_quality="plain_text")
    selected_ids = {str(doc.get("document_id") or "") for doc in list(preview.get("documents") or [])}
    strict_docs = [
        document
        for document in list(enriched.get("documents") or [])
        if str(document.get("id") or document.get("document_id") or "") in selected_ids
    ]
    return {
        "docket_id": enriched.get("docket_id"),
        "case_name": enriched.get("case_name"),
        "court": enriched.get("court"),
        "source_type": "courtlistener_plain_text_plus_bundle",
        "metadata": {
            **dict(enriched.get("metadata") or {}),
            "artifact_provenance": {
                "retrieval_index": {
                    "selected_document_count": len(strict_docs),
                    "mode": "plain_text_plus",
                }
            },
        },
        "documents": strict_docs,
        "plaintiff_docket": list(enriched.get("plaintiff_docket") or []),
        "defendant_docket": list(enriched.get("defendant_docket") or []),
        "authorities": list(enriched.get("authorities") or []),
    }


def main() -> int:
    args = _parse_args()
    if args.prefer_hacc_venv:
        import os
        import sys

        target = "/home/barberb/HACC/.venv/bin/python"
        if sys.executable != target and os.path.exists(target):
            os.execv(target, [target, *sys.argv[1:]])

    if args.low_memory:
        os.environ.setdefault("IPFS_DATASETS_PY_ROUTER_CACHE", "0")
        os.environ.setdefault("IPFS_DATASETS_PY_ROUTER_RESPONSE_CACHE", "0")
        os.environ.setdefault("IPFS_DATASETS_PY_DISABLE_EU_AUDIT", "1")
        os.environ.setdefault("IPFS_DATASETS_PY_CITATION_AUDIT_MAX_CHARS", "20000")
        os.environ.setdefault("IPFS_DATASETS_PY_EMBEDDINGS_BATCH_WORKERS", "1")

    heartbeat_raw = str(os.getenv("IPFS_DATASETS_PY_EXPORT_HEARTBEAT_SECONDS", "0")).strip()
    try:
        heartbeat_seconds = max(0.0, float(heartbeat_raw))
    except Exception:
        heartbeat_seconds = 0.0
    status = {
        "stage": "init",
        "detail": "",
    }
    stop_event = threading.Event()

    def _heartbeat() -> None:
        if not heartbeat_seconds:
            return
        while not stop_event.wait(heartbeat_seconds):
            detail = status["detail"]
            if status["stage"] == "build_full_logic":
                formal = formal_docket_enrichment.get_formal_logic_progress()
                router = rich_docket_enrichment.get_router_enrichment_progress()
                proof = proof_assistant_module.get_proof_assistant_progress()
                dataset_progress = docket_dataset.get_docket_dataset_progress()
                embed_progress = embeddings_router.get_embedding_progress()
                if formal.get("stage"):
                    detail = f"formal:{formal.get('stage')} doc={formal.get('document_id')}"
                if router.get("stage"):
                    detail = f"{detail} router:{router.get('stage')} doc={router.get('document_id')}".strip()
                if proof.get("stage"):
                    detail = f"{detail} proof:{proof.get('stage')} {proof.get('detail')}".strip()
                if dataset_progress.get("stage"):
                    detail = f"{detail} dataset:{dataset_progress.get('stage')} {dataset_progress.get('detail')}".strip()
                if embed_progress.get("stage"):
                    detail = f"{detail} embed:{embed_progress.get('stage')} {embed_progress.get('detail')}".strip()
            elif status["stage"] == "citation_audit":
                citation_progress = bluebook_citation_linker.get_citation_audit_progress()
                if citation_progress.get("stage"):
                    detail = f"citations:{citation_progress.get('stage')} {citation_progress.get('detail')}".strip()
            print(f"[export] stage={status['stage']} detail={detail}", flush=True)

    heartbeat_thread = threading.Thread(target=_heartbeat, name="export-heartbeat", daemon=True)
    heartbeat_thread.start()

    output_parquet = Path(args.output_parquet).expanduser()
    output_parquet.parent.mkdir(parents=True, exist_ok=True)

    status["stage"] = "load_enriched"
    if str(args.input_enriched_json or "").strip():
        enriched_path = Path(args.input_enriched_json).expanduser()
        enriched = json.loads(enriched_path.read_text(encoding="utf-8"))
    else:
        status["stage"] = "fetch_docket"
        enriched = fetch_courtlistener_docket(
            str(args.docket_id),
            enable_rendered_page_enrichment=True,
            enable_pdf_text_backfill=False,
            include_recap_documents=True,
            include_document_text=True,
        )
        status["stage"] = "attach_recap"
        enriched = attach_available_courtlistener_recap_evidence_to_docket(
            enriched,
            max_documents=None if int(args.max_recap_documents or 0) <= 0 else int(args.max_recap_documents),
            request_timeout_seconds=float(args.request_timeout_seconds or 30.0),
        )
        if str(args.filing_url or "").strip():
            status["stage"] = "attach_filing_pdfs"
            enriched = attach_public_courtlistener_filing_pdfs_to_docket(
                enriched,
                str(args.filing_url).strip(),
                max_pdfs=max(0, int(args.max_filing_pdfs or 0)),
                request_timeout_seconds=float(args.request_timeout_seconds or 30.0),
            )

    if args.write_enriched_json:
        status["stage"] = "write_enriched_json"
        enriched_path = Path(args.write_enriched_json).expanduser()
        enriched_path.parent.mkdir(parents=True, exist_ok=True)
        enriched_path.write_text(json.dumps(enriched), encoding="utf-8")

    auto_cuda = str(os.getenv("IPFS_DATASETS_PY_AUTO_CUDA", "")).strip().lower() in {"1", "true", "yes", "on"}
    embeddings_device = _auto_cuda_device(
        str(args.embeddings_device or "").strip() or None,
        enable=auto_cuda,
    )

    builder = DocketDatasetBuilder(
        vector_dimension=max(8, int(args.vector_dimension or 16)),
        router_max_documents=4,
        formal_logic_max_documents=4,
        embeddings_provider=str(args.embeddings_provider or "").strip() or None,
        embeddings_model_name=str(args.embeddings_model or "").strip() or None,
        embeddings_device=embeddings_device,
        embeddings_batch_size=int(args.embeddings_batch_size or 128),
        embeddings_parallel_batches=int(args.embeddings_parallel_batches or 1),
        embeddings_chunking_strategy=str(args.embeddings_chunking_strategy or "").strip() or None,
        embeddings_chunk_size=int(args.embeddings_chunk_size or 512),
        embeddings_chunk_overlap=int(args.embeddings_chunk_overlap or 0),
    )
    preflight_report: dict | None = None
    if args.full_logic_audit and args.router_preflight:
        preflight_report = {
            "status": "unknown",
            "provider": "",
            "model_name": "",
            "elapsed_seconds": 0.0,
            "error": "",
        }
        try:
            status["stage"] = "router_preflight"
            preflight_start = time.monotonic()
            timeout_raw = str(os.getenv("IPFS_DATASETS_PY_PREFLIGHT_TIMEOUT_SECONDS", "10")).strip()
            try:
                preflight_timeout = max(0.0, float(timeout_raw))
            except Exception:
                preflight_timeout = 10.0
            if preflight_timeout:
                import concurrent.futures

                executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
                future = executor.submit(
                    llm_router.generate_text,
                    "Return a JSON object only. Respond with {\"status\":\"ok\"}.",
                    temperature=0.0,
                    max_new_tokens=24,
                    allow_local_fallback=False,
                    disable_model_retry=True,
                )
                try:
                    response = future.result(timeout=preflight_timeout)
                except concurrent.futures.TimeoutError:
                    preflight_report["status"] = "timeout"
                    preflight_report["elapsed_seconds"] = float(time.monotonic() - preflight_start)
                    future.cancel()
                    executor.shutdown(wait=False, cancel_futures=True)
                    response = ""
                else:
                    executor.shutdown(wait=False, cancel_futures=True)
            else:
                response = llm_router.generate_text(
                    "Return a JSON object only. Respond with {\"status\":\"ok\"}.",
                    temperature=0.0,
                    max_new_tokens=24,
                    allow_local_fallback=False,
                    disable_model_retry=True,
                )
            trace = llm_router.get_last_generation_trace()
            preflight_report["provider"] = str(trace.get("provider_name") or "")
            preflight_report["model_name"] = str(trace.get("model_name") or "")
            preflight_report["elapsed_seconds"] = float(time.monotonic() - preflight_start)
            if preflight_report["status"] == "unknown":
                preflight_report["status"] = "ok" if str(response or "").strip() else "empty_response"
        except Exception as exc:
            preflight_report["status"] = "error"
            preflight_report["error"] = str(exc)
    if args.formal_logic_max_documents is not None:
        builder.formal_logic_max_documents = max(0, int(args.formal_logic_max_documents))
    if args.router_max_documents is not None:
        builder.router_max_documents = max(0, int(args.router_max_documents))

    status["stage"] = "prepare_source"
    export_source = _build_strict_subset(enriched, builder) if bool(args.strict_evidence_mode) else enriched

    if args.full_logic_audit:
        if args.formal_logic_max_documents is None:
            builder.formal_logic_max_documents = None
        if args.router_max_documents is None:
            builder.router_max_documents = None
        status["stage"] = "build_full_logic"
        dataset_obj = builder.build_from_docket(
            export_source,
            include_knowledge_graph=True,
            include_bm25=True,
            include_vector_index=True,
            include_formal_logic=True,
            include_router_enrichment=not bool(args.no_router_enrichment),
        )
        status["stage"] = "trim_metadata"
        _strip_document_raw_metadata(getattr(dataset_obj, "documents", []))
        status["stage"] = "serialize_full_logic"
        status["detail"] = ""
        dataset_payload = _serialize_dataset_payload(dataset_obj, status)
    else:
        status["stage"] = "build_lightweight"
        normalized = builder._normalize_documents(export_source)
        index_documents = builder._select_index_documents(normalized)
        docket_id = str(export_source.get("docket_id") or "")
        case_name = str(export_source.get("case_name") or docket_id)
        court = str(export_source.get("court") or "")
        dataset_id = f"docket_dataset_{docket_id.replace(':', '_').replace('-', '_')}"
        knowledge_graph = builder._build_knowledge_graph(dataset_id, docket_id, case_name, court, index_documents)
        bm25_index = builder._build_bm25_index(dataset_id, index_documents)
        vector_index = builder._build_vector_index(dataset_id, index_documents)

        dataset_payload = {
            "dataset_id": dataset_id,
            "docket_id": docket_id,
            "case_name": case_name,
            "court": court,
            "documents": [document.to_dict() for document in normalized],
            "plaintiff_docket": list(export_source.get("plaintiff_docket") or []),
            "defendant_docket": list(export_source.get("defendant_docket") or []),
            "authorities": list(export_source.get("authorities") or []),
            "knowledge_graph": knowledge_graph,
            "deontic_graph": {},
            "deontic_triggers": {},
            "proof_assistant": {},
            "bm25_index": bm25_index,
            "vector_index": vector_index,
            "metadata": dict(export_source.get("metadata") or {}),
        }
    if args.citation_source_audit:
        status["stage"] = "citation_audit"
        dataset_obj = DocketDatasetObject.from_dict(dataset_payload)
        eu_max_raw = str(os.getenv("IPFS_DATASETS_PY_EU_AUDIT_MAX_DOCUMENTS", "")).strip()
        eu_max_documents = None
        if eu_max_raw:
            try:
                eu_max_documents = max(0, int(eu_max_raw))
            except Exception:
                eu_max_documents = None
        citation_audit = audit_docket_dataset_citation_sources(
            dataset_obj,
            include_eu_audit=not _truthy_env("IPFS_DATASETS_PY_DISABLE_EU_AUDIT"),
            eu_max_documents=eu_max_documents or 120,
        )
        dataset_payload.setdefault("metadata", {})["citation_source_audit"] = dict(citation_audit)
    if preflight_report:
        dataset_payload.setdefault("metadata", {})["router_preflight"] = dict(preflight_report)

    status["stage"] = "export_parquet"
    export_result = export_docket_dataset_single_parquet(dataset_payload, output_parquet)
    docket_id = str(dataset_payload.get("docket_id") or "")
    case_name = str(dataset_payload.get("case_name") or docket_id)
    court = str(dataset_payload.get("court") or "")
    knowledge_graph = dict(dataset_payload.get("knowledge_graph") or {})
    deontic_graph = dict(dataset_payload.get("deontic_graph") or {})
    deontic_triggers = dict(dataset_payload.get("deontic_triggers") or {})
    bm25_index = dict(dataset_payload.get("bm25_index") or {})
    vector_index = dict(dataset_payload.get("vector_index") or {})
    proof_assistant = dict(dataset_payload.get("proof_assistant") or {})
    citation_audit = dict((dataset_payload.get("metadata") or {}).get("citation_source_audit") or {})
    formal_logic_summary = dict((dataset_payload.get("metadata") or {}).get("artifact_provenance", {}).get("formal_logic") or {})
    payload = {
        "docket_id": docket_id,
        "case_name": case_name,
        "court": court,
        "strict_evidence_mode": bool(args.strict_evidence_mode),
        "document_count": len(list(dataset_payload.get("documents") or [])),
        "bm25_document_count": int((bm25_index or {}).get("document_count") or 0),
        "vector_document_count": int((vector_index or {}).get("document_count") or 0),
        "vector_total_count": int((vector_index or {}).get("vector_count") or 0),
        "knowledge_graph_entity_count": len(list((knowledge_graph or {}).get("entities") or [])),
        "knowledge_graph_relationship_count": len(list((knowledge_graph or {}).get("relationships") or [])),
        "proof_agenda_count": len(list((proof_assistant or {}).get("agenda") or [])),
        "proof_evidence_packet_count": len(list((proof_assistant or {}).get("evidence_packets") or [])),
        "proof_revalidation_count": len(list((proof_assistant or {}).get("revalidation_runs") or [])),
        "deontic_rule_count": len(dict(deontic_graph.get("rules") or {})),
        "deontic_node_count": len(dict(deontic_graph.get("nodes") or {})),
        "deontic_trigger_count": len(list((deontic_triggers or {}).get("entries") or [])),
        "formal_logic_summary": formal_logic_summary,
        "vector_backend": str((vector_index or {}).get("backend") or ""),
        "vector_provider": str((vector_index or {}).get("provider") or ""),
        "vector_model": str((vector_index or {}).get("model_name") or ""),
        "vector_device": str((vector_index or {}).get("device") or ""),
        "vector_chunking_strategy": str((vector_index or {}).get("chunking_strategy") or ""),
        "vector_chunk_size": (vector_index or {}).get("chunk_size"),
        "vector_chunk_overlap": (vector_index or {}).get("chunk_overlap"),
        "vector_batch_size": (vector_index or {}).get("batch_size"),
        "vector_parallel_batches": (vector_index or {}).get("parallel_batches"),
        "citation_audit_included": bool(args.citation_source_audit),
        "citation_count": int(citation_audit.get("citation_count") or 0),
        "unmatched_citation_count": int(citation_audit.get("unmatched_citation_count") or 0),
        "documents_with_citations": int(citation_audit.get("documents_with_citations") or 0),
        "router_preflight": preflight_report or {},
        "export": export_result,
    }

    stop_event.set()
    if heartbeat_thread.is_alive():
        heartbeat_thread.join(timeout=1.0)

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Docket: {docket_id}")
        print(f"Case: {case_name}")
        print(f"Court: {court}")
        print(f"Strict evidence mode: {bool(args.strict_evidence_mode)}")
        print(f"Documents: {payload['document_count']}")
        print(f"BM25 documents: {payload['bm25_document_count']}")
        print(f"Vector documents: {payload['vector_document_count']}")
        if payload.get("vector_total_count"):
            print(f"Vector count: {payload['vector_total_count']}")
        if payload.get("citation_audit_included"):
            print(
                "Citation audit: "
                f"citations={payload.get('citation_count')} "
                f"unmatched={payload.get('unmatched_citation_count')} "
                f"documents_with_citations={payload.get('documents_with_citations')}"
            )
        if payload.get("vector_backend"):
            print(
                "Vector backend: "
                f"{payload.get('vector_backend')} "
                f"model={payload.get('vector_model') or ''} "
                f"device={payload.get('vector_device') or ''} "
                f"chunking={payload.get('vector_chunking_strategy') or ''}"
            )
        print(f"KG entities: {payload['knowledge_graph_entity_count']}")
        print(f"KG relationships: {payload['knowledge_graph_relationship_count']}")
        print(f"Output parquet: {export_result['parquet_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
