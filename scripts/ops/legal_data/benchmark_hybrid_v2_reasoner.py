#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import platform
import socket
import statistics
import time
from typing import Any, Dict, List

from ipfs_datasets_py.processors.legal_data.reasoner.hybrid_v2_blueprint import (
    check_compliance,
    compile_ir_to_dcec,
    compile_ir_to_temporal_deontic_fol,
    parse_cnl_to_ir,
)


def _load_sentences_from_jsonl(path: Path, sentence_field: str) -> List[str]:
    sentences: List[str] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            value = str(row.get(sentence_field, "")).strip()
            if value:
                sentences.append(value)
    return sentences


def _percentile(values: List[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    idx = (len(ordered) - 1) * pct
    low = int(idx)
    high = min(low + 1, len(ordered) - 1)
    frac = idx - low
    return ordered[low] * (1.0 - frac) + ordered[high] * frac


def _stage_summary(samples_ms: List[float]) -> Dict[str, Any]:
    return {
        "sample_count": len(samples_ms),
        "mean_ms": round(statistics.fmean(samples_ms), 4) if samples_ms else 0.0,
        "p50_ms": round(_percentile(samples_ms, 0.50), 4),
        "p95_ms": round(_percentile(samples_ms, 0.95), 4),
        "min_ms": round(min(samples_ms), 4) if samples_ms else 0.0,
        "max_ms": round(max(samples_ms), 4) if samples_ms else 0.0,
    }


def run_benchmark(
    *,
    sentences: List[str],
    jurisdiction: str,
    iterations: int,
) -> Dict[str, Any]:
    parse_ms: List[float] = []
    compile_dcec_ms: List[float] = []
    compile_tdfol_ms: List[float] = []
    reason_ms: List[float] = []
    case_rows: List[Dict[str, Any]] = []

    for sentence in sentences:
        for _ in range(iterations):
            t0 = time.perf_counter()
            ir = parse_cnl_to_ir(sentence, jurisdiction=jurisdiction)
            t1 = time.perf_counter()

            dcec = compile_ir_to_dcec(ir)
            t2 = time.perf_counter()

            tdfol = compile_ir_to_temporal_deontic_fol(ir)
            t3 = time.perf_counter()

            out = check_compliance({"ir": ir, "events": []}, {"at": "2026-03-01"})
            t4 = time.perf_counter()

            parse_dt = (t1 - t0) * 1000.0
            dcec_dt = (t2 - t1) * 1000.0
            tdfol_dt = (t3 - t2) * 1000.0
            reason_dt = (t4 - t3) * 1000.0

            parse_ms.append(parse_dt)
            compile_dcec_ms.append(dcec_dt)
            compile_tdfol_ms.append(tdfol_dt)
            reason_ms.append(reason_dt)

            case_rows.append(
                {
                    "sentence": sentence,
                    "parse_ms": round(parse_dt, 4),
                    "compile_dcec_ms": round(dcec_dt, 4),
                    "compile_tdfol_ms": round(tdfol_dt, 4),
                    "reason_ms": round(reason_dt, 4),
                    "dcec_formula_count": len(dcec),
                    "tdfol_formula_count": len(tdfol),
                    "status": out.get("status"),
                    "violation_count": out.get("violation_count"),
                }
            )

    return {
        "metadata": {
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "hostname": socket.gethostname(),
            "platform": platform.platform(),
            "python_version": platform.python_version(),
            "processor": platform.processor() or "unknown",
            "jurisdiction": jurisdiction,
            "sentence_count": len(sentences),
            "iterations": iterations,
            "tool": "benchmark_hybrid_v2_reasoner",
            "schema_version": "1.0",
        },
        "stage_timings": {
            "parse": _stage_summary(parse_ms),
            "compile_dcec": _stage_summary(compile_dcec_ms),
            "compile_tdfol": _stage_summary(compile_tdfol_ms),
            "reason_check_compliance": _stage_summary(reason_ms),
        },
        "cases": case_rows,
    }


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Benchmark Hybrid V2 parse/compile/reason stage timings.")
    p.add_argument("--input-jsonl", required=True, help="JSONL path containing sentence records.")
    p.add_argument("--sentence-field", default="sentence", help="Sentence field key in JSONL.")
    p.add_argument("--jurisdiction", default="us/federal", help="Jurisdiction label.")
    p.add_argument("--iterations", type=int, default=3, help="Runs per sentence (>=1).")
    p.add_argument("--output-json", required=True, help="Output JSON artifact path.")
    p.add_argument("--pretty", action="store_true", help="Pretty-print output JSON.")
    return p


def main(argv: List[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    iterations = int(args.iterations)
    if iterations < 1:
        parser.error("--iterations must be >= 1")

    input_path = Path(args.input_jsonl)
    if not input_path.exists():
        parser.error(f"--input-jsonl not found: {input_path}")

    sentences = _load_sentences_from_jsonl(input_path, args.sentence_field)
    if not sentences:
        parser.error("No valid sentences found in input JSONL")

    payload = run_benchmark(
        sentences=sentences,
        jurisdiction=args.jurisdiction,
        iterations=iterations,
    )

    out_path = Path(args.output_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, indent=2 if args.pretty else None, sort_keys=True),
        encoding="utf-8",
    )

    print(json.dumps(payload["metadata"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
