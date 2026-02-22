"""Batch 218 feature tests.

Methods under test (2 new + 4 stale-verified):
  New:
    - OntologyLearningAdapter.feedback_valley_score()
    - LogicValidator.center_size(ontology)
  Stale (already existed, smoke-tested):
    - OntologyOptimizer.score_harmonic_mean()
    - OntologyCritic.dimension_geometric_mean(score)
    - OntologyGenerator.entity_confidence_range(result)
    - OntologyPipeline.run_score_harmonic_mean()
"""
import math
import pytest


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(adapter, score):
    adapter.apply_feedback(final_score=score, actions={})


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


def _graph(entities, edges):
    return {
        "entities": [{"id": e} for e in entities],
        "relationships": [{"source": s, "target": t} for s, t in edges],
    }


def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg


def _push_opt(o, avg):
    o._history.append(_FakeEntry(avg))


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


# ═══════════════════════════════════════════════════════════════════════════════
# OntologyLearningAdapter.feedback_valley_score
# ═══════════════════════════════════════════════════════════════════════════════

class TestFeedbackValleyScore:

    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_valley_score() == 0.0

    def test_single_entry_returns_that_score(self):
        a = _make_adapter()
        _push_feedback(a, 0.7)
        assert a.feedback_valley_score() == pytest.approx(0.7)

    def test_min_of_multiple_scores(self):
        a = _make_adapter()
        _push_feedback(a, 0.4)
        _push_feedback(a, 0.9)
        _push_feedback(a, 0.6)
        assert a.feedback_valley_score() == pytest.approx(0.4)

    def test_all_uniform_returns_that_score(self):
        a = _make_adapter()
        for _ in range(5):
            _push_feedback(a, 0.5)
        assert a.feedback_valley_score() == pytest.approx(0.5)

    def test_descending_scores_returns_last(self):
        a = _make_adapter()
        for s in [0.9, 0.7, 0.5, 0.3, 0.1]:
            _push_feedback(a, s)
        assert a.feedback_valley_score() == pytest.approx(0.1)

    def test_ascending_scores_returns_first(self):
        a = _make_adapter()
        for s in [0.1, 0.3, 0.5, 0.7, 0.9]:
            _push_feedback(a, s)
        assert a.feedback_valley_score() == pytest.approx(0.1)

    def test_returns_float(self):
        a = _make_adapter()
        _push_feedback(a, 0.3)
        _push_feedback(a, 0.8)
        assert isinstance(a.feedback_valley_score(), float)

    def test_valley_leq_peak(self):
        a = _make_adapter()
        for s in [0.2, 0.8, 0.5, 0.1, 0.9]:
            _push_feedback(a, s)
        assert a.feedback_valley_score() <= a.feedback_peak_score()

    def test_valley_leq_mean(self):
        a = _make_adapter()
        for s in [0.3, 0.5, 0.7, 0.9]:
            _push_feedback(a, s)
        scores = [0.3, 0.5, 0.7, 0.9]
        mean = sum(scores) / len(scores)
        assert a.feedback_valley_score() <= mean

    def test_two_entries(self):
        a = _make_adapter()
        _push_feedback(a, 0.2)
        _push_feedback(a, 0.8)
        assert a.feedback_valley_score() == pytest.approx(0.2)

    def test_zero_score_entry(self):
        a = _make_adapter()
        _push_feedback(a, 0.0)
        _push_feedback(a, 0.5)
        assert a.feedback_valley_score() == pytest.approx(0.0)

    def test_valley_equal_peak_when_uniform(self):
        a = _make_adapter()
        for _ in range(4):
            _push_feedback(a, 0.6)
        assert a.feedback_valley_score() == pytest.approx(a.feedback_peak_score())


# ═══════════════════════════════════════════════════════════════════════════════
# LogicValidator.center_size
# ═══════════════════════════════════════════════════════════════════════════════

