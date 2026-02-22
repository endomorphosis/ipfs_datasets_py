"""Batch-196 feature tests.

Methods under test:
  - OntologyOptimizer.score_delta_std()
  - OntologyOptimizer.history_coefficient_of_variation()
  - OntologyCritic.dimension_sum(score)
  - OntologyGenerator.relationship_avg_weight(result)
  - OntologyPipeline.run_score_min()
  - OntologyPipeline.run_score_max()
  - OntologyLearningAdapter.feedback_variance()
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


def _make_rel_mock(weight=0.0):
    r = MagicMock()
    r.weight = weight
    return r


def _make_result(relationships=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(entities=[], relationships=relationships or [], confidence=1.0)


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline()


def _push_run(p, score_val):
    run = MagicMock()
    run.score.overall = score_val
    p._run_history.append(run)


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(a, score):
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import FeedbackRecord
    a._feedback.append(FeedbackRecord(final_score=score))


# ── OntologyOptimizer.score_delta_std ────────────────────────────────────────

class TestScoreDeltaStd:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_delta_std() == pytest.approx(0.0)

    def test_two_entries_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.3)
        _push_opt(o, 0.7)
        assert o.score_delta_std() == pytest.approx(0.0)

    def test_constant_deltas_returns_zero(self):
        o = _make_optimizer()
        for v in [0.2, 0.4, 0.6, 0.8]:
            _push_opt(o, v)
        assert o.score_delta_std() == pytest.approx(0.0)

    def test_varying_deltas_positive_std(self):
        o = _make_optimizer()
        for v in [0.5, 0.9, 0.2, 0.8]:
            _push_opt(o, v)
        assert o.score_delta_std() > 0.0


# ── OntologyOptimizer.history_coefficient_of_variation ───────────────────────

class TestHistoryCoefficientOfVariation:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_coefficient_of_variation() == pytest.approx(0.0)

    def test_uniform_returns_zero(self):
        o = _make_optimizer()
        for _ in range(4):
            _push_opt(o, 0.5)
        assert o.history_coefficient_of_variation() == pytest.approx(0.0)

    def test_known_cv(self):
        o = _make_optimizer()
        # vals: [0.4, 0.6] mean=0.5, std=0.1, cv=0.2
        _push_opt(o, 0.4)
        _push_opt(o, 0.6)
        assert o.history_coefficient_of_variation() == pytest.approx(0.2)

    def test_zero_mean_returns_zero(self):
        o = _make_optimizer()
        for _ in range(3):
            _push_opt(o, 0.0)
        assert o.history_coefficient_of_variation() == pytest.approx(0.0)


# ── OntologyCritic.dimension_sum ─────────────────────────────────────────────

class TestDimensionSum:
    def test_all_half_returns_three(self):
        c = _make_critic()
        s = _make_score()  # all 0.5
        assert c.dimension_sum(s) == pytest.approx(3.0)

    def test_all_zero_returns_zero(self):
        c = _make_critic()
        s = _make_score(completeness=0.0, consistency=0.0, clarity=0.0,
                        granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0)
        assert c.dimension_sum(s) == pytest.approx(0.0)

    def test_all_one_returns_six(self):
        c = _make_critic()
        s = _make_score(completeness=1.0, consistency=1.0, clarity=1.0,
                        granularity=1.0, relationship_coherence=1.0, domain_alignment=1.0)
        assert c.dimension_sum(s) == pytest.approx(6.0)


# ── OntologyGenerator.relationship_avg_weight ────────────────────────────────

class TestRelationshipAvgWeight:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result([])
        assert g.relationship_avg_weight(r) == pytest.approx(0.0)

    def test_single_relationship(self):
        g = _make_generator()
        r = _make_result([_make_rel_mock(weight=0.8)])
        assert g.relationship_avg_weight(r) == pytest.approx(0.8)

    def test_average_of_multiple(self):
        g = _make_generator()
        rels = [_make_rel_mock(w) for w in [0.4, 0.6, 0.8]]
        r = _make_result(rels)
        assert g.relationship_avg_weight(r) == pytest.approx(0.6)


# ── OntologyPipeline.run_score_min ───────────────────────────────────────────

class TestRunScoreMin:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_min() == pytest.approx(0.0)

    def test_single_run(self):
        p = _make_pipeline()
        _push_run(p, 0.6)
        assert p.run_score_min() == pytest.approx(0.6)

    def test_minimum_of_multiple(self):
        p = _make_pipeline()
        for v in [0.5, 0.2, 0.8]:
            _push_run(p, v)
        assert p.run_score_min() == pytest.approx(0.2)


# ── OntologyPipeline.run_score_max ───────────────────────────────────────────

class TestRunScoreMax:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_max() == pytest.approx(0.0)

    def test_single_run(self):
        p = _make_pipeline()
        _push_run(p, 0.4)
        assert p.run_score_max() == pytest.approx(0.4)

    def test_maximum_of_multiple(self):
        p = _make_pipeline()
        for v in [0.3, 0.9, 0.6]:
            _push_run(p, v)
        assert p.run_score_max() == pytest.approx(0.9)


# ── OntologyLearningAdapter.feedback_variance ────────────────────────────────

class TestFeedbackVariance:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_variance() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_variance() == pytest.approx(0.0)

    def test_uniform_returns_zero(self):
        a = _make_adapter()
        for _ in range(4):
            _push_feedback(a, 0.6)
        assert a.feedback_variance() == pytest.approx(0.0)

    def test_known_variance(self):
        a = _make_adapter()
        _push_feedback(a, 0.4)
        _push_feedback(a, 0.6)
        # mean = 0.5, variance = 0.01
        assert a.feedback_variance() == pytest.approx(0.01)
