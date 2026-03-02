#!/usr/bin/env python3
"""Smoke-test state-law embedding search against Hugging Face parquet datasets.

Default target layout:
  justicedao/ipfs_state_laws/<STATE>/parsed/parquet

Example:
  python scripts/ops/legal_data/smoke_state_law_vector_search.py --states OR,CA,WA
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from datasets import load_dataset
from huggingface_hub import hf_hub_url, list_repo_files

from ipfs_datasets_py.processors.legal_scrapers import legal_dataset_api


def _normalize_states(raw: str) -> List[str]:
    states: List[str] = []
    for token in (part.strip().upper() for part in raw.split(",")):
        if not token:
            continue
        if token == "ALL":
            return ["ALL"]
        if len(token) != 2 or not token.isalpha():
            raise ValueError(f"Invalid state code '{token}'. Use two-letter codes like OR, CA, NY.")
        states.append(token)
    if not states:
        raise ValueError("At least one state code is required.")
    return states


def _pick_embeddings_file(dataset_id: str, state: str) -> str:
    prefix = f"{state}/parsed/parquet"
    files = list_repo_files(repo_id=dataset_id, repo_type="dataset")
    parquet_files = sorted(
        f for f in files if f.endswith(".parquet") and (f == prefix or f.startswith(prefix + "/"))
    )
    if not parquet_files:
        raise RuntimeError(f"No parquet files found under '{prefix}' in {dataset_id}")

    for candidate in parquet_files:
        lowered = candidate.lower()
        if "embedding" in lowered or "vector" in lowered:
            return candidate
    return parquet_files[0]


def _discover_states_with_parsed_parquet(dataset_id: str) -> List[str]:
    files = list_repo_files(repo_id=dataset_id, repo_type="dataset")
    states = sorted(
        {
            f.split("/", 1)[0]
            for f in files
            if "/parsed/parquet/" in f
            and len(f.split("/", 1)[0]) == 2
            and f.split("/", 1)[0].isalpha()
        }
    )
    return states


def _extract_query_vector(dataset_id: str, parquet_file: str) -> List[float]:
    url = hf_hub_url(repo_id=dataset_id, repo_type="dataset", filename=parquet_file)
    dataset = load_dataset("parquet", data_files={"train": url}, split="train[:32]")
    first = dataset[0]

    for key in ("embedding", "embeddings", "vector", "vectors", "centroid"):
        value = first.get(key)
        if isinstance(value, list) and value and isinstance(value[0], (int, float)):
            return [float(x) for x in value]

    keys = ", ".join(sorted(first.keys()))
    raise RuntimeError(f"No vector column found in {parquet_file}. Keys: {keys}")


async def _run_for_state(args: argparse.Namespace, state: str) -> Dict[str, Any]:
    dataset_id = args.dataset_id
    parquet_file = _pick_embeddings_file(dataset_id=dataset_id, state=state)
    query_vector = _extract_query_vector(dataset_id=dataset_id, parquet_file=parquet_file)
    collection_name = f"{args.collection_prefix}_{state.lower()}"

    ingest = await legal_dataset_api.ingest_caselaw_access_vectors_from_parameters(
        {
            "collection_name": collection_name,
            "store_type": args.store_type,
            "hf_dataset_id": dataset_id,
            "parquet_file": parquet_file,
            "max_rows": args.max_rows,
            "auto_setup_venv": args.auto_setup_venv,
            "venv_dir": args.venv_dir,
        }
    )

    search = await legal_dataset_api.search_state_law_corpus_from_parameters(
        {
            "collection_name": collection_name,
            "state": state,
            "store_type": args.store_type,
            "query_vector": query_vector,
            "top_k": args.top_k,
            "enrich_with_cases": args.enrich_with_cases,
            "hf_dataset_id": dataset_id,
            "hf_parquet_file": parquet_file,
            "auto_setup_venv": args.auto_setup_venv,
            "venv_dir": args.venv_dir,
        }
    )

    result: Dict[str, Any] = {
        "state": state,
        "parquet_file": parquet_file,
        "collection_name": collection_name,
        "ingest_status": ingest.get("status"),
        "ingested_count": ingest.get("result", {}).get("ingested_count"),
        "search_status": search.get("status"),
        "result_count": len(search.get("results", []) or []),
    }

    if search.get("results"):
        top = search["results"][0]
        result["top_result"] = {
            "chunk_id": top.get("chunk_id"),
            "score": top.get("score"),
            "metadata_keys": sorted((top.get("metadata") or {}).keys()),
        }

    if ingest.get("status") != "success":
        result["ingest_error"] = ingest.get("error")
    if search.get("status") != "success":
        result["search_error"] = search.get("error")

    if args.cleanup_faiss:
        index_path = Path("faiss_index") / f"{collection_name}.index"
        meta_path = Path("faiss_metadata") / f"{collection_name}_metadata.pkl"
        index_path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)

    return result


async def _main(args: argparse.Namespace) -> int:
    results: List[Dict[str, Any]] = []
    failed = False

    states = args.states
    if states == ["ALL"]:
        states = _discover_states_with_parsed_parquet(args.dataset_id)
        if not states:
            print(
                json.dumps(
                    {
                        "dataset_id": args.dataset_id,
                        "states": [],
                        "results": [],
                        "error": "No states with /parsed/parquet/ found",
                    }
                )
            )
            return 1

    for state in states:
        try:
            state_result = await _run_for_state(args, state)
        except Exception as exc:
            failed = True
            state_result = {
                "state": state,
                "ingest_status": "error",
                "search_status": "error",
                "result_count": 0,
                "error": str(exc),
            }
        if state_result.get("search_status") != "success":
            failed = True
        results.append(state_result)

    summary = {
        "dataset_id": args.dataset_id,
        "store_type": args.store_type,
        "states": states,
        "enrich_with_cases": args.enrich_with_cases,
        "results": results,
    }
    print(json.dumps(summary))
    return 1 if failed else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test state-law embedding search by state")
    parser.add_argument(
        "--states",
        default="OR",
        help="Comma-separated two-letter states (default: OR) or ALL for auto-discovery",
    )
    parser.add_argument("--dataset-id", default="justicedao/ipfs_state_laws")
    parser.add_argument("--store-type", default="faiss")
    parser.add_argument("--max-rows", type=int, default=512)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--collection-prefix", default="state_hf_smoke")
    parser.add_argument("--venv-dir", default=".venv")
    parser.add_argument("--auto-setup-venv", action="store_true", help="Install deps in tool venv before run")
    parser.add_argument("--enrich-with-cases", action="store_true", help="Use case/statute enrichment mode")
    parser.add_argument("--cleanup-faiss", action="store_true", help="Delete generated FAISS files after each state")
    args = parser.parse_args()
    args.states = _normalize_states(args.states)
    return args


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(parse_args())))
