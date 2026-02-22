"""Batch-199 feature tests.

Methods under test:
  - OntologyOptimizer.score_interquartile_mean()
  - OntologyOptimizer.score_bimodality_coefficient()
  - OntologyGenerator.entity_confidence_histogram(result, bins)
  - LogicValidator.orphan_nodes(ontology)
  - OntologyPipeline.run_score_geometric_mean()
  - OntologyLearningAdapter.feedback_mode()
  - OntologyMediator.action_top_n(n)
"""
import math
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


def _make_result(entities=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities or [],
        relationships=[],
        confidence=1.0,
    )


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


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


# ── OntologyOptimizer.score_interquartile_mean ────────────────────────────────

class TestScoreInterquartileMean:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_interquartile_mean() == pytest.approx(0.0)

    def test_fewer_than_four_returns_zero(self):
        o = _make_optimizer()
        for v in [0.3, 0.7]:
            _push_opt(o, v)
        assert o.score_interquartile_mean() == pytest.approx(0.0)

    def test_returns_float(self):
        o = _make_optimizer()
        for v in [0.1, 0.3, 0.5, 0.7, 0.9]:
            _push_opt(o, v)
        result = o.score_interquartile_mean()
        assert isinstance(result, float)
        assert 0.0 <= result <= 1.0

    def test_uniform_scores(self):
        o = _make_optimizer()
        for _ in range(6):
            _push_opt(o, 0.5)
        assert o.score_interquartile_mean() == pytest.approx(0.5)


# ── OntologyOptimizer.score_bimodality_coefficient ───────────────────────────

class TestScoreBimodalityCoefficient:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_bimodality_coefficient() == pytest.approx(0.0)

    def test_uniform_returns_zero(self):
        o = _make_optimizer()
        for _ in range(5):
            _push_opt(o, 0.5)
        assert o.score_bimodality_coefficient() == pytest.approx(0.0)

    def test_returns_value_in_unit_interval(self):
        o = _make_optimizer()
        for v in [0.1, 0.3, 0.5, 0.7, 0.9]:
            _push_opt(o, v)
        bc = o.score_bimodality_coefficient()
        assert 0.0 <= bc <= 1.0


# ── OntologyGenerator.entity_confidence_histogram ────────────────────────────

class TestEntityConfidenceHistogram:
    def test_no_entities_returns_empty_list(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_confidence_histogram(r) == []

    def test_bins_count_matches(self):
        g = _make_generator()
        r = _make_result([_make_entity("a", 0.5)])
        hist = g.entity_confidence_histogram(r, bins=5)
        assert len(hist) == 5
        assert sum(hist) == 1

    def test_confidence_zero_goes_to_first_bin(self):
        g = _make_generator()
        r = _make_result([_make_entity("a", 0.0)])
        hist = g.entity_confidence_histogram(r, bins=5)
        assert hist[0] == 1
        assert sum(hist[1:]) == 0

    def test_confidence_one_goes_to_last_bin(self):
        g = _make_generator()
        r = _make_result([_make_entity("a", 1.0)])
        hist = g.entity_confidence_histogram(r, bins=5)
        assert hist[-1] == 1

    def test_distribution_correct(self):
        g = _make_generator()
        # 0.0→bin0, 0.2→bin1, 0.4→bin2, 0.6→bin3, 0.8→bin4
        entities = [_make_entity(f"e{i}", v) for i, v in enumerate([0.0, 0.2, 0.4, 0.6, 0.8])]
        r = _make_result(entities)
        hist = g.entity_confidence_histogram(r, bins=5)
        assert sum(hist) == 5
        assert all(c == 1 for c in hist)


# ── LogicValidator.orphan_nodes ───────────────────────────────────────────────

class TestOrphanNodes:
    def test_empty_returns_empty(self):
        v = _make_validator()
        assert v.orphan_nodes({}) == []

    def test_no_relationships_all_orphans(self):
        v = _make_validator()
        onto = {"entities": [{"id": "a"}, {"id": "b"}]}
        result = v.orphan_nodes(onto)
        assert result == ["a", "b"]

    def test_connected_node_not_orphan(self):
        v = _make_validator()
        onto = {
            "entities": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            "relationships": [{"source": "a", "target": "b"}],
        }
        result = v.orphan_nodes(onto)
        assert result == ["c"]

    def test_returns_sorted(self):
        v = _make_validator()
        onto = {
            "entities": [{"id": "z"}, {"id": "m"}, {"id": "a"}],
            "relationships": [],
        }
        result = v.orphan_nodes(onto)
        assert result == ["a", "m", "z"]


# ── OntologyPipeline.run_score_geometric_mean ─────────────────────────────────

class TestRunScoreGeometricMean:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_geometric_mean() == pytest.approx(0.0)

    def test_zero_score_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.0)
        assert p.run_score_geometric_mean() == pytest.approx(0.0)

    def test_uniform_scores(self):
        p = _make_pipeline()
        for _ in range(4):
            _push_run(p, 0.5)
        assert p.run_score_geometric_mean() == pytest.approx(0.5)

    def test_geometric_mean_correct(self):
        p = _make_pipeline()
        for v in [0.25, 1.0]:
            _push_run(p, v)
        # geo mean = sqrt(0.25 * 1.0) = 0.5
        assert p.run_score_geometric_mean() == pytest.approx(0.5)


# ── OntologyLearningAdapter.feedback_mode ─────────────────────────────────────

class TestFeedbackMode:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_mode() == pytest.approx(0.0)

    def test_single_record(self):
        a = _make_adapter()
        _push_feedback(a, 0.7)
        assert a.feedback_mode() == pytest.approx(0.7)

    def test_returns_most_common(self):
        a = _make_adapter()
        for v in [0.5, 0.5, 0.5, 0.8, 0.8]:
            _push_feedback(a, v)
        assert a.feedback_mode() == pytest.approx(0.5)


# ── OntologyMediator.action_top_n ─────────────────────────────────────────────

class TestActionTopN:
    def test_empty_returns_empty(self):
        m = _make_mediator()
        assert m.action_top_n(3) == []

    def test_fewer_than_n_returns_all(self):
        m = _make_mediator()
        m._action_counts = {"a": 5, "b": 3}
        result = m.action_top_n(5)
        assert len(result) == 2

    def test_returns_top_n_descending(self):
        m = _make_mediator()
        m._action_counts = {"a": 5, "b": 3, "c": 8, "d": 1}
        result = m.action_top_n(2)
        assert len(result) == 2
        assert result[0] == ("c", 8)
        assert result[1] == ("a", 5)

    def test_default_n_is_3(self):
        m = _make_mediator()
        m._action_counts = {"a": 5, "b": 4, "c": 3, "d": 2, "e": 1}
        result = m.action_top_n()
        assert len(result) == 3
