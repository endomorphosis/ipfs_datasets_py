"""
Batch 227 — unit tests for four new graphrag optimizer methods.

New methods under test
~~~~~~~~~~~~~~~~~~~~~~
* ``OntologyOptimizer.score_valley_density()``
* ``OntologyCritic.score_dimension_min_z(score)``
* ``OntologyPipeline.run_score_velocity_range()``
* ``LogicValidator.scc_non_singleton_fraction(ontology)``

Stale (already implemented, verified by smoke test)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* ``OntologyGenerator.relationship_type_entropy(result)``  (line 7547)
* ``OntologyLearningAdapter.feedback_above_mean_count()``  (line 1513)
"""

import sys
import types

import pytest

# ---------------------------------------------------------------------------
# Minimal module stubs so heavy optional deps don't block import
# ---------------------------------------------------------------------------
for _mod in ("torch", "transformers"):
    if _mod not in sys.modules:
        sys.modules[_mod] = types.ModuleType(_mod)

from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer  # noqa: E402
from ipfs_datasets_py.optimizers.graphrag.ontology_critic import (  # noqa: E402
    OntologyCritic,
    CriticScore,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_generator import (  # noqa: E402
    OntologyGenerator,
    Entity,
    Relationship,
    EntityExtractionResult,
)
from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import (  # noqa: E402
    OntologyLearningAdapter,
)
from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers shared across test classes
# ---------------------------------------------------------------------------


class _FakeEntry:
    """Minimal history entry with average_score."""

    def __init__(self, s: float) -> None:
        self.average_score = s


def _make_opt(*scores):
    """Build OntologyOptimizer bypassing __init__ with given history."""
    opt = object.__new__(OntologyOptimizer)
    opt._history = [_FakeEntry(s) for s in scores]
    return opt


def _make_score(**kwargs):
    defaults = dict(
        completeness=0.5,
        consistency=0.5,
        clarity=0.5,
        granularity=0.5,
        relationship_coherence=0.5,
        domain_alignment=0.5,
    )
    defaults.update(kwargs)
    return CriticScore(**defaults)


def _make_critic():
    return object.__new__(OntologyCritic)


def _make_entity(eid, confidence=0.7):
    return Entity(id=eid, text=eid, type="test", confidence=confidence)


def _make_result(entities=None, relationships=None):
    ents = entities or []
    rels = relationships or []
    return EntityExtractionResult(
        entities=ents,
        relationships=rels,
        confidence=sum(e.confidence for e in ents) / len(ents) if ents else 0.0,
    )


def _make_gen():
    return object.__new__(OntologyGenerator)


def _make_adapter():
    adapter = object.__new__(OntologyLearningAdapter)
    adapter._feedback = []
    return adapter


def _add_feedback(adapter, *scores):
    class _FbRecord:
        def __init__(self, s):
            self.final_score = s
            self.actions = {}

    for s in scores:
        adapter._feedback.append(_FbRecord(s))


def _make_pipeline(scores):
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline

    class _FakeScore2:
        def __init__(self, v):
            self.overall = v

    class _FakeRun:
        def __init__(self, v):
            self.score = _FakeScore2(v)

    p = object.__new__(OntologyPipeline)
    p._run_history = [_FakeRun(s) for s in scores]
    return p


def _make_lv():
    return object.__new__(LogicValidator)


def _make_ont(nodes, edges):
    """Build a dict-style ontology with node IDs and (src, tgt) edges."""
    return {
        "entities": [{"id": n} for n in nodes],
        "relationships": [{"source_id": s, "target_id": t} for s, t in edges],
    }


# ---------------------------------------------------------------------------
# Tests: OntologyOptimizer.score_valley_density
# ---------------------------------------------------------------------------


class TestScoreValleyDensity:

    def test_empty_returns_zero(self):
        opt = _make_opt()
        assert opt.score_valley_density() == 0.0

    def test_single_entry_returns_zero(self):
        # mean == only value; nothing is strictly below
        opt = _make_opt(0.5)
        assert opt.score_valley_density() == 0.0

    def test_uniform_scores_no_valleys(self):
        # all scores equal mean → none strictly below
        opt = _make_opt(0.5, 0.5, 0.5, 0.5)
        assert opt.score_valley_density() == 0.0

    def test_one_below_mean(self):
        # scores [0.0, 0.5, 1.0] → mean=0.5; 1 of 3 strictly below
        opt = _make_opt(0.0, 0.5, 1.0)
        density = opt.score_valley_density()
        assert abs(density - 1 / 3) < 1e-9

    def test_two_below_mean(self):
        # scores [0.1, 0.2, 0.9, 1.0] → mean=0.55; 0.1 and 0.2 are below
        opt = _make_opt(0.1, 0.2, 0.9, 1.0)
        density = opt.score_valley_density()
        assert abs(density - 0.5) < 1e-9

    def test_all_below_except_one(self):
        # [0.0, 0.0, 0.0, 1.0] → mean=0.25; three are below 0.25
        opt = _make_opt(0.0, 0.0, 0.0, 1.0)
        density = opt.score_valley_density()
        assert abs(density - 0.75) < 1e-9

    def test_strictly_increasing(self):
        # [0.1, 0.3, 0.7, 0.9] → mean=0.5; first two (0.1, 0.3) below
        opt = _make_opt(0.1, 0.3, 0.7, 0.9)
        density = opt.score_valley_density()
        assert abs(density - 0.5) < 1e-9

    def test_result_in_unit_interval(self):
        import random
        rng = random.Random(42)
        scores = [rng.random() for _ in range(20)]
        opt = _make_opt(*scores)
        d = opt.score_valley_density()
        assert 0.0 <= d <= 1.0

    def test_returns_float(self):
        opt = _make_opt(0.2, 0.8)
        assert isinstance(opt.score_valley_density(), float)

    def test_two_entries_one_below(self):
        # [0.3, 0.7] → mean=0.5; only 0.3 is strictly below
        opt = _make_opt(0.3, 0.7)
        density = opt.score_valley_density()
        assert abs(density - 0.5) < 1e-9


# ---------------------------------------------------------------------------
# Tests: OntologyCritic.score_dimension_min_z
# ---------------------------------------------------------------------------


class TestScoreDimensionMinZ:

    def test_uniform_returns_zero(self):
        critic = _make_critic()
        s = _make_score()  # all dims=0.5
        assert critic.score_dimension_min_z(s) == 0.0

    def test_all_zero_returns_zero(self):
        critic = _make_critic()
        s = _make_score(
            completeness=0.0, consistency=0.0, clarity=0.0,
            granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0,
        )
        assert critic.score_dimension_min_z(s) == 0.0

    def test_one_outlier_min_is_zero(self):
        # 4 dims at 0.5 (exactly at the mean) + one at 0.0 + one at 1.0
        # mean = (0.0 + 0.5*4 + 1.0)/6 = 0.5; the 4 values at 0.5 have z=0
        critic = _make_critic()
        s = _make_score(
            completeness=0.0, consistency=0.5, clarity=0.5,
            granularity=0.5, relationship_coherence=0.5, domain_alignment=1.0,
        )
        min_z = critic.score_dimension_min_z(s)
        assert min_z == 0.0

    def test_two_distinct_values_min_less_than_max(self):
        # Two groups of values — min_z must be less than max_z
        critic = _make_critic()
        s = _make_score(
            completeness=1.0, consistency=1.0, clarity=1.0,
            granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0,
        )
        min_z = critic.score_dimension_min_z(s)
        max_z = critic.score_dimension_max_z(s)
        assert min_z <= max_z

    def test_min_z_non_negative(self):
        critic = _make_critic()
        s = _make_score(completeness=0.9, consistency=0.1)
        assert critic.score_dimension_min_z(s) >= 0.0

    def test_symmetric_score_min_z_equals_max_z(self):
        # Two groups of 3 equal values each: all |z| values are equal
        critic = _make_critic()
        s = _make_score(
            completeness=1.0, consistency=1.0, clarity=1.0,
            granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0,
        )
        min_z = critic.score_dimension_min_z(s)
        max_z = critic.score_dimension_max_z(s)
        assert abs(min_z - max_z) < 1e-9

    def test_returns_float(self):
        critic = _make_critic()
        s = _make_score()
        assert isinstance(critic.score_dimension_min_z(s), float)

    def test_small_perturbation_min_less_than_max(self):
        # One outlier among 6 dims — min_z (closest to mean) < max_z (furthest)
        critic = _make_critic()
        s = _make_score(
            completeness=1.0, consistency=0.0, clarity=0.0,
            granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0,
        )
        assert critic.score_dimension_min_z(s) < critic.score_dimension_max_z(s)


# ---------------------------------------------------------------------------
# Tests: OntologyPipeline.run_score_velocity_range
# ---------------------------------------------------------------------------


class TestRunScoreVelocityRange:

    def test_empty_returns_zero(self):
        p = _make_pipeline([])
        assert p.run_score_velocity_range() == 0.0

    def test_single_run_returns_zero(self):
        p = _make_pipeline([0.5])
        assert p.run_score_velocity_range() == 0.0

    def test_two_runs_range_is_zero(self):
        # only one fd value → max == min → range == 0
        p = _make_pipeline([0.3, 0.7])
        assert p.run_score_velocity_range() == 0.0

    def test_three_runs_constant_velocity_range_zero(self):
        # fd = [0.2, 0.2] → range = 0
        p = _make_pipeline([0.2, 0.4, 0.6])
        assert abs(p.run_score_velocity_range()) < 1e-9

    def test_range_equals_max_minus_min(self):
        # fd = [0.1, 0.3, -0.2] → max=0.3, min=-0.2, range=0.5
        p = _make_pipeline([0.1, 0.2, 0.5, 0.3])
        vr = p.run_score_velocity_range()
        expected = p.run_score_velocity_max() - p.run_score_velocity_min()
        assert abs(vr - expected) < 1e-9

    def test_range_non_negative(self):
        import random
        rng = random.Random(7)
        scores = [rng.random() for _ in range(8)]
        p = _make_pipeline(scores)
        assert p.run_score_velocity_range() >= 0.0

    def test_all_same_scores_range_zero(self):
        p = _make_pipeline([0.5, 0.5, 0.5, 0.5])
        assert p.run_score_velocity_range() == 0.0

    def test_monotone_increasing_range_zero(self):
        # Constant step of 0.2 → all fd equal → range = 0
        p = _make_pipeline([0.1, 0.3, 0.5, 0.7, 0.9])
        assert abs(p.run_score_velocity_range()) < 1e-9

    def test_returns_float(self):
        p = _make_pipeline([0.2, 0.5, 0.3])
        assert isinstance(p.run_score_velocity_range(), float)

    def test_large_range(self):
        # fd = [0.9, -0.8] → range = 1.7
        p = _make_pipeline([0.0, 0.9, 0.1])
        vr = p.run_score_velocity_range()
        assert abs(vr - 1.7) < 1e-9


# ---------------------------------------------------------------------------
# Tests: LogicValidator.scc_non_singleton_fraction
# ---------------------------------------------------------------------------


class TestSCCNonSingletonFraction:

    def test_empty_returns_zero(self):
        lv = _make_lv()
        ont = _make_ont([], [])
        assert lv.scc_non_singleton_fraction(ont) == 0.0

    def test_single_node_no_edges_all_singletons(self):
        # One SCC of size 1 → scc_singleton_fraction=1.0 → non=0.0
        lv = _make_lv()
        ont = _make_ont(["A"], [])
        assert lv.scc_non_singleton_fraction(ont) == 0.0

    def test_dag_all_singletons_non_zero(self):
        # A→B→C, no cycles → every SCC is singleton → non=0.0
        lv = _make_lv()
        ont = _make_ont(["A", "B", "C"], [("A", "B"), ("B", "C")])
        assert lv.scc_non_singleton_fraction(ont) == 0.0

    def test_simple_cycle_all_non_singleton(self):
        # A→B→C→A — all in one SCC of size 3; 0 singletons → non=1.0
        lv = _make_lv()
        ont = _make_ont(["A", "B", "C"], [("A", "B"), ("B", "C"), ("C", "A")])
        nsf = lv.scc_non_singleton_fraction(ont)
        assert nsf == 1.0

    def test_complement_identity(self):
        # For non-empty graphs: singleton + non_singleton == 1.0
        lv = _make_lv()
        ont = _make_ont(["A", "B", "C"], [("A", "B"), ("B", "C")])
        sf = lv.scc_singleton_fraction(ont)
        nsf = lv.scc_non_singleton_fraction(ont)
        assert abs(sf + nsf - 1.0) < 1e-9

    def test_mixed_graph_complement(self):
        # Two-cycle A↔B and isolated C → SCCs: {A,B}, {C} → 1 singleton, 1 non
        lv = _make_lv()
        ont = _make_ont(["A", "B", "C"], [("A", "B"), ("B", "A")])
        sf = lv.scc_singleton_fraction(ont)
        nsf = lv.scc_non_singleton_fraction(ont)
        assert abs(sf + nsf - 1.0) < 1e-9
        assert nsf > 0.0

    def test_returns_float(self):
        lv = _make_lv()
        ont = _make_ont(["A"], [])
        assert isinstance(lv.scc_non_singleton_fraction(ont), float)

    def test_result_in_unit_interval(self):
        lv = _make_lv()
        ont = _make_ont(
            ["A", "B", "C", "D"],
            [("A", "B"), ("B", "C"), ("C", "A"), ("D", "A")],
        )
        nsf = lv.scc_non_singleton_fraction(ont)
        assert 0.0 <= nsf <= 1.0

    def test_pure_cycle_non_fraction_is_one(self):
        lv = _make_lv()
        ont = _make_ont(["X", "Y"], [("X", "Y"), ("Y", "X")])
        assert lv.scc_non_singleton_fraction(ont) == 1.0


# ---------------------------------------------------------------------------
# Stale smoke tests — verify pre-existing methods still work
# ---------------------------------------------------------------------------


class TestStaleRelationshipTypeEntropy:
    """relationship_type_entropy already existed at line 7547 of ontology_generator.py."""

    def test_empty_result_returns_zero(self):
        gen = _make_gen()
        result = _make_result()
        val = gen.relationship_type_entropy(result)
        assert isinstance(val, float)
        assert val == 0.0

    def test_single_type_zero_entropy(self):
        gen = _make_gen()
        rels = [
            Relationship(id="r1", source_id="A", target_id="B", type="likes", confidence=0.9),
            Relationship(id="r2", source_id="B", target_id="C", type="likes", confidence=0.8),
        ]
        result = _make_result(relationships=rels)
        val = gen.relationship_type_entropy(result)
        assert isinstance(val, float)
        assert val == 0.0


class TestStaleFeedbackAboveMeanCount:
    """feedback_above_mean_count already existed at line 1513 of ontology_learning_adapter.py."""

    def test_empty_feedback_returns_zero(self):
        adapter = _make_adapter()
        val = adapter.feedback_above_mean_count()
        assert isinstance(val, int)
        assert val == 0

    def test_uniform_none_above_mean(self):
        adapter = _make_adapter()
        _add_feedback(adapter, 0.5, 0.5, 0.5)
        val = adapter.feedback_above_mean_count()
        assert isinstance(val, int)
        assert val == 0
