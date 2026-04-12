#!/usr/bin/env python3
"""Docket dataset import CLI.

Packaged bundle read helpers:
- `--packaged-action summary|inspect|dashboard|report|dashboard-report|recap-fetch|recap-preflight` is the preferred scripted entrypoint.
- `--summary-only` reads the lightweight manifest-driven packaged summary view.
- `--inspect-packaged` reads the packaged inspection payload.
- `--load-packaged-report` reads the archived `inspection_report` artifact.
- `--operator-dashboard` reads the combined packaged operator dashboard payload.
- `--load-operator-dashboard-report` reads the archived `operator_dashboard_report` artifact.
- `--citation-source-audit` reports which citations resolved to legal source records.
- `--fields` applies to the active packaged read mode.

Examples:
- `... --input-type packaged --input-path /path/to/bundle_manifest.json --packaged-action summary --json`
- `... --input-type packaged --input-path /path/to/bundle_manifest.json --packaged-action inspect --fields latest_routing_reason,top_routing_citation --json`
- `... --input-type packaged --input-path /path/to/bundle_manifest.json --packaged-action report --report-format parsed --fields latest_routing_reason`
- `... --input-type packaged --input-path /path/to/bundle_manifest.json --packaged-action dashboard --fields dataset_id,source --json`
- `... --input-type packaged --input-path /path/to/bundle_manifest.json --packaged-action dashboard-report --report-format text`
- `... --input-type packaged --input-path /path/to/bundle_manifest.json --packaged-action recap-fetch --json`
- `... --input-type packaged --input-path /path/to/bundle_manifest.json --packaged-action recap-preflight --json`
- `... --input-type packaged --input-path /path/to/bundle_manifest.json --citation-source-audit --json`
"""

from __future__ import annotations

import asyncio
import argparse
import json
from pathlib import Path
import zipfile

from ipfs_datasets_py.processors.legal_data import (
    CourtListenerIngestionError,
    audit_docket_dataset_citation_sources,
    audit_packaged_docket_citation_sources,
    build_packaged_docket_recap_fetch_preflight,
    DocketDatasetBuilder,
    DocketDatasetObject,
    DocketDatasetPackager,
    enrich_packaged_docket_with_tactician,
    fetch_courtlistener_docket,
    get_courtlistener_recap_fetch_request,
    get_packaged_docket_operator_dashboard,
    load_packaged_docket_dataset,
    load_packaged_docket_operator_dashboard_report,
    load_packaged_docket_summary_view,
    package_docket_dataset,
    package_courtlistener_fetch_cache,
    render_packaged_docket_operator_dashboard,
    submit_packaged_docket_recap_fetch_requests,
    summarize_docket_dataset,
)
from ipfs_datasets_py.processors.legal_scrapers import recover_citation_audit_feedback

__all__ = ["create_parser", "main"]


def _classify_courtlistener_error(message: str) -> tuple[str, dict[str, object]]:
    normalized = str(message or "").strip()
    lowered = normalized.lower()
    if "pacerloginexception" in lowered and "nextgencso cookie" in lowered:
        return (
            "pacer_login_failed",
            {
                "provider": "CourtListener RECAP Fetch",
                "upstream_system": "PACER",
                "likely_causes": [
                    "invalid_pacer_username_or_password",
                    "pacer_nextgen_login_challenge",
                    "pacer_mfa_or_account_lock",
                ],
                "recommended_next_steps": [
                    "verify_pacer_credentials_directly_in_pacer",
                    "confirm_the_account_can_complete_a_nextgen_login_without_additional_browser_prompts",
                    "temporarily_disable_pacer_mfa_if_courtlistener_recap_fetch_is_blocked_by_nextgen_cookie_failures",
                    "rotate_the_pacer_password_or_generate_fresh_credentials_if_needed",
                    "retry_the_same_recap_fetch_submission_after_the_pacer_login_is_confirmed",
                ],
            },
        )
    if "throttled" in lowered or "too many requests" in lowered or "429" in lowered:
        return (
            "courtlistener_throttled",
            {
                "provider": "CourtListener",
                "recommended_next_steps": [
                    "wait_for_the_courtlistener_throttle_window_to_clear",
                    "retry_the_same_request_with_backoff",
                ],
            },
        )
    return ("courtlistener_ingestion_error", {})


def _emit_cli_error(parsed: argparse.Namespace, *, message: str, error_type: str = "runtime_error", details: dict[str, object] | None = None) -> int:
    payload: dict[str, object] = {
        "status": "error",
        "error_type": str(error_type or "runtime_error"),
        "message": str(message or ""),
    }
    if details:
        payload["details"] = dict(details)
    if parsed.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"{error_type}: {message}")
        if details:
            for key, value in details.items():
                print(f"{key}: {value}")
    return 1


_PACKAGED_READ_FLAG_TO_MODE = {
    "summary_only": "summary",
    "inspect_packaged": "inspection",
    "operator_dashboard": "dashboard",
    "load_packaged_report": "report",
    "load_operator_dashboard_report": "dashboard_report",
    "submit_packaged_recap_fetch": "recap_fetch",
    "packaged_recap_preflight": "recap_preflight",
}

_PACKAGED_ACTION_TO_MODE = {
    "summary": "summary",
    "inspect": "inspection",
    "dashboard": "dashboard",
    "report": "report",
    "dashboard-report": "dashboard_report",
    "recap-fetch": "recap_fetch",
    "recap-preflight": "recap_preflight",
}

_PACKAGED_MODE_TO_FIELD_FLAG = {
    "summary": "summary-fields",
    "inspection": "inspection-fields",
    "dashboard": "dashboard-fields",
    "report": "report-fields",
    "dashboard_report": "report-fields",
    "recap_fetch": "recap-fetch-fields",
    "recap_preflight": "recap-fetch-fields",
}

def _create_bundle_zip(bundle_dir: str | Path) -> str:
    bundle_path = Path(bundle_dir)
    zip_path = bundle_path.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(bundle_path.rglob("*")):
            if not path.is_file():
                continue
            archive.write(path, arcname=str(path.relative_to(bundle_path.parent)))
    return str(zip_path)


def _print_packaged_inspection(inspection: dict[str, object]) -> None:
    print("Packaged Inspection")
    for key, value in inspection.items():
        if isinstance(value, list):
            rendered = ", ".join(str(item) for item in value)
        else:
            rendered = value
        print(f"{key}: {rendered}")


def _write_text_output(path: str | Path, content: str) -> str:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return str(output_path)


def _stringify_packaged_report(report_payload: object, report_format: str) -> str:
    normalized_format = str(report_format or "").strip().lower()
    if normalized_format in {"json", "markdown", "text"}:
        return str(report_payload or "")
    if isinstance(report_payload, dict):
        lines: list[str] = []
        for key, value in report_payload.items():
            if isinstance(value, list):
                rendered = ", ".join(str(item) for item in value)
            else:
                rendered = value
            lines.append(f"{key}: {rendered}")
        return "\n".join(lines)
    return json.dumps(report_payload, indent=2, ensure_ascii=False)


