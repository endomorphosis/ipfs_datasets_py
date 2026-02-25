"""Batch 104: best_entry, worst_entry, feedback_mean, relationship_types, clear_stash."""

from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    Relationship,
    EntityExtractionResult,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(eid: str, conf: float = 0.8) -> Entity:
    return Entity(id=eid, text=f"E{eid}", type="PERSON", confidence=conf)


def _make_rel(source: str, target: str, rtype: str = "RELATED") -> Relationship:
    return Relationship(id=f"{source}-{target}", source_id=source, target_id=target,
                        type=rtype, confidence=0.8)


def _make_result(entities=None, rels=None) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=list(entities or []),
        relationships=list(rels or []),
        confidence=0.8,
        metadata={},
    )


def _make_mediator() -> OntologyMediator:
    return OntologyMediator(OntologyGenerator(), OntologyCritic())


class _FakeEntry:
    def __init__(self, score: float):
        self.average_score = score
        self.best_ontology = {}
        self.worst_ontology = {}


# ---------------------------------------------------------------------------
# OntologyOptimizer.best_entry / worst_entry
# ---------------------------------------------------------------------------


class TestBestEntry:
    @pytest.mark.parametrize(
        "scores,expected",
        [
            ([], None),
            ([0.7], 0.7),
            ([0.3, 0.9, 0.5], 0.9),
        ],
    )
    def test_best_entry_scenarios(self, scores, expected):
        opt = OntologyOptimizer()
        entries = [_FakeEntry(score) for score in scores]
        opt._history.extend(entries)
        best = opt.best_entry()
        if expected is None:
            assert best is None
        else:
            assert best is not None
            assert best.average_score == pytest.approx(expected)


class TestWorstEntry:
    @pytest.mark.parametrize(
        "scores,expected",
        [
            ([], None),
            ([0.4], 0.4),
            ([0.3, 0.9, 0.5], 0.3),
        ],
    )
    def test_worst_entry_scenarios(self, scores, expected):
        opt = OntologyOptimizer()
        opt._history.extend([_FakeEntry(score) for score in scores])
        worst = opt.worst_entry()
        if expected is None:
            assert worst is None
        else:
            assert worst is not None
            assert worst.average_score == pytest.approx(expected)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_mean
# ---------------------------------------------------------------------------


class TestFeedbackMean:
    @pytest.mark.parametrize(
        "scores,expected",
        [
            ([], 0.0),
            ([0.6], 0.6),
            ([0.4, 0.8], 0.6),
        ],
    )
    def test_feedback_mean_scenarios(self, scores, expected):
        a = OntologyLearningAdapter()
        for score in scores:
            a.apply_feedback(score)
        assert a.feedback_mean() == pytest.approx(expected)

    def test_returns_float(self):
        assert isinstance(OntologyLearningAdapter().feedback_mean(), float)


# ---------------------------------------------------------------------------
# EntityExtractionResult.relationship_types
# ---------------------------------------------------------------------------


class TestRelationshipTypes:
    def test_empty(self):
        assert _make_result().relationship_types() == []

    def test_returns_sorted(self):
        r = _make_result([_make_entity("1"), _make_entity("2")],
                         [_make_rel("1", "2", "Z_TYPE"), _make_rel("2", "1", "A_TYPE")])
        types = r.relationship_types()
        assert types == ["A_TYPE", "Z_TYPE"]

    def test_dedup(self):
        r = _make_result([_make_entity("1"), _make_entity("2")],
                         [_make_rel("1", "2", "SAME"), _make_rel("2", "1", "SAME")])
        assert r.relationship_types() == ["SAME"]

    def test_returns_list(self):
        assert isinstance(_make_result().relationship_types(), list)


# ---------------------------------------------------------------------------
# OntologyMediator.clear_stash
# ---------------------------------------------------------------------------


class TestClearStash:
    def test_empty(self):
        m = _make_mediator()
        assert m.clear_stash() == 0

    def test_clears_all(self):
        m = _make_mediator()
        ont = {"entities": [], "relationships": []}
        m.stash(ont)
        m.stash(ont)
        count = m.clear_stash()
        assert count == 2
        assert m.snapshot_count() == 0

    def test_returns_int(self):
        assert isinstance(_make_mediator().clear_stash(), int)
