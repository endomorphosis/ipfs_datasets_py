#!/usr/bin/env python3
"""Summarize caselaw chunk lookup JSONL run logs.

Expected input records look like:
{
  "run_id": "...",
  "timestamp": "...",
  "mode": "cid|vector",
  "collection_name": "...",
  "top_k": 5,
  "result": {
    "status": "success|error",
    "operation": "...",
    "chunk_source": "hf|local|None",
    "chunk_lookup_error": "...",
    "results": [...]
  }
}
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List


def _load_records(path: Path) -> List[Dict[str, Any]]:
    """Load JSONL records, skipping blank lines."""
    records: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records


def _build_summary(records: List[Dict[str, Any]], top_errors: int) -> Dict[str, Any]:
    """Build aggregate summary across run records."""
    total = len(records)
    status_counter: Counter[str] = Counter()
    mode_counter: Counter[str] = Counter()
    operation_counter: Counter[str] = Counter()
    chunk_source_counter: Counter[str] = Counter()
    error_counter: Counter[str] = Counter()
    total_hits = 0

    for rec in records:
        mode_counter[str(rec.get("mode") or "unknown")] += 1
        result = rec.get("result") or {}
        status_counter[str(result.get("status") or "unknown")] += 1
        operation_counter[str(result.get("operation") or "unknown")] += 1
        chunk_source_counter[str(result.get("chunk_source") or "none")] += 1

        hits = result.get("results") or []
        if isinstance(hits, list):
            total_hits += len(hits)

        err = str(result.get("chunk_lookup_error") or "").strip()
        if err:
            # Normalize very long transport errors so grouping is useful.
            error_key = err[:200]
            error_counter[error_key] += 1

    summary: Dict[str, Any] = {
        "total_runs": total,
        "success_runs": status_counter.get("success", 0),
        "error_runs": status_counter.get("error", 0),
        "status_counts": dict(status_counter),
        "mode_counts": dict(mode_counter),
        "operation_counts": dict(operation_counter),
        "chunk_source_counts": dict(chunk_source_counter),
        "total_result_items": total_hits,
        "avg_result_items_per_run": (total_hits / total) if total else 0.0,
        "top_chunk_lookup_errors": [
            {"error": message, "count": count}
            for message, count in error_counter.most_common(max(top_errors, 0))
        ],
    }
    return summary


def _print_pretty(summary: Dict[str, Any]) -> None:
    """Print summary in human-readable format."""
    print(f"total_runs: {summary.get('total_runs')}")
    print(f"success_runs: {summary.get('success_runs')}")
    print(f"error_runs: {summary.get('error_runs')}")
    print(f"avg_result_items_per_run: {summary.get('avg_result_items_per_run'):.2f}")

    print("\nmode_counts:")
    for k, v in sorted((summary.get("mode_counts") or {}).items()):
        print(f"  {k}: {v}")

    print("\nstatus_counts:")
    for k, v in sorted((summary.get("status_counts") or {}).items()):
        print(f"  {k}: {v}")

    print("\nchunk_source_counts:")
    for k, v in sorted((summary.get("chunk_source_counts") or {}).items()):
        print(f"  {k}: {v}")

    top_errors = summary.get("top_chunk_lookup_errors") or []
    if top_errors:
        print("\ntop_chunk_lookup_errors:")
        for row in top_errors:
            print(f"  [{row['count']}] {row['error']}")


def _summarize_by_run_id(records: List[Dict[str, Any]], top_errors: int) -> Dict[str, Any]:
    """Build summaries grouped by run_id with a global fallback bucket."""
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for rec in records:
        run_id = str(rec.get("run_id") or "__missing_run_id__")
        buckets.setdefault(run_id, []).append(rec)

    grouped = {
        run_id: _build_summary(run_records, top_errors=top_errors)
        for run_id, run_records in buckets.items()
    }
    return {
        "group_count": len(grouped),
        "groups": grouped,
    }


def main() -> None:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(description="Summarize JSONL run logs for caselaw chunk lookup")
    parser.add_argument(
        "--input",
        default="outputs/cid_lookup_runs.jsonl",
        help="Path to JSONL run log",
    )
    parser.add_argument(
        "--top-errors",
        type=int,
        default=5,
        help="Number of top chunk lookup errors to show",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print summary as JSON",
    )
    parser.add_argument(
        "--group-by-run-id",
        action="store_true",
        help="Summarize each run_id separately",
    )
    parser.add_argument(
        "--only-run-id",
        help="Filter input records to a single run_id before summarizing",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        raise SystemExit(f"Input JSONL does not exist: {input_path}")

    records = _load_records(input_path)
    if args.only_run_id:
        requested = str(args.only_run_id)
        records = [r for r in records if str(r.get("run_id") or "__missing_run_id__") == requested]
        if not records:
            raise SystemExit(f"No records found for run_id: {requested}")

    if args.group_by_run_id:
        summary = _summarize_by_run_id(records, top_errors=args.top_errors)
    else:
        summary = _build_summary(records, top_errors=args.top_errors)

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        if args.group_by_run_id:
            print(f"group_count: {summary.get('group_count')}")
            groups = summary.get("groups") or {}
            for run_id, group_summary in sorted(groups.items()):
                print(f"\nrun_id: {run_id}")
                _print_pretty(group_summary)
        else:
            _print_pretty(summary)


if __name__ == "__main__":
    main()
