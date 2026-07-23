#!/usr/bin/env python3
"""Build embeddings and optional FAISS sidecars for a canonical legal corpus parquet file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from ipfs_datasets_py.processors.legal_scrapers import (
    build_canonical_corpus_semantic_index,
    canonical_corpus_index_build_result_to_dict,
    canonical_corpus_index_publish_result_to_dict,
    publish_canonical_corpus_semantic_index,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build semantic index sidecars for a canonical legal corpus parquet file."
    )
    parser.add_argument(
        "--corpus-key",
        required=True,
        choices=[
            "us_code",
            "federal_register",
            "state_laws",
            "municipal_laws",
            "state_admin_rules",
            "state_court_rules",
            "netherlands_laws",
        ],
        help="Canonical corpus key.",
    )
    parser.add_argument("--canonical-parquet", required=True, help="Path to the canonical parquet file.")
    parser.add_argument("--state", default="", help="Optional state code for state-partitioned corpora.")
    parser.add_argument("--provider", default="", help="Embeddings provider override.")
    parser.add_argument("--model", default="", help="Embedding model override.")
    parser.add_argument("--embeddings-output", default="", help="Optional output path for *_embeddings.parquet.")
    parser.add_argument("--faiss-output", default="", help="Optional output path for the FAISS index.")
    parser.add_argument("--faiss-metadata-output", default="", help="Optional output path for FAISS metadata parquet.")
    parser.add_argument("--no-faiss", action="store_true", help="Skip FAISS index generation.")
    parser.add_argument("--publish-to-hf", action="store_true", help="Upload generated artifacts to the Hugging Face dataset.")
    parser.add_argument("--hf-token", default="", help="Hugging Face token for upload.")
    parser.add_argument("--repo-id", default="", help="Override Hugging Face dataset repo id.")
    parser.add_argument("--include-canonical-parquet", action="store_true", help="Also upload the canonical parquet file.")
    parser.add_argument("--canonical-repo-path", default="", help="Override path-in-repo for the canonical parquet file.")
    parser.add_argument("--embeddings-repo-path", default="", help="Override path-in-repo for the embeddings parquet.")
    parser.add_argument("--faiss-repo-path", default="", help="Override path-in-repo for the FAISS index.")
    parser.add_argument("--faiss-metadata-repo-path", default="", help="Override path-in-repo for the FAISS metadata parquet.")
    parser.add_argument("--commit-message", default="", help="Optional commit message for HF uploads.")
    parser.add_argument("--json", action="store_true", help="Print JSON result.")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    result = canonical_corpus_index_build_result_to_dict(
        build_canonical_corpus_semantic_index(
            args.corpus_key,
            canonical_parquet_path=str(Path(args.canonical_parquet).expanduser()),
            state_code=str(args.state or "").strip() or None,
            embeddings_output_path=str(Path(args.embeddings_output).expanduser()) if args.embeddings_output else None,
            faiss_index_output_path=str(Path(args.faiss_output).expanduser()) if args.faiss_output else None,
            faiss_metadata_output_path=str(Path(args.faiss_metadata_output).expanduser()) if args.faiss_metadata_output else None,
            provider=str(args.provider or "").strip() or None,
            model_name=str(args.model or "").strip() or None,
            build_faiss=not bool(args.no_faiss),
        )
    )

    payload: dict[str, object] = {"build": result}
    if args.publish_to_hf:
        publish_result = canonical_corpus_index_publish_result_to_dict(
            publish_canonical_corpus_semantic_index(
                result,
                hf_token=str(args.hf_token or "").strip() or None,
                repo_id=str(args.repo_id or "").strip() or None,
                include_canonical_parquet=bool(args.include_canonical_parquet),
                canonical_repo_path=str(args.canonical_repo_path or "").strip() or None,
                embeddings_repo_path=str(args.embeddings_repo_path or "").strip() or None,
                faiss_index_repo_path=str(args.faiss_repo_path or "").strip() or None,
                faiss_metadata_repo_path=str(args.faiss_metadata_repo_path or "").strip() or None,
                commit_message=str(args.commit_message or "").strip() or None,
            )
        )
        payload["publish"] = publish_result

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Corpus: {result['corpus_key']}")
        print(f"Dataset: {result['dataset_id']}")
        print(f"Canonical parquet: {result['canonical_parquet_path']}")
        print(f"Embeddings parquet: {result['embeddings_parquet_path']}")
        print(f"FAISS index: {result['faiss_index_path'] or 'not written'}")
        print(f"FAISS metadata: {result['faiss_metadata_path'] or 'not written'}")
        print(f"Rows indexed: {result['row_count']}")
        print(f"Vector dimension: {result['vector_dimension']}")
        print(f"Backend: {result['backend']}")
        print(f"Provider: {result['provider']}")
        print(f"Model: {result['model_name']}")
        print(f"Join field: {result['join_field']}")
        if result.get("state_code"):
            print(f"State: {result['state_code']}")
        if "publish" in payload:
            publish_result = payload["publish"]
            assert isinstance(publish_result, dict)
            print(f"Uploaded files: {publish_result.get('upload_count')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
