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
    @pytest.mark.parametrize(
        "scores,n,expected",
        [
            ([], 5, []),
            ([0.5], 0, []),
            ([0.1, 0.5, 0.9], 2, [0.1, 0.5]),
            ([0.3, 0.7], 10, [0.3, 0.7]),
        ],
    )
    def test_first_n_history_scenarios(self, scores, n, expected):
        o = _make_optimizer()
        for v in scores:
            _push_opt(o, v)
        result = o.first_n_history(n)
        assert [entry.average_score for entry in result] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_rolling_average
# ---------------------------------------------------------------------------

class TestFeedbackRollingAverage:
    @pytest.mark.parametrize(
        "scores,window,predicate",
        [
            ([], 2, lambda result: result == []),
            ([0.3, 0.5, 0.7], 2, lambda result: len(result) == 3),
            ([0.4, 0.8], 2, lambda result: result[0] == pytest.approx(0.4)),
            (
                [0.2, 0.4, 0.6],
                2,
                # [0.2, 0.3, 0.5]
                lambda result: result[1] == pytest.approx(0.3) and result[2] == pytest.approx(0.5),
            ),
        ],
    )
    def test_feedback_rolling_average_scenarios(self, scores, window, predicate):
        a = _make_adapter()
        for v in scores:
            _push_feedback(a, v)
        result = a.feedback_rolling_average(window=window)
        assert predicate(result)


# ---------------------------------------------------------------------------
# OntologyCritic.dimension_variance
# ---------------------------------------------------------------------------

class TestDimensionVariance:
    @pytest.mark.parametrize(
        "scores,dim,expected",
        [
            ([], "completeness", 0.0),
            ([_make_score()], "completeness", 0.0),
            ([_make_score(completeness=0.5) for _ in range(3)], "completeness", 0.0),
            # population variance of [0, 1] = 0.25
            ([_make_score(completeness=0.0), _make_score(completeness=1.0)], "completeness", 0.25),
        ],
    )
    def test_dimension_variance_scenarios(self, scores, dim, expected):
        critic = _make_critic()
        assert critic.dimension_variance(scores, dim) == pytest.approx(expected)

    def test_invalid_dim_raises(self):
        critic = _make_critic()
        s = _make_score()
        with pytest.raises(AttributeError):
            critic.dimension_variance([s, s], "nonexistent_dim")


# ---------------------------------------------------------------------------
# LogicValidator.average_path_length
# ---------------------------------------------------------------------------

class TestAveragePathLength:
    @pytest.mark.parametrize(
        "ontology,predicate",
        [
            ({}, lambda result: result == pytest.approx(0.0)),
            (
                {"entities": [{"id": "A"}, {"id": "B"}], "relationships": []},
                lambda result: result == pytest.approx(0.0),
            ),
            (
                {
                    "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
                    "relationships": [{"subject_id": "A", "object_id": "B"}, {"subject_id": "B", "object_id": "C"}],
                },
                # A->B=1, A->C=2, B->C=1 => 4/3
                lambda result: result == pytest.approx(4 / 3),
            ),
            (
                {"entities": [{"id": "X"}, {"id": "Y"}], "relationships": [{"subject_id": "X", "object_id": "Y"}]},
                lambda result: result >= 0.0,
            ),
        ],
    )
    def test_average_path_length_scenarios(self, ontology, predicate):
        v = _make_validator()
        assert predicate(v.average_path_length(ontology))
