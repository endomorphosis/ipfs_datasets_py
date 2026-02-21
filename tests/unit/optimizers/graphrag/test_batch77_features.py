"""Batch 77: ExtractionConfig.copy, feedback_summary, get_round_count,
score_delta, filter_by_span."""

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


def _make_entity(eid: str, text: str, span: tuple | None = None) -> Entity:
    return Entity(id=eid, text=text, entity_type="TEST", confidence=0.8, source_span=span)


def _make_result(*entities: Entity) -> EntityExtractionResult:
    return EntityExtractionResult(entities=list(entities), relationships=[], confidence=0.8, metadata={})


def _make_mediator():
    gen = OntologyGenerator()
    crit = OntologyCritic()
    return OntologyMediator(gen, crit)


def _make_score(c=0.8, con=0.7, cl=0.6, g=0.5, da=0.9) -> CriticScore:
    return CriticScore(
        completeness=c,
        consistency=con,
        clarity=cl,
        granularity=g,
        domain_alignment=da,
    )


# ---------------------------------------------------------------------------
# ExtractionConfig.copy
# ---------------------------------------------------------------------------


class TestExtractionConfigCopy:
    def test_copy_returns_new_instance(self):
        cfg = ExtractionConfig(confidence_threshold=0.7)
        c2 = cfg.copy()
        assert c2 is not cfg

    def test_copy_values_equal(self):
        cfg = ExtractionConfig(confidence_threshold=0.6, max_entities=50)
        c2 = cfg.copy()
        assert c2.confidence_threshold == cfg.confidence_threshold
        assert c2.max_entities == cfg.max_entities

    def test_copy_is_independent(self):
        cfg = ExtractionConfig(confidence_threshold=0.5)
        c2 = cfg.copy()
        c2.confidence_threshold = 0.9
        assert cfg.confidence_threshold == 0.5

    def test_copy_preserves_min_entity_length(self):
        cfg = ExtractionConfig(min_entity_length=4)
        assert cfg.copy().min_entity_length == 4

    def test_copy_preserves_max_entities(self):
        cfg = ExtractionConfig(max_entities=50)
        assert cfg.copy().max_entities == 50

    def test_copy_default_config(self):
        cfg = ExtractionConfig()
        c2 = cfg.copy()
        assert c2.confidence_threshold == cfg.confidence_threshold


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_summary
# ---------------------------------------------------------------------------


class TestFeedbackSummary:
    def test_empty_returns_zero_count(self):
        adapter = OntologyLearningAdapter()
        s = adapter.feedback_summary()
        assert s["count"] == 0

    def test_empty_scores_are_zero(self):
        adapter = OntologyLearningAdapter()
        s = adapter.feedback_summary()
        assert s["mean_score"] == 0.0
        assert s["min_score"] == 0.0
        assert s["max_score"] == 0.0

    def test_empty_includes_threshold(self):
        adapter = OntologyLearningAdapter(base_threshold=0.42)
        s = adapter.feedback_summary()
        assert s["current_threshold"] == pytest.approx(0.42, abs=1e-6)

    def test_single_record(self):
        adapter = OntologyLearningAdapter()
        adapter._feedback.append(FeedbackRecord(final_score=0.7))
        s = adapter.feedback_summary()
        assert s["count"] == 1
        assert s["mean_score"] == pytest.approx(0.7, abs=1e-5)
        assert s["min_score"] == pytest.approx(0.7, abs=1e-5)
        assert s["max_score"] == pytest.approx(0.7, abs=1e-5)

    def test_multiple_records_mean(self):
        adapter = OntologyLearningAdapter()
        for v in [0.5, 0.7, 0.9]:
            adapter._feedback.append(FeedbackRecord(final_score=v))
        s = adapter.feedback_summary()
        assert s["mean_score"] == pytest.approx(0.7, abs=1e-5)

    def test_multiple_records_min_max(self):
        adapter = OntologyLearningAdapter()
        for v in [0.2, 0.5, 0.8]:
            adapter._feedback.append(FeedbackRecord(final_score=v))
        s = adapter.feedback_summary()
        assert s["min_score"] == pytest.approx(0.2, abs=1e-5)
        assert s["max_score"] == pytest.approx(0.8, abs=1e-5)

    def test_returns_dict(self):
        adapter = OntologyLearningAdapter()
        assert isinstance(adapter.feedback_summary(), dict)


# ---------------------------------------------------------------------------
# OntologyMediator.get_round_count
# ---------------------------------------------------------------------------


