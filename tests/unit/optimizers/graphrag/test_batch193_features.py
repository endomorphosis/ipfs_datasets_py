"""Batch-193 feature tests.

Methods under test:
  - OntologyOptimizer.history_streak_above(threshold)
  - OntologyOptimizer.score_volatility()
  - OntologyOptimizer.history_percentile_rank(value)
  - OntologyCritic.dimension_weighted_score(score, weights)
  - OntologyGenerator.entity_avg_text_length(result)
  - OntologyGenerator.relationship_confidence_range(result)
  - OntologyLearningAdapter.feedback_positive_rate(threshold)
  - OntologyMediator.action_diversity_score()
"""
import math
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


def _make_entity(eid, text=None, confidence=0.5):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="T", text=text or eid, confidence=confidence)


def _make_rel_mock(confidence=0.8):
    r = MagicMock()
    r.confidence = confidence
    return r


def _make_result(entities=None, relationships=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities or [],
        relationships=relationships or [],
        confidence=1.0,
    )


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


# ── OntologyOptimizer.history_streak_above ───────────────────────────────────

class TestHistoryStreakAbove:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_streak_above() == 0

    def test_none_above_returns_zero(self):
        o = _make_optimizer()
        for v in [0.3, 0.4, 0.5]:
            _push_opt(o, v)
        assert o.history_streak_above(threshold=0.7) == 0

    def test_trailing_streak(self):
        o = _make_optimizer()
        for v in [0.5, 0.8, 0.9, 0.95]:
            _push_opt(o, v)
        assert o.history_streak_above(threshold=0.7) == 3

    def test_streak_broken(self):
        o = _make_optimizer()
        for v in [0.9, 0.3, 0.8, 0.85]:
            _push_opt(o, v)
        assert o.history_streak_above(threshold=0.7) == 2


# ── OntologyOptimizer.score_volatility ───────────────────────────────────────

class TestScoreVolatility:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_volatility() == pytest.approx(0.0)

    def test_two_entries_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.3)
        _push_opt(o, 0.7)
        assert o.score_volatility() == pytest.approx(0.0)

    def test_constant_deltas_zero_volatility(self):
        o = _make_optimizer()
        for v in [0.2, 0.4, 0.6, 0.8]:
            _push_opt(o, v)
        assert o.score_volatility() == pytest.approx(0.0)

    def test_varying_deltas_positive_volatility(self):
        o = _make_optimizer()
        for v in [0.5, 0.9, 0.1, 0.8, 0.2]:
            _push_opt(o, v)
        assert o.score_volatility() > 0.0


# ── OntologyOptimizer.history_percentile_rank ────────────────────────────────

class TestHistoryPercentileRank:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_percentile_rank(0.5) == pytest.approx(0.0)

    def test_value_below_all_returns_zero(self):
        o = _make_optimizer()
        for v in [0.4, 0.5, 0.6]:
            _push_opt(o, v)
        assert o.history_percentile_rank(0.3) == pytest.approx(0.0)

    def test_value_above_all_returns_100(self):
        o = _make_optimizer()
        for v in [0.4, 0.5, 0.6]:
            _push_opt(o, v)
        assert o.history_percentile_rank(0.9) == pytest.approx(100.0)

    def test_half_below(self):
        o = _make_optimizer()
        for v in [0.2, 0.4, 0.6, 0.8]:
            _push_opt(o, v)
        # value=0.5: 0.2 and 0.4 are below → 2/4 = 50%
        assert o.history_percentile_rank(0.5) == pytest.approx(50.0)


# ── OntologyCritic.dimension_weighted_score ──────────────────────────────────

