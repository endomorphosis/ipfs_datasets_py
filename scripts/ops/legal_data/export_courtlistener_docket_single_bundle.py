#!/usr/bin/env python3
"""Build an end-to-end single-parquet bundle for a CourtListener docket."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_data import (
    DocketDatasetBuilder,
    attach_available_courtlistener_recap_evidence_to_docket,
    attach_public_courtlistener_filing_pdfs_to_docket,
    export_docket_dataset_single_parquet,
    fetch_courtlistener_docket,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a CourtListener docket as a single parquet bundle with evidence-aware indexing."
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
        "--json",
        action="store_true",
        help="Print machine-readable JSON output.",
    )
    return parser.parse_args()


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

    output_parquet = Path(args.output_parquet).expanduser()
    output_parquet.parent.mkdir(parents=True, exist_ok=True)

    if str(args.input_enriched_json or "").strip():
        enriched_path = Path(args.input_enriched_json).expanduser()
        enriched = json.loads(enriched_path.read_text(encoding="utf-8"))
    else:
        enriched = fetch_courtlistener_docket(
            str(args.docket_id),
            enable_rendered_page_enrichment=True,
            enable_pdf_text_backfill=False,
            include_recap_documents=True,
            include_document_text=True,
        )
        enriched = attach_available_courtlistener_recap_evidence_to_docket(
            enriched,
            max_documents=None if int(args.max_recap_documents or 0) <= 0 else int(args.max_recap_documents),
            request_timeout_seconds=float(args.request_timeout_seconds or 30.0),
        )
        if str(args.filing_url or "").strip():
            enriched = attach_public_courtlistener_filing_pdfs_to_docket(
                enriched,
                str(args.filing_url).strip(),
                max_pdfs=max(0, int(args.max_filing_pdfs or 0)),
                request_timeout_seconds=float(args.request_timeout_seconds or 30.0),
            )

    if args.write_enriched_json:
        enriched_path = Path(args.write_enriched_json).expanduser()
        enriched_path.parent.mkdir(parents=True, exist_ok=True)
        enriched_path.write_text(json.dumps(enriched), encoding="utf-8")

    builder = DocketDatasetBuilder(
        vector_dimension=max(8, int(args.vector_dimension or 16)),
        router_max_documents=4,
        formal_logic_max_documents=4,
    )

    export_source = _build_strict_subset(enriched, builder) if bool(args.strict_evidence_mode) else enriched

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

    export_result = export_docket_dataset_single_parquet(dataset_payload, output_parquet)
    payload = {
        "docket_id": docket_id,
        "case_name": case_name,
        "court": court,
        "strict_evidence_mode": bool(args.strict_evidence_mode),
        "document_count": len(list(dataset_payload.get("documents") or [])),
        "bm25_document_count": int((bm25_index or {}).get("document_count") or 0),
        "vector_document_count": int((vector_index or {}).get("document_count") or 0),
        "knowledge_graph_entity_count": len(list((knowledge_graph or {}).get("entities") or [])),
        "knowledge_graph_relationship_count": len(list((knowledge_graph or {}).get("relationships") or [])),
        "export": export_result,
    }

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
        print(f"KG entities: {payload['knowledge_graph_entity_count']}")
        print(f"KG relationships: {payload['knowledge_graph_relationship_count']}")
        print(f"Output parquet: {export_result['parquet_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
