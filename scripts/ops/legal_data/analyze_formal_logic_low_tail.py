#!/usr/bin/env python3
"""Analyze low-tail roundtrip quality from formal-logic conversion reports.

Usage:
  python scripts/ops/analyze_formal_logic_low_tail.py \
    --report artifacts/formal_logic_tmp_verify/federal/report.json \
    --baseline artifacts/formal_logic_tmp_verify/federal/report.pre_phase1_cleanup.json \
    --top-k 12
"""

from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


def _load_report(path: str) -> Dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _score_rows(report: Dict[str, Any]) -> List[Tuple[float, Dict[str, Any]]]:
    rows: List[Tuple[float, Dict[str, Any]]] = []
    for rec in report.get("records", []):
        score = rec.get("semantic_similarity_final_decoded")
        if score is None:
            continue
        rows.append((float(score), rec))
    rows.sort(key=lambda x: x[0])
    return rows


def _safe_mean(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return float(statistics.mean(values))


def _summary(report: Dict[str, Any], top_k: int) -> Dict[str, Any]:
    rows = _score_rows(report)
    vals = [score for score, _ in rows]
    top_k = max(1, min(top_k, len(vals))) if vals else 1
    low_vals = vals[:top_k] if vals else []
    fol_vals = [
        float(rec.get("semantic_similarity_final_decoded"))
        for _, rec in rows
        if rec.get("final_decoded_text_origin") == "fol"
    ]
    hybrid_vals = [
        float(rec.get("semantic_similarity_final_decoded"))
        for _, rec in rows
        if rec.get("final_decoded_text_origin") == "hybrid"
    ]
    out = {
        "n": len(vals),
        "mean": _safe_mean(vals),
        "low_k": top_k,
        "low_k_mean": _safe_mean(low_vals),
        "p10": vals[max(0, int(0.1 * (len(vals) - 1)))] if vals else None,
        "p50": vals[len(vals) // 2] if vals else None,
        "p90": vals[min(len(vals) - 1, int(0.9 * (len(vals) - 1)))] if vals else None,
        "fol_n": len(fol_vals),
        "fol_mean": _safe_mean(fol_vals),
        "hybrid_n": len(hybrid_vals),
        "hybrid_mean": _safe_mean(hybrid_vals),
    }
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="Analyze low-tail formal-logic roundtrip quality")
    ap.add_argument("--report", required=True, help="Path to current report.json")
    ap.add_argument("--baseline", default="", help="Optional baseline report.json for deltas")
    ap.add_argument("--top-k", type=int, default=12, help="Size of low-tail slice (default: 12)")
    ap.add_argument("--show-worst", type=int, default=8, help="How many worst records to print")
    args = ap.parse_args()

    report = _load_report(args.report)
    curr = _summary(report, top_k=int(args.top_k))

    print("[current]")
    for key in [
        "n",
        "mean",
        "low_k",
        "low_k_mean",
        "p10",
        "p50",
        "p90",
        "fol_n",
        "fol_mean",
        "hybrid_n",
        "hybrid_mean",
    ]:
        print(f"{key}: {curr.get(key)}")

    summary = report.get("summary", {})
    print("artifact_orphan_total:", summary.get("final_decoded_orphan_terminal_count_total"))
    print("artifact_relative_total:", summary.get("final_decoded_relative_clause_artifact_count_total"))
    if "hybrid_ir_enabled" in summary:
        print("hybrid_ir_enabled:", summary.get("hybrid_ir_enabled"))
    if "hybrid_ir_success_count" in summary:
        print("hybrid_ir_success_count:", summary.get("hybrid_ir_success_count"))
    if "hybrid_ir_success_rate" in summary:
        print("hybrid_ir_success_rate:", summary.get("hybrid_ir_success_rate"))
    if "semantic_similarity_hybrid_mean" in summary:
        print("semantic_similarity_hybrid_mean:", summary.get("semantic_similarity_hybrid_mean"))

    if args.baseline:
        base_report = _load_report(args.baseline)
        base = _summary(base_report, top_k=int(args.top_k))
        print("\n[delta_vs_baseline]")
        for key in ["mean", "low_k_mean", "p10", "p50", "p90", "fol_mean", "hybrid_mean"]:
            a = base.get(key)
            b = curr.get(key)
            delta = (b - a) if (a is not None and b is not None) else None
            print(f"{key}: baseline={a} current={b} delta={delta}")

    rows = _score_rows(report)
    print("\n[worst_records]")
    for score, rec in rows[: max(1, int(args.show_worst))]:
        sid = rec.get("source_id")
        origin = rec.get("final_decoded_text_origin")
        txt = str(rec.get("final_decoded_text") or "")
        txt = txt.replace("\n", " ").strip()
        print("---")
        print(f"score={score:.4f} origin={origin} source_id={sid}")
        print(txt[:240])


if __name__ == "__main__":
    main()
