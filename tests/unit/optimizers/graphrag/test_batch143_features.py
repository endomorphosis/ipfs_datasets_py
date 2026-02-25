"""Batch-143 feature tests.

Methods under test:
  - OntologyCritic.improvement_over_baseline(scores, baseline)
  - OntologyCritic.score_iqr(scores)
  - OntologyMediator.total_actions_taken()
  - OntologyMediator.unique_action_count()
"""
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_critic():
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    return OntologyCritic(use_llm=False)


def _cs(overall):
    s = MagicMock()
    s.overall = overall
    return s


def _make_mediator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
    gen = MagicMock()
    crit = MagicMock()
    return OntologyMediator(gen, crit)


# ---------------------------------------------------------------------------
# OntologyCritic.improvement_over_baseline
# ---------------------------------------------------------------------------

class TestImprovementOverBaseline:
    @pytest.mark.parametrize(
        "values,baseline,expected",
        [
            ([], 0.5, 0.0),
            ([0.7, 0.8, 0.9], 0.5, 1.0),
            ([0.1, 0.2], 0.5, 0.0),
            ([0.3, 0.7], 0.5, 0.5),
            # Strict > not >=
            ([0.5], 0.5, 0.0),
        ],
    )
    def test_improvement_over_baseline_scenarios(self, values, baseline, expected):
        c = _make_critic()
        scores = [_cs(v) for v in values]
        assert c.improvement_over_baseline(scores, baseline=baseline) == pytest.approx(expected)

    def test_returns_float(self):
        c = _make_critic()
        result = c.improvement_over_baseline([_cs(0.6)], baseline=0.5)
        assert isinstance(result, float)


# ---------------------------------------------------------------------------
# OntologyCritic.score_iqr
# ---------------------------------------------------------------------------

class TestScoreIQR:
    @pytest.mark.parametrize(
        "values,predicate",
        [
            ([], lambda result: result == pytest.approx(0.0)),
            ([0.5, 0.6], lambda result: result == pytest.approx(0.0)),
            ([0.1, 0.3, 0.7, 0.9], lambda result: result > 0.0),
            ([0.5] * 8, lambda result: result == pytest.approx(0.0)),
        ],
    )
    def test_score_iqr_scenarios(self, values, predicate):
        c = _make_critic()
        scores = [_cs(v) for v in values]
        assert predicate(c.score_iqr(scores))

    def test_non_negative(self):
        c = _make_critic()
        scores = [_cs(v) for v in [0.2, 0.4, 0.6, 0.8, 0.9]]
        assert c.score_iqr(scores) >= 0.0


# ---------------------------------------------------------------------------
# OntologyMediator.total_actions_taken
# ---------------------------------------------------------------------------

class TestTotalActionsTaken:
    @pytest.mark.parametrize(
        "counts,expected",
        [
            ({}, 0),
            ({"ADD": 3, "REMOVE": 2}, 5),
            ({"MERGE": 7}, 7),
        ],
    )
    def test_total_actions_taken_scenarios(self, counts, expected):
        m = _make_mediator()
        for name, value in counts.items():
            m._action_counts[name] = value
        assert m.total_actions_taken() == expected

    def test_returns_int(self):
        m = _make_mediator()
        assert isinstance(m.total_actions_taken(), int)


# ---------------------------------------------------------------------------
# OntologyMediator.unique_action_count
# ---------------------------------------------------------------------------

class TestUniqueActionCount:
    @pytest.mark.parametrize(
        "counts,expected",
        [
            ({}, 0),
            ({"ADD": 5, "REMOVE": 0}, 1),
            ({"ADD": 3, "REMOVE": 2}, 2),
        ],
    )
    def test_unique_action_count_scenarios(self, counts, expected):
        m = _make_mediator()
        for name, value in counts.items():
            m._action_counts[name] = value
        assert m.unique_action_count() == expected

    def test_returns_int(self):
        m = _make_mediator()
        assert isinstance(m.unique_action_count(), int)
