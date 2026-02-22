"""Batch 83: top_entities, most_frequent_action, dimension_gap, by_id, worst_feedback_scores."""

from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    OntologyGenerator,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    FeedbackRecord,
    OntologyLearningAdapter,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(eid: str, text: str, conf: float = 0.8) -> Entity:
    return Entity(id=eid, text=text, type="TEST", confidence=conf)


def _make_result(*entities: Entity) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=list(entities), relationships=[], confidence=0.8, metadata={}
    )


def _make_mediator():
    gen = OntologyGenerator()
    crit = OntologyCritic()
    return OntologyMediator(gen, crit)


def _make_score(c=0.8, con=0.7, cl=0.6, g=0.5, da=0.9) -> CriticScore:
    return CriticScore(
        completeness=c, consistency=con, clarity=cl, granularity=g, relationship_coherence=da
    , domain_alignment=da
    )


# ---------------------------------------------------------------------------
# OntologyGenerator.top_entities
# ---------------------------------------------------------------------------


class TestTopEntities:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_empty_result(self):
        r = _make_result()
        assert self.gen.top_entities(r) == []

    def test_fewer_than_n(self):
        e1 = _make_entity("1", "Alice", 0.8)
        r = _make_result(e1)
        assert len(self.gen.top_entities(r, n=5)) == 1

    def test_top_n_returns_n(self):
        entities = [_make_entity(str(i), f"E{i}", i * 0.1) for i in range(1, 11)]
        r = _make_result(*entities)
        top = self.gen.top_entities(r, n=3)
        assert len(top) == 3

    def test_sorted_descending(self):
        e1 = _make_entity("1", "Alice", 0.3)
        e2 = _make_entity("2", "Bob", 0.9)
        e3 = _make_entity("3", "Carol", 0.6)
        r = _make_result(e1, e2, e3)
        top = self.gen.top_entities(r, n=3)
        confs = [e.confidence for e in top]
        assert confs == sorted(confs, reverse=True)

    def test_first_is_highest(self):
        entities = [_make_entity(str(i), f"E{i}", i * 0.1) for i in range(1, 6)]
        r = _make_result(*entities)
        top = self.gen.top_entities(r, n=1)
        assert top[0].confidence == max(e.confidence for e in r.entities)

    def test_default_n_10(self):
        entities = [_make_entity(str(i), f"E{i}") for i in range(15)]
        r = _make_result(*entities)
        assert len(self.gen.top_entities(r)) == 10


# ---------------------------------------------------------------------------
# OntologyMediator.most_frequent_action
# ---------------------------------------------------------------------------


class TestMostFrequentAction:
    def test_empty_returns_none(self):
        med = _make_mediator()
        assert med.most_frequent_action() is None

    def test_single_action(self):
        med = _make_mediator()
        med._action_counts["add_entity"] = 1
        assert med.most_frequent_action() == "add_entity"

    def test_highest_count(self):
        med = _make_mediator()
        med._action_counts["add_entity"] = 2
        med._action_counts["merge"] = 10
        med._action_counts["prune"] = 5
        assert med.most_frequent_action() == "merge"

    def test_returns_string(self):
        med = _make_mediator()
        med._action_counts["x"] = 1
        assert isinstance(med.most_frequent_action(), str)

    def test_cleared_returns_none(self):
        med = _make_mediator()
        med._action_counts["x"] = 1
        med._action_counts.clear()
        assert med.most_frequent_action() is None


# ---------------------------------------------------------------------------
# OntologyCritic.dimension_gap
# ---------------------------------------------------------------------------


class TestDimensionGap:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_all_dims_present(self):
        score = _make_score()
        gaps = self.critic.dimension_gap(score)
        for key in ["completeness", "consistency", "clarity", "granularity", "domain_alignment"]:
            assert key in gaps

    def test_positive_gap_below_target(self):
        score = _make_score(c=0.5, con=0.5, cl=0.5, g=0.5, da=0.5)
        gaps = self.critic.dimension_gap(score, target=1.0)
        assert all(v > 0 for v in gaps.values())

    def test_zero_gap_at_target(self):
        score = _make_score(c=1.0, con=1.0, cl=1.0, g=1.0, da=1.0)
        gaps = self.critic.dimension_gap(score, target=1.0)
        for v in gaps.values():
            assert abs(v) < 1e-6

    def test_custom_target(self):
        score = _make_score(c=0.7)
        gaps = self.critic.dimension_gap(score, target=0.7)
        assert abs(gaps["completeness"]) < 1e-6

    def test_returns_dict(self):
        assert isinstance(self.critic.dimension_gap(_make_score()), dict)

    def test_gap_correct_value(self):
        score = _make_score(c=0.6)
        gap = self.critic.dimension_gap(score, target=1.0)["completeness"]
        assert gap == pytest.approx(0.4, abs=1e-5)


# ---------------------------------------------------------------------------
# EntityExtractionResult.by_id
# ---------------------------------------------------------------------------


class TestById:
    def test_found(self):
        e1 = _make_entity("abc", "Alice")
        r = _make_result(e1)
        found = r.by_id("abc")
        assert found is e1

    def test_not_found_returns_none(self):
        r = _make_result()
        assert r.by_id("missing") is None

    def test_empty_result(self):
        r = _make_result()
        assert r.by_id("any") is None

    def test_multiple_entities_correct_one(self):
        e1 = _make_entity("1", "Alice")
        e2 = _make_entity("2", "Bob")
        r = _make_result(e1, e2)
        assert r.by_id("2") is e2

    def test_returns_entity_object(self):
        e1 = _make_entity("x1", "Alice")
        r = _make_result(e1)
        result = r.by_id("x1")
        assert isinstance(result, Entity)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.worst_feedback_scores
# ---------------------------------------------------------------------------


class TestWorstFeedbackScores:
    def test_empty_returns_empty(self):
        adapter = OntologyLearningAdapter()
        assert adapter.worst_feedback_scores() == []

    def test_sorted_ascending(self):
        adapter = OntologyLearningAdapter()
        for v in [0.9, 0.3, 0.5]:
            adapter._feedback.append(FeedbackRecord(final_score=v))
        worst = adapter.worst_feedback_scores(3)
        scores = [r.final_score for r in worst]
        assert scores == sorted(scores)

    def test_respects_n(self):
        adapter = OntologyLearningAdapter()
        for v in [0.1, 0.5, 0.8, 0.9]:
            adapter._feedback.append(FeedbackRecord(final_score=v))
        assert len(adapter.worst_feedback_scores(2)) == 2

    def test_first_is_lowest(self):
        adapter = OntologyLearningAdapter()
        for v in [0.7, 0.2, 0.5]:
            adapter._feedback.append(FeedbackRecord(final_score=v))
        worst = adapter.worst_feedback_scores(1)
        assert worst[0].final_score == pytest.approx(0.2, abs=1e-5)

    def test_n_larger_than_feedback_returns_all(self):
        adapter = OntologyLearningAdapter()
        for v in [0.4, 0.6]:
            adapter._feedback.append(FeedbackRecord(final_score=v))
        assert len(adapter.worst_feedback_scores(100)) == 2
