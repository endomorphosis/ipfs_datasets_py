"""Batch 99: relationship_count, score_range, run_count, entity_by_id, feedback_score_range."""

from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
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


class _FakeEntry:
    def __init__(self, score: float):
        self.average_score = score
        self.best_ontology = {}
        self.worst_ontology = {}


# ---------------------------------------------------------------------------
# LogicValidator.relationship_count
# ---------------------------------------------------------------------------


class TestValidatorRelationshipCount:
    def setup_method(self):
        self.v = LogicValidator()

    def test_empty(self):
        assert self.v.relationship_count({"relationships": []}) == 0

    def test_counts(self):
        ont = {"relationships": [{"id": "r1"}, {"id": "r2"}]}
        assert self.v.relationship_count(ont) == 2

    def test_fallback_edges(self):
        assert self.v.relationship_count({"edges": [{"id": "e1"}]}) == 1

    def test_no_key_zero(self):
        assert self.v.relationship_count({}) == 0

    def test_returns_int(self):
        assert isinstance(self.v.relationship_count({}), int)


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_range
# ---------------------------------------------------------------------------


class TestOptimizerScoreRange:
    def test_empty(self):
        assert OntologyOptimizer().score_range() == (0.0, 0.0)

    def test_single(self):
        opt = OntologyOptimizer()
        opt._history.append(_FakeEntry(0.7))
        lo, hi = opt.score_range()
        assert lo == pytest.approx(0.7)
        assert hi == pytest.approx(0.7)

    def test_range(self):
        opt = OntologyOptimizer()
        opt._history.extend([_FakeEntry(0.3), _FakeEntry(0.9)])
        lo, hi = opt.score_range()
        assert lo == pytest.approx(0.3)
        assert hi == pytest.approx(0.9)

    def test_returns_tuple(self):
        assert isinstance(OntologyOptimizer().score_range(), tuple)


# ---------------------------------------------------------------------------
# OntologyPipeline.run_count
# ---------------------------------------------------------------------------


class TestPipelineRunCount:
    def test_zero_before_runs(self):
        assert OntologyPipeline().run_count() == 0

    def test_increments(self):
        p = OntologyPipeline()
        p.run("Alice founded ACME Corp.")
        assert p.run_count() == 1
        p.run("Bob joined.")
        assert p.run_count() == 2

    def test_zero_after_reset(self):
        p = OntologyPipeline()
        p.run("text")
        p.reset()
        assert p.run_count() == 0

    def test_returns_int(self):
        assert isinstance(OntologyPipeline().run_count(), int)


# ---------------------------------------------------------------------------
# EntityExtractionResult.entity_by_id
# ---------------------------------------------------------------------------


class TestEntityById:
    def test_found(self):
        e = _make_entity("e42")
        r = _make_result(e)
        assert r.entity_by_id("e42") is e

    def test_not_found(self):
        r = _make_result(_make_entity("e1"))
        assert r.entity_by_id("xyz") is None

    def test_empty(self):
        assert _make_result().entity_by_id("x") is None

    def test_returns_entity_type(self):
        e = _make_entity("e1")
        r = _make_result(e)
        assert isinstance(r.entity_by_id("e1"), Entity)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_score_range
# ---------------------------------------------------------------------------


class TestFeedbackScoreRange:
    def test_empty(self):
        assert OntologyLearningAdapter().feedback_score_range() == (0.0, 0.0)

    def test_range(self):
        a = OntologyLearningAdapter()
        a.apply_feedback(0.2)
        a.apply_feedback(0.8)
        lo, hi = a.feedback_score_range()
        assert lo == pytest.approx(0.2)
        assert hi == pytest.approx(0.8)

    def test_single(self):
        a = OntologyLearningAdapter()
        a.apply_feedback(0.5)
        lo, hi = a.feedback_score_range()
        assert lo == hi == pytest.approx(0.5)

    def test_returns_tuple(self):
        assert isinstance(OntologyLearningAdapter().feedback_score_range(), tuple)
