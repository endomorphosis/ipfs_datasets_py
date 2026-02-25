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
    @pytest.mark.parametrize(
        "a,b,expected",
        [
            (0.5, 0.8, 0.3),
            (0.8, 0.5, -0.3),
            (0.6, 0.6, 0.0),
        ],
    )
    def test_delta_scenarios(self, a, b, expected):
        c = _make_critic()
        assert c.score_delta_between(_score(a), _score(b)) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# OntologyCritic.all_pass
# ---------------------------------------------------------------------------

class TestAllPass:
    def test_empty_list_is_true(self):
        c = _make_critic()
        assert c.all_pass([]) is True

    @pytest.mark.parametrize(
        "values,threshold,expected",
        [
            ([0.7, 0.8, 0.9], 0.6, True),
            ([0.7, 0.4, 0.9], 0.6, False),
            ([0.6, 0.7], 0.6, False),  # Exactly at threshold does NOT pass (strict >)
        ],
    )
    def test_threshold_scenarios(self, values, threshold, expected):
        c = _make_critic()
        scores = [_score(v) for v in values]
        assert c.all_pass(scores, threshold=threshold) is expected


# ---------------------------------------------------------------------------
# OntologyCritic.score_variance
# ---------------------------------------------------------------------------

class TestScoreVariance:
    @pytest.mark.parametrize(
        "values,expected",
        [
            ([], 0.0),
            ([0.7], 0.0),
            ([0.5, 0.5, 0.5], 0.0),
            ([0.0, 1.0], 0.25),
        ],
    )
    def test_variance_scenarios(self, values, expected):
        c = _make_critic()
        scores = [_score(v) for v in values]
        assert c.score_variance(scores) == pytest.approx(expected)

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
