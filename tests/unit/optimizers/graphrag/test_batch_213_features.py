"""Batch 213 feature tests.

Methods under test:
  - OntologyOptimizer.score_zscore_outliers(threshold)
  - OntologyCritic.dimension_weighted_std(score)
  - OntologyGenerator.entity_confidence_weighted_mean(result, weights)
  - OntologyLearningAdapter.feedback_decay_mean(decay)
  - OntologyPipeline.run_score_autocorrelation(lag)
  - LogicValidator.clustering_coefficient_approx(ontology)
"""
import pytest
from unittest.mock import MagicMock


# ── helpers ───────────────────────────────────────────────────────────────────

class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg


def _push_opt(o, avg):
    o._history.append(_FakeEntry(avg))


def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


def _make_critic_direct():
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    return OntologyCritic.__new__(OntologyCritic)


def _make_critic_score(completeness=0.8, consistency=0.7, clarity=0.6,
                        granularity=0.5, relationship_coherence=0.4,
                        domain_alignment=0.3):
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
    return CriticScore(
        completeness=completeness,
        consistency=consistency,
        clarity=clarity,
        granularity=granularity,
        relationship_coherence=relationship_coherence,
        domain_alignment=domain_alignment,
    )


def _make_entity(eid, confidence=1.0, entity_type="T"):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type=entity_type, text=eid, confidence=confidence)


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


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(a, score):
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import FeedbackRecord
    a._feedback.append(FeedbackRecord(final_score=score))


def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline()


def _push_run(p, score_val):
    run = MagicMock()
    run.score.overall = score_val
    p._run_history.append(run)


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


def _make_onto(entity_ids, edge_pairs):
    """Build ontology dict from list of entity IDs and (source, target) tuples."""
    entities = [{"id": eid} for eid in entity_ids]
    relationships = [{"source": s, "target": t} for s, t in edge_pairs]
    return {"entities": entities, "relationships": relationships}


# ── OntologyOptimizer.score_zscore_outliers ──────────────────────────────────

