"""Benchmark: OntologyGenerator.generate_ontology() on long text.

Run with::

    pytest benchmarks/bench_ontology_generator_generate.py -v
"""

from __future__ import annotations

import logging

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    DataType,
    ExtractionConfig,
    ExtractionStrategy,
    OntologyGenerationContext,
    OntologyGenerator,
)


@pytest.fixture(scope="module")
def generator() -> OntologyGenerator:
    log = logging.getLogger("bench.ontology_generator.generate")
    log.addHandler(logging.NullHandler())
    log.propagate = False
    log.disabled = True
    return OntologyGenerator(use_ipfs_accelerate=False, logger=log)


@pytest.fixture(scope="module")
def context() -> OntologyGenerationContext:
    return OntologyGenerationContext(
        data_source="benchmark",
        data_type=DataType.TEXT,
        domain="general",
        extraction_strategy=ExtractionStrategy.RULE_BASED,
        config=ExtractionConfig(),
    )


@pytest.fixture(scope="module")
def long_text() -> str:
    sentence = (
        "Dr. Alice Smith met Bob Johnson at Acme Corp on January 1, 2024 in New York City. "
        "USD 1,000.00 was paid to Acme Corp. "
        "The obligation of Alice is to file the report. "
    )
    # Chosen to be roughly O(10k) tokens worth of repeated content.
    return sentence * 1500


@pytest.mark.benchmark(group="ontology_generate")
def test_generate_ontology_long_text(benchmark, generator, context, long_text):
    ontology = benchmark(lambda: generator.generate_ontology(long_text, context))
    assert ontology.get("entities")
