"""Batch-119 feature tests.

Methods under test:
  - OntologyCritic.score_delta_between(a, b)
  - OntologyCritic.all_pass(scores, threshold)
  - OntologyCritic.score_variance(scores)
  - OntologyCritic.best_score(scores)
"""
import pytest
import dataclasses as _dc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_critic():
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    return OntologyCritic(use_llm=False)


def _score(overall):
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
    # CriticScore is a dataclass; overall is a @property computed from dims
    # Set equal dims so overall equals the target value
    # overall = mean(completeness, consistency, clarity, granularity, domain_alignment)
    s = CriticScore(
        completeness=overall,
        consistency=overall,
        clarity=overall,
        granularity=overall,
        relationship_coherence=overall, domain_alignment=overall,
    )
    return s


# ---------------------------------------------------------------------------
# OntologyCritic.score_delta_between
# ---------------------------------------------------------------------------

class TestScoreDeltaBetween:
    def test_improvement(self):
        c = _make_critic()
        a = _score(0.5)
        b = _score(0.8)
        assert c.score_delta_between(a, b) == pytest.approx(0.3)

    def test_decline(self):
        c = _make_critic()
        a = _score(0.8)
        b = _score(0.5)
        assert c.score_delta_between(a, b) == pytest.approx(-0.3)

    def test_equal(self):
        c = _make_critic()
        a = _score(0.6)
        b = _score(0.6)
        assert c.score_delta_between(a, b) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# OntologyCritic.all_pass
# ---------------------------------------------------------------------------

class TestAllPass:
    def test_empty_list_is_true(self):
        c = _make_critic()
        assert c.all_pass([]) is True

    def test_all_above_threshold(self):
        c = _make_critic()
        scores = [_score(0.7), _score(0.8), _score(0.9)]
        assert c.all_pass(scores, threshold=0.6) is True

    def test_one_below_threshold(self):
        c = _make_critic()
        scores = [_score(0.7), _score(0.4), _score(0.9)]
        assert c.all_pass(scores, threshold=0.6) is False

    def test_exactly_at_threshold(self):
        c = _make_critic()
        scores = [_score(0.6), _score(0.7)]
        # Exactly at threshold does NOT pass (strict >)
        assert c.all_pass(scores, threshold=0.6) is False


# ---------------------------------------------------------------------------
# OntologyCritic.score_variance
# ---------------------------------------------------------------------------

class TestScoreVariance:
    def test_empty(self):
        c = _make_critic()
        assert c.score_variance([]) == pytest.approx(0.0)

    def test_single(self):
        c = _make_critic()
        assert c.score_variance([_score(0.7)]) == pytest.approx(0.0)

    def test_equal_scores(self):
        c = _make_critic()
        scores = [_score(0.5), _score(0.5), _score(0.5)]
        assert c.score_variance(scores) == pytest.approx(0.0)

    def test_varied_scores(self):
        c = _make_critic()
        scores = [_score(0.0), _score(1.0)]
        assert c.score_variance(scores) == pytest.approx(0.25)

    def test_positive(self):
        c = _make_critic()
        scores = [_score(0.2), _score(0.5), _score(0.8)]
        assert c.score_variance(scores) > 0.0


# ---------------------------------------------------------------------------
# OntologyCritic.best_score
# ---------------------------------------------------------------------------

class TestBestScore:
    def test_empty_returns_none(self):
        c = _make_critic()
        assert c.best_score([]) is None

    def test_single(self):
        c = _make_critic()
        s = _score(0.7)
        assert c.best_score([s]) is s

    def test_multiple(self):
        c = _make_critic()
        low = _score(0.3)
        high = _score(0.9)
        mid = _score(0.6)
        result = c.best_score([low, high, mid])
        assert result.overall == pytest.approx(0.9)
