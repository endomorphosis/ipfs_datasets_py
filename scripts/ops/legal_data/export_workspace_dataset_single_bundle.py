#!/usr/bin/env python3
"""Build a single-parquet bundle for a workspace dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_data import (
    WorkspaceDatasetBuilder,
    export_workspace_dataset_single_parquet,
)


def _parse_args(args: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a workspace dataset as a single parquet bundle with evidence-aware indexing."
    )
    parser.add_argument(
        "--prefer-hacc-venv",
        action="store_true",
        help="Rerun the export with /home/barberb/HACC/.venv when available to ensure CUDA-enabled embeddings.",
    )
    parser.add_argument("--output-parquet", required=True, help="Path to the output single-bundle parquet file.")
    parser.add_argument("--input-json", default="", help="Path to a workspace JSON payload.")
    parser.add_argument("--input-directory", default="", help="Path to a directory corpus to ingest.")
    parser.add_argument(
        "--input-type",
        choices=[
            "workspace-json",
            "directory",
            "google-voice-manifest",
            "discord-export",
            "email-export",
            "imap-snippet-summary",
        ],
        default="",
        help="Explicit source type when using --input-path.",
    )
    parser.add_argument("--input-path", default="", help="Generic input path used with --input-type.")
    parser.add_argument("--workspace-id", default="", help="Optional workspace id override.")
    parser.add_argument("--workspace-name", default="", help="Optional workspace name override.")
    parser.add_argument("--source-type", default="", help="Optional workspace source type override.")
    parser.add_argument("--strict-evidence-mode", action="store_true", help="Restrict to the plain_text+ retrieval subset.")
    parser.add_argument("--vector-dimension", type=int, default=16, help="Vector dimension for local hashed embeddings.")
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
    parser.add_argument("--glob-pattern", default="*", help="Glob used for directory ingestion.")
    parser.add_argument("--write-normalized-json", default="", help="Optional path to persist the normalized dataset JSON.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    return parser.parse_args(args)


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


def _build_strict_subset(workspace_payload: dict, builder: WorkspaceDatasetBuilder) -> dict:
    preview = builder.preview_retrieval_index(workspace_payload, min_evidence_quality="plain_text")
    selected_ids = {str(doc.get("document_id") or "") for doc in list(preview.get("documents") or [])}
    strict_docs = [
        document
        for document in list(workspace_payload.get("documents") or [])
        if str(document.get("document_id") or document.get("id") or "") in selected_ids
    ]
    metadata = dict(workspace_payload.get("metadata") or {})
    artifact_provenance = dict(metadata.get("artifact_provenance") or {})
    artifact_provenance["retrieval_index"] = {
        "selected_document_count": len(strict_docs),
        "mode": "plain_text_plus",
    }
    metadata["artifact_provenance"] = artifact_provenance
    return {
        **workspace_payload,
        "documents": strict_docs,
        "metadata": metadata,
        "source_type": str(workspace_payload.get("source_type") or "workspace_plain_text_plus_bundle"),
    }


def _apply_overrides(dataset, args: argparse.Namespace, builder: WorkspaceDatasetBuilder):
    payload = dataset.to_dict()
    overrides_applied = False
    if str(args.workspace_id or "").strip():
        payload["workspace_id"] = str(args.workspace_id)
        overrides_applied = True
    if str(args.workspace_name or "").strip():
        payload["workspace_name"] = str(args.workspace_name)
        overrides_applied = True
    if str(args.source_type or "").strip():
        payload["source_type"] = str(args.source_type)
        overrides_applied = True
    if bool(args.strict_evidence_mode):
        payload = _build_strict_subset(payload, builder)
        overrides_applied = True
    if overrides_applied:
        return builder.build_from_workspace(payload)
    return dataset


def _load_workspace_payload(input_path: str) -> dict:
    with Path(input_path).expanduser().open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _detect_workspace_input_type(input_path: str) -> str:
    path = Path(input_path).expanduser()
    if path.is_dir():
        return "directory"
    payload = _load_workspace_payload(input_path)
    if isinstance(payload, dict):
        if isinstance(payload.get("bundles"), list):
            return "google-voice-manifest"
        if isinstance(payload.get("messages"), list):
            return "discord-export"
        if isinstance(payload.get("emails"), list):
            return "email-export"
    if isinstance(payload, list) and payload:
        sample = payload[0]
        if isinstance(sample, dict) and ("body_path" in sample or "headers_path" in sample):
            return "imap-snippet-summary"
    return "workspace-json"


def _resolve_workspace_input_type(args: argparse.Namespace) -> tuple[str, str]:
    if str(args.input_json or "").strip():
        return "workspace-json", "legacy-input-json"
    if str(args.input_directory or "").strip():
        return "directory", "legacy-input-directory"
    input_type = str(args.input_type or "").strip().lower()
    if input_type:
        return input_type, "explicit"
    input_path = str(args.input_path or "").strip()
    if input_path:
        return _detect_workspace_input_type(input_path), "auto"
    raise ValueError("An input source is required. Provide --input-json, --input-directory, or --input-path.")


def _load_dataset(args: argparse.Namespace, builder: WorkspaceDatasetBuilder):
    resolved_input_type, _resolution = _resolve_workspace_input_type(args)
    if str(args.input_json or "").strip():
        dataset = builder.build_from_json_file(args.input_json)
    elif str(args.input_directory or "").strip():
        dataset = builder.build_from_directory(
            args.input_directory,
            workspace_id=str(args.workspace_id or "") or None,
            workspace_name=str(args.workspace_name or "") or None,
            source_type=str(args.source_type or "workspace") or "workspace",
            glob_pattern=str(args.glob_pattern or "*"),
        )
    elif str(args.input_path or "").strip():
        input_path = str(args.input_path)
        if resolved_input_type == "workspace-json":
            dataset = builder.build_from_json_file(input_path)
        elif resolved_input_type == "directory":
            dataset = builder.build_from_directory(
                input_path,
                workspace_id=str(args.workspace_id or "") or None,
                workspace_name=str(args.workspace_name or "") or None,
                source_type=str(args.source_type or "workspace") or "workspace",
                glob_pattern=str(args.glob_pattern or "*"),
            )
        elif resolved_input_type == "google-voice-manifest":
            dataset = builder.build_from_google_voice_manifest(input_path)
        elif resolved_input_type == "discord-export":
            dataset = builder.build_from_discord_export(input_path)
        elif resolved_input_type == "email-export":
            dataset = builder.build_from_email_export(input_path)
        elif resolved_input_type == "imap-snippet-summary":
            dataset = builder.build_from_imap_snippet_summary(input_path)
        else:
            raise ValueError(f"Unsupported --input-type: {resolved_input_type}")
    else:
        raise ValueError("An input source is required. Provide --input-json, --input-directory, or --input-path.")

    return _apply_overrides(dataset, args, builder)


def main(args: list[str] | None = None) -> int:
    parsed = _parse_args(args)
    if parsed.prefer_hacc_venv:
        import os
        import sys

        target = "/home/barberb/HACC/.venv/bin/python"
        if sys.executable != target and os.path.exists(target):
            os.execv(target, [target, *sys.argv[1:]])
    output_parquet = Path(parsed.output_parquet).expanduser()
    output_parquet.parent.mkdir(parents=True, exist_ok=True)

    auto_cuda = str(os.getenv("IPFS_DATASETS_PY_AUTO_CUDA", "")).strip().lower() in {"1", "true", "yes", "on"}
    embeddings_device = _auto_cuda_device(
        str(parsed.embeddings_device or "").strip() or None,
        enable=auto_cuda,
    )

    builder = WorkspaceDatasetBuilder(
        vector_dimension=max(8, int(parsed.vector_dimension or 16)),
        router_max_documents=4,
        formal_logic_max_documents=4,
        embeddings_provider=str(parsed.embeddings_provider or "").strip() or None,
        embeddings_model_name=str(parsed.embeddings_model or "").strip() or None,
        embeddings_device=embeddings_device,
        embeddings_batch_size=int(parsed.embeddings_batch_size or 128),
        embeddings_parallel_batches=int(parsed.embeddings_parallel_batches or 1),
        embeddings_chunking_strategy=str(parsed.embeddings_chunking_strategy or "").strip() or None,
        embeddings_chunk_size=int(parsed.embeddings_chunk_size or 512),
        embeddings_chunk_overlap=int(parsed.embeddings_chunk_overlap or 0),
    )

    input_type, input_type_resolution = _resolve_workspace_input_type(parsed)
    dataset = _load_dataset(parsed, builder)
    if str(parsed.write_normalized_json or "").strip():
        dataset.write_json(parsed.write_normalized_json)

    export_result = export_workspace_dataset_single_parquet(dataset, output_parquet)
    summary = dataset.summary()
    payload = {
        **summary,
        "input_type": input_type,
        "input_type_resolution": input_type_resolution,
        "strict_evidence_mode": bool(parsed.strict_evidence_mode),
        "vector_backend": str((dataset.vector_index or {}).get("backend") or ""),
        "vector_provider": str((dataset.vector_index or {}).get("provider") or ""),
        "vector_model": str((dataset.vector_index or {}).get("model_name") or ""),
        "vector_device": str((dataset.vector_index or {}).get("device") or ""),
        "vector_chunking_strategy": str((dataset.vector_index or {}).get("chunking_strategy") or ""),
        "vector_chunk_size": (dataset.vector_index or {}).get("chunk_size"),
        "vector_chunk_overlap": (dataset.vector_index or {}).get("chunk_overlap"),
        "vector_batch_size": (dataset.vector_index or {}).get("batch_size"),
        "vector_parallel_batches": (dataset.vector_index or {}).get("parallel_batches"),
        "export": export_result,
    }

    if parsed.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Workspace: {payload.get('workspace_id')}")
        print(f"Name: {payload.get('workspace_name')}")
        print(f"Source: {payload.get('source_type')}")
        print(f"Input type: {payload.get('input_type')} ({payload.get('input_type_resolution')})")
        print(f"Strict evidence mode: {payload.get('strict_evidence_mode')}")
        print(f"Documents: {payload.get('document_count')}")
        print(f"Collections: {payload.get('collection_count')}")
        print(f"BM25 documents: {payload.get('bm25_document_count')}")
        print(f"Vector documents: {payload.get('vector_document_count')}")
        if payload.get("vector_backend"):
            print(
                "Vector backend: "
                f"{payload.get('vector_backend')} "
                f"model={payload.get('vector_model') or ''} "
                f"device={payload.get('vector_device') or ''} "
                f"chunking={payload.get('vector_chunking_strategy') or ''}"
            )
        print(f"KG entities: {payload.get('knowledge_graph_entity_count')}")
        print(f"KG relationships: {payload.get('knowledge_graph_relationship_count')}")
        print(f"Output parquet: {export_result.get('parquet_path')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
