#!/usr/bin/env python3
"""Build an end-to-end single-parquet bundle for a generic workspace corpus."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_data import (
    WorkspaceDatasetBuilder,
    export_workspace_dataset_single_parquet,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a generic workspace corpus as a single parquet bundle with evidence-aware indexing."
    )
    input_group = parser.add_mutually_exclusive_group(required=False)
    input_group.add_argument(
        "--input-json",
        default="",
        help="Path to a workspace JSON payload.",
    )
    input_group.add_argument(
        "--input-directory",
        default="",
        help="Path to a directory of text, markdown, JSON, and EML evidence files.",
    )
    parser.add_argument(
        "--input-type",
        choices=["workspace-json", "directory", "google-voice-manifest", "discord-export", "email-export"],
        default="",
        help="Optional explicit input type when using --input-path instead of the legacy --input-json/--input-directory flags.",
    )
    parser.add_argument(
        "--input-path",
        default="",
        help="Path for --input-type driven imports. Supported types: workspace-json, directory, google-voice-manifest, discord-export, email-export.",
    )
    parser.add_argument(
        "--output-parquet",
        required=True,
        help="Path to the output single-bundle parquet file.",
    )
    parser.add_argument(
        "--workspace-id",
        default="",
        help="Optional workspace id override for directory ingestion.",
    )
    parser.add_argument(
        "--workspace-name",
        default="",
        help="Optional workspace name override for directory ingestion.",
    )
    parser.add_argument(
        "--source-type",
        default="workspace",
        help="Logical workspace source type for metadata and bundle labeling.",
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
        "--glob-pattern",
        default="*",
        help="Optional glob filter for directory ingestion.",
    )
    parser.add_argument(
        "--write-normalized-json",
        default="",
        help="Optional path to persist the normalized workspace dataset JSON payload.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output.",
    )
    args = parser.parse_args()
    if not str(args.input_json or "").strip() and not str(args.input_directory or "").strip():
        if not (str(args.input_type or "").strip() and str(args.input_path or "").strip()):
            parser.error("Provide either --input-json/--input-directory or --input-type with --input-path.")
    return args


def _build_strict_subset(workspace: dict, builder: WorkspaceDatasetBuilder) -> dict:
    preview = builder.preview_retrieval_index(workspace, min_evidence_quality="plain_text")
    selected_ids = {str(doc.get("document_id") or "") for doc in list(preview.get("documents") or [])}
    strict_docs = [
        document
        for document in list(workspace.get("documents") or [])
        if str(document.get("id") or document.get("document_id") or "") in selected_ids
    ]
    return {
        "workspace_id": workspace.get("workspace_id") or workspace.get("id") or "workspace",
        "workspace_name": workspace.get("workspace_name") or workspace.get("title") or workspace.get("workspace_id") or "workspace",
        "source_type": f"{workspace.get('source_type') or 'workspace'}_plain_text_plus_bundle",
        "source_path": workspace.get("source_path") or "",
        "metadata": {
            **dict(workspace.get("metadata") or {}),
            "artifact_provenance": {
                "retrieval_index": {
                    "selected_document_count": len(strict_docs),
                    "mode": "plain_text_plus",
                }
            },
        },
        "collections": list(workspace.get("collections") or []),
        "documents": strict_docs,
    }


def _load_workspace_payload(args: argparse.Namespace) -> dict:
    if str(args.input_json or "").strip():
        path = Path(args.input_json).expanduser()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Workspace JSON payload must be an object")
        payload.setdefault("source_type", str(args.source_type or "workspace"))
        payload.setdefault("source_path", str(path))
        return payload

    root = Path(args.input_directory).expanduser()
    documents = []
    supported_suffixes = {".txt", ".md", ".json", ".eml"}
    for path in sorted(candidate for candidate in root.rglob(str(args.glob_pattern or "*")) if candidate.is_file()):
        if path.suffix.lower() not in supported_suffixes:
            continue
        if path.suffix.lower() == ".json":
            try:
                json_payload = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                json_payload = None
            if isinstance(json_payload, dict):
                text = str(
                    json_payload.get("text")
                    or json_payload.get("plain_text")
                    or json_payload.get("content")
                    or json_payload.get("body")
                    or json_payload.get("message")
                    or json_payload.get("description")
                    or ""
                ).strip()
                if text:
                    documents.append(
                        {
                            "id": json_payload.get("id") or path.stem,
                            "title": json_payload.get("title") or json_payload.get("subject") or path.stem,
                            "text": text,
                            "source_url": str(path),
                            "document_type": json_payload.get("document_type") or "json",
                            "metadata": {"raw": json_payload},
                        }
                    )
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            continue
        documents.append(
            {
                "id": path.stem,
                "title": path.stem.replace("_", " ").replace("-", " ").strip() or path.name,
                "text": text,
                "source_url": str(path),
                "document_type": path.suffix.lower().lstrip("."),
            }
        )
    return {
        "workspace_id": str(args.workspace_id or root.name),
        "workspace_name": str(args.workspace_name or root.name.replace("_", " ").replace("-", " ")),
        "source_type": str(args.source_type or "directory"),
        "source_path": str(root),
        "collections": [
            {
                "id": root.name,
                "title": str(args.workspace_name or root.name),
                "source_path": str(root),
                "source_type": str(args.source_type or "directory"),
            }
        ],
        "documents": documents,
    }


def _build_dataset(args: argparse.Namespace, builder: WorkspaceDatasetBuilder):
    explicit_input_type = str(args.input_type or "").strip().lower()
    explicit_input_path = str(args.input_path or "").strip()
    if explicit_input_type and explicit_input_path:
        input_path = Path(explicit_input_path).expanduser()
        if explicit_input_type == "workspace-json":
            dataset = builder.build_from_json_file(input_path)
        elif explicit_input_type == "directory":
            dataset = builder.build_from_directory(
                input_path,
                workspace_id=str(args.workspace_id or "") or None,
                workspace_name=str(args.workspace_name or "") or None,
                source_type=str(args.source_type or "directory"),
                glob_pattern=str(args.glob_pattern or "*"),
            )
        elif explicit_input_type == "google-voice-manifest":
            dataset = builder.build_from_google_voice_manifest(input_path)
        elif explicit_input_type == "discord-export":
            dataset = builder.build_from_discord_export(input_path)
        elif explicit_input_type == "email-export":
            dataset = builder.build_from_email_export(input_path)
        else:
            raise ValueError(f"Unsupported workspace input type: {explicit_input_type}")
    else:
        workspace = _load_workspace_payload(args)
        dataset = builder.build_from_workspace(workspace)

    if bool(args.strict_evidence_mode):
        strict_workspace = _build_strict_subset(dataset.to_dict(), builder)
        dataset = builder.build_from_workspace(strict_workspace)
    return dataset


def main() -> int:
    args = _parse_args()
    output_parquet = Path(args.output_parquet).expanduser()
    output_parquet.parent.mkdir(parents=True, exist_ok=True)

    builder = WorkspaceDatasetBuilder(vector_dimension=max(8, int(args.vector_dimension or 16)))
    dataset = _build_dataset(args, builder)

    if str(args.write_normalized_json or "").strip():
        output_json = Path(args.write_normalized_json).expanduser()
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(dataset.to_dict(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    export_result = export_workspace_dataset_single_parquet(dataset, output_parquet)
    summary = dataset.summary()
    payload = {
        "workspace_id": summary["workspace_id"],
        "workspace_name": summary["workspace_name"],
        "source_type": summary["source_type"],
        "strict_evidence_mode": bool(args.strict_evidence_mode),
        "document_count": summary["document_count"],
        "collection_count": summary["collection_count"],
        "bm25_document_count": summary["bm25_document_count"],
        "vector_document_count": summary["vector_document_count"],
        "knowledge_graph_entity_count": summary["knowledge_graph_entity_count"],
        "knowledge_graph_relationship_count": summary["knowledge_graph_relationship_count"],
        "export": export_result,
    }

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Workspace: {payload['workspace_id']}")
        print(f"Name: {payload['workspace_name']}")
        print(f"Source type: {payload['source_type']}")
        print(f"Strict evidence mode: {payload['strict_evidence_mode']}")
        print(f"Documents: {payload['document_count']}")
        print(f"Collections: {payload['collection_count']}")
        print(f"BM25 documents: {payload['bm25_document_count']}")
        print(f"Vector documents: {payload['vector_document_count']}")
        print(f"KG entities: {payload['knowledge_graph_entity_count']}")
        print(f"KG relationships: {payload['knowledge_graph_relationship_count']}")
        print(f"Output parquet: {export_result['parquet_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())