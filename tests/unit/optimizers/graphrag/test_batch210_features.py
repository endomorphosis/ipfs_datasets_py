"""Batch-210 feature tests.

Methods under test:
  - OntologyOptimizer.score_half_life_estimate()
  - OntologyOptimizer.history_increasing_fraction()
  - OntologyGenerator.entity_confidence_cv(result)
  - OntologyGenerator.relationship_unique_endpoints(result)
  - LogicValidator.density_comparison(ontology)
  - OntologyPipeline.run_best_to_current_ratio()
  - OntologyLearningAdapter.feedback_half_above_threshold(threshold)
  - OntologyMediator.action_peak_fraction()
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


def _make_rel_mock(source_id="src", target_id="tgt"):
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


# ── OntologyOptimizer.score_half_life_estimate ───────────────────────────────

class TestScoreHalfLifeEstimate:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_half_life_estimate() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.score_half_life_estimate() == pytest.approx(0.0)

    def test_declining_returns_inf(self):
        o = _make_optimizer()
        for v in [0.9, 0.7, 0.5]:
            _push_opt(o, v)
        assert o.score_half_life_estimate() == float("inf")

    def test_improving_returns_positive_finite(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.7]:
            _push_opt(o, v)
        hl = o.score_half_life_estimate()
        assert 0 < hl < float("inf")


# ── OntologyOptimizer.history_increasing_fraction ────────────────────────────

class TestHistoryIncreasingFraction:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_increasing_fraction() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.history_increasing_fraction() == pytest.approx(0.0)

    def test_all_increasing_returns_one(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.7]:
            _push_opt(o, v)
        assert o.history_increasing_fraction() == pytest.approx(1.0)

    def test_half_increasing(self):
        o = _make_optimizer()
        for v in [0.3, 0.7, 0.5, 0.9]:
            _push_opt(o, v)
        # steps: +, -, + → 2/3
        assert o.history_increasing_fraction() == pytest.approx(2 / 3)


# ── OntologyGenerator.entity_confidence_cv ───────────────────────────────────

class TestEntityConfidenceCv:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_confidence_cv(r) == pytest.approx(0.0)

    def test_single_returns_zero(self):
        g = _make_generator()
        r = _make_result([_make_entity("a", 0.5)])
        assert g.entity_confidence_cv(r) == pytest.approx(0.0)

    def test_uniform_returns_zero(self):
        g = _make_generator()
        r = _make_result([_make_entity("a", 0.5), _make_entity("b", 0.5)])
        assert g.entity_confidence_cv(r) == pytest.approx(0.0)

    def test_returns_float(self):
        g = _make_generator()
        r = _make_result([_make_entity("a", 0.3), _make_entity("b", 0.7)])
        result = g.entity_confidence_cv(r)
        assert isinstance(result, float)
        assert result >= 0.0


# ── OntologyGenerator.relationship_unique_endpoints ──────────────────────────

class TestRelationshipUniqueEndpoints:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result(relationships=[])
        assert g.relationship_unique_endpoints(r) == 0

    def test_single_relationship(self):
        g = _make_generator()
        r = _make_result(relationships=[_make_rel_mock("a", "b")])
        assert g.relationship_unique_endpoints(r) == 2

    def test_shared_endpoint_counted_once(self):
        g = _make_generator()
        rels = [_make_rel_mock("a", "b"), _make_rel_mock("a", "c")]
        r = _make_result(relationships=rels)
        # a, b, c → 3 unique endpoints
        assert g.relationship_unique_endpoints(r) == 3


# ── LogicValidator.density_comparison ────────────────────────────────────────

class TestDensityComparison:
    def test_empty_returns_zeros(self):
        v = _make_validator()
        result = v.density_comparison({})
        assert result["edges"] == 0
        assert result["nodes"] == 0

    def test_single_edge(self):
        v = _make_validator()
        onto = {"relationships": [{"source": "a", "target": "b"}]}
        result = v.density_comparison(onto)
        assert result["edges"] == 1
        assert result["nodes"] == 2
        # density = 1 / (2*1) = 0.5
        assert result["actual_density"] == pytest.approx(0.5)

    def test_dense_graph(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "a"},
        ]}
        result = v.density_comparison(onto)
        # V=2, E=2, max=2 → density=1.0
        assert result["actual_density"] == pytest.approx(1.0)


# ── OntologyPipeline.run_best_to_current_ratio ───────────────────────────────

class TestRunBestToCurrentRatio:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_best_to_current_ratio() == pytest.approx(0.0)

    def test_single_run_returns_one(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.run_best_to_current_ratio() == pytest.approx(1.0)

    def test_ratio_when_current_is_best(self):
        p = _make_pipeline()
        for v in [0.3, 0.7]:
            _push_run(p, v)
        assert p.run_best_to_current_ratio() == pytest.approx(1.0)

    def test_ratio_when_current_below_best(self):
        p = _make_pipeline()
        for v in [0.9, 0.6]:
            _push_run(p, v)
        assert p.run_best_to_current_ratio() == pytest.approx(0.9 / 0.6)


# ── OntologyLearningAdapter.feedback_half_above_threshold ────────────────────

class TestFeedbackHalfAboveThreshold:
    def test_empty_returns_false(self):
        a = _make_adapter()
        assert a.feedback_half_above_threshold() is False

    def test_all_above_returns_true(self):
        a = _make_adapter()
        for v in [0.6, 0.7, 0.8]:
            _push_feedback(a, v)
        assert a.feedback_half_above_threshold() is True

    def test_all_below_returns_false(self):
        a = _make_adapter()
        for v in [0.1, 0.2, 0.3]:
            _push_feedback(a, v)
        assert a.feedback_half_above_threshold() is False

    def test_exactly_half_returns_true(self):
        a = _make_adapter()
        for v in [0.3, 0.7]:
            _push_feedback(a, v)
        assert a.feedback_half_above_threshold() is True


# ── OntologyMediator.action_peak_fraction ────────────────────────────────────

class TestActionPeakFraction:
    def test_empty_returns_zero(self):
        m = _make_mediator()
        assert m.action_peak_fraction() == pytest.approx(0.0)

    def test_single_type_returns_one(self):
        m = _make_mediator()
        m._action_counts = {"a": 5}
        assert m.action_peak_fraction() == pytest.approx(1.0)

    def test_dominant_action(self):
        m = _make_mediator()
        m._action_counts = {"a": 8, "b": 2}
        assert m.action_peak_fraction() == pytest.approx(0.8)
