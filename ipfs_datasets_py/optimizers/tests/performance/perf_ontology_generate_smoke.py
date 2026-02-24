"""Smoke micro-benchmark for OntologyGenerator.generate_ontology()."""

from __future__ import annotations

import argparse
import json
import statistics
import time
from pathlib import Path

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    OntologyGenerator,
    OntologyGenerationContext,
    ExtractionConfig,
    ExtractionStrategy,
)


TEXT = (
    "The plaintiff agreed to the arbitration clause in Section 12.3. "
    "The defendant accepted the warranty and indemnification terms. "
    "The patient reported symptoms and the physician prescribed 5 mg dosage. "
    "The API endpoint /v1/claims returns JSON to the web client."
)


def run(iterations: int = 10) -> dict:
    generator = OntologyGenerator()
    context = OntologyGenerationContext(
        data_source="perf-smoke",
        data_type="text",
        domain="general",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
        config=ExtractionConfig(confidence_threshold=0.0, llm_fallback_threshold=0.0),
    )

    timings = []
    for _ in range(iterations):
        start = time.perf_counter()
        generator.generate_ontology(TEXT, context)
        timings.append(time.perf_counter() - start)

    mean_ms = statistics.mean(timings) * 1000.0
    p95_ms = statistics.quantiles(timings, n=20)[-1] * 1000.0
    min_ms = min(timings) * 1000.0
    max_ms = max(timings) * 1000.0
    return {
        "iterations": iterations,
        "mean_ms": mean_ms,
        "p95_ms": p95_ms,
        "min_ms": min_ms,
        "max_ms": max_ms,
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="OntologyGenerator smoke benchmark")
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--output", type=Path, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    results = run(iterations=args.iterations)
    print("OntologyGenerator.generate_ontology() smoke benchmark")
    print(f"iterations: {results['iterations']}")
    print(f"mean_ms: {results['mean_ms']:.2f}")
    print(f"p95_ms: {results['p95_ms']:.2f}")
    print(f"min_ms: {results['min_ms']:.2f}")
    print(f"max_ms: {results['max_ms']:.2f}")
    if args.output is not None:
        payload = dict(results)
        payload["text_chars"] = len(TEXT)
        args.output.write_text(json.dumps(payload, indent=2))
        print(f"wrote: {args.output}")
