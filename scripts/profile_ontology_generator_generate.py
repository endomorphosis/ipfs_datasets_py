"""Profile OntologyGenerator.generate_ontology() using cProfile.

This is intended for quick local hotspot discovery (not as a CI benchmark).

Run with::

    python scripts/profile_ontology_generator_generate.py --repeats 1500 --limit 40
"""

from __future__ import annotations

import argparse
import cProfile
import io
import logging
import pstats

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    DataType,
    ExtractionConfig,
    ExtractionStrategy,
    OntologyGenerationContext,
    OntologyGenerator,
)


def _build_text(repeats: int) -> str:
    sentence = (
        "Dr. Alice Smith met Bob Johnson at Acme Corp on January 1, 2024 in New York City. "
        "USD 1,000.00 was paid to Acme Corp. "
        "The obligation of Alice is to file the report. "
    )
    return sentence * repeats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=1500)
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument(
        "--sort",
        choices=["cumulative", "tottime", "calls"],
        default="cumulative",
    )
    args = parser.parse_args()

    log = logging.getLogger("profile.ontology_generator.generate")
    log.addHandler(logging.NullHandler())
    log.propagate = False
    log.disabled = True

    generator = OntologyGenerator(use_ipfs_accelerate=False, logger=log)
    context = OntologyGenerationContext(
        data_source="profile",
        data_type=DataType.TEXT,
        domain="general",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
        config=ExtractionConfig(),
    )
    text = _build_text(args.repeats)

    def run_once():
        return generator.generate_ontology(text, context)

    # Warm caches (regex compilation, etc.)
    run_once()

    profiler = cProfile.Profile()
    profiler.runcall(run_once)

    buf = io.StringIO()
    stats = pstats.Stats(profiler, stream=buf).strip_dirs().sort_stats(args.sort)
    stats.print_stats(args.limit)
    print(buf.getvalue())

    ontology = run_once()
    meta = ontology.get("metadata", {}) if isinstance(ontology, dict) else {}
    print(
        "result:",
        {
            "entities": len(ontology.get("entities", [])),
            "relationships": len(ontology.get("relationships", [])),
            "strategy": meta.get("extraction_strategy"),
            "domain": meta.get("domain"),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
