"""Batch-128 feature tests.

Methods under test:
  - OntologyCritic.worst_score(scores)
  - OntologyCritic.average_overall(scores)
  - OntologyCritic.count_failing(scores, threshold)
"""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_critic():
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    return OntologyCritic(use_llm=False)


def _score(overall):
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
    return CriticScore(
        completeness=overall,
        consistency=overall,
        clarity=overall,
        granularity=overall,
        relationship_coherence=overall, domain_alignment=overall,
    )


# ---------------------------------------------------------------------------
# OntologyCritic.worst_score
# ---------------------------------------------------------------------------

class TestWorstScore:
    def test_empty_returns_none(self):
        c = _make_critic()
        assert c.worst_score([]) is None

    def test_single(self):
        c = _make_critic()
        s = _score(0.4)
        assert c.worst_score([s]) is s

    def test_multiple(self):
        c = _make_critic()
        scores = [_score(0.7), _score(0.3), _score(0.9)]
        result = c.worst_score(scores)
        assert result.overall == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# OntologyCritic.average_overall
# ---------------------------------------------------------------------------

class TestAverageOverall:
    def test_empty(self):
        c = _make_critic()
        assert c.average_overall([]) == pytest.approx(0.0)

    def test_single(self):
        c = _make_critic()
        assert c.average_overall([_score(0.6)]) == pytest.approx(0.6)

    def test_multiple(self):
        c = _make_critic()
        scores = [_score(0.4), _score(0.6), _score(0.8)]
        assert c.average_overall(scores) == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# OntologyCritic.count_failing
# ---------------------------------------------------------------------------

class TestCountFailing:
    def test_empty(self):
        c = _make_critic()
        assert c.count_failing([]) == 0

    def test_all_failing(self):
        c = _make_critic()
        scores = [_score(0.3), _score(0.4), _score(0.5)]
        assert c.count_failing(scores, threshold=0.6) == 3

    def test_none_failing(self):
        c = _make_critic()
        scores = [_score(0.7), _score(0.8)]
        assert c.count_failing(scores, threshold=0.6) == 0

    def test_exactly_at_threshold_counted(self):
        c = _make_critic()
        assert c.count_failing([_score(0.6)], threshold=0.6) == 1

    def test_partial(self):
        c = _make_critic()
        scores = [_score(0.3), _score(0.7), _score(0.9)]
        assert c.count_failing(scores, threshold=0.6) == 1
