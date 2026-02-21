"""Batch-154 feature tests.

Methods under test:
  - OntologyLearningAdapter.worst_domain()
  - OntologyOptimizer.score_above_threshold(threshold)
  - OntologyCritic.weakest_dimension(score)
  - LogicValidator.node_degree_histogram(ontology)
"""
import pytest
from unittest.mock import MagicMock


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(a, score, domain=None):
    r = MagicMock()
    r.final_score = score
    r.domain = domain
    a._feedback.append(r)


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


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.worst_domain
# ---------------------------------------------------------------------------

class TestWorstDomain:
    def test_empty_returns_empty_string(self):
        a = _make_adapter()
        assert a.worst_domain() == ""

    def test_single_domain(self):
        a = _make_adapter()
        _push_feedback(a, 0.5, domain="science")
        result = a.worst_domain()
        assert result == "science"

    def test_returns_lowest_avg_domain(self):
        a = _make_adapter()
        _push_feedback(a, 0.8, domain="law")
        _push_feedback(a, 0.2, domain="medicine")
        _push_feedback(a, 0.3, domain="medicine")
        # law avg=0.8, medicine avg=0.25 → worst is medicine
        assert a.worst_domain() == "medicine"

    def test_no_domain_grouped_as_unknown(self):
        a = _make_adapter()
        _push_feedback(a, 0.9, domain=None)  # no domain
        result = a.worst_domain()
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_above_threshold
# ---------------------------------------------------------------------------

class TestScoreAboveThreshold:
    def test_empty_returns_empty(self):
        o = _make_optimizer()
        assert o.score_above_threshold() == []

    def test_all_below_threshold(self):
        o = _make_optimizer()
        for v in [0.2, 0.4, 0.6]:
            _push_opt(o, v)
        assert o.score_above_threshold(threshold=0.9) == []

    def test_all_above_threshold(self):
        o = _make_optimizer()
        for v in [0.8, 0.9]:
            _push_opt(o, v)
        result = o.score_above_threshold(threshold=0.7)
        assert len(result) == 2

    def test_mixed(self):
        o = _make_optimizer()
        for v in [0.3, 0.7, 0.9]:
            _push_opt(o, v)
        result = o.score_above_threshold(threshold=0.6)
        assert len(result) == 2

    def test_exclusive_threshold(self):
        o = _make_optimizer()
        _push_opt(o, 0.7)
        assert o.score_above_threshold(threshold=0.7) == []


# ---------------------------------------------------------------------------
# OntologyCritic.weakest_dimension
# ---------------------------------------------------------------------------

class TestWeakestDimension:
    def test_returns_lowest_dimension(self):
        critic = _make_critic()
        score = _make_score(completeness=0.1, consistency=0.9)
        assert critic.weakest_dimension(score) == "completeness"

    def test_granularity_is_weakest(self):
        critic = _make_critic()
        score = _make_score(granularity=0.05)
        assert critic.weakest_dimension(score) == "granularity"

    def test_all_equal_returns_a_dimension(self):
        critic = _make_critic()
        score = _make_score()  # all 0.5
        result = critic.weakest_dimension(score)
        assert result in {"completeness", "consistency", "clarity",
                          "granularity", "relationship_coherence", "domain_alignment"}

    def test_domain_alignment_weakest(self):
        critic = _make_critic()
        score = _make_score(domain_alignment=0.01)
        assert critic.weakest_dimension(score) == "domain_alignment"


# ---------------------------------------------------------------------------
# LogicValidator.node_degree_histogram
# ---------------------------------------------------------------------------

class TestNodeDegreeHistogram:
    def test_empty_returns_empty(self):
        v = _make_validator()
        assert v.node_degree_histogram({}) == {}

    def test_no_edges_all_degree_zero(self):
        v = _make_validator()
        ont = {"entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}], "relationships": []}
        hist = v.node_degree_histogram(ont)
        assert hist == {0: 3}

    def test_one_edge(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "A"}, {"id": "B"}],
            "relationships": [{"subject_id": "A", "object_id": "B"}],
        }
        hist = v.node_degree_histogram(ont)
        assert hist[1] == 1  # A has out-degree 1
        assert hist[0] == 1  # B has out-degree 0

    def test_hub_node(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}, {"id": "D"}],
            "relationships": [
                {"subject_id": "A", "object_id": "B"},
                {"subject_id": "A", "object_id": "C"},
                {"subject_id": "A", "object_id": "D"},
            ],
        }
        hist = v.node_degree_histogram(ont)
        assert hist[3] == 1  # A has degree 3
        assert hist[0] == 3  # B, C, D have degree 0
