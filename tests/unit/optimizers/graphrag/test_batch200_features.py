"""Batch-200 feature tests.

Methods under test:
  - OntologyOptimizer.score_below_threshold_rate(threshold)
  - OntologyOptimizer.history_plateau_count(tolerance)
  - OntologyOptimizer.history_run_last_improvement()
  - OntologyGenerator.entity_avg_id_length(result)
  - OntologyGenerator.relationship_isolated_ids(result)
  - OntologyPipeline.run_score_harmonic_mean()
  - OntologyLearningAdapter.feedback_plateau_length(tolerance)
  - OntologyMediator.action_count_total()
"""
import pytest
from unittest.mock import MagicMock


# ── helpers ──────────────────────────────────────────────────────────────────

class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg


def _push_opt(o, avg):
    o._history.append(_FakeEntry(avg))


def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


def _make_entity(eid, confidence=1.0):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="T", text=eid, confidence=confidence)


def _make_rel_mock(source_id, target_id):
    r = MagicMock()
    r.source_id = source_id
    r.target_id = target_id
    return r


def _make_result(entities=None, relationships=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities or [],
        relationships=relationships or [],
        confidence=1.0,
    )


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline()


def _push_run(p, score_val):
    run = MagicMock()
    run.score.overall = score_val
    p._run_history.append(run)


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(a, score):
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import FeedbackRecord
    a._feedback.append(FeedbackRecord(final_score=score))


def _make_mediator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
    return OntologyMediator(generator=MagicMock(), critic=MagicMock())


# ── OntologyOptimizer.score_below_threshold_rate ─────────────────────────────

