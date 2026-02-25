#!/usr/bin/env python3
"""Load benchmark for GraphRAGQueryOptimizer.optimize_query()."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from statistics import mean, median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ipfs_datasets_py.optimizers.graphrag.query_optimizer import GraphRAGQueryOptimizer  # noqa: E402


def _build_query(payload_size: str) -> dict:
    base = {
        "query_type": "entity_search",
        "entity": "Alice",
        "constraints": {"type": "Person", "min_confidence": 0.7},
        "filters": {"domain": "legal"},
    }

    if payload_size == "small":
        return base
    if payload_size == "medium":
        base["context"] = {
            "synonyms": ["Alice Smith", "A. Smith", "Alice S."],
            "related_types": ["Person", "Witness", "Beneficiary"],
            "time_range": {"start": "2024-01-01", "end": "2025-12-31"},
            "jurisdictions": ["US", "EU", "UK"],
        }
        return base

    # large
    base["context"] = {
        "synonyms": [f"Alice Variant {i}" for i in range(40)],
        "related_types": [f"Type{i}" for i in range(20)],
        "time_range": {"start": "2020-01-01", "end": "2026-12-31"},
        "jurisdictions": ["US", "EU", "UK", "CA", "AU"],
        "metadata_filters": {
            f"field_{i}": {
                "allowed": [f"value_{i}_{j}" for j in range(8)],
                "weight": round(1.0 / (i + 1), 4),
            }
            for i in range(20)
        },
    }
    return base


def _run_case(
    optimizer: GraphRAGQueryOptimizer,
    query: dict,
    iterations: int = 3000,
    warmups: int = 100,
) -> dict:
    for _ in range(warmups):
        optimizer.optimize_query(query)

    samples_ms = []
    start_total = time.perf_counter()
    for _ in range(iterations):
        start = time.perf_counter()
        optimizer.optimize_query(query)
        samples_ms.append((time.perf_counter() - start) * 1000.0)
    elapsed_total = time.perf_counter() - start_total

    samples_ms.sort()
    p95_index = max(0, int(iterations * 0.95) - 1)

    return {
        "iterations": iterations,
        "warmups": warmups,
        "avg_ms": round(mean(samples_ms), 4),
        "median_ms": round(median(samples_ms), 4),
        "p95_ms": round(samples_ms[p95_index], 4),
        "max_ms": round(max(samples_ms), 4),
        "throughput_qps": round(iterations / elapsed_total, 2),
    }


def main() -> None:
    logging.disable(logging.CRITICAL)
    optimizer = GraphRAGQueryOptimizer()

    report = {}
    for payload_size in ("small", "medium", "large"):
        query = _build_query(payload_size)
        report[f"{payload_size}_payload"] = _run_case(optimizer, query)

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
