"""Batch-185 feature tests.

Methods under test:
  - OntologyOptimizer.history_std_ratio(window)
  - OntologyOptimizer.score_turning_points()
  - OntologyCritic.dimension_balance_score(score)
  - OntologyCritic.score_percentile_rank(score, history)
  - OntologyGenerator.entity_confidence_iqr(result)
  - OntologyGenerator.avg_entity_confidence(result)
  - OntologyPipeline.run_score_harmonic_mean()
  - OntologyPipeline.worst_run_index()
  - OntologyLearningAdapter.feedback_longest_positive_streak()
  - OntologyLearningAdapter.feedback_score_range()
"""
import pytest
from unittest.mock import MagicMock


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


def _make_result(entities, rels=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities, relationships=rels or [], confidence=1.0, metadata={}, errors=[]
    )


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline()


def _push_run(p, score):
    r = MagicMock()
    r.score.overall = score
    p._run_history.append(r)


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(adapter, score):
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import FeedbackRecord
    adapter._feedback.append(FeedbackRecord(final_score=score))


# ── OntologyOptimizer.history_std_ratio ──────────────────────────────────────

class TestHistoryStdRatio:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_std_ratio() == pytest.approx(0.0)

    def test_too_few_returns_zero(self):
        o = _make_optimizer()
        for v in [0.3, 0.7]:
            _push_opt(o, v)
        assert o.history_std_ratio() == pytest.approx(0.0)

    def test_constant_returns_zero(self):
        o = _make_optimizer()
        for _ in range(6):
            _push_opt(o, 0.5)
        assert o.history_std_ratio() == pytest.approx(0.0)

    def test_returns_float(self):
        o = _make_optimizer()
        for v in [0.1, 0.3, 0.5, 0.7, 0.9, 0.2]:
            _push_opt(o, v)
        assert isinstance(o.history_std_ratio(), float)


# ── OntologyOptimizer.score_turning_points ────────────────────────────────────

class TestScoreTurningPoints:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_turning_points() == 0

    def test_monotone_returns_zero(self):
        o = _make_optimizer()
        for v in [0.1, 0.3, 0.5, 0.7]:
            _push_opt(o, v)
        assert o.score_turning_points() == 0

    def test_zigzag_has_turning_points(self):
        o = _make_optimizer()
        for v in [0.5, 0.9, 0.3, 0.8, 0.2]:
            _push_opt(o, v)
        assert o.score_turning_points() >= 2

    def test_returns_int(self):
        o = _make_optimizer()
        for v in [0.5, 0.9, 0.3]:
            _push_opt(o, v)
        assert isinstance(o.score_turning_points(), int)


# ── OntologyCritic.dimension_balance_score ────────────────────────────────────

class TestDimensionBalanceScore:
    def test_all_same_returns_one(self):
        c = _make_critic()
        assert c.dimension_balance_score(_make_score()) == pytest.approx(1.0, rel=1e-3)

    def test_returns_float(self):
        c = _make_critic()
        assert isinstance(c.dimension_balance_score(_make_score()), float)

    def test_in_range(self):
        c = _make_critic()
        score = _make_score(completeness=1.0, consistency=0.0)
        val = c.dimension_balance_score(score)
        assert 0.0 <= val <= 1.0

    def test_unbalanced_less_than_balanced(self):
        c = _make_critic()
        balanced = _make_score()
        unbalanced = _make_score(completeness=1.0, consistency=0.0)
        assert c.dimension_balance_score(unbalanced) < c.dimension_balance_score(balanced)


# ── OntologyCritic.score_percentile_rank ─────────────────────────────────────

class TestScorePercentileRank:
    def test_empty_history_returns_zero(self):
        c = _make_critic()
        assert c.score_percentile_rank(_make_score(), []) == pytest.approx(0.0)

    def test_best_in_history_returns_100(self):
        c = _make_critic()
        top = _make_score(**{d: 1.0 for d in ["completeness", "consistency", "clarity",
                                                "granularity", "relationship_coherence", "domain_alignment"]})
        history = [_make_score() for _ in range(5)]
        assert c.score_percentile_rank(top, history) == pytest.approx(100.0)

    def test_worst_returns_zero(self):
        c = _make_critic()
        bottom = _make_score(**{d: 0.0 for d in ["completeness", "consistency", "clarity",
                                                    "granularity", "relationship_coherence", "domain_alignment"]})
        history = [_make_score() for _ in range(5)]
        assert c.score_percentile_rank(bottom, history) == pytest.approx(0.0)

    def test_returns_float(self):
        c = _make_critic()
        assert isinstance(c.score_percentile_rank(_make_score(), [_make_score()]), float)


