#!/usr/bin/env python3
"""Workspace dataset bundle inspection CLI."""

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
    render_workspace_dataset_single_parquet_report,
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
        description="Inspect workspace dataset single-parquet bundles.",
    )
    parser.add_argument(
        "--action",
        choices=["summary", "inspect", "load", "report", "export"],
        default="summary",
        help="Read a lightweight summary, bundle inspection view, full dataset-shaped payload, rendered report, or export a new workspace bundle.",
    )
    parser.add_argument(
        "--input-path",
        required=False,
        help="Path to the workspace dataset bundle for read actions, or input source path for --action export when paired with --input-type.",
    )
    parser.add_argument("--input-json", default="", help="For --action export, path to a workspace JSON payload.")
    parser.add_argument("--input-directory", default="", help="For --action export, path to a directory corpus.")
    parser.add_argument(
        "--input-type",
        choices=["workspace-json", "directory", "google-voice-manifest", "discord-export", "email-export"],
        default="",
        help="For --action export, explicit source type when using --input-path.",
    )
    parser.add_argument("--output-parquet", default="", help="For --action export, path to the output parquet bundle.")
    parser.add_argument("--workspace-id", default="", help="For --action export directory imports, optional workspace id override.")
    parser.add_argument("--workspace-name", default="", help="For --action export directory imports, optional workspace name override.")
    parser.add_argument("--source-type", default="workspace", help="For --action export, logical workspace source type label.")
    parser.add_argument("--strict-evidence-mode", action="store_true", help="For --action export, restrict to the plain_text+ retrieval subset.")
    parser.add_argument("--vector-dimension", type=int, default=16, help="For --action export, local vector dimension.")
    parser.add_argument("--glob-pattern", default="*", help="For --action export directory imports, optional file glob.")
    parser.add_argument("--write-normalized-json", default="", help="For --action export, optional path to persist normalized dataset JSON.")
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

    if parsed.action == "export":
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
        export_module = _load_export_workspace_script_module()
        return int(export_module.main(export_args))

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
    elif parsed.action == "report":
        rendered = render_workspace_dataset_single_parquet_report(
            bundle_path,
            report_format="json" if parsed.json else parsed.report_format,
        )
        print(rendered, end="")
        return 0
    else:
        payload = load_workspace_dataset_single_parquet(bundle_path)
        title = "Workspace Bundle"

    payload = _select_fields(payload, fields)
    if parsed.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(_render_text(payload, title=title), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())