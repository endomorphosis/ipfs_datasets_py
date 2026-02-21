"""Batch 91: clear_feedback, dimension_scores, passes_all, with_threshold, entity_texts, entity_ids, feedback_summary_dict."""

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


def _make_entity(eid: str, text: str, etype: str = "PERSON") -> Entity:
    return Entity(id=eid, text=text, type=etype, confidence=0.8)


def _make_result(*entities: Entity) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=list(entities), relationships=[], confidence=0.8, metadata={}
    )


def _make_score(c=0.8, con=0.7, cl=0.6, g=0.5, da=0.9) -> CriticScore:
    return CriticScore(completeness=c, consistency=con, clarity=cl, granularity=g, domain_alignment=da)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.clear_feedback
# ---------------------------------------------------------------------------


class TestClearFeedback:
    def test_empty_returns_zero(self):
        adapter = OntologyLearningAdapter()
        assert adapter.clear_feedback() == 0

    def test_returns_count(self):
        adapter = OntologyLearningAdapter()
        adapter._feedback.extend([FeedbackRecord(final_score=s) for s in [0.5, 0.7, 0.9]])
        assert adapter.clear_feedback() == 3

    def test_feedback_empty_after(self):
        adapter = OntologyLearningAdapter()
        adapter._feedback.append(FeedbackRecord(final_score=0.5))
        adapter.clear_feedback()
        assert adapter.feedback_count() == 0

    def test_returns_int(self):
        assert isinstance(OntologyLearningAdapter().clear_feedback(), int)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_summary_dict
# ---------------------------------------------------------------------------


class TestFeedbackSummaryDict:
    def test_empty(self):
        adapter = OntologyLearningAdapter()
        d = adapter.feedback_summary_dict()
        assert d["count"] == 0
        assert d["mean"] == pytest.approx(0.0)
        assert d["variance"] == pytest.approx(0.0)

    def test_with_records(self):
        adapter = OntologyLearningAdapter()
        for s in [0.4, 0.6]:
            adapter._feedback.append(FeedbackRecord(final_score=s))
        d = adapter.feedback_summary_dict()
        assert d["count"] == 2
        assert d["mean"] == pytest.approx(0.5)

    def test_returns_dict(self):
        assert isinstance(OntologyLearningAdapter().feedback_summary_dict(), dict)


# ---------------------------------------------------------------------------
# OntologyCritic.dimension_scores
# ---------------------------------------------------------------------------


class TestDimensionScores:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_returns_dict(self):
        assert isinstance(self.critic.dimension_scores(_make_score()), dict)

    def test_has_all_keys(self):
        d = self.critic.dimension_scores(_make_score())
        for key in ["completeness", "consistency", "clarity", "granularity", "domain_alignment", "overall"]:
            assert key in d

    def test_values_match(self):
        score = _make_score(c=0.9, con=0.8, cl=0.7, g=0.6, da=0.5)
        d = self.critic.dimension_scores(score)
        assert d["completeness"] == pytest.approx(0.9)
        assert d["consistency"] == pytest.approx(0.8)
        assert d["overall"] == pytest.approx(score.overall)


# ---------------------------------------------------------------------------
# OntologyCritic.passes_all
# ---------------------------------------------------------------------------


class TestPassesAll:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_empty_returns_true(self):
        assert self.critic.passes_all([]) is True

    def test_all_pass(self):
        scores = [_make_score(c=0.9, con=0.9, cl=0.9, g=0.9, da=0.9)] * 3
        assert self.critic.passes_all(scores) is True

    def test_one_fails(self):
        high = _make_score(c=0.9, con=0.9, cl=0.9, g=0.9, da=0.9)
        low = _make_score(c=0.1, con=0.1, cl=0.1, g=0.1, da=0.1)
        assert self.critic.passes_all([high, low]) is False

    def test_custom_threshold(self):
        score = _make_score()
        assert self.critic.passes_all([score], threshold=0.0) is True
        assert self.critic.passes_all([score], threshold=1.0) is False

    def test_returns_bool(self):
        assert isinstance(self.critic.passes_all([_make_score()]), bool)


# ---------------------------------------------------------------------------
# ExtractionConfig.with_threshold
# ---------------------------------------------------------------------------


class TestWithThreshold:
    def test_returns_new_config(self):
        cfg = ExtractionConfig()
        new = cfg.with_threshold(0.9)
        assert isinstance(new, ExtractionConfig)

    def test_threshold_updated(self):
        cfg = ExtractionConfig(confidence_threshold=0.5)
        assert cfg.with_threshold(0.9).confidence_threshold == pytest.approx(0.9)

    def test_original_unchanged(self):
        cfg = ExtractionConfig(confidence_threshold=0.5)
        cfg.with_threshold(0.9)
        assert cfg.confidence_threshold == pytest.approx(0.5)

    def test_other_fields_preserved(self):
        cfg = ExtractionConfig(max_entities=42)
        new = cfg.with_threshold(0.7)
        assert new.max_entities == 42


# ---------------------------------------------------------------------------
# EntityExtractionResult.entity_texts
# ---------------------------------------------------------------------------


class TestEntityTexts:
    def test_empty(self):
        assert _make_result().entity_texts() == []

    def test_returns_all_texts(self):
        r = _make_result(_make_entity("1", "Alice"), _make_entity("2", "Bob"))
        assert r.entity_texts() == ["Alice", "Bob"]

    def test_returns_list(self):
        assert isinstance(_make_result().entity_texts(), list)

    def test_order_preserved(self):
        entities = [_make_entity(str(i), f"E{i}") for i in range(5)]
        r = _make_result(*entities)
        assert r.entity_texts() == [f"E{i}" for i in range(5)]


# ---------------------------------------------------------------------------
# OntologyGenerator.entity_ids
# ---------------------------------------------------------------------------


class TestEntityIds:
    def setup_method(self):
        self.gen = OntologyGenerator()

    def test_empty(self):
        assert self.gen.entity_ids(_make_result()) == []

    def test_returns_ids(self):
        r = _make_result(_make_entity("e1", "A"), _make_entity("e2", "B"))
        assert self.gen.entity_ids(r) == ["e1", "e2"]

    def test_returns_list(self):
        assert isinstance(self.gen.entity_ids(_make_result()), list)
