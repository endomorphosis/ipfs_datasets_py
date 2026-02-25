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
    @pytest.mark.parametrize(
        "feedback_scores,n,expected_len,expected_top,predicate",
        [
            ([], 3, 0, None, None),
            ([0.2, 0.8, 0.5, 0.9], 2, 2, 0.9, None),
            ([0.3, 0.7, 0.5], 3, 3, 0.7, lambda scores: scores == sorted(scores, reverse=True)),
            ([0.1, 0.9, 0.4], 1, 1, 0.9, None),
            ([0.3, 0.6], 10, 2, 0.6, None),
        ],
    )
    def test_best_n_feedback_scenarios(self, feedback_scores, n, expected_len, expected_top, predicate):
        a = _make_adapter()
        for v in feedback_scores:
            _push_feedback(a, v)
        result = a.best_n_feedback(n)
        assert len(result) == expected_len
        if expected_top is not None and result:
            assert result[0].final_score == pytest.approx(expected_top)
        if predicate is not None:
            scores = [r.final_score for r in result]
            assert predicate(scores)


class TestPipelineScoreRange:
    @pytest.mark.parametrize(
        "scores,expected",
        [
            ([], 0.0),
            ([0.5], 0.0),
            ([0.2, 0.8, 0.5], 0.6),
            ([0.7, 0.7, 0.7, 0.7], 0.0),
        ],
    )
    def test_pipeline_score_range_scenarios(self, scores, expected):
        p = _make_pipeline()
        for v in scores:
            _push_run(p, v)
        assert p.pipeline_score_range() == pytest.approx(expected)


class TestWeaklyConnectedComponents:
    @pytest.mark.parametrize(
        "ontology,predicate",
        [
            ({}, lambda wccs: wccs == []),
            (
                {"entities": [{"id": "A"}, {"id": "B"}], "relationships": []},
                lambda wccs: sorted([n for wcc in wccs for n in wcc]) == ["A", "B"] and all(len(w) == 1 for w in wccs),
            ),
            (
                {
                    "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
                    "relationships": [{"subject_id": "A", "object_id": "B"}, {"subject_id": "B", "object_id": "C"}],
                },
                lambda wccs: len(wccs) == 1 and wccs[0] == ["A", "B", "C"],
            ),
            (
                {
                    "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}, {"id": "D"}],
                    "relationships": [{"subject_id": "A", "object_id": "B"}, {"subject_id": "C", "object_id": "D"}],
                },
                lambda wccs: len(wccs) == 2,
            ),
            (
                {"entities": [{"id": "A"}, {"id": "B"}], "relationships": [{"subject_id": "B", "object_id": "A"}]},
                lambda wccs: len(wccs) == 1,
            ),
        ],
    )
    def test_weakly_connected_components_scenarios(self, ontology, predicate):
        v = _make_validator()
        assert predicate(v.weakly_connected_components(ontology))


class TestHistoryEntropy:
    @pytest.mark.parametrize(
        "scores,predicate",
        [
            ([], lambda entropy: entropy == pytest.approx(0.0)),
            ([0.5, 0.5, 0.5, 0.5], lambda entropy: entropy == pytest.approx(0.0)),
            ([(i + 0.5) / 10.0 for i in range(10)], lambda entropy: entropy > 0.0),
            ([0.1, 0.5, 0.9], lambda entropy: entropy >= 0.0),
        ],
    )
    def test_history_entropy_scenarios(self, scores, predicate):
        o = _make_optimizer()
        for v in scores:
            _push_opt(o, v)
        assert predicate(o.history_entropy())
