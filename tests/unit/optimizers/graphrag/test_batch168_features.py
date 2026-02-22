"""Batch-168 feature tests.

Methods under test:
  - OntologyMediator.clear_feedback()
  - OntologyMediator.feedback_score_mean()
  - OntologyCritic.weighted_score(score, weights)
  - OntologyPipeline.run_moving_average(n)
  - OntologyPipeline.convergence_round(variance_threshold)
"""
import pytest
from unittest.mock import MagicMock


def _make_mediator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
    gen = MagicMock()
    critic = MagicMock()
    return OntologyMediator(gen, critic)


def _make_critic():
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    return OntologyCritic(use_llm=False)


def _make_score(**kwargs):
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
    defaults = dict(
        completeness=0.5, consistency=0.5, clarity=0.5,
        granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5,
    )
    defaults.update(kwargs)
    return CriticScore(**defaults)


def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline()


def _push_run(p, score):
    r = MagicMock()
    r.score.overall = score
    p._run_history.append(r)


# ---------------------------------------------------------------------------
# OntologyMediator.clear_feedback / feedback_score_mean
# ---------------------------------------------------------------------------

class TestClearFeedback:
    def test_empty_mediator_clears_zero(self):
        m = _make_mediator()
        removed = m.clear_feedback()
        assert removed == 0

    def test_clears_feedback_list(self):
        m = _make_mediator()
        m._feedback = [MagicMock(), MagicMock()]
        removed = m.clear_feedback()
        assert removed == 2

    def test_after_clear_size_is_zero(self):
        m = _make_mediator()
        m._feedback = [MagicMock()]
        m.clear_feedback()
        assert m.feedback_history_size() == 0


class TestFeedbackScoreMean:
    def test_empty_returns_zero(self):
        m = _make_mediator()
        assert m.feedback_score_mean() == pytest.approx(0.0)

    def test_single_record_with_final_score(self):
        m = _make_mediator()
        r = MagicMock()
        r.final_score = 0.8
        r.score = None
        m._feedback = [r]
        assert m.feedback_score_mean() == pytest.approx(0.8)

    def test_multiple_records(self):
        m = _make_mediator()
        scores = [0.4, 0.6, 0.8]
        records = []
        for s in scores:
            r = MagicMock()
            r.final_score = s
            r.score = None
            records.append(r)
        m._feedback = records
        assert m.feedback_score_mean() == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# OntologyCritic.weighted_score
# ---------------------------------------------------------------------------

class TestWeightedScore:
    def test_equal_weights_equals_mean(self):
        critic = _make_critic()
        score = _make_score()  # all 0.5
        # equal weights → same as mean = 0.5
        result = critic.weighted_score(score)
        assert result == pytest.approx(0.5)

    def test_custom_weights(self):
        critic = _make_critic()
        score = _make_score(completeness=1.0, consistency=0.0, clarity=0.0,
                            granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0)
        # give completeness all the weight
        weights = {"completeness": 10.0}
        result = critic.weighted_score(score, weights)
        # weighted average: (1.0*10 + 0.0*1 + ...) / (10 + 5*1) = 10/15
        assert result == pytest.approx(10.0 / 15.0)

    def test_none_weights_uses_equal(self):
        critic = _make_critic()
        score = _make_score()
        assert critic.weighted_score(score, None) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# OntologyPipeline.run_moving_average
# ---------------------------------------------------------------------------

class TestRunMovingAverage:
    def test_empty_returns_empty(self):
        p = _make_pipeline()
        assert p.run_moving_average(3) == []

    def test_fewer_than_n_returns_empty(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        _push_run(p, 0.6)
        assert p.run_moving_average(3) == []

    def test_exactly_n_returns_one(self):
        p = _make_pipeline()
        for v in [0.3, 0.6, 0.9]:
            _push_run(p, v)
        result = p.run_moving_average(3)
        assert len(result) == 1
        assert result[0] == pytest.approx(0.6)

    def test_more_than_n(self):
        p = _make_pipeline()
        for v in [0.2, 0.4, 0.6, 0.8]:
            _push_run(p, v)
        result = p.run_moving_average(2)
        assert result == pytest.approx([0.3, 0.5, 0.7])


# ---------------------------------------------------------------------------
# OntologyPipeline.convergence_round
# ---------------------------------------------------------------------------

class TestConvergenceRound:
    def test_empty_returns_minus_one(self):
        p = _make_pipeline()
        assert p.convergence_round() == -1

    def test_too_few_runs(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        _push_run(p, 0.6)
        assert p.convergence_round() == -1

    def test_converges_at_third_round(self):
        p = _make_pipeline()
        for v in [0.5, 0.501, 0.502]:
            _push_run(p, v)
        # variance of [0.5, 0.501, 0.502] should be tiny
        result = p.convergence_round(variance_threshold=0.01)
        assert result == 2

    def test_never_converges(self):
        p = _make_pipeline()
        for v in [0.1, 0.9, 0.1, 0.9]:
            _push_run(p, v)
        assert p.convergence_round(variance_threshold=0.001) == -1
