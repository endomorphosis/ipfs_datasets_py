"""Performance benchmarks for optimizer extraction and critic evaluation.

Uses ``pytest-benchmark`` for statistical measurement.  Run with::

    pytest tests/performance/optimizers/ -v --benchmark-only

Or include in the normal test run (benchmarks are skipped automatically if
``pytest-benchmark`` is not installed, or if the ``--benchmark-disable`` flag
is passed).
"""
from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_small_ontology(n_entities: int = 20, n_rels: int = 10):
    entities = [
        {"id": f"e{i}", "text": f"Entity {i}", "type": "Person", "confidence": 0.8}
        for i in range(n_entities)
    ]
    relationships = [
        {
            "id": f"r{i}",
            "source": f"e{i % n_entities}",
            "target": f"e{(i + 1) % n_entities}",
            "type": "related_to",
            "confidence": 0.7,
        }
        for i in range(n_rels)
    ]
    return {"entities": entities, "relationships": relationships}


def _make_medium_ontology(n_entities: int = 100, n_rels: int = 50):
    return _make_small_ontology(n_entities, n_rels)


def _make_document(n_tokens: int = 1000) -> str:
    import itertools
    words = ["Alice", "Bob", "London", "Paris", "Acme", "signed", "contract",
             "agreement", "met", "visited", "on", "in", "the", "and", "a"]
    cycle = itertools.cycle(words)
    return " ".join(next(cycle) for _ in range(n_tokens))


# ---------------------------------------------------------------------------
# OntologyGenerator benchmarks
# ---------------------------------------------------------------------------

class TestExtractEntitiesBenchmarks:
    """Benchmark entity extraction at various document sizes."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            OntologyGenerator,
            ExtractionConfig,
            OntologyGenerationContext,
        )
        self.generator = OntologyGenerator()
        self.context = OntologyGenerationContext(
            data_source="bench",
            data_type="text",
            domain="general",
            config=ExtractionConfig(confidence_threshold=0.4, max_entities=200),
        )

    def test_extract_entities_1k_tokens(self, benchmark):
        doc = _make_document(1_000)
        benchmark(self.generator.extract_entities, doc, self.context)

    def test_extract_entities_5k_tokens(self, benchmark):
        doc = _make_document(5_000)
        benchmark(self.generator.extract_entities, doc, self.context)

    def test_extract_entities_10k_tokens(self, benchmark):
        doc = _make_document(10_000)
        benchmark(self.generator.extract_entities, doc, self.context)


# ---------------------------------------------------------------------------
# OntologyCritic benchmarks
# ---------------------------------------------------------------------------

class TestCriticEvaluateBenchmarks:
    """Benchmark critic evaluation at various ontology sizes."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from unittest.mock import MagicMock
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        ctx = MagicMock()
        ctx.domain = "general"
        self.critic = OntologyCritic(context=ctx)
        self.ctx = ctx

    def test_evaluate_small_ontology(self, benchmark):
        ontology = _make_small_ontology(20, 10)
        benchmark(self.critic.evaluate_ontology, ontology, self.ctx)

    def test_evaluate_medium_ontology(self, benchmark):
        ontology = _make_medium_ontology(100, 50)
        benchmark(self.critic.evaluate_ontology, ontology, self.ctx)

    def test_evaluate_large_ontology(self, benchmark):
        ontology = _make_medium_ontology(500, 250)
        benchmark(self.critic.evaluate_ontology, ontology, self.ctx)


# ---------------------------------------------------------------------------
# LogicValidator benchmarks
# ---------------------------------------------------------------------------

class TestLogicValidatorBenchmarks:
    """Benchmark TDFOL conversion and validation."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
        self.validator = LogicValidator(use_cache=True)
        self.validator_no_cache = LogicValidator(use_cache=False)

    def test_ontology_to_tdfol_small_cached(self, benchmark):
        ontology = _make_small_ontology(10, 5)
        benchmark(self.validator.ontology_to_tdfol, ontology)

    def test_ontology_to_tdfol_medium_cached(self, benchmark):
        ontology = _make_medium_ontology(50, 25)
        benchmark(self.validator.ontology_to_tdfol, ontology)

    def test_ontology_to_tdfol_medium_no_cache(self, benchmark):
        ontology = _make_medium_ontology(50, 25)
        benchmark(self.validator_no_cache.ontology_to_tdfol, ontology)