class TestScoreBelowThresholdRate:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_below_threshold_rate() == pytest.approx(0.0)

    def test_all_above_returns_zero(self):
        o = _make_optimizer()
        for v in [0.6, 0.7, 0.8]:
            _push_opt(o, v)
        assert o.score_below_threshold_rate(threshold=0.5) == pytest.approx(0.0)

    def test_all_below_returns_one(self):
        o = _make_optimizer()
        for v in [0.1, 0.2, 0.3]:
            _push_opt(o, v)
        assert o.score_below_threshold_rate(threshold=0.5) == pytest.approx(1.0)

    def test_half_below(self):
        o = _make_optimizer()
        for v in [0.3, 0.7]:
            _push_opt(o, v)
        assert o.score_below_threshold_rate(threshold=0.5) == pytest.approx(0.5)

    def test_strict_boundary(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        # exactly at threshold: NOT below (strict <)
        assert o.score_below_threshold_rate(threshold=0.5) == pytest.approx(0.0)


# ── OntologyOptimizer.history_plateau_count ───────────────────────────────────

class TestHistoryPlateauCount:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_plateau_count() == 0

    def test_single_entry_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.history_plateau_count() == 0

    def test_no_plateau(self):
        o = _make_optimizer()
        for v in [0.1, 0.5, 0.9]:
            _push_opt(o, v)
        assert o.history_plateau_count(tolerance=0.01) == 0

    def test_single_plateau_pair(self):
        o = _make_optimizer()
        for v in [0.5, 0.5]:
            _push_opt(o, v)
        assert o.history_plateau_count(tolerance=0.01) == 1

    def test_all_plateau(self):
        o = _make_optimizer()
        for _ in range(5):
            _push_opt(o, 0.5)
        # 4 consecutive pairs all within tolerance
        assert o.history_plateau_count(tolerance=0.01) == 4


# ── OntologyOptimizer.history_run_last_improvement ───────────────────────────

class TestHistoryRunLastImprovement:
    def test_empty_returns_minus_one(self):
        o = _make_optimizer()
        assert o.history_run_last_improvement() == pytest.approx(-1.0)

    def test_single_entry_returns_minus_one(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.history_run_last_improvement() == pytest.approx(-1.0)

    def test_monotone_decreasing_returns_minus_one(self):
        o = _make_optimizer()
        for v in [0.9, 0.7, 0.5]:
            _push_opt(o, v)
        assert o.history_run_last_improvement() == pytest.approx(-1.0)

    def test_last_improved_at_index_two(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.7, 0.6, 0.5]:
            _push_opt(o, v)
        # last improvement is at index 2 (0.7 > 0.5)
        assert o.history_run_last_improvement() == pytest.approx(2.0)


# ── OntologyGenerator.entity_avg_id_length ────────────────────────────────────

class TestEntityAvgIdLength:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_avg_id_length(r) == pytest.approx(0.0)

    def test_single_entity(self):
        g = _make_generator()
        r = _make_result([_make_entity("hello")])
        assert g.entity_avg_id_length(r) == pytest.approx(5.0)

    def test_average_of_two(self):
        g = _make_generator()
        r = _make_result([_make_entity("ab"), _make_entity("abcd")])
        assert g.entity_avg_id_length(r) == pytest.approx(3.0)


# ── OntologyGenerator.relationship_isolated_ids ──────────────────────────────

class TestRelationshipIsolatedIds:
    def test_no_relationships_returns_empty(self):
        g = _make_generator()
        r = _make_result(relationships=[])
        assert g.relationship_isolated_ids(r) == set()

    def test_identifies_isolated_node(self):
        g = _make_generator()
        rels = [
            _make_rel_mock("a", "b"),
            _make_rel_mock("a", "c"),
        ]
        r = _make_result(relationships=rels)
        # b and c each appear once; a appears twice → isolated: {b, c}
        assert g.relationship_isolated_ids(r) == {"b", "c"}

    def test_all_connected_returns_empty(self):
        g = _make_generator()
        rels = [
            _make_rel_mock("a", "b"),
            _make_rel_mock("b", "a"),
        ]
        r = _make_result(relationships=rels)
        # each appears twice → none isolated
        assert g.relationship_isolated_ids(r) == set()


# ── OntologyPipeline.run_score_harmonic_mean ──────────────────────────────────

class TestRunScoreHarmonicMean:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_harmonic_mean() == pytest.approx(0.0)

    def test_zero_score_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.0)
        assert p.run_score_harmonic_mean() == pytest.approx(0.0)

    def test_uniform_scores(self):
        p = _make_pipeline()
        for _ in range(4):
            _push_run(p, 0.5)
        assert p.run_score_harmonic_mean() == pytest.approx(0.5)

    def test_known_harmonic_mean(self):
        p = _make_pipeline()
        _push_run(p, 1.0)
        _push_run(p, 2.0)
        # H = 2 / (1 + 0.5) = 4/3 ≈ 1.333...
        assert p.run_score_harmonic_mean() == pytest.approx(4.0 / 3.0)


# ── OntologyLearningAdapter.feedback_plateau_length ──────────────────────────

class TestFeedbackPlateauLength:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_plateau_length() == 0

    def test_single_record_returns_one(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_plateau_length() == 1

    def test_no_plateau_returns_one(self):
        a = _make_adapter()
        for v in [0.1, 0.5, 0.9]:
            _push_feedback(a, v)
        assert a.feedback_plateau_length(tolerance=0.01) == 1

    def test_all_same_returns_length(self):
        a = _make_adapter()
        for _ in range(5):
            _push_feedback(a, 0.5)
        assert a.feedback_plateau_length(tolerance=0.01) == 5

    def test_partial_plateau(self):
        a = _make_adapter()
        for v in [0.1, 0.5, 0.5, 0.5, 0.9]:
            _push_feedback(a, v)
        assert a.feedback_plateau_length(tolerance=0.01) == 3


# ── OntologyMediator.action_count_total ──────────────────────────────────────

class TestActionCountTotal:
    def test_empty_returns_zero(self):
        m = _make_mediator()
        assert m.action_count_total() == 0

    def test_single_action_type(self):
        m = _make_mediator()
        m._action_counts = {"refine": 7}
        assert m.action_count_total() == 7

    def test_multiple_action_types(self):
        m = _make_mediator()
        m._action_counts = {"a": 3, "b": 5, "c": 2}
        assert m.action_count_total() == 10
