"""
Batch 226 — unit tests for five new graphrag optimizer methods.

New methods under test
~~~~~~~~~~~~~~~~~~~~~~
* ``OntologyOptimizer.score_entropy_rate()``
* ``OntologyCritic.score_dimension_max_z(score)``
* ``OntologyLearningAdapter.feedback_plateau_fraction(epsilon)``
* ``OntologyPipeline.run_score_velocity_min()``
* ``LogicValidator.scc_singleton_fraction(ontology)``

Stale (already implemented, verified by smoke test)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* ``OntologyGenerator.entity_confidence_skewness(result)``  (line 6137)
"""

import math
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
# Helpers
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
# Tests: OntologyOptimizer.score_entropy_rate
# ---------------------------------------------------------------------------


class TestScoreEntropyRate:

    def test_empty_returns_zero(self):
        opt = _make_opt()
        assert opt.score_entropy_rate() == 0.0

    def test_single_entry_returns_zero(self):
        opt = _make_opt(0.5)
        assert opt.score_entropy_rate() == 0.0

    def test_two_identical_entries_zero_rate(self):
        # Both entries fall in the same bin → entropy never changes
        opt = _make_opt(0.5, 0.5)
        assert opt.score_entropy_rate() == 0.0

    def test_two_different_bins_positive_rate(self):
        # 0.1 → bin 1; 0.9 → bin 9 — entropy should change
        opt = _make_opt(0.1, 0.9)
        rate = opt.score_entropy_rate()
        assert rate > 0.0

    def test_return_type_is_float(self):
        opt = _make_opt(0.1, 0.5, 0.9)
        assert isinstance(opt.score_entropy_rate(), float)

    def test_non_negative(self):
        # rate is average of absolute differences so always ≥ 0
        opt = _make_opt(0.1, 0.5, 0.3, 0.8, 0.2)
        assert opt.score_entropy_rate() >= 0.0

    def test_more_entries_than_two(self):
        # Just ensure no exception with more entries
        opt = _make_opt(0.1, 0.3, 0.5, 0.7, 0.9, 0.1, 0.3)
        rate = opt.score_entropy_rate()
        assert isinstance(rate, float)
        assert rate >= 0.0

    def test_uniform_across_all_bins_gives_non_negative(self):
        # Scores that span all bins: entropy near maximum; rate should be small
        scores = [i / 10 + 0.05 for i in range(10)] * 2  # 20 entries, 2 each bin
        opt = _make_opt(*scores)
        rate = opt.score_entropy_rate()
        assert rate >= 0.0

    def test_monotone_change_has_positive_rate(self):
        # Scores spread across many bins: entropy increases at each step
        opt = _make_opt(*[i / 20 for i in range(20)])
        rate = opt.score_entropy_rate()
        assert rate > 0.0


# ---------------------------------------------------------------------------
# Tests: OntologyCritic.score_dimension_max_z
# ---------------------------------------------------------------------------


