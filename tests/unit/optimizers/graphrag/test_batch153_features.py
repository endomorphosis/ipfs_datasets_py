"""Batch-153 feature tests.

Methods under test:
  - OntologyOptimizer.first_n_history(n)
  - OntologyLearningAdapter.feedback_rolling_average(window)
  - OntologyCritic.dimension_variance(scores, dim)
  - LogicValidator.average_path_length(ontology)
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


# ---------------------------------------------------------------------------
# OntologyOptimizer.first_n_history
# ---------------------------------------------------------------------------

class TestFirstNHistory:
    def test_empty_returns_empty(self):
        o = _make_optimizer()
        assert o.first_n_history(5) == []

    def test_n_zero_returns_empty(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.first_n_history(0) == []

    def test_returns_first_n(self):
        o = _make_optimizer()
        for v in [0.1, 0.5, 0.9]:
            _push_opt(o, v)
        result = o.first_n_history(2)
        assert len(result) == 2
        assert result[0].average_score == pytest.approx(0.1)
        assert result[1].average_score == pytest.approx(0.5)

    def test_n_larger_than_history(self):
        o = _make_optimizer()
        for v in [0.3, 0.7]:
            _push_opt(o, v)
        result = o.first_n_history(10)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_rolling_average
# ---------------------------------------------------------------------------

class TestFeedbackRollingAverage:
    def test_empty_returns_empty(self):
        a = _make_adapter()
        assert a.feedback_rolling_average() == []

    def test_same_length_as_feedback(self):
        a = _make_adapter()
        for v in [0.3, 0.5, 0.7]:
            _push_feedback(a, v)
        result = a.feedback_rolling_average(window=2)
        assert len(result) == 3

    def test_first_element_equals_first_score(self):
        a = _make_adapter()
        _push_feedback(a, 0.4)
        _push_feedback(a, 0.8)
        result = a.feedback_rolling_average(window=2)
        assert result[0] == pytest.approx(0.4)

    def test_rolling_average_correct(self):
        a = _make_adapter()
        for v in [0.2, 0.4, 0.6]:
            _push_feedback(a, v)
        result = a.feedback_rolling_average(window=2)
        # [0.2, (0.2+0.4)/2, (0.4+0.6)/2] = [0.2, 0.3, 0.5]
        assert result[1] == pytest.approx(0.3)
        assert result[2] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# OntologyCritic.dimension_variance
# ---------------------------------------------------------------------------

class TestDimensionVariance:
    def test_empty_returns_zero(self):
        critic = _make_critic()
        assert critic.dimension_variance([], "completeness") == pytest.approx(0.0)

    def test_single_score_returns_zero(self):
        critic = _make_critic()
        s = _make_score()
        assert critic.dimension_variance([s], "completeness") == pytest.approx(0.0)

    def test_identical_scores_returns_zero(self):
        critic = _make_critic()
        scores = [_make_score(completeness=0.5) for _ in range(3)]
        assert critic.dimension_variance(scores, "completeness") == pytest.approx(0.0)

    def test_known_variance(self):
        critic = _make_critic()
        s1 = _make_score(completeness=0.0)
        s2 = _make_score(completeness=1.0)
        # population variance of [0, 1] = 0.25
        assert critic.dimension_variance([s1, s2], "completeness") == pytest.approx(0.25)

    def test_invalid_dim_raises(self):
        critic = _make_critic()
        s = _make_score()
        with pytest.raises(AttributeError):
            critic.dimension_variance([s, s], "nonexistent_dim")


# ---------------------------------------------------------------------------
# LogicValidator.average_path_length
# ---------------------------------------------------------------------------

class TestAveragePathLength:
    def test_empty_returns_zero(self):
        v = _make_validator()
        assert v.average_path_length({}) == pytest.approx(0.0)

    def test_no_edges_returns_zero(self):
        v = _make_validator()
        ont = {"entities": [{"id": "A"}, {"id": "B"}], "relationships": []}
        assert v.average_path_length(ont) == pytest.approx(0.0)

    def test_simple_chain(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
            "relationships": [
                {"subject_id": "A", "object_id": "B"},
                {"subject_id": "B", "object_id": "C"},
            ],
        }
        # A→B=1, A→C=2, B→C=1  → mean of [1, 2, 1] = 4/3
        result = v.average_path_length(ont)
        assert result == pytest.approx(4 / 3)

    def test_non_negative(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "X"}, {"id": "Y"}],
            "relationships": [{"subject_id": "X", "object_id": "Y"}],
        }
        assert v.average_path_length(ont) >= 0.0
