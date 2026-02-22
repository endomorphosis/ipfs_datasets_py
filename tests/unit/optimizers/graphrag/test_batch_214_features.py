"""Batch 214 feature tests.

Methods under test (3 new + 3 stale-verified):
  New:
    - OntologyOptimizer.score_bimodality_dip()
    - OntologyGenerator.entity_confidence_trimmed_mean(result, trim_pct)
    - LogicValidator.diameter_approx(ontology)
  Stale (already existed, smoke-tested):
    - OntologyCritic.dimension_entropy(score)
    - OntologyLearningAdapter.feedback_range()
    - OntologyPipeline.run_score_percentile(p)
"""
import math
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


# ── OntologyOptimizer.score_bimodality_dip ───────────────────────────────────

class TestScoreBimodalityDip:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_bimodality_dip() == 0.0

    def test_single_entry_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.score_bimodality_dip() == 0.0

    def test_two_entries_returns_nonnegative(self):
        o = _make_optimizer()
        _push_opt(o, 0.1)
        _push_opt(o, 0.9)
        result = o.score_bimodality_dip()
        assert result >= 0.0

    def test_uniform_distribution_low_dip(self):
        # Scores spread evenly across all 10 bins → dip near 0
        o = _make_optimizer()
        for i in range(10):
            _push_opt(o, (i + 0.5) / 10.0)
        dip = o.score_bimodality_dip()
        # Each bin has exactly 1/10 → dip should be 0
        assert dip == pytest.approx(0.0, abs=1e-9)

    def test_all_in_one_bin_high_dip(self):
        # All scores in bin 0 → max|1.0 - 0.1| = 0.9, other bins |0.0 - 0.1| = 0.1
        o = _make_optimizer()
        for _ in range(10):
            _push_opt(o, 0.05)  # all in bin 0
        dip = o.score_bimodality_dip()
        assert dip == pytest.approx(0.9, abs=1e-9)

    def test_bimodal_higher_dip_than_uniform(self):
        # Mix of scores at both extremes → higher dip than near-uniform
        o_bi = _make_optimizer()
        o_uni = _make_optimizer()
        for _ in range(5):
            _push_opt(o_bi, 0.05)
            _push_opt(o_bi, 0.95)
        for i in range(10):
            _push_opt(o_uni, (i + 0.5) / 10.0)
        dip_bi = o_bi.score_bimodality_dip()
        dip_uni = o_uni.score_bimodality_dip()
        assert dip_bi > dip_uni

    def test_result_in_unit_interval(self):
        o = _make_optimizer()
        for v in [0.1, 0.2, 0.8, 0.9, 0.5]:
            _push_opt(o, v)
        dip = o.score_bimodality_dip()
        assert 0.0 <= dip <= 1.0

    def test_boundary_score_zero(self):
        o = _make_optimizer()
        for _ in range(5):
            _push_opt(o, 0.0)
        _push_opt(o, 0.5)
        dip = o.score_bimodality_dip()
        assert 0.0 <= dip <= 1.0

    def test_boundary_score_one(self):
        o = _make_optimizer()
        for _ in range(5):
            _push_opt(o, 1.0)  # maps to bin 9
        _push_opt(o, 0.0)
        dip = o.score_bimodality_dip()
        assert 0.0 <= dip <= 1.0

    def test_symmetry_two_equal_groups(self):
        # 5 scores at 0.05 and 5 at 0.55 → bins 0 and 5 each have freq=0.5
        o = _make_optimizer()
        for _ in range(5):
            _push_opt(o, 0.05)
        for _ in range(5):
            _push_opt(o, 0.55)
        dip = o.score_bimodality_dip()
        # Both full bins: |0.5 - 0.1| = 0.4; empty bins: |0.0 - 0.1| = 0.1; max = 0.4
        assert dip == pytest.approx(0.4, abs=1e-9)

    def test_twenty_entries_valid_range(self):
        o = _make_optimizer()
        for v in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0] * 2:
            _push_opt(o, v)
        dip = o.score_bimodality_dip()
        assert 0.0 <= dip <= 1.0


# ── OntologyGenerator.entity_confidence_trimmed_mean ─────────────────────────

