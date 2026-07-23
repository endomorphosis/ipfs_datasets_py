#!/usr/bin/env python3
"""CLI for reusable legal PDF rendering helpers."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import logging
from pathlib import Path
import warnings

import jsonschema
from jsonschema.exceptions import ValidationError

__all__ = ["create_parser", "main"]


_LEGAL_DATA_EXPORTS: dict[str, object] | None = None


def _load_legal_data_exports(*, quiet: bool = False) -> dict[str, object]:
    global _LEGAL_DATA_EXPORTS
    if _LEGAL_DATA_EXPORTS is not None:
        return _LEGAL_DATA_EXPORTS

    def _import_exports() -> dict[str, object]:
        from ipfs_datasets_py.processors.legal_data.court_pdf_rendering import (
            StateCourtPleadingConfig,
            build_state_court_filing_packet,
            render_exhibit_cover_from_markdown,
            render_exhibit_tab_from_markdown,
            render_state_court_markdown_to_pdf,
            render_state_court_pdf_batch,
        )
        from ipfs_datasets_py.processors.legal_data.exhibit_binder_export import (
            build_exhibit_binder,
            convert_markdown_to_binder_pdf,
            eml_to_pdf,
            image_to_pdf,
            markdown_or_text_to_pdf,
            merge_pdfs,
            pdf_page_count,
            render_binder_title_pdf,
            render_family_divider_pdf,
            source_to_pdf,
        )
        from ipfs_datasets_py.processors.legal_data.exhibit_binder_manifest import build_exhibit_binder_from_manifest
        from ipfs_datasets_py.processors.legal_data.full_evidence_binder_manifest import build_full_evidence_binder_from_manifest
        from ipfs_datasets_py.processors.legal_data.legal_pdf_manifest import (
            build_state_court_filing_packet_from_manifest,
            load_json_manifest,
        )
        from ipfs_datasets_py.processors.legal_data.courtstyle_packet_export import (
            build_courtstyle_packet_from_config,
            build_default_courtstyle_packet,
        )
        from ipfs_datasets_py.processors.legal_data.court_ready_binder_index_export import (
            build_default_court_ready_binder_index,
            build_court_ready_binder_index_from_config,
        )
        from ipfs_datasets_py.processors.legal_data.official_form_drafts_export import (
            build_default_official_form_drafts,
            build_official_form_drafts_from_config,
        )
        from ipfs_datasets_py.processors.legal_data.filing_specific_binders_export import (
            build_default_filing_specific_binders,
            build_filing_specific_binders_from_config,
        )

        return {
            "build_exhibit_binder": build_exhibit_binder,
            "build_exhibit_binder_from_manifest": build_exhibit_binder_from_manifest,
            "build_full_evidence_binder_from_manifest": build_full_evidence_binder_from_manifest,
            "build_default_courtstyle_packet": build_default_courtstyle_packet,
            "build_courtstyle_packet_from_config": build_courtstyle_packet_from_config,
            "build_default_court_ready_binder_index": build_default_court_ready_binder_index,
            "build_court_ready_binder_index_from_config": build_court_ready_binder_index_from_config,
            "build_default_official_form_drafts": build_default_official_form_drafts,
            "build_official_form_drafts_from_config": build_official_form_drafts_from_config,
            "build_default_filing_specific_binders": build_default_filing_specific_binders,
            "build_filing_specific_binders_from_config": build_filing_specific_binders_from_config,
            "build_state_court_filing_packet": build_state_court_filing_packet,
            "build_state_court_filing_packet_from_manifest": build_state_court_filing_packet_from_manifest,
            "convert_markdown_to_binder_pdf": convert_markdown_to_binder_pdf,
            "eml_to_pdf": eml_to_pdf,
            "image_to_pdf": image_to_pdf,
            "markdown_or_text_to_pdf": markdown_or_text_to_pdf,
            "merge_pdfs": merge_pdfs,
            "pdf_page_count": pdf_page_count,
            "render_binder_title_pdf": render_binder_title_pdf,
            "render_exhibit_cover_from_markdown": render_exhibit_cover_from_markdown,
            "render_exhibit_tab_from_markdown": render_exhibit_tab_from_markdown,
            "render_family_divider_pdf": render_family_divider_pdf,
            "render_state_court_markdown_to_pdf": render_state_court_markdown_to_pdf,
            "render_state_court_pdf_batch": render_state_court_pdf_batch,
            "source_to_pdf": source_to_pdf,
            "StateCourtPleadingConfig": StateCourtPleadingConfig,
            "load_json_manifest": load_json_manifest,
        }

    if quiet:
        logging.disable(logging.CRITICAL)
        stderr_buffer = io.StringIO()
        stdout_buffer = io.StringIO()
        try:
            with warnings.catch_warnings(), contextlib.redirect_stderr(stderr_buffer), contextlib.redirect_stdout(stdout_buffer):
                warnings.simplefilter("ignore")
                _LEGAL_DATA_EXPORTS = _import_exports()
        finally:
            logging.disable(logging.NOTSET)
    else:
        _LEGAL_DATA_EXPORTS = _import_exports()
    return _LEGAL_DATA_EXPORTS


_SCHEMA_DIR = Path(__file__).resolve().parents[2] / "docs" / "schemas" / "legal_pdf"
_STATE_COURT_PACKET_SCHEMA = _SCHEMA_DIR / "state_court_filing_packet_manifest.schema.json"
_EXHIBIT_BINDER_SCHEMA = _SCHEMA_DIR / "exhibit_binder_manifest.schema.json"
_FULL_EVIDENCE_BINDER_SCHEMA = _SCHEMA_DIR / "full_evidence_binder_manifest.schema.json"


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ipfs-datasets legal-pdf",
        description="Render state-court PDFs, exhibit binder parts, and source conversions.",
    )
    parser.add_argument(
        "--action",
        choices=[
            "validate-manifest",
            "render-state-court",
            "render-state-court-batch",
            "build-court-filing-packet",
            "build-court-filing-packet-from-manifest",
            "build-exhibit-binder-from-manifest",
            "build-full-evidence-binder-from-manifest",
            "build-courtstyle-packet-default",
            "build-court-ready-binder-index-default",
            "build-official-form-drafts-default",
            "build-filing-specific-binders-default",
            "render-exhibit-tab",
            "render-exhibit-cover",
            "render-binder-title",
            "render-family-divider",
            "convert-source",
            "convert-markdown",
            "merge-pdfs",
            "count-pages",
            "build-exhibit-binder",
        ],
        required=True,
    )
    parser.add_argument("--input-path", default="", help="Primary input path for single-file actions.")
    parser.add_argument("--input-paths", nargs="*", default=[], help="Multiple input paths for batch and merge actions.")
    parser.add_argument("--output-path", default="", help="Output file path.")
    parser.add_argument("--output-dir", default="", help="Output directory for batch rendering.")
    parser.add_argument("--packet-output-path", default="", help="Merged output PDF path for build-court-filing-packet.")
    parser.add_argument("--manifest-path", default="", help="JSON manifest path for manifest-driven actions.")
    parser.add_argument("--config-path", default="", help="JSON config path for reusable default builder actions.")
    parser.add_argument("--front-pdf", default="", help="Front sheet PDF for build-exhibit-binder.")
    parser.add_argument("--table-pdf", default="", help="Optional table-of-exhibits PDF for build-exhibit-binder.")
    parser.add_argument("--packet-pdfs", nargs="*", default=[], help="Packet PDFs for build-exhibit-binder.")
    parser.add_argument("--family", default="", help="Family label for divider/source rendering.")
    parser.add_argument("--labels", default="", help="Comma-separated exhibit labels for family divider.")
    parser.add_argument("--label", default="", help="Exhibit/source label.")
    parser.add_argument("--source", default="", help="Logical source description for convert-source.")
    parser.add_argument("--lean-mode", action="store_true", help="Use lean binder title rendering.")
    parser.add_argument("--contact-block", default="", help="HTML contact block for state-court rendering.")
    parser.add_argument("--court-name", default="", help="Court heading for state-court rendering.")
    parser.add_argument("--state-name", default="", help="State heading for state-court rendering.")
    parser.add_argument("--caption-left", default="", help="Left caption block HTML for state-court rendering.")
    parser.add_argument("--case-number-line", default="Case No. __________________", help="Default case number line.")
    parser.add_argument("--filed-date", default="", help="Filed date for signature blocks.")
    parser.add_argument("--signature-doc-keywords", default="motion,memorandum,response,certificate_of_service", help="Comma-separated signature doc stem keywords.")
    parser.add_argument("--declaration-doc-keywords", default="declaration", help="Comma-separated declaration doc stem keywords.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    return parser


def _config_from_args(parsed: argparse.Namespace, *, quiet_imports: bool = False) -> object:
    exports = _load_legal_data_exports(quiet=quiet_imports)
    state_court_pleading_config = exports["StateCourtPleadingConfig"]
    return state_court_pleading_config(
        contact_block_html=str(parsed.contact_block or ""),
        court_name=str(parsed.court_name or ""),
        state_name=str(parsed.state_name or ""),
        caption_left_html=str(parsed.caption_left or ""),
        case_number_line=str(parsed.case_number_line or "Case No. __________________"),
        filed_date=str(parsed.filed_date or ""),
        signature_doc_keywords=tuple(item.strip() for item in str(parsed.signature_doc_keywords or "").split(",") if item.strip()),
        declaration_doc_keywords=tuple(item.strip() for item in str(parsed.declaration_doc_keywords or "").split(",") if item.strip()),
    )


def _emit(payload: dict[str, object], *, as_json: bool) -> int:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")
    return 0


def _validate_manifest(manifest_path: str | Path, *, action: str, quiet_imports: bool = False) -> dict[str, object]:
    manifest_path = Path(manifest_path)
    exports = _load_legal_data_exports(quiet=quiet_imports)
    load_json_manifest = exports["load_json_manifest"]
    payload = load_json_manifest(manifest_path)
    if action in {"build-court-filing-packet-from-manifest", "validate-manifest:state-court"}:
        schema_path = _STATE_COURT_PACKET_SCHEMA
    elif action in {"build-full-evidence-binder-from-manifest", "validate-manifest:full-evidence-binder"}:
        schema_path = _FULL_EVIDENCE_BINDER_SCHEMA
    else:
        schema_path = _EXHIBIT_BINDER_SCHEMA
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    jsonschema.validate(payload, schema)
    return payload


def _format_validation_error(exc: Exception) -> str:
    if not isinstance(exc, ValidationError):
        return str(exc)
    path_parts = [str(part) for part in list(exc.absolute_path or [])]
    path_text = ".".join(path_parts) if path_parts else "<root>"
    return f"{path_text}: {exc.message}"


def main(args: list[str] | None = None) -> int:
    parser = create_parser()
    parsed = parser.parse_args(args)

    action = str(parsed.action)
    quiet_imports = bool(parsed.json)
    if action == "validate-manifest":
        if not parsed.manifest_path:
            parser.error("--manifest-path is required.")
        exports = _load_legal_data_exports(quiet=bool(parsed.json))
        payload = exports["load_json_manifest"](parsed.manifest_path)
        manifest_type = "state-court"
        if "families" in payload:
            manifest_type = "full-evidence-binder"
        elif "exhibits" in payload and "documents" not in payload:
            manifest_type = "exhibit-binder"
        if manifest_type == "state-court":
            validate_action = "validate-manifest:state-court"
        elif manifest_type == "full-evidence-binder":
            validate_action = "validate-manifest:full-evidence-binder"
        else:
            validate_action = "validate-manifest:exhibit-binder"
        try:
            _validate_manifest(parsed.manifest_path, action=validate_action, quiet_imports=quiet_imports)
        except Exception as exc:
            parser.error(f"Manifest validation failed: {_format_validation_error(exc)}")
        return _emit(
            {
                "action": action,
                "manifest_path": str(parsed.manifest_path),
                "manifest_type": manifest_type,
                "valid": True,
            },
            as_json=bool(parsed.json),
        )

    if action == "render-state-court":
        if not parsed.input_path or not parsed.output_path:
            parser.error("--input-path and --output-path are required.")
        path = _load_legal_data_exports(quiet=quiet_imports)["render_state_court_markdown_to_pdf"](parsed.input_path, parsed.output_path, config=_config_from_args(parsed, quiet_imports=quiet_imports))
        return _emit({"action": action, "output_path": str(path)}, as_json=bool(parsed.json))

    if action == "render-state-court-batch":
        if not parsed.input_paths or not parsed.output_dir:
            parser.error("--input-paths and --output-dir are required.")
        outputs = _load_legal_data_exports(quiet=quiet_imports)["render_state_court_pdf_batch"](parsed.input_paths, parsed.output_dir, config=_config_from_args(parsed, quiet_imports=quiet_imports))
        return _emit({"action": action, "output_paths": [str(path) for path in outputs]}, as_json=bool(parsed.json))

    if action == "build-court-filing-packet":
        if not parsed.input_paths or not parsed.output_dir or not parsed.packet_output_path:
            parser.error("--input-paths, --output-dir, and --packet-output-path are required.")
        payload = _load_legal_data_exports(quiet=quiet_imports)["build_state_court_filing_packet"](
            parsed.input_paths,
            parsed.output_dir,
            parsed.packet_output_path,
            config=_config_from_args(parsed, quiet_imports=quiet_imports),
        )
        return _emit({"action": action, **payload}, as_json=bool(parsed.json))

    if action == "build-court-filing-packet-from-manifest":
        if not parsed.manifest_path:
            parser.error("--manifest-path is required.")
        try:
            _validate_manifest(parsed.manifest_path, action=action, quiet_imports=quiet_imports)
        except Exception as exc:
            parser.error(f"Manifest validation failed: {_format_validation_error(exc)}")
        payload = _load_legal_data_exports(quiet=quiet_imports)["build_state_court_filing_packet_from_manifest"](parsed.manifest_path)
        return _emit({"action": action, **payload}, as_json=bool(parsed.json))

    if action == "build-exhibit-binder-from-manifest":
        if not parsed.manifest_path:
            parser.error("--manifest-path is required.")
        try:
            _validate_manifest(parsed.manifest_path, action=action, quiet_imports=quiet_imports)
        except Exception as exc:
            parser.error(f"Manifest validation failed: {_format_validation_error(exc)}")
        payload = _load_legal_data_exports(quiet=quiet_imports)["build_exhibit_binder_from_manifest"](parsed.manifest_path)
        return _emit({"action": action, **payload}, as_json=bool(parsed.json))

    if action == "build-full-evidence-binder-from-manifest":
        if not parsed.manifest_path:
            parser.error("--manifest-path is required.")
        try:
            _validate_manifest(parsed.manifest_path, action=action, quiet_imports=quiet_imports)
        except Exception as exc:
            parser.error(f"Manifest validation failed: {_format_validation_error(exc)}")
        payload = _load_legal_data_exports(quiet=quiet_imports)["build_full_evidence_binder_from_manifest"](parsed.manifest_path, lean_mode=bool(parsed.lean_mode))
        return _emit({"action": action, **payload}, as_json=bool(parsed.json))

    if action == "build-courtstyle-packet-default":
        if parsed.config_path:
            payload = _load_legal_data_exports(quiet=quiet_imports)["build_courtstyle_packet_from_config"](parsed.config_path)
            return _emit({"action": action, **payload}, as_json=bool(parsed.json))
        _load_legal_data_exports(quiet=quiet_imports)["build_default_courtstyle_packet"]()
        return _emit({"action": action, "status": "ok"}, as_json=bool(parsed.json))

    if action == "build-court-ready-binder-index-default":
        if parsed.config_path:
            payload = _load_legal_data_exports(quiet=quiet_imports)["build_court_ready_binder_index_from_config"](parsed.config_path)
            return _emit({"action": action, **payload}, as_json=bool(parsed.json))
        output_path = _load_legal_data_exports(quiet=quiet_imports)["build_default_court_ready_binder_index"]()
        return _emit({"action": action, "output_path": str(output_path)}, as_json=bool(parsed.json))

    if action == "build-official-form-drafts-default":
        if parsed.config_path:
            payload = _load_legal_data_exports(quiet=quiet_imports)["build_official_form_drafts_from_config"](parsed.config_path)
            return _emit({"action": action, **payload}, as_json=bool(parsed.json))
        output_paths = _load_legal_data_exports(quiet=quiet_imports)["build_default_official_form_drafts"]()
        return _emit({"action": action, "output_paths": [str(path) for path in list(output_paths or [])]}, as_json=bool(parsed.json))

    if action == "build-filing-specific-binders-default":
        if parsed.config_path:
            payload = _load_legal_data_exports(quiet=quiet_imports)["build_filing_specific_binders_from_config"](parsed.config_path)
            return _emit({"action": action, **payload}, as_json=bool(parsed.json))
        output_paths = _load_legal_data_exports(quiet=quiet_imports)["build_default_filing_specific_binders"]()
        return _emit({"action": action, "output_paths": [str(path) for path in list(output_paths or [])]}, as_json=bool(parsed.json))

    if action == "render-exhibit-tab":
        path = _load_legal_data_exports(quiet=quiet_imports)["render_exhibit_tab_from_markdown"](parsed.input_path, parsed.output_path)
        return _emit({"action": action, "output_path": str(path)}, as_json=bool(parsed.json))

    if action == "render-exhibit-cover":
        path = _load_legal_data_exports(quiet=quiet_imports)["render_exhibit_cover_from_markdown"](parsed.input_path, parsed.output_path)
        return _emit({"action": action, "output_path": str(path)}, as_json=bool(parsed.json))

    if action == "render-binder-title":
        path = _load_legal_data_exports(quiet=quiet_imports)["render_binder_title_pdf"](parsed.output_path, lean_mode=bool(parsed.lean_mode))
        return _emit({"action": action, "output_path": str(path)}, as_json=bool(parsed.json))

    if action == "render-family-divider":
        labels = [item.strip() for item in str(parsed.labels or "").split(",") if item.strip()]
        path = _load_legal_data_exports(quiet=quiet_imports)["render_family_divider_pdf"](parsed.output_path, str(parsed.family or ""), labels)
        return _emit({"action": action, "output_path": str(path), "labels": labels}, as_json=bool(parsed.json))

    if action == "convert-source":
        source = str(parsed.source or parsed.input_path or "")
        if not source or not parsed.output_path or not parsed.label or not parsed.family:
            parser.error("--source or --input-path, --output-path, --label, and --family are required.")
        path = _load_legal_data_exports(quiet=quiet_imports)["source_to_pdf"](source, output_path=parsed.output_path, label=parsed.label, family=parsed.family, lean_mode=bool(parsed.lean_mode))
        return _emit({"action": action, "output_path": str(path)}, as_json=bool(parsed.json))

    if action == "convert-markdown":
        if not parsed.input_path or not parsed.output_path:
            parser.error("--input-path and --output-path are required.")
        path = _load_legal_data_exports(quiet=quiet_imports)["convert_markdown_to_binder_pdf"](parsed.input_path, parsed.output_path, generated_dir=Path(parsed.output_path).parent)
        return _emit({"action": action, "output_path": str(path)}, as_json=bool(parsed.json))

    if action == "merge-pdfs":
        if not parsed.input_paths or not parsed.output_path:
            parser.error("--input-paths and --output-path are required.")
        path = _load_legal_data_exports(quiet=quiet_imports)["merge_pdfs"](parsed.output_path, parsed.input_paths)
        return _emit({"action": action, "output_path": str(path)}, as_json=bool(parsed.json))

    if action == "count-pages":
        if not parsed.input_path:
            parser.error("--input-path is required.")
        return _emit({"action": action, "input_path": str(parsed.input_path), "page_count": _load_legal_data_exports(quiet=quiet_imports)["pdf_page_count"](parsed.input_path)}, as_json=bool(parsed.json))

    if action == "build-exhibit-binder":
        if not parsed.front_pdf or not parsed.output_path or not parsed.packet_pdfs:
            parser.error("--front-pdf, --packet-pdfs, and --output-path are required.")
        path = _load_legal_data_exports(quiet=quiet_imports)["build_exhibit_binder"](front_pdf=parsed.front_pdf, table_pdf=(parsed.table_pdf or None), packet_pdfs=parsed.packet_pdfs, output_pdf=parsed.output_path)
        return _emit({"action": action, "output_path": str(path)}, as_json=bool(parsed.json))

    parser.error(f"Unsupported action: {action}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
