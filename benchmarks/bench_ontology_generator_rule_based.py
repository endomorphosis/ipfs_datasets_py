"""Benchmark: OntologyGenerator._extract_rule_based() hot path.

Run with::

    pytest benchmarks/bench_ontology_generator_rule_based.py -v
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
    log = logging.getLogger("bench.ontology_generator")
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
    # Synthetic text designed to trigger multiple base patterns.
    sentence = (
        "Dr. Alice Smith met Bob Johnson at Acme Corp on January 1, 2024 in New York City. "
        "The obligation of Alice is to file the report. "
        "USD 1,000.00 was paid to Acme Corp. "
    )
    return sentence * 2000


@pytest.mark.benchmark(group="ontology_rule_based")
def test_extract_rule_based_long_text(benchmark, generator, context, long_text):
    result = benchmark(lambda: generator._extract_rule_based(long_text, context))
    assert result.entities
