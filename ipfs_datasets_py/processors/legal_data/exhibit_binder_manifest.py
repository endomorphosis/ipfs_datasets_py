"""Manifest helpers for exhibit binder builds."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .exhibit_binder_export import (
    build_exhibit_binder,
    convert_markdown_to_binder_pdf,
    pdf_page_count,
    source_to_pdf,
)
from .exhibit_binder_templates import render_exhibit_binder_front_sheet, render_table_of_exhibits_pdf
from .legal_pdf_manifest import binder_court_config_from_manifest, load_json_manifest


def _resolve_exhibit_source(base_dir: Path, payload: dict[str, Any], exhibit: dict[str, Any], code: str) -> str:
    explicit = str(exhibit.get("source") or "").strip()
    if explicit:
        return explicit
    exhibits_root_value = str(payload.get("exhibits_root") or "").strip()
    if not exhibits_root_value:
        return ""
    exhibits_root = base_dir / exhibits_root_value
    matches = sorted(exhibits_root.glob(f"Exhibit_{code}_*"))
    return str(matches[0]) if matches else ""


def build_exhibit_binder_from_manifest(path: str | Path) -> dict[str, Any]:
    manifest_path = Path(path)
    payload = load_json_manifest(manifest_path)
    base_dir = manifest_path.parent
    working_dir = base_dir / str(payload.get("working_dir") or "compiled")
    output_pdf = base_dir / str(payload.get("output_pdf") or "binder.pdf")
    front_md = base_dir / str(payload.get("front_sheet_markdown") or "")
    front_pdf = working_dir / "0000_Exhibit_Binder_Front_Sheet.pdf"
    court_config = binder_court_config_from_manifest(payload)
    working_dir.mkdir(parents=True, exist_ok=True)
    render_exhibit_binder_front_sheet(front_md, front_pdf, config=court_config)

    packet_paths: list[Path] = []
    starts: dict[str, int] = {}
    counts: dict[str, int] = {}
    current_page = pdf_page_count(front_pdf) + 2

    for exhibit in list(payload.get("exhibits") or []):
        if not isinstance(exhibit, dict):
            continue
        code = str(exhibit.get("code") or "")
        divider_md = base_dir / str(exhibit.get("divider_markdown") or "")
        cover_md = base_dir / str(exhibit.get("cover_markdown") or "")
        source = _resolve_exhibit_source(base_dir, payload, exhibit, code)
        divider_pdf = working_dir / f"Exhibit_{code}_tab_divider.pdf"
        cover_pdf = working_dir / f"Exhibit_{code}_cover_sheet.pdf"
        source_pdf = working_dir / f"Exhibit_{code}_source.pdf"
        packet_pdf = working_dir / f"Exhibit_{code}_packet.pdf"

        convert_markdown_to_binder_pdf(divider_md, divider_pdf, generated_dir=working_dir)
        convert_markdown_to_binder_pdf(cover_md, cover_pdf, generated_dir=working_dir)
        source_to_pdf(source, output_path=source_pdf, label=f"Exhibit {code}", family=str(payload.get("family") or "Exhibit Binder"))

        starts[code] = current_page
        counts[code] = pdf_page_count(divider_pdf) + pdf_page_count(cover_pdf) + pdf_page_count(source_pdf)
        current_page += counts[code]

        build_exhibit_binder(front_pdf=divider_pdf, packet_pdfs=[cover_pdf, source_pdf], output_pdf=packet_pdf)
        packet_paths.append(packet_pdf)

    table_pdf = working_dir / "0001_Table_Of_Exhibits.pdf"
    render_table_of_exhibits_pdf(
        table_pdf,
        exhibit_order=[str(item.get("code") or "") for item in list(payload.get("exhibits") or []) if isinstance(item, dict)],
        exhibit_titles={str(item.get("code") or ""): str(item.get("title") or "") for item in list(payload.get("exhibits") or []) if isinstance(item, dict)},
        starts=starts,
        counts=counts,
        config=court_config,
    )
    result = build_exhibit_binder(front_pdf=front_pdf, table_pdf=table_pdf, packet_pdfs=packet_paths, output_pdf=output_pdf)
    return {
        "manifest_path": str(manifest_path),
        "output_pdf": str(result),
        "front_pdf": str(front_pdf),
        "table_pdf": str(table_pdf),
        "packet_paths": [str(path) for path in packet_paths],
        "exhibit_count": len(packet_paths),
    }


__all__ = ["build_exhibit_binder_from_manifest"]