class TestScoreDimensionMaxZ:

    def test_uniform_returns_zero(self):
        critic = _make_critic()
        s = _make_score()  # all dims == 0.5
        assert critic.score_dimension_max_z(s) == 0.0

    def test_one_extreme_value(self):
        # 5 dims at 0.0, one dim at 1.0
        critic = _make_critic()
        s = _make_score(
            completeness=1.0,
            consistency=0.0,
            clarity=0.0,
            granularity=0.0,
            relationship_coherence=0.0,
            domain_alignment=0.0,
        )
        result = critic.score_dimension_max_z(s)
        assert result > 0.0

    def test_return_type_float(self):
        critic = _make_critic()
        s = _make_score(completeness=0.8, consistency=0.2)
        assert isinstance(critic.score_dimension_max_z(s), float)

    def test_non_negative(self):
        critic = _make_critic()
        for _ in range(10):
            s = _make_score(completeness=0.9, consistency=0.1, clarity=0.5)
            assert critic.score_dimension_max_z(s) >= 0.0

    def test_symmetric_values_returns_zero(self):
        # Two dims at 1.0, two at 0.5, two at 0.0 → asymmetric → nonzero
        critic = _make_critic()
        s = _make_score(
            completeness=1.0, consistency=0.0,
            clarity=0.5, granularity=0.5,
            relationship_coherence=1.0, domain_alignment=0.0,
        )
        result = critic.score_dimension_max_z(s)
        assert result > 0.0

    def test_all_zero_dims_returns_zero(self):
        critic = _make_critic()
        s = _make_score(
            completeness=0.0,
            consistency=0.0,
            clarity=0.0,
            granularity=0.0,
            relationship_coherence=0.0,
            domain_alignment=0.0,
        )
        assert critic.score_dimension_max_z(s) == 0.0

    def test_two_extreme_values(self):
        # 0.0 and 1.0 alternating across dims → non-zero result
        critic = _make_critic()
        s = _make_score(
            completeness=0.0, consistency=1.0,
            clarity=0.0, granularity=1.0,
            relationship_coherence=0.0, domain_alignment=1.0,
        )
        result = critic.score_dimension_max_z(s)
        assert result > 0.0

    def test_greater_variance_yields_greater_max_z(self):
        # High variance should produce a higher max-z than low variance
        critic = _make_critic()
        s_low_var = _make_score(completeness=0.4, consistency=0.5, clarity=0.5,
                                granularity=0.5, relationship_coherence=0.6, domain_alignment=0.5)
        s_high_var = _make_score(completeness=0.0, consistency=0.5, clarity=0.5,
                                 granularity=0.5, relationship_coherence=1.0, domain_alignment=0.5)
        assert critic.score_dimension_max_z(s_high_var) >= critic.score_dimension_max_z(s_low_var)


# ---------------------------------------------------------------------------
# Tests: OntologyLearningAdapter.feedback_plateau_fraction
# ---------------------------------------------------------------------------


class TestFeedbackPlateauFraction:

    def test_empty_returns_zero(self):
        adapter = _make_adapter()
        assert adapter.feedback_plateau_fraction() == 0.0

    def test_single_entry_returns_zero(self):
        adapter = _make_adapter()
        _add_feedback(adapter, 0.5)
        assert adapter.feedback_plateau_fraction() == 0.0

    def test_two_identical_entries_all_flat(self):
        adapter = _make_adapter()
        _add_feedback(adapter, 0.5, 0.5)
        assert adapter.feedback_plateau_fraction() == 1.0

    def test_two_different_entries_no_flat(self):
        adapter = _make_adapter()
        _add_feedback(adapter, 0.1, 0.9)
        assert adapter.feedback_plateau_fraction() == 0.0

    def test_half_flat(self):
        # [0.5, 0.5, 0.9, 0.9] → 2 pairs: (0.5,0.5)=flat, (0.5,0.9)=not, (0.9,0.9)=flat
        # = 2 flat / 3 total ≈ 0.667
        adapter = _make_adapter()
        _add_feedback(adapter, 0.5, 0.5, 0.9, 0.9)
        frac = adapter.feedback_plateau_fraction()
        assert abs(frac - 2 / 3) < 1e-9

    def test_return_type_float(self):
        adapter = _make_adapter()
        _add_feedback(adapter, 0.3, 0.5)
        assert isinstance(adapter.feedback_plateau_fraction(), float)

    def test_result_in_zero_one(self):
        adapter = _make_adapter()
        _add_feedback(adapter, 0.5, 0.5, 0.5, 0.9)
        frac = adapter.feedback_plateau_fraction()
        assert 0.0 <= frac <= 1.0

    def test_all_flat_returns_one(self):
        adapter = _make_adapter()
        _add_feedback(adapter, 0.6, 0.6, 0.6, 0.6)
        assert adapter.feedback_plateau_fraction() == 1.0

    def test_no_flat_returns_zero(self):
        adapter = _make_adapter()
        _add_feedback(adapter, 0.1, 0.5, 0.9, 0.3, 0.7)
        frac = adapter.feedback_plateau_fraction()
        assert frac == 0.0

    def test_custom_epsilon(self):
        adapter = _make_adapter()
        # |0.5 - 0.45| = 0.05 > 0.01 but <= 0.1
        _add_feedback(adapter, 0.5, 0.45)
        assert adapter.feedback_plateau_fraction(epsilon=0.01) == 0.0
        assert adapter.feedback_plateau_fraction(epsilon=0.1) == 1.0

    def test_consistency_with_plateau_count(self):
        adapter = _make_adapter()
        _add_feedback(adapter, 0.5, 0.5, 0.5, 0.9, 0.9)
        n = len(adapter._feedback)
        count = adapter.feedback_plateau_count()
        frac = adapter.feedback_plateau_fraction()
        assert abs(frac - count / (n - 1)) < 1e-9