# ── OntologyGenerator.entity_confidence_iqr ──────────────────────────────────

class TestEntityConfidenceIQR:
    def test_too_few_returns_zero(self):
        gen = _make_generator()
        entities = [_make_entity("e1"), _make_entity("e2")]
        assert gen.entity_confidence_iqr(_make_result(entities)) == pytest.approx(0.0)

    def test_constant_returns_zero(self):
        gen = _make_generator()
        entities = [_make_entity(f"e{i}", 0.5) for i in range(5)]
        assert gen.entity_confidence_iqr(_make_result(entities)) == pytest.approx(0.0)

    def test_nonzero_iqr(self):
        gen = _make_generator()
        entities = [_make_entity(f"e{i}", v) for i, v in enumerate([0.1, 0.3, 0.7, 0.9])]
        assert gen.entity_confidence_iqr(_make_result(entities)) > 0


# ── OntologyGenerator.avg_entity_confidence ──────────────────────────────────

class TestAvgEntityConfidence:
    def test_empty_returns_zero(self):
        gen = _make_generator()
        assert gen.avg_entity_confidence(_make_result([])) == pytest.approx(0.0)

    def test_single_entity(self):
        gen = _make_generator()
        assert gen.avg_entity_confidence(_make_result([_make_entity("e1", 0.7)])) == pytest.approx(0.7)

    def test_average(self):
        gen = _make_generator()
        entities = [_make_entity("e1", 0.3), _make_entity("e2", 0.7)]
        assert gen.avg_entity_confidence(_make_result(entities)) == pytest.approx(0.5)


# ── OntologyPipeline.run_score_harmonic_mean ──────────────────────────────────

class TestRunScoreHarmonicMean:
    def test_no_runs_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_harmonic_mean() == pytest.approx(0.0)

    def test_single_run(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.run_score_harmonic_mean() == pytest.approx(0.5, rel=1e-3)

    def test_harmonic_leq_arith(self):
        p = _make_pipeline()
        vals = [0.3, 0.5, 0.7]
        for v in vals:
            _push_run(p, v)
        arith = sum(vals) / len(vals)
        assert p.run_score_harmonic_mean() <= arith + 1e-9


# ── OntologyPipeline.worst_run_index ─────────────────────────────────────────

class TestWorstRunIndex:
    def test_no_runs_returns_minus_one(self):
        p = _make_pipeline()
        assert p.worst_run_index() == -1

    def test_single_run(self):
        p = _make_pipeline()
        _push_run(p, 0.7)
        assert p.worst_run_index() == 0

    def test_identifies_worst(self):
        p = _make_pipeline()
        _push_run(p, 0.9)
        _push_run(p, 0.2)
        _push_run(p, 0.7)
        assert p.worst_run_index() == 1


# ── OntologyLearningAdapter.feedback_longest_positive_streak ─────────────────

class TestFeedbackLongestPositiveStreak:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_longest_positive_streak() == 0

    def test_no_positive_returns_zero(self):
        a = _make_adapter()
        for v in [0.1, 0.2, 0.3]:
            _push_feedback(a, v)
        assert a.feedback_longest_positive_streak() == 0

    def test_all_positive(self):
        a = _make_adapter()
        for v in [0.6, 0.7, 0.8]:
            _push_feedback(a, v)
        assert a.feedback_longest_positive_streak() == 3

    def test_finds_longest(self):
        a = _make_adapter()
        for v in [0.6, 0.7, 0.2, 0.8, 0.9, 0.7]:
            _push_feedback(a, v)
        assert a.feedback_longest_positive_streak() == 3


# ── OntologyLearningAdapter.feedback_score_range ─────────────────────────────

class TestFeedbackScoreRange:
    def test_single_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_score_range() == pytest.approx(0.0)

    def test_computes_range(self):
        a = _make_adapter()
        _push_feedback(a, 0.3)
        _push_feedback(a, 0.8)
        assert a.feedback_score_range() == pytest.approx(0.5)