class TestEntityConfidenceTrimmedMean:
    def test_no_entities_returns_zero(self):
        g = _make_generator()
        result = _make_result()
        assert g.entity_confidence_trimmed_mean(result) == 0.0

    def test_single_entity_no_trim(self):
        g = _make_generator()
        result = _make_result(entities=[_make_entity("e1", confidence=0.7)])
        tm = g.entity_confidence_trimmed_mean(result, trim_pct=0.0)
        assert tm == pytest.approx(0.7)

    def test_zero_trim_equals_mean(self):
        g = _make_generator()
        entities = [_make_entity(f"e{i}", confidence=v)
                    for i, v in enumerate([0.2, 0.4, 0.6, 0.8])]
        result = _make_result(entities=entities)
        mean = g.avg_entity_confidence(result)
        tm = g.entity_confidence_trimmed_mean(result, trim_pct=0.0)
        assert tm == pytest.approx(mean, abs=1e-9)

    def test_trim_removes_extremes(self):
        # [0.0, 0.5, 0.5, 1.0] → trim 25% from each end → k=1 → keep [0.5, 0.5]
        g = _make_generator()
        entities = [
            _make_entity("e1", confidence=0.0),
            _make_entity("e2", confidence=0.5),
            _make_entity("e3", confidence=0.5),
            _make_entity("e4", confidence=1.0),
        ]
        result = _make_result(entities=entities)
        tm = g.entity_confidence_trimmed_mean(result, trim_pct=25.0)
        assert tm == pytest.approx(0.5)

    def test_default_trim_10_pct(self):
        g = _make_generator()
        entities = [_make_entity(f"e{i}", confidence=float(i) / 10.0)
                    for i in range(10)]  # 0.0, 0.1, ..., 0.9
        result = _make_result(entities=entities)
        tm = g.entity_confidence_trimmed_mean(result)
        # k=1, keep indices 1..8 → [0.1..0.8], mean = 0.45
        assert tm == pytest.approx(0.45)

    def test_result_in_unit_interval(self):
        g = _make_generator()
        entities = [_make_entity(f"e{i}", confidence=v)
                    for i, v in enumerate([0.1, 0.3, 0.7, 0.9])]
        result = _make_result(entities=entities)
        tm = g.entity_confidence_trimmed_mean(result, trim_pct=10.0)
        assert 0.0 <= tm <= 1.0

    def test_invalid_trim_pct_raises(self):
        g = _make_generator()
        result = _make_result(entities=[_make_entity("e1", confidence=0.5)])
        with pytest.raises(ValueError):
            g.entity_confidence_trimmed_mean(result, trim_pct=50.0)

    def test_negative_trim_pct_raises(self):
        g = _make_generator()
        result = _make_result(entities=[_make_entity("e1", confidence=0.5)])
        with pytest.raises(ValueError):
            g.entity_confidence_trimmed_mean(result, trim_pct=-1.0)

    def test_two_entities_zero_trim_mean_of_both(self):
        g = _make_generator()
        entities = [
            _make_entity("e1", confidence=0.3),
            _make_entity("e2", confidence=0.7),
        ]
        result = _make_result(entities=entities)
        tm = g.entity_confidence_trimmed_mean(result, trim_pct=0.0)
        assert tm == pytest.approx(0.5)

    def test_all_same_confidence(self):
        g = _make_generator()
        entities = [_make_entity(f"e{i}", confidence=0.6) for i in range(5)]
        result = _make_result(entities=entities)
        tm = g.entity_confidence_trimmed_mean(result, trim_pct=20.0)
        assert tm == pytest.approx(0.6)

    def test_large_trim_pct_just_below_50(self):
        g = _make_generator()
        entities = [_make_entity(f"e{i}", confidence=float(i) / 9.0)
                    for i in range(10)]
        result = _make_result(entities=entities)
        tm = g.entity_confidence_trimmed_mean(result, trim_pct=49.0)
        assert 0.0 <= tm <= 1.0


# ── LogicValidator.diameter_approx ───────────────────────────────────────────

