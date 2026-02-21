"""Batch-170 feature tests.

Methods under test:
  - OntologyOptimizer.score_gini_coefficient()
  - OntologyCritic.dimension_correlation(scores_a, scores_b, dimension)
  - LogicValidator.graph_diameter(ontology)
  - OntologyLearningAdapter.feedback_percentile_rank(value)
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


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(a, score):
    r = MagicMock()
    r.final_score = score
    a._feedback.append(r)


def _ont(entities, rels):
    return {"entities": entities, "relationships": rels}


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_gini_coefficient
# ---------------------------------------------------------------------------

class TestScoreGiniCoefficient:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_gini_coefficient() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.score_gini_coefficient() == pytest.approx(0.0)

    def test_equal_scores_zero_gini(self):
        o = _make_optimizer()
        for _ in range(5):
            _push_opt(o, 0.5)
        assert o.score_gini_coefficient() == pytest.approx(0.0)

    def test_non_negative(self):
        o = _make_optimizer()
        for v in [0.1, 0.3, 0.7, 0.9]:
            _push_opt(o, v)
        assert o.score_gini_coefficient() >= 0.0

    def test_more_unequal_higher_gini(self):
        o_even = _make_optimizer()
        for _ in range(4):
            _push_opt(o_even, 0.5)
        o_uneven = _make_optimizer()
        for v in [0.0, 0.0, 0.0, 1.0]:
            _push_opt(o_uneven, v)
        assert o_uneven.score_gini_coefficient() > o_even.score_gini_coefficient()


# ---------------------------------------------------------------------------
# OntologyCritic.dimension_correlation
# ---------------------------------------------------------------------------

class TestDimensionCorrelation:
    def test_empty_returns_zero(self):
        critic = _make_critic()
        assert critic.dimension_correlation([], [], "completeness") == pytest.approx(0.0)

    def test_perfect_positive_correlation(self):
        critic = _make_critic()
        scores_a = [_make_score(completeness=v) for v in [0.2, 0.5, 0.8]]
        scores_b = [_make_score(completeness=v) for v in [0.2, 0.5, 0.8]]
        r = critic.dimension_correlation(scores_a, scores_b, "completeness")
        assert r == pytest.approx(1.0, abs=1e-6)

    def test_single_pair_returns_zero(self):
        critic = _make_critic()
        scores_a = [_make_score()]
        scores_b = [_make_score()]
        assert critic.dimension_correlation(scores_a, scores_b) == pytest.approx(0.0)

    def test_constant_series_returns_zero(self):
        critic = _make_critic()
        scores_a = [_make_score(completeness=0.5) for _ in range(4)]
        scores_b = [_make_score(completeness=0.5) for _ in range(4)]
        assert critic.dimension_correlation(scores_a, scores_b) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# LogicValidator.graph_diameter
# ---------------------------------------------------------------------------

class TestGraphDiameter:
    def test_empty_returns_zero(self):
        v = _make_validator()
        assert v.graph_diameter(_ont([], [])) == 0

    def test_single_entity_returns_zero(self):
        v = _make_validator()
        assert v.graph_diameter(_ont([{"id": "a"}], [])) == 0

    def test_direct_edge_diameter_one(self):
        v = _make_validator()
        ont = _ont(
            [{"id": "a"}, {"id": "b"}],
            [{"source": "a", "target": "b", "type": "r"}],
        )
        assert v.graph_diameter(ont) == 1

    def test_chain_of_three(self):
        v = _make_validator()
        ont = _ont(
            [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            [
                {"source": "a", "target": "b", "type": "r"},
                {"source": "b", "target": "c", "type": "r"},
            ],
        )
        assert v.graph_diameter(ont) == 2

    def test_disconnected_no_path(self):
        v = _make_validator()
        ont = _ont(
            [{"id": "a"}, {"id": "b"}],
            [],  # no edges
        )
        assert v.graph_diameter(ont) == 0


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_percentile_rank
# ---------------------------------------------------------------------------

class TestFeedbackPercentileRank:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_percentile_rank(0.5) == pytest.approx(0.0)

    def test_value_below_all(self):
        a = _make_adapter()
        for v in [0.5, 0.7, 0.9]:
            _push_feedback(a, v)
        assert a.feedback_percentile_rank(0.3) == pytest.approx(0.0)

    def test_value_above_all(self):
        a = _make_adapter()
        for v in [0.3, 0.5, 0.7]:
            _push_feedback(a, v)
        assert a.feedback_percentile_rank(0.9) == pytest.approx(1.0)

    def test_value_in_middle(self):
        a = _make_adapter()
        for v in [0.2, 0.4, 0.6, 0.8]:
            _push_feedback(a, v)
        # 2 records below 0.5 (0.2 and 0.4) => 2/4 = 0.5
        assert a.feedback_percentile_rank(0.5) == pytest.approx(0.5)
