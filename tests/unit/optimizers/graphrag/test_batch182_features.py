"""Batch-182 feature tests.

Methods under test:
  - OntologyOptimizer.score_above_mean_fraction()
  - OntologyOptimizer.history_gini()
  - OntologyCritic.dimension_geometric_mean(score)
  - OntologyCritic.dimensions_below_count(score, threshold)
  - LogicValidator.average_in_degree(ontology)
  - LogicValidator.average_out_degree(ontology)
  - OntologyPipeline.run_score_range()
  - OntologyPipeline.run_score_above_mean_fraction()
  - OntologyLearningAdapter.feedback_consecutive_positive()
  - OntologyLearningAdapter.feedback_gini()
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


class _FakeRel:
    def __init__(self, src, tgt):
        self.source_id = src
        self.target_id = tgt


class _FakeOntology:
    def __init__(self, rels):
        self.relationships = rels


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


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


# ── OntologyOptimizer.score_above_mean_fraction ───────────────────────────────

class TestScoreAboveMeanFraction:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_above_mean_fraction() == pytest.approx(0.0)

    def test_all_same_returns_zero(self):
        o = _make_optimizer()
        for _ in range(4):
            _push_opt(o, 0.5)
        assert o.score_above_mean_fraction() == pytest.approx(0.0)

    def test_half_above(self):
        o = _make_optimizer()
        _push_opt(o, 0.3)
        _push_opt(o, 0.7)
        # mean = 0.5; only 0.7 > 0.5
        assert o.score_above_mean_fraction() == pytest.approx(0.5)

    def test_returns_float(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert isinstance(o.score_above_mean_fraction(), float)


# ── OntologyOptimizer.history_gini ────────────────────────────────────────────

class TestHistoryGini:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_gini() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.history_gini() == pytest.approx(0.0)

    def test_all_same_returns_zero(self):
        o = _make_optimizer()
        for _ in range(4):
            _push_opt(o, 0.5)
        assert o.history_gini() == pytest.approx(0.0, abs=1e-6)

    def test_nonzero_for_unequal(self):
        o = _make_optimizer()
        _push_opt(o, 0.1)
        _push_opt(o, 0.9)
        assert o.history_gini() > 0

    def test_bounded_in_range(self):
        o = _make_optimizer()
        for v in [0.1, 0.3, 0.5, 0.7, 0.9]:
            _push_opt(o, v)
        g = o.history_gini()
        assert 0.0 <= g <= 1.0


# ── OntologyCritic.dimension_geometric_mean ───────────────────────────────────

class TestDimensionGeometricMean:
    def test_all_same_equals_that_value(self):
        c = _make_critic()
        assert c.dimension_geometric_mean(_make_score()) == pytest.approx(0.5, rel=1e-3)

    def test_all_one(self):
        c = _make_critic()
        score = _make_score(**{d: 1.0 for d in ["completeness", "consistency", "clarity",
                                                   "granularity", "relationship_coherence", "domain_alignment"]})
        assert c.dimension_geometric_mean(score) == pytest.approx(1.0, rel=1e-3)

    def test_geom_leq_arith(self):
        c = _make_critic()
        score = _make_score(completeness=0.9, consistency=0.1)
        dims = ["completeness", "consistency", "clarity", "granularity", "relationship_coherence", "domain_alignment"]
        arith = sum(getattr(score, d) for d in dims) / 6
        assert c.dimension_geometric_mean(score) <= arith + 1e-9

    def test_returns_float(self):
        c = _make_critic()
        assert isinstance(c.dimension_geometric_mean(_make_score()), float)


# ── OntologyCritic.dimensions_below_count ─────────────────────────────────────

class TestDimensionsBelowCount:
    def test_none_below(self):
        c = _make_critic()
        assert c.dimensions_below_count(_make_score(), threshold=0.3) == 0

    def test_some_below(self):
        c = _make_critic()
        score = _make_score(completeness=0.1, consistency=0.2)
        assert c.dimensions_below_count(score, threshold=0.3) == 2

    def test_all_below(self):
        c = _make_critic()
        score = _make_score(**{d: 0.0 for d in ["completeness", "consistency", "clarity",
                                                   "granularity", "relationship_coherence", "domain_alignment"]})
        assert c.dimensions_below_count(score, threshold=0.3) == 6

    def test_returns_int(self):
        c = _make_critic()
        assert isinstance(c.dimensions_below_count(_make_score()), int)


# ── LogicValidator.average_in_degree ──────────────────────────────────────────

class TestAverageInDegree:
    def test_empty_returns_zero(self):
        v = _make_validator()
        assert v.average_in_degree(_FakeOntology([])) == pytest.approx(0.0)

    def test_single_edge(self):
        v = _make_validator()
        # 2 nodes, 1 edge → target_id ("b") has in-degree 1, "a" has 0 → sum=1, nodes=2
        rels = [_FakeRel("a", "b")]
        assert v.average_in_degree(_FakeOntology(rels)) == pytest.approx(0.5)

    def test_multiple_edges(self):
        v = _make_validator()
        rels = [_FakeRel("a", "c"), _FakeRel("b", "c")]
        # nodes: a, b, c (3); c has in-degree 2
        result = v.average_in_degree(_FakeOntology(rels))
        assert result == pytest.approx(2 / 3)


# ── LogicValidator.average_out_degree ─────────────────────────────────────────

class TestAverageOutDegree:
    def test_empty_returns_zero(self):
        v = _make_validator()
        assert v.average_out_degree(_FakeOntology([])) == pytest.approx(0.0)

    def test_single_edge(self):
        v = _make_validator()
        rels = [_FakeRel("a", "b")]
        # 2 nodes, a has out-degree 1
        assert v.average_out_degree(_FakeOntology(rels)) == pytest.approx(0.5)

    def test_multiple_sources(self):
        v = _make_validator()
        rels = [_FakeRel("a", "c"), _FakeRel("a", "b")]
        # nodes: a, b, c; a has out=2
        result = v.average_out_degree(_FakeOntology(rels))
        assert result == pytest.approx(2 / 3)


# ── OntologyPipeline.run_score_range ──────────────────────────────────────────

class TestRunScoreRange:
    def test_no_runs_returns_zeros(self):
        p = _make_pipeline()
        lo, hi = p.run_score_range()
        assert lo == pytest.approx(0.0)
        assert hi == pytest.approx(0.0)

    def test_single_run(self):
        p = _make_pipeline()
        _push_run(p, 0.7)
        lo, hi = p.run_score_range()
        assert lo == pytest.approx(0.7)
        assert hi == pytest.approx(0.7)

    def test_multiple_runs(self):
        p = _make_pipeline()
        for v in [0.3, 0.6, 0.9]:
            _push_run(p, v)
        lo, hi = p.run_score_range()
        assert lo == pytest.approx(0.3)
        assert hi == pytest.approx(0.9)

    def test_returns_tuple(self):
        p = _make_pipeline()
        result = p.run_score_range()
        assert isinstance(result, tuple)


# ── OntologyPipeline.run_score_above_mean_fraction ───────────────────────────

class TestRunScoreAboveMeanFraction:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_above_mean_fraction() == pytest.approx(0.0)

    def test_all_same_returns_zero(self):
        p = _make_pipeline()
        for _ in range(3):
            _push_run(p, 0.5)
        assert p.run_score_above_mean_fraction() == pytest.approx(0.0)

    def test_half_above(self):
        p = _make_pipeline()
        _push_run(p, 0.3)
        _push_run(p, 0.7)
        assert p.run_score_above_mean_fraction() == pytest.approx(0.5)


# ── OntologyLearningAdapter.feedback_consecutive_positive ────────────────────

class TestFeedbackConsecutivePositive:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_consecutive_positive() == 0

    def test_all_positive(self):
        a = _make_adapter()
        for v in [0.6, 0.7, 0.8]:
            _push_feedback(a, v)
        assert a.feedback_consecutive_positive() == 3

    def test_trailing_positives_only(self):
        a = _make_adapter()
        _push_feedback(a, 0.2)
        _push_feedback(a, 0.7)
        _push_feedback(a, 0.8)
        assert a.feedback_consecutive_positive() == 2

    def test_all_negative_returns_zero(self):
        a = _make_adapter()
        for v in [0.1, 0.2]:
            _push_feedback(a, v)
        assert a.feedback_consecutive_positive() == 0


# ── OntologyLearningAdapter.feedback_gini ────────────────────────────────────

class TestFeedbackGini:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_gini() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_gini() == pytest.approx(0.0)

    def test_all_same_returns_zero(self):
        a = _make_adapter()
        for _ in range(4):
            _push_feedback(a, 0.5)
        assert a.feedback_gini() == pytest.approx(0.0, abs=1e-6)

    def test_nonzero_for_unequal(self):
        a = _make_adapter()
        _push_feedback(a, 0.1)
        _push_feedback(a, 0.9)
        assert a.feedback_gini() > 0