class TestScoreZscoreOutliers:
    def test_empty_returns_empty(self):
        o = _make_optimizer()
        assert o.score_zscore_outliers() == []

    def test_single_returns_empty(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.score_zscore_outliers() == []

    def test_uniform_returns_empty(self):
        o = _make_optimizer()
        for _ in range(5):
            _push_opt(o, 0.5)
        # std = 0 → no outliers
        assert o.score_zscore_outliers() == []

    def test_detects_extreme_outlier(self):
        o = _make_optimizer()
        # 6 clustered near 0.5, one very extreme outlier.
        # With k identical values + 1 extreme outlier the z-score = sqrt(k);
        # we need k >= 5 to get z = sqrt(5) ≈ 2.24 > threshold 2.0.
        for _ in range(6):
            _push_opt(o, 0.5)
        _push_opt(o, 1000.0)  # extreme outlier at index 6
        result = o.score_zscore_outliers(threshold=2.0)
        assert 6 in result

    def test_no_outliers_within_threshold(self):
        o = _make_optimizer()
        for v in [0.4, 0.5, 0.5, 0.5, 0.6]:
            _push_opt(o, v)
        result = o.score_zscore_outliers(threshold=2.0)
        assert result == []

    def test_high_threshold_catches_nothing(self):
        o = _make_optimizer()
        for v in [0.1, 0.9]:
            _push_opt(o, v)
        assert o.score_zscore_outliers(threshold=100.0) == []

    def test_returns_list(self):
        o = _make_optimizer()
        for v in [0.5, 0.5, 0.5]:
            _push_opt(o, v)
        result = o.score_zscore_outliers()
        assert isinstance(result, list)

    def test_multiple_outliers(self):
        o = _make_optimizer()
        # 6 centre values; 2 extreme outliers (need k>=5 identical centre values
        # so z of outliers > 2.0; z of outlier ≈ sqrt(k/(1+outlier fraction)))
        for _ in range(10):
            _push_opt(o, 0.5)
        _push_opt(o, -1000.0)   # low outlier
        _push_opt(o, 1000.0)    # high outlier
        result = o.score_zscore_outliers(threshold=2.0)
        assert len(result) >= 2


# ── OntologyCritic.dimension_weighted_std ────────────────────────────────────

class TestDimensionWeightedStd:
    def test_uniform_returns_zero(self):
        c = _make_critic_direct()
        score = _make_critic_score(0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
        assert c.dimension_weighted_std(score) == pytest.approx(0.0)

    def test_returns_non_negative(self):
        c = _make_critic_direct()
        score = _make_critic_score()
        result = c.dimension_weighted_std(score)
        assert isinstance(result, float)
        assert result >= 0.0

    def test_diverse_dimensions_positive(self):
        c = _make_critic_direct()
        score = _make_critic_score(0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
        assert c.dimension_weighted_std(score) > 0.0

    def test_all_ones_returns_zero(self):
        c = _make_critic_direct()
        score = _make_critic_score(1.0, 1.0, 1.0, 1.0, 1.0, 1.0)
        assert c.dimension_weighted_std(score) == pytest.approx(0.0)

    def test_all_zeros_returns_zero(self):
        c = _make_critic_direct()
        score = _make_critic_score(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        assert c.dimension_weighted_std(score) == pytest.approx(0.0)

    def test_result_at_most_half(self):
        c = _make_critic_direct()
        # Max possible wstd is when half weights at 0, half at 1
        score = _make_critic_score(0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
        result = c.dimension_weighted_std(score)
        assert result <= 0.6  # sanity upper bound

    def test_smoke_different_dims(self):
        c = _make_critic_direct()
        score = _make_critic_score(0.2, 0.4, 0.6, 0.8, 0.9, 0.1)
        result = c.dimension_weighted_std(score)
        assert 0.0 <= result <= 1.0


# ── OntologyGenerator.entity_confidence_weighted_mean ────────────────────────

class TestEntityConfidenceWeightedMean:
    def test_empty_returns_zero(self):
        g = _make_generator()
        r = _make_result([])
        assert g.entity_confidence_weighted_mean(r) == pytest.approx(0.0)

    def test_no_weights_plain_mean(self):
        g = _make_generator()
        entities = [
            _make_entity("a", confidence=0.4, entity_type="A"),
            _make_entity("b", confidence=0.8, entity_type="B"),
        ]
        r = _make_result(entities)
        result = g.entity_confidence_weighted_mean(r)
        assert result == pytest.approx(0.6)

    def test_double_weight_pulls_towards_high(self):
        g = _make_generator()
        entities = [
            _make_entity("a", confidence=0.2, entity_type="Low"),
            _make_entity("b", confidence=1.0, entity_type="High"),
        ]
        r = _make_result(entities)
        # weight High=3, Low=1 → (1*0.2 + 3*1.0) / 4 = 3.2/4 = 0.8
        result = g.entity_confidence_weighted_mean(r, {"High": 3.0, "Low": 1.0})
        assert result == pytest.approx(0.8)

    def test_zero_weight_excludes_type(self):
        g = _make_generator()
        entities = [
            _make_entity("a", confidence=0.0, entity_type="Noise"),
            _make_entity("b", confidence=0.9, entity_type="Signal"),
        ]
        r = _make_result(entities)
        result = g.entity_confidence_weighted_mean(r, {"Noise": 0.0, "Signal": 1.0})
        assert result == pytest.approx(0.9)

    def test_returns_float_in_range(self):
        g = _make_generator()
        entities = [_make_entity(f"e{i}", confidence=0.5) for i in range(5)]
        r = _make_result(entities)
        result = g.entity_confidence_weighted_mean(r)
        assert 0.0 <= result <= 1.0

    def test_single_entity(self):
        g = _make_generator()
        r = _make_result([_make_entity("x", confidence=0.75)])
        assert g.entity_confidence_weighted_mean(r) == pytest.approx(0.75)

    def test_none_weights_defaults_to_uniform(self):
        g = _make_generator()
        entities = [
            _make_entity("a", confidence=0.3),
            _make_entity("b", confidence=0.7),
        ]
        r = _make_result(entities)
        assert g.entity_confidence_weighted_mean(r, None) == pytest.approx(0.5)

    def test_unknown_type_uses_default_weight_one(self):
        g = _make_generator()
        entities = [
            _make_entity("a", confidence=0.4, entity_type="Known"),
            _make_entity("b", confidence=0.8, entity_type="Unknown"),
        ]
        r = _make_result(entities)
        # weights only specifies "Known" → Unknown defaults to 1.0
        result = g.entity_confidence_weighted_mean(r, {"Known": 1.0})
        assert result == pytest.approx((0.4 + 0.8) / 2)


# ── OntologyLearningAdapter.feedback_decay_mean ──────────────────────────────

class TestFeedbackDecayMean:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_decay_mean() == pytest.approx(0.0)

    def test_single_entry(self):
        a = _make_adapter()
        _push_feedback(a, 0.7)
        assert a.feedback_decay_mean() == pytest.approx(0.7)

    def test_decay_weights_recency(self):
        a = _make_adapter()
        _push_feedback(a, 0.0)   # old
        _push_feedback(a, 1.0)   # recent
        # decay=0.9: weights=[0.9^1, 0.9^0] = [0.9, 1.0]
        # mean = (0.9*0.0 + 1.0*1.0) / 1.9 = 1.0/1.9 ≈ 0.526
        result = a.feedback_decay_mean(decay=0.9)
        assert result > 0.5  # recent high score should dominate

    def test_uniform_scores_return_score(self):
        a = _make_adapter()
        for _ in range(4):
            _push_feedback(a, 0.6)
        result = a.feedback_decay_mean()
        assert result == pytest.approx(0.6)

    def test_result_in_range(self):
        a = _make_adapter()
        for v in [0.2, 0.4, 0.6, 0.8]:
            _push_feedback(a, v)
        result = a.feedback_decay_mean()
        assert 0.0 <= result <= 1.0

    def test_decay_one_is_arithmetic_mean(self):
        a = _make_adapter()
        for v in [0.2, 0.4, 0.6, 0.8]:
            _push_feedback(a, v)
        # decay=1.0 → all weights equal → plain mean
        result = a.feedback_decay_mean(decay=1.0)
        assert result == pytest.approx(0.5)

    def test_decay_near_zero_picks_last(self):
        a = _make_adapter()
        _push_feedback(a, 0.1)
        _push_feedback(a, 0.9)
        # decay very small → weight on last entry dominates
        result = a.feedback_decay_mean(decay=0.001)
        assert result > 0.8

    def test_returns_float(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert isinstance(a.feedback_decay_mean(), float)


# ── OntologyPipeline.run_score_autocorrelation ────────────────────────────────

class TestRunScoreAutocorrelation:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_autocorrelation() == pytest.approx(0.0)

    def test_single_run_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.run_score_autocorrelation(lag=1) == pytest.approx(0.0)

    def test_uniform_series_returns_zero(self):
        p = _make_pipeline()
        for _ in range(5):
            _push_run(p, 0.6)
        assert p.run_score_autocorrelation(lag=1) == pytest.approx(0.0)

    def test_increasing_series_positive_autocorrelation(self):
        p = _make_pipeline()
        for v in [0.1, 0.3, 0.5, 0.7, 0.9]:
            _push_run(p, v)
        result = p.run_score_autocorrelation(lag=1)
        assert result > 0.0

    def test_alternating_series_negative_autocorrelation(self):
        p = _make_pipeline()
        for v in [0.1, 0.9, 0.1, 0.9, 0.1, 0.9]:
            _push_run(p, v)
        result = p.run_score_autocorrelation(lag=1)
        assert result < 0.0

    def test_result_in_minus_one_to_one(self):
        p = _make_pipeline()
        for v in [0.2, 0.8, 0.4, 0.6, 0.5]:
            _push_run(p, v)
        result = p.run_score_autocorrelation(lag=1)
        assert -1.0 <= result <= 1.0

    def test_lag_two(self):
        p = _make_pipeline()
        for v in [0.1, 0.5, 0.2, 0.6, 0.3, 0.7]:
            _push_run(p, v)
        result = p.run_score_autocorrelation(lag=2)
        assert isinstance(result, float)

    def test_lag_too_large_returns_zero(self):
        p = _make_pipeline()
        for v in [0.3, 0.7]:
            _push_run(p, v)
        # lag >= n → 0.0
        assert p.run_score_autocorrelation(lag=5) == pytest.approx(0.0)

    def test_returns_float(self):
        p = _make_pipeline()
        for v in [0.3, 0.7, 0.5]:
            _push_run(p, v)
        assert isinstance(p.run_score_autocorrelation(), float)


# ── LogicValidator.clustering_coefficient_approx ─────────────────────────────

class TestClusteringCoefficientApprox:
    def test_empty_returns_zero(self):
        v = _make_validator()
        assert v.clustering_coefficient_approx({}) == pytest.approx(0.0)

    def test_no_entities_returns_zero(self):
        v = _make_validator()
        onto = {"entities": [], "relationships": []}
        assert v.clustering_coefficient_approx(onto) == pytest.approx(0.0)

    def test_isolated_nodes_returns_zero(self):
        v = _make_validator()
        onto = _make_onto(["A", "B", "C"], [])
        assert v.clustering_coefficient_approx(onto) == pytest.approx(0.0)

    def test_triangle_returns_one(self):
        v = _make_validator()
        # A-B, B-C, A-C (triangle — all neighbours connected)
        onto = _make_onto(["A", "B", "C"], [("A", "B"), ("B", "C"), ("A", "C")])
        result = v.clustering_coefficient_approx(onto)
        assert result == pytest.approx(1.0)

    def test_star_graph_returns_zero(self):
        v = _make_validator()
        # Centre A connected to B, C, D but B/C/D not connected to each other
        onto = _make_onto(
            ["A", "B", "C", "D"],
            [("A", "B"), ("A", "C"), ("A", "D")],
        )
        result = v.clustering_coefficient_approx(onto)
        # B, C, D each have degree 1 → not counted; A has degree 3 but no
        # edges among its neighbours
        assert result == pytest.approx(0.0)

    def test_result_in_zero_one_range(self):
        v = _make_validator()
        onto = _make_onto(
            ["A", "B", "C", "D"],
            [("A", "B"), ("B", "C"), ("C", "D"), ("A", "C")],
        )
        result = v.clustering_coefficient_approx(onto)
        assert 0.0 <= result <= 1.0

    def test_returns_float(self):
        v = _make_validator()
        onto = _make_onto(["A", "B"], [("A", "B")])
        assert isinstance(v.clustering_coefficient_approx(onto), float)

    def test_complete_graph_four_nodes_returns_one(self):
        v = _make_validator()
        nodes = ["A", "B", "C", "D"]
        edges = [(a, b) for a in nodes for b in nodes if a < b]
        onto = _make_onto(nodes, edges)
        result = v.clustering_coefficient_approx(onto)
        assert result == pytest.approx(1.0)

    def test_no_degree_two_nodes_returns_zero(self):
        v = _make_validator()
        # Path graph A-B (each has degree 1, no node has degree ≥ 2)
        onto = _make_onto(["A", "B"], [("A", "B")])
        assert v.clustering_coefficient_approx(onto) == pytest.approx(0.0)
