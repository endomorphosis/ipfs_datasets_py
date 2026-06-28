"""Command-line entry point for the Netherlands legal data pipeline."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from .api import scrape
from .builders.ipfs_indexes import build_all_indexes, build_bm25_index, build_knowledge_graph, build_vector_index
from .builders.ipfs_package import DEFAULT_REPO_ID as DEFAULT_BASE_REPO_ID
from .builders.ipfs_package import build_ipfs_cid_package
from .builders.normalized_package import DEFAULT_REPO_ID as DEFAULT_NORMALIZED_REPO_ID
from .builders.normalized_package import build_normalized_package
from .builders.unified_package import (
    DEFAULT_REPO_ID as DEFAULT_UNIFIED_REPO_ID,
)
from .builders.unified_package import build_unified_wetwijzer_package, validate_unified_package
from .operations import (
    build_incremental_hf_delta,
    coverage_report,
    import_discovery_catalog,
    mark_packaged,
    mark_uploaded,
    mark_verified,
    queue_identifiers,
    reconcile_milestone,
    reset_interrupted_downloads,
    retry_failures,
    scrape_queued_batch,
    sync_catalog_from_raw,
    validate_integrity,
)
from .paths import DEFAULT_BWBR_CATALOG_PATH, DEFAULT_HF_NAMESPACE, DEFAULT_HF_REPO_IDS, PACKAGE_RAW_OUTPUT_DIR
from .quality_audit import run_quality_audit
from .upload import token_from_env, upload_datasets, verify_remote_datasets


def _print(obj: Any, as_json: bool = True) -> None:
    if as_json:
        print(json.dumps(obj, indent=2, ensure_ascii=False))
    else:
        print(obj)


def _summarize_scrape_result(result: dict[str, Any]) -> dict[str, Any]:
    metadata = dict(result.get("metadata") or {})
    summary_keys = [
        "seed_pages_visited",
        "seed_pages_failed",
        "candidate_links_found",
        "candidate_links_unique",
        "official_law_documents_accepted",
        "unique_laws_discovered",
        "documents_selected_for_fetch",
        "documents_fetched",
        "documents_parsed",
        "documents_skipped",
        "documents_failed",
        "documents_retried",
        "records_count",
        "article_records_count",
        "search_records_count",
        "persisted_records_count",
        "persisted_article_records_count",
        "output_records_count",
        "output_article_records_count",
        "output_search_records_count",
        "distinct_law_identifiers_in_outputs",
        "article_producing_laws_count",
        "non_article_producing_laws_count",
        "article_extraction_missing_count",
        "genuine_non_article_laws_count",
        "error_count",
        "elapsed_time_seconds",
    ]
    compact_metadata = {key: metadata[key] for key in summary_keys if key in metadata}
    for key in [
        "output_dir",
        "index_path",
        "article_index_path",
        "search_index_path",
        "run_metadata_path",
        "max_documents",
        "max_seed_pages",
        "crawl_depth",
        "rate_limit_delay",
        "skip_existing",
        "resume",
        "scrape_command",
    ]:
        if key in metadata:
            compact_metadata[key] = metadata[key]
    if metadata.get("errors"):
        compact_metadata["errors"] = list(metadata.get("errors") or [])[:20]
    if metadata.get("non_article_producing_laws"):
        compact_metadata["non_article_producing_laws"] = list(metadata.get("non_article_producing_laws") or [])[:20]
    return {
        "status": result.get("status"),
        "metadata": compact_metadata,
    }


def _parse_bool(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    normalized = value.strip().lower()
    if normalized in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "f", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"Expected a boolean value, got {value!r}.")


def _add_common_build_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source-dir", type=Path, help="Override source package directory.")
    parser.add_argument("--out-dir", type=Path, help="Override output directory.")
    parser.add_argument("--repo-id", help="Override Hugging Face dataset repo id for generated metadata.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Netherlands laws scrape, packaging, indexing, and Hugging Face upload helpers.")
    parser.add_argument("--json", action="store_true", default=True, help="Print JSON output.")
    sub = parser.add_subparsers(dest="command", required=True)

    scrape_parser = sub.add_parser("scrape", help="Scrape Netherlands laws into the package-managed raw output directory.")
    scrape_parser.add_argument("--output-dir", type=Path, default=PACKAGE_RAW_OUTPUT_DIR)
    scrape_parser.add_argument("--document-url", action="append", dest="document_urls", default=[])
    scrape_parser.add_argument("--seed-url", action="append", dest="seed_urls", default=[])
    scrape_parser.add_argument("--use-default-seeds", "--use_default_seeds", nargs="?", const=True, default=False, type=_parse_bool)
    scrape_parser.add_argument("--max-documents", "--max_documents", type=int)
    scrape_parser.add_argument("--max-seed-pages", "--max_seed_pages", type=int, default=25)
    scrape_parser.add_argument(
        "--full-discovery",
        "--full_discovery",
        action="store_true",
        help="Do not cap official discovery pages and do not apply a document cap unless explicit document URLs are supplied.",
    )
    scrape_parser.add_argument("--crawl-depth", "--crawl_depth", type=int, default=1)
    scrape_parser.add_argument("--rate-limit-delay", "--rate_limit_delay", type=float, default=0.5)
    scrape_parser.add_argument("--skip-existing", "--skip_existing", nargs="?", const=True, default=False, type=_parse_bool)
    scrape_parser.add_argument("--resume", nargs="?", const=True, default=False, type=_parse_bool)
    scrape_parser.add_argument("--no-skip-existing", "--no_skip_existing", nargs="?", const=True, default=False, type=_parse_bool)
    scrape_parser.add_argument("--from-catalog", "--from_catalog", action="store_true", help="Lease a queued BWBR batch from the persistent catalog.")
    scrape_parser.add_argument("--catalog-path", "--catalog_path", type=Path, default=DEFAULT_BWBR_CATALOG_PATH)
    scrape_parser.add_argument("--batch-size", "--batch_size", type=int, default=25)
    scrape_parser.add_argument("--worker-id", "--worker_id", default="default")
    scrape_parser.add_argument("--stale-after-minutes", "--stale_after_minutes", type=int, default=120)

    discover = sub.add_parser("discover", help="Import official SRU discovery JSONL into the persistent BWBR catalog.")
    discover.add_argument("--discovery-jsonl", "--discovery_jsonl", type=Path, required=True)
    discover.add_argument("--catalog-path", "--catalog_path", type=Path, default=DEFAULT_BWBR_CATALOG_PATH)
    discover.add_argument("--discovery-source", "--discovery_source", default="official_bwb_sru")
    discover.add_argument("--max-retries", "--max_retries", type=int, default=3)

    queue = sub.add_parser("queue", help="Queue discovered BWBR identifiers for resumable scraping.")
    queue.add_argument("--catalog-path", "--catalog_path", type=Path, default=DEFAULT_BWBR_CATALOG_PATH)
    queue.add_argument("--identifier", action="append", dest="identifiers")
    queue.add_argument("--limit", type=int)
    queue.add_argument("--include-retryable-failures", "--include_retryable_failures", action="store_true")

    retry = sub.add_parser("retry-failures", help="Queue only transient failed BWBR identifiers that still have retry budget.")
    retry.add_argument("--catalog-path", "--catalog_path", type=Path, default=DEFAULT_BWBR_CATALOG_PATH)
    retry.add_argument("--limit", type=int)

    resume = sub.add_parser("resume", help="Reset stale leases and process the next queued BWBR batch.")
    resume.add_argument("--catalog-path", "--catalog_path", type=Path, default=DEFAULT_BWBR_CATALOG_PATH)
    resume.add_argument("--raw-dir", "--raw_dir", type=Path, default=PACKAGE_RAW_OUTPUT_DIR)
    resume.add_argument("--batch-size", "--batch_size", type=int, default=25)
    resume.add_argument("--worker-id", "--worker_id", default="default")
    resume.add_argument("--rate-limit-delay", "--rate_limit_delay", type=float, default=0.5)
    resume.add_argument("--stale-after-minutes", "--stale_after_minutes", type=int, default=120)

    sync_raw = sub.add_parser("sync-raw", help="Synchronize existing raw law rows into the persistent catalog.")
    sync_raw.add_argument("--catalog-path", "--catalog_path", type=Path, default=DEFAULT_BWBR_CATALOG_PATH)
    sync_raw.add_argument("--raw-dir", "--raw_dir", type=Path, default=PACKAGE_RAW_OUTPUT_DIR)

    build_normalized = sub.add_parser("build-normalized", help="Build the normalized package.")
    build_normalized.add_argument("--raw-dir", type=Path)
    build_normalized.add_argument("--out-dir", type=Path)
    build_normalized.add_argument("--repo-id", default=DEFAULT_NORMALIZED_REPO_ID)

    build_ipfs = sub.add_parser("build-ipfs-package", help="Build the CID-addressed base package.")
    build_ipfs.add_argument("--raw-dir", type=Path)
    build_ipfs.add_argument("--out-dir", type=Path)
    build_ipfs.add_argument("--repo-id", default=DEFAULT_BASE_REPO_ID)

    vector = sub.add_parser("build-vector-index", help="Build the vector index package.")
    _add_common_build_args(vector)

    bm25 = sub.add_parser("build-bm25-index", help="Build the BM25 index package.")
    _add_common_build_args(bm25)

    kg = sub.add_parser("build-knowledge-graph", help="Build the JSON-LD knowledge graph package.")
    _add_common_build_args(kg)

    unified = sub.add_parser("build-unified", help="Build the unified WetWijzer corpus bundle.")
    unified.add_argument("--base-dir", "--base_dir", type=Path)
    unified.add_argument("--vector-dir", "--vector_dir", type=Path)
    unified.add_argument("--bm25-dir", "--bm25_dir", type=Path)
    unified.add_argument("--kg-dir", "--kg_dir", type=Path)
    unified.add_argument("--reports-dir", "--reports_dir", type=Path)
    unified.add_argument("--out-dir", "--out_dir", type=Path)
    unified.add_argument("--repo-id", default=DEFAULT_UNIFIED_REPO_ID)
    unified.add_argument(
        "--no-relationship-summaries",
        "--no_relationship_summaries",
        action="store_true",
        help="Do not derive the CID-keyed logic/relationship summary table.",
    )

    validate_unified = sub.add_parser("validate-unified", help="Validate the local unified WetWijzer corpus bundle.")
    validate_unified.add_argument("--out-dir", "--out_dir", type=Path)

    indexes = sub.add_parser("build-indexes", help="Build vector, BM25, and knowledge graph packages.")
    indexes.add_argument("--source-dir", type=Path)

    rebuild_indexes = sub.add_parser("rebuild-indexes", help="Operational alias for rebuilding vector, BM25, and graph packages.")
    rebuild_indexes.add_argument("--source-dir", type=Path)

    rebuild_hf = sub.add_parser("rebuild-huggingface", help="Rebuild full packages or emit a changed-only incremental delta.")
    rebuild_hf.add_argument("--catalog-path", "--catalog_path", type=Path, default=DEFAULT_BWBR_CATALOG_PATH)
    rebuild_hf.add_argument("--raw-dir", "--raw_dir", type=Path, default=PACKAGE_RAW_OUTPUT_DIR)
    rebuild_hf.add_argument("--incremental", action="store_true", help="Write changed-only law/article/CID/index/graph delta rows.")
    rebuild_hf.add_argument("--out-dir", "--out_dir", type=Path)
    rebuild_hf.add_argument("--identifier", action="append", dest="identifiers")
    rebuild_hf.add_argument("--limit", type=int)

    upload = sub.add_parser("upload", help="Upload or update Hugging Face dataset repositories.")
    upload.add_argument("--target", action="append", help="Target key: all, base, vector, bm25, knowledge-graph, normalized.")
    upload.add_argument("--namespace", default=DEFAULT_HF_NAMESPACE)
    upload.add_argument("--token-env", default="HF_TOKEN")
    upload.add_argument("--private", action="store_true")
    upload.add_argument("--dry-run", action="store_true")
    upload.add_argument("--catalog-path", "--catalog_path", type=Path, default=DEFAULT_BWBR_CATALOG_PATH)

    verify = sub.add_parser("verify-remote", help="Verify required files and manifests on Hugging Face.")
    verify.add_argument("--target", action="append")
    verify.add_argument("--namespace", default=DEFAULT_HF_NAMESPACE)
    verify.add_argument("--token-env", default="HF_TOKEN")
    verify.add_argument("--catalog-path", "--catalog_path", type=Path, default=DEFAULT_BWBR_CATALOG_PATH)

    verify_ops = sub.add_parser("verify", help="Run local integrity validation, or remote verification with --remote.")
    verify_ops.add_argument("--catalog-path", "--catalog_path", type=Path, default=DEFAULT_BWBR_CATALOG_PATH)
    verify_ops.add_argument("--raw-dir", "--raw_dir", type=Path, default=PACKAGE_RAW_OUTPUT_DIR)
    verify_ops.add_argument("--remote", action="store_true")
    verify_ops.add_argument("--target", action="append")
    verify_ops.add_argument("--namespace", default=DEFAULT_HF_NAMESPACE)
    verify_ops.add_argument("--token-env", default="HF_TOKEN")
    verify_ops.add_argument("--out-path", "--out_path", type=Path)

    coverage = sub.add_parser("coverage-report", help="Write a machine-readable BWBR catalog coverage report.")
    coverage.add_argument("--catalog-path", "--catalog_path", type=Path, default=DEFAULT_BWBR_CATALOG_PATH)
    coverage.add_argument("--out-path", "--out_path", type=Path)
    coverage.add_argument("--no-remaining-identifiers", "--no_remaining_identifiers", action="store_true")

    reconcile = sub.add_parser("reconcile", help="Read-only local reconciliation report for a Netherlands corpus milestone.")
    reconcile.add_argument("--catalog-path", "--catalog_path", type=Path, default=DEFAULT_BWBR_CATALOG_PATH)
    reconcile.add_argument("--raw-dir", "--raw_dir", type=Path)
    reconcile.add_argument("--package-dir", "--package_dir", type=Path)
    reconcile.add_argument("--unified-dir", "--unified_dir", type=Path)
    reconcile.add_argument("--reports-dir", "--reports_dir", type=Path)
    reconcile.add_argument("--coverage-report-path", "--coverage_report_path", type=Path)
    reconcile.add_argument("--integrity-report-path", "--integrity_report_path", type=Path)
    reconcile.add_argument("--out-path", "--out_path", type=Path)
    reconcile.add_argument("--milestone-name", "--milestone_name", default="netherlands-legal-corpus")

    reconcile_milestone_parser = sub.add_parser(
        "reconcile-milestone",
        help="Alias for reconcile; read-only/no-network/no-scrape milestone report.",
    )
    reconcile_milestone_parser.add_argument("--catalog-path", "--catalog_path", type=Path, default=DEFAULT_BWBR_CATALOG_PATH)
    reconcile_milestone_parser.add_argument("--raw-dir", "--raw_dir", type=Path)
    reconcile_milestone_parser.add_argument("--package-dir", "--package_dir", type=Path)
    reconcile_milestone_parser.add_argument("--unified-dir", "--unified_dir", type=Path)
    reconcile_milestone_parser.add_argument("--reports-dir", "--reports_dir", type=Path)
    reconcile_milestone_parser.add_argument("--coverage-report-path", "--coverage_report_path", type=Path)
    reconcile_milestone_parser.add_argument("--integrity-report-path", "--integrity_report_path", type=Path)
    reconcile_milestone_parser.add_argument("--out-path", "--out_path", type=Path)
    reconcile_milestone_parser.add_argument("--milestone-name", "--milestone_name", default="netherlands-legal-corpus")

    quality = sub.add_parser("quality-audit", help="Run duplicate, parser-noise, hierarchy, citation, status, packaging, and retrieval audits.")
    quality.add_argument("--base-dir", "--base_dir", type=Path)
    quality.add_argument("--vector-dir", "--vector_dir", type=Path)
    quality.add_argument("--bm25-dir", "--bm25_dir", type=Path)
    quality.add_argument("--kg-dir", "--kg_dir", type=Path)
    quality.add_argument("--raw-dir", "--raw_dir", type=Path, default=PACKAGE_RAW_OUTPUT_DIR)
    quality.add_argument("--out-dir", "--out_dir", type=Path)
    quality.add_argument("--sample-size", "--sample_size", type=int, default=500)
    quality.add_argument("--seed", type=int, default=42)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "scrape":
        if args.from_catalog:
            _print(
                asyncio.run(
                    scrape_queued_batch(
                        catalog_path=args.catalog_path,
                        raw_dir=args.output_dir,
                        batch_size=args.batch_size,
                        worker_id=args.worker_id,
                        rate_limit_delay=args.rate_limit_delay,
                        skip_existing=(args.skip_existing or args.resume) and not args.no_skip_existing,
                        stale_after_minutes=args.stale_after_minutes,
                    )
                )
            )
            return 0
        result = asyncio.run(
            scrape(
                output_dir=args.output_dir,
                document_urls=args.document_urls,
                seed_urls=args.seed_urls,
                use_default_seeds=args.use_default_seeds,
                max_documents=None if args.full_discovery else args.max_documents,
                max_seed_pages=None if args.full_discovery or args.max_seed_pages == 0 else args.max_seed_pages,
                crawl_depth=args.crawl_depth,
                rate_limit_delay=args.rate_limit_delay,
                skip_existing=(args.skip_existing or args.resume) and not args.no_skip_existing,
                resume=args.resume,
            )
        )
        _print(_summarize_scrape_result(result))
        return 0

    if args.command == "discover":
        _print(
            import_discovery_catalog(
                discovery_jsonl_path=args.discovery_jsonl,
                catalog_path=args.catalog_path,
                discovery_source=args.discovery_source,
                max_retries=args.max_retries,
            )
        )
        return 0

    if args.command == "queue":
        _print(
            queue_identifiers(
                catalog_path=args.catalog_path,
                identifiers=args.identifiers,
                limit=args.limit,
                include_retryable_failures=args.include_retryable_failures,
            )
        )
        return 0

    if args.command == "retry-failures":
        _print(retry_failures(catalog_path=args.catalog_path, limit=args.limit))
        return 0

    if args.command == "resume":
        reset = reset_interrupted_downloads(catalog_path=args.catalog_path, stale_after_minutes=args.stale_after_minutes)
        result = asyncio.run(
            scrape_queued_batch(
                catalog_path=args.catalog_path,
                raw_dir=args.raw_dir,
                batch_size=args.batch_size,
                worker_id=args.worker_id,
                rate_limit_delay=args.rate_limit_delay,
                skip_existing=True,
                stale_after_minutes=args.stale_after_minutes,
            )
        )
        _print({"reset": reset, "scrape": result})
        return 0

    if args.command == "sync-raw":
        _print(sync_catalog_from_raw(catalog_path=args.catalog_path, raw_dir=args.raw_dir))
        return 0

    if args.command == "build-normalized":
        out_dir = build_normalized_package(raw_dir=args.raw_dir, out_dir=args.out_dir, repo_id=args.repo_id)
        _print({"out_dir": str(out_dir)})
        return 0

    if args.command == "build-ipfs-package":
        out_dir = build_ipfs_cid_package(raw_dir=args.raw_dir, out_dir=args.out_dir, repo_id=args.repo_id)
        _print({"out_dir": str(out_dir)})
        return 0

    if args.command == "build-vector-index":
        out_dir = build_vector_index(source_dir=args.source_dir, out_dir=args.out_dir, repo_id=args.repo_id or DEFAULT_HF_REPO_IDS["vector"])
        _print({"out_dir": str(out_dir)})
        return 0

    if args.command == "build-bm25-index":
        out_dir = build_bm25_index(source_dir=args.source_dir, out_dir=args.out_dir, repo_id=args.repo_id or DEFAULT_HF_REPO_IDS["bm25"])
        _print({"out_dir": str(out_dir)})
        return 0

    if args.command == "build-knowledge-graph":
        out_dir = build_knowledge_graph(source_dir=args.source_dir, out_dir=args.out_dir, repo_id=args.repo_id or DEFAULT_HF_REPO_IDS["knowledge-graph"])
        _print({"out_dir": str(out_dir)})
        return 0

    if args.command == "build-unified":
        out_dir = build_unified_wetwijzer_package(
            base_dir=args.base_dir,
            vector_dir=args.vector_dir,
            bm25_dir=args.bm25_dir,
            kg_dir=args.kg_dir,
            reports_dir=args.reports_dir,
            out_dir=args.out_dir,
            repo_id=args.repo_id,
            include_relationship_summaries=not args.no_relationship_summaries,
        )
        _print({"out_dir": str(out_dir), "validation": validate_unified_package(out_dir)})
        return 0

    if args.command == "validate-unified":
        _print(validate_unified_package(args.out_dir))
        return 0

    if args.command == "build-indexes":
        _print({"out_dirs": [str(path) for path in build_all_indexes(source_dir=args.source_dir)]})
        return 0

    if args.command == "rebuild-indexes":
        _print({"out_dirs": [str(path) for path in build_all_indexes(source_dir=args.source_dir)]})
        return 0

    if args.command == "rebuild-huggingface":
        if args.incremental:
            _print(
                build_incremental_hf_delta(
                    catalog_path=args.catalog_path,
                    raw_dir=args.raw_dir,
                    out_dir=args.out_dir,
                    identifiers=args.identifiers,
                    limit=args.limit,
                )
            )
            return 0
        normalized = build_normalized_package(raw_dir=args.raw_dir)
        base = build_ipfs_cid_package(raw_dir=args.raw_dir)
        indexes_out = build_all_indexes(source_dir=base)
        packaged = mark_packaged(catalog_path=args.catalog_path, package_dir=base)
        _print(
            {
                "out_dirs": {
                    "normalized": str(normalized),
                    "base": str(base),
                    "vector": str(indexes_out[0]),
                    "bm25": str(indexes_out[1]),
                    "knowledge-graph": str(indexes_out[2]),
                },
                "catalog": packaged,
            }
        )
        return 0

    if args.command == "upload":
        upload_result = upload_datasets(
            args.target,
            namespace=args.namespace,
            token=token_from_env(args.token_env),
            private=args.private,
            dry_run=args.dry_run,
        )
        if not args.dry_run and all(item.get("uploaded") for item in upload_result):
            mark_uploaded(catalog_path=args.catalog_path)
        _print(upload_result)
        return 0

    if args.command == "verify-remote":
        verify_result = verify_remote_datasets(args.target, namespace=args.namespace, token=token_from_env(args.token_env))
        if verify_result and all(item.get("ok") for item in verify_result):
            mark_verified(catalog_path=args.catalog_path)
        _print(verify_result)
        return 0

    if args.command == "verify":
        if args.remote:
            verify_result = verify_remote_datasets(args.target, namespace=args.namespace, token=token_from_env(args.token_env))
            if verify_result and all(item.get("ok") for item in verify_result):
                mark_verified(catalog_path=args.catalog_path)
            _print(verify_result)
            return 0
        _print(
            validate_integrity(
                catalog_path=args.catalog_path,
                raw_dir=args.raw_dir,
                out_path=args.out_path,
            )
        )
        return 0

    if args.command == "coverage-report":
        _print(
            coverage_report(
                catalog_path=args.catalog_path,
                out_path=args.out_path,
                include_remaining_identifiers=not args.no_remaining_identifiers,
            )
        )
        return 0

    if args.command in {"reconcile", "reconcile-milestone"}:
        _print(
            reconcile_milestone(
                catalog_path=args.catalog_path,
                raw_dir=args.raw_dir,
                package_dir=args.package_dir,
                unified_dir=args.unified_dir,
                reports_dir=args.reports_dir,
                coverage_report_path=args.coverage_report_path,
                integrity_report_path=args.integrity_report_path,
                out_path=args.out_path,
                milestone_name=args.milestone_name,
            )
        )
        return 0

    if args.command == "quality-audit":
        _print(
            run_quality_audit(
                base_dir=args.base_dir,
                vector_dir=args.vector_dir,
                bm25_dir=args.bm25_dir,
                kg_dir=args.kg_dir,
                raw_dir=args.raw_dir,
                out_dir=args.out_dir,
                sample_size=args.sample_size,
                seed=args.seed,
            )
        )
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
