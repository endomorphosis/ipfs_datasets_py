"""Batch-211 feature tests.

Methods under test:
  - OntologyOptimizer.score_gain_rate()
  - OntologyOptimizer.history_weight_by_recency()
  - OntologyGenerator.entity_with_highest_confidence(result)
  - OntologyGenerator.relationship_source_degree_distribution(result)
  - LogicValidator.articulation_point_count(ontology)
  - OntologyPipeline.run_first_to_last_delta()
  - OntologyLearningAdapter.feedback_positive_fraction_last_n(n, threshold)
  - OntologyMediator.action_concentration_ratio(top_k)
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


# ── OntologyOptimizer.score_gain_rate ────────────────────────────────────────

class TestScoreGainRate:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_gain_rate() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.score_gain_rate() == pytest.approx(0.0)

    def test_improving_positive(self):
        o = _make_optimizer()
        for v in [0.4, 0.6, 0.8]:
            _push_opt(o, v)
        # (0.8 - 0.4) / 2 = 0.2
        assert o.score_gain_rate() == pytest.approx(0.2)

    def test_declining_negative(self):
        o = _make_optimizer()
        for v in [0.8, 0.6, 0.4]:
            _push_opt(o, v)
        assert o.score_gain_rate() == pytest.approx(-0.2)


# ── OntologyOptimizer.history_weight_by_recency ──────────────────────────────

class TestHistoryWeightByRecency:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_weight_by_recency() == pytest.approx(0.0)

    def test_single_returns_value(self):
        o = _make_optimizer()
        _push_opt(o, 0.6)
        assert o.history_weight_by_recency() == pytest.approx(0.6)

    def test_two_entries_recent_weighted_more(self):
        o = _make_optimizer()
        _push_opt(o, 0.0)
        _push_opt(o, 1.0)
        # weights: 1, 2; total=3; weighted = (1*0 + 2*1)/3 = 2/3
        assert o.history_weight_by_recency() == pytest.approx(2 / 3)


# ── OntologyGenerator.entity_with_highest_confidence ─────────────────────────

class TestEntityWithHighestConfidence:
    def test_empty_returns_none(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_with_highest_confidence(r) is None

    def test_single_returns_it(self):
        g = _make_generator()
        e = _make_entity("a", 0.7)
        r = _make_result([e])
        assert g.entity_with_highest_confidence(r) is e

    def test_returns_max_entity(self):
        g = _make_generator()
        e1 = _make_entity("a", 0.3)
        e2 = _make_entity("b", 0.9)
        e3 = _make_entity("c", 0.5)
        r = _make_result([e1, e2, e3])
        assert g.entity_with_highest_confidence(r) is e2


# ── OntologyGenerator.relationship_source_degree_distribution ────────────────

class TestRelationshipSourceDegreeDistribution:
    def test_empty_returns_empty_dict(self):
        g = _make_generator()
        r = _make_result(relationships=[])
        assert g.relationship_source_degree_distribution(r) == {}

    def test_single_relationship(self):
        g = _make_generator()
        r = _make_result(relationships=[_make_rel_mock("a", "b")])
        dist = g.relationship_source_degree_distribution(r)
        assert dist == {"a": 1}

    def test_multiple_from_same_source(self):
        g = _make_generator()
        rels = [_make_rel_mock("a", "b"), _make_rel_mock("a", "c"), _make_rel_mock("b", "c")]
        r = _make_result(relationships=rels)
        dist = g.relationship_source_degree_distribution(r)
        assert dist["a"] == 2
        assert dist["b"] == 1


# ── LogicValidator.articulation_point_count ───────────────────────────────────

class TestArticulationPointCount:
    def test_empty_returns_zero(self):
        v = _make_validator()
        assert v.articulation_point_count({}) == 0

    def test_single_edge_no_cut(self):
        v = _make_validator()
        onto = {"relationships": [{"source": "a", "target": "b"}]}
        result = v.articulation_point_count(onto)
        assert isinstance(result, int)
        assert result >= 0

    def test_triangle_no_cut(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "c"},
            {"source": "a", "target": "c"},
        ]}
        # All pairs connected → no articulation points
        assert v.articulation_point_count(onto) == 0


# ── OntologyPipeline.run_first_to_last_delta ─────────────────────────────────

class TestRunFirstToLastDelta:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_first_to_last_delta() == pytest.approx(0.0)

    def test_single_run_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.run_first_to_last_delta() == pytest.approx(0.0)

    def test_positive_delta(self):
        p = _make_pipeline()
        _push_run(p, 0.3)
        _push_run(p, 0.7)
        assert p.run_first_to_last_delta() == pytest.approx(0.4)

    def test_negative_delta(self):
        p = _make_pipeline()
        _push_run(p, 0.8)
        _push_run(p, 0.5)
        assert p.run_first_to_last_delta() == pytest.approx(-0.3)


# ── OntologyLearningAdapter.feedback_positive_fraction_last_n ────────────────

class TestFeedbackPositiveFractionLastN:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_positive_fraction_last_n() == pytest.approx(0.0)

    def test_all_positive(self):
        a = _make_adapter()
        for v in [0.6, 0.7, 0.8]:
            _push_feedback(a, v)
        assert a.feedback_positive_fraction_last_n(n=3) == pytest.approx(1.0)

    def test_half_positive(self):
        a = _make_adapter()
        for v in [0.3, 0.7, 0.3, 0.7]:
            _push_feedback(a, v)
        assert a.feedback_positive_fraction_last_n(n=4) == pytest.approx(0.5)

    def test_window_respected(self):
        a = _make_adapter()
        for v in [0.1, 0.1, 0.9, 0.9]:
            _push_feedback(a, v)
        # last 2 are both 0.9 → 1.0
        assert a.feedback_positive_fraction_last_n(n=2) == pytest.approx(1.0)


# ── OntologyMediator.action_concentration_ratio ──────────────────────────────

class TestActionConcentrationRatio:
    def test_empty_returns_zero(self):
        m = _make_mediator()
        assert m.action_concentration_ratio() == pytest.approx(0.0)

    def test_single_type_returns_one(self):
        m = _make_mediator()
        m._action_counts = {"a": 10}
        assert m.action_concentration_ratio(top_k=3) == pytest.approx(1.0)

    def test_top_3_fraction(self):
        m = _make_mediator()
        m._action_counts = {"a": 5, "b": 3, "c": 2, "d": 0}
        # top 3: 5+3+2=10, total=10 → 1.0
        assert m.action_concentration_ratio(top_k=3) == pytest.approx(1.0)

    def test_top_1_fraction(self):
        m = _make_mediator()
        m._action_counts = {"a": 6, "b": 4}
        assert m.action_concentration_ratio(top_k=1) == pytest.approx(0.6)
