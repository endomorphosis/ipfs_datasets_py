#!/usr/bin/env python3
"""Workspace dataset bundle inspection CLI.

Examples:
- `ipfs-datasets workspace --action summary --input-path /path/to/workspace_bundle.parquet --json`
- `ipfs-datasets workspace --action export --input-json /tmp/workspace.json --output-parquet /tmp/workspace_bundle.parquet --json`
- `ipfs-datasets workspace --action package --input-json /tmp/workspace.json --output-dir /tmp/workspace_bundle --package-name workspace_bundle --json`
- `ipfs-datasets workspace --action package-summary --input-path /tmp/workspace_bundle/bundle_manifest.json --json`
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

from ipfs_datasets_py.processors.legal_data import (
    inspect_workspace_dataset_single_parquet,
    load_workspace_dataset_single_parquet,
    load_workspace_dataset_single_parquet_summary,
    inspect_packaged_workspace_bundle,
    export_packaged_workspace_hf_records_parquet,
    ingest_workspace_pdf_directory,
    iter_packaged_workspace_chain,
    load_packaged_workspace_dataset,
    load_packaged_workspace_dataset_components,
    load_packaged_workspace_summary_view,
    package_workspace_dataset,
    render_packaged_workspace_report,
    render_workspace_dataset_single_parquet_report,
    search_workspace_dataset_bm25,
    search_workspace_dataset_vector,
)

__all__ = ["create_parser", "main"]


def _parse_fields_arg(value: str | None) -> list[str] | None:
    if value is None:
        return None
    fields = [item.strip() for item in str(value).split(",") if item.strip()]
    return fields or None


def _select_fields(payload: dict[str, Any], fields: list[str] | None) -> dict[str, Any]:
    if not fields:
        return dict(payload)
    return {field: payload.get(field) for field in fields}


def _render_text(payload: dict[str, Any], *, title: str) -> str:
    lines = [title]
    for key, value in payload.items():
        if isinstance(value, list):
            rendered = ", ".join(str(item) for item in value)
        elif isinstance(value, dict):
            rendered = json.dumps(value, ensure_ascii=False, sort_keys=True)
        else:
            rendered = str(value)
        lines.append(f"{key}: {rendered}")
    return "\n".join(lines) + "\n"


def _render_search_text(payload: dict[str, Any], *, title: str) -> str:
    lines = [title]
    lines.append(f"query: {str(payload.get('query') or '')}")
    lines.append(f"result_count: {int(payload.get('result_count') or 0)}")
    lines.append(f"group_count: {int(payload.get('group_count') or 0)}")

    grouped_results = [dict(item) for item in list(payload.get("grouped_results") or []) if isinstance(item, dict)]
    if grouped_results:
        lines.append("groups:")
        for group in grouped_results:
            lines.append(
                "  - "
                f"{str(group.get('group_id') or '')}"
                f" [{str(group.get('source_type') or '')}]"
                f" matches={int(group.get('match_count') or 0)}"
                f" docs={len(list(group.get('document_ids') or []))}"
            )
            for document in [dict(item) for item in list(group.get("documents") or []) if isinstance(item, dict)]:
                marker = "*" if bool(document.get("is_match")) else "-"
                lines.append(
                    "    "
                    f"{marker} {str(document.get('document_id') or '')}: {str(document.get('title') or '')}"
                )
    else:
        lines.append("groups: none")
    return "\n".join(lines) + "\n"


def _load_export_workspace_script_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "legal_data" / "export_workspace_dataset_single_bundle.py"
    spec = importlib.util.spec_from_file_location("workspace_export_single_bundle_under_test", module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load workspace export script from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ipfs-datasets workspace",
        description="Inspect, search, export, and package workspace datasets and packaged bundles.",
    )
    parser.add_argument(
        "--action",
        choices=[
            "summary",
            "inspect",
            "load",
            "report",
            "search-bm25",
            "search-vector",
            "export",
            "package",
            "package-summary",
            "package-inspect",
            "package-load",
            "package-report",
            "package-export-hf-records",
            "package-search-bm25",
            "package-search-vector",
            "chain",
            "components",
            "ingest-pdf-dir",
        ],
        default="summary",
        help="Read, search, export, or package workspace datasets and packaged bundles.",
    )
    parser.add_argument(
        "--input-path",
        required=False,
        help="Path to the workspace dataset bundle for read actions, or an input source path for --action export/--action package.",
    )
    parser.add_argument("--input-json", default="", help="For --action export or --action package, path to a workspace JSON payload.")
    parser.add_argument("--input-directory", default="", help="For --action export or --action package, path to a directory corpus.")
    parser.add_argument(
        "--input-type",
        choices=[
            "workspace-json",
            "directory",
            "google-voice-manifest",
            "discord-export",
            "email-export",
            "imap-snippet-summary",
            "pdf-directory",
        ],
        default="",
        help="For --action export or --action package, explicit source type when using --input-path. Omit it to auto-detect supported source shapes.",
    )
    parser.add_argument("--output-parquet", default="", help="For --action export, path to the output parquet bundle.")
    parser.add_argument("--output-dir", default="", help="For --action package, directory to write a packaged bundle.")
    parser.add_argument("--output-hf-records-parquet", default="", help="For --action package-export-hf-records, path to the single flat records parquet.")
    parser.add_argument("--package-name", default="", help="For --action package, optional package name.")
    parser.add_argument("--workspace-id", default="", help="For --action export or --action package directory imports, optional workspace id override.")
    parser.add_argument("--workspace-name", default="", help="For --action export or --action package directory imports, optional workspace name override.")
    parser.add_argument("--source-type", default="", help="For --action export or --action package, logical workspace source type label.")
    parser.add_argument("--embeddings-provider", default="", help="For --action export, embeddings router provider override.")
    parser.add_argument("--embeddings-model", default="", help="For --action export, embeddings model name override.")
    parser.add_argument("--embeddings-device", default="", help="For --action export, embeddings device override.")
    parser.add_argument("--embeddings-batch-size", type=int, default=128, help="For --action export, embeddings batch size.")
    parser.add_argument("--embeddings-parallel-batches", type=int, default=1, help="For --action export, embeddings parallel batches.")
    parser.add_argument("--embeddings-chunking-strategy", default="", help="For --action export, embeddings chunking strategy.")
    parser.add_argument("--embeddings-chunk-size", type=int, default=512, help="For --action export, embeddings chunk size.")
    parser.add_argument("--embeddings-chunk-overlap", type=int, default=50, help="For --action export, embeddings chunk overlap.")
    parser.add_argument("--strict-evidence-mode", action="store_true", help="For --action export or --action package, restrict to the plain_text+ retrieval subset.")
    parser.add_argument("--vector-dimension", type=int, default=16, help="For --action export or --action package, local vector dimension.")
    parser.add_argument("--glob-pattern", default="*", help="For --action export or --action package directory imports, optional file glob.")
    parser.add_argument("--exclude-dir", action="append", default=[], help="For --action ingest-pdf-dir, directory name to exclude; can be repeated.")
    parser.add_argument("--max-pdf-pages", type=int, default=0, help="For --action ingest-pdf-dir, optional max pages per PDF.")
    parser.add_argument("--max-pdf-chars", type=int, default=0, help="For --action ingest-pdf-dir, optional max extracted characters per PDF.")
    parser.add_argument("--max-logic-documents", type=int, default=0, help="For --action ingest-pdf-dir, optional max documents for formal logic extraction.")
    parser.add_argument("--enable-ocr", action="store_true", help="For --action ingest-pdf-dir, run Tesseract OCR when PDF text extraction is empty.")
    parser.add_argument("--ocr-dpi", type=int, default=200, help="For --action ingest-pdf-dir, render DPI used by Tesseract OCR.")
    parser.add_argument("--ocr-lang", default="eng", help="For --action ingest-pdf-dir, Tesseract language code.")
    parser.add_argument("--skip-failed-pdf-documents", action="store_true", help="For --action ingest-pdf-dir, omit PDFs that still have no text after extraction/OCR.")
    parser.add_argument("--no-formal-logic", action="store_true", help="For --action ingest-pdf-dir, skip formal logic/theorem extraction metadata.")
    parser.add_argument("--write-normalized-json", default="", help="For --action export, optional path to persist normalized dataset JSON.")
    parser.add_argument("--no-car", action="store_true", help="For --action package, disable CAR emission.")
    parser.add_argument("--piece-ids", default="", help="For --action components, comma-separated list of piece ids to load.")
    parser.add_argument("--query", default="", help="For search actions, query text.")
    parser.add_argument("--top-k", type=int, default=10, help="For search actions, maximum results to return.")
    parser.add_argument(
        "--fields",
        default=None,
        help="Comma-separated field subset for the selected action.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output.",
    )
    parser.add_argument(
        "--report-format",
        choices=["markdown", "text", "json"],
        default="markdown",
        help="Output format used with --action report.",
    )
    return parser


def main(args: list[str] | None = None) -> int:
    parser = create_parser()
    parsed = parser.parse_args(args)

    if parsed.action == "ingest-pdf-dir":
        input_directory = str(parsed.input_directory or parsed.input_path or "").strip()
        output_parquet = str(parsed.output_parquet or "").strip()
        if not input_directory:
            parser.error("--input-directory or --input-path is required for --action ingest-pdf-dir.")
        if not output_parquet:
            parser.error("--output-parquet is required for --action ingest-pdf-dir.")
        payload = ingest_workspace_pdf_directory(
            input_directory,
            output_parquet,
            workspace_id=str(parsed.workspace_id or "") or None,
            workspace_name=str(parsed.workspace_name or "") or None,
            source_type=str(parsed.source_type or "pdf_directory"),
            vector_dimension=int(parsed.vector_dimension or 16),
            include_formal_logic=not bool(parsed.no_formal_logic),
            formal_logic_max_documents=int(parsed.max_logic_documents) if int(parsed.max_logic_documents or 0) > 0 else None,
            max_pdf_pages=int(parsed.max_pdf_pages) if int(parsed.max_pdf_pages or 0) > 0 else None,
            max_pdf_chars=int(parsed.max_pdf_chars) if int(parsed.max_pdf_chars or 0) > 0 else None,
            enable_ocr=bool(parsed.enable_ocr),
            ocr_dpi=int(parsed.ocr_dpi or 200),
            ocr_lang=str(parsed.ocr_lang or "eng"),
            include_failed_pdf_documents=not bool(parsed.skip_failed_pdf_documents),
            glob_pattern=str(parsed.glob_pattern or "*.pdf"),
            exclude_dirs=list(parsed.exclude_dir or []),
        )
        if parsed.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(_render_text(payload, title="Workspace PDF Directory Ingest"), end="")
        return 0

    if parsed.action in {"export", "package"}:
        export_args: list[str] = ["--output-parquet", str(parsed.output_parquet or "")] if str(parsed.output_parquet or "").strip() else []
        if str(parsed.input_json or "").strip():
            export_args.extend(["--input-json", str(parsed.input_json)])
        if str(parsed.input_directory or "").strip():
            export_args.extend(["--input-directory", str(parsed.input_directory)])
        if str(parsed.input_type or "").strip():
            export_args.extend(["--input-type", str(parsed.input_type)])
        if str(parsed.input_path or "").strip():
            export_args.extend(["--input-path", str(parsed.input_path)])
        if str(parsed.workspace_id or "").strip():
            export_args.extend(["--workspace-id", str(parsed.workspace_id)])
        if str(parsed.workspace_name or "").strip():
            export_args.extend(["--workspace-name", str(parsed.workspace_name)])
        if str(parsed.source_type or "").strip():
            export_args.extend(["--source-type", str(parsed.source_type)])
        if str(parsed.embeddings_provider or "").strip():
            export_args.extend(["--embeddings-provider", str(parsed.embeddings_provider)])
        if str(parsed.embeddings_model or "").strip():
            export_args.extend(["--embeddings-model", str(parsed.embeddings_model)])
        if str(parsed.embeddings_device or "").strip():
            export_args.extend(["--embeddings-device", str(parsed.embeddings_device)])
        if int(parsed.embeddings_batch_size or 0) > 0:
            export_args.extend(["--embeddings-batch-size", str(parsed.embeddings_batch_size)])
        if int(parsed.embeddings_parallel_batches or 0) > 0:
            export_args.extend(["--embeddings-parallel-batches", str(parsed.embeddings_parallel_batches)])
        if str(parsed.embeddings_chunking_strategy or "").strip():
            export_args.extend(["--embeddings-chunking-strategy", str(parsed.embeddings_chunking_strategy)])
        if int(parsed.embeddings_chunk_size or 0) > 0:
            export_args.extend(["--embeddings-chunk-size", str(parsed.embeddings_chunk_size)])
        if int(parsed.embeddings_chunk_overlap or 0) >= 0:
            export_args.extend(["--embeddings-chunk-overlap", str(parsed.embeddings_chunk_overlap)])
        if bool(parsed.strict_evidence_mode):
            export_args.append("--strict-evidence-mode")
        if int(parsed.vector_dimension or 0) > 0:
            export_args.extend(["--vector-dimension", str(parsed.vector_dimension)])
        if str(parsed.glob_pattern or "").strip():
            export_args.extend(["--glob-pattern", str(parsed.glob_pattern)])
        if str(parsed.write_normalized_json or "").strip():
            export_args.extend(["--write-normalized-json", str(parsed.write_normalized_json)])
        if bool(parsed.json):
            export_args.append("--json")
        if not export_args:
            parser.error("--action export requires export input flags and --output-parquet.")
        if parsed.action == "export":
            export_module = _load_export_workspace_script_module()
            return int(export_module.main(export_args))
        if not str(parsed.output_dir or "").strip():
            parser.error("--output-dir is required for --action package.")
        from ipfs_datasets_py.processors.legal_data import WorkspaceDatasetBuilder

        export_module = _load_export_workspace_script_module()
        builder = WorkspaceDatasetBuilder(vector_dimension=int(parsed.vector_dimension or 16))
        try:
            input_type, input_type_resolution = export_module._resolve_workspace_input_type(parsed)
            dataset_payload = export_module._load_dataset(parsed, builder)
        except ValueError as exc:
            parser.error(str(exc))

        dataset_dict = dataset_payload.to_dict() if hasattr(dataset_payload, "to_dict") else dict(dataset_payload)
        metadata = dict(dataset_dict.get("metadata") or {})
        artifact_provenance = dict(metadata.get("artifact_provenance") or {})
        artifact_provenance["workspace_input"] = {
            "input_type": str(input_type or ""),
            "input_type_resolution": str(input_type_resolution or ""),
        }
        metadata["artifact_provenance"] = artifact_provenance
        dataset_dict["metadata"] = metadata

        packaged = package_workspace_dataset(
            dataset_dict,
            str(parsed.output_dir),
            package_name=str(parsed.package_name or "") or None,
            include_car=not bool(parsed.no_car),
        )
        packaged["input_type"] = str(input_type or "")
        packaged["input_type_resolution"] = str(input_type_resolution or "")
        if parsed.json:
            print(json.dumps(packaged, indent=2, ensure_ascii=False))
        else:
            print(render_packaged_workspace_report(str(packaged.get("manifest_json_path") or ""), report_format="text"), end="")
        return 0

    fields = _parse_fields_arg(parsed.fields)
    if not str(parsed.input_path or "").strip():
        parser.error("--input-path is required for workspace read actions.")
    bundle_path = Path(parsed.input_path)

    if not bundle_path.exists():
        error_payload = {
            "status": "error",
            "error_type": "file_not_found",
            "message": f"Workspace bundle not found: {bundle_path}",
        }
        if parsed.json:
            print(json.dumps(error_payload, indent=2, ensure_ascii=False))
        else:
            print(f"file_not_found: Workspace bundle not found: {bundle_path}")
        return 1

    if parsed.action == "summary":
        payload = load_workspace_dataset_single_parquet_summary(bundle_path)
        title = "Workspace Bundle Summary"
    elif parsed.action == "inspect":
        payload = inspect_workspace_dataset_single_parquet(bundle_path)
        title = "Workspace Bundle Inspection"
    elif parsed.action == "search-bm25":
        if not str(parsed.query or "").strip():
            parser.error("--query is required for --action search-bm25.")
        payload = search_workspace_dataset_bm25(
            load_workspace_dataset_single_parquet(bundle_path),
            str(parsed.query),
            top_k=int(parsed.top_k or 10),
        )
        title = "Workspace BM25 Search"
    elif parsed.action == "search-vector":
        if not str(parsed.query or "").strip():
            parser.error("--query is required for --action search-vector.")
        payload = search_workspace_dataset_vector(
            load_workspace_dataset_single_parquet(bundle_path),
            str(parsed.query),
            top_k=int(parsed.top_k or 10),
        )
        title = "Workspace Vector Search"
    elif parsed.action == "report":
        rendered = render_workspace_dataset_single_parquet_report(
            bundle_path,
            report_format="json" if parsed.json else parsed.report_format,
        )
        print(rendered, end="")
        return 0
    elif parsed.action == "package-summary":
        payload = load_packaged_workspace_summary_view(bundle_path)
        title = "Packaged Workspace Summary"
    elif parsed.action == "package-inspect":
        payload = inspect_packaged_workspace_bundle(bundle_path)
        title = "Packaged Workspace Inspection"
    elif parsed.action == "package-load":
        payload = load_packaged_workspace_dataset(bundle_path)
        title = "Packaged Workspace Dataset"
    elif parsed.action == "package-search-bm25":
        if not str(parsed.query or "").strip():
            parser.error("--query is required for --action package-search-bm25.")
        payload = search_workspace_dataset_bm25(
            load_packaged_workspace_dataset(bundle_path),
            str(parsed.query),
            top_k=int(parsed.top_k or 10),
        )
        title = "Packaged Workspace BM25 Search"
    elif parsed.action == "package-search-vector":
        if not str(parsed.query or "").strip():
            parser.error("--query is required for --action package-search-vector.")
        payload = search_workspace_dataset_vector(
            load_packaged_workspace_dataset(bundle_path),
            str(parsed.query),
            top_k=int(parsed.top_k or 10),
        )
        title = "Packaged Workspace Vector Search"
    elif parsed.action == "package-report":
        rendered = render_packaged_workspace_report(
            bundle_path,
            report_format="json" if parsed.json else parsed.report_format,
        )
        print(rendered, end="")
        return 0
    elif parsed.action == "package-export-hf-records":
        output_path = str(parsed.output_hf_records_parquet or "").strip()
        if not output_path:
            parser.error("--output-hf-records-parquet is required for --action package-export-hf-records.")
        payload = export_packaged_workspace_hf_records_parquet(bundle_path, output_path)
        title = "Packaged Workspace HF Records Export"
    elif parsed.action == "chain":
        payload = iter_packaged_workspace_chain(bundle_path)
        title = "Packaged Workspace Chain"
    elif parsed.action == "components":
        piece_ids = [item.strip() for item in str(parsed.piece_ids or "").split(",") if item.strip()]
        payload = load_packaged_workspace_dataset_components(bundle_path, piece_ids=piece_ids or None)
        title = "Packaged Workspace Components"
    else:
        payload = load_workspace_dataset_single_parquet(bundle_path)
        title = "Workspace Bundle"

    payload = _select_fields(payload, fields)
    if parsed.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    elif parsed.action in {"search-bm25", "search-vector", "package-search-bm25", "package-search-vector"}:
        print(_render_search_text(payload, title=title), end="")
    else:
        print(_render_text(payload, title=title), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