class TestGetRoundCount:
    def test_initial_zero(self):
        med = OntologyMediator()
        assert med.get_round_count() == 0

    def test_equals_undo_depth_before_undo(self):
        med = OntologyMediator()
        assert med.get_round_count() == med.get_undo_depth()

    def test_non_negative(self):
        med = OntologyMediator()
        assert med.get_round_count() >= 0

    def test_returns_int(self):
        med = OntologyMediator()
        assert isinstance(med.get_round_count(), int)

    def test_after_manual_stack_push(self):
        med = OntologyMediator()
        med._undo_stack.append({"entities": [], "relationships": []})
        assert med.get_round_count() == 1

    def test_after_two_pushes(self):
        med = OntologyMediator()
        med._undo_stack.append({})
        med._undo_stack.append({})
        assert med.get_round_count() == 2


# ---------------------------------------------------------------------------
# OntologyCritic.score_delta
# ---------------------------------------------------------------------------


class TestScoreDelta:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_zero_delta_identical(self):
        s = _make_score()
        delta = self.critic.score_delta(s, s)
        assert delta["overall"] == pytest.approx(0.0, abs=1e-6)

    def test_positive_delta(self):
        a = _make_score(c=0.5)
        b = _make_score(c=0.8)
        delta = self.critic.score_delta(a, b)
        assert delta["completeness"] == pytest.approx(0.3, abs=1e-5)

    def test_negative_delta(self):
        a = _make_score(c=0.9)
        b = _make_score(c=0.5)
        delta = self.critic.score_delta(a, b)
        assert delta["completeness"] == pytest.approx(-0.4, abs=1e-5)

    def test_returns_five_plus_overall(self):
        s = _make_score()
        delta = self.critic.score_delta(s, s)
        for key in ["completeness", "consistency", "clarity", "granularity", "domain_alignment", "overall"]:
            assert key in delta

    def test_all_dims_computed(self):
        a = _make_score(c=0.5, con=0.4, cl=0.3, g=0.2, da=0.1)
        b = _make_score(c=0.9, con=0.8, cl=0.7, g=0.6, da=0.5)
        delta = self.critic.score_delta(a, b)
        for key in ["completeness", "consistency", "clarity", "granularity", "domain_alignment"]:
            assert delta[key] > 0

    def test_overall_delta_correct(self):
        a = _make_score()
        b = _make_score(c=1.0, con=1.0, cl=1.0, g=1.0, da=1.0)
        delta = self.critic.score_delta(a, b)
        assert delta["overall"] == pytest.approx(b.overall - a.overall, abs=1e-5)


# ---------------------------------------------------------------------------
# EntityExtractionResult.filter_by_span
# ---------------------------------------------------------------------------


class TestFilterBySpan:
    def test_empty_result(self):
        r = _make_result()
        assert r.filter_by_span(0, 100).entities == []

    def test_all_inside_span(self):
        e1 = _make_entity("1", "Alice", (0, 5))
        e2 = _make_entity("2", "Bob", (6, 9))
        r = _make_result(e1, e2)
        filtered = r.filter_by_span(0, 20)
        assert len(filtered.entities) == 2

    def test_none_inside_span(self):
        e1 = _make_entity("1", "Alice", (50, 55))
        r = _make_result(e1)
        assert r.filter_by_span(0, 10).entities == []

    def test_partial_overlap_kept(self):
        e1 = _make_entity("1", "Alice", (8, 15))
        r = _make_result(e1)
        filtered = r.filter_by_span(10, 20)
        assert len(filtered.entities) == 1

    def test_entities_without_span_excluded(self):
        e1 = _make_entity("1", "Alice", None)
        r = _make_result(e1)
        assert r.filter_by_span(0, 100).entities == []

    def test_relationships_filtered_too(self):
        e1 = _make_entity("1", "Alice", (0, 5))
        e2 = _make_entity("2", "Bob", (100, 110))
        rel = Relationship(
            id="r1", source_id="1", target_id="2",
            relation_type="knows", confidence=0.9,
        )
        r = EntityExtractionResult(entities=[e1, e2], relationships=[rel], metadata={})
        filtered = r.filter_by_span(0, 10)
        assert len(filtered.entities) == 1
        assert len(filtered.relationships) == 0

    def test_relationships_kept_when_both_in_span(self):
        e1 = _make_entity("1", "Alice", (0, 5))
        e2 = _make_entity("2", "Bob", (10, 15))
        rel = Relationship(
            id="r1", source_id="1", target_id="2",
            relation_type="knows", confidence=0.9,
        )
        r = EntityExtractionResult(entities=[e1, e2], relationships=[rel], metadata={})
        filtered = r.filter_by_span(0, 20)
        assert len(filtered.relationships) == 1

    def test_returns_new_object(self):
        e1 = _make_entity("1", "Alice", (0, 5))
        r = _make_result(e1)
        assert r.filter_by_span(0, 20) is not r
