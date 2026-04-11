#!/usr/bin/env python3
"""Docket dataset import CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import zipfile

from ipfs_datasets_py.processors.legal_data import (
    DocketDatasetBuilder,
    DocketDatasetPackager,
    enrich_packaged_docket_with_tactician,
    fetch_courtlistener_docket,
    load_packaged_docket_dataset,
    load_packaged_docket_summary_view,
    package_docket_dataset,
    package_courtlistener_fetch_cache,
    summarize_docket_dataset,
)

__all__ = ["create_parser", "main"]


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
    print(f"dataset_id: {inspection.get('dataset_id') or ''}")
    print(f"docket_id: {inspection.get('docket_id') or ''}")
    print(f"case_name: {inspection.get('case_name') or ''}")
    print(f"court: {inspection.get('court') or ''}")
    print(f"document_count: {inspection.get('document_count') or 0}")
    print(f"attachment_count: {inspection.get('attachment_count') or 0}")
    print(f"latest_proof_packet_id: {inspection.get('latest_proof_packet_id') or ''}")
    print(f"latest_proof_packet_version: {inspection.get('latest_proof_packet_version') or 0}")
    print(f"latest_routing_reason: {inspection.get('latest_routing_reason') or ''}")
    corpus_priority = ", ".join(str(item) for item in list(inspection.get("preferred_corpus_priority") or []))
    state_codes = ", ".join(str(item) for item in list(inspection.get("preferred_state_codes") or []))
    print(f"preferred_corpus_priority: {corpus_priority}")
    print(f"preferred_state_codes: {state_codes}")
    print(f"routing_evidence_count: {inspection.get('routing_evidence_count') or 0}")
    print(f"top_routing_citation: {inspection.get('top_routing_citation') or ''}")
    print(f"top_routing_source_url: {inspection.get('top_routing_source_url') or ''}")
    print(
        "routing_provenance_piece_present: "
        f"{bool(inspection.get('routing_provenance_piece_present'))}"
    )


def _write_text_output(path: str | Path, content: str) -> str:
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    return str(output_path)


def _stringify_packaged_report(report_payload: object, report_format: str) -> str:
    normalized_format = str(report_format or "").strip().lower()
    if normalized_format in {"json", "markdown", "text"}:
        return str(report_payload or "")
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
    parser.add_argument("--inspect-packaged", action="store_true", help="For packaged inputs, include a lightweight inspection payload with latest routing/proof provenance.")
    parser.add_argument("--summary-only", action="store_true", help="For packaged inputs, include only the lightweight manifest-driven summary view.")
    parser.add_argument("--summary-fields", default=None, help="Comma-separated field subset for --summary-only packaged output.")
    parser.add_argument("--load-packaged-report", action="store_true", help="For packaged inputs, load the archived inspection_report artifact directly.")
    parser.add_argument("--export-packaged-report", default=None, help="For packaged inputs, write a provenance/inspection report to this path.")
    parser.add_argument("--report-format", choices=["json", "markdown", "text", "parsed", "row"], default="markdown", help="Format used with packaged report load/export.")
    parser.add_argument("--json", action="store_true", help="Print a JSON summary instead of text.")
    return parser


def main(args: list[str] | None = None) -> int:
    parser = create_parser()
    parsed = parser.parse_args(args)
    summary_fields = _parse_summary_fields_arg(parsed.summary_fields)

    packaged_read_only = (
        parsed.input_type == "packaged"
        and not parsed.enrich_query
        and not parsed.package_dir
        and not parsed.parquet_dir
        and not parsed.courtlistener_cache_package_dir
        and (parsed.inspect_packaged or parsed.summary_only or parsed.load_packaged_report or parsed.export_packaged_report)
    )
    if not parsed.output and not packaged_read_only:
        parser.error("--output is required unless you are only inspecting or loading a packaged report.")
    if summary_fields and not parsed.summary_only:
        parser.error("--summary-fields is only valid with --summary-only.")

    builder = DocketDatasetBuilder(vector_dimension=int(parsed.vector_dimension or 32))
    common_kwargs = {
        "include_knowledge_graph": not parsed.skip_knowledge_graph,
        "include_bm25": not parsed.skip_bm25,
        "include_vector_index": not parsed.skip_vector_index,
    }

    dataset = None
    packaged_read_packager = DocketDatasetPackager() if packaged_read_only else None

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
    else:
        assert packaged_read_packager is not None
        summary = _build_packaged_read_only_summary(packaged_read_packager, parsed.input_path)
    payload = {
        "status": "success",
        "summary": summary,
    }
    if output_path is not None:
        payload["output_path"] = str(output_path)
    inspection_requested = bool(parsed.inspect_packaged or parsed.summary_only or parsed.export_packaged_report or parsed.load_packaged_report)
    if inspection_requested:
        if parsed.input_type != "packaged":
            parser.error("--inspect-packaged, --summary-only, --load-packaged-report, and --export-packaged-report are only valid with --input-type packaged.")
        packager = packaged_read_packager or DocketDatasetPackager()
        if parsed.summary_only:
            payload["packaged_summary_view"] = _filter_mapping_fields(
                load_packaged_docket_summary_view(parsed.input_path),
                summary_fields,
            )
        inspection_payload = packager.inspect_packaged_bundle(parsed.input_path)
        if parsed.inspect_packaged:
            payload["inspection"] = inspection_payload
        if parsed.load_packaged_report:
            payload["loaded_packaged_report"] = packager.load_inspection_report(
                parsed.input_path,
                report_format=parsed.report_format,
            )
        if parsed.export_packaged_report:
            if parsed.load_packaged_report:
                report_content = _stringify_packaged_report(
                    payload["loaded_packaged_report"],
                    parsed.report_format,
                )
            else:
                report_content = packager.render_packaged_inspection_report(
                    parsed.input_path,
                    report_format=parsed.report_format,
                )
            payload["inspection_report"] = {
                "report_path": _write_text_output(parsed.export_packaged_report, report_content),
                "report_format": str(parsed.report_format),
            }
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

    if parsed.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        if output_path is not None:
            print(f"Wrote docket dataset: {output_path}")
        for key, value in payload["summary"].items():
            print(f"{key}: {value}")
        if parsed.inspect_packaged and "inspection" in payload:
            _print_packaged_inspection(dict(payload["inspection"]))
        if parsed.summary_only and "packaged_summary_view" in payload:
            print("Packaged Summary")
            for key, value in dict(payload["packaged_summary_view"]).items():
                if key in {"package_manifest", "routing_provenance", "inspection_report"}:
                    continue
                print(f"{key}: {value}")
        if parsed.load_packaged_report and "loaded_packaged_report" in payload:
            print(_stringify_packaged_report(payload["loaded_packaged_report"], parsed.report_format))
        if "inspection_report" in payload:
            print(f"inspection_report_path: {payload['inspection_report']['report_path']}")
            print(f"inspection_report_format: {payload['inspection_report']['report_format']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
