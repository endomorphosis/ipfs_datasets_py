"""Batch 216 feature tests.

Methods under test (2 new + 4 stale-verified):
  New:
    - OntologyLearningAdapter.feedback_spike_count(threshold)
    - LogicValidator.radius_approx(ontology)
  Stale (already existed, smoke-tested):
    - OntologyOptimizer.score_bimodality_coefficient()
    - OntologyCritic.dimension_coefficient_of_variation(score)
    - OntologyGenerator.entity_confidence_mode(result)
    - OntologyPipeline.run_score_range()
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
    p = OntologyPipeline.__new__(OntologyPipeline)
    p._run_history = []
    return p


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
# OntologyLearningAdapter.feedback_spike_count
# ═══════════════════════════════════════════════════════════════════════════════

class TestFeedbackSpikeCount:
    def test_empty_feedback_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_spike_count() == 0

    def test_single_feedback_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_spike_count() == 0

    def test_no_spikes_when_all_below_threshold(self):
        a = _make_adapter()
        for score in [0.5, 0.55, 0.52, 0.53]:
            _push_feedback(a, score)
        # max delta = 0.05, threshold = 0.1
        assert a.feedback_spike_count(threshold=0.1) == 0

    def test_counts_single_upward_spike(self):
        a = _make_adapter()
        for score in [0.3, 0.8, 0.75]:
            _push_feedback(a, score)
        # 0.8 - 0.3 = 0.5 > 0.2; 0.75 - 0.8 = 0.05 not
        assert a.feedback_spike_count(threshold=0.2) == 1

    def test_counts_single_downward_spike(self):
        a = _make_adapter()
        for score in [0.9, 0.3, 0.35]:
            _push_feedback(a, score)
        # |0.3 - 0.9| = 0.6 > 0.4; |0.35 - 0.3| = 0.05 not
        assert a.feedback_spike_count(threshold=0.4) == 1

    def test_counts_multiple_spikes(self):
        a = _make_adapter()
        for score in [0.1, 0.9, 0.1, 0.9]:
            _push_feedback(a, score)
        # Each pair: |0.9 - 0.1| = 0.8, |0.1 - 0.9| = 0.8, |0.9 - 0.1| = 0.8 — all > 0.5
        assert a.feedback_spike_count(threshold=0.5) == 3

    def test_boundary_exact_threshold_is_not_spike(self):
        a = _make_adapter()
        for score in [0.3, 0.5]:
            _push_feedback(a, score)
        # |0.5 - 0.3| = 0.2, threshold = 0.2 → not spike (strict >)
        assert a.feedback_spike_count(threshold=0.2) == 0

    def test_just_above_threshold_is_spike(self):
        a = _make_adapter()
        for score in [0.3, 0.501]:
            _push_feedback(a, score)
        # |0.501 - 0.3| = 0.201 > 0.2
        assert a.feedback_spike_count(threshold=0.2) == 1

    def test_default_threshold_small_changes_no_spike(self):
        a = _make_adapter()
        for score in [0.5, 0.55, 0.58]:
            _push_feedback(a, score)
        # deltas 0.05, 0.03 < default 0.1
        assert a.feedback_spike_count() == 0

    def test_default_threshold_with_spike(self):
        a = _make_adapter()
        for score in [0.3, 0.45]:
            _push_feedback(a, score)
        # |0.45 - 0.3| = 0.15 > 0.1 default
        assert a.feedback_spike_count() == 1

    def test_all_pairs_spike_returns_n_minus_1(self):
        a = _make_adapter()
        scores = [0.0, 1.0, 0.0, 1.0, 0.0]
        for s in scores:
            _push_feedback(a, s)
        assert a.feedback_spike_count(threshold=0.5) == 4

    def test_returns_int(self):
        a = _make_adapter()
        for score in [0.1, 0.9]:
            _push_feedback(a, score)
        result = a.feedback_spike_count(threshold=0.5)
        assert isinstance(result, int)

    def test_zero_threshold_counts_all_changes(self):
        a = _make_adapter()
        for score in [0.4, 0.4, 0.5]:
            _push_feedback(a, score)
        # |0.4 - 0.4| = 0 not > 0; |0.5 - 0.4| = 0.1 > 0
        assert a.feedback_spike_count(threshold=0.0) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# LogicValidator.radius_approx
# ═══════════════════════════════════════════════════════════════════════════════

class TestRadiusApprox:
    def test_empty_graph_returns_zero(self):
        v = _make_validator()
        assert v.radius_approx({"entities": [], "relationships": []}) == 0

    def test_single_node_returns_zero(self):
        v = _make_validator()
        assert v.radius_approx(_ontology(["A"], [])) == 0

    def test_two_nodes_no_edges_returns_zero(self):
        v = _make_validator()
        assert v.radius_approx(_ontology(["A", "B"], [])) == 0

    def test_linear_chain_a_to_b_radius_one(self):
        v = _make_validator()
        # A→B: eccentricities [1, 0]; min positive = 1
        ont = _ontology(["A", "B"], [("A", "B")])
        assert v.radius_approx(ont) == 1

    def test_linear_chain_three_nodes(self):
        v = _make_validator()
        # A→B→C: eccs [2, 1, 0]; min positive = 1
        ont = _ontology(["A", "B", "C"], [("A", "B"), ("B", "C")])
        assert v.radius_approx(ont) == 1

    def test_cycle_two_nodes_radius_one(self):
        v = _make_validator()
        # A→B, B→A: each reaches the other in 1; eccs [1,1]; radius = 1
        ont = _ontology(["A", "B"], [("A", "B"), ("B", "A")])
        assert v.radius_approx(ont) == 1

    def test_three_node_cycle_radius_one(self):
        v = _make_validator()
        # A→B→C→A: each can reach any other in ≤2 steps; eccs all 2; radius = 2
        ont = _ontology(["A", "B", "C"], [("A", "B"), ("B", "C"), ("C", "A")])
        result = v.radius_approx(ont)
        assert result == 2

    def test_star_graph_center_has_low_eccentricity(self):
        v = _make_validator()
        # A→B, A→C, A→D: eccs [1, 0, 0, 0]; min positive = 1
        ont = _ontology(["A", "B", "C", "D"],
                        [("A", "B"), ("A", "C"), ("A", "D")])
        assert v.radius_approx(ont) == 1

    def test_disconnected_graph_ignores_isolated_nodes(self):
        v = _make_validator()
        # A→B (connected), C isolated; eccs: A=1, B=0, C=0; min positive = 1
        ont = _ontology(["A", "B", "C"], [("A", "B")])
        assert v.radius_approx(ont) == 1

    def test_returns_int(self):
        v = _make_validator()
        result = v.radius_approx(_ontology(["A", "B"], [("A", "B")]))
        assert isinstance(result, int)

    def test_two_separate_chains(self):
        v = _make_validator()
        # A→B and C→D→E: eccs: A=1,B=0,C=2,D=1,E=0; min positive = 1
        ont = _ontology(["A", "B", "C", "D", "E"],
                        [("A", "B"), ("C", "D"), ("D", "E")])
        assert v.radius_approx(ont) == 1

    def test_radius_leq_diameter(self):
        v = _make_validator()
        # radius ≤ diameter by definition
        ont = _ontology(["A", "B", "C", "D"],
                        [("A", "B"), ("B", "C"), ("C", "D")])
        radius = v.radius_approx(ont)
        diameter = v.diameter_approx(ont)
        assert radius <= diameter


# ═══════════════════════════════════════════════════════════════════════════════
# Stale smoke tests (methods already existed before Batch 216)
# ═══════════════════════════════════════════════════════════════════════════════

class TestStaleSmokeBatch216:
    def test_score_bimodality_coefficient_callable(self):
        o = _make_optimizer()
        result = o.score_bimodality_coefficient()
        assert isinstance(result, float)

    def test_score_bimodality_coefficient_nonempty(self):
        o = _make_optimizer()
        for s in [0.2, 0.8]:
            _push_opt(o, s)
        result = o.score_bimodality_coefficient()
        assert isinstance(result, float)

    def test_dimension_coefficient_of_variation_callable(self):
        c = _make_critic()
        score = _make_score()
        result = c.dimension_coefficient_of_variation(score)
        assert isinstance(result, float)

    def test_dimension_coefficient_of_variation_uniform(self):
        c = _make_critic()
        score = _make_score(0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
        # All identical → std=0, CV=0
        result = c.dimension_coefficient_of_variation(score)
        assert result == 0.0

    def test_run_score_range_callable(self):
        p = _make_pipeline()
        result = p.run_score_range()
        assert isinstance(result, tuple)

    def test_run_score_range_nonempty(self):
        p = _make_pipeline()
        class _FakeScore:
            def __init__(self, v):
                self.overall = v
        class _FakeRunOverall:
            def __init__(self, v):
                self.score = _FakeScore(v)
        for s in [0.3, 0.7, 0.5]:
            p._run_history.append(_FakeRunOverall(s))
        lo, hi = p.run_score_range()
        assert lo == pytest.approx(0.3)
        assert hi == pytest.approx(0.7)