class TestCenterSize:

    def test_empty_graph_returns_zero(self):
        v = _make_validator()
        assert v.center_size(_graph([], [])) == 0

    def test_single_node_no_edges_returns_zero(self):
        v = _make_validator()
        assert v.center_size(_graph(["A"], [])) == 0

    def test_two_nodes_no_edges_returns_zero(self):
        v = _make_validator()
        assert v.center_size(_graph(["A", "B"], [])) == 0

    def test_simple_chain_center_is_middle(self):
        # A→B→C: ecc(A)=2, ecc(B)=1, ecc(C)=0
        # radius = min positive ecc = 1 → center = {B} → center_size = 1
        v = _make_validator()
        g = _graph(["A", "B", "C"], [("A", "B"), ("B", "C")])
        assert v.center_size(g) == 1

    def test_two_node_chain_center_size(self):
        # A→B: ecc(A)=1, ecc(B)=0; radius=1; center={A}
        v = _make_validator()
        g = _graph(["A", "B"], [("A", "B")])
        assert v.center_size(g) == 1

    def test_three_cycle_all_center(self):
        # A→B→C→A: all ecc=1 (each reaches the others in ≤2 hops)
        # radius=1; center = all 3 nodes
        v = _make_validator()
        g = _graph(["A", "B", "C"], [("A", "B"), ("B", "C"), ("C", "A")])
        # All eccentricities equal radius so all nodes are in the center
        assert v.center_size(g) == 3

    def test_star_graph_center(self):
        # A→B, A→C, A→D: ecc(A)=1, others=0; radius=1; center={A}
        v = _make_validator()
        g = _graph(["A", "B", "C", "D"],
                   [("A", "B"), ("A", "C"), ("A", "D")])
        assert v.center_size(g) == 1

    def test_returns_int(self):
        v = _make_validator()
        g = _graph(["A", "B"], [("A", "B")])
        assert isinstance(v.center_size(g), int)

    def test_center_leq_periphery_plus_center_leq_n(self):
        # center_size + periphery_size <= total nodes (some may have ecc=0)
        v = _make_validator()
        g = _graph(["A", "B", "C"], [("A", "B"), ("B", "C")])
        n = 3
        c = v.center_size(g)
        p = v.periphery_size(g)
        assert c + p <= n

    def test_center_size_leq_total_nodes(self):
        v = _make_validator()
        g = _graph(["A", "B", "C", "D"],
                   [("A", "B"), ("B", "C"), ("C", "D")])
        assert v.center_size(g) <= 4

    def test_disconnected_graph_returns_positive(self):
        # A→B in one component; C isolated
        # ecc(A)=1, ecc(B)=0, ecc(C)=0; radius=1; center={A}
        v = _make_validator()
        g = _graph(["A", "B", "C"], [("A", "B")])
        assert v.center_size(g) >= 1

    def test_center_radius_relationship(self):
        # center_size counts nodes matching radius, so must equal
        # radius_approx output used as reference
        v = _make_validator()
        g = _graph(["A", "B", "C"], [("A", "B"), ("B", "C")])
        eccs = v.eccentricity_distribution(g)
        positive = [e for e in eccs if e > 0]
        radius = min(positive) if positive else 0
        expected = sum(1 for e in eccs if e == radius) if radius > 0 else 0
        assert v.center_size(g) == expected


# ═══════════════════════════════════════════════════════════════════════════════
# Stale smoke tests (already-implemented methods)
# ═══════════════════════════════════════════════════════════════════════════════

class TestStaleSmoke:

    # OntologyOptimizer.score_harmonic_mean
    def test_score_harmonic_mean_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_harmonic_mean() == 0.0

    def test_score_harmonic_mean_uniform(self):
        o = _make_optimizer()
        for _ in range(4):
            _push_opt(o, 0.5)
        # harmonic mean of uniform values = that value
        assert abs(o.score_harmonic_mean() - 0.5) < 1e-9

    # OntologyCritic.dimension_geometric_mean
    def test_dimension_geometric_mean_uniform(self):
        c = _make_critic()
        s = _make_score(0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
        assert abs(c.dimension_geometric_mean(s) - 0.5) < 1e-9

    def test_dimension_geometric_mean_mixed(self):
        c = _make_critic()
        s = _make_score(0.2, 0.8, 0.2, 0.8, 0.2, 0.8)
        result = c.dimension_geometric_mean(s)
        assert result > 0.0

    # OntologyGenerator.entity_confidence_range
    def test_entity_confidence_range_empty_result(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
        g = OntologyGenerator.__new__(OntologyGenerator)
        r = _make_result()
        assert g.entity_confidence_range(r) == 0.0

    def test_entity_confidence_range_two_entities(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
        g = OntologyGenerator.__new__(OntologyGenerator)
        e1 = _make_entity("E1", confidence=0.2)
        e2 = _make_entity("E2", confidence=0.9)
        r = _make_result(entities=[e1, e2])
        assert abs(g.entity_confidence_range(r) - 0.7) < 1e-9

    # OntologyPipeline.run_score_harmonic_mean
    def test_run_score_harmonic_mean_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.run_score_harmonic_mean() == 0.0

    def test_run_score_harmonic_mean_uniform(self):
        p = _make_pipeline()
        for _ in range(4):
            _push_run(p, 0.5)
        assert abs(p.run_score_harmonic_mean() - 0.5) < 1e-9