def _parse_summary_fields_arg(value: str | None) -> list[str]:
    fields: list[str] = []
    for item in str(value or "").split(","):
        field = str(item).strip()
        if field and field not in fields:
            fields.append(field)
    return fields


def _filter_mapping_fields(payload: dict[str, object], fields: list[str]) -> dict[str, object]:
    if not fields:
        return dict(payload)
    return {field: payload[field] for field in fields if field in payload}


def _build_citation_source_audit_from_dataset(
    dataset: object,
    *,
    include_eu_audit: bool = True,
    eu_language: str | None = None,
    eu_max_documents: int = 120,
) -> dict[str, object]:
    if isinstance(dataset, DocketDatasetObject):
        return audit_docket_dataset_citation_sources(
            dataset,
            include_eu_audit=include_eu_audit,
            eu_language=eu_language,
            eu_max_documents=eu_max_documents,
        )
    if isinstance(dataset, dict):
        return audit_docket_dataset_citation_sources(
            DocketDatasetObject.from_dict(dataset),
            include_eu_audit=include_eu_audit,
            eu_language=eu_language,
            eu_max_documents=eu_max_documents,
        )
    raise TypeError("citation source audit requires a docket dataset object or dictionary payload")


def _recover_citation_sources_from_audit(
    audit_payload: dict[str, object],
    *,
    publish_to_hf: bool,
    hf_token: str | None,
    max_candidates: int,
    archive_top_k: int,
) -> dict[str, object]:
    return asyncio.run(
        recover_citation_audit_feedback(
            audit_payload,
            publish_to_hf=publish_to_hf,
            hf_token=hf_token,
            max_candidates=max_candidates,
            archive_top_k=archive_top_k,
        )
    )


def _packaged_read_modes(parsed: argparse.Namespace) -> set[str]:
    modes: set[str] = set()
    action_mode = _PACKAGED_ACTION_TO_MODE.get(str(getattr(parsed, "packaged_action", "") or "").strip().lower())
    if action_mode:
        modes.add(action_mode)
    for flag_name, mode_name in _PACKAGED_READ_FLAG_TO_MODE.items():
        if bool(getattr(parsed, flag_name, False)):
            modes.add(mode_name)
    return modes


def _is_packaged_read_only(parsed: argparse.Namespace, packaged_modes: set[str]) -> bool:
    return (
        parsed.input_type == "packaged"
        and not parsed.enrich_query
        and not parsed.package_dir
        and not parsed.parquet_dir
        and not parsed.courtlistener_cache_package_dir
        and (
            packaged_modes
            or bool(parsed.export_packaged_report)
            or bool(parsed.export_operator_dashboard_report)
        )
    )


def _resolve_packaged_field_selections(
    parsed: argparse.Namespace,
    *,
    summary_fields: list[str],
    inspection_fields: list[str],
    dashboard_fields: list[str],
    report_fields: list[str],
    recap_fetch_fields: list[str],
    generic_fields: list[str],
    packaged_modes: set[str],
    parser: argparse.ArgumentParser,
) -> dict[str, list[str]]:
    if summary_fields and "summary" not in packaged_modes:
        parser.error("--summary-fields is only valid with --summary-only.")
    if inspection_fields and "inspection" not in packaged_modes:
        parser.error("--inspection-fields is only valid with --inspect-packaged.")
    if dashboard_fields and "dashboard" not in packaged_modes:
        parser.error("--dashboard-fields is only valid with --operator-dashboard.")
    if report_fields and not ({"report", "dashboard_report"} & packaged_modes):
        parser.error("--report-fields is only valid with --load-packaged-report or --load-operator-dashboard-report.")
    if recap_fetch_fields and "recap_fetch" not in packaged_modes:
        if "recap_preflight" not in packaged_modes:
            parser.error("--recap-fetch-fields is only valid with --submit-packaged-recap-fetch or --packaged-recap-preflight.")
    if generic_fields and not packaged_modes and not bool(getattr(parsed, "citation_source_audit", False)) and not bool(getattr(parsed, "recover_citation_sources", False)) and not bool(getattr(parsed, "recap_fetch_request_id", None)):
        parser.error("--fields is only valid with packaged read modes, --citation-source-audit, --recover-citation-sources, or --recap-fetch-request-id.")

    specific_fields_by_mode = {
        "summary": summary_fields,
        "inspection": inspection_fields,
        "dashboard": dashboard_fields,
        "report": report_fields,
        "dashboard_report": report_fields,
        "recap_fetch": recap_fetch_fields,
        "recap_preflight": recap_fetch_fields,
    }
    for mode_name, field_values in specific_fields_by_mode.items():
        if generic_fields and field_values and mode_name in packaged_modes:
            parser.error(f"Use either --fields or --{_PACKAGED_MODE_TO_FIELD_FLAG[mode_name]}, not both.")

    resolved = {
        "summary": generic_fields if ("summary" in packaged_modes and generic_fields) else summary_fields,
        "inspection": generic_fields if ("inspection" in packaged_modes and generic_fields) else inspection_fields,
        "dashboard": generic_fields if ("dashboard" in packaged_modes and generic_fields) else dashboard_fields,
        "report": generic_fields if ("report" in packaged_modes and generic_fields) else report_fields,
        "dashboard_report": generic_fields if ("dashboard_report" in packaged_modes and generic_fields) else report_fields,
        "recap_fetch": generic_fields if ("recap_fetch" in packaged_modes and generic_fields) else recap_fetch_fields,
        "recap_preflight": generic_fields if ("recap_preflight" in packaged_modes and generic_fields) else recap_fetch_fields,
    }
    if (resolved["report"] or resolved["dashboard_report"]) and str(parsed.report_format or "").strip().lower() not in {"parsed", "row"}:
        parser.error("--report-fields/--fields for packaged reports requires --report-format parsed or row.")
    return resolved


