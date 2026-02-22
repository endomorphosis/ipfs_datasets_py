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
    def test_empty_list_does_nothing(self):
        m = _make_mediator()
        called = []
        m.apply_feedback = lambda s: called.append(s)
        m.apply_feedback_list([])
        assert called == []

    def test_each_score_applied_in_order(self):
        m = _make_mediator()
        applied = []
        m.apply_feedback = lambda s: applied.append(s)
        scores = [_make_score(completeness=v) for v in [0.3, 0.6, 0.9]]
        m.apply_feedback_list(scores)
        assert len(applied) == 3
        assert [s.completeness for s in applied] == pytest.approx([0.3, 0.6, 0.9])

    def test_single_score_applied(self):
        m = _make_mediator()
        applied = []
        m.apply_feedback = lambda s: applied.append(s)
        m.apply_feedback_list([_make_score()])
        assert len(applied) == 1

    def test_returns_none(self):
        m = _make_mediator()
        m.apply_feedback = lambda s: None
        result = m.apply_feedback_list([_make_score()])
        assert result is None


# ---------------------------------------------------------------------------
# OntologyOptimizer.convergence_score
# ---------------------------------------------------------------------------

class TestConvergenceScore:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.convergence_score() == pytest.approx(0.0)

    def test_fewer_than_4_returns_zero(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.7]:
            _push_opt(o, v)
        assert o.convergence_score() == pytest.approx(0.0)

    def test_stable_end_returns_high(self):
        o = _make_optimizer()
        # first half varies, second half constant
        for v in [0.1, 0.9, 0.5, 0.5]:
            _push_opt(o, v)
        score = o.convergence_score()
        assert 0.0 <= score <= 1.0

    def test_constant_history_returns_one(self):
        o = _make_optimizer()
        for _ in range(6):
            _push_opt(o, 0.5)
        # std of both halves is 0; first_half std=0 → returns 1.0
        assert o.convergence_score() == pytest.approx(1.0)

    def test_clamped_between_zero_and_one(self):
        o = _make_optimizer()
        # diverging — second std > first std
        for v in [0.4, 0.6, 0.1, 0.9]:
            _push_opt(o, v)
        score = o.convergence_score()
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# LogicValidator.strongly_connected_components
# ---------------------------------------------------------------------------

class TestStronglyConnectedComponents:
    def test_empty_ontology_returns_empty(self):
        v = _make_validator()
        assert v.strongly_connected_components({}) == []

    def test_no_edges_each_node_is_own_scc(self):
        v = _make_validator()
        ont = {"entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}], "relationships": []}
        sccs = v.strongly_connected_components(ont)
        flat = sorted([n for scc in sccs for n in scc])
        assert flat == ["A", "B", "C"]
        assert all(len(s) == 1 for s in sccs)

    def test_cycle_forms_single_scc(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
            "relationships": [
                {"subject_id": "A", "object_id": "B"},
                {"subject_id": "B", "object_id": "C"},
                {"subject_id": "C", "object_id": "A"},
            ],
        }
        sccs = v.strongly_connected_components(ont)
        assert len(sccs) == 1
        assert sccs[0] == ["A", "B", "C"]

    def test_dag_all_singletons(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
            "relationships": [
                {"subject_id": "A", "object_id": "B"},
                {"subject_id": "B", "object_id": "C"},
            ],
        }
        sccs = v.strongly_connected_components(ont)
        assert all(len(s) == 1 for s in sccs)

    def test_partial_cycle(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}, {"id": "D"}],
            "relationships": [
                {"subject_id": "A", "object_id": "B"},
                {"subject_id": "B", "object_id": "A"},  # A↔B cycle
                {"subject_id": "B", "object_id": "C"},
                {"subject_id": "C", "object_id": "D"},
            ],
        }
        sccs = v.strongly_connected_components(ont)
        # A and B form an SCC; C, D are singletons
        scc_sizes = sorted([len(s) for s in sccs], reverse=True)
        assert scc_sizes[0] == 2
