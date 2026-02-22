"""Batch 219 feature tests.

New methods:
  * OntologyOptimizer.score_quartile_dispersion()
  * OntologyLearningAdapter.feedback_range_ratio()
  * OntologyPipeline.run_score_quartile_dispersion()
  * LogicValidator.source_count()

Stale smoke tests (already implemented in source, now formally exercised):
  * OntologyCritic.dimension_min(score)
  * OntologyGenerator.relationship_avg_confidence(result)
"""
import math
import types
import pytest


# ---------------------------------------------------------------------------
# Lightweight stubs to avoid heavy import chain
# ---------------------------------------------------------------------------

def _make_optimizer(scores):
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    class _E:
        def __init__(self, v):
            self.average_score = v
    o = object.__new__(OntologyOptimizer)
    o._history = [_E(v) for v in scores]
    return o


def _make_adapter(scores):
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    class _FR:
        def __init__(self, s):
            self.final_score = s
    la = object.__new__(OntologyLearningAdapter)
    la._feedback = [_FR(s) for s in scores]
    return la


def _make_pipeline(scores):
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    class _S:
        def __init__(self, v):
            self.overall = v
    class _R:
        def __init__(self, v):
            self.score = _S(v)
    p = object.__new__(OntologyPipeline)
    p._run_history = [_R(v) for v in scores]
    return p


def _make_ontology(entity_ids, rels):
    """Build a simple object-based ontology fixture."""
    class _E:
        def __init__(self, i):
            self.id = i
    class _R:
        def __init__(self, s, t):
            self.source_id = s
            self.target_id = t
    class _Ont:
        def __init__(self, eids, rs):
            self.entities = [_E(i) for i in eids]
            self.relationships = [_R(s, t) for s, t in rs]
    return _Ont(entity_ids, rels)


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_quartile_dispersion
# ---------------------------------------------------------------------------

class TestScoreQuartileDispersion:
    def test_empty_returns_zero(self):
        o = _make_optimizer([])
        assert o.score_quartile_dispersion() == 0.0

    def test_fewer_than_four_returns_zero(self):
        for n in range(1, 4):
            o = _make_optimizer([0.5] * n)
            assert o.score_quartile_dispersion() == 0.0

    def test_uniform_four_returns_zero(self):
        # q1 == q3 so denom = 2*q; numer = 0
        o = _make_optimizer([0.5, 0.5, 0.5, 0.5])
        assert o.score_quartile_dispersion() == 0.0

    def test_formula_four_entries(self):
        # sorted: [0.2, 0.4, 0.6, 0.8] → q1=scores[1]=0.4, q3=scores[3]=0.8
        o = _make_optimizer([0.8, 0.2, 0.6, 0.4])
        result = o.score_quartile_dispersion()
        expected = (0.8 - 0.4) / (0.8 + 0.4)
        assert abs(result - expected) < 1e-9

    def test_returns_float(self):
        o = _make_optimizer([0.1, 0.3, 0.5, 0.7, 0.9])
        assert isinstance(o.score_quartile_dispersion(), float)

    def test_result_in_zero_to_one(self):
        import random
        random.seed(42)
        vals = [random.random() for _ in range(8)]
        o = _make_optimizer(vals)
        r = o.score_quartile_dispersion()
        assert 0.0 <= r <= 1.0

    def test_all_zeros_returns_zero(self):
        # q3 + q1 == 0 guard
        o = _make_optimizer([0.0, 0.0, 0.0, 0.0])
        assert o.score_quartile_dispersion() == 0.0

    def test_large_history(self):
        vals = [i / 99.0 for i in range(100)]
        o = _make_optimizer(vals)
        r = o.score_quartile_dispersion()
        assert r > 0.0

    def test_high_dispersion_larger_than_low(self):
        # wide spread vs narrow spread
        o_wide = _make_optimizer([0.0, 0.1, 0.9, 1.0])
        o_narrow = _make_optimizer([0.4, 0.45, 0.55, 0.6])
        assert o_wide.score_quartile_dispersion() >= o_narrow.score_quartile_dispersion()


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_range_ratio
# ---------------------------------------------------------------------------

