"""Batch 95: worst_n_ontologies, score_trend, above_threshold_count, sample_entities, validate_and_report."""

from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(eid: str, conf: float = 0.8) -> Entity:
    return Entity(id=eid, text=f"E{eid}", type="PERSON", confidence=conf)


def _make_result(*entities: Entity) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=list(entities), relationships=[], confidence=0.8, metadata={}
    )


def _make_score(v: float) -> CriticScore:
    return CriticScore(completeness=v, consistency=v, clarity=v, granularity=v, domain_alignment=v)


class _FakeEntry:
    def __init__(self, score: float, best_ont=None, worst_ont=None):
        self.average_score = score
        self.best_ontology = best_ont or {"score": score}
        self.worst_ontology = worst_ont or {"score": score}


# ---------------------------------------------------------------------------
# OntologyOptimizer.worst_n_ontologies
# ---------------------------------------------------------------------------


class TestWorstNOntologies:
    def test_empty_returns_empty(self):
        assert OntologyOptimizer().worst_n_ontologies() == []

    def test_respects_n(self):
        opt = OntologyOptimizer()
        for s in [0.9, 0.5, 0.3, 0.7]:
            opt._history.append(_FakeEntry(s))
        assert len(opt.worst_n_ontologies(2)) == 2

    def test_returns_list(self):
        assert isinstance(OntologyOptimizer().worst_n_ontologies(), list)

    def test_worst_first(self):
        opt = OntologyOptimizer()
        opt._history.append(_FakeEntry(0.9, worst_ont={"score": 0.9}))
        opt._history.append(_FakeEntry(0.3, worst_ont={"score": 0.3}))
        result = opt.worst_n_ontologies(1)
        assert result[0]["score"] == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# OntologyPipeline.score_trend
# ---------------------------------------------------------------------------


class TestScoreTrend:
    def test_empty_before_runs(self):
        p = OntologyPipeline()
        assert p.score_trend() == []

    def test_length_matches_runs(self):
        p = OntologyPipeline()
        p.run("Alice.")
        p.run("Bob.")
        assert len(p.score_trend()) == 2

    def test_returns_list_of_floats(self):
        p = OntologyPipeline()
        p.run("Alice.")
        trend = p.score_trend()
        assert all(isinstance(s, float) for s in trend)

    def test_empty_after_reset(self):
        p = OntologyPipeline()
        p.run("Alice.")
        p.reset()
        assert p.score_trend() == []


# ---------------------------------------------------------------------------
# OntologyCritic.above_threshold_count
# ---------------------------------------------------------------------------


class TestAboveThresholdCount:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_empty_returns_zero(self):
        assert self.critic.above_threshold_count([]) == 0

    def test_all_above(self):
        scores = [_make_score(0.9)] * 4
        assert self.critic.above_threshold_count(scores) == 4

    def test_none_above(self):
        scores = [_make_score(0.1)] * 3
        assert self.critic.above_threshold_count(scores, threshold=0.9) == 0

    def test_partial(self):
        scores = [_make_score(0.8), _make_score(0.3), _make_score(0.7)]
        assert self.critic.above_threshold_count(scores, threshold=0.6) == 2

    def test_returns_int(self):
        assert isinstance(self.critic.above_threshold_count([]), int)


# ---------------------------------------------------------------------------
# EntityExtractionResult.sample_entities
# ---------------------------------------------------------------------------


class TestSampleEntities:
    def test_empty(self):
        assert _make_result().sample_entities(5) == []

    def test_returns_at_most_n(self):
        entities = [_make_entity(str(i)) for i in range(10)]
        result = _make_result(*entities)
        assert len(result.sample_entities(3)) <= 3

    def test_all_when_n_large(self):
        entities = [_make_entity(str(i)) for i in range(4)]
        result = _make_result(*entities)
        assert len(result.sample_entities(100)) == 4

    def test_returns_list(self):
        assert isinstance(_make_result().sample_entities(3), list)

    def test_original_unchanged(self):
        entities = [_make_entity(str(i)) for i in range(5)]
        result = _make_result(*entities)
        before = list(result.entities)
        result.sample_entities(3)
        assert result.entities == before


# ---------------------------------------------------------------------------
# LogicValidator.validate_and_report
# ---------------------------------------------------------------------------


class TestValidateAndReport:
    def setup_method(self):
        self.v = LogicValidator()

    def test_returns_string(self):
        assert isinstance(self.v.validate_and_report({"entities": [], "relationships": []}), str)

    def test_consistent_ontology(self):
        report = self.v.validate_and_report({"entities": [], "relationships": []})
        assert "CONSISTENT" in report

    def test_non_empty(self):
        assert len(self.v.validate_and_report({})) > 0
