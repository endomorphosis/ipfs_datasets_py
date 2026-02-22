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
    def test_empty_returns_zero(self):
        c = _make_critic()
        assert c.improvement_over_baseline([]) == pytest.approx(0.0)

    def test_all_above(self):
        c = _make_critic()
        scores = [_cs(0.7), _cs(0.8), _cs(0.9)]
        assert c.improvement_over_baseline(scores, baseline=0.5) == pytest.approx(1.0)

    def test_all_below(self):
        c = _make_critic()
        scores = [_cs(0.1), _cs(0.2)]
        assert c.improvement_over_baseline(scores, baseline=0.5) == pytest.approx(0.0)

    def test_half_above(self):
        c = _make_critic()
        scores = [_cs(0.3), _cs(0.7)]
        assert c.improvement_over_baseline(scores, baseline=0.5) == pytest.approx(0.5)

    def test_exact_baseline_not_counted(self):
        """Strict > not >="""
        c = _make_critic()
        scores = [_cs(0.5)]
        assert c.improvement_over_baseline(scores, baseline=0.5) == pytest.approx(0.0)

    def test_returns_float(self):
        c = _make_critic()
        result = c.improvement_over_baseline([_cs(0.6)], baseline=0.5)
        assert isinstance(result, float)


# ---------------------------------------------------------------------------
# OntologyCritic.score_iqr
# ---------------------------------------------------------------------------

class TestScoreIQR:
    def test_empty_returns_zero(self):
        c = _make_critic()
        assert c.score_iqr([]) == pytest.approx(0.0)

    def test_fewer_than_four_returns_zero(self):
        c = _make_critic()
        assert c.score_iqr([_cs(0.5), _cs(0.6)]) == pytest.approx(0.0)

    def test_four_scores(self):
        c = _make_critic()
        scores = [_cs(v) for v in [0.1, 0.3, 0.7, 0.9]]
        result = c.score_iqr(scores)
        assert result > 0.0

    def test_all_same_returns_zero(self):
        c = _make_critic()
        scores = [_cs(0.5) for _ in range(8)]
        assert c.score_iqr(scores) == pytest.approx(0.0)

    def test_non_negative(self):
        c = _make_critic()
        scores = [_cs(v) for v in [0.2, 0.4, 0.6, 0.8, 0.9]]
        assert c.score_iqr(scores) >= 0.0


# ---------------------------------------------------------------------------
# OntologyMediator.total_actions_taken
# ---------------------------------------------------------------------------

class TestTotalActionsTaken:
    def test_empty_returns_zero(self):
        m = _make_mediator()
        assert m.total_actions_taken() == 0

    def test_sum_of_counts(self):
        m = _make_mediator()
        m._action_counts["ADD"] = 3
        m._action_counts["REMOVE"] = 2
        assert m.total_actions_taken() == 5

    def test_single_action(self):
        m = _make_mediator()
        m._action_counts["MERGE"] = 7
        assert m.total_actions_taken() == 7

    def test_returns_int(self):
        m = _make_mediator()
        assert isinstance(m.total_actions_taken(), int)


# ---------------------------------------------------------------------------
# OntologyMediator.unique_action_count
# ---------------------------------------------------------------------------

class TestUniqueActionCount:
    def test_empty_returns_zero(self):
        m = _make_mediator()
        assert m.unique_action_count() == 0

    def test_single_used_action(self):
        m = _make_mediator()
        m._action_counts["ADD"] = 5
        m._action_counts["REMOVE"] = 0
        assert m.unique_action_count() == 1

    def test_two_used_actions(self):
        m = _make_mediator()
        m._action_counts["ADD"] = 3
        m._action_counts["REMOVE"] = 2
        assert m.unique_action_count() == 2

    def test_returns_int(self):
        m = _make_mediator()
        assert isinstance(m.unique_action_count(), int)
