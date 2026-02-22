"""Batch 220 feature tests.

New methods:
  * OntologyLearningAdapter.feedback_iqr_ratio()
  * LogicValidator.sink_count()

Stale smoke tests (already implemented in source, now formally exercised):
  * OntologyOptimizer.score_geometric_mean()
  * OntologyCritic.dimension_max(score)
  * OntologyGenerator.entity_confidence_sum(result)
  * OntologyPipeline.run_score_geometric_mean()
"""
import math
import types
import pytest


# ---------------------------------------------------------------------------
# Lightweight stubs to avoid heavy import chain
# ---------------------------------------------------------------------------

def _make_adapter(scores):
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    class _FR:
        def __init__(self, s):
            self.final_score = s
    la = object.__new__(OntologyLearningAdapter)
    la._feedback = [_FR(s) for s in scores]
    return la


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


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return object.__new__(LogicValidator)


def _make_optimizer(scores):
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    class _E:
        def __init__(self, v):
            self.average_score = v
    o = object.__new__(OntologyOptimizer)
    o._history = [_E(v) for v in scores]
    return o


def _make_critic_score(completeness=0.5, consistency=0.5, clarity=0.5,
                       granularity=0.5, relationship_coherence=0.5,
                       domain_alignment=0.5):
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
    return CriticScore(
        completeness=completeness,
        consistency=consistency,
        clarity=clarity,
        granularity=granularity,
        relationship_coherence=relationship_coherence,
        domain_alignment=domain_alignment,
    )


def _make_entity(confidence):
    class _Ent:
        def __init__(self, c):
            self.confidence = c
            self.id = "e"
            self.name = "n"
            self.entity_type = "t"
            self.text = ""
            self.properties = {}
    return _Ent(confidence)


def _make_extraction_result(entity_confidences):
    class _R:
        def __init__(self, ents):
            self.entities = ents
            self.relationships = []
            self.confidence = 1.0
    return _R([_make_entity(c) for c in entity_confidences])


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


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_iqr_ratio
# ---------------------------------------------------------------------------

class TestFeedbackIqrRatio:
    def test_empty_returns_zero(self):
        la = _make_adapter([])
        assert la.feedback_iqr_ratio() == 0.0

    def test_fewer_than_four_returns_zero(self):
        for n in range(1, 4):
            la = _make_adapter([0.5] * n)
            assert la.feedback_iqr_ratio() == 0.0

    def test_uniform_iqr_zero_returns_zero(self):
        # IQR == 0 when all equal → ratio is 0
        la = _make_adapter([0.4, 0.4, 0.4, 0.4])
        assert la.feedback_iqr_ratio() == 0.0

    def test_formula_four_entries(self):
        # sorted [0.2, 0.4, 0.6, 0.8]
        # q1 = scores[1] = 0.4, q3 = scores[3] = 0.8  → IQR = 0.4
        # mean = (0.2+0.4+0.6+0.8)/4 = 0.5
        # ratio = 0.4 / 0.5 = 0.8
        la = _make_adapter([0.8, 0.2, 0.6, 0.4])
        result = la.feedback_iqr_ratio()
        assert abs(result - 0.8) < 1e-9

    def test_zero_mean_returns_zero(self):
        # All zeros: mean == 0 → guard kicks in
        la = _make_adapter([0.0, 0.0, 0.0, 0.0])
        assert la.feedback_iqr_ratio() == 0.0

    def test_returns_float(self):
        la = _make_adapter([0.1, 0.3, 0.5, 0.7, 0.9])
        assert isinstance(la.feedback_iqr_ratio(), float)

    def test_result_non_negative(self):
        la = _make_adapter([0.1, 0.2, 0.8, 0.9])
        assert la.feedback_iqr_ratio() >= 0.0

    def test_larger_spread_gives_larger_ratio(self):
        # narrow spread
        la_narrow = _make_adapter([0.45, 0.48, 0.52, 0.55])
        # wide spread
        la_wide = _make_adapter([0.1, 0.3, 0.7, 0.9])
        assert la_wide.feedback_iqr_ratio() > la_narrow.feedback_iqr_ratio()

    def test_five_entries(self):
        # sorted [0.1, 0.2, 0.5, 0.8, 0.9]
        # n=5, q1=scores[1]=0.2, q3=scores[3]=0.8 → IQR=0.6
        # mean = (0.1+0.2+0.5+0.8+0.9)/5 = 0.5
        # ratio = 0.6 / 0.5 = 1.2
        la = _make_adapter([0.1, 0.9, 0.5, 0.2, 0.8])
        result = la.feedback_iqr_ratio()
        assert abs(result - 1.2) < 1e-9

    def test_symmetric_uniform_distribution(self):
        # [0, 1, 2, ..., 9] / 9
        import random
        scores = [i / 9.0 for i in range(10)]
        la = _make_adapter(scores)
        r = la.feedback_iqr_ratio()
        assert r > 0.0

    def test_ratio_consistent_with_components(self):
        scores = [0.1, 0.3, 0.5, 0.7, 0.9, 1.0]
        la = _make_adapter(scores)
        iqr = la.feedback_iqr()
        mean = sum(scores) / len(scores)
        expected = iqr / mean if (iqr > 0 and mean > 0) else 0.0
        assert abs(la.feedback_iqr_ratio() - expected) < 1e-9


# ---------------------------------------------------------------------------
# LogicValidator.sink_count
# ---------------------------------------------------------------------------

