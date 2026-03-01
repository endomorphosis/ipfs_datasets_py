#!/usr/bin/env python3
"""Run CAP vector search with optional sparse chunk retrieval.

This CLI wraps `search_caselaw_access_cases_from_parameters` so you can run a
single command that returns:
- vector search hits
- CID-level case metadata (when available)
- chunk-level snippet enrichment from sparse chunks parquet
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict, List
import uuid

import faiss
import duckdb
from huggingface_hub import hf_hub_url

# Ensure repository root is importable when running script directly.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ipfs_datasets_py.processors.legal_scrapers.legal_dataset_api import (
    search_caselaw_access_cases_from_parameters,
)


def _load_query_vector(args: argparse.Namespace) -> List[float]:
    """Load query vector from JSON string/file, or generate zeros from FAISS index."""
    if args.query_vector_json:
        vector = json.loads(args.query_vector_json)
        if not isinstance(vector, list):
            raise ValueError("--query-vector-json must decode to a JSON array")
        return [float(v) for v in vector]

    if args.query_vector_file:
        payload = json.loads(Path(args.query_vector_file).read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            raise ValueError("--query-vector-file must contain a JSON array")
        return [float(v) for v in payload]

    if not args.faiss_index:
        raise ValueError(
            "Provide --query-vector-json, --query-vector-file, or --faiss-index for --zero-vector"
        )

    index = faiss.read_index(args.faiss_index)
    return [0.0] * int(index.d)


def _print_results(result: Dict[str, Any], snippet_chars: int) -> None:
    """Print search results in a concise text format."""
    print(f"status: {result.get('status')}")
    print(f"operation: {result.get('operation')}")
    print(f"case_source: {result.get('case_source')}")
    print(f"chunk_source: {result.get('chunk_source')}")
    if result.get("chunk_lookup_error"):
        print(f"chunk_lookup_error: {result.get('chunk_lookup_error')}")

    hits = result.get("results") or []
    print(f"hits: {len(hits)}")

    for i, hit in enumerate(hits, start=1):
        cid = hit.get("cid") or ""
        score = hit.get("score")
        case = hit.get("case") or {}
        chunk = hit.get("file_chunk") or {}

        print(f"\n[{i}] cid={cid} score={score}")
        if case:
            name = case.get("name") or ""
            court = case.get("court") or ""
            date = case.get("decision_date") or ""
            case_snippet = (case.get("snippet") or "")[:snippet_chars]
            if name or court or date:
                print(f"case: {name} | {court} | {date}")
            if case_snippet:
                print(f"case_snippet: {case_snippet}")

        if chunk:
            chunk_cid = chunk.get("chunk_cid") or ""
            source_file_cid = chunk.get("source_file_cid") or ""
            chunk_snippet = (chunk.get("snippet") or "")[:snippet_chars]
            print(f"chunk_cid: {chunk_cid}")
            print(f"source_file_cid: {source_file_cid}")
            if chunk_snippet:
                print(f"chunk_snippet: {chunk_snippet}")


def _build_parser() -> argparse.ArgumentParser:
    """Build CLI parser."""
    parser = argparse.ArgumentParser(
        description="CAP vector search with optional sparse chunk retrieval",
    )
    parser.add_argument("--collection-name", help="FAISS collection name (vector mode)")
    parser.add_argument("--top-k", type=int, default=5, help="Number of results to return")
    parser.add_argument("--mode", choices=["vector", "cid"], default="vector", help="Run vector search mode or direct CID lookup mode")

    parser.add_argument(
        "--query-vector-json",
        help="Query vector as JSON array string, e.g. '[0.1, 0.2, ...]'",
    )
    parser.add_argument(
        "--query-vector-file",
        help="Path to file containing query vector JSON array",
    )
    parser.add_argument(
        "--faiss-index",
        help="Path to .index file; used to infer dimension for --zero-vector",
    )
    parser.add_argument(
        "--zero-vector",
        action="store_true",
        help="Use an all-zero query vector (requires --faiss-index unless query vector provided)",
    )

    parser.add_argument(
        "--hf-dataset-id",
        default="justicedao/ipfs_caselaw_access_project",
        help="Dataset id for case-level parquet",
    )
    parser.add_argument(
        "--hf-parquet-file",
        default="embeddings/ipfs_TeraflopAI___Caselaw_Access_Project.parquet",
        help="Case-level parquet file path in dataset",
    )
    parser.add_argument(
        "--local-case-parquet-file",
        help="Local fallback path for case-level parquet",
    )

    parser.add_argument(
        "--disable-chunk-lookup",
        action="store_true",
        help="Disable sparse chunk lookup",
    )
    parser.add_argument(
        "--chunk-hf-dataset-id",
        default="justicedao/ipfs_caselaw_access_project",
        help="Dataset id for chunk-level parquet",
    )
    parser.add_argument(
        "--chunk-hf-parquet-file",
        default="embeddings/sparse_chunks.parquet",
        help="Chunk parquet file path in dataset",
    )
    parser.add_argument(
        "--local-chunk-parquet-file",
        help="Local fallback path for chunk-level parquet",
    )
    parser.add_argument(
        "--chunk-snippet-chars",
        type=int,
        default=1000,
        help="Max chunk snippet characters",
    )

    parser.add_argument("--venv-dir", default=".venv", help="Venv directory used by legal API runner")
    parser.add_argument(
        "--auto-setup-venv",
        action="store_true",
        default=False,
        help="If set, auto-install dependencies into the configured venv",
    )
    parser.add_argument(
        "--output-json",
        action="store_true",
        help="Print raw JSON result",
    )
    parser.add_argument(
        "--save-json",
        help="Optional path to save raw JSON result payload",
    )
    parser.add_argument(
        "--append-jsonl",
        help="Optional path to append one JSONL record containing run metadata and raw result",
    )
    parser.add_argument(
        "--run-id",
        help="Optional run identifier for saved/JSONL outputs (auto-generated if omitted)",
    )
    parser.add_argument(
        "--print-snippet-chars",
        type=int,
        default=400,
        help="Max chars to print per snippet in text output",
    )
    parser.add_argument(
        "--cid",
        action="append",
        default=[],
        help="CID to retrieve in direct CID mode (repeatable)",
    )
    parser.add_argument(
        "--cid-file",
        help="Path to JSON array or newline-delimited CID file for direct CID mode",
    )
    return parser


def _load_cids(args: argparse.Namespace) -> List[str]:
    """Load CIDs from repeated flags and optional file."""
    cids: List[str] = []
    for cid in args.cid:
        cid_val = str(cid).strip()
        if cid_val:
            cids.append(cid_val)

    if args.cid_file:
        raw = Path(args.cid_file).read_text(encoding="utf-8").strip()
        if raw:
            if raw.startswith("["):
                parsed = json.loads(raw)
                if not isinstance(parsed, list):
                    raise ValueError("--cid-file JSON payload must be an array")
                for item in parsed:
                    item_val = str(item).strip()
                    if item_val:
                        cids.append(item_val)
            else:
                for line in raw.splitlines():
                    line_val = line.strip()
                    if line_val:
                        cids.append(line_val)

    deduped: List[str] = []
    seen = set()
    for cid in cids:
        if cid not in seen:
            seen.add(cid)
            deduped.append(cid)
    return deduped


def _query_sparse_chunks_by_cids(args: argparse.Namespace, cids: List[str]) -> Dict[str, Any]:
    """Fetch chunk snippets directly from sparse chunk parquet by CID list."""
    if not cids:
        return {
            "status": "error",
            "operation": "cid_lookup",
            "error": "No CIDs provided. Use --cid or --cid-file",
            "results": [],
        }

    hf_url = hf_hub_url(
        repo_id=args.chunk_hf_dataset_id,
        repo_type="dataset",
        filename=args.chunk_hf_parquet_file,
    )

    sources = [("hf", hf_url)]
    if args.local_chunk_parquet_file and Path(args.local_chunk_parquet_file).exists():
        sources.append(("local", args.local_chunk_parquet_file))

    chunk_snippet_chars = int(args.chunk_snippet_chars)
    last_error = None

    for source_name, source_ref in sources:
        try:
            con = duckdb.connect()

            def _run_with_retry(query: str, params=None, retries: int = 4):
                last_exc = None
                for attempt in range(retries):
                    try:
                        if params is None:
                            return con.execute(query)
                        return con.execute(query, params)
                    except Exception as exc:
                        last_exc = exc
                        message = str(exc)
                        if "HTTP 429" in message and attempt < retries - 1:
                            time.sleep(1.5 * (2 ** attempt))
                            continue
                        raise
                if last_exc is not None:
                    raise last_exc

            placeholders = ", ".join(["?"] * len(cids))
            query = (
                "SELECT "
                "source_file_cid, "
                "source_filename, "
                "items.cid AS chunk_cid, "
                f"substr(items.content, 1, {chunk_snippet_chars}) AS chunk_snippet "
                f"FROM read_parquet('{source_ref}') "
                f"WHERE items.cid IN ({placeholders}) OR source_file_cid IN ({placeholders})"
            )
            params = list(cids) + list(cids)
            rows = _run_with_retry(query, params).fetchall()

            result_rows: List[Dict[str, Any]] = []
            for row in rows:
                source_file_cid, source_filename, chunk_cid, chunk_snippet = row
                result_rows.append(
                    {
                        "cid": str(chunk_cid).strip() if chunk_cid is not None else "",
                        "source_file_cid": str(source_file_cid).strip()
                        if source_file_cid is not None
                        else "",
                        "source_filename": source_filename,
                        "file_chunk": {
                            "chunk_cid": str(chunk_cid).strip() if chunk_cid is not None else "",
                            "source_file_cid": str(source_file_cid).strip()
                            if source_file_cid is not None
                            else "",
                            "source_filename": source_filename,
                            "snippet": chunk_snippet,
                        },
                    }
                )

            return {
                "status": "success",
                "operation": "cid_lookup",
                "chunk_source": source_name,
                "chunk_lookup_error": None,
                "results": result_rows,
            }
        except Exception as exc:
            last_error = exc
            continue

    return {
        "status": "error",
        "operation": "cid_lookup",
        "chunk_source": None,
        "chunk_lookup_error": str(last_error) if last_error is not None else "Chunk lookup failed",
        "results": [],
    }


async def _run(args: argparse.Namespace) -> Dict[str, Any]:
    """Execute the search through legal dataset API."""
    query_vector = _load_query_vector(args)

    parameters: Dict[str, Any] = {
        "collection_name": args.collection_name,
        "query_vector": query_vector,
        "top_k": int(args.top_k),
        "auto_setup_venv": bool(args.auto_setup_venv),
        "venv_dir": args.venv_dir,
        "hf_dataset_id": args.hf_dataset_id,
        "hf_parquet_file": args.hf_parquet_file,
        "local_case_parquet_file": args.local_case_parquet_file,
        "chunk_lookup_enabled": not bool(args.disable_chunk_lookup),
        "chunk_hf_dataset_id": args.chunk_hf_dataset_id,
        "chunk_hf_parquet_file": args.chunk_hf_parquet_file,
        "local_chunk_parquet_file": args.local_chunk_parquet_file,
        "chunk_snippet_chars": int(args.chunk_snippet_chars),
    }

    return await search_caselaw_access_cases_from_parameters(
        parameters,
        tool_version="cli-caselaw-chunk-search-1.0.0",
    )


def main() -> None:
    """CLI entrypoint."""
    parser = _build_parser()
    args = parser.parse_args()

    if args.mode == "vector":
        if not args.collection_name:
            parser.error("--collection-name is required in vector mode")
        if not args.query_vector_json and not args.query_vector_file and not args.zero_vector:
            parser.error("Provide one of --query-vector-json, --query-vector-file, or --zero-vector")
        result = asyncio.run(_run(args))
    else:
        cids = _load_cids(args)
        result = _query_sparse_chunks_by_cids(args, cids)

    run_id = args.run_id or str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()

    if args.save_json:
        out_path = Path(args.save_json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        wrapped = {
            "run_id": run_id,
            "timestamp": timestamp,
            "result": result,
        }
        out_path.write_text(json.dumps(wrapped, indent=2), encoding="utf-8")

    if args.append_jsonl:
        jsonl_path = Path(args.append_jsonl)
        jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "run_id": run_id,
            "timestamp": timestamp,
            "mode": args.mode,
            "collection_name": args.collection_name,
            "top_k": args.top_k,
            "result": result,
        }
        with jsonl_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=True) + "\n")

    if args.output_json:
        print(json.dumps(result, indent=2))
    else:
        _print_results(result, snippet_chars=int(args.print_snippet_chars))


if __name__ == "__main__":
    main()
