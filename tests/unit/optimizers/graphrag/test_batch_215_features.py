"""Batch 215 feature tests.

Methods under test (3 new + 3 stale-verified):
  New:
    - OntologyOptimizer.score_bimodality_index()
    - OntologyCritic.dimension_percentile_rank(score, dim)
    - LogicValidator.eccentricity_distribution(ontology)
  Stale (already existed, smoke-tested):
    - OntologyGenerator.entity_avg_text_length(result)
    - OntologyLearningAdapter.feedback_mean_last_n(n)   [was feedback_last_n_mean]
    - OntologyPipeline.run_score_iqr()
"""
import math
import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg


def _push_opt(o, avg):
    o._history.append(_FakeEntry(avg))


def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


def _make_critic():
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    return OntologyCritic.__new__(OntologyCritic)


def _make_score(completeness=0.5, consistency=0.5, clarity=0.5,
                granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5):
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
    return CriticScore(
        completeness=completeness,
        consistency=consistency,
        clarity=clarity,
        granularity=granularity,
        relationship_coherence=relationship_coherence,
        domain_alignment=domain_alignment,
    )


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


def _make_entity(eid, text=None, confidence=1.0, entity_type="T"):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type=entity_type, text=text or eid, confidence=confidence)


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


class _FakeRun:
    def __init__(self, score):
        self.overall_score = score


def _push_run(p, score):
    p._run_history.append(_FakeRun(score))


