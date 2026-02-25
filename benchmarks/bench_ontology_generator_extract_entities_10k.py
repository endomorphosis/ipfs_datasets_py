#!/usr/bin/env python3
"""Micro-benchmark for OntologyGenerator.extract_entities() on ~10k-token text."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from statistics import mean, median
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (  # noqa: E402
    DataType,
    ExtractionConfig,
    ExtractionStrategy,
    OntologyGenerationContext,
    OntologyGenerator,
)


def _build_text() -> str:
    sentence = (
        "Dr. Alice Smith met Bob Johnson at Acme Corp on January 1, 2024 in New York City. "
        "USD 1,000.00 was paid to Acme Corp. "
        "The obligation of Alice is to file the report. "
    )
    # Roughly 10k+ tokens.
    return sentence * 1500


def _run_case(
    generator: OntologyGenerator,
    context: OntologyGenerationContext,
    text: str,
    iterations: int = 20,
    warmups: int = 3,
) -> dict:
    for _ in range(warmups):
        generator.extract_entities(text, context)

    samples_ms = []
    entity_counts = []
    relationship_counts = []
    for _ in range(iterations):
        start = time.perf_counter()
        result = generator.extract_entities(text, context)
        samples_ms.append((time.perf_counter() - start) * 1000.0)
        entity_counts.append(len(result.entities))
        relationship_counts.append(len(result.relationships))

    samples_ms.sort()
    p95_index = max(0, int(iterations * 0.95) - 1)
    return {
        "iterations": iterations,
        "warmups": warmups,
        "avg_ms": round(mean(samples_ms), 4),
        "median_ms": round(median(samples_ms), 4),
        "p95_ms": round(samples_ms[p95_index], 4),
        "max_ms": round(max(samples_ms), 4),
        "avg_entities": round(mean(entity_counts), 2),
        "avg_relationships": round(mean(relationship_counts), 2),
    }


def _context_for(domain: str, sentence_window: int) -> OntologyGenerationContext:
    return OntologyGenerationContext(
        data_source="benchmark",
        data_type=DataType.TEXT,
        domain=domain,
        extraction_strategy=ExtractionStrategy.RULE_BASED,
        config=ExtractionConfig(sentence_window=sentence_window),
    )


def main() -> None:
    logging.disable(logging.CRITICAL)
    generator = OntologyGenerator(use_ipfs_accelerate=False)
    text = _build_text()

    cases = {
        "general_window_0": _context_for(domain="general", sentence_window=0),
        "legal_window_2": _context_for(domain="legal", sentence_window=2),
    }

    report = {
        case_name: _run_case(generator, context, text)
        for case_name, context in cases.items()
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
