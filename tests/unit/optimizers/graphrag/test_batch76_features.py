"""Batch-76 feature tests.

Covers:
- OntologyGenerator.merge_results(results)
- EntityExtractionResult.highest_confidence_entity()
- Entity.to_text()
- OntologyPipeline.summary()
- OntologyCritic.dimension_report(score)
"""

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    OntologyGenerator,
    OntologyGenerationContext,
    Relationship,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entity(eid="e1", etype="Person", text="Alice", conf=0.9):
    return Entity(id=eid, type=etype, text=text, confidence=conf)


def _result(*entities, rels=None):
    return EntityExtractionResult(
        entities=list(entities),
        relationships=list(rels or []),
        confidence=0.8,
    )


def _score(**kw):
    defaults = dict(completeness=0.7, consistency=0.8, clarity=0.6, granularity=0.5, domain_alignment=0.9)
    defaults.update(kw)
    return CriticScore(**defaults)


# ---------------------------------------------------------------------------
# OntologyGenerator.merge_results
# ---------------------------------------------------------------------------

class TestMergeResults:
    def test_empty_returns_empty_result(self):
        gen = OntologyGenerator()
        r = gen.merge_results([])
        assert r.entities == []
        assert r.confidence == 0.0

    def test_single_result(self):
        gen = OntologyGenerator()
        r1 = _result(_entity())
        merged = gen.merge_results([r1])
        assert len(merged.entities) == 1

    def test_combines_entities(self):
        gen = OntologyGenerator()
        r1 = _result(_entity("e1"))
        r2 = _result(_entity("e2", "Org"))
        merged = gen.merge_results([r1, r2])
        assert len(merged.entities) == 2

    def test_combines_relationships(self):
        gen = OntologyGenerator()
        e1, e2 = _entity("e1"), _entity("e2", "Org")
        rel = Relationship(id="r1", source_id="e1", target_id="e2", type="knows")
        r1 = _result(e1, e2, rels=[rel])
        r2 = _result(_entity("e3"))
        merged = gen.merge_results([r1, r2])
        assert len(merged.relationships) == 1

    def test_confidence_is_mean(self):
        gen = OntologyGenerator()
        r1 = EntityExtractionResult(entities=[], relationships=[], confidence=0.6)
        r2 = EntityExtractionResult(entities=[], relationships=[], confidence=0.4)
        merged = gen.merge_results([r1, r2])
        assert abs(merged.confidence - 0.5) < 1e-9

    def test_returns_extraction_result(self):
        gen = OntologyGenerator()
        assert isinstance(gen.merge_results([_result()]), EntityExtractionResult)


# ---------------------------------------------------------------------------
# EntityExtractionResult.highest_confidence_entity
# ---------------------------------------------------------------------------

class TestHighestConfidenceEntity:
    def test_empty_returns_none(self):
        r = _result()
        assert r.highest_confidence_entity() is None

    def test_returns_entity(self):
        r = _result(_entity())
        assert isinstance(r.highest_confidence_entity(), Entity)

    def test_returns_max_confidence(self):
        e1 = _entity("e1", conf=0.5)
        e2 = _entity("e2", conf=0.95)
        e3 = _entity("e3", conf=0.7)
        r = _result(e1, e2, e3)
        best = r.highest_confidence_entity()
        assert best.id == "e2"

    def test_single_entity(self):
        e = _entity("e1", conf=0.8)
        r = _result(e)
        assert r.highest_confidence_entity().id == "e1"


# ---------------------------------------------------------------------------
# Entity.to_text
# ---------------------------------------------------------------------------

class TestEntityToText:
    def test_returns_string(self):
        e = _entity()
        assert isinstance(e.to_text(), str)

    def test_contains_text(self):
        e = _entity(text="Alice")
        assert "Alice" in e.to_text()

    def test_contains_type(self):
        e = _entity(etype="Person")
        assert "Person" in e.to_text()

    def test_contains_confidence(self):
        e = _entity(conf=0.75)
        assert "0.75" in e.to_text()

    def test_format(self):
        e = _entity(text="Bob", etype="Org", conf=0.5)
        assert e.to_text() == "Bob (Org, conf=0.50)"


# ---------------------------------------------------------------------------
# OntologyPipeline.summary
# ---------------------------------------------------------------------------

class TestPipelineSummary:
    def test_returns_string(self):
        assert isinstance(OntologyPipeline().summary(), str)

    def test_contains_domain(self):
        p = OntologyPipeline(domain="legal")
        assert "legal" in p.summary()

    def test_contains_ontologypipeline(self):
        assert "OntologyPipeline" in OntologyPipeline().summary()

    def test_nonempty(self):
        assert len(OntologyPipeline().summary()) > 0


# ---------------------------------------------------------------------------
# OntologyCritic.dimension_report
# ---------------------------------------------------------------------------

class TestDimensionReport:
    def test_returns_string(self):
        critic = OntologyCritic(use_llm=False)
        assert isinstance(critic.dimension_report(_score()), str)

    def test_contains_all_dimensions(self):
        critic = OntologyCritic(use_llm=False)
        report = critic.dimension_report(_score())
        for dim in ("completeness", "consistency", "clarity", "granularity", "domain_alignment"):
            assert dim in report

    def test_contains_overall(self):
        critic = OntologyCritic(use_llm=False)
        assert "overall" in critic.dimension_report(_score())

    def test_multiline(self):
        critic = OntologyCritic(use_llm=False)
        lines = critic.dimension_report(_score()).split("\n")
        assert len(lines) >= 6  # 5 dims + overall

    def test_has_float_values(self):
        critic = OntologyCritic(use_llm=False)
        report = critic.dimension_report(_score())
        assert "0." in report
