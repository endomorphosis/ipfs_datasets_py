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
    parser.add_argument("--output-parquet", required=True, help="Path to the output single-bundle parquet file.")
    parser.add_argument("--input-json", default="", help="Path to a workspace JSON payload.")
    parser.add_argument("--input-directory", default="", help="Path to a directory corpus to ingest.")
    parser.add_argument(
        "--input-type",
        choices=["workspace-json", "directory", "google-voice-manifest", "discord-export", "email-export"],
        default="",
        help="Explicit source type when using --input-path.",
    )
    parser.add_argument("--input-path", default="", help="Generic input path used with --input-type.")
    parser.add_argument("--workspace-id", default="", help="Optional workspace id override.")
    parser.add_argument("--workspace-name", default="", help="Optional workspace name override.")
    parser.add_argument("--source-type", default="", help="Optional workspace source type override.")
    parser.add_argument("--strict-evidence-mode", action="store_true", help="Restrict to the plain_text+ retrieval subset.")
    parser.add_argument("--vector-dimension", type=int, default=16, help="Vector dimension for local hashed embeddings.")
    parser.add_argument("--glob-pattern", default="*", help="Glob used for directory ingestion.")
    parser.add_argument("--write-normalized-json", default="", help="Optional path to persist the normalized dataset JSON.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    return parser.parse_args(args)


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


def _load_dataset(args: argparse.Namespace, builder: WorkspaceDatasetBuilder):
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
        input_type = str(args.input_type or "").strip().lower()
        if not input_type:
            raise ValueError("--input-type is required when using --input-path")
        if input_type == "workspace-json":
            dataset = builder.build_from_json_file(input_path)
        elif input_type == "directory":
            dataset = builder.build_from_directory(
                input_path,
                workspace_id=str(args.workspace_id or "") or None,
                workspace_name=str(args.workspace_name or "") or None,
                source_type=str(args.source_type or "workspace") or "workspace",
                glob_pattern=str(args.glob_pattern or "*"),
            )
        elif input_type == "google-voice-manifest":
            dataset = builder.build_from_google_voice_manifest(input_path)
        elif input_type == "discord-export":
            dataset = builder.build_from_discord_export(input_path)
        elif input_type == "email-export":
            dataset = builder.build_from_email_export(input_path)
        else:
            raise ValueError(f"Unsupported --input-type: {input_type}")
    else:
        raise ValueError("An input source is required. Provide --input-json, --input-directory, or --input-path.")

    return _apply_overrides(dataset, args, builder)


def main(args: list[str] | None = None) -> int:
    parsed = _parse_args(args)
    output_parquet = Path(parsed.output_parquet).expanduser()
    output_parquet.parent.mkdir(parents=True, exist_ok=True)

    builder = WorkspaceDatasetBuilder(
        vector_dimension=max(8, int(parsed.vector_dimension or 16)),
        router_max_documents=4,
        formal_logic_max_documents=4,
    )

    dataset = _load_dataset(parsed, builder)
    if str(parsed.write_normalized_json or "").strip():
        dataset.write_json(parsed.write_normalized_json)

    export_result = export_workspace_dataset_single_parquet(dataset, output_parquet)
    summary = dataset.summary()
    payload = {
        **summary,
        "strict_evidence_mode": bool(parsed.strict_evidence_mode),
        "export": export_result,
    }

    if parsed.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Workspace: {payload.get('workspace_id')}")
        print(f"Name: {payload.get('workspace_name')}")
        print(f"Source: {payload.get('source_type')}")
        print(f"Strict evidence mode: {payload.get('strict_evidence_mode')}")
        print(f"Documents: {payload.get('document_count')}")
        print(f"Collections: {payload.get('collection_count')}")
        print(f"BM25 documents: {payload.get('bm25_document_count')}")
        print(f"Vector documents: {payload.get('vector_document_count')}")
        print(f"KG entities: {payload.get('knowledge_graph_entity_count')}")
        print(f"KG relationships: {payload.get('knowledge_graph_relationship_count')}")
        print(f"Output parquet: {export_result.get('parquet_path')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
