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
    @pytest.mark.parametrize(
        "records,predicate",
        [
            ([], lambda value: value == ""),
            ([(0.5, "science")], lambda value: value == "science"),
            # law avg=0.8, medicine avg=0.25 -> worst is medicine
            ([(0.8, "law"), (0.2, "medicine"), (0.3, "medicine")], lambda value: value == "medicine"),
            ([(0.9, None)], lambda value: isinstance(value, str)),
        ],
    )
    def test_worst_domain_scenarios(self, records, predicate):
        a = _make_adapter()
        for score, domain in records:
            _push_feedback(a, score, domain=domain)
        assert predicate(a.worst_domain())


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_above_threshold
# ---------------------------------------------------------------------------

class TestScoreAboveThreshold:
    @pytest.mark.parametrize(
        "scores,threshold,expected_len",
        [
            ([], 0.7, 0),
            ([0.2, 0.4, 0.6], 0.9, 0),
            ([0.8, 0.9], 0.7, 2),
            ([0.3, 0.7, 0.9], 0.6, 2),
            ([0.7], 0.7, 0),
        ],
    )
    def test_score_above_threshold_scenarios(self, scores, threshold, expected_len):
        o = _make_optimizer()
        for v in scores:
            _push_opt(o, v)
        result = o.score_above_threshold(threshold=threshold)
        assert len(result) == expected_len


# ---------------------------------------------------------------------------
# OntologyCritic.weakest_dimension
# ---------------------------------------------------------------------------

class TestWeakestDimension:
    @pytest.mark.parametrize(
        "score,predicate",
        [
            (_make_score(completeness=0.1, consistency=0.9), lambda value: value == "completeness"),
            (_make_score(granularity=0.05), lambda value: value == "granularity"),
            (
                _make_score(),
                lambda value: value
                in {"completeness", "consistency", "clarity", "granularity", "relationship_coherence", "domain_alignment"},
            ),
            (_make_score(domain_alignment=0.01), lambda value: value == "domain_alignment"),
        ],
    )
    def test_weakest_dimension_scenarios(self, score, predicate):
        critic = _make_critic()
        assert predicate(critic.weakest_dimension(score))


# ---------------------------------------------------------------------------
# LogicValidator.node_degree_histogram
# ---------------------------------------------------------------------------

class TestNodeDegreeHistogram:
    @pytest.mark.parametrize(
        "ontology,predicate",
        [
            ({}, lambda hist: hist == {}),
            (
                {"entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}], "relationships": []},
                lambda hist: hist == {0: 3},
            ),
            (
                {"entities": [{"id": "A"}, {"id": "B"}], "relationships": [{"subject_id": "A", "object_id": "B"}]},
                lambda hist: hist[1] == 1 and hist[0] == 1,
            ),
            (
                {
                    "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}, {"id": "D"}],
                    "relationships": [
                        {"subject_id": "A", "object_id": "B"},
                        {"subject_id": "A", "object_id": "C"},
                        {"subject_id": "A", "object_id": "D"},
                    ],
                },
                lambda hist: hist[3] == 1 and hist[0] == 3,
            ),
        ],
    )
    def test_node_degree_histogram_scenarios(self, ontology, predicate):
        v = _make_validator()
        assert predicate(v.node_degree_histogram(ontology))
