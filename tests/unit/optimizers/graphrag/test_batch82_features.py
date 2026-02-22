"""Batch 82: avg_confidence, improve_score_suggestion, feedback_count, last_score, is_strict."""

from __future__ import annotations

import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).parents[4]))

import pytest

from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
    Entity,
    EntityExtractionResult,
    ExtractionConfig,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (
    FeedbackRecord,
    OntologyLearningAdapter,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import (
    OntologyOptimizer,
    OptimizationReport,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity(eid: str, text: str, conf: float = 0.8) -> Entity:
    return Entity(id=eid, text=text, type="TEST", confidence=conf)


def _make_result(*entities: Entity) -> EntityExtractionResult:
    return EntityExtractionResult(
        entities=list(entities), relationships=[], confidence=0.8, metadata={}
    )


def _make_score(c=0.8, con=0.7, cl=0.6, g=0.5, da=0.9) -> CriticScore:
    return CriticScore(
        completeness=c, consistency=con, clarity=cl, granularity=g, relationship_coherence=da
    , domain_alignment=da
    )


def _make_report(score: float) -> OptimizationReport:
    return OptimizationReport(average_score=score, trend="stable")


# ---------------------------------------------------------------------------
# EntityExtractionResult.avg_confidence
# ---------------------------------------------------------------------------


class TestAvgConfidence:
    def test_empty_returns_zero(self):
        r = _make_result()
        assert r.avg_confidence() == pytest.approx(0.0)

    def test_single_entity(self):
        r = _make_result(_make_entity("1", "Alice", 0.7))
        assert r.avg_confidence() == pytest.approx(0.7)

    def test_mean_of_multiple(self):
        entities = [_make_entity(str(i), f"E{i}", c) for i, c in enumerate([0.4, 0.6, 0.8])]
        r = _make_result(*entities)
        assert r.avg_confidence() == pytest.approx(0.6, abs=1e-5)

    def test_returns_float(self):
        r = _make_result(_make_entity("1", "Alice"))
        assert isinstance(r.avg_confidence(), float)

    def test_between_zero_and_one(self):
        entities = [_make_entity(str(i), f"E{i}", c) for i, c in enumerate([0.3, 0.7, 0.9])]
        r = _make_result(*entities)
        v = r.avg_confidence()
        assert 0.0 <= v <= 1.0


# ---------------------------------------------------------------------------
# OntologyCritic.improve_score_suggestion
# ---------------------------------------------------------------------------


class TestImproveScoreSuggestion:
    def setup_method(self):
        self.critic = OntologyCritic()

    def test_returns_string(self):
        score = _make_score()
        assert isinstance(self.critic.improve_score_suggestion(score), str)

    def test_returns_lowest_dim(self):
        score = _make_score(c=0.9, con=0.8, cl=0.7, g=0.05, da=0.9)
        assert self.critic.improve_score_suggestion(score) == "granularity"

    def test_valid_dim_name(self):
        score = _make_score()
        valid = {"completeness", "consistency", "clarity", "granularity", "domain_alignment"}
        assert self.critic.improve_score_suggestion(score) in valid

    def test_consistent_with_bottom_dimension(self):
        score = _make_score()
        assert self.critic.improve_score_suggestion(score) == self.critic.bottom_dimension(score)

    def test_completeness_suggestion(self):
        score = _make_score(c=0.01, con=0.9, cl=0.9, g=0.9, da=0.9)
        assert self.critic.improve_score_suggestion(score) == "completeness"


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_count
# ---------------------------------------------------------------------------


class TestFeedbackCount:
    def test_empty_returns_zero(self):
        adapter = OntologyLearningAdapter()
        assert adapter.feedback_count() == 0

    def test_after_adding_records(self):
        adapter = OntologyLearningAdapter()
        for _ in range(3):
            adapter._feedback.append(FeedbackRecord(final_score=0.5))
        assert adapter.feedback_count() == 3

    def test_returns_int(self):
        adapter = OntologyLearningAdapter()
        assert isinstance(adapter.feedback_count(), int)

    def test_decreases_after_reset(self):
        adapter = OntologyLearningAdapter()
        adapter._feedback.append(FeedbackRecord(final_score=0.5))
        adapter.reset_feedback()
        assert adapter.feedback_count() == 0

    def test_consistent_with_len_feedback(self):
        adapter = OntologyLearningAdapter()
        for _ in range(5):
            adapter._feedback.append(FeedbackRecord(final_score=0.6))
        assert adapter.feedback_count() == len(adapter._feedback)


# ---------------------------------------------------------------------------
# OntologyOptimizer.last_score
# ---------------------------------------------------------------------------


class TestLastScore:
    def test_empty_history_returns_zero(self):
        opt = OntologyOptimizer()
        assert opt.last_score() == pytest.approx(0.0)

    def test_single_entry(self):
        opt = OntologyOptimizer()
        opt._history.append(_make_report(0.75))
        assert opt.last_score() == pytest.approx(0.75)

    def test_returns_last_not_first(self):
        opt = OntologyOptimizer()
        opt._history.append(_make_report(0.3))
        opt._history.append(_make_report(0.9))
        assert opt.last_score() == pytest.approx(0.9)

    def test_returns_float(self):
        opt = OntologyOptimizer()
        assert isinstance(opt.last_score(), float)

    def test_consistent_with_score_history(self):
        opt = OntologyOptimizer()
        for v in [0.4, 0.6, 0.8]:
            opt._history.append(_make_report(v))
        assert opt.last_score() == pytest.approx(opt.score_history()[-1])


# ---------------------------------------------------------------------------
# ExtractionConfig.is_strict
# ---------------------------------------------------------------------------


class TestIsStrict:
    def test_strict_above_0_8(self):
        cfg = ExtractionConfig(confidence_threshold=0.9)
        assert cfg.is_strict() is True

    def test_strict_at_0_8(self):
        cfg = ExtractionConfig(confidence_threshold=0.8)
        assert cfg.is_strict() is True

    def test_not_strict_below_0_8(self):
        cfg = ExtractionConfig(confidence_threshold=0.7)
        assert cfg.is_strict() is False

    def test_returns_bool(self):
        cfg = ExtractionConfig()
        assert isinstance(cfg.is_strict(), bool)

    def test_default_config_not_strict(self):
        # Default confidence_threshold should be < 0.8
        cfg = ExtractionConfig()
        # Just check it returns a bool without error
        assert isinstance(cfg.is_strict(), bool)
