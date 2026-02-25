"""Batch-146 feature tests.

Methods under test:
  - OntologyMediator.apply_feedback_list(scores)
  - OntologyOptimizer.convergence_score()
  - LogicValidator.strongly_connected_components(ontology)
"""
import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_score(**kwargs):
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
    defaults = dict(
        completeness=0.5, consistency=0.5, clarity=0.5,
        granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5,
    )
    defaults.update(kwargs)
    return CriticScore(**defaults)


def _make_mediator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
    gen = MagicMock()
    critic = MagicMock()
    m = OntologyMediator(gen, critic)
    m._action_counts = {}
    return m


def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg
        self.trend = "stable"


def _push_opt(o, avg):
    o._history.append(_FakeEntry(avg))


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


# ---------------------------------------------------------------------------
# OntologyMediator.apply_feedback_list
# ---------------------------------------------------------------------------

class TestApplyFeedbackList:
    @pytest.mark.parametrize(
        "completeness_values,expected",
        [
            ([], []),
            ([0.3, 0.6, 0.9], [0.3, 0.6, 0.9]),
            ([0.5], [0.5]),
        ],
    )
    def test_apply_feedback_list_scenarios(self, completeness_values, expected):
        m = _make_mediator()
        applied = []
        m.apply_feedback = lambda s: applied.append(s)
        scores = [_make_score(completeness=v) for v in completeness_values]
        m.apply_feedback_list(scores)
        assert [s.completeness for s in applied] == pytest.approx(expected)

    def test_returns_none(self):
        m = _make_mediator()
        m.apply_feedback = lambda s: None
        result = m.apply_feedback_list([_make_score()])
        assert result is None


# ---------------------------------------------------------------------------
# OntologyOptimizer.convergence_score
# ---------------------------------------------------------------------------

class TestConvergenceScore:
    @pytest.mark.parametrize(
        "history,predicate",
        [
            ([], lambda score: score == pytest.approx(0.0)),
            ([0.3, 0.5, 0.7], lambda score: score == pytest.approx(0.0)),
            # first half varies, second half constant
            ([0.1, 0.9, 0.5, 0.5], lambda score: 0.0 <= score <= 1.0),
            # std of both halves is 0; first_half std=0 -> returns 1.0
            ([0.5, 0.5, 0.5, 0.5, 0.5, 0.5], lambda score: score == pytest.approx(1.0)),
            # diverging: second std > first std
            ([0.4, 0.6, 0.1, 0.9], lambda score: 0.0 <= score <= 1.0),
        ],
    )
    def test_convergence_score_scenarios(self, history, predicate):
        o = _make_optimizer()
        for v in history:
            _push_opt(o, v)
        assert predicate(o.convergence_score())


# ---------------------------------------------------------------------------
# LogicValidator.strongly_connected_components
# ---------------------------------------------------------------------------

class TestStronglyConnectedComponents:
    @pytest.mark.parametrize(
        "ontology,predicate",
        [
            ({}, lambda sccs: sccs == []),
            (
                {"entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}], "relationships": []},
                lambda sccs: sorted([n for scc in sccs for n in scc]) == ["A", "B", "C"] and all(len(s) == 1 for s in sccs),
            ),
            (
                {
                    "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
                    "relationships": [
                        {"subject_id": "A", "object_id": "B"},
                        {"subject_id": "B", "object_id": "C"},
                        {"subject_id": "C", "object_id": "A"},
                    ],
                },
                lambda sccs: len(sccs) == 1 and sccs[0] == ["A", "B", "C"],
            ),
            (
                {
                    "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
                    "relationships": [{"subject_id": "A", "object_id": "B"}, {"subject_id": "B", "object_id": "C"}],
                },
                lambda sccs: all(len(s) == 1 for s in sccs),
            ),
            (
                {
                    "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}, {"id": "D"}],
                    "relationships": [
                        {"subject_id": "A", "object_id": "B"},
                        {"subject_id": "B", "object_id": "A"},
                        {"subject_id": "B", "object_id": "C"},
                        {"subject_id": "C", "object_id": "D"},
                    ],
                },
                lambda sccs: sorted([len(s) for s in sccs], reverse=True)[0] == 2,
            ),
        ],
    )
    def test_strongly_connected_components_scenarios(self, ontology, predicate):
        v = _make_validator()
        assert predicate(v.strongly_connected_components(ontology))
