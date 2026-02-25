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
    @pytest.mark.parametrize(
        "scores,predicate",
        [
            ([], lambda result: result == pytest.approx(0.0)),
            ([0.8], lambda result: 0.0 < result <= 1.0),
            ([0.5, 0.5, 0.5, 0.5], lambda result: result == pytest.approx(1.0)),
            ([0.0, 0.0, 0.0], lambda result: result == pytest.approx(0.0)),
        ],
    )
    def test_history_stability_scenarios(self, scores, predicate):
        o = _make_optimizer()
        for v in scores:
            _push_opt(o, v)
        assert predicate(o.history_stability())

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
    @pytest.mark.parametrize(
        "scores,predicate",
        [
            ([], lambda value: value == pytest.approx(0.0)),
            ([0.3, 0.5, 0.7], lambda value: value == pytest.approx(0.0)),
            ([0.5, 0.5, 0.5, 0.5, 0.5], lambda value: value == pytest.approx(0.0)),
            ([0.1, 0.3, 0.5, 0.7, 0.9], lambda value: isinstance(value, float)),
            ([0.2, 0.4, 0.6, 0.8], lambda value: isinstance(value, float)),
        ],
    )
    def test_feedback_kurtosis_scenarios(self, scores, predicate):
        a = _make_adapter()
        for v in scores:
            _push_feedback(a, v)
        assert predicate(a.feedback_kurtosis())


# ---------------------------------------------------------------------------
# OntologyCritic.critic_dimension_rank
# ---------------------------------------------------------------------------

class TestCriticDimensionRank:
    @pytest.mark.parametrize(
        "score,predicate",
        [
            (_make_score(), lambda rank: len(rank) == 6),
            (_make_score(completeness=0.1, consistency=0.9), lambda rank: rank[0] == "completeness"),
            (_make_score(domain_alignment=0.95), lambda rank: rank[-1] == "domain_alignment"),
            (
                _make_score(),
                lambda rank: set(rank) == {
                    "completeness",
                    "consistency",
                    "clarity",
                    "granularity",
                    "relationship_coherence",
                    "domain_alignment",
                },
            ),
        ],
    )
    def test_critic_dimension_rank_scenarios(self, score, predicate):
        critic = _make_critic()
        rank = critic.critic_dimension_rank(score)
        assert predicate(rank)

    def test_critic_dimension_rank_is_ascending(self):
        critic = _make_critic()
        score = _make_score(
            completeness=0.1,
            consistency=0.3,
            clarity=0.5,
            granularity=0.7,
            relationship_coherence=0.8,
            domain_alignment=0.9,
        )
        rank = critic.critic_dimension_rank(score)
        values = [getattr(score, d) for d in rank]
        assert values == sorted(values)


# ---------------------------------------------------------------------------
# LogicValidator.relationship_type_distribution
# ---------------------------------------------------------------------------

class TestRelationshipTypeDistribution:
    @pytest.mark.parametrize(
        "ontology,predicate",
        [
            ({}, lambda dist: dist == {}),
            ({"relationships": []}, lambda dist: dist == {}),
            (
                {"relationships": [{"type": "IS_A"}, {"type": "IS_A"}, {"type": "PART_OF"}]},
                lambda dist: dist["IS_A"] == 2 and dist["PART_OF"] == 1,
            ),
            (
                {"relationships": [{"subject_id": "A", "object_id": "B"}]},
                lambda dist: dist.get("unknown", 0) == 1,
            ),
            (
                {"relationships": [{"type": "X"}, {"type": "Y"}, {"type": "X"}]},
                lambda dist: sum(dist.values()) == 3,
            ),
        ],
    )
    def test_relationship_type_distribution_scenarios(self, ontology, predicate):
        v = _make_validator()
        assert predicate(v.relationship_type_distribution(ontology))
