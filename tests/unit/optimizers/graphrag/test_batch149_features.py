"""Batch-149 feature tests.

Methods under test:
  - OntologyOptimizer.history_mode()
  - OntologyLearningAdapter.feedback_above_mean()
  - OntologyPipeline.score_at_percentile(p)
  - LogicValidator.entity_density(ontology)
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


# ---------------------------------------------------------------------------
# OntologyOptimizer.history_mode
# ---------------------------------------------------------------------------

class TestHistoryMode:
    @pytest.mark.parametrize(
        "scores,predicate",
        [
            ([], lambda value: value == pytest.approx(0.0)),
            ([0.55], lambda value: 0.0 < value <= 1.0),
            ([0.75, 0.75, 0.75, 0.75, 0.75, 0.1], lambda value: value == pytest.approx(0.75)),
            ([0.2, 0.5, 0.8], lambda value: 0.0 <= value <= 1.0),
        ],
    )
    def test_history_mode_scenarios(self, scores, predicate):
        o = _make_optimizer()
        for v in scores:
            _push_opt(o, v)
        assert predicate(o.history_mode())


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_above_mean
# ---------------------------------------------------------------------------

class TestFeedbackAboveMean:
    @pytest.mark.parametrize(
        "scores,expected_len,predicate",
        [
            ([], 0, None),
            ([0.7], 1, None),
            # mean=0.5; above: 0.6, 0.8
            ([0.2, 0.4, 0.6, 0.8], 2, lambda result: all(r.final_score > 0.5 for r in result)),
            ([0.5, 0.5, 0.5, 0.5], 0, None),
        ],
    )
    def test_feedback_above_mean_scenarios(self, scores, expected_len, predicate):
        a = _make_adapter()
        for v in scores:
            _push_feedback(a, v)
        result = a.feedback_above_mean()
        assert len(result) == expected_len
        if predicate is not None:
            assert predicate(result)


# ---------------------------------------------------------------------------
# OntologyPipeline.score_at_percentile
# ---------------------------------------------------------------------------

class TestScoreAtPercentile:
    @pytest.mark.parametrize(
        "scores,percentile,predicate",
        [
            ([], 50, lambda value: value == pytest.approx(0.0)),
            ([0.3, 0.7, 0.5], 0, lambda value: value == pytest.approx(0.3)),
            ([0.3, 0.7, 0.5], 100, lambda value: value == pytest.approx(0.7)),
            ([0.2, 0.4, 0.6, 0.8], 50, lambda value: 0.4 <= value <= 0.6),
        ],
    )
    def test_score_at_percentile_scenarios(self, scores, percentile, predicate):
        p = _make_pipeline()
        for v in scores:
            _push_run(p, v)
        assert predicate(p.score_at_percentile(percentile))

    def test_invalid_percentile_raises(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        with pytest.raises(ValueError):
            p.score_at_percentile(101)
        with pytest.raises(ValueError):
            p.score_at_percentile(-1)


# ---------------------------------------------------------------------------
# LogicValidator.entity_density
# ---------------------------------------------------------------------------

class TestEntityDensity:
    @pytest.mark.parametrize(
        "ontology,expected",
        [
            ({}, 0.0),
            ({"entities": [{"id": "A"}, {"id": "B"}], "relationships": []}, 0.0),
            (
                {
                    "entities": [{"id": "A"}, {"id": "B"}],
                    "relationships": [{"subject_id": "A", "object_id": "B"}, {"subject_id": "B", "object_id": "A"}],
                },
                1.0,
            ),
            (
                {
                    "entities": [{"id": "A"}],
                    "relationships": [{"subject_id": "A", "object_id": "A"}, {"subject_id": "A", "object_id": "A"}],
                },
                2.0,
            ),
        ],
    )
    def test_entity_density_scenarios(self, ontology, expected):
        v = _make_validator()
        assert v.entity_density(ontology) == pytest.approx(expected)