def _ontology(entities, rels):
    return {
        "entities": [{"id": e} for e in entities],
        "relationships": [{"source": s, "target": t} for s, t in rels],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# OntologyOptimizer.score_bimodality_index
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoreBimodalityIndex:
    def test_returns_zero_no_history(self):
        o = _make_optimizer()
        assert o.score_bimodality_index() == 0.0

    def test_returns_zero_single_entry(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.score_bimodality_index() == 0.0

    def test_returns_zero_uniform_scores(self):
        o = _make_optimizer()
        for _ in range(6):
            _push_opt(o, 0.5)
        assert o.score_bimodality_index() == 0.0

    def test_perfect_bimodal_two_clusters(self):
        # [0.0, 0.0, 1.0, 1.0] — perfectly split
        o = _make_optimizer()
        for _ in range(2):
            _push_opt(o, 0.0)
        for _ in range(2):
            _push_opt(o, 1.0)
        val = o.score_bimodality_index()
        assert val == pytest.approx(1.0, abs=1e-9)

    def test_bimodal_higher_than_unimodal(self):
        o_bimodal = _make_optimizer()
        for _ in range(4):
            _push_opt(o_bimodal, 0.0)
        for _ in range(4):
            _push_opt(o_bimodal, 1.0)

        o_unimodal = _make_optimizer()
        for _ in range(8):
            _push_opt(o_unimodal, 0.5)

        assert o_bimodal.score_bimodality_index() > o_unimodal.score_bimodality_index()

    def test_result_in_unit_interval(self):
        o = _make_optimizer()
        scores = [0.1, 0.3, 0.5, 0.6, 0.8, 0.9]
        for s in scores:
            _push_opt(o, s)
        val = o.score_bimodality_index()
        assert 0.0 <= val <= 1.0

    def test_two_entries_different(self):
        o = _make_optimizer()
        _push_opt(o, 0.0)
        _push_opt(o, 1.0)
        val = o.score_bimodality_index()
        assert val == pytest.approx(1.0, abs=1e-9)

    def test_nearly_uniform_low_score(self):
        o = _make_optimizer()
        for v in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
            _push_opt(o, v)
        val = o.score_bimodality_index()
        assert val >= 0.0

    def test_asymmetric_cluster_still_in_unit_range(self):
        o = _make_optimizer()
        for _ in range(3):
            _push_opt(o, 0.1)
        for _ in range(1):
            _push_opt(o, 0.9)
        val = o.score_bimodality_index()
        assert 0.0 <= val <= 1.0

    def test_returns_float(self):
        o = _make_optimizer()
        _push_opt(o, 0.3)
        _push_opt(o, 0.7)
        assert isinstance(o.score_bimodality_index(), float)


# ═══════════════════════════════════════════════════════════════════════════════
# OntologyCritic.dimension_percentile_rank
# ═══════════════════════════════════════════════════════════════════════════════

class TestDimensionPercentileRank:
    def test_maximum_dim_returns_1(self):
        c = _make_critic()
        s = _make_score(completeness=1.0, consistency=0.5, clarity=0.5,
                        granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5)
        assert c.dimension_percentile_rank(s, 'completeness') == pytest.approx(1.0)

    def test_minimum_dim_returns_1_over_6(self):
        # Only 1 out of 6 values ≤ minimum (itself)
        c = _make_critic()
        s = _make_score(completeness=0.0, consistency=0.5, clarity=0.5,
                        granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5)
        assert c.dimension_percentile_rank(s, 'completeness') == pytest.approx(1.0 / 6.0)

    def test_all_equal_all_dims_rank_1(self):
        c = _make_critic()
        s = _make_score(0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
        for dim in ('completeness', 'consistency', 'clarity',
                    'granularity', 'relationship_coherence', 'domain_alignment'):
            assert c.dimension_percentile_rank(s, dim) == pytest.approx(1.0)

    def test_invalid_dim_returns_zero(self):
        c = _make_critic()
        s = _make_score()
        assert c.dimension_percentile_rank(s, 'nonexistent') == 0.0

    def test_middle_ranked_dim(self):
        c = _make_critic()
        # vals: 0.1, 0.2, 0.5, 0.6, 0.8, 0.9 → clarity=0.5 is 3rd out of 6
        s = _make_score(completeness=0.9, consistency=0.8, clarity=0.5,
                        granularity=0.6, relationship_coherence=0.2, domain_alignment=0.1)
        rank = c.dimension_percentile_rank(s, 'clarity')
        # values ≤ 0.5: [0.1, 0.2, 0.5] → 3 out of 6 = 0.5
        assert rank == pytest.approx(3.0 / 6.0)

    def test_tie_handling(self):
        c = _make_critic()
        # completeness and consistency both 0.7; two values ≤ 0.5 ... wait, let's check
        s = _make_score(completeness=0.5, consistency=0.5, clarity=0.5,
                        granularity=0.5, relationship_coherence=0.9, domain_alignment=0.9)
        # values ≤ 0.5: [0.5, 0.5, 0.5, 0.5] → 4 out of 6
        rank = c.dimension_percentile_rank(s, 'completeness')
        assert rank == pytest.approx(4.0 / 6.0)

    def test_second_lowest(self):
        c = _make_critic()
        s = _make_score(completeness=0.9, consistency=0.8, clarity=0.7,
                        granularity=0.6, relationship_coherence=0.2, domain_alignment=0.1)
        # relationship_coherence=0.2; values ≤ 0.2: [0.1, 0.2] → 2/6
        rank = c.dimension_percentile_rank(s, 'relationship_coherence')
        assert rank == pytest.approx(2.0 / 6.0)

    def test_result_in_unit_interval(self):
        c = _make_critic()
        s = _make_score(0.3, 0.5, 0.7, 0.2, 0.9, 0.4)
        for dim in ('completeness', 'consistency', 'clarity',
                    'granularity', 'relationship_coherence', 'domain_alignment'):
            r = c.dimension_percentile_rank(s, dim)
            assert 0.0 <= r <= 1.0

    def test_returns_float(self):
        c = _make_critic()
        s = _make_score()
        assert isinstance(c.dimension_percentile_rank(s, 'clarity'), float)

    def test_distinct_values_consistent_ordering(self):
        c = _make_critic()
        s = _make_score(completeness=0.1, consistency=0.2, clarity=0.3,
                        granularity=0.4, relationship_coherence=0.5, domain_alignment=0.6)
        ranks = [c.dimension_percentile_rank(s, d) for d in
                 ('completeness', 'consistency', 'clarity',
                  'granularity', 'relationship_coherence', 'domain_alignment')]
        # ranks should be strictly increasing
        for i in range(1, len(ranks)):
            assert ranks[i] > ranks[i - 1]


# ═══════════════════════════════════════════════════════════════════════════════
# LogicValidator.eccentricity_distribution
# ═══════════════════════════════════════════════════════════════════════════════

class TestEccentricityDistribution:
    def test_empty_ontology_returns_empty(self):
        v = _make_validator()
        assert v.eccentricity_distribution({}) == []

    def test_single_node_no_edges(self):
        v = _make_validator()
        result = v.eccentricity_distribution(_ontology(["A"], []))
        assert result == [0]

    def test_two_nodes_one_directed_edge(self):
        v = _make_validator()
        ont = _ontology(["A", "B"], [("A", "B")])
        result = v.eccentricity_distribution(ont)
        # sorted order: A, B
        assert result[0] == 1   # A→B: dist 1
        assert result[1] == 0   # B can reach no one

    def test_linear_chain(self):
        v = _make_validator()
        ont = _ontology(["A", "B", "C"], [("A", "B"), ("B", "C")])
        result = v.eccentricity_distribution(ont)
        # sorted: A, B, C
        assert result[0] == 2   # A→B→C
        assert result[1] == 1   # B→C
        assert result[2] == 0   # C can reach no one

    def test_cycle_all_equal(self):
        v = _make_validator()
        ont = _ontology(["A", "B", "C"], [("A", "B"), ("B", "C"), ("C", "A")])
        result = v.eccentricity_distribution(ont)
        # In a 3-cycle, max dist from any node is 2
        assert len(result) == 3
        assert all(e == 2 for e in result)

    def test_two_disconnected_nodes(self):
        v = _make_validator()
        ont = _ontology(["A", "B"], [])
        result = v.eccentricity_distribution(ont)
        assert result == [0, 0]

    def test_self_loop_ignored(self):
        v = _make_validator()
        ont = {
            "entities": [{"id": "X"}],
            "relationships": [{"source": "X", "target": "X"}],
        }
        result = v.eccentricity_distribution(ont)
        assert result == [0]

    def test_result_length_equals_node_count(self):
        v = _make_validator()
        ont = _ontology(["A", "B", "C", "D"], [("A", "B"), ("C", "D")])
        result = v.eccentricity_distribution(ont)
        assert len(result) == 4

    def test_all_nonnegative(self):
        v = _make_validator()
        ont = _ontology(["A", "B", "C"], [("A", "B"), ("A", "C")])
        result = v.eccentricity_distribution(ont)
        assert all(e >= 0 for e in result)

    def test_star_graph_center_has_highest_eccentricity_1(self):
        v = _make_validator()
        # Center→4 leaves, no edges back
        ont = _ontology(["C", "L1", "L2", "L3", "L4"],
                        [("C", "L1"), ("C", "L2"), ("C", "L3"), ("C", "L4")])
        result = v.eccentricity_distribution(ont)
        # C reaches L1..L4 in 1 hop → ecc=1; leaves reach no one → ecc=0
        idx_C = sorted(["C", "L1", "L2", "L3", "L4"]).index("C")
        assert result[idx_C] == 1
        for i, node in enumerate(sorted(["C", "L1", "L2", "L3", "L4"])):
            if node != "C":
                assert result[i] == 0

    def test_returns_list(self):
        v = _make_validator()
        assert isinstance(v.eccentricity_distribution(_ontology(["A"], [])), list)

    def test_diameter_equals_max_eccentricity(self):
        """diameter_approx should equal max of eccentricity_distribution."""
        v = _make_validator()
        ont = _ontology(["A", "B", "C", "D"],
                        [("A", "B"), ("B", "C"), ("C", "D")])
        ecc = v.eccentricity_distribution(ont)
        diam = v.diameter_approx(ont)
        assert max(ecc) == diam

    def test_nodes_from_relationships_only(self):
        v = _make_validator()
        ont = {
            "entities": [],
            "relationships": [{"source": "X", "target": "Y"}],
        }
        result = v.eccentricity_distribution(ont)
        assert len(result) == 2
        assert sorted(result) == [0, 1]

    def test_deterministic_sorted_order(self):
        v = _make_validator()
        ont = _ontology(["B", "A", "C"], [("A", "B"), ("B", "C")])
        result1 = v.eccentricity_distribution(ont)
        result2 = v.eccentricity_distribution(ont)
        assert result1 == result2


# ═══════════════════════════════════════════════════════════════════════════════
# Stale smoke tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestStaleB215:
    def test_entity_avg_text_length_exists(self):
        gen = _make_generator()
        result = _make_result(entities=[
            _make_entity("Alice", text="Alice"),
            _make_entity("Bob", text="Bob"),
        ])
        val = gen.entity_avg_text_length(result)
        assert val == pytest.approx(4.0)  # (5+3)/2

    def test_entity_avg_text_length_empty(self):
        gen = _make_generator()
        assert gen.entity_avg_text_length(_make_result()) == 0.0

    def test_feedback_mean_last_n_exists(self):
        a = _make_adapter()
        for score in [0.1, 0.2, 0.3, 0.8, 0.9]:
            _push_feedback(a, score)
        val = a.feedback_mean_last_n(n=2)
        assert val == pytest.approx((0.8 + 0.9) / 2)

    def test_feedback_mean_last_n_empty(self):
        a = _make_adapter()
        assert a.feedback_mean_last_n() == 0.0

    def test_run_score_iqr_exists(self):
        p = _make_pipeline()
        for v in [0.1, 0.3, 0.5, 0.7, 0.9]:
            _push_run(p, v)
        val = p.run_score_iqr()
        assert isinstance(val, float)
        assert val >= 0.0

    def test_run_score_iqr_empty(self):
        p = _make_pipeline()
        assert p.run_score_iqr() == 0.0
