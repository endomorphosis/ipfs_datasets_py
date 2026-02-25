#!/usr/bin/env python3
"""Benchmark OntologyPipeline.run_batch() serial vs parallel execution."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from statistics import mean, median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline  # noqa: E402


def _sample_docs(n: int = 16) -> list[str]:
    base = [
        "Alice works at Acme Corporation and reports to Bob.",
        "Bob manages the New York office and oversees legal operations.",
        "Carol signed the agreement with Delta Partners on January 15.",
        "The contract includes confidentiality and arbitration clauses.",
    ]
    docs: list[str] = []
    for i in range(n):
        docs.append(f"{base[i % len(base)]} Document index={i}.")
    return docs


def _run_case(
    pipeline: OntologyPipeline,
    docs: list[str],
    *,
    parallel: bool,
    max_workers: int = 4,
    iterations: int = 20,
    warmups: int = 3,
) -> dict[str, float | int]:
    kwargs = {
        "data_source": "bench",
        "refine": False,
        "parallel": parallel,
        "max_workers": max_workers,
    }

    for _ in range(warmups):
        pipeline.run_batch(docs, **kwargs)

    samples_ms: list[float] = []
    total_start = time.perf_counter()
    for _ in range(iterations):
        start = time.perf_counter()
        pipeline.run_batch(docs, **kwargs)
        samples_ms.append((time.perf_counter() - start) * 1000.0)
    total_elapsed = time.perf_counter() - total_start

    sorted_samples = sorted(samples_ms)
    p95_idx = max(0, int(iterations * 0.95) - 1)
    return {
        "iterations": iterations,
        "warmups": warmups,
        "doc_count": len(docs),
        "avg_ms": round(mean(samples_ms), 4),
        "median_ms": round(median(samples_ms), 4),
        "p95_ms": round(sorted_samples[p95_idx], 4),
        "max_ms": round(max(samples_ms), 4),
        "throughput_batches_per_s": round(iterations / total_elapsed, 2),
    }


def main() -> None:
    logging.disable(logging.CRITICAL)
    docs = _sample_docs()
    pipeline = OntologyPipeline(domain="general", use_llm=False, max_rounds=1)

    serial = _run_case(pipeline, docs, parallel=False, max_workers=1)
    parallel = _run_case(pipeline, docs, parallel=True, max_workers=4)

    speedup = (
        round(serial["avg_ms"] / parallel["avg_ms"], 4)
        if isinstance(serial["avg_ms"], float)
        and isinstance(parallel["avg_ms"], float)
        and parallel["avg_ms"] > 0.0
        else None
    )

    report = {
        "serial": serial,
        "parallel": parallel,
        "speedup_factor_avg_ms": speedup,
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

