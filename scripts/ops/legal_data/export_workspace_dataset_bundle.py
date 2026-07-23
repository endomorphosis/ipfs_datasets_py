#!/usr/bin/env python3
"""Build a packaged Parquet/CAR bundle for a workspace dataset."""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_data import (
    WorkspaceDatasetBuilder,
    WorkspaceDatasetPackager,
)


def _load_single_bundle_export_module():
    module_path = Path(__file__).resolve().parent / "export_workspace_dataset_single_bundle.py"
    spec = importlib.util.spec_from_file_location("workspace_export_single_bundle_for_package", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load workspace single-bundle export script from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Package a workspace dataset into chain-loadable Parquet (and optional CAR) artifacts."
    )
    parser.add_argument("--input-json", default="", help="Path to a workspace JSON payload.")
    parser.add_argument("--input-directory", default="", help="Path to a directory of evidence files.")
    parser.add_argument(
        "--input-type",
        choices=["workspace-json", "directory", "google-voice-manifest", "discord-export", "email-export", "imap-snippet-summary"],
        default="",
        help="Explicit input type when using --input-path. Omit it to auto-detect supported source shapes.",
    )
    parser.add_argument("--input-path", default="", help="Input path for generic or source-specific workspace imports.")
    parser.add_argument("--output-dir", required=True, help="Directory to write the packaged bundle.")
    parser.add_argument("--package-name", default="", help="Optional package name for structured bundle output.")
    parser.add_argument("--workspace-id", default="", help="Optional workspace id override for directory ingestion.")
    parser.add_argument("--workspace-name", default="", help="Optional workspace name override for directory ingestion.")
    parser.add_argument("--source-type", default="", help="Logical workspace source type label.")
    parser.add_argument("--strict-evidence-mode", action="store_true", help="Restrict to the plain_text+ retrieval subset.")
    parser.add_argument("--vector-dimension", type=int, default=16, help="Vector dimension for local embeddings.")
    parser.add_argument("--glob-pattern", default="*", help="Glob filter for directory ingestion.")
    parser.add_argument("--no-car", action="store_true", help="Disable CAR emission and write parquet-only bundles.")
    parser.add_argument("--write-normalized-json", default="", help="Optional path to persist normalized workspace JSON.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON output.")
    args = parser.parse_args(argv)
    if not str(args.input_json or "").strip() and not str(args.input_directory or "").strip():
        if not str(args.input_path or "").strip():
            parser.error("Provide --input-json, --input-directory, or --input-path.")
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




def _build_workspace_dataset(args: argparse.Namespace, export_module) -> dict:
    builder = WorkspaceDatasetBuilder(vector_dimension=int(args.vector_dimension or 16))
    dataset = export_module._load_dataset(args, builder)
    return dataset.to_dict()


def _annotate_input_type_provenance(
    dataset_payload: dict,
    *,
    input_type: str,
    input_type_resolution: str,
) -> dict:
    payload = dict(dataset_payload)
    metadata = dict(payload.get("metadata") or {})
    artifact_provenance = dict(metadata.get("artifact_provenance") or {})
    artifact_provenance["workspace_input"] = {
        "input_type": str(input_type or ""),
        "input_type_resolution": str(input_type_resolution or ""),
    }
    metadata["artifact_provenance"] = artifact_provenance
    payload["metadata"] = metadata
    return payload


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    export_module = _load_single_bundle_export_module()
    input_type, input_type_resolution = export_module._resolve_workspace_input_type(args)
    dataset_payload = _build_workspace_dataset(args, export_module)
    dataset_payload = _annotate_input_type_provenance(
        dataset_payload,
        input_type=input_type,
        input_type_resolution=input_type_resolution,
    )
    if args.strict_evidence_mode:
        dataset_payload = export_module._build_strict_subset(
            dataset_payload,
            WorkspaceDatasetBuilder(vector_dimension=int(args.vector_dimension or 16)),
        )

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
    result["input_type"] = input_type
    result["input_type_resolution"] = input_type_resolution

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
        print(f"Input type: {result.get('input_type')} ({result.get('input_type_resolution')})")
        summary = dict(result.get("summary") or {})
        print(f"Documents: {summary.get('document_count')}")
        print(f"Collections: {summary.get('collection_count')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