class TestDimensionWeightedScore:
    def test_uniform_weights_equals_mean(self):
        c = _make_critic()
        s = _make_score()  # all 0.5
        assert c.dimension_weighted_score(s) == pytest.approx(0.5)

    def test_single_dimension_emphasis(self):
        c = _make_critic()
        s = _make_score(completeness=1.0, consistency=0.0, clarity=0.0,
                        granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0)
        weights = {"completeness": 1.0, "consistency": 0.0, "clarity": 0.0,
                   "granularity": 0.0, "relationship_coherence": 0.0, "domain_alignment": 0.0}
        # weighted = 1.0 * 1.0 / 1.0 = 1.0
        assert c.dimension_weighted_score(s, weights=weights) == pytest.approx(1.0)

    def test_default_matches_dimension_mean(self):
        c = _make_critic()
        s = _make_score(completeness=0.2, consistency=0.4, clarity=0.6,
                        granularity=0.8, relationship_coherence=1.0, domain_alignment=0.0)
        assert c.dimension_weighted_score(s) == pytest.approx(c.dimension_mean(s))


# ── OntologyGenerator.entity_avg_text_length ─────────────────────────────────

class TestEntityAvgTextLength:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_avg_text_length(r) == pytest.approx(0.0)

    def test_single_entity(self):
        g = _make_generator()
        r = _make_result([_make_entity("e1", text="hello")])
        assert g.entity_avg_text_length(r) == pytest.approx(5.0)

    def test_average_of_multiple(self):
        g = _make_generator()
        r = _make_result([
            _make_entity("e1", text="hi"),         # 2
            _make_entity("e2", text="hello"),       # 5
            _make_entity("e3", text="greetings"),   # 9
        ])
        assert g.entity_avg_text_length(r) == pytest.approx((2 + 5 + 9) / 3)


# ── OntologyGenerator.relationship_confidence_range ──────────────────────────

class TestRelationshipConfidenceRange:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result([])
        assert g.relationship_confidence_range(r) == pytest.approx(0.0)

    def test_single_relationship_returns_zero(self):
        g = _make_generator()
        r = _make_result(relationships=[_make_rel_mock(0.7)])
        assert g.relationship_confidence_range(r) == pytest.approx(0.0)

    def test_range_of_multiple(self):
        g = _make_generator()
        rels = [_make_rel_mock(c) for c in [0.2, 0.9, 0.5]]
        r = _make_result(relationships=rels)
        assert g.relationship_confidence_range(r) == pytest.approx(0.7)


# ── OntologyLearningAdapter.feedback_positive_rate ───────────────────────────

class TestFeedbackPositiveRate:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_positive_rate() == pytest.approx(0.0)

    def test_all_positive(self):
        a = _make_adapter()
        for v in [0.7, 0.8, 0.9]:
            _push_feedback(a, v)
        assert a.feedback_positive_rate(threshold=0.6) == pytest.approx(1.0)

    def test_none_positive(self):
        a = _make_adapter()
        for v in [0.1, 0.3, 0.5]:
            _push_feedback(a, v)
        assert a.feedback_positive_rate(threshold=0.6) == pytest.approx(0.0)

    def test_half_positive(self):
        a = _make_adapter()
        for v in [0.3, 0.5, 0.7, 0.9]:
            _push_feedback(a, v)
        assert a.feedback_positive_rate(threshold=0.6) == pytest.approx(0.5)


# ── OntologyMediator.action_diversity_score ──────────────────────────────────

class TestActionDiversityScore:
    def test_no_actions_returns_zero(self):
        m = _make_mediator()
        assert m.action_diversity_score() == pytest.approx(0.0)

    def test_single_action_returns_zero(self):
        m = _make_mediator()
        m._action_counts["expand"] = 5
        assert m.action_diversity_score() == pytest.approx(0.0)

    def test_uniform_two_actions_returns_one(self):
        m = _make_mediator()
        m._action_counts["a"] = 5
        m._action_counts["b"] = 5
        assert m.action_diversity_score() == pytest.approx(1.0)

    def test_skewed_distribution_below_one(self):
        m = _make_mediator()
        m._action_counts["a"] = 9
        m._action_counts["b"] = 1
        result = m.action_diversity_score()
        assert 0.0 < result < 1.0

    def test_uniform_four_actions_returns_one(self):
        m = _make_mediator()
        for k in "abcd":
            m._action_counts[k] = 4
        assert m.action_diversity_score() == pytest.approx(1.0)