# ---------------------------------------------------------------------------
# Tests: OntologyPipeline.run_score_velocity_min
# ---------------------------------------------------------------------------


class TestRunScoreVelocityMin:

    def test_empty_returns_zero(self):
        p = _make_pipeline([])
        assert p.run_score_velocity_min() == 0.0

    def test_single_run_returns_zero(self):
        p = _make_pipeline([0.5])
        assert p.run_score_velocity_min() == 0.0

    def test_two_runs_increasing(self):
        p = _make_pipeline([0.3, 0.7])
        assert p.run_score_velocity_min() == pytest.approx(0.4)

    def test_two_runs_decreasing(self):
        p = _make_pipeline([0.7, 0.3])
        assert p.run_score_velocity_min() == pytest.approx(-0.4)

    def test_monotone_increase_min_is_first_diff(self):
        # Increasing by 0.1, 0.2, 0.3 → min is 0.1
        p = _make_pipeline([0.1, 0.2, 0.4, 0.7])
        assert p.run_score_velocity_min() == pytest.approx(0.1)

    def test_mixed_min_is_most_negative(self):
        p = _make_pipeline([0.5, 0.8, 0.2, 0.9])
        # diffs: 0.3, -0.6, 0.7 → min = -0.6
        assert p.run_score_velocity_min() == pytest.approx(-0.6)

    def test_return_type_float(self):
        p = _make_pipeline([0.2, 0.8])
        assert isinstance(p.run_score_velocity_min(), float)

    def test_velocity_min_leq_velocity_max(self):
        from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline

        p = _make_pipeline([0.1, 0.9, 0.3, 0.7, 0.5])
        assert p.run_score_velocity_min() <= p.run_score_velocity_max()

    def test_uniform_scores_min_is_zero(self):
        p = _make_pipeline([0.5, 0.5, 0.5, 0.5])
        assert p.run_score_velocity_min() == pytest.approx(0.0)

    def test_three_runs_all_declining(self):
        p = _make_pipeline([0.9, 0.6, 0.3])
        # diffs: -0.3, -0.3 → min = -0.3
        assert p.run_score_velocity_min() == pytest.approx(-0.3)


# ---------------------------------------------------------------------------
# Tests: LogicValidator.scc_singleton_fraction
# ---------------------------------------------------------------------------


