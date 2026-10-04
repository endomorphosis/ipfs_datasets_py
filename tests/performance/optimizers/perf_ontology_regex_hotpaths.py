"""Micro-benchmark for OntologyGenerator regex + entity promotion hot paths.

Run manually (not collected as a test):

    python -m ipfs_datasets_py.optimizers.tests.performance.perf_ontology_regex_hotpaths
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


def _benchmark_hotpaths(iterations: int = 10) -> dict[str, float]:
    generator = OntologyGenerator(use_ipfs_accelerate=False)
    context = OntologyGenerationContext(
        data_source="perf-hotpaths",
        data_type="text",
        domain="general",
    )
    text = (
        "Acme Corp signed a contract with Beta LLC on January 5, 2026. "
        "Dr. Chen met Alice and Bob in Seattle. "
        "The backend API endpoint /v1/claims returns JSON for the web client. "
        "Ms. Rivera joined Gamma Corp in California. "
        "Payment of USD 1,250 was processed on 02/12/2026."
    )

    # Warmup to stabilize caches.
    generator._extract_rule_based(text, context)

    pattern_ms: list[float] = []
    extract_ms: list[float] = []
    promote_ms: list[float] = []

    for _ in range(iterations):
        start = time.perf_counter()
        patterns = generator._build_rule_patterns("general", None)
        pattern_ms.append((time.perf_counter() - start) * 1000.0)

        text_value = str(text)
        min_len, stopwords, allowed_types, max_conf = generator._resolve_rule_config(None)

        start = time.perf_counter()
        entities = generator._extract_entities_from_patterns(
            text_value,
            patterns,
            allowed_types,
            min_len,
            stopwords,
            max_conf,
        )
        extract_ms.append((time.perf_counter() - start) * 1000.0)

        start = time.perf_counter()
        generator._promote_person_entities(text_value, entities)
        promote_ms.append((time.perf_counter() - start) * 1000.0)

    return {
        "runs": float(iterations),
        "pattern_mean_ms": statistics.mean(pattern_ms),
        "pattern_p95_ms": _percentile(pattern_ms, 0.95),
        "extract_mean_ms": statistics.mean(extract_ms),
        "extract_p95_ms": _percentile(extract_ms, 0.95),
        "promote_mean_ms": statistics.mean(promote_ms),
        "promote_p95_ms": _percentile(promote_ms, 0.95),
    }


def main() -> None:
    stats = _benchmark_hotpaths()
    print("\nOntologyGenerator regex hot paths (smoke)\n")
    print("| Segment | Mean (ms) | P95 (ms) |")
    print("| --- | --- | --- |")
    print(f"| Pattern build | {stats['pattern_mean_ms']:.2f} | {stats['pattern_p95_ms']:.2f} |")
    print(f"| Pattern extract | {stats['extract_mean_ms']:.2f} | {stats['extract_p95_ms']:.2f} |")
    print(f"| Person promotion | {stats['promote_mean_ms']:.2f} | {stats['promote_p95_ms']:.2f} |")
    print("\nCopy the table into PERFORMANCE_TUNING_GUIDE.md for before/after tracking.")


if __name__ == "__main__":
    main()
