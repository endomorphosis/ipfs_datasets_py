"""Batch 80: count_entities_by_type, top_feedback_scores, span_coverage,
bottom_dimension, reset_all_state."""

from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    OntologyGenerator,
    Relationship,
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


def _make_entity(eid: str, text: str, etype: str = "TEST", conf: float = 0.8, span=None) -> Entity:
    return Entity(id=eid, text=text, type=etype, confidence=conf, source_span=span)


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
        completeness=c, consistency=con, clarity=cl, granularity=g, domain_alignment=da
    )


# ---------------------------------------------------------------------------
# OntologyGenerator.count_entities_by_type
# ---------------------------------------------------------------------------


class TestCountEntitiesByType:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_empty_result(self):
        r = _make_result()
        assert self.gen.count_entities_by_type(r) == {}

    def test_single_type(self):
        e1 = _make_entity("1", "Alice", "Person")
        e2 = _make_entity("2", "Bob", "Person")
        r = _make_result(e1, e2)
        counts = self.gen.count_entities_by_type(r)
        assert counts["Person"] == 2

    def test_multiple_types(self):
        e1 = _make_entity("1", "Alice", "Person")
        e2 = _make_entity("2", "ACME", "Org")
        r = _make_result(e1, e2)
        counts = self.gen.count_entities_by_type(r)
        assert counts["Person"] == 1
        assert counts["Org"] == 1

    def test_sorted_by_frequency(self):
        entities = [
            _make_entity(str(i), f"E{i}", "Person") for i in range(5)
        ] + [
            _make_entity("10", "ACME", "Org")
        ]
        r = _make_result(*entities)
        counts = self.gen.count_entities_by_type(r)
        keys = list(counts.keys())
        assert keys[0] == "Person"

    def test_returns_dict(self):
        r = _make_result()
        assert isinstance(self.gen.count_entities_by_type(r), dict)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.top_feedback_scores
# ---------------------------------------------------------------------------


class TestTopFeedbackScores:
    def test_empty_returns_empty(self):
        adapter = OntologyLearningAdapter()
        assert adapter.top_feedback_scores() == []

    def test_returns_sorted_descending(self):
        adapter = OntologyLearningAdapter()
        for v in [0.3, 0.9, 0.5]:
            adapter._feedback.append(FeedbackRecord(final_score=v))
        top = adapter.top_feedback_scores(3)
        scores = [r.final_score for r in top]
        assert scores == sorted(scores, reverse=True)

    def test_respects_n(self):
        adapter = OntologyLearningAdapter()
        for v in [0.1, 0.5, 0.8, 0.9]:
            adapter._feedback.append(FeedbackRecord(final_score=v))
        top = adapter.top_feedback_scores(2)
        assert len(top) == 2

    def test_top_has_highest_score(self):
        adapter = OntologyLearningAdapter()
        for v in [0.2, 0.7, 0.5]:
            adapter._feedback.append(FeedbackRecord(final_score=v))
        top = adapter.top_feedback_scores(1)
        assert top[0].final_score == pytest.approx(0.7, abs=1e-5)

    def test_returns_list_of_feedback_records(self):
        adapter = OntologyLearningAdapter()
        adapter._feedback.append(FeedbackRecord(final_score=0.6))
        top = adapter.top_feedback_scores()
        assert isinstance(top, list)
        assert isinstance(top[0], FeedbackRecord)

    def test_n_larger_than_feedback_returns_all(self):
        adapter = OntologyLearningAdapter()
        for v in [0.3, 0.7]:
            adapter._feedback.append(FeedbackRecord(final_score=v))
        assert len(adapter.top_feedback_scores(100)) == 2


# ---------------------------------------------------------------------------
# EntityExtractionResult.span_coverage
# ---------------------------------------------------------------------------


class TestSpanCoverage:
    def test_no_spans_returns_zero(self):
        e1 = _make_entity("1", "Alice", span=None)
        r = _make_result(e1)
        assert r.span_coverage(100) == pytest.approx(0.0)

    def test_full_coverage(self):
        e1 = _make_entity("1", "Alice", span=(0, 100))
        r = _make_result(e1)
        assert r.span_coverage(100) == pytest.approx(1.0)

    def test_partial_coverage(self):
        e1 = _make_entity("1", "Alice", span=(0, 50))
        r = _make_result(e1)
        assert r.span_coverage(100) == pytest.approx(0.5)

    def test_overlapping_spans_not_double_counted(self):
        e1 = _make_entity("1", "Alice", span=(0, 60))
        e2 = _make_entity("2", "Bob", span=(40, 80))
        r = _make_result(e1, e2)
        assert r.span_coverage(100) == pytest.approx(0.8)

    def test_zero_text_length_returns_zero(self):
        e1 = _make_entity("1", "Alice", span=(0, 5))
        r = _make_result(e1)
        assert r.span_coverage(0) == pytest.approx(0.0)

    def test_capped_at_one(self):
        e1 = _make_entity("1", "Alice", span=(0, 200))
        r = _make_result(e1)
        assert r.span_coverage(100) == pytest.approx(1.0)

    def test_empty_result(self):
        r = _make_result()
        assert r.span_coverage(100) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# OntologyCritic.bottom_dimension
# ---------------------------------------------------------------------------


class TestBottomDimension:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_granularity_lowest(self):
        score = _make_score(c=0.9, con=0.8, cl=0.7, g=0.1, da=0.9)
        assert self.critic.bottom_dimension(score) == "granularity"

    def test_clarity_lowest(self):
        score = _make_score(c=0.9, con=0.8, cl=0.05, g=0.7, da=0.9)
        assert self.critic.bottom_dimension(score) == "clarity"

    def test_returns_string(self):
        score = _make_score()
        assert isinstance(self.critic.bottom_dimension(score), str)

    def test_valid_dimension_name(self):
        score = _make_score()
        valid = {"completeness", "consistency", "clarity", "granularity", "domain_alignment"}
        assert self.critic.bottom_dimension(score) in valid

    def test_opposite_of_top_dimension(self):
        score = _make_score(c=0.05, con=0.5, cl=0.5, g=0.5, da=0.99)
        assert self.critic.bottom_dimension(score) == "completeness"
        assert self.critic.top_dimension(score) == "domain_alignment"


# ---------------------------------------------------------------------------
# OntologyMediator.reset_all_state
# ---------------------------------------------------------------------------


class TestResetAllState:
    def test_clears_action_counts(self):
        med = _make_mediator()
        med._action_counts["add_entity"] = 3
        med.reset_all_state()
        assert med.get_action_stats() == {}

    def test_clears_undo_stack(self):
        med = _make_mediator()
        med._undo_stack.append({"x": 1})
        med.reset_all_state()
        assert med.get_undo_depth() == 0

    def test_clears_action_entries(self):
        med = _make_mediator()
        med._action_entries.append({"action": "merge", "round": 1})
        med.reset_all_state()
        assert med.action_log() == []

    def test_clears_recommendation_counts(self):
        med = _make_mediator()
        med._recommendation_counts["add more entities"] = 2
        med.reset_all_state()
        assert med.get_recommendation_stats() == {}

    def test_round_count_zero_after_reset(self):
        med = _make_mediator()
        med._undo_stack.append({})
        med.reset_all_state()
        assert med.get_round_count() == 0
