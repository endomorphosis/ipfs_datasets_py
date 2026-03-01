#!/usr/bin/env python3
"""Compare two formal logic conversion reports side-by-side."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple


def _load(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _origin_counts(records: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for rec in records:
        origin = str(rec.get("final_decoded_text_origin") or "none")
        counts[origin] = counts.get(origin, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: kv[0]))


def _fmt(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.6f}"
    return str(v)


def main() -> None:
    ap = argparse.ArgumentParser(description="Compare two formal logic report.json files")
    ap.add_argument("--baseline", required=True, help="Baseline report path")
    ap.add_argument("--candidate", required=True, help="Candidate report path")
    args = ap.parse_args()

    base = _load(args.baseline)
    cand = _load(args.candidate)
    bs = base.get("summary", {})
    cs = cand.get("summary", {})

    metrics: List[Tuple[str, Any, Any]] = [
        (
            "semantic_similarity_final_decoded_mean",
            bs.get("semantic_similarity_final_decoded_mean"),
            cs.get("semantic_similarity_final_decoded_mean"),
        ),
        (
            "final_decoded_keyphrase_retention_mean",
            bs.get("final_decoded_keyphrase_retention_mean"),
            cs.get("final_decoded_keyphrase_retention_mean"),
        ),
        (
            "final_decoded_enumeration_integrity_mean",
            bs.get("final_decoded_enumeration_integrity_mean"),
            cs.get("final_decoded_enumeration_integrity_mean"),
        ),
        ("flogic_relation_coverage_mean", bs.get("flogic_relation_coverage_mean"), cs.get("flogic_relation_coverage_mean")),
        (
            "artifact_orphan_total",
            bs.get("final_decoded_orphan_terminal_count_total"),
            cs.get("final_decoded_orphan_terminal_count_total"),
        ),
        (
            "artifact_relative_total",
            bs.get("final_decoded_relative_clause_artifact_count_total"),
            cs.get("final_decoded_relative_clause_artifact_count_total"),
        ),
        ("semantic_similarity_hybrid_mean", bs.get("semantic_similarity_hybrid_mean"), cs.get("semantic_similarity_hybrid_mean")),
        ("hybrid_ir_success_count", bs.get("hybrid_ir_success_count"), cs.get("hybrid_ir_success_count")),
        ("hybrid_ir_success_rate", bs.get("hybrid_ir_success_rate"), cs.get("hybrid_ir_success_rate")),
    ]

    print("BASELINE:", args.baseline)
    print("CANDIDATE:", args.candidate)
    print("segment_count_baseline:", bs.get("segment_count"))
    print("segment_count_candidate:", cs.get("segment_count"))
    print("")
    print(f"{'metric':46} {'baseline':>14} {'candidate':>14} {'delta(c-b)':>14}")
    print("-" * 92)
    for key, b, c in metrics:
        if isinstance(b, (int, float)) and isinstance(c, (int, float)):
            delta = c - b
            print(f"{key:46} {_fmt(b):>14} {_fmt(c):>14} {_fmt(delta):>14}")
        else:
            delta = "" if (b is None or c is None) else _fmt(c)
            print(f"{key:46} {_fmt(b):>14} {_fmt(c):>14} {delta:>14}")

    print("")
    print("origin_counts_baseline:", _origin_counts(base.get("records", [])))
    print("origin_counts_candidate:", _origin_counts(cand.get("records", [])))


if __name__ == "__main__":
    main()
