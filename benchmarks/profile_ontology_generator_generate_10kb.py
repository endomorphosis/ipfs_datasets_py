#!/usr/bin/env python3
"""Profile OntologyGenerator.generate_ontology() on ~10kB input."""

from __future__ import annotations

import cProfile
import io
import json
import logging
import pstats
import sys
import time
from pathlib import Path
from statistics import mean, median

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (  # noqa: E402
    DataType,
    ExtractionConfig,
    ExtractionStrategy,
    OntologyGenerationContext,
    OntologyGenerator,
)


def _build_text_10kb() -> str:
    sentence = (
        "Alice entered into a service agreement with Acme Corp on January 1, 2024. "
        "The contract requires payment within thirty days of invoice and includes warranty terms. "
    )
    chunks = []
    size = 0
    while size < 10_240:
        chunks.append(sentence)
        size += len(sentence.encode("utf-8"))
    return "".join(chunks)


def _make_context() -> OntologyGenerationContext:
    return OntologyGenerationContext(
        data_source="benchmark",
        data_type=DataType.TEXT,
        domain="legal",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
        config=ExtractionConfig(sentence_window=2),
    )


def _profile_once(generator: OntologyGenerator, text: str, context: OntologyGenerationContext) -> dict[str, object]:
    profiler = cProfile.Profile()
    profiler.enable()
    ontology = generator.generate_ontology(text, context)
    profiler.disable()

    stats_stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stats_stream).sort_stats("cumulative")
    stats.print_stats(15)

    return {
        "entity_count": len(ontology.get("entities", [])),
        "relationship_count": len(ontology.get("relationships", [])),
        "top_functions": stats_stream.getvalue(),
    }


def main() -> None:
    logging.disable(logging.CRITICAL)
    generator = OntologyGenerator(use_ipfs_accelerate=False)
    context = _make_context()
    text = _build_text_10kb()

    warmups = 3
    iterations = 30

    for _ in range(warmups):
        generator.generate_ontology(text, context)

    samples_ms: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        generator.generate_ontology(text, context)
        samples_ms.append((time.perf_counter() - start) * 1000.0)

    profile_snapshot = _profile_once(generator, text, context)

    report = {
        "input_bytes": len(text.encode("utf-8")),
        "warmups": warmups,
        "iterations": iterations,
        "avg_ms": round(mean(samples_ms), 4),
        "median_ms": round(median(samples_ms), 4),
        "p95_ms": round(sorted(samples_ms)[max(0, int(iterations * 0.95) - 1)], 4),
        "entity_count": profile_snapshot["entity_count"],
        "relationship_count": profile_snapshot["relationship_count"],
        "top_functions": profile_snapshot["top_functions"],
    }

    print(json.dumps(report, indent=2, default=str))


if __name__ == "__main__":
    main()
