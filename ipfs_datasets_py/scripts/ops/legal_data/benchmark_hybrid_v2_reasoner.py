"""WS12-06: Performance Budget Sentinel - benchmark runner.

Benchmarks the parse/compile/prover/explain phases of the V2 reasoner pipeline.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

# Ensure the reasoner package is importable when used standalone.
_LEGAL_DATA_DIR = Path(__file__).resolve().parents[4] / "processors" / "legal_data"
if str(_LEGAL_DATA_DIR) not in sys.path:
    sys.path.insert(0, str(_LEGAL_DATA_DIR))

from reasoner.hybrid_v2_blueprint import (  # noqa: E402
    check_compliance,
    compile_ir_to_dcec,
    compile_ir_to_temporal_deontic_fol,
    explain_proof,
    parse_cnl_to_ir,
    run_v2_pipeline_with_defaults,
)

BENCHMARK_SCHEMA_VERSION = "1.0"
PHASES = ["parse", "compile_dcec", "compile_tdfol", "check_compliance", "explain_proof"]

_DEFAULT_SENTENCES: List[str] = [
    "Contractor shall submit the report",
    "Vendor shall not disclose the record",
    "Agent may request the document",
]


def _percentile(sorted_values: List[float], pct: float) -> float:
    """Return the *pct*-th percentile of an already-sorted list."""
    if not sorted_values:
        return 0.0
    idx = pct / 100.0 * (len(sorted_values) - 1)
    lower = int(idx)
    upper = min(lower + 1, len(sorted_values) - 1)
    frac = idx - lower
    return sorted_values[lower] * (1.0 - frac) + sorted_values[upper] * frac


def run_benchmark(
    sentences: Optional[List[str]] = None, *, iterations: int = 10
) -> Dict[str, Any]:
    """Run benchmark for all phases; return per-phase p50/p95/p99 latencies in ms.

    Parameters
    ----------
    sentences:
        CNL sentences to use as benchmark input.  Defaults to a small built-in
        corpus when *None*.
    iterations:
        Number of timing iterations per phase.

    Returns
    -------
    dict
        ``{"schema_version": ..., "phases": {phase: {"p50_ms", "p95_ms", "p99_ms",
        "samples"}}}``
    """
    if sentences is None:
        sentences = _DEFAULT_SENTENCES

    # Pre-parse IRs so compilation benchmarks are not penalised by parsing.
    irs = [parse_cnl_to_ir(s) for s in sentences]

    # Obtain a valid proof_id for the explain_proof benchmark.
    _pipeline_result = run_v2_pipeline_with_defaults(sentences[0])
    _proof_id = _pipeline_result.get("proof_id", "")

    timings: Dict[str, List[float]] = {p: [] for p in PHASES}

    for _ in range(iterations):
        for sentence, ir in zip(sentences, irs):
            # --- parse ---
            t0 = time.perf_counter()
            parse_cnl_to_ir(sentence)
            timings["parse"].append((time.perf_counter() - t0) * 1000.0)

            # --- compile_dcec ---
            t0 = time.perf_counter()
            compile_ir_to_dcec(ir)
            timings["compile_dcec"].append((time.perf_counter() - t0) * 1000.0)

            # --- compile_tdfol ---
            t0 = time.perf_counter()
            compile_ir_to_temporal_deontic_fol(ir)
            timings["compile_tdfol"].append((time.perf_counter() - t0) * 1000.0)

            # --- check_compliance ---
            t0 = time.perf_counter()
            check_compliance(
                {"ir": ir, "facts": {}, "events": []},
                {"range": None},
            )
            timings["check_compliance"].append((time.perf_counter() - t0) * 1000.0)

            # --- explain_proof ---
            t0 = time.perf_counter()
            if _proof_id:
                explain_proof(_proof_id, format="nl")
            timings["explain_proof"].append((time.perf_counter() - t0) * 1000.0)

    phases_out: Dict[str, Dict[str, Any]] = {}
    for phase in PHASES:
        samples = sorted(timings[phase])
        phases_out[phase] = {
            "p50_ms": _percentile(samples, 50),
            "p95_ms": _percentile(samples, 95),
            "p99_ms": _percentile(samples, 99),
            "samples": len(samples),
        }

    return {
        "schema_version": BENCHMARK_SCHEMA_VERSION,
        "phases": phases_out,
    }
