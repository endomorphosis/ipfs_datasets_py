#!/usr/bin/env python3
"""Docket dataset import CLI."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import zipfile

from ipfs_datasets_py.processors.legal_data import (
    DocketDatasetBuilder,
    fetch_courtlistener_docket,
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


def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ipfs-datasets docket",
        description="Import a docket into a reusable dataset artifact with KG, BM25, and vector indexes.",
    )
    parser.add_argument(
        "--input-type",
        choices=["json", "directory", "courtlistener"],
        required=True,
        help="Whether --input-path points to a docket JSON object, a docket directory, or a CourtListener docket id/URL.",
    )
    parser.add_argument("--input-path", required=True, help="Path to the docket JSON file, docket document directory, or CourtListener docket id/URL.")
    parser.add_argument("--output", required=True, help="Path to write the docket dataset artifact JSON.")
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
    parser.add_argument("--package-dir", default=None, help="Optional directory to also write a packaged parquet/CAR docket bundle.")
    parser.add_argument("--parquet-dir", default=None, help="Optional directory to write a parquet-only docket bundle.")
    parser.add_argument("--package-name", default=None, help="Optional package name for structured bundle output.")
    parser.add_argument("--courtlistener-cache-package-dir", default=None, help="Optional directory to write a packaged Parquet/CAR bundle for the CourtListener shared fetch cache.")
    parser.add_argument("--courtlistener-cache-dir", default=None, help="Optional explicit CourtListener shared fetch cache directory to package.")
    parser.add_argument("--zip-package", action="store_true", help="Also write a .zip archive for any docket/cache bundle that gets generated.")
    parser.add_argument("--no-car", action="store_true", help="Do not emit CAR files when writing a docket package.")
    parser.add_argument("--json", action="store_true", help="Print a JSON summary instead of text.")
    return parser


def main(args: list[str] | None = None) -> int:
    parser = create_parser()
    parsed = parser.parse_args(args)

    builder = DocketDatasetBuilder(vector_dimension=int(parsed.vector_dimension or 32))
    common_kwargs = {
        "include_knowledge_graph": not parsed.skip_knowledge_graph,
        "include_bm25": not parsed.skip_bm25,
        "include_vector_index": not parsed.skip_vector_index,
    }

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
    else:
        dataset = builder.build_from_directory(
            parsed.input_path,
            docket_id=parsed.docket_id,
            case_name=parsed.case_name,
            court=parsed.court,
            glob_pattern=parsed.glob,
            **common_kwargs,
        )

    output_path = dataset.write_json(Path(parsed.output))
    package_payload = None
    package_dir = parsed.parquet_dir or parsed.package_dir
    include_car = not parsed.no_car and not bool(parsed.parquet_dir)
    if package_dir:
        package_payload = dataset.write_package(
            package_dir,
            package_name=parsed.package_name,
            include_car=include_car,
        )
    payload = {
        "status": "success",
        "output_path": str(output_path),
        "summary": summarize_docket_dataset(dataset),
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
        print(f"Wrote docket dataset: {output_path}")
        for key, value in payload["summary"].items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