def _apply_packaged_action_alias(parsed: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    action = str(getattr(parsed, "packaged_action", "") or "").strip().lower()
    if not action:
        return
    mode_name = _PACKAGED_ACTION_TO_MODE[action]
    for flag_name, candidate_mode in _PACKAGED_READ_FLAG_TO_MODE.items():
        if candidate_mode != mode_name and bool(getattr(parsed, flag_name, False)):
            parser.error("--packaged-action cannot be combined with a different packaged read mode flag.")
    if action == "summary":
        parsed.summary_only = True
    elif action == "inspect":
        parsed.inspect_packaged = True
    elif action == "dashboard":
        parsed.operator_dashboard = True
    elif action == "report":
        parsed.load_packaged_report = True
    elif action == "dashboard-report":
        parsed.load_operator_dashboard_report = True
    elif action == "recap-fetch":
        parsed.submit_packaged_recap_fetch = True
    elif action == "recap-preflight":
        parsed.packaged_recap_preflight = True


def _build_packaged_read_only_summary(packager: DocketDatasetPackager, manifest_path: str | Path) -> dict[str, object]:
    summary_view = packager.load_summary_view(manifest_path)
    manifest = dict(summary_view.get("package_manifest") or {})
    manifest_summary = dict(manifest.get("summary") or {})
    provenance = dict(manifest.get("provenance") or {})
    latest_routing = dict(provenance.get("latest_proof_packet_routing_explanation") or {})
    return {
        "dataset_id": str(summary_view.get("dataset_id") or manifest.get("dataset_id") or ""),
        "docket_id": str(summary_view.get("docket_id") or manifest.get("docket_id") or ""),
        "case_name": str(summary_view.get("case_name") or manifest.get("case_name") or ""),
        "court": str(summary_view.get("court") or manifest.get("court") or ""),
        "document_count": int(summary_view.get("document_count") or 0),
        "attachment_count": int(summary_view.get("attachment_count") or 0),
        "knowledge_graph_entity_count": int(manifest_summary.get("knowledge_graph_entity_count") or 0),
        "knowledge_graph_relationship_count": int(manifest_summary.get("knowledge_graph_relationship_count") or 0),
        "proof_tactician_plan_count": int(manifest_summary.get("tactician_plan_count") or 0),
        "proof_packet_count": int(manifest_summary.get("proof_packet_count") or 0),
        "proof_store_count": int(manifest_summary.get("proof_store_count") or 0),
        "has_latest_proof_packet_routing_explanation": bool(
            provenance.get("has_latest_proof_packet_routing_explanation")
        ),
        "latest_proof_packet_routing_reason": str(latest_routing.get("routing_reason") or ""),
    }


def _build_recap_fetch_status_summary(parsed: argparse.Namespace) -> dict[str, object]:
    return {
        "request_id": str(parsed.recap_fetch_request_id or ""),
        "input_type": str(parsed.input_type or ""),
        "input_path": str(parsed.input_path or ""),
    }


def _latest_routing_explanation_from_dataset_dict(dataset_payload: dict[str, object]) -> dict[str, object]:
    metadata = dict(dataset_payload.get("metadata") or {})
    proof_assistant = dict(dataset_payload.get("proof_assistant") or {})
    proof_metadata = dict(proof_assistant.get("metadata") or {})
    attached_packet = dict(dataset_payload.get("attached_proof_assistant_packet") or {})
    return dict(
        metadata.get("latest_proof_packet_routing_explanation")
        or proof_metadata.get("latest_proof_packet_routing_explanation")
        or attached_packet.get("routing_explanation")
        or {}
    )


def _build_packaged_summary_from_dataset_dict(dataset_payload: dict[str, object]) -> dict[str, object]:
    summary = summarize_docket_dataset(dataset_payload)
    metadata = dict(dataset_payload.get("metadata") or {})
    eu_audit = dict(metadata.get("eu_citation_audit") or {})
    if not eu_audit:
        eu_audit = dict((metadata.get("citation_source_audit") or {}).get("eu_citation_audit") or {})
    return {
        "dataset_id": str(dataset_payload.get("dataset_id") or summary.get("dataset_id") or ""),
        "docket_id": str(dataset_payload.get("docket_id") or summary.get("docket_id") or ""),
        "case_name": str(dataset_payload.get("case_name") or ""),
        "court": str(dataset_payload.get("court") or ""),
        "document_count": int(summary.get("document_count") or len(list(dataset_payload.get("documents") or []))),
        "attachment_count": int(summary.get("attachment_count") or 0),
        "knowledge_graph_entity_count": int(summary.get("knowledge_graph_entity_count") or 0),
        "knowledge_graph_relationship_count": int(summary.get("knowledge_graph_relationship_count") or 0),
        "proof_tactician_plan_count": int(summary.get("proof_tactician_plan_count") or 0),
        "proof_packet_count": int(summary.get("proof_packet_count") or 0),
        "proof_store_count": int(summary.get("proof_store_count") or 0),
        "eu_citation_count": int(eu_audit.get("citation_count") or 0),
        "eu_unique_citation_count": int(eu_audit.get("unique_citation_count") or 0),
        "eu_documents_with_citations": int(eu_audit.get("documents_with_citations") or 0),
        "has_latest_proof_packet_routing_explanation": bool(
            summary.get("has_latest_proof_packet_routing_explanation")
        ),
        "latest_proof_packet_routing_reason": str(
            summary.get("latest_proof_packet_routing_reason") or ""
        ),
    }


def _build_packaged_inspection_from_dataset_dict(dataset_payload: dict[str, object]) -> dict[str, object]:
    summary = summarize_docket_dataset(dataset_payload)
    metadata = dict(dataset_payload.get("metadata") or {})
    eu_audit = dict(metadata.get("eu_citation_audit") or {})
    if not eu_audit:
        eu_audit = dict((metadata.get("citation_source_audit") or {}).get("eu_citation_audit") or {})
    latest_routing = _latest_routing_explanation_from_dataset_dict(dataset_payload)
    routing_evidence = list(latest_routing.get("routing_evidence") or [])
    top_routing = dict((routing_evidence or [{}])[0])
    return {
        "dataset_id": str(dataset_payload.get("dataset_id") or summary.get("dataset_id") or ""),
        "docket_id": str(dataset_payload.get("docket_id") or summary.get("docket_id") or ""),
        "case_name": str(dataset_payload.get("case_name") or ""),
        "court": str(dataset_payload.get("court") or ""),
        "document_count": int(summary.get("document_count") or len(list(dataset_payload.get("documents") or []))),
        "attachment_count": int(summary.get("attachment_count") or 0),
        "eu_citation_count": int(eu_audit.get("citation_count") or 0),
        "eu_unique_citation_count": int(eu_audit.get("unique_citation_count") or 0),
        "eu_documents_with_citations": int(eu_audit.get("documents_with_citations") or 0),
        "latest_proof_packet_id": str(
            dict(dataset_payload.get("metadata") or {}).get("latest_proof_packet_id")
            or dict(dataset_payload.get("proof_assistant") or {}).get("metadata", {}).get("latest_proof_packet_id")
            or ""
        ),
        "latest_proof_packet_version": int(
            dict(dataset_payload.get("metadata") or {}).get("latest_proof_packet_version")
            or dict(dataset_payload.get("proof_assistant") or {}).get("metadata", {}).get("latest_proof_packet_version")
            or 0
        ),
        "latest_routing_reason": str(latest_routing.get("routing_reason") or ""),
        "preferred_corpus_priority": list(latest_routing.get("preferred_corpus_priority") or []),
        "preferred_state_codes": list(latest_routing.get("preferred_state_codes") or []),
        "routing_evidence_count": len(routing_evidence),
        "top_routing_citation": str(top_routing.get("citation_text") or ""),
        "top_routing_source_url": str(top_routing.get("source_url") or ""),
        "routing_provenance_piece_present": False,
        "routing_provenance": {},
    }


def _build_loaded_report_from_dataset_dict(
    packager: DocketDatasetPackager,
    dataset_payload: dict[str, object],
    report_format: str,
) -> object:
    inspection = _build_packaged_inspection_from_dataset_dict(dataset_payload)
    normalized_format = str(report_format or "parsed").strip().lower()
    if normalized_format in {"parsed", "dict", "inspection"}:
        return inspection
    if normalized_format == "row":
        return {
            "report_json": json.dumps(inspection, indent=2, ensure_ascii=False),
            "report_text": packager.render_packaged_inspection_report_from_inspection(inspection, report_format="text"),
            "report_markdown": packager.render_packaged_inspection_report_from_inspection(inspection, report_format="markdown"),
            "inspection": inspection,
        }
    return packager.render_packaged_inspection_report_from_inspection(
        inspection,
        report_format=report_format,
    )


def _build_operator_dashboard_from_dataset_dict(
    packager: DocketDatasetPackager,
    dataset_payload: dict[str, object],
) -> dict[str, object]:
    summary_view = _build_packaged_summary_from_dataset_dict(dataset_payload)
    inspection = _build_packaged_inspection_from_dataset_dict(dataset_payload)
    proof_assistant = dict(dataset_payload.get("proof_assistant") or {})
    proof_metadata = dict(proof_assistant.get("metadata") or {})
    revalidation_runs = list(proof_assistant.get("revalidation_runs") or [])
    latest_run = dict((revalidation_runs or [{}])[-1])
    report_text = str(dataset_payload.get("proof_revalidation_report") or "")
    if not report_text:
        report_text = "No proof revalidation report available."
    return {
        "dataset_id": summary_view.get("dataset_id") or inspection.get("dataset_id") or "",
        "docket_id": summary_view.get("docket_id") or inspection.get("docket_id") or "",
        "case_name": summary_view.get("case_name") or inspection.get("case_name") or "",
        "court": summary_view.get("court") or inspection.get("court") or "",
        "inspection": inspection,
        "proof_revalidation_report": {
            "report_text": report_text,
        },
        "proof_revalidation_snapshot": {
            "source": "enriched_dataset_operator_dashboard_snapshot",
            "current_status": {
                "review_required_work_item_count": int(proof_metadata.get("review_required_work_item_count") or 0),
                "high_priority_revalidation_count": int(proof_metadata.get("high_priority_revalidation_count") or 0),
                "queue_count": int(proof_metadata.get("review_required_work_item_count") or 0),
                "latest_run_available": bool(revalidation_runs),
            },
            "latest_run_summary": {
                "run_id": str(latest_run.get("run_id") or ""),
                "best_terminal_source_type": str(latest_run.get("best_terminal_source_type") or ""),
                "best_terminal_support_strength": str(latest_run.get("best_terminal_support_strength") or ""),
                "attached_packet_count": int(latest_run.get("attached_packet_count") or 0),
            },
            "next_queue_item_summary": {},
            "queue": [],
            "runs": {
                "run_count": len(revalidation_runs),
                "total_run_count": len(revalidation_runs),
                "latest_run_id": str(latest_run.get("run_id") or ""),
                "runs": revalidation_runs,
            },
        },
        "summary": {
            **summary_view,
            "review_required_work_item_count": int(proof_metadata.get("review_required_work_item_count") or 0),
            "high_priority_revalidation_count": int(proof_metadata.get("high_priority_revalidation_count") or 0),
            "revalidation_run_count": len(revalidation_runs),
        },
        "source": "enriched_dataset_operator_dashboard",
    }


def _build_loaded_operator_dashboard_report_from_dataset_dict(
    packager: DocketDatasetPackager,
    dataset_payload: dict[str, object],
    report_format: str,
) -> object:
    dashboard = _build_operator_dashboard_from_dataset_dict(packager, dataset_payload)
    normalized_format = str(report_format or "parsed").strip().lower()
    if normalized_format in {"parsed", "dict", "dashboard"}:
        return dashboard
    if normalized_format == "row":
        return {
            "report_json": json.dumps(dashboard, indent=2, ensure_ascii=False),
            "report_text": render_packaged_docket_operator_dashboard(dashboard, report_format="text"),
            "report_markdown": render_packaged_docket_operator_dashboard(dashboard, report_format="markdown"),
            "dashboard": dashboard,
        }
    return render_packaged_docket_operator_dashboard(
        dashboard,
        report_format=report_format,
    )


def _resolve_packaged_summary_view(
    parsed: argparse.Namespace,
    dataset: object,
    *,
    enriched_packaged_read: bool,
) -> dict[str, object]:
    if enriched_packaged_read and isinstance(dataset, dict):
        return _build_packaged_summary_from_dataset_dict(dataset)
    return load_packaged_docket_summary_view(parsed.input_path)


def _resolve_packaged_inspection_payload(
    parsed: argparse.Namespace,
    packager: DocketDatasetPackager,
    dataset: object,
    *,
    enriched_packaged_read: bool,
) -> dict[str, object]:
    if enriched_packaged_read and isinstance(dataset, dict):
        return _build_packaged_inspection_from_dataset_dict(dataset)
    return dict(packager.inspect_packaged_bundle(parsed.input_path))


def _resolve_operator_dashboard_payload(
    parsed: argparse.Namespace,
    packager: DocketDatasetPackager,
    dataset: object,
    *,
    enriched_packaged_read: bool,
) -> dict[str, object]:
    if enriched_packaged_read and isinstance(dataset, dict):
        return _build_operator_dashboard_from_dataset_dict(packager, dataset)
    return dict(get_packaged_docket_operator_dashboard(parsed.input_path))


def _resolve_loaded_packaged_report(
    parsed: argparse.Namespace,
    packager: DocketDatasetPackager,
    dataset: object,
    *,
    enriched_packaged_read: bool,
) -> object:
    if enriched_packaged_read and isinstance(dataset, dict):
        return _build_loaded_report_from_dataset_dict(
            packager,
            dataset,
            parsed.report_format,
        )
    return packager.load_inspection_report(
        parsed.input_path,
        report_format=parsed.report_format,
    )


def _resolve_loaded_operator_dashboard_report(
    parsed: argparse.Namespace,
    packager: DocketDatasetPackager,
    dataset: object,
    *,
    enriched_packaged_read: bool,
) -> object:
    if enriched_packaged_read and isinstance(dataset, dict):
        return _build_loaded_operator_dashboard_report_from_dataset_dict(
            packager,
            dataset,
            parsed.report_format,
        )
    return load_packaged_docket_operator_dashboard_report(
        parsed.input_path,
        report_format=parsed.report_format,
    )


def _handle_packaged_read_outputs(
    parsed: argparse.Namespace,
    *,
    payload: dict[str, object],
    dataset: object,
    packager: DocketDatasetPackager,
    active_summary_fields: list[str],
    active_inspection_fields: list[str],
    active_dashboard_fields: list[str],
    active_report_fields: list[str],
    active_recap_fetch_fields: list[str],
) -> None:
    enriched_packaged_read = (
        parsed.input_type == "packaged"
        and bool(parsed.enrich_query)
        and isinstance(dataset, dict)
    )

    if parsed.summary_only:
        payload["packaged_summary_view"] = _filter_mapping_fields(
            _resolve_packaged_summary_view(
                parsed,
                dataset,
                enriched_packaged_read=enriched_packaged_read,
            ),
            active_summary_fields,
        )

    if parsed.inspect_packaged:
        payload["inspection"] = _filter_mapping_fields(
            _resolve_packaged_inspection_payload(
                parsed,
                packager,
                dataset,
                enriched_packaged_read=enriched_packaged_read,
            ),
            active_inspection_fields,
        )

    if parsed.operator_dashboard:
        payload["operator_dashboard"] = _filter_mapping_fields(
            _resolve_operator_dashboard_payload(
                parsed,
                packager,
                dataset,
                enriched_packaged_read=enriched_packaged_read,
            ),
            active_dashboard_fields,
        )

    if parsed.load_packaged_report:
        loaded_report = _resolve_loaded_packaged_report(
            parsed,
            packager,
            dataset,
            enriched_packaged_read=enriched_packaged_read,
        )
        if active_report_fields and isinstance(loaded_report, dict):
            loaded_report = _filter_mapping_fields(dict(loaded_report), active_report_fields)
        payload["loaded_packaged_report"] = loaded_report

    if parsed.load_operator_dashboard_report:
        loaded_dashboard_report = _resolve_loaded_operator_dashboard_report(
            parsed,
            packager,
            dataset,
            enriched_packaged_read=enriched_packaged_read,
        )
        if active_report_fields and isinstance(loaded_dashboard_report, dict):
            loaded_dashboard_report = _filter_mapping_fields(dict(loaded_dashboard_report), active_report_fields)
        payload["loaded_operator_dashboard_report"] = loaded_dashboard_report

    if parsed.packaged_recap_preflight:
        recap_preflight = build_packaged_docket_recap_fetch_preflight(
            parsed.input_path,
            api_token=parsed.courtlistener_api_token,
            pacer_username=parsed.pacer_username,
            pacer_password=parsed.pacer_password,
            client_code=parsed.pacer_client_code,
        )
        payload["recap_fetch_preflight"] = _filter_mapping_fields(
            recap_preflight,
            active_recap_fetch_fields,
        )

    if parsed.submit_packaged_recap_fetch:
        recap_fetch_result = submit_packaged_docket_recap_fetch_requests(
            parsed.input_path,
            api_token=parsed.courtlistener_api_token,
            pacer_username=parsed.pacer_username,
            pacer_password=parsed.pacer_password,
            client_code=parsed.pacer_client_code,
        )
        payload["recap_fetch_submission"] = _filter_mapping_fields(
            recap_fetch_result,
            active_recap_fetch_fields,
        )

    if parsed.export_packaged_report:
        if parsed.load_packaged_report:
            report_content = _stringify_packaged_report(
                payload["loaded_packaged_report"],
                parsed.report_format,
            )
        else:
            report_content = _stringify_packaged_report(
                _resolve_loaded_packaged_report(
                    parsed,
                    packager,
                    dataset,
                    enriched_packaged_read=enriched_packaged_read,
                ),
                parsed.report_format,
            ) if str(parsed.report_format or "").strip().lower() in {"parsed", "row"} else _resolve_loaded_packaged_report(
                parsed,
                packager,
                dataset,
                enriched_packaged_read=enriched_packaged_read,
            )
        payload["inspection_report"] = {
            "report_path": _write_text_output(parsed.export_packaged_report, report_content),
            "report_format": str(parsed.report_format),
        }

    if parsed.export_operator_dashboard_report:
        if parsed.load_operator_dashboard_report:
            dashboard_report_content = _stringify_packaged_report(
                payload["loaded_operator_dashboard_report"],
                parsed.report_format,
            )
        else:
            dashboard_report_content = _stringify_packaged_report(
                _resolve_loaded_operator_dashboard_report(
                    parsed,
                    packager,
                    dataset,
                    enriched_packaged_read=enriched_packaged_read,
                ),
                parsed.report_format,
            ) if str(parsed.report_format or "").strip().lower() in {"parsed", "row"} else _resolve_loaded_operator_dashboard_report(
                parsed,
                packager,
                dataset,
                enriched_packaged_read=enriched_packaged_read,
            )
        payload["operator_dashboard_report"] = {
            "report_path": _write_text_output(parsed.export_operator_dashboard_report, dashboard_report_content),
            "report_format": str(parsed.report_format),
        }


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ipfs-datasets docket",
        description="Import a docket into a reusable dataset artifact with KG, BM25, and vector indexes.",
    )
    parser.add_argument(
        "--input-type",
        choices=["json", "directory", "courtlistener", "packaged"],
        required=True,
        help="Whether --input-path points to a docket JSON object, a docket directory, a CourtListener docket id/URL, or an existing packaged docket manifest/archive.",
    )
    parser.add_argument("--input-path", required=True, help="Path to the docket JSON file, docket document directory, or CourtListener docket id/URL.")
    parser.add_argument("--output", required=False, help="Path to write the docket dataset artifact JSON.")
    parser.add_argument("--docket-id", default=None, help="Optional docket id override for directory imports.")
    parser.add_argument("--case-name", default=None, help="Optional case name override for directory imports.")
    parser.add_argument("--court", default="", help="Optional court name to attach to the dataset.")
    parser.add_argument("--glob", default="*", help="Glob pattern used for directory imports.")
    parser.add_argument("--skip-knowledge-graph", action="store_true", help="Do not build the knowledge graph artifact.")
    parser.add_argument("--skip-bm25", action="store_true", help="Do not build the BM25 artifact.")
    parser.add_argument("--skip-vector-index", action="store_true", help="Do not build the vector index artifact.")
    parser.add_argument("--vector-dimension", type=int, default=32, help="Vector dimension for the lightweight vector index.")
    parser.add_argument("--courtlistener-api-token", default=None, help="Optional CourtListener API token.")
    parser.add_argument("--max-courtlistener-documents", type=int, default=None, help="Optional limit for RECAP documents fetched from CourtListener.")
    parser.add_argument("--skip-courtlistener-documents", action="store_true", help="Only import the CourtListener docket metadata and party records, skipping RECAP document fetches.")
    parser.add_argument("--skip-courtlistener-text", action="store_true", help="Do not fetch missing full text for RECAP documents from CourtListener.")
    parser.add_argument("--enrich-query", action="append", default=None, help="For packaged inputs, run a tactician-guided enrichment query and attach a proof packet. Repeat for multiple queries.")
    parser.add_argument("--follow-up-top-k", type=int, default=10, help="Top-k used for tactician follow-up retrieval against packaged bundles.")
    parser.add_argument("--package-dir", default=None, help="Optional directory to also write a packaged parquet/CAR docket bundle.")
    parser.add_argument("--parquet-dir", default=None, help="Optional directory to write a parquet-only docket bundle.")
    parser.add_argument("--package-name", default=None, help="Optional package name for structured bundle output.")
    parser.add_argument("--courtlistener-cache-package-dir", default=None, help="Optional directory to write a packaged Parquet/CAR bundle for the CourtListener shared fetch cache.")
    parser.add_argument("--courtlistener-cache-dir", default=None, help="Optional explicit CourtListener shared fetch cache directory to package.")
    parser.add_argument("--zip-package", action="store_true", help="Also write a .zip archive for any docket/cache bundle that gets generated.")
    parser.add_argument("--no-car", action="store_true", help="Do not emit CAR files when writing a docket package.")
    parser.add_argument(
        "--packaged-action",
        choices=["summary", "inspect", "dashboard", "report", "dashboard-report", "recap-fetch", "recap-preflight"],
        default=None,
        help="Preferred packaged read selector for scripts: summary, inspect, dashboard, report, dashboard-report, recap-fetch, or recap-preflight.",
    )
    parser.add_argument("--inspect-packaged", action="store_true", help="For packaged inputs, include a lightweight inspection payload with latest routing/proof provenance.")
    parser.add_argument("--inspection-fields", default=None, help="Comma-separated field subset for --inspect-packaged.")
    parser.add_argument("--operator-dashboard", action="store_true", help="For packaged inputs, include the combined operator dashboard payload.")
    parser.add_argument("--dashboard-fields", default=None, help="Comma-separated field subset for --operator-dashboard.")
    parser.add_argument("--summary-only", action="store_true", help="For packaged inputs, include only the lightweight manifest-driven summary view.")
    parser.add_argument("--summary-fields", default=None, help="Comma-separated field subset for --summary-only packaged output.")
    parser.add_argument("--citation-source-audit", action="store_true", help="Include a citation source resolution audit for the docket dataset or packaged bundle.")
    parser.add_argument("--citation-audit-fields", default=None, help="Comma-separated field subset for --citation-source-audit output.")
    parser.add_argument("--no-eu-citation-audit", action="store_true", help="Skip the EU/member-state citation audit within --citation-source-audit.")
    parser.add_argument("--eu-citation-language", default=None, help="Optional language hint for EU/member-state citation extraction.")
    parser.add_argument("--eu-citation-max-documents", type=int, default=120, help="Max documents to scan for EU/member-state citations.")
    parser.add_argument("--recover-citation-sources", action="store_true", help="Run unresolved citation audit misses through the legal source recovery workflow.")
    parser.add_argument("--citation-recovery-fields", default=None, help="Comma-separated field subset for --recover-citation-sources output.")
    parser.add_argument("--recovery-max-candidates", type=int, default=8, help="Maximum recovery candidates to keep per unresolved citation.")
    parser.add_argument("--recovery-archive-top-k", type=int, default=3, help="How many top recovery candidates to archive per unresolved citation.")
    parser.add_argument("--publish-recovered-citations-to-hf", action="store_true", help="Publish recovered citation manifests to the target Hugging Face dataset.")
    parser.add_argument("--hf-token", default=None, help="Optional Hugging Face token used with --publish-recovered-citations-to-hf.")
    parser.add_argument("--load-packaged-report", action="store_true", help="For packaged inputs, load the archived inspection_report artifact directly.")
    parser.add_argument("--load-operator-dashboard-report", action="store_true", help="For packaged inputs, load the archived operator_dashboard_report artifact directly.")
    parser.add_argument("--submit-packaged-recap-fetch", action="store_true", help="For packaged inputs, submit PACER-gated acquisition queue rows to CourtListener RECAP Fetch.")
    parser.add_argument("--packaged-recap-preflight", action="store_true", help="For packaged inputs, inspect whether PACER/CourtListener RECAP Fetch has the required packaged context and secrets.")
    parser.add_argument("--recap-fetch-request-id", default=None, help="Optional CourtListener RECAP Fetch request id to inspect.")
    parser.add_argument("--recap-fetch-fields", default=None, help="Comma-separated field subset for --submit-packaged-recap-fetch or --recap-fetch-request-id.")
    parser.add_argument("--pacer-username", default=None, help="Optional PACER username override for CourtListener RECAP Fetch.")
    parser.add_argument("--pacer-password", default=None, help="Optional PACER password override for CourtListener RECAP Fetch.")
    parser.add_argument("--pacer-client-code", default=None, help="Optional PACER client code for CourtListener RECAP Fetch.")
    parser.add_argument("--report-fields", default=None, help="Comma-separated field subset for --load-packaged-report when using parsed/row output.")
    parser.add_argument("--fields", default=None, help="Comma-separated field subset for the active packaged read mode.")
    parser.add_argument("--export-packaged-report", default=None, help="For packaged inputs, write a provenance/inspection report to this path.")
    parser.add_argument("--export-operator-dashboard-report", default=None, help="For packaged inputs, write the archived operator dashboard report to this path.")
    parser.add_argument("--report-format", choices=["json", "markdown", "text", "parsed", "row"], default="markdown", help="Format used with packaged report load/export.")
    parser.add_argument("--json", action="store_true", help="Print a JSON summary instead of text.")
    return parser


