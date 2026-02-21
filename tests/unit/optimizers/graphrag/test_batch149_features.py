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
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_mode() == pytest.approx(0.0)

    def test_single_entry_bin_midpoint(self):
        o = _make_optimizer()
        _push_opt(o, 0.55)  # bin 5 → midpoint 0.55
        result = o.history_mode()
        assert 0.0 < result <= 1.0

    def test_concentration_in_one_bin(self):
        o = _make_optimizer()
        for _ in range(5):
            _push_opt(o, 0.75)  # all in bin 7 → midpoint 0.75
        for _ in range(1):
            _push_opt(o, 0.1)   # bin 1
        result = o.history_mode()
        assert result == pytest.approx(0.75)

    def test_returns_float_in_zero_one(self):
        o = _make_optimizer()
        for v in [0.2, 0.5, 0.8]:
            _push_opt(o, v)
        assert 0.0 <= o.history_mode() <= 1.0


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_above_mean
# ---------------------------------------------------------------------------

class TestFeedbackAboveMean:
    def test_empty_returns_empty(self):
        a = _make_adapter()
        assert a.feedback_above_mean() == []

    def test_single_returns_all(self):
        a = _make_adapter()
        _push_feedback(a, 0.7)
        result = a.feedback_above_mean()
        assert len(result) == 1

    def test_above_mean_count_correct(self):
        a = _make_adapter()
        for v in [0.2, 0.4, 0.6, 0.8]:
            _push_feedback(a, v)
        # mean = 0.5; above: 0.6, 0.8
        result = a.feedback_above_mean()
        assert len(result) == 2
        assert all(r.final_score > 0.5 for r in result)

    def test_all_equal_returns_empty(self):
        a = _make_adapter()
        for _ in range(4):
            _push_feedback(a, 0.5)
        result = a.feedback_above_mean()
        assert result == []


# ---------------------------------------------------------------------------
# OntologyPipeline.score_at_percentile
# ---------------------------------------------------------------------------

class TestScoreAtPercentile:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.score_at_percentile(50) == pytest.approx(0.0)

    def test_0th_percentile_is_min(self):
        p = _make_pipeline()
        for v in [0.3, 0.7, 0.5]:
            _push_run(p, v)
        assert p.score_at_percentile(0) == pytest.approx(0.3)

    def test_100th_percentile_is_max(self):
        p = _make_pipeline()
        for v in [0.3, 0.7, 0.5]:
            _push_run(p, v)
        assert p.score_at_percentile(100) == pytest.approx(0.7)

    def test_50th_percentile_of_sorted(self):
        p = _make_pipeline()
        for v in [0.2, 0.4, 0.6, 0.8]:
            _push_run(p, v)
        result = p.score_at_percentile(50)
        assert 0.4 <= result <= 0.6

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
    def test_empty_returns_zero(self):
        v = _make_validator()
        assert v.entity_density({}) == pytest.approx(0.0)

    def test_no_relationships(self):
        v = _make_validator()
        ont = {"entities": [{"id": "A"}, {"id": "B"}], "relationships": []}
        assert v.entity_density(ont) == pytest.approx(0.0)

    def test_equal_entities_and_relationships(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "A"}, {"id": "B"}],
            "relationships": [{"subject_id": "A", "object_id": "B"},
                              {"subject_id": "B", "object_id": "A"}],
        }
        assert v.entity_density(ont) == pytest.approx(1.0)

    def test_more_relationships_than_entities(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "A"}],
            "relationships": [{"subject_id": "A", "object_id": "A"},
                              {"subject_id": "A", "object_id": "A"}],
        }
        assert v.entity_density(ont) == pytest.approx(2.0)
