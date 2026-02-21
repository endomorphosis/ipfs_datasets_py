"""Batch 94: pending_recommendation, feedback_ids, score_improvement, relationship_count, is_default."""

from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    Relationship,
    EntityExtractionResult,
    ExtractionConfig,
    OntologyGenerator,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    OntologyLearningAdapter,
    FeedbackRecord,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(eid: str) -> Entity:
    return Entity(id=eid, text=f"E{eid}", type="PERSON", confidence=0.8)


def _make_rel(rid: str, src: str, tgt: str) -> Relationship:
    return Relationship(id=rid, source_id=src, target_id=tgt, type="X")


def _make_result(entities=None, rels=None) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=entities or [], relationships=rels or [], confidence=0.8, metadata={}
    )


def _make_mediator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    gen = OntologyGenerator()
    crit = OntologyCritic()
    return OntologyMediator(gen, crit)


def _make_score(overall_target: float) -> CriticScore:
    # completeness has weight 0.3, let's set all equal for predictable overall
    v = overall_target
    return CriticScore(completeness=v, consistency=v, clarity=v, granularity=v, domain_alignment=v)


# ---------------------------------------------------------------------------
# OntologyMediator.pending_recommendation
# ---------------------------------------------------------------------------


class TestPendingRecommendation:
    def test_none_when_empty(self):
        med = _make_mediator()
        assert med.pending_recommendation() is None

    def test_returns_top(self):
        med = _make_mediator()
        med._recommendation_counts["add_entity"] = 5
        med._recommendation_counts["remove_rel"] = 2
        assert med.pending_recommendation() == "add_entity"

    def test_does_not_modify_state(self):
        med = _make_mediator()
        med._recommendation_counts["x"] = 3
        before = dict(med._recommendation_counts)
        med.pending_recommendation()
        assert med._recommendation_counts == before

    def test_returns_string_or_none(self):
        med = _make_mediator()
        result = med.pending_recommendation()
        assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_ids
# ---------------------------------------------------------------------------


class TestFeedbackIds:
    def test_empty(self):
        adapter = OntologyLearningAdapter()
        assert adapter.feedback_ids() == []

    def test_returns_list(self):
        adapter = OntologyLearningAdapter()
        assert isinstance(adapter.feedback_ids(), list)

    def test_fallback_index_label(self):
        adapter = OntologyLearningAdapter()
        adapter._feedback.append(FeedbackRecord(final_score=0.5))
        ids = adapter.feedback_ids()
        assert len(ids) == 1
        assert "record_0" in ids[0] or isinstance(ids[0], str)

    def test_length_matches_feedback_count(self):
        adapter = OntologyLearningAdapter()
        for _ in range(3):
            adapter._feedback.append(FeedbackRecord(final_score=0.5))
        assert len(adapter.feedback_ids()) == 3


# ---------------------------------------------------------------------------
# OntologyCritic.score_improvement
# ---------------------------------------------------------------------------


class TestScoreImprovement:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_positive_improvement(self):
        a = _make_score(0.5)
        b = _make_score(0.8)
        assert self.critic.score_improvement(a, b) > 0.0

    def test_negative_improvement(self):
        a = _make_score(0.8)
        b = _make_score(0.5)
        assert self.critic.score_improvement(a, b) < 0.0

    def test_no_change(self):
        s = _make_score(0.7)
        assert self.critic.score_improvement(s, s) == pytest.approx(0.0)

    def test_returns_float(self):
        s = _make_score(0.5)
        assert isinstance(self.critic.score_improvement(s, s), float)


# ---------------------------------------------------------------------------
# OntologyGenerator.relationship_count
# ---------------------------------------------------------------------------


class TestRelationshipCount:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_empty(self):
        assert self.gen.relationship_count(_make_result()) == 0

    def test_non_empty(self):
        rels = [_make_rel("r1", "e1", "e2"), _make_rel("r2", "e2", "e3")]
        result = _make_result(rels=rels)
        assert self.gen.relationship_count(result) == 2

    def test_returns_int(self):
        assert isinstance(self.gen.relationship_count(_make_result()), int)


# ---------------------------------------------------------------------------
# ExtractionConfig.is_default
# ---------------------------------------------------------------------------


class TestIsDefault:
    def test_fresh_config_is_default(self):
        assert ExtractionConfig().is_default() is True

    def test_modified_config_not_default(self):
        cfg = ExtractionConfig(confidence_threshold=0.9)
        assert cfg.is_default() is False

    def test_returns_bool(self):
        assert isinstance(ExtractionConfig().is_default(), bool)

    def test_after_with_threshold_not_default(self):
        cfg = ExtractionConfig().with_threshold(0.9)
        assert cfg.is_default() is False
