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
from .paths import DEFAULT_HF_NAMESPACE, DEFAULT_HF_REPO_IDS, PACKAGE_RAW_OUTPUT_DIR
from .upload import token_from_env, upload_datasets, verify_remote_datasets


def _print(obj: Any, as_json: bool = True) -> None:
    if as_json:
        print(json.dumps(obj, indent=2, ensure_ascii=False))
    else:
        print(obj)


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
    scrape_parser.add_argument("--use-default-seeds", action="store_true")
    scrape_parser.add_argument("--max-documents", type=int)
    scrape_parser.add_argument("--max-seed-pages", type=int)
    scrape_parser.add_argument("--crawl-depth", type=int, default=1)
    scrape_parser.add_argument("--rate-limit-delay", type=float, default=0.5)
    scrape_parser.add_argument("--no-skip-existing", action="store_true")

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

    indexes = sub.add_parser("build-indexes", help="Build vector, BM25, and knowledge graph packages.")
    indexes.add_argument("--source-dir", type=Path)

    upload = sub.add_parser("upload", help="Upload or update Hugging Face dataset repositories.")
    upload.add_argument("--target", action="append", help="Target key: all, base, vector, bm25, knowledge-graph, normalized.")
    upload.add_argument("--namespace", default=DEFAULT_HF_NAMESPACE)
    upload.add_argument("--token-env", default="HF_TOKEN")
    upload.add_argument("--private", action="store_true")
    upload.add_argument("--dry-run", action="store_true")

    verify = sub.add_parser("verify-remote", help="Verify required files and manifests on Hugging Face.")
    verify.add_argument("--target", action="append")
    verify.add_argument("--namespace", default=DEFAULT_HF_NAMESPACE)
    verify.add_argument("--token-env", default="HF_TOKEN")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "scrape":
        result = asyncio.run(
            scrape(
                output_dir=args.output_dir,
                document_urls=args.document_urls,
                seed_urls=args.seed_urls,
                use_default_seeds=args.use_default_seeds,
                max_documents=args.max_documents,
                max_seed_pages=args.max_seed_pages,
                crawl_depth=args.crawl_depth,
                rate_limit_delay=args.rate_limit_delay,
                skip_existing=not args.no_skip_existing,
            )
        )
        _print(result)
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

    if args.command == "build-indexes":
        _print({"out_dirs": [str(path) for path in build_all_indexes(source_dir=args.source_dir)]})
        return 0

    if args.command == "upload":
        _print(
            upload_datasets(
                args.target,
                namespace=args.namespace,
                token=token_from_env(args.token_env),
                private=args.private,
                dry_run=args.dry_run,
            )
        )
        return 0

    if args.command == "verify-remote":
        _print(verify_remote_datasets(args.target, namespace=args.namespace, token=token_from_env(args.token_env)))
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
