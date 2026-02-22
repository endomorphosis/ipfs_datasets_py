"""Batch 217 feature tests.

Methods under test (3 new + 3 stale-verified):
  New:
    - OntologyOptimizer.score_bimodality_ratio()
    - OntologyLearningAdapter.feedback_peak_score()
    - LogicValidator.periphery_size(ontology)
  Stale (already existed, smoke-tested):
    - OntologyCritic.dimension_harmonic_mean(score)
    - OntologyGenerator.entity_confidence_cv(result)
    - OntologyPipeline.run_score_coefficient_of_variation()
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


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(adapter, score):
    adapter.apply_feedback(final_score=score, actions={})


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


def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    p = OntologyPipeline.__new__(OntologyPipeline)
    p._run_history = []
    return p


class _FakeScore:
    def __init__(self, overall):
        self.overall = overall


class _FakeRun:
    def __init__(self, s):
        self.score = _FakeScore(s)


def _push_run(p, s):
    p._run_history.append(_FakeRun(s))


def _graph(entities, edges):
    return {
        "entities": [{"id": e} for e in entities],
        "relationships": [{"source": s, "target": t} for s, t in edges],
    }


# ═══════════════════════════════════════════════════════════════════════════════
# OntologyOptimizer.score_bimodality_ratio
# ═══════════════════════════════════════════════════════════════════════════════

class TestScoreBimodalityRatio:

    def test_empty_history_returns_zero(self):
        o = _make_optimizer()
        assert o.score_bimodality_ratio() == 0.0

    def test_single_entry_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.score_bimodality_ratio() == 0.0

    def test_all_identical_scores_returns_zero(self):
        o = _make_optimizer()
        for _ in range(5):
            _push_opt(o, 0.6)
        assert o.score_bimodality_ratio() == 0.0

    def test_non_uniform_spread_returns_positive(self):
        o = _make_optimizer()
        # bimodal-ish: cluster around 0.1 and 0.9
        for _ in range(5):
            _push_opt(o, 0.1)
        for _ in range(5):
            _push_opt(o, 0.9)
        ratio = o.score_bimodality_ratio()
        assert ratio > 0.0

    def test_returns_float(self):
        o = _make_optimizer()
        for v in [0.2, 0.8, 0.2, 0.8, 0.2, 0.8]:
            _push_opt(o, v)
        assert isinstance(o.score_bimodality_ratio(), float)

    def test_ratio_equals_dip_over_mad(self):
        o = _make_optimizer()
        for v in [0.1, 0.2, 0.8, 0.9, 0.1, 0.9]:
            _push_opt(o, v)
        dip = o.score_bimodality_dip()
        mad = o.score_mad()
        expected = dip / mad if mad != 0.0 else 0.0
        assert abs(o.score_bimodality_ratio() - expected) < 1e-9

    def test_two_entries_different(self):
        o = _make_optimizer()
        _push_opt(o, 0.1)
        _push_opt(o, 0.9)
        assert o.score_bimodality_ratio() > 0.0

    def test_monotone_spread_returns_nonnegative(self):
        o = _make_optimizer()
        for v in [0.0, 0.25, 0.5, 0.75, 1.0]:
            _push_opt(o, v)
        assert o.score_bimodality_ratio() >= 0.0

    def test_large_history_consistent(self):
        o = _make_optimizer()
        for i in range(20):
            _push_opt(o, 0.0 if i % 2 == 0 else 1.0)
        ratio = o.score_bimodality_ratio()
        assert ratio > 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# OntologyLearningAdapter.feedback_peak_score
# ═══════════════════════════════════════════════════════════════════════════════

class TestFeedbackPeakScore:

    def test_empty_feedback_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_peak_score() == 0.0

    def test_single_entry(self):
        a = _make_adapter()
        _push_feedback(a, 0.7)
        assert abs(a.feedback_peak_score() - 0.7) < 1e-9

    def test_returns_max(self):
        a = _make_adapter()
        for v in [0.3, 0.8, 0.5, 0.1, 0.9]:
            _push_feedback(a, v)
        assert abs(a.feedback_peak_score() - 0.9) < 1e-9

    def test_all_same(self):
        a = _make_adapter()
        for _ in range(5):
            _push_feedback(a, 0.55)
        assert abs(a.feedback_peak_score() - 0.55) < 1e-9

    def test_descending_sequence(self):
        a = _make_adapter()
        for v in [1.0, 0.8, 0.6, 0.4, 0.2]:
            _push_feedback(a, v)
        assert abs(a.feedback_peak_score() - 1.0) < 1e-9

    def test_ascending_sequence(self):
        a = _make_adapter()
        for v in [0.1, 0.3, 0.5, 0.7, 0.9]:
            _push_feedback(a, v)
        assert abs(a.feedback_peak_score() - 0.9) < 1e-9

    def test_returns_float(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert isinstance(a.feedback_peak_score(), float)

    def test_peak_geq_mean(self):
        a = _make_adapter()
        for v in [0.2, 0.4, 0.6, 0.8]:
            _push_feedback(a, v)
        assert a.feedback_peak_score() >= a.mean_score()

    def test_peak_geq_median(self):
        a = _make_adapter()
        for v in [0.1, 0.5, 0.9]:
            _push_feedback(a, v)
        assert a.feedback_peak_score() >= a.feedback_median()

    def test_two_entries(self):
        a = _make_adapter()
        _push_feedback(a, 0.3)
        _push_feedback(a, 0.7)
        assert abs(a.feedback_peak_score() - 0.7) < 1e-9

    def test_peak_with_zero_scores(self):
        a = _make_adapter()
        for v in [0.0, 0.0, 0.5]:
            _push_feedback(a, v)
        assert abs(a.feedback_peak_score() - 0.5) < 1e-9

    def test_peak_is_last_element(self):
        a = _make_adapter()
        for v in [0.1, 0.2, 0.3, 1.0]:
            _push_feedback(a, v)
        assert abs(a.feedback_peak_score() - 1.0) < 1e-9


# ═══════════════════════════════════════════════════════════════════════════════
# LogicValidator.periphery_size
# ═══════════════════════════════════════════════════════════════════════════════

class TestPeripherySize:

    def test_empty_graph_returns_zero(self):
        v = _make_validator()
        assert v.periphery_size({}) == 0

    def test_single_node_no_edges_returns_zero(self):
        v = _make_validator()
        assert v.periphery_size(_graph(["A"], [])) == 0

    def test_two_nodes_no_edges_returns_zero(self):
        v = _make_validator()
        assert v.periphery_size(_graph(["A", "B"], [])) == 0

    def test_simple_chain_periphery(self):
        # A→B→C: eccs = A=2, B=1, C=0; diameter=2; periphery={A} → size=1
        v = _make_validator()
        g = _graph(["A", "B", "C"], [("A", "B"), ("B", "C")])
        assert v.periphery_size(g) == 1

    def test_two_node_chain_periphery(self):
        # A→B: eccs = A=1, B=0; diameter=1; periphery={A} → size=1
        v = _make_validator()
        g = _graph(["A", "B"], [("A", "B")])
        assert v.periphery_size(g) == 1

    def test_cycle_all_peripheral(self):
        # A→B→C→A: all have ecc=2 (reach others in ≤2 hops); diameter=2; periphery=all 3
        v = _make_validator()
        g = _graph(["A", "B", "C"], [("A", "B"), ("B", "C"), ("C", "A")])
        size = v.periphery_size(g)
        assert size == 3

    def test_star_out_single_hub(self):
        # Hub→A, Hub→B, Hub→C: Hub ecc=1; A/B/C ecc=0; diameter=1; periphery={Hub} → 1
        v = _make_validator()
        g = _graph(["Hub", "A", "B", "C"],
                   [("Hub", "A"), ("Hub", "B"), ("Hub", "C")])
        assert v.periphery_size(g) == 1

    def test_disconnected_uses_positive_eccs_only(self):
        # Two separate chains: A→B and C→D→E
        # A ecc=1, B ecc=0, C ecc=2, D ecc=1, E ecc=0
        # diameter=2; periphery={C} → 1
        v = _make_validator()
        g = {
            "entities": [{"id": x} for x in ["A", "B", "C", "D", "E"]],
            "relationships": [
                {"source": "A", "target": "B"},
                {"source": "C", "target": "D"},
                {"source": "D", "target": "E"},
            ],
        }
        assert v.periphery_size(g) == 1

    def test_returns_int(self):
        v = _make_validator()
        g = _graph(["A", "B"], [("A", "B")])
        assert isinstance(v.periphery_size(g), int)

    def test_periphery_leq_total_nodes(self):
        v = _make_validator()
        g = _graph(["A", "B", "C", "D"],
                   [("A", "B"), ("B", "C"), ("C", "D")])
        entities = g["entities"]
        assert v.periphery_size(g) <= len(entities)

    def test_periphery_size_geq_one_when_positive(self):
        v = _make_validator()
        g = _graph(["A", "B", "C"], [("A", "B"), ("A", "C")])
        # A ecc=1, B ecc=0, C ecc=0; diameter=1; periphery={A} → 1
        assert v.periphery_size(g) >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# Stale smoke tests (methods already existed)
# ═══════════════════════════════════════════════════════════════════════════════

class TestStaleMethodsSmoke:

    def test_dimension_harmonic_mean_returns_float(self):
        c = _make_critic()
        score = _make_score(0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
        result = c.dimension_harmonic_mean(score)
        assert isinstance(result, float)

    def test_dimension_harmonic_mean_uniform_equals_value(self):
        c = _make_critic()
        score = _make_score(0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
        assert abs(c.dimension_harmonic_mean(score) - 0.5) < 1e-6

    def test_entity_confidence_cv_returns_float(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
        g = OntologyGenerator.__new__(OntologyGenerator)
        entities = [_make_entity("E1", confidence=0.3), _make_entity("E2", confidence=0.7)]
        result = _make_result(entities=entities)
        assert isinstance(g.entity_confidence_cv(result), float)

    def test_entity_confidence_cv_zero_for_uniform(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
        g = OntologyGenerator.__new__(OntologyGenerator)
        entities = [_make_entity(f"E{i}", confidence=0.5) for i in range(4)]
        result = _make_result(entities=entities)
        assert g.entity_confidence_cv(result) == 0.0

    def test_run_score_coefficient_of_variation_returns_float(self):
        p = _make_pipeline()
        for v in [0.5, 0.6, 0.7, 0.8]:
            _push_run(p, v)
        assert isinstance(p.run_score_coefficient_of_variation(), float)

    def test_run_score_coefficient_of_variation_zero_for_uniform(self):
        p = _make_pipeline()
        for _ in range(4):
            _push_run(p, 0.6)
        assert p.run_score_coefficient_of_variation() == 0.0
