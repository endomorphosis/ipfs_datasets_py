"""Batch-148 feature tests.

Methods under test:
  - OntologyLearningAdapter.best_n_feedback(n)
  - OntologyPipeline.pipeline_score_range()
  - LogicValidator.weakly_connected_components(ontology)
  - OntologyOptimizer.history_entropy()
"""
import pytest
from unittest.mock import MagicMock


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(a, score):
    r = MagicMock()
    r.final_score = score
    a._feedback.append(r)


def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline()


def _push_run(p, overall):
    score = MagicMock()
    score.overall = overall
    run = MagicMock()
    run.score = score
    p._run_history.append(run)


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg
        self.trend = "stable"


def _push_opt(o, avg):
    o._history.append(_FakeEntry(avg))


class TestBestNFeedback:
    def test_empty_returns_empty(self):
        a = _make_adapter()
        assert a.best_n_feedback(3) == []

    def test_returns_at_most_n(self):
        a = _make_adapter()
        for v in [0.2, 0.8, 0.5, 0.9]:
            _push_feedback(a, v)
        result = a.best_n_feedback(2)
        assert len(result) == 2

    def test_sorted_descending(self):
        a = _make_adapter()
        for v in [0.3, 0.7, 0.5]:
            _push_feedback(a, v)
        result = a.best_n_feedback(3)
        scores = [r.final_score for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_top_is_highest(self):
        a = _make_adapter()
        for v in [0.1, 0.9, 0.4]:
            _push_feedback(a, v)
        best = a.best_n_feedback(1)
        assert len(best) == 1
        assert best[0].final_score == pytest.approx(0.9)

    def test_n_larger_than_records(self):
        a = _make_adapter()
        for v in [0.3, 0.6]:
            _push_feedback(a, v)
        result = a.best_n_feedback(10)
        assert len(result) == 2


class TestPipelineScoreRange:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.pipeline_score_range() == pytest.approx(0.0)

    def test_single_run_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.pipeline_score_range() == pytest.approx(0.0)

    def test_known_range(self):
        p = _make_pipeline()
        for v in [0.2, 0.8, 0.5]:
            _push_run(p, v)
        assert p.pipeline_score_range() == pytest.approx(0.6)

    def test_identical_scores_returns_zero(self):
        p = _make_pipeline()
        for _ in range(4):
            _push_run(p, 0.7)
        assert p.pipeline_score_range() == pytest.approx(0.0)


class TestWeaklyConnectedComponents:
    def test_empty_returns_empty(self):
        v = _make_validator()
        assert v.weakly_connected_components({}) == []

    def test_no_edges_each_is_singleton(self):
        v = _make_validator()
        ont = {"entities": [{"id": "A"}, {"id": "B"}], "relationships": []}
        wccs = v.weakly_connected_components(ont)
        assert sorted([n for wcc in wccs for n in wcc]) == ["A", "B"]
        assert all(len(w) == 1 for w in wccs)

    def test_connected_graph_single_wcc(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
            "relationships": [
                {"subject_id": "A", "object_id": "B"},
                {"subject_id": "B", "object_id": "C"},
            ],
        }
        wccs = v.weakly_connected_components(ont)
        assert len(wccs) == 1
        assert wccs[0] == ["A", "B", "C"]

    def test_two_components(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}, {"id": "D"}],
            "relationships": [
                {"subject_id": "A", "object_id": "B"},
                {"subject_id": "C", "object_id": "D"},
            ],
        }
        wccs = v.weakly_connected_components(ont)
        assert len(wccs) == 2

    def test_undirected_treatment(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "A"}, {"id": "B"}],
            "relationships": [{"subject_id": "B", "object_id": "A"}],
        }
        wccs = v.weakly_connected_components(ont)
        assert len(wccs) == 1


class TestHistoryEntropy:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_entropy() == pytest.approx(0.0)

    def test_single_bin_returns_zero(self):
        o = _make_optimizer()
        for _ in range(4):
            _push_opt(o, 0.5)
        assert o.history_entropy() == pytest.approx(0.0)

    def test_uniform_distribution_has_positive_entropy(self):
        o = _make_optimizer()
        for i in range(10):
            _push_opt(o, (i + 0.5) / 10.0)
        assert o.history_entropy() > 0.0

    def test_returns_non_negative(self):
        o = _make_optimizer()
        for v in [0.1, 0.5, 0.9]:
            _push_opt(o, v)
        assert o.history_entropy() >= 0.0