def main(args: list[str] | None = None) -> int:
    parser = create_parser()
    parsed = parser.parse_args(args)
    _apply_packaged_action_alias(parsed, parser)
    summary_fields = _parse_summary_fields_arg(parsed.summary_fields)
    inspection_fields = _parse_summary_fields_arg(parsed.inspection_fields)
    dashboard_fields = _parse_summary_fields_arg(parsed.dashboard_fields)
    citation_audit_fields = _parse_summary_fields_arg(parsed.citation_audit_fields)
    citation_recovery_fields = _parse_summary_fields_arg(parsed.citation_recovery_fields)
    report_fields = _parse_summary_fields_arg(parsed.report_fields)
    recap_fetch_fields = _parse_summary_fields_arg(parsed.recap_fetch_fields)
    generic_fields = _parse_summary_fields_arg(parsed.fields)
    include_eu_audit = not bool(parsed.no_eu_citation_audit)
    eu_citation_language = str(parsed.eu_citation_language or "").strip() or None
    eu_citation_max_documents = max(0, int(parsed.eu_citation_max_documents or 120))
    packaged_modes = _packaged_read_modes(parsed)
    packaged_read_only = _is_packaged_read_only(parsed, packaged_modes)
    citation_audit_only = bool(
        parsed.citation_source_audit
        and not parsed.recover_citation_sources
        and not parsed.package_dir
        and not parsed.parquet_dir
        and not parsed.courtlistener_cache_package_dir
        and not packaged_modes
        and not parsed.export_packaged_report
        and not parsed.export_operator_dashboard_report
    )
    citation_recovery_only = bool(
        parsed.recover_citation_sources
        and not parsed.package_dir
        and not parsed.parquet_dir
        and not parsed.courtlistener_cache_package_dir
        and not packaged_modes
        and not parsed.export_packaged_report
        and not parsed.export_operator_dashboard_report
    )
    recap_fetch_status_only = bool(
        parsed.recap_fetch_request_id
        and not parsed.package_dir
        and not parsed.parquet_dir
        and not parsed.courtlistener_cache_package_dir
        and not packaged_modes
        and not parsed.export_packaged_report
        and not parsed.export_operator_dashboard_report
    )
    if not parsed.output and not packaged_read_only and not citation_audit_only and not citation_recovery_only and not recap_fetch_status_only:
        parser.error("--output is required unless you are only inspecting or loading a packaged report.")
    if citation_audit_fields and not parsed.citation_source_audit:
        parser.error("--citation-audit-fields is only valid with --citation-source-audit.")
    if citation_recovery_fields and not parsed.recover_citation_sources:
        parser.error("--citation-recovery-fields is only valid with --recover-citation-sources.")
    if generic_fields and citation_audit_fields:
        parser.error("Use either --fields or --citation-audit-fields, not both.")
    if generic_fields and citation_recovery_fields:
        parser.error("Use either --fields or --citation-recovery-fields, not both.")
    if recap_fetch_fields and not (parsed.submit_packaged_recap_fetch or parsed.recap_fetch_request_id):
        parser.error("--recap-fetch-fields is only valid with --submit-packaged-recap-fetch or --recap-fetch-request-id.")
    if generic_fields and recap_fetch_fields:
        parser.error("Use either --fields or --recap-fetch-fields, not both.")
    active_packaged_fields = _resolve_packaged_field_selections(
        parsed,
        summary_fields=summary_fields,
        inspection_fields=inspection_fields,
        dashboard_fields=dashboard_fields,
        report_fields=report_fields,
        recap_fetch_fields=recap_fetch_fields,
        generic_fields=generic_fields,
        packaged_modes=packaged_modes,
        parser=parser,
    )
    active_summary_fields = active_packaged_fields["summary"]
    active_inspection_fields = active_packaged_fields["inspection"]
    active_dashboard_fields = active_packaged_fields["dashboard"]
    active_report_fields = active_packaged_fields["report"] or active_packaged_fields["dashboard_report"]
    active_recap_fetch_fields = (
        generic_fields
        if (parsed.recap_fetch_request_id and generic_fields)
        else (active_packaged_fields["recap_fetch"] or active_packaged_fields["recap_preflight"])
    )
    active_citation_audit_fields = generic_fields if (parsed.citation_source_audit and generic_fields) else citation_audit_fields
    active_citation_recovery_fields = generic_fields if (parsed.recover_citation_sources and generic_fields) else citation_recovery_fields

    builder = DocketDatasetBuilder(vector_dimension=int(parsed.vector_dimension or 32))
    common_kwargs = {
        "include_knowledge_graph": not parsed.skip_knowledge_graph,
        "include_bm25": not parsed.skip_bm25,
        "include_vector_index": not parsed.skip_vector_index,
    }

    dataset = None
    packaged_read_packager = DocketDatasetPackager() if packaged_read_only else None

    try:
        if parsed.input_type == "json":
            dataset = builder.build_from_json_file(parsed.input_path, **common_kwargs)
        elif parsed.input_type == "courtlistener":
            docket_payload = fetch_courtlistener_docket(
                parsed.input_path,
                api_token=parsed.courtlistener_api_token,
                include_recap_documents=not parsed.skip_courtlistener_documents,
                include_document_text=not parsed.skip_courtlistener_text,
                max_documents=parsed.max_courtlistener_documents,
            )
            if parsed.case_name:
                docket_payload["case_name"] = parsed.case_name
            if parsed.court:
                docket_payload["court"] = parsed.court
            if parsed.docket_id:
                docket_payload["docket_id"] = parsed.docket_id
            dataset = builder.build_from_docket(docket_payload, **common_kwargs)
        elif parsed.input_type == "packaged":
            if parsed.skip_knowledge_graph or parsed.skip_bm25 or parsed.skip_vector_index:
                parser.error("Skip flags are only valid for source docket imports, not packaged bundle enrichment.")
            if parsed.vector_dimension != 32:
                parser.error("--vector-dimension is only used for source docket imports, not packaged bundle enrichment.")
            if parsed.enrich_query:
                dataset = enrich_packaged_docket_with_tactician(
                    parsed.input_path,
                    parsed.enrich_query,
                    top_k=int(parsed.follow_up_top_k or 10),
                )
            elif recap_fetch_status_only:
                dataset = None
            elif not packaged_read_only:
                dataset = load_packaged_docket_dataset(parsed.input_path)
            else:
                dataset = None
        else:
            dataset = builder.build_from_directory(
                parsed.input_path,
                docket_id=parsed.docket_id,
                case_name=parsed.case_name,
                court=parsed.court,
                glob_pattern=parsed.glob,
                **common_kwargs,
            )
    except CourtListenerIngestionError as exc:
        classified_error_type, classified_details = _classify_courtlistener_error(str(exc))
        return _emit_cli_error(
            parsed,
            message=str(exc),
            error_type=classified_error_type,
            details={
                "input_type": str(parsed.input_type or ""),
                "input_path": str(parsed.input_path or ""),
                **classified_details,
            },
        )

    try:
        output_path = None
        if parsed.output and dataset is not None:
            output_target = Path(parsed.output)
            if hasattr(dataset, "write_json"):
                output_path = dataset.write_json(output_target)
            else:
                output_target.parent.mkdir(parents=True, exist_ok=True)
                output_target.write_text(json.dumps(dataset, indent=2, ensure_ascii=False), encoding="utf-8")
                output_path = output_target
        package_payload = None
        package_dir = parsed.parquet_dir or parsed.package_dir
        include_car = not parsed.no_car and not bool(parsed.parquet_dir)
        if package_dir:
            if hasattr(dataset, "write_package"):
                package_payload = dataset.write_package(
                    package_dir,
                    package_name=parsed.package_name,
                    include_car=include_car,
                )
            else:
                package_payload = package_docket_dataset(
                    dataset,
                    package_dir,
                    package_name=parsed.package_name,
                    include_car=include_car,
                )
        if dataset is not None:
            summary = summarize_docket_dataset(dataset)
        elif recap_fetch_status_only:
            summary = _build_recap_fetch_status_summary(parsed)
        else:
            assert packaged_read_packager is not None
            summary = _build_packaged_read_only_summary(packaged_read_packager, parsed.input_path)
        payload = {
            "status": "success",
            "summary": summary,
        }
        if output_path is not None:
            payload["output_path"] = str(output_path)
        if parsed.citation_source_audit:
            if dataset is not None:
                citation_audit = _build_citation_source_audit_from_dataset(
                    dataset,
                    include_eu_audit=include_eu_audit,
                    eu_language=eu_citation_language,
                    eu_max_documents=eu_citation_max_documents,
                )
                if hasattr(dataset, "metadata"):
                    dataset.metadata = dict(getattr(dataset, "metadata") or {})
                    dataset.metadata["citation_source_audit"] = dict(citation_audit)
                    if isinstance(citation_audit.get("eu_citation_audit"), dict):
                        dataset.metadata["eu_citation_audit"] = dict(citation_audit.get("eu_citation_audit") or {})
                elif isinstance(dataset, dict):
                    metadata = dict(dataset.get("metadata") or {})
                    metadata["citation_source_audit"] = dict(citation_audit)
                    if isinstance(citation_audit.get("eu_citation_audit"), dict):
                        metadata["eu_citation_audit"] = dict(citation_audit.get("eu_citation_audit") or {})
                    dataset["metadata"] = metadata
            else:
                citation_audit = audit_packaged_docket_citation_sources(
                    parsed.input_path,
                    include_eu_audit=include_eu_audit,
                    eu_language=eu_citation_language,
                    eu_max_documents=eu_citation_max_documents,
                )
            payload["citation_source_audit"] = _filter_mapping_fields(
                citation_audit,
                active_citation_audit_fields,
            )
        if parsed.recover_citation_sources:
            if "citation_source_audit" in payload:
                citation_audit = dict(payload["citation_source_audit"])
                if active_citation_audit_fields:
                    if dataset is not None:
                        citation_audit = _build_citation_source_audit_from_dataset(
                            dataset,
                            include_eu_audit=include_eu_audit,
                            eu_language=eu_citation_language,
                            eu_max_documents=eu_citation_max_documents,
                        )
                    else:
                        citation_audit = audit_packaged_docket_citation_sources(
                            parsed.input_path,
                            include_eu_audit=include_eu_audit,
                            eu_language=eu_citation_language,
                            eu_max_documents=eu_citation_max_documents,
                        )
            else:
                if dataset is not None:
                    citation_audit = _build_citation_source_audit_from_dataset(
                        dataset,
                        include_eu_audit=include_eu_audit,
                        eu_language=eu_citation_language,
                        eu_max_documents=eu_citation_max_documents,
                    )
                else:
                    citation_audit = audit_packaged_docket_citation_sources(
                        parsed.input_path,
                        include_eu_audit=include_eu_audit,
                        eu_language=eu_citation_language,
                        eu_max_documents=eu_citation_max_documents,
                    )
            citation_recovery = _recover_citation_sources_from_audit(
                citation_audit,
                publish_to_hf=bool(parsed.publish_recovered_citations_to_hf),
                hf_token=parsed.hf_token,
                max_candidates=int(parsed.recovery_max_candidates or 8),
                archive_top_k=int(parsed.recovery_archive_top_k or 3),
            )
            payload["citation_source_recovery"] = _filter_mapping_fields(
                citation_recovery,
                active_citation_recovery_fields,
            )
        if parsed.recap_fetch_request_id:
            if parsed.input_type != "packaged":
                parser.error("--recap-fetch-request-id currently expects --input-type packaged so the CLI stays aligned with packaged CourtListener workflows.")
            recap_fetch_status = get_courtlistener_recap_fetch_request(
                parsed.recap_fetch_request_id,
                api_token=parsed.courtlistener_api_token,
            )
            payload["recap_fetch_request"] = _filter_mapping_fields(
                recap_fetch_status,
                active_recap_fetch_fields,
            )
        inspection_requested = bool(
            packaged_modes
            or parsed.export_packaged_report
            or parsed.export_operator_dashboard_report
        )
        if inspection_requested:
            if parsed.input_type != "packaged":
                parser.error("--inspect-packaged, --operator-dashboard, --summary-only, --load-packaged-report, --load-operator-dashboard-report, --submit-packaged-recap-fetch, --export-packaged-report, and --export-operator-dashboard-report are only valid with --input-type packaged.")
            packager = packaged_read_packager or DocketDatasetPackager()
            _handle_packaged_read_outputs(
                parsed,
                payload=payload,
                dataset=dataset,
                packager=packager,
                active_summary_fields=active_summary_fields,
                active_inspection_fields=active_inspection_fields,
                active_dashboard_fields=active_dashboard_fields,
                active_report_fields=active_report_fields,
                active_recap_fetch_fields=active_recap_fetch_fields,
            )
        if package_payload is not None:
            if parsed.zip_package:
                package_payload["zip_path"] = _create_bundle_zip(package_payload["bundle_dir"])
            payload["package"] = package_payload
        if parsed.courtlistener_cache_package_dir:
            cache_dir = parsed.courtlistener_cache_dir
            if not cache_dir:
                cache_dir = (
                    Path.home()
                    / ".cache"
                    / "ipfs_datasets_py"
                    / "legal_fetch_cache"
                )
            cache_package_payload = package_courtlistener_fetch_cache(
                cache_dir,
                parsed.courtlistener_cache_package_dir,
                package_name=(f"{parsed.package_name}_cache" if parsed.package_name else None),
                include_car=include_car,
            )
            if parsed.zip_package:
                cache_package_payload["zip_path"] = _create_bundle_zip(cache_package_payload["bundle_dir"])
            payload["courtlistener_cache_package"] = cache_package_payload
    except CourtListenerIngestionError as exc:
        classified_error_type, classified_details = _classify_courtlistener_error(str(exc))
        return _emit_cli_error(
            parsed,
            message=str(exc),
            error_type=classified_error_type,
            details={
                "input_type": str(parsed.input_type or ""),
                "input_path": str(parsed.input_path or ""),
                **classified_details,
            },
        )

    if parsed.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        if output_path is not None:
            print(f"Wrote docket dataset: {output_path}")
        if packaged_read_only and parsed.summary_only and "packaged_summary_view" in payload:
            print("Packaged Summary")
            for key, value in dict(payload["packaged_summary_view"]).items():
                if key in {"package_manifest", "routing_provenance", "inspection_report"}:
                    continue
                print(f"{key}: {value}")
        elif not packaged_read_only:
            for key, value in payload["summary"].items():
                print(f"{key}: {value}")
        if parsed.inspect_packaged and "inspection" in payload:
            _print_packaged_inspection(dict(payload["inspection"]))
        if parsed.operator_dashboard and "operator_dashboard" in payload:
            print(render_packaged_docket_operator_dashboard(payload["operator_dashboard"], report_format="text"))
        if parsed.load_packaged_report and "loaded_packaged_report" in payload:
            print(_stringify_packaged_report(payload["loaded_packaged_report"], parsed.report_format))
        if parsed.load_operator_dashboard_report and "loaded_operator_dashboard_report" in payload:
            print(_stringify_packaged_report(payload["loaded_operator_dashboard_report"], parsed.report_format))
        if parsed.citation_source_audit and "citation_source_audit" in payload:
            print("Citation Source Audit")
            for key, value in dict(payload["citation_source_audit"]).items():
                if key in {"documents", "unresolved_documents"}:
                    continue
                print(f"{key}: {value}")
        if parsed.recover_citation_sources and "citation_source_recovery" in payload:
            print("Citation Source Recovery")
            for key, value in dict(payload["citation_source_recovery"]).items():
                if key == "recoveries":
                    continue
                print(f"{key}: {value}")
        if parsed.recap_fetch_request_id and "recap_fetch_request" in payload:
            print("RECAP Fetch Request")
            for key, value in dict(payload["recap_fetch_request"]).items():
                print(f"{key}: {value}")
        if parsed.submit_packaged_recap_fetch and "recap_fetch_submission" in payload:
            print("RECAP Fetch Submission")
            for key, value in dict(payload["recap_fetch_submission"]).items():
                if key == "submissions":
                    continue
                print(f"{key}: {value}")
        if parsed.packaged_recap_preflight and "recap_fetch_preflight" in payload:
            print("RECAP Fetch Preflight")
            for key, value in dict(payload["recap_fetch_preflight"]).items():
                print(f"{key}: {value}")
        if "inspection_report" in payload:
            print(f"inspection_report_path: {payload['inspection_report']['report_path']}")
            print(f"inspection_report_format: {payload['inspection_report']['report_format']}")
        if "operator_dashboard_report" in payload:
            print(f"operator_dashboard_report_path: {payload['operator_dashboard_report']['report_path']}")
            print(f"operator_dashboard_report_format: {payload['operator_dashboard_report']['report_format']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
