"""Batch 96: score_delta, entities_by_type, top_n_scores, ExtractionConfig.merge, best_run."""

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
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(eid: str, etype: str = "PERSON") -> Entity:
    return Entity(id=eid, text=f"E{eid}", type=etype, confidence=0.8)


def _make_result(*entities: Entity) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=list(entities), relationships=[], confidence=0.8, metadata={}
    )


def _make_score(v: float) -> CriticScore:
    return CriticScore(completeness=v, consistency=v, clarity=v, granularity=v, domain_alignment=v)


class _FakeEntry:
    def __init__(self, score: float):
        self.average_score = score
        self.best_ontology = {"score": score}
        self.worst_ontology = {"score": score}


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_delta
# ---------------------------------------------------------------------------


class TestScoreDelta:
    def test_raises_on_empty(self):
        opt = OntologyOptimizer()
        with pytest.raises(IndexError):
            opt.score_delta(0, 1)

    def test_positive_delta(self):
        opt = OntologyOptimizer()
        opt._history.extend([_FakeEntry(0.3), _FakeEntry(0.8)])
        assert opt.score_delta(0, 1) == pytest.approx(0.5)

    def test_negative_delta(self):
        opt = OntologyOptimizer()
        opt._history.extend([_FakeEntry(0.8), _FakeEntry(0.3)])
        assert opt.score_delta(0, 1) == pytest.approx(-0.5)

    def test_same_index_zero(self):
        opt = OntologyOptimizer()
        opt._history.append(_FakeEntry(0.7))
        assert opt.score_delta(0, 0) == pytest.approx(0.0)

    def test_returns_float(self):
        opt = OntologyOptimizer()
        opt._history.extend([_FakeEntry(0.5), _FakeEntry(0.5)])
        assert isinstance(opt.score_delta(0, 1), float)


# ---------------------------------------------------------------------------
# OntologyGenerator.entities_by_type
# ---------------------------------------------------------------------------


class TestEntitiesByType:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_empty(self):
        assert self.gen.entities_by_type(_make_result()) == {}

    def test_groups_correctly(self):
        r = _make_result(
            _make_entity("1", "PERSON"),
            _make_entity("2", "ORG"),
            _make_entity("3", "PERSON"),
        )
        d = self.gen.entities_by_type(r)
        assert len(d["PERSON"]) == 2
        assert len(d["ORG"]) == 1

    def test_returns_dict(self):
        assert isinstance(self.gen.entities_by_type(_make_result()), dict)

    def test_missing_type_absent(self):
        r = _make_result(_make_entity("1", "PERSON"))
        d = self.gen.entities_by_type(r)
        assert "ORG" not in d


# ---------------------------------------------------------------------------
# OntologyCritic.top_n_scores
# ---------------------------------------------------------------------------


class TestTopNScores:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_empty(self):
        assert self.critic.top_n_scores([], n=3) == []

    def test_returns_top(self):
        scores = [_make_score(v) for v in [0.3, 0.9, 0.6]]
        top1 = self.critic.top_n_scores(scores, n=1)
        assert len(top1) == 1
        assert top1[0].overall == pytest.approx(scores[1].overall)

    def test_descending_order(self):
        scores = [_make_score(v) for v in [0.2, 0.8, 0.5]]
        result = self.critic.top_n_scores(scores, n=3)
        assert result[0].overall >= result[1].overall >= result[2].overall

    def test_returns_list(self):
        assert isinstance(self.critic.top_n_scores([]), list)


# ---------------------------------------------------------------------------
# ExtractionConfig.merge
# ---------------------------------------------------------------------------


class TestConfigMerge:
    def test_returns_new_instance(self):
        a = ExtractionConfig()
        b = ExtractionConfig()
        merged = a.merge(b)
        assert merged is not a and merged is not b

    def test_other_overrides_non_default(self):
        a = ExtractionConfig(max_entities=100)
        b = ExtractionConfig(max_entities=50)
        merged = a.merge(b)
        assert merged.max_entities == 50

    def test_self_preserved_when_other_default(self):
        a = ExtractionConfig(confidence_threshold=0.9)
        b = ExtractionConfig()
        merged = a.merge(b)
        assert merged.confidence_threshold == pytest.approx(0.9)

    def test_returns_extraction_config(self):
        assert isinstance(ExtractionConfig().merge(ExtractionConfig()), ExtractionConfig)


# ---------------------------------------------------------------------------
# OntologyPipeline.best_run
# ---------------------------------------------------------------------------


class TestBestRun:
    def test_none_before_runs(self):
        assert OntologyPipeline().best_run() is None

    def test_returns_highest_score_run(self):
        p = OntologyPipeline()
        p.run("Alice ACME Corp merger deal.")
        p.run("x")
        best = p.best_run()
        assert best is not None
        assert best.score.overall == max(r.score.overall for r in p.history)

    def test_none_after_reset(self):
        p = OntologyPipeline()
        p.run("Alice.")
        p.reset()
        assert p.best_run() is None