class TestSccSingletonFraction:

    def test_empty_graph_returns_zero(self):
        lv = _make_lv()
        ont = _make_ont([], [])
        assert lv.scc_singleton_fraction(ont) == 0.0

    def test_single_node_no_edges_is_singleton(self):
        # One node, no edges → one SCC of size 1 → fraction = 1.0
        lv = _make_lv()
        ont = _make_ont(["A"], [])
        assert lv.scc_singleton_fraction(ont) == 1.0

    def test_two_nodes_no_edges_all_singletons(self):
        lv = _make_lv()
        ont = _make_ont(["A", "B"], [])
        assert lv.scc_singleton_fraction(ont) == 1.0

    def test_chain_all_singletons(self):
        # A→B→C: no back edges → 3 singleton SCCs
        lv = _make_lv()
        ont = _make_ont(["A", "B", "C"], [("A", "B"), ("B", "C")])
        assert lv.scc_singleton_fraction(ont) == 1.0

    def test_cycle_no_singletons(self):
        # A→B→C→A: one SCC of size 3 → fraction = 0.0
        lv = _make_lv()
        ont = _make_ont(["A", "B", "C"], [("A", "B"), ("B", "C"), ("C", "A")])
        assert lv.scc_singleton_fraction(ont) == 0.0

    def test_mixed_one_singleton_one_scc(self):
        # A→B→A (cycle): one SCC of size 2
        # C (isolated): one SCC of size 1
        # 1 singleton out of 2 SCCs → fraction = 0.5
        lv = _make_lv()
        ont = _make_ont(["A", "B", "C"], [("A", "B"), ("B", "A")])
        frac = lv.scc_singleton_fraction(ont)
        assert abs(frac - 0.5) < 1e-9

    def test_return_type_float(self):
        lv = _make_lv()
        ont = _make_ont(["A", "B"], [("A", "B")])
        assert isinstance(lv.scc_singleton_fraction(ont), float)

    def test_in_zero_one_range(self):
        lv = _make_lv()
        ont = _make_ont(["A", "B", "C", "D"], [("A", "B"), ("B", "C"), ("C", "A")])
        frac = lv.scc_singleton_fraction(ont)
        assert 0.0 <= frac <= 1.0

    def test_star_graph_all_singletons(self):
        # Hub→spoke1, Hub→spoke2, Hub→spoke3 → 4 singletons (no cycles)
        lv = _make_lv()
        ont = _make_ont(
            ["H", "S1", "S2", "S3"],
            [("H", "S1"), ("H", "S2"), ("H", "S3")],
        )
        assert lv.scc_singleton_fraction(ont) == 1.0

    def test_dag_returns_one(self):
        # Pure DAG: every SCC is a singleton
        lv = _make_lv()
        ont = _make_ont(
            ["A", "B", "C", "D"],
            [("A", "B"), ("A", "C"), ("B", "D"), ("C", "D")],
        )
        assert lv.scc_singleton_fraction(ont) == 1.0


# ---------------------------------------------------------------------------
# Stale smoke tests: OntologyGenerator.entity_confidence_skewness
# ---------------------------------------------------------------------------


class TestEntityConfidenceSkewness_Stale:
    """entity_confidence_skewness already exists at line 6137; verify it works."""

    def test_empty_result_returns_zero(self):
        gen = _make_gen()
        result = _make_result(entities=[])
        assert gen.entity_confidence_skewness(result) == 0.0

    def test_fewer_than_three_entities_returns_zero(self):
        gen = _make_gen()
        result = _make_result(entities=[_make_entity("A", 0.3), _make_entity("B", 0.7)])
        assert gen.entity_confidence_skewness(result) == 0.0

    def test_uniform_confidence_returns_zero(self):
        gen = _make_gen()
        ents = [_make_entity(f"e{i}", 0.5) for i in range(5)]
        result = _make_result(entities=ents)
        assert gen.entity_confidence_skewness(result) == 0.0

    def test_skewed_distribution_nonzero(self):
        gen = _make_gen()
        # Right-skewed: most scores low, one high
        ents = [
            _make_entity("a", 0.1),
            _make_entity("b", 0.1),
            _make_entity("c", 0.1),
            _make_entity("d", 0.9),
        ]
        result = _make_result(entities=ents)
        skew = gen.entity_confidence_skewness(result)
        assert isinstance(skew, float)
        assert skew != 0.0
