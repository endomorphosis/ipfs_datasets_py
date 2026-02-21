"""Batch-156 feature tests.

Methods under test:
  - OntologyOptimizer.score_below_threshold(threshold)
  - OntologyLearningAdapter.feedback_trend_direction()
  - OntologyGenerator.entity_avg_confidence(result)
  - OntologyCritic.dimension_delta_summary(before, after)
"""
import pytest
from unittest.mock import MagicMock


def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg
        self.trend = "stable"


def _push_opt(o, avg):
    o._history.append(_FakeEntry(avg))


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(a, score):
    r = MagicMock()
    r.final_score = score
    a._feedback.append(r)


def _make_entity(eid, confidence=0.5):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="Test", text=eid, confidence=confidence)


def _make_result(entities):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities, relationships=[], confidence=1.0, metadata={}, errors=[]
    )


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


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


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_below_threshold
# ---------------------------------------------------------------------------

class TestScoreBelowThreshold:
    def test_empty_returns_empty(self):
        o = _make_optimizer()
        assert o.score_below_threshold() == []

    def test_all_above_threshold(self):
        o = _make_optimizer()
        for v in [0.7, 0.8, 0.9]:
            _push_opt(o, v)
        assert o.score_below_threshold(threshold=0.5) == []

    def test_some_below(self):
        o = _make_optimizer()
        for v in [0.2, 0.6, 0.8]:
            _push_opt(o, v)
        result = o.score_below_threshold(threshold=0.5)
        assert len(result) == 1
        assert result[0].average_score == pytest.approx(0.2)

    def test_exclusive_threshold(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.score_below_threshold(threshold=0.5) == []


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_trend_direction
# ---------------------------------------------------------------------------

class TestFeedbackTrendDirection:
    def test_empty_returns_stable(self):
        a = _make_adapter()
        assert a.feedback_trend_direction() == "stable"

    def test_single_returns_stable(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_trend_direction() == "stable"

    def test_improving(self):
        a = _make_adapter()
        for v in [0.2, 0.3, 0.7, 0.8]:
            _push_feedback(a, v)
        assert a.feedback_trend_direction() == "improving"

    def test_declining(self):
        a = _make_adapter()
        for v in [0.8, 0.9, 0.2, 0.3]:
            _push_feedback(a, v)
        assert a.feedback_trend_direction() == "declining"

    def test_flat_returns_stable(self):
        a = _make_adapter()
        for _ in range(4):
            _push_feedback(a, 0.5)
        assert a.feedback_trend_direction() == "stable"

    def test_returns_string(self):
        a = _make_adapter()
        _push_feedback(a, 0.4)
        _push_feedback(a, 0.6)
        assert isinstance(a.feedback_trend_direction(), str)


# ---------------------------------------------------------------------------
# OntologyGenerator.entity_avg_confidence
# ---------------------------------------------------------------------------

class TestEntityAvgConfidence:
    def test_empty_returns_zero(self):
        gen = _make_generator()
        result = _make_result([])
        assert gen.entity_avg_confidence(result) == pytest.approx(0.0)

    def test_single_entity(self):
        gen = _make_generator()
        result = _make_result([_make_entity("e1", confidence=0.8)])
        assert gen.entity_avg_confidence(result) == pytest.approx(0.8)

    def test_mean_of_multiple(self):
        gen = _make_generator()
        entities = [_make_entity(f"e{i}", confidence=v) for i, v in enumerate([0.2, 0.4, 0.6])]
        result = _make_result(entities)
        assert gen.entity_avg_confidence(result) == pytest.approx(0.4)

    def test_in_zero_one_range(self):
        gen = _make_generator()
        entities = [_make_entity(f"e{i}", confidence=i * 0.1) for i in range(5)]
        result = _make_result(entities)
        avg = gen.entity_avg_confidence(result)
        assert 0.0 <= avg <= 1.0


# ---------------------------------------------------------------------------
# OntologyCritic.dimension_delta_summary
# ---------------------------------------------------------------------------

class TestDimensionDeltaSummary:
    def test_returns_all_six_dimensions(self):
        critic = _make_critic()
        before = _make_score()
        after = _make_score()
        summary = critic.dimension_delta_summary(before, after)
        assert len(summary) == 6

    def test_zero_change_all_zeros(self):
        critic = _make_critic()
        before = _make_score()
        after = _make_score()
        summary = critic.dimension_delta_summary(before, after)
        assert all(v == pytest.approx(0.0) for v in summary.values())

    def test_positive_delta(self):
        critic = _make_critic()
        before = _make_score(completeness=0.3)
        after = _make_score(completeness=0.7)
        summary = critic.dimension_delta_summary(before, after)
        assert summary["completeness"] == pytest.approx(0.4)

    def test_negative_delta(self):
        critic = _make_critic()
        before = _make_score(clarity=0.9)
        after = _make_score(clarity=0.4)
        summary = critic.dimension_delta_summary(before, after)
        assert summary["clarity"] == pytest.approx(-0.5)