class TestSinkCount:
    def test_empty_returns_zero(self):
        v = _make_validator()
        ont = _make_ontology([], [])
        assert v.sink_count(ont) == 0

    def test_single_node_no_edges(self):
        v = _make_validator()
        ont = _make_ontology(["A"], [])
        # A has no outgoing edges → it is a sink
        assert v.sink_count(ont) == 1

    def test_two_nodes_no_edges(self):
        v = _make_validator()
        ont = _make_ontology(["A", "B"], [])
        assert v.sink_count(ont) == 2

    def test_chain_one_sink(self):
        # A → B → C : only C has no outgoing edge
        v = _make_validator()
        ont = _make_ontology(["A", "B", "C"], [("A", "B"), ("B", "C")])
        assert v.sink_count(ont) == 1

    def test_star_one_source_multiple_sinks(self):
        # A → B, A → C, A → D : A has out-degree 3; B, C, D are sinks
        v = _make_validator()
        ont = _make_ontology(["A", "B", "C", "D"], [("A", "B"), ("A", "C"), ("A", "D")])
        assert v.sink_count(ont) == 3

    def test_cycle_no_sinks(self):
        # A → B → C → A : all nodes have out-degree 1 → no sinks
        v = _make_validator()
        ont = _make_ontology(["A", "B", "C"], [("A", "B"), ("B", "C"), ("C", "A")])
        assert v.sink_count(ont) == 0

    def test_two_chains_two_sinks(self):
        # A → B, C → D : B and D are sinks
        v = _make_validator()
        ont = _make_ontology(["A", "B", "C", "D"], [("A", "B"), ("C", "D")])
        assert v.sink_count(ont) == 2

    def test_returns_int(self):
        v = _make_validator()
        ont = _make_ontology(["A", "B"], [("A", "B")])
        assert isinstance(v.sink_count(ont), int)

    def test_sink_plus_source_leq_nodes(self):
        # sink_count + source_count <= n always holds
        v = _make_validator()
        ont = _make_ontology(["A", "B", "C", "D"], [("A", "B"), ("B", "C"), ("A", "D")])
        n = len(["A", "B", "C", "D"])
        assert v.sink_count(ont) + v.source_count(ont) <= n

    def test_dict_style_ontology(self):
        # dict-style ontology with source/target keys
        ont = {
            "entities": [{"id": "X"}, {"id": "Y"}, {"id": "Z"}],
            "relationships": [{"source_id": "X", "target_id": "Y"},
                               {"source_id": "X", "target_id": "Z"}],
        }
        v = _make_validator()
        assert v.sink_count(ont) == 2  # Y and Z are sinks

    def test_fully_connected_bidirectional_no_sinks(self):
        # A→B and B→A: both have outgoing edges → no sinks
        v = _make_validator()
        ont = _make_ontology(["A", "B"], [("A", "B"), ("B", "A")])
        assert v.sink_count(ont) == 0

    def test_symmetric_with_source_count(self):
        # In a DAG with one source and one sink, source_count ≥ 1 and sink_count ≥ 1
        v = _make_validator()
        # A → B → C
        ont = _make_ontology(["A", "B", "C"], [("A", "B"), ("B", "C")])
        assert v.source_count(ont) == 1
        assert v.sink_count(ont) == 1

    def test_geq_zero_large_graph(self):
        ids = [str(i) for i in range(10)]
        rels = [(str(i), str(i + 1)) for i in range(9)]
        v = _make_validator()
        ont = _make_ontology(ids, rels)
        assert v.sink_count(ont) >= 0


# ---------------------------------------------------------------------------
# Stale smoke tests — methods that already exist in source
# ---------------------------------------------------------------------------

class TestStaleSmoke:
    # OntologyOptimizer.score_geometric_mean
    def test_score_geometric_mean_empty(self):
        o = _make_optimizer([])
        assert o.score_geometric_mean() == 0.0

    def test_score_geometric_mean_two_values(self):
        # geometric mean of 0.25 and 1.0 == sqrt(0.25) == 0.5
        o = _make_optimizer([0.25, 1.0])
        result = o.score_geometric_mean()
        assert abs(result - 0.5) < 1e-9

    # OntologyCritic.dimension_max
    def test_dimension_max_returns_highest_dim(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        critic = object.__new__(OntologyCritic)
        score = _make_critic_score(completeness=0.9, consistency=0.3)
        result = critic.dimension_max(score)
        assert result == "completeness"

    def test_dimension_max_returns_string(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
        critic = object.__new__(OntologyCritic)
        score = _make_critic_score()
        assert isinstance(critic.dimension_max(score), str)

    # OntologyGenerator.entity_confidence_sum
    def test_entity_confidence_sum_empty(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
        gen = object.__new__(OntologyGenerator)
        result = gen.entity_confidence_sum(_make_extraction_result([]))
        assert result == 0.0

    def test_entity_confidence_sum_values(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
        gen = object.__new__(OntologyGenerator)
        result = gen.entity_confidence_sum(_make_extraction_result([0.3, 0.4, 0.5]))
        assert abs(result - 1.2) < 1e-9

    # OntologyPipeline.run_score_geometric_mean
    def test_run_score_geometric_mean_empty(self):
        p = _make_pipeline([])
        assert p.run_score_geometric_mean() == 0.0

    def test_run_score_geometric_mean_two_values(self):
        # geometric mean of 0.25 and 1.0 == 0.5
        p = _make_pipeline([0.25, 1.0])
        result = p.run_score_geometric_mean()
        assert abs(result - 0.5) < 1e-9
