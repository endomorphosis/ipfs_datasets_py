#!/usr/bin/env python3
"""Micro-benchmark for LogicValidator.validate_ontology on synthetic ontologies."""

from __future__ import annotations

import json
import logging
import time
from statistics import mean, median
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator


def _build_ontology(entity_count: int, extra_edges: int = 0) -> dict:
    entities = [
        {
            "id": f"e{i}",
            "text": f"Entity {i}",
            "type": "Concept",
            "confidence": 0.8,
            "properties": {},
        }
        for i in range(entity_count)
    ]

    # Build a simple DAG backbone (chain) then add extra forward edges.
    relationships = [
        {
            "id": f"r_chain_{i}",
            "source_id": f"e{i}",
            "target_id": f"e{i+1}",
            "type": "related_to",
            "confidence": 0.7,
        }
        for i in range(max(0, entity_count - 1))
    ]

    for i in range(extra_edges):
        src = i % max(entity_count, 1)
        dst = min(entity_count - 1, src + 2 + (i % 7))
        if src != dst:
            relationships.append(
                {
                    "id": f"r_extra_{i}",
                    "source_id": f"e{src}",
                    "target_id": f"e{dst}",
                    "type": "related_to",
                    "confidence": 0.65,
                }
            )

    return {
        "entities": entities,
        "relationships": relationships,
        "metadata": {"source": "benchmark"},
    }


def _run_case(
    validator: LogicValidator,
    ontology: dict,
    iterations: int = 200,
    warmups: int = 10,
) -> dict:
    for _ in range(warmups):
        validator.validate_ontology(ontology)

    samples_ms = []
    for _ in range(iterations):
        start = time.perf_counter()
        validator.validate_ontology(ontology)
        samples_ms.append((time.perf_counter() - start) * 1000.0)

    samples_ms.sort()
    p95_index = max(0, int(iterations * 0.95) - 1)
    return {
        "iterations": iterations,
        "warmups": warmups,
        "avg_ms": round(mean(samples_ms), 4),
        "median_ms": round(median(samples_ms), 4),
        "p95_ms": round(samples_ms[p95_index], 4),
        "max_ms": round(max(samples_ms), 4),
    }


def main() -> None:
    # Keep benchmark output machine-readable JSON only.
    logging.disable(logging.CRITICAL)
    validator = LogicValidator(use_cache=False)
    cases = {
        "100_entities_120_relationships": _build_ontology(entity_count=100, extra_edges=21),
        "100_entities_180_relationships": _build_ontology(entity_count=100, extra_edges=81),
    }

    report = {name: _run_case(validator, ontology) for name, ontology in cases.items()}
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
