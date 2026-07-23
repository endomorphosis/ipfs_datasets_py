#!/usr/bin/env python3
"""Rebuild the municipal-laws dataset into canonical CID-keyed parquet artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def _bootstrap_pythonpath() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


_bootstrap_pythonpath()

from ipfs_datasets_py.processors.legal_scrapers.municipal_corpus_rebuilder import (
    municipal_corpus_rebuild_result_to_dict,
    rebuild_municipal_laws_corpus,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert the municipal-laws dataset into canonical CID-keyed parquet, KG, and vector artifacts."
    )
    parser.add_argument("--input-root", required=True, help="Directory containing the raw *_citation.parquet and *_html.parquet files.")
    parser.add_argument("--output-root", default="", help="Destination root for canonical parquet outputs and sidecars.")
    parser.add_argument("--states", default="", help="Optional comma-separated state filter.")
    parser.add_argument("--provider", default="", help="Embeddings provider override.")
    parser.add_argument("--model", default="thenlper/gte-small", help="Embedding model passed through the shared semantic-index builder.")
    parser.add_argument("--device", default="", help="Optional embeddings device override.")
    parser.add_argument("--no-faiss", action="store_true", help="Skip FAISS sidecar generation.")
    parser.add_argument("--publish-to-hf", action="store_true", help="Upload generated artifacts to the municipal dataset repo.")
    parser.add_argument("--hf-token", default="", help="Optional Hugging Face token.")
    parser.add_argument("--repo-id", default="", help="Optional Hugging Face dataset override.")
    parser.add_argument("--no-canonical-upload", action="store_true", help="Skip uploading the canonical parquet files when publishing.")
    parser.add_argument("--json", action="store_true", help="Print JSON instead of a short text summary.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    states = [item.strip().upper() for item in str(args.states or "").split(",") if item.strip()]
    result = municipal_corpus_rebuild_result_to_dict(
        rebuild_municipal_laws_corpus(
            input_root=str(Path(args.input_root).expanduser()),
            output_root=str(Path(args.output_root).expanduser()) if args.output_root else None,
            states=states or None,
            provider=str(args.provider or "").strip() or None,
            model_name=str(args.model or "").strip() or "thenlper/gte-small",
            device=str(args.device or "").strip() or None,
            build_faiss=not bool(args.no_faiss),
            publish_to_hf=bool(args.publish_to_hf),
            hf_token=str(args.hf_token or "").strip() or None,
            repo_id=str(args.repo_id or "").strip() or None,
            include_canonical_parquet=not bool(args.no_canonical_upload),
        )
    )
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Input root: {result['input_root']}")
        print(f"Output root: {result['output_root']}")
        print(f"Combined parquet: {result['combined_parquet_path']}")
        print(f"Rows converted: {result['row_count']}")
        print(f"States written: {', '.join(sorted(result['state_parquet_paths'].keys())) or 'none'}")
        print(f"Artifacts built: {len(result['artifact_results'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
