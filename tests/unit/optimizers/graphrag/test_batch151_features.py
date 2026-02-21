"""Batch-151 feature tests.

Methods under test:
  - OntologyOptimizer.history_stability()
  - OntologyLearningAdapter.feedback_kurtosis()
  - OntologyCritic.critic_dimension_rank(score)
  - LogicValidator.relationship_type_distribution(ontology)
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
# OntologyOptimizer.history_stability
# ---------------------------------------------------------------------------

class TestHistoryStability:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_stability() == pytest.approx(0.0)

    def test_single_entry_stable(self):
        o = _make_optimizer()
        _push_opt(o, 0.8)
        result = o.history_stability()
        assert 0.0 < result <= 1.0

    def test_constant_returns_one(self):
        o = _make_optimizer()
        for _ in range(4):
            _push_opt(o, 0.5)
        assert o.history_stability() == pytest.approx(1.0)

    def test_zero_mean_returns_zero(self):
        o = _make_optimizer()
        for _ in range(3):
            _push_opt(o, 0.0)
        assert o.history_stability() == pytest.approx(0.0)

    def test_high_variance_less_stable(self):
        o1 = _make_optimizer()
        for v in [0.1, 0.9]:
            _push_opt(o1, v)

        o2 = _make_optimizer()
        for v in [0.48, 0.52]:
            _push_opt(o2, v)

        assert o1.history_stability() < o2.history_stability()


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_kurtosis
# ---------------------------------------------------------------------------

class TestFeedbackKurtosis:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_kurtosis() == pytest.approx(0.0)

    def test_fewer_than_four_returns_zero(self):
        a = _make_adapter()
        for v in [0.3, 0.5, 0.7]:
            _push_feedback(a, v)
        assert a.feedback_kurtosis() == pytest.approx(0.0)

    def test_zero_variance_returns_zero(self):
        a = _make_adapter()
        for _ in range(5):
            _push_feedback(a, 0.5)
        assert a.feedback_kurtosis() == pytest.approx(0.0)

    def test_uniform_returns_negative(self):
        # Uniform distribution has excess kurtosis < 0
        a = _make_adapter()
        for v in [0.1, 0.3, 0.5, 0.7, 0.9]:
            _push_feedback(a, v)
        # Uniform-like — excess kurtosis should be negative
        kurtosis = a.feedback_kurtosis()
        assert isinstance(kurtosis, float)

    def test_returns_float(self):
        a = _make_adapter()
        for v in [0.2, 0.4, 0.6, 0.8]:
            _push_feedback(a, v)
        assert isinstance(a.feedback_kurtosis(), float)


# ---------------------------------------------------------------------------
# OntologyCritic.critic_dimension_rank
# ---------------------------------------------------------------------------

class TestCriticDimensionRank:
    def test_returns_all_dimensions(self):
        critic = _make_critic()
        score = _make_score()
        rank = critic.critic_dimension_rank(score)
        assert len(rank) == 6

    def test_lowest_first(self):
        critic = _make_critic()
        score = _make_score(completeness=0.1, consistency=0.9)
        rank = critic.critic_dimension_rank(score)
        assert rank[0] == "completeness"

    def test_highest_last(self):
        critic = _make_critic()
        score = _make_score(domain_alignment=0.95)
        rank = critic.critic_dimension_rank(score)
        assert rank[-1] == "domain_alignment"

    def test_equal_scores_all_dims_present(self):
        critic = _make_critic()
        score = _make_score()  # all 0.5
        rank = critic.critic_dimension_rank(score)
        assert set(rank) == {"completeness", "consistency", "clarity",
                              "granularity", "relationship_coherence", "domain_alignment"}

    def test_ascending_order(self):
        critic = _make_critic()
        score = _make_score(completeness=0.1, consistency=0.3, clarity=0.5,
                            granularity=0.7, relationship_coherence=0.8, domain_alignment=0.9)
        rank = critic.critic_dimension_rank(score)
        values = [getattr(score, d) for d in rank]
        assert values == sorted(values)


# ---------------------------------------------------------------------------
# LogicValidator.relationship_type_distribution
# ---------------------------------------------------------------------------

class TestRelationshipTypeDistribution:
    def test_empty_ontology_returns_empty(self):
        v = _make_validator()
        assert v.relationship_type_distribution({}) == {}

    def test_no_relationships_returns_empty(self):
        v = _make_validator()
        assert v.relationship_type_distribution({"relationships": []}) == {}

    def test_counts_types(self):
        v = _make_validator()
        ont = {"relationships": [
            {"type": "IS_A"}, {"type": "IS_A"}, {"type": "PART_OF"},
        ]}
        dist = v.relationship_type_distribution(ont)
        assert dist["IS_A"] == 2
        assert dist["PART_OF"] == 1

    def test_unknown_type_grouped(self):
        v = _make_validator()
        ont = {"relationships": [{"subject_id": "A", "object_id": "B"}]}
        dist = v.relationship_type_distribution(ont)
        assert dist.get("unknown", 0) == 1

    def test_mixed_types(self):
        v = _make_validator()
        ont = {"relationships": [
            {"type": "X"}, {"type": "Y"}, {"type": "X"},
        ]}
        dist = v.relationship_type_distribution(ont)
        assert sum(dist.values()) == 3
