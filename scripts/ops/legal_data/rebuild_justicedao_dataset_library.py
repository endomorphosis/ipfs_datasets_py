#!/usr/bin/env python3
"""Rebuild retrieval artifacts for the JusticeDAO legal corpus library."""

from __future__ import annotations

import argparse
import json
from typing import Dict, List

from ipfs_datasets_py.processors.legal_scrapers.justicedao_dataset_inventory import (
    build_justicedao_rebuild_plan,
    justicedao_rebuild_plan_to_dict,
    justicedao_library_rebuild_result_to_dict,
    rebuild_justicedao_dataset_library,
)


def _parse_override(values: List[str]) -> Dict[str, List[str] | str]:
    overrides: Dict[str, List[str] | str] = {}
    for item in values:
        raw = str(item or "").strip()
        if "=" not in raw:
            raise ValueError(f"Expected override in corpus_key=/path/to/file.parquet form, got: {raw}")
        corpus_key, path = raw.split("=", 1)
        key = corpus_key.strip().lower()
        value = path.strip()
        if not key or not value:
            raise ValueError(f"Invalid override: {raw}")
        existing = overrides.get(key)
        if existing is None:
            overrides[key] = value
        elif isinstance(existing, list):
            existing.append(value)
        else:
            overrides[key] = [existing, value]
    return overrides


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild CID/BM25/KG/vector artifacts for JusticeDAO datasets.")
    parser.add_argument("--corpus-key", action="append", dest="corpus_keys", default=[])
    parser.add_argument("--state", action="append", dest="state_codes", default=[])
    parser.add_argument("--parquet-override", action="append", default=[])
    parser.add_argument("--provider", default=None)
    parser.add_argument("--model-name", default=None)
    parser.add_argument("--device", default=None)
    parser.add_argument("--enable-llm-kg-enrichment", action="store_true")
    parser.add_argument("--llm-provider", default=None)
    parser.add_argument("--llm-model-name", default=None)
    parser.add_argument("--llm-max-rows", type=int, default=0)
    parser.add_argument("--llm-max-chars", type=int, default=700)
    parser.add_argument("--execute-recovery-for-degraded-corpora", action="store_true")
    parser.add_argument("--recovery-max-candidates", type=int, default=8)
    parser.add_argument("--recovery-archive-top-k", type=int, default=3)
    parser.add_argument("--recovery-publish-to-hf", action="store_true")
    parser.add_argument("--no-faiss", action="store_true")
    parser.add_argument("--publish-to-hf", action="store_true")
    parser.add_argument("--hf-token", default=None)
    parser.add_argument("--include-canonical-parquet", action="store_true")
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--max-files-per-corpus", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=0)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--no-hf-download", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    overrides = _parse_override(list(args.parquet_override or [])) if args.parquet_override else None
    if args.plan_only:
        plan = build_justicedao_rebuild_plan(
            corpus_keys=list(args.corpus_keys or []) or None,
            state_codes=list(args.state_codes or []) or None,
            batch_size=int(args.batch_size or 0),
            max_files_per_corpus=int(args.max_files_per_corpus or 0),
        )
        payload = justicedao_rebuild_plan_to_dict(plan)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    result = rebuild_justicedao_dataset_library(
        corpus_keys=list(args.corpus_keys or []) or None,
        state_codes=list(args.state_codes or []) or None,
        parquet_file_overrides=overrides,
        allow_hf_download=not bool(args.no_hf_download),
        build_faiss=not bool(args.no_faiss),
        provider=(str(args.provider).strip() or None) if args.provider is not None else None,
        model_name=(str(args.model_name).strip() or None) if args.model_name is not None else None,
        device=(str(args.device).strip() or None) if args.device is not None else None,
        enable_llm_kg_enrichment=bool(args.enable_llm_kg_enrichment),
        llm_provider=(str(args.llm_provider).strip() or None) if args.llm_provider is not None else None,
        llm_model_name=(str(args.llm_model_name).strip() or None) if args.llm_model_name is not None else None,
        llm_max_rows=int(args.llm_max_rows or 0),
        llm_max_chars=int(args.llm_max_chars or 700),
        execute_recovery_for_degraded_corpora=bool(args.execute_recovery_for_degraded_corpora),
        recovery_max_candidates=int(args.recovery_max_candidates or 8),
        recovery_archive_top_k=int(args.recovery_archive_top_k or 3),
        recovery_publish_to_hf=bool(args.recovery_publish_to_hf),
        publish_to_hf=bool(args.publish_to_hf),
        hf_token=(str(args.hf_token).strip() or None) if args.hf_token is not None else None,
        include_canonical_parquet=bool(args.include_canonical_parquet),
        max_files_per_corpus=int(args.max_files_per_corpus or 0),
        output_root=(str(args.output_root).strip() or None) if args.output_root is not None else None,
    )

    payload = justicedao_library_rebuild_result_to_dict(result)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(
            json.dumps(
                {
                    "success_count": payload["success_count"],
                    "failure_count": payload["failure_count"],
                    "artifact_results": payload["artifact_results"],
                    "errors": payload["errors"],
                },
                indent=2,
                sort_keys=True,
            )
        )
    return 0 if payload["failure_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
