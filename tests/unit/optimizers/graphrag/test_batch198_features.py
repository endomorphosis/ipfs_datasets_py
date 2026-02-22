"""Batch-198 feature tests.

Methods under test:
  - OntologyOptimizer.score_z_score()
  - OntologyOptimizer.score_mad()
  - OntologyOptimizer.history_quantile(q)
  - OntologyGenerator.entity_id_list(result)
  - OntologyGenerator.relationship_source_ids(result)
  - OntologyGenerator.relationship_target_ids(result)
  - LogicValidator.hub_nodes(ontology, min_degree)
  - OntologyPipeline.run_score_count_above_mean()
  - OntologyLearningAdapter.feedback_trimmed_mean(trim)
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


def _make_entity(eid):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="T", text=eid)


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


# ── OntologyOptimizer.score_z_score ──────────────────────────────────────────

class TestScoreZScore:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_z_score() == pytest.approx(0.0)

    def test_single_entry_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.score_z_score() == pytest.approx(0.0)

    def test_uniform_history_std_zero_returns_zero(self):
        o = _make_optimizer()
        for _ in range(4):
            _push_opt(o, 0.5)
        assert o.score_z_score() == pytest.approx(0.0)

    def test_last_is_mean_returns_zero(self):
        o = _make_optimizer()
        for v in [0.4, 0.6, 0.5]:
            _push_opt(o, v)
        # last = 0.5 = mean → z=0
        assert o.score_z_score() == pytest.approx(0.0, abs=1e-9)

    def test_last_above_mean_positive_z(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.9]:
            _push_opt(o, v)
        assert o.score_z_score() > 0.0

    def test_last_below_mean_negative_z(self):
        o = _make_optimizer()
        for v in [0.9, 0.7, 0.1]:
            _push_opt(o, v)
        assert o.score_z_score() < 0.0


# ── OntologyOptimizer.score_mad ──────────────────────────────────────────────

class TestScoreMad:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_mad() == pytest.approx(0.0)

    def test_single_entry_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.score_mad() == pytest.approx(0.0)

    def test_uniform_returns_zero(self):
        o = _make_optimizer()
        for _ in range(4):
            _push_opt(o, 0.5)
        assert o.score_mad() == pytest.approx(0.0)

    def test_known_mad(self):
        o = _make_optimizer()
        # [0.2, 0.4, 0.6, 0.8] median=0.5, deviations=[0.3, 0.1, 0.1, 0.3], MAD=0.2
        for v in [0.2, 0.4, 0.6, 0.8]:
            _push_opt(o, v)
        assert o.score_mad() == pytest.approx(0.2)


# ── OntologyOptimizer.history_quantile ───────────────────────────────────────

class TestHistoryQuantile:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_quantile() == pytest.approx(0.0)

    def test_q0_returns_min(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.7, 0.9]:
            _push_opt(o, v)
        assert o.history_quantile(q=0.0) == pytest.approx(0.3)

    def test_q1_returns_max(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.7, 0.9]:
            _push_opt(o, v)
        assert o.history_quantile(q=1.0) == pytest.approx(0.9)

    def test_q50_is_median(self):
        o = _make_optimizer()
        for v in [0.2, 0.5, 0.8]:
            _push_opt(o, v)
        assert o.history_quantile(q=0.5) == pytest.approx(0.5)


# ── OntologyGenerator.entity_id_list ─────────────────────────────────────────

class TestEntityIdList:
    def test_empty_returns_empty_list(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_id_list(r) == []

    def test_returns_sorted_ids(self):
        g = _make_generator()
        r = _make_result([_make_entity("e3"), _make_entity("e1"), _make_entity("e2")])
        assert g.entity_id_list(r) == ["e1", "e2", "e3"]

    def test_single_entity(self):
        g = _make_generator()
        r = _make_result([_make_entity("only")])
        assert g.entity_id_list(r) == ["only"]


# ── OntologyGenerator.relationship_source_ids ────────────────────────────────

class TestRelationshipSourceIds:
    def test_no_relationships_returns_empty(self):
        g = _make_generator()
        r = _make_result([])
        assert g.relationship_source_ids(r) == set()

    def test_returns_source_ids(self):
        g = _make_generator()
        rels = [_make_rel_mock("a", "b"), _make_rel_mock("c", "d")]
        r = _make_result(relationships=rels)
        assert g.relationship_source_ids(r) == {"a", "c"}

    def test_deduplication(self):
        g = _make_generator()
        rels = [_make_rel_mock("a", "b"), _make_rel_mock("a", "c")]
        r = _make_result(relationships=rels)
        assert g.relationship_source_ids(r) == {"a"}


# ── OntologyGenerator.relationship_target_ids ────────────────────────────────

class TestRelationshipTargetIds:
    def test_no_relationships_returns_empty(self):
        g = _make_generator()
        r = _make_result([])
        assert g.relationship_target_ids(r) == set()

    def test_returns_target_ids(self):
        g = _make_generator()
        rels = [_make_rel_mock("a", "b"), _make_rel_mock("c", "d")]
        r = _make_result(relationships=rels)
        assert g.relationship_target_ids(r) == {"b", "d"}


# ── LogicValidator.hub_nodes ─────────────────────────────────────────────────

class TestHubNodes:
    def test_empty_returns_empty_list(self):
        v = _make_validator()
        assert v.hub_nodes({}) == []

    def test_no_high_degree_nodes(self):
        v = _make_validator()
        onto = {"relationships": [{"source": "a", "target": "b"}]}
        assert v.hub_nodes(onto, min_degree=3) == []

    def test_hub_node_identified(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "hub", "target": "a"},
            {"source": "hub", "target": "b"},
            {"source": "c", "target": "hub"},
        ]}
        # hub: degree 3 (2 out + 1 in) >= 3
        assert v.hub_nodes(onto, min_degree=3) == ["hub"]

    def test_returns_sorted(self):
        v = _make_validator()
        onto = {"relationships": [
            {"source": "z", "target": "y"},
            {"source": "z", "target": "x"},
            {"source": "a", "target": "z"},
            {"source": "a", "target": "b"},
            {"source": "b", "target": "a"},
            {"source": "c", "target": "a"},
        ]}
        result = v.hub_nodes(onto, min_degree=3)
        assert result == sorted(result)


# ── OntologyPipeline.run_score_count_above_mean ──────────────────────────────

class TestRunScoreCountAboveMean:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_count_above_mean() == 0

    def test_uniform_returns_zero(self):
        p = _make_pipeline()
        for _ in range(4):
            _push_run(p, 0.5)
        assert p.run_score_count_above_mean() == 0

    def test_half_above(self):
        p = _make_pipeline()
        for v in [0.3, 0.5, 0.7, 0.9]:
            _push_run(p, v)
        # mean=0.6; 0.7 and 0.9 above → 2
        assert p.run_score_count_above_mean() == 2


# ── OntologyLearningAdapter.feedback_trimmed_mean ────────────────────────────

class TestFeedbackTrimmedMean:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_trimmed_mean() == pytest.approx(0.0)

    def test_single_record(self):
        a = _make_adapter()
        _push_feedback(a, 0.6)
        assert a.feedback_trimmed_mean() == pytest.approx(0.6)

    def test_uniform_trim_returns_same(self):
        a = _make_adapter()
        for _ in range(5):
            _push_feedback(a, 0.5)
        assert a.feedback_trimmed_mean() == pytest.approx(0.5)

    def test_trims_extremes(self):
        a = _make_adapter()
        for v in [0.0, 0.5, 0.5, 0.5, 1.0]:
            _push_feedback(a, v)
        # 10% trim of 5 = 0 items cut; with trim=0.2: cut 1 from each end
        result = a.feedback_trimmed_mean(trim=0.2)
        # trimmed: [0.5, 0.5, 0.5]
        assert result == pytest.approx(0.5)
