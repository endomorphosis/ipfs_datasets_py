"""Batch 86: ExtractionConfig.summary, mean_score, filter_by_type, score_mean, entity_count."""

from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    ExtractionConfig,
    OntologyGenerator,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    OntologyLearningAdapter,
    FeedbackRecord,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(eid: str, text: str, etype: str = "PERSON", conf: float = 0.8) -> Entity:
    return Entity(id=eid, text=text, type=etype, confidence=conf)


def _make_result(*entities: Entity) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=list(entities), relationships=[], confidence=0.8, metadata={}
    )


def _make_score(c=0.8, con=0.7, cl=0.6, g=0.5, da=0.9) -> CriticScore:
    return CriticScore(
        completeness=c, consistency=con, clarity=cl, granularity=g, domain_alignment=da
    )


def _make_feedback(score: float) -> FeedbackRecord:
    return FeedbackRecord(final_score=score)


# ---------------------------------------------------------------------------
# ExtractionConfig.summary
# ---------------------------------------------------------------------------


class TestExtractionConfigSummary:
    def test_returns_string(self):
        cfg = ExtractionConfig()
        assert isinstance(cfg.summary(), str)

    def test_contains_threshold(self):
        cfg = ExtractionConfig(confidence_threshold=0.75)
        assert "0.75" in cfg.summary()

    def test_contains_max_entities(self):
        cfg = ExtractionConfig(max_entities=50)
        assert "50" in cfg.summary()

    def test_contains_max_relationships(self):
        cfg = ExtractionConfig(max_relationships=300)
        assert "300" in cfg.summary()

    def test_non_empty(self):
        assert len(ExtractionConfig().summary()) > 0


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.mean_score
# ---------------------------------------------------------------------------


class TestMeanScore:
    def test_empty_returns_zero(self):
        adapter = OntologyLearningAdapter()
        assert adapter.mean_score() == pytest.approx(0.0)

    def test_single_record(self):
        adapter = OntologyLearningAdapter()
        adapter._feedback.append(_make_feedback(0.8))
        assert adapter.mean_score() == pytest.approx(0.8)

    def test_multiple_records(self):
        adapter = OntologyLearningAdapter()
        for s in [0.4, 0.6, 0.8]:
            adapter._feedback.append(_make_feedback(s))
        assert adapter.mean_score() == pytest.approx(0.6)

    def test_returns_float(self):
        adapter = OntologyLearningAdapter()
        assert isinstance(adapter.mean_score(), float)


# ---------------------------------------------------------------------------
# EntityExtractionResult.filter_by_type
# ---------------------------------------------------------------------------


class TestFilterByType:
    def test_keeps_matching_type(self):
        e_org = _make_entity("1", "ACME", etype="ORG")
        e_per = _make_entity("2", "Alice", etype="PERSON")
        result = _make_result(e_org, e_per)
        filtered = result.filter_by_type("ORG")
        assert all(e.type == "ORG" for e in filtered.entities)
        assert len(filtered.entities) == 1

    def test_case_insensitive_default(self):
        e = _make_entity("1", "X", etype="ORG")
        result = _make_result(e)
        filtered = result.filter_by_type("org")
        assert len(filtered.entities) == 1

    def test_case_sensitive(self):
        e = _make_entity("1", "X", etype="ORG")
        result = _make_result(e)
        assert len(result.filter_by_type("org", case_sensitive=True).entities) == 0

    def test_empty_if_no_match(self):
        e = _make_entity("1", "X", etype="PERSON")
        result = _make_result(e)
        assert result.filter_by_type("LOC").entities == []

    def test_returns_extraction_result(self):
        result = _make_result()
        assert isinstance(result.filter_by_type("X"), EntityExtractionResult)


# ---------------------------------------------------------------------------
# OntologyCritic.score_mean
# ---------------------------------------------------------------------------


class TestScoreMean:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_empty_returns_zero(self):
        assert self.critic.score_mean([]) == pytest.approx(0.0)

    def test_single_score(self):
        s = _make_score(c=1.0, con=1.0, cl=1.0, g=1.0, da=1.0)
        assert self.critic.score_mean([s]) == pytest.approx(1.0)

    def test_mean_of_two(self):
        high = _make_score(c=1.0, con=1.0, cl=1.0, g=1.0, da=1.0)
        low = _make_score(c=0.0, con=0.0, cl=0.0, g=0.0, da=0.0)
        mean = self.critic.score_mean([high, low])
        assert 0.0 < mean < 1.0

    def test_returns_float(self):
        assert isinstance(self.critic.score_mean([_make_score()]), float)


# ---------------------------------------------------------------------------
# OntologyGenerator.entity_count
# ---------------------------------------------------------------------------


class TestEntityCount:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_empty(self):
        assert self.gen.entity_count(_make_result()) == 0

    def test_non_empty(self):
        r = _make_result(_make_entity("1", "A"), _make_entity("2", "B"))
        assert self.gen.entity_count(r) == 2

    def test_returns_int(self):
        assert isinstance(self.gen.entity_count(_make_result()), int)
