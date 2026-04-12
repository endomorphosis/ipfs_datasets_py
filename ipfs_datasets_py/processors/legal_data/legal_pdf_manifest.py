"""Manifest helpers for legal PDF rendering workflows."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .court_pdf_rendering import StateCourtPleadingConfig, build_state_court_filing_packet
from .exhibit_binder_templates import BinderCourtConfig, DEFAULT_BINDER_COURT_CONFIG


def load_json_manifest(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8"))


def _state_court_config_from_manifest(payload: Mapping[str, Any]) -> StateCourtPleadingConfig:
    config_payload = dict(payload.get("config") or {})
    return StateCourtPleadingConfig(
        contact_block_html=str(config_payload.get("contact_block_html") or ""),
        court_name=str(config_payload.get("court_name") or ""),
        state_name=str(config_payload.get("state_name") or ""),
        caption_left_html=str(config_payload.get("caption_left_html") or ""),
        case_number_line=str(config_payload.get("case_number_line") or "Case No. __________________"),
        filed_date=str(config_payload.get("filed_date") or ""),
        signature_doc_keywords=tuple(str(item) for item in list(config_payload.get("signature_doc_keywords") or [])),
        declaration_doc_keywords=tuple(str(item) for item in list(config_payload.get("declaration_doc_keywords") or [])),
    )


def binder_court_config_from_manifest(payload: Mapping[str, Any]) -> BinderCourtConfig:
    config_payload = dict(payload.get("court_config") or payload.get("config") or {})
    default = DEFAULT_BINDER_COURT_CONFIG
    return BinderCourtConfig(
        case_number=str(config_payload.get("case_number") or default.case_number),
        court_name=str(config_payload.get("court_name") or default.court_name),
        state_name=str(config_payload.get("state_name") or default.state_name),
        contact_block_html=str(config_payload.get("contact_block_html") or default.contact_block_html),
        caption_left_html=str(config_payload.get("caption_left_html") or default.caption_left_html),
    )


def build_state_court_filing_packet_from_manifest(path: str | Path) -> dict[str, object]:
    manifest_path = Path(path)
    payload = load_json_manifest(manifest_path)
    base_dir = manifest_path.parent
    md_paths = [base_dir / str(item) for item in list(payload.get("documents") or [])]
    output_dir = base_dir / str(payload.get("output_dir") or "rendered_pdfs")
    packet_output_path = base_dir / str(payload.get("packet_output_path") or "filing_packet.pdf")
    result = build_state_court_filing_packet(md_paths, output_dir, packet_output_path, config=_state_court_config_from_manifest(payload))
    result["manifest_path"] = str(manifest_path)
    return result


__all__ = [
    "binder_court_config_from_manifest",
    "build_state_court_filing_packet_from_manifest",
    "load_json_manifest",
]
