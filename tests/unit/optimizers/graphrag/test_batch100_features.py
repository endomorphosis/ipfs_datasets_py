"""Batch 100: high/low_confidence_entities, scores_above_threshold, recent_score_mean, feedback_count_above."""

from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter


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
    return CriticScore(completeness=v, consistency=v, clarity=v, granularity=v, relationship_coherence=v, domain_alignment=v)


class _FakeEntry:
    def __init__(self, score: float):
        self.average_score = score
        self.best_ontology = {}
        self.worst_ontology = {}


# ---------------------------------------------------------------------------
# EntityExtractionResult.high_confidence_entities
# ---------------------------------------------------------------------------


class TestHighConfidenceEntities:
    def test_empty(self):
        assert _make_result().high_confidence_entities() == []

    def test_filters_above(self):
        r = _make_result(_make_entity("1", 0.9), _make_entity("2", 0.5))
        result = r.high_confidence_entities(threshold=0.8)
        assert len(result) == 1
        assert result[0].id == "1"

    def test_inclusive_threshold(self):
        r = _make_result(_make_entity("1", 0.8))
        assert len(r.high_confidence_entities(threshold=0.8)) == 1

    def test_returns_list(self):
        assert isinstance(_make_result().high_confidence_entities(), list)


# ---------------------------------------------------------------------------
# EntityExtractionResult.low_confidence_entities
# ---------------------------------------------------------------------------


class TestLowConfidenceEntities:
    def test_empty(self):
        assert _make_result().low_confidence_entities() == []

    def test_filters_below(self):
        r = _make_result(_make_entity("1", 0.3), _make_entity("2", 0.8))
        result = r.low_confidence_entities(threshold=0.5)
        assert len(result) == 1
        assert result[0].id == "1"

    def test_exclusive_threshold(self):
        r = _make_result(_make_entity("1", 0.5))
        # exactly 0.5 is NOT below the default threshold of 0.5
        assert len(r.low_confidence_entities(threshold=0.5)) == 0

    def test_returns_list(self):
        assert isinstance(_make_result().low_confidence_entities(), list)


# ---------------------------------------------------------------------------
# OntologyCritic.scores_above_threshold
# ---------------------------------------------------------------------------


class TestScoresAboveThreshold:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_empty(self):
        assert self.critic.scores_above_threshold([]) == []

    def test_filters(self):
        scores = [_make_score(0.4), _make_score(0.8)]
        result = self.critic.scores_above_threshold(scores, threshold=0.6)
        assert len(result) == 1
        assert result[0].overall > 0.6

    def test_exclusive(self):
        scores = [_make_score(0.6)]
        # exactly 0.6 should NOT pass strict >0.6 check
        assert self.critic.scores_above_threshold(scores, threshold=0.6) == []

    def test_returns_list(self):
        assert isinstance(self.critic.scores_above_threshold([]), list)


# ---------------------------------------------------------------------------
# OntologyOptimizer.recent_score_mean
# ---------------------------------------------------------------------------


class TestRecentScoreMean:
    def test_empty(self):
        assert OntologyOptimizer().recent_score_mean() == pytest.approx(0.0)

    def test_uses_last_n(self):
        opt = OntologyOptimizer()
        opt._history.extend([_FakeEntry(0.1), _FakeEntry(0.9), _FakeEntry(0.9)])
        # last 2 are 0.9 each
        assert opt.recent_score_mean(n=2) == pytest.approx(0.9)

    def test_all_when_n_large(self):
        opt = OntologyOptimizer()
        opt._history.extend([_FakeEntry(0.4), _FakeEntry(0.6)])
        assert opt.recent_score_mean(n=100) == pytest.approx(0.5)

    def test_returns_float(self):
        assert isinstance(OntologyOptimizer().recent_score_mean(), float)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_count_above
# ---------------------------------------------------------------------------


class TestFeedbackCountAbove:
    def test_empty(self):
        assert OntologyLearningAdapter().feedback_count_above() == 0

    def test_counts_above(self):
        a = OntologyLearningAdapter()
        for score in [0.3, 0.7, 0.9]:
            a.apply_feedback(score)
        assert a.feedback_count_above(threshold=0.6) == 2

    def test_exclusive(self):
        a = OntologyLearningAdapter()
        a.apply_feedback(0.6)
        assert a.feedback_count_above(threshold=0.6) == 0

    def test_returns_int(self):
        assert isinstance(OntologyLearningAdapter().feedback_count_above(), int)
