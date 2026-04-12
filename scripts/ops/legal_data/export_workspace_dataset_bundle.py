#!/usr/bin/env python3
"""Build a packaged Parquet/CAR bundle for a workspace dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_data import (
    WorkspaceDatasetBuilder,
    WorkspaceDatasetPackager,
)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Package a workspace dataset into chain-loadable Parquet (and optional CAR) artifacts."
    )
    parser.add_argument("--input-json", default="", help="Path to a workspace JSON payload.")
    parser.add_argument("--input-directory", default="", help="Path to a directory of evidence files.")
    parser.add_argument(
        "--input-type",
        choices=["workspace-json", "directory", "google-voice-manifest", "discord-export", "email-export"],
        default="",
        help="Explicit input type when using --input-path.",
    )
    parser.add_argument("--input-path", default="", help="Input path for --input-type driven imports.")
    parser.add_argument("--output-dir", required=True, help="Directory to write the packaged bundle.")
    parser.add_argument("--package-name", default="", help="Optional package name for structured bundle output.")
    parser.add_argument("--workspace-id", default="", help="Optional workspace id override for directory ingestion.")
    parser.add_argument("--workspace-name", default="", help="Optional workspace name override for directory ingestion.")
    parser.add_argument("--source-type", default="workspace", help="Logical workspace source type label.")
    parser.add_argument("--strict-evidence-mode", action="store_true", help="Restrict to the plain_text+ retrieval subset.")
    parser.add_argument("--vector-dimension", type=int, default=16, help="Vector dimension for local embeddings.")
    parser.add_argument("--glob-pattern", default="*", help="Glob filter for directory ingestion.")
    parser.add_argument("--no-car", action="store_true", help="Disable CAR emission and write parquet-only bundles.")
    parser.add_argument("--write-normalized-json", default="", help="Optional path to persist normalized workspace JSON.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    args = parser.parse_args(argv)
    if not str(args.input_json or "").strip() and not str(args.input_directory or "").strip():
        if not str(args.input_path or "").strip():
            parser.error("Provide --input-json, --input-directory, or --input-path with --input-type.")
    return args


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
    return {
        "workspace_id": str(args.workspace_id or root.name),
        "workspace_name": str(args.workspace_name or root.name.replace("_", " ").replace("-", " ")),
        "source_type": str(args.source_type or "directory"),
        "source_path": str(root),
        "documents": [],
        "collections": [
            {
                "id": root.name,
                "title": str(args.workspace_name or root.name),
                "source_path": str(root),
                "source_type": str(args.source_type or "directory"),
            }
        ],
    }


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


def _build_workspace_dataset(args: argparse.Namespace) -> dict:
    builder = WorkspaceDatasetBuilder(vector_dimension=int(args.vector_dimension or 16))

    if str(args.input_json or "").strip():
        workspace = _load_workspace_payload(args)
        dataset = builder.build_from_workspace(workspace)
        return dataset.to_dict()

    if str(args.input_directory or "").strip():
        dataset = builder.build_from_directory(
            args.input_directory,
            workspace_id=str(args.workspace_id or ""),
            workspace_name=str(args.workspace_name or ""),
            source_type=str(args.source_type or "directory"),
            glob_pattern=str(args.glob_pattern or "*"),
        )
        return dataset.to_dict()

    input_type = str(args.input_type or "").strip()
    input_path = str(args.input_path or "").strip()
    if not input_type or not input_path:
        raise ValueError("Missing --input-type or --input-path for workspace bundle export.")

    if input_type == "workspace-json":
        dataset = builder.build_from_json_file(input_path)
    elif input_type == "directory":
        dataset = builder.build_from_directory(
            input_path,
            workspace_id=str(args.workspace_id or ""),
            workspace_name=str(args.workspace_name or ""),
            source_type=str(args.source_type or "directory"),
            glob_pattern=str(args.glob_pattern or "*"),
        )
    elif input_type == "google-voice-manifest":
        dataset = builder.build_from_google_voice_manifest(input_path)
    elif input_type == "discord-export":
        dataset = builder.build_from_discord_export(input_path)
    elif input_type == "email-export":
        dataset = builder.build_from_email_export(input_path)
    else:
        raise ValueError(f"Unsupported input type: {input_type}")
    return dataset.to_dict()


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    dataset_payload = _build_workspace_dataset(args)
    if args.strict_evidence_mode:
        dataset_payload = _build_strict_subset(dataset_payload, WorkspaceDatasetBuilder(vector_dimension=int(args.vector_dimension or 16)))

    output_dir = Path(args.output_dir).expanduser()
    package_name = str(args.package_name or "").strip() or None
    include_car = not bool(args.no_car)

    packager = WorkspaceDatasetPackager()
    result = packager.package(
        dataset_payload,
        output_dir,
        package_name=package_name,
        include_car=include_car,
    )

    if str(args.write_normalized_json or "").strip():
        Path(args.write_normalized_json).expanduser().write_text(
            json.dumps(dataset_payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print("Workspace bundle packaged.")
        print(f"Bundle dir: {result.get('bundle_dir')}")
        print(f"Manifest: {result.get('manifest_json_path')}")
        summary = dict(result.get("summary") or {})
        print(f"Documents: {summary.get('document_count')}")
        print(f"Collections: {summary.get('collection_count')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