class TestDiameterApprox:
    def test_empty_graph_returns_zero(self):
        v = _make_validator()
        onto = _make_onto([], [])
        assert v.diameter_approx(onto) == 0

    def test_single_node_returns_zero(self):
        v = _make_validator()
        onto = _make_onto(["A"], [])
        assert v.diameter_approx(onto) == 0

    def test_two_nodes_no_edges_returns_zero(self):
        v = _make_validator()
        onto = _make_onto(["A", "B"], [])
        assert v.diameter_approx(onto) == 0

    def test_single_edge_diameter_one(self):
        v = _make_validator()
        onto = _make_onto(["A", "B"], [("A", "B")])
        assert v.diameter_approx(onto) == 1

    def test_chain_of_three_diameter_two(self):
        # A→B→C: longest path = 2
        v = _make_validator()
        onto = _make_onto(["A", "B", "C"], [("A", "B"), ("B", "C")])
        assert v.diameter_approx(onto) == 2

    def test_chain_of_four_diameter_three(self):
        v = _make_validator()
        onto = _make_onto(["A", "B", "C", "D"],
                          [("A", "B"), ("B", "C"), ("C", "D")])
        assert v.diameter_approx(onto) == 3

    def test_directed_graph_not_symmetric(self):
        # A→B, B→C; from C there's no path to A → diameter still 2 (A→B→C)
        v = _make_validator()
        onto = _make_onto(["A", "B", "C"], [("A", "B"), ("B", "C")])
        assert v.diameter_approx(onto) == 2

    def test_cycle_diameter_n_minus_one(self):
        # A→B→C→A: diameter 2 (any node can reach any other in at most 2 steps)
        v = _make_validator()
        onto = _make_onto(["A", "B", "C"], [("A", "B"), ("B", "C"), ("C", "A")])
        assert v.diameter_approx(onto) == 2

    def test_disconnected_components_diameter_based_on_reachable(self):
        # A→B (component 1), C→D (component 2) → each has diameter 1
        v = _make_validator()
        onto = _make_onto(["A", "B", "C", "D"], [("A", "B"), ("C", "D")])
        assert v.diameter_approx(onto) == 1

    def test_fully_connected_dag(self):
        # A→B, A→C, B→D, C→D → longest path A→B→D or A→C→D = 2
        v = _make_validator()
        onto = _make_onto(
            ["A", "B", "C", "D"],
            [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")],
        )
        assert v.diameter_approx(onto) == 2

    def test_self_loop_ignored(self):
        # A→A (self-loop) + A→B → diameter should be 1
        v = _make_validator()
        onto = {"entities": [{"id": "A"}, {"id": "B"}],
                "relationships": [{"source": "A", "target": "A"},
                                   {"source": "A", "target": "B"}]}
        assert v.diameter_approx(onto) == 1

    def test_star_graph_diameter_two(self):
        # Hub→A, Hub→B, Hub→C; no edges between leaves → diameter 1
        v = _make_validator()
        onto = _make_onto(
            ["Hub", "A", "B", "C"],
            [("Hub", "A"), ("Hub", "B"), ("Hub", "C")],
        )
        assert v.diameter_approx(onto) == 1

    def test_long_chain_diameter_n_minus_one(self):
        n = 6
        ids = [str(i) for i in range(n)]
        edges = [(ids[i], ids[i + 1]) for i in range(n - 1)]
        v = _make_validator()
        onto = _make_onto(ids, edges)
        assert v.diameter_approx(onto) == n - 1

    def test_result_nonnegative(self):
        v = _make_validator()
        onto = _make_onto(["X", "Y"], [("X", "Y"), ("Y", "X")])
        assert v.diameter_approx(onto) >= 0

    def test_edges_only_nodes_not_in_entities(self):
        # Nodes introduced only via relationships
        v = _make_validator()
        onto = {"entities": [],
                "relationships": [{"source": "A", "target": "B"},
                                   {"source": "B", "target": "C"}]}
        assert v.diameter_approx(onto) == 2


# ── Stale smoke tests (already existed) ─────────────────────────────────────

class TestStaleDimensionEntropy:
    """dimension_entropy already existed – smoke-test to confirm it works."""

    def test_uniform_dims_max_entropy(self):
        c = _make_critic_direct()
        score = _make_critic_score(
            completeness=0.5, consistency=0.5, clarity=0.5,
            granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5,
        )
        entropy = c.dimension_entropy(score)
        # Uniform distribution → max entropy = log2(6) ≈ 2.585
        assert entropy == pytest.approx(math.log2(6), abs=1e-6)

    def test_all_zero_dims_returns_zero(self):
        c = _make_critic_direct()
        score = _make_critic_score(
            completeness=0.0, consistency=0.0, clarity=0.0,
            granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0,
        )
        assert c.dimension_entropy(score) == 0.0

    def test_single_nonzero_dim_returns_zero(self):
        c = _make_critic_direct()
        score = _make_critic_score(
            completeness=1.0, consistency=0.0, clarity=0.0,
            granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0,
        )
        # All probability mass on one bin → H = 0
        assert c.dimension_entropy(score) == pytest.approx(0.0)

    def test_result_nonnegative(self):
        c = _make_critic_direct()
        score = _make_critic_score()
        assert c.dimension_entropy(score) >= 0.0


class TestStaleFeedbackRange:
    """feedback_range already existed – smoke-test."""

    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_range() == 0.0

    def test_single_record_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_range() == 0.0

    def test_two_records_correct_range(self):
        a = _make_adapter()
        _push_feedback(a, 0.2)
        _push_feedback(a, 0.8)
        assert a.feedback_range() == pytest.approx(0.6)


class TestStaleRunScorePercentile:
    """run_score_percentile already existed – smoke-test."""

    def test_fewer_than_two_runs_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.run_score_percentile(50.0) == 0.0

    def test_median_of_four_runs(self):
        p = _make_pipeline()
        for v in [0.2, 0.4, 0.6, 0.8]:
            _push_run(p, v)
        # 50th percentile of [0.2, 0.4, 0.6, 0.8] → interpolated between 0.4 and 0.6
        median = p.run_score_percentile(50.0)
        assert 0.4 <= median <= 0.6

    def test_0th_percentile_is_min(self):
        p = _make_pipeline()
        for v in [0.3, 0.5, 0.7]:
            _push_run(p, v)
        assert p.run_score_percentile(0.0) == pytest.approx(0.3)

    def test_100th_percentile_is_max(self):
        p = _make_pipeline()
        for v in [0.3, 0.5, 0.7]:
            _push_run(p, v)
        assert p.run_score_percentile(100.0) == pytest.approx(0.7)