class TestFeedbackRangeRatio:
    def test_empty_returns_zero(self):
        la = _make_adapter([])
        assert la.feedback_range_ratio() == 0.0

    def test_single_entry_uniform(self):
        la = _make_adapter([0.5])
        # peak == valley == 0.5, denom = 1.0, numer = 0.0
        assert la.feedback_range_ratio() == 0.0

    def test_two_entries_formula(self):
        # peak=0.8, valley=0.2, ratio=(0.8-0.2)/(0.8+0.2)=0.6
        la = _make_adapter([0.2, 0.8])
        assert abs(la.feedback_range_ratio() - 0.6) < 1e-9

    def test_all_same_returns_zero(self):
        la = _make_adapter([0.7, 0.7, 0.7])
        assert la.feedback_range_ratio() == 0.0

    def test_all_zeros_returns_zero(self):
        la = _make_adapter([0.0, 0.0, 0.0])
        # peak=0, valley=0, denom=0 → 0.0
        assert la.feedback_range_ratio() == 0.0

    def test_returns_float(self):
        la = _make_adapter([0.3, 0.7])
        assert isinstance(la.feedback_range_ratio(), float)

    def test_result_in_zero_to_one(self):
        la = _make_adapter([0.1, 0.4, 0.9])
        r = la.feedback_range_ratio()
        assert 0.0 <= r <= 1.0

    def test_max_spread(self):
        # peak=1.0, valley=0.0, denom=1.0, but 0.0+1.0=1.0, ratio=1.0
        la = _make_adapter([0.0, 1.0])
        assert abs(la.feedback_range_ratio() - 1.0) < 1e-9

    def test_geq_valley_formula(self):
        # (peak - valley) / (peak + valley) is always >= 0
        la = _make_adapter([0.3, 0.5, 0.8])
        assert la.feedback_range_ratio() >= 0.0

    def test_many_entries_uses_global_peak_valley(self):
        la = _make_adapter([0.4, 0.5, 0.6, 0.1, 0.9])
        expected = (0.9 - 0.1) / (0.9 + 0.1)
        assert abs(la.feedback_range_ratio() - expected) < 1e-9


# ---------------------------------------------------------------------------
# OntologyPipeline.run_score_quartile_dispersion
# ---------------------------------------------------------------------------

class TestRunScoreQuartileDispersion:
    def test_empty_returns_zero(self):
        p = _make_pipeline([])
        assert p.run_score_quartile_dispersion() == 0.0

    def test_fewer_than_four_returns_zero(self):
        for n in range(1, 4):
            p = _make_pipeline([0.5] * n)
            assert p.run_score_quartile_dispersion() == 0.0

    def test_uniform_four_returns_zero(self):
        p = _make_pipeline([0.5, 0.5, 0.5, 0.5])
        assert p.run_score_quartile_dispersion() == 0.0

    def test_formula_four_entries(self):
        # sorted: [0.2, 0.4, 0.6, 0.8] → q1=0.4, q3=0.8
        p = _make_pipeline([0.8, 0.2, 0.6, 0.4])
        expected = (0.8 - 0.4) / (0.8 + 0.4)
        assert abs(p.run_score_quartile_dispersion() - expected) < 1e-9

    def test_returns_float(self):
        p = _make_pipeline([0.2, 0.4, 0.6, 0.8])
        assert isinstance(p.run_score_quartile_dispersion(), float)

    def test_result_in_zero_to_one(self):
        import random
        random.seed(99)
        vals = [random.random() for _ in range(10)]
        p = _make_pipeline(vals)
        r = p.run_score_quartile_dispersion()
        assert 0.0 <= r <= 1.0

    def test_all_zeros_returns_zero(self):
        p = _make_pipeline([0.0, 0.0, 0.0, 0.0])
        assert p.run_score_quartile_dispersion() == 0.0

    def test_wide_spread_larger_than_narrow(self):
        p_wide = _make_pipeline([0.0, 0.1, 0.9, 1.0])
        p_narrow = _make_pipeline([0.45, 0.48, 0.52, 0.55])
        assert p_wide.run_score_quartile_dispersion() >= p_narrow.run_score_quartile_dispersion()


# ---------------------------------------------------------------------------
# LogicValidator.source_count
# ---------------------------------------------------------------------------

