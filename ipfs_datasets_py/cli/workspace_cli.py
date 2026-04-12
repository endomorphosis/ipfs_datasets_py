#!/usr/bin/env python3
"""Workspace dataset bundle inspection CLI."""

from __future__ import annotations

import argparse
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


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ipfs-datasets workspace",
        description="Inspect workspace dataset single-parquet bundles.",
    )
    parser.add_argument(
        "--action",
        choices=["summary", "inspect", "load", "report"],
        default="summary",
        help="Read a lightweight summary, bundle inspection view, full dataset-shaped payload, or rendered report.",
    )
    parser.add_argument(
        "--input-path",
        required=True,
        help="Path to the workspace dataset single-parquet bundle.",
    )
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
    fields = _parse_fields_arg(parsed.fields)
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