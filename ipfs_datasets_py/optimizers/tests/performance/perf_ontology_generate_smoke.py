"""Micro-benchmark smoke test for OntologyGenerator.generate_ontology().

Produces a small timing table for before/after comparisons in documentation.
Run manually (not collected as a test):

    python -m ipfs_datasets_py.optimizers.tests.performance.perf_ontology_generate_smoke
"""

from __future__ import annotations

import statistics
import time

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerationContext,
    OntologyGenerator,
)


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = int(round((len(ordered) - 1) * pct))
    idx = max(0, min(idx, len(ordered) - 1))
    return ordered[idx]


def _benchmark_generate(iterations: int = 8) -> dict[str, float]:
    generator = OntologyGenerator(use_ipfs_accelerate=False)
    context = OntologyGenerationContext(
        data_source="perf-smoke",
        data_type="text",
        domain="general",
    )
    text = (
        "Acme Corp signed a contract with Beta LLC on January 5, 2026. "
        "Dr. Chen reviewed the patient record under HIPAA guidance. "
        "The backend API endpoint /v1/claims returns JSON for the web client. "
        "AWS Lambda processed the batch payment queue for invoices."
    )

    # Warmup run to stabilize caches.
    generator.generate_ontology(text, context)

    timings_ms: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        generator.generate_ontology(text, context)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        timings_ms.append(elapsed_ms)

    return {
        "runs": float(len(timings_ms)),
        "mean_ms": statistics.mean(timings_ms),
        "min_ms": min(timings_ms),
        "max_ms": max(timings_ms),
        "p95_ms": _percentile(timings_ms, 0.95),
    }


def main() -> None:
    stats = _benchmark_generate()
    print("\nOntologyGenerator.generate_ontology() micro-benchmark (smoke)\n")
    print("| Metric | Value |")
    print("| --- | --- |")
    print(f"| Runs | {int(stats['runs'])} |")
    print(f"| Mean (ms) | {stats['mean_ms']:.2f} |")
    print(f"| P95 (ms) | {stats['p95_ms']:.2f} |")
    print(f"| Min (ms) | {stats['min_ms']:.2f} |")
    print(f"| Max (ms) | {stats['max_ms']:.2f} |")
    print("\nCopy the table into PERFORMANCE_TUNING_GUIDE.md for before/after tracking.")


if __name__ == "__main__":
    main()