class TestSourceCount:
    @pytest.fixture(autouse=True)
    def _validator(self):
        from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
        self.lv = LogicValidator()

    def test_empty_ontology_returns_zero(self):
        assert self.lv.source_count(_make_ontology([], [])) == 0

    def test_single_isolated_node_is_source(self):
        # one node, no edges → in-degree 0 → source
        assert self.lv.source_count(_make_ontology(["A"], [])) == 1

    def test_two_isolated_nodes_both_sources(self):
        assert self.lv.source_count(_make_ontology(["A", "B"], [])) == 2

    def test_single_edge_one_source(self):
        ont = _make_ontology(["A", "B"], [("A", "B")])
        assert self.lv.source_count(ont) == 1  # A has in-degree 0

    def test_chain_only_first_is_source(self):
        ont = _make_ontology(["A", "B", "C"], [("A", "B"), ("B", "C")])
        assert self.lv.source_count(ont) == 1  # A only

    def test_two_sources_one_common_sink(self):
        # A→C, B→C: both A and B are sources
        ont = _make_ontology(["A", "B", "C"], [("A", "C"), ("B", "C")])
        assert self.lv.source_count(ont) == 2

    def test_star_single_source(self):
        # A→B, A→C, A→D
        ont = _make_ontology(["A", "B", "C", "D"], [("A", "B"), ("A", "C"), ("A", "D")])
        assert self.lv.source_count(ont) == 1

    def test_cycle_no_sources(self):
        # A→B→C→A: every node has in-degree ≥ 1
        ont = _make_ontology(["A", "B", "C"], [("A", "B"), ("B", "C"), ("C", "A")])
        assert self.lv.source_count(ont) == 0

    def test_returns_int(self):
        ont = _make_ontology(["A", "B"], [("A", "B")])
        assert isinstance(self.lv.source_count(ont), int)

    def test_disconnected_subgraph(self):
        # A→B (chain), C is isolated → 2 sources (A and C)
        ont = _make_ontology(["A", "B", "C"], [("A", "B")])
        assert self.lv.source_count(ont) == 2

    def test_source_count_leq_entity_count(self):
        ont = _make_ontology(["A", "B", "C", "D"], [("A", "B"), ("B", "C")])
        assert self.lv.source_count(ont) <= 4

    def test_dict_style_ontology(self):
        ont = {
            "entities": [{"id": "A"}, {"id": "B"}],
            "relationships": [{"source_id": "A", "target_id": "B"}],
        }
        assert self.lv.source_count(ont) == 1

    def test_dict_source_target_keys(self):
        # "source" / "target" fallback keys
        ont = {
            "entities": [{"id": "X"}, {"id": "Y"}],
            "relationships": [{"source": "X", "target": "Y"}],
        }
        assert self.lv.source_count(ont) == 1


# ---------------------------------------------------------------------------
# Stale smoke tests (already implemented; exercised here for coverage)
# ---------------------------------------------------------------------------

class TestStaleDimensionMin:
    def test_dimension_min_returns_string(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
        c = OntologyCritic()
        score = CriticScore(
            completeness=0.9,
            consistency=0.3,
            clarity=0.7,
            granularity=0.5,
            relationship_coherence=0.6,
            domain_alignment=0.8,
        )
        result = c.dimension_min(score)
        assert isinstance(result, str)

    def test_dimension_min_returns_lowest(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic, CriticScore
        c = OntologyCritic()
        score = CriticScore(
            completeness=0.9,
            consistency=0.1,   # lowest
            clarity=0.7,
            granularity=0.5,
            relationship_coherence=0.6,
            domain_alignment=0.8,
        )
        assert c.dimension_min(score) == "consistency"


class TestStaleRelationshipAvgConfidence:
    def _make_result(self, confidences):
        """Build a minimal EntityExtractionResult with relationships."""
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (
            EntityExtractionResult, Relationship,
        )
        rels = [
            Relationship(id=f"r{i}", source_id="A", target_id="B", type="rel", confidence=c)
            for i, c in enumerate(confidences)
        ]
        return EntityExtractionResult(entities=[], relationships=rels, confidence=0.5)

    def test_empty_relationships_returns_zero(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
        g = object.__new__(OntologyGenerator)
        result = self._make_result([])
        assert g.relationship_avg_confidence(result) == 0.0

    def test_single_relationship_returns_its_confidence(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
        g = object.__new__(OntologyGenerator)
        result = self._make_result([0.7])
        assert abs(g.relationship_avg_confidence(result) - 0.7) < 1e-9
