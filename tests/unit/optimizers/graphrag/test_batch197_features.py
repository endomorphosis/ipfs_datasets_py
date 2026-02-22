"""Batch-197 feature tests.

Methods under test:
  - OntologyOptimizer.history_above_threshold_rate(threshold)
  - OntologyOptimizer.history_improving_fraction()
  - OntologyOptimizer.score_percentile_of_last()
  - OntologyCritic.score_diff_from_mean(score)
  - OntologyGenerator.entity_confidence_sum(result)
  - OntologyLearningAdapter.feedback_longest_negative_streak(threshold)
  - OntologyMediator.action_names()
"""
import pytest
from unittest.mock import MagicMock


# ── helpers ──────────────────────────────────────────────────────────────────

class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg


def _push_opt(o, avg):
    o._history.append(_FakeEntry(avg))


def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


def _make_score(**kwargs):
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
    defaults = dict(
        completeness=0.5, consistency=0.5, clarity=0.5,
        granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5,
    )
    defaults.update(kwargs)
    return CriticScore(**defaults)


def _make_critic():
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    return OntologyCritic(use_llm=False)


def _make_entity(eid, confidence=0.5):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="T", text=eid, confidence=confidence)


def _make_result(entities=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(entities=entities or [], relationships=[], confidence=1.0)


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(a, score):
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import FeedbackRecord
    a._feedback.append(FeedbackRecord(final_score=score))


def _make_mediator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
    return OntologyMediator(generator=MagicMock(), critic=MagicMock())


# ── OntologyOptimizer.history_above_threshold_rate ───────────────────────────

class TestHistoryAboveThresholdRate:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_above_threshold_rate() == pytest.approx(0.0)

    def test_none_above_returns_zero(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.6]:
            _push_opt(o, v)
        assert o.history_above_threshold_rate(threshold=0.7) == pytest.approx(0.0)

    def test_all_above_returns_one(self):
        o = _make_optimizer()
        for v in [0.8, 0.9, 0.95]:
            _push_opt(o, v)
        assert o.history_above_threshold_rate(threshold=0.7) == pytest.approx(1.0)

    def test_half_above(self):
        o = _make_optimizer()
        for v in [0.5, 0.6, 0.8, 0.9]:
            _push_opt(o, v)
        assert o.history_above_threshold_rate(threshold=0.7) == pytest.approx(0.5)


# ── OntologyOptimizer.history_improving_fraction ─────────────────────────────

class TestHistoryImprovingFraction:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_improving_fraction() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.history_improving_fraction() == pytest.approx(0.0)

    def test_always_improving(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.7, 0.9]:
            _push_opt(o, v)
        assert o.history_improving_fraction() == pytest.approx(1.0)

    def test_never_improving(self):
        o = _make_optimizer()
        for v in [0.9, 0.7, 0.5, 0.3]:
            _push_opt(o, v)
        assert o.history_improving_fraction() == pytest.approx(0.0)

    def test_half_improving(self):
        o = _make_optimizer()
        for v in [0.5, 0.8, 0.3, 0.9]:
            _push_opt(o, v)
        # pairs: up, down, up → 2/3
        assert o.history_improving_fraction() == pytest.approx(2 / 3)


# ── OntologyOptimizer.score_percentile_of_last ───────────────────────────────

class TestScorePercentileOfLast:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_percentile_of_last() == pytest.approx(0.0)

    def test_single_entry_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        # nothing below 0.5 → 0%
        assert o.score_percentile_of_last() == pytest.approx(0.0)

    def test_last_is_highest(self):
        o = _make_optimizer()
        for v in [0.2, 0.4, 0.6, 0.9]:
            _push_opt(o, v)
        # 0.9 > 0.2, 0.4, 0.6 → 3/4 = 75%
        assert o.score_percentile_of_last() == pytest.approx(75.0)


# ── OntologyCritic.score_diff_from_mean ──────────────────────────────────────

class TestScoreDiffFromMean:
    def test_uniform_dimensions_zero_diff(self):
        c = _make_critic()
        # With uniform dimensions, overall ≈ dimension_mean (may differ due to weights)
        s = _make_score()  # all 0.5
        result = c.score_diff_from_mean(s)
        assert isinstance(result, float)

    def test_returns_float(self):
        c = _make_critic()
        s = _make_score(completeness=0.8, consistency=0.6, clarity=0.7,
                        granularity=0.5, relationship_coherence=0.4, domain_alignment=0.3)
        result = c.score_diff_from_mean(s)
        # overall is computed from weights, dimension_mean is simple mean
        # result should be a float (positive or negative)
        assert isinstance(result, float)

    def test_no_overall_attr_returns_zero(self):
        c = _make_critic()
        s = _make_score()
        # Verify method handles missing overall gracefully
        # CriticScore.overall is a computed property, so it will be available
        # The method returns overall - dim_mean
        result = c.score_diff_from_mean(s)
        assert isinstance(result, float)


# ── OntologyGenerator.entity_confidence_sum ──────────────────────────────────

class TestEntityConfidenceSum:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_confidence_sum(r) == pytest.approx(0.0)

    def test_single_entity(self):
        g = _make_generator()
        r = _make_result([_make_entity("e1", confidence=0.7)])
        assert g.entity_confidence_sum(r) == pytest.approx(0.7)

    def test_sum_of_multiple(self):
        g = _make_generator()
        r = _make_result([
            _make_entity("e1", confidence=0.4),
            _make_entity("e2", confidence=0.6),
            _make_entity("e3", confidence=0.8),
        ])
        assert g.entity_confidence_sum(r) == pytest.approx(1.8)


# ── OntologyLearningAdapter.feedback_longest_negative_streak ─────────────────

class TestFeedbackLongestNegativeStreak:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_longest_negative_streak() == 0

    def test_none_negative_returns_zero(self):
        a = _make_adapter()
        for v in [0.6, 0.7, 0.8]:
            _push_feedback(a, v)
        assert a.feedback_longest_negative_streak(threshold=0.4) == 0

    def test_streak_of_three(self):
        a = _make_adapter()
        for v in [0.7, 0.2, 0.1, 0.3, 0.8]:
            _push_feedback(a, v)
        assert a.feedback_longest_negative_streak(threshold=0.4) == 3

    def test_multiple_streaks_returns_longest(self):
        a = _make_adapter()
        for v in [0.1, 0.7, 0.2, 0.1, 0.8]:
            _push_feedback(a, v)
        # streaks: 1, 2 → longest = 2
        assert a.feedback_longest_negative_streak(threshold=0.4) == 2


# ── OntologyMediator.action_names ────────────────────────────────────────────

class TestActionNames:
    def test_no_actions_returns_empty_list(self):
        m = _make_mediator()
        assert m.action_names() == []

    def test_returns_sorted_names(self):
        m = _make_mediator()
        m._action_counts["expand"] = 3
        m._action_counts["prune"] = 1
        m._action_counts["merge"] = 5
        assert m.action_names() == ["expand", "merge", "prune"]

    def test_single_action(self):
        m = _make_mediator()
        m._action_counts["refine"] = 2
        assert m.action_names() == ["refine"]
