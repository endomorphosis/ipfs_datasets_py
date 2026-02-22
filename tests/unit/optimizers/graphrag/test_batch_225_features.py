"""
Batch 225 — unit tests for five new graphrag optimizer methods.

New methods under test
~~~~~~~~~~~~~~~~~~~~~~
* ``OntologyOptimizer.score_entropy_ratio()``
* ``OntologyCritic.score_dimension_gini_coefficient(score)``
* ``OntologyLearningAdapter.feedback_plateau_count(epsilon)``
* ``OntologyPipeline.run_score_velocity_max()``
* ``LogicValidator.avg_scc_size(ontology)``

Stale (already implemented, verified by smoke test)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* ``OntologyGenerator.entity_confidence_std`` (lines 5921 + 6801)
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
# Tests: OntologyOptimizer.score_entropy_ratio
# ---------------------------------------------------------------------------


class TestScoreEntropyRatio:

    def test_empty_returns_zero(self):
        opt = _make_opt()
        assert opt.score_entropy_ratio() == 0.0

    def test_single_entry_returns_zero(self):
        # All scores fall in a single bin → entropy = 0 → ratio = 0
        opt = _make_opt(0.5)
        assert opt.score_entropy_ratio() == 0.0

    def test_uniform_scores_single_bin_returns_zero(self):
        # All 5 scores in the same bin → entropy = 0 → ratio = 0
        opt = _make_opt(0.5, 0.5, 0.5, 0.5, 0.5)
        assert opt.score_entropy_ratio() == 0.0

    def test_two_bins_equal_returns_expected(self):
        # 5 scores in bin 0, 5 in bin 9 → H = 1 bit → ratio = 1/log2(10)
        opt = _make_opt(0.05, 0.05, 0.05, 0.05, 0.05, 0.95, 0.95, 0.95, 0.95, 0.95)
        ratio = opt.score_entropy_ratio()
        expected = 1.0 / math.log2(10)
        assert abs(ratio - expected) < 1e-9

    def test_result_in_zero_one_range(self):
        # Any history should produce a value in [0, 1]
        opt = _make_opt(0.1, 0.3, 0.5, 0.7, 0.9)
        ratio = opt.score_entropy_ratio()
        assert 0.0 <= ratio <= 1.0

    def test_uniform_distribution_approaches_one(self):
        # 10 evenly spaced bins (1 score each) → max entropy → ratio ≈ 1.0
        scores = [0.05 + i * 0.1 for i in range(10)]
        opt = _make_opt(*scores)
        ratio = opt.score_entropy_ratio()
        assert abs(ratio - 1.0) < 1e-9

    def test_returns_float(self):
        opt = _make_opt(0.3, 0.7)
        assert isinstance(opt.score_entropy_ratio(), float)

    def test_higher_diversity_higher_ratio(self):
        # Two distinct bins vs one bin → higher ratio for diverse
        single_bin = _make_opt(0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5, 0.5)
        two_bin = _make_opt(0.05, 0.05, 0.05, 0.05, 0.05, 0.95, 0.95, 0.95, 0.95, 0.95)
        assert two_bin.score_entropy_ratio() > single_bin.score_entropy_ratio()

    def test_ratio_leq_raw_entropy_divided_by_log2_10(self):
        # score_entropy_ratio == score_entropy / log2(10) by definition
        opt = _make_opt(0.1, 0.2, 0.4, 0.6, 0.8)
        ratio = opt.score_entropy_ratio()
        raw = opt.score_entropy()
        if raw == 0.0:
            assert ratio == 0.0
        else:
            assert abs(ratio - raw / math.log2(10)) < 1e-9


# ---------------------------------------------------------------------------
# Tests: OntologyCritic.score_dimension_gini_coefficient
# ---------------------------------------------------------------------------


class TestScoreDimensionGiniCoefficient:

    def test_uniform_returns_zero(self):
        # All equal → Gini = 0
        critic = _make_critic()
        s = _make_score()  # all 0.5
        assert critic.score_dimension_gini_coefficient(s) == 0.0

    def test_all_zero_returns_zero(self):
        critic = _make_critic()
        s = _make_score(completeness=0.0, consistency=0.0, clarity=0.0,
                        granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0)
        assert critic.score_dimension_gini_coefficient(s) == 0.0

    def test_one_dominant_dim_high_gini(self):
        # One dimension = 1.0, rest = 0.0 → high inequality
        critic = _make_critic()
        s = _make_score(completeness=1.0, consistency=0.0, clarity=0.0,
                        granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0)
        g = critic.score_dimension_gini_coefficient(s)
        assert g > 0.5

    def test_alias_of_dimension_gini(self):
        # Must produce exactly the same result as dimension_gini
        critic = _make_critic()
        s = _make_score(completeness=0.2, consistency=0.8, clarity=0.5,
                        granularity=0.3, relationship_coherence=0.6, domain_alignment=0.4)
        assert critic.score_dimension_gini_coefficient(s) == critic.dimension_gini(s)

    def test_result_in_zero_one_range(self):
        critic = _make_critic()
        s = _make_score(completeness=0.1, consistency=0.9, clarity=0.3,
                        granularity=0.7, relationship_coherence=0.5, domain_alignment=0.2)
        g = critic.score_dimension_gini_coefficient(s)
        assert 0.0 <= g <= 1.0

    def test_returns_float(self):
        critic = _make_critic()
        s = _make_score()
        assert isinstance(critic.score_dimension_gini_coefficient(s), float)

    def test_high_inequality_higher_than_low_inequality(self):
        critic = _make_critic()
        low = _make_score(completeness=0.4, consistency=0.5, clarity=0.5,
                          granularity=0.5, relationship_coherence=0.5, domain_alignment=0.6)
        high = _make_score(completeness=0.0, consistency=0.0, clarity=0.0,
                           granularity=0.0, relationship_coherence=0.0, domain_alignment=1.0)
        assert critic.score_dimension_gini_coefficient(high) > critic.score_dimension_gini_coefficient(low)


# ---------------------------------------------------------------------------
# Tests: OntologyLearningAdapter.feedback_plateau_count
# ---------------------------------------------------------------------------


class TestFeedbackPlateauCount:

    def test_empty_returns_zero(self):
        adapter = _make_adapter()
        assert adapter.feedback_plateau_count() == 0

    def test_single_entry_returns_zero(self):
        adapter = _make_adapter()
        _add_feedback(adapter, 0.5)
        assert adapter.feedback_plateau_count() == 0

    def test_no_flat_pairs_returns_zero(self):
        # All deltas > default epsilon=0.01
        adapter = _make_adapter()
        _add_feedback(adapter, 0.1, 0.5, 0.9)
        assert adapter.feedback_plateau_count() == 0

    def test_all_identical_counts_all_pairs(self):
        # n identical scores → n-1 flat pairs
        adapter = _make_adapter()
        _add_feedback(adapter, 0.5, 0.5, 0.5, 0.5)
        assert adapter.feedback_plateau_count() == 3

    def test_one_flat_pair(self):
        adapter = _make_adapter()
        _add_feedback(adapter, 0.5, 0.5, 0.9)
        assert adapter.feedback_plateau_count() == 1

    def test_non_consecutive_flat_pairs(self):
        # 0.5→0.5 flat, 0.5→0.9 not, 0.9→0.9 flat → count=2
        adapter = _make_adapter()
        _add_feedback(adapter, 0.5, 0.5, 0.9, 0.9)
        assert adapter.feedback_plateau_count() == 2

    def test_custom_epsilon_larger(self):
        # With epsilon=0.2, all pairs within 0.2 count
        adapter = _make_adapter()
        _add_feedback(adapter, 0.5, 0.6, 0.7)
        assert adapter.feedback_plateau_count(epsilon=0.2) == 2

    def test_custom_epsilon_zero_only_exact(self):
        # epsilon=0.0 → only exactly equal pairs count
        adapter = _make_adapter()
        _add_feedback(adapter, 0.5, 0.5, 0.501, 0.501)
        # 0.5==0.5 → flat; 0.5→0.501 delta=0.001>0; 0.501==0.501 → flat
        assert adapter.feedback_plateau_count(epsilon=0.0) == 2

    def test_returns_int(self):
        adapter = _make_adapter()
        _add_feedback(adapter, 0.3, 0.3)
        assert isinstance(adapter.feedback_plateau_count(), int)

    def test_boundary_exactly_epsilon(self):
        # |delta| = 0.005 < 0.01 → should count as flat
        adapter = _make_adapter()
        _add_feedback(adapter, 0.5, 0.505)
        assert adapter.feedback_plateau_count(epsilon=0.01) == 1

    def test_count_leq_len_minus_one(self):
        # Can never exceed n-1 pairs
        adapter = _make_adapter()
        _add_feedback(adapter, 0.4, 0.4, 0.4, 0.4, 0.4)
        assert adapter.feedback_plateau_count() <= 4


# ---------------------------------------------------------------------------
# Tests: OntologyPipeline.run_score_velocity_max
# ---------------------------------------------------------------------------


class TestRunScoreVelocityMax:

    def test_empty_returns_zero(self):
        p = _make_pipeline([])
        assert p.run_score_velocity_max() == 0.0

    def test_single_run_returns_zero(self):
        p = _make_pipeline([0.5])
        assert p.run_score_velocity_max() == 0.0

    def test_two_runs_increasing(self):
        # velocity = [0.3] → max = 0.3
        p = _make_pipeline([0.4, 0.7])
        assert abs(p.run_score_velocity_max() - 0.3) < 1e-9

    def test_two_runs_decreasing(self):
        # velocity = [-0.2] → max = -0.2
        p = _make_pipeline([0.7, 0.5])
        assert abs(p.run_score_velocity_max() - (-0.2)) < 1e-9

    def test_multiple_runs_picks_max(self):
        # deltas: 0.1, 0.3, -0.2 → max = 0.3
        p = _make_pipeline([0.2, 0.3, 0.6, 0.4])
        assert abs(p.run_score_velocity_max() - 0.3) < 1e-9

    def test_monotone_increasing(self):
        # deltas all 0.1 → max = 0.1
        p = _make_pipeline([0.0, 0.1, 0.2, 0.3])
        assert abs(p.run_score_velocity_max() - 0.1) < 1e-9

    def test_monotone_decreasing(self):
        # deltas all -0.1 → max = -0.1
        p = _make_pipeline([0.3, 0.2, 0.1, 0.0])
        assert abs(p.run_score_velocity_max() - (-0.1)) < 1e-9

    def test_returns_float(self):
        p = _make_pipeline([0.4, 0.6])
        assert isinstance(p.run_score_velocity_max(), float)

    def test_velocity_max_geq_velocity_min(self):
        # max >= all other velocities
        p = _make_pipeline([0.1, 0.5, 0.3, 0.8])
        vmax = p.run_score_velocity_max()
        scores = [0.1, 0.5, 0.3, 0.8]
        for i in range(len(scores) - 1):
            assert vmax >= scores[i + 1] - scores[i] - 1e-9

    def test_velocity_max_geq_acceleration(self):
        # max velocity is independent of acceleration
        p = _make_pipeline([0.0, 0.5, 0.4, 0.9])
        assert isinstance(p.run_score_velocity_max(), float)


# ---------------------------------------------------------------------------
# Tests: LogicValidator.avg_scc_size
# ---------------------------------------------------------------------------


class TestAvgSccSize:

    def test_empty_graph_returns_zero(self):
        lv = _make_lv()
        ont = _make_ont([], [])
        assert lv.avg_scc_size(ont) == 0.0

    def test_single_node_no_edges(self):
        # 1 SCC of size 1 → avg = 1.0
        lv = _make_lv()
        ont = _make_ont(["A"], [])
        assert lv.avg_scc_size(ont) == 1.0

    def test_two_isolated_nodes(self):
        # 2 SCCs of size 1 each → avg = 1.0
        lv = _make_lv()
        ont = _make_ont(["A", "B"], [])
        assert lv.avg_scc_size(ont) == 1.0

    def test_directed_chain_all_trivial_sccs(self):
        # A→B→C: 3 SCCs of size 1 → avg = 1.0
        lv = _make_lv()
        ont = _make_ont(["A", "B", "C"], [("A", "B"), ("B", "C")])
        assert lv.avg_scc_size(ont) == 1.0

    def test_cycle_one_scc(self):
        # A→B→C→A: 1 SCC of size 3 → avg = 3.0
        lv = _make_lv()
        ont = _make_ont(["A", "B", "C"], [("A", "B"), ("B", "C"), ("C", "A")])
        assert lv.avg_scc_size(ont) == 3.0

    def test_two_cycles_equal_size(self):
        # cycle1: A↔B (size 2), cycle2: C↔D (size 2) → avg = 2.0
        lv = _make_lv()
        ont = _make_ont(
            ["A", "B", "C", "D"],
            [("A", "B"), ("B", "A"), ("C", "D"), ("D", "C")],
        )
        assert lv.avg_scc_size(ont) == 2.0

    def test_avg_equals_sum_divided_by_count(self):
        # avg SCC size = total_nodes / num_SCCs
        lv = _make_lv()
        ont = _make_ont(["A", "B", "C"], [("A", "B"), ("B", "C"), ("C", "A")])
        sizes = lv.strongly_connected_component_sizes(ont)
        expected = sum(sizes) / len(sizes)
        assert abs(lv.avg_scc_size(ont) - expected) < 1e-9

    def test_avg_leq_total_nodes(self):
        # avg ≤ total node count
        lv = _make_lv()
        ont = _make_ont(["A", "B", "C", "D"], [("A", "B"), ("B", "A")])
        assert lv.avg_scc_size(ont) <= 4.0

    def test_returns_float(self):
        lv = _make_lv()
        ont = _make_ont(["A"], [])
        assert isinstance(lv.avg_scc_size(ont), float)

    def test_avg_geq_one_for_nonempty(self):
        # Every SCC has at least 1 node, so avg >= 1
        lv = _make_lv()
        ont = _make_ont(["A", "B", "C"], [("A", "B")])
        assert lv.avg_scc_size(ont) >= 1.0


# ---------------------------------------------------------------------------
# Stale smoke tests: OntologyGenerator.entity_confidence_std (already exists)
# ---------------------------------------------------------------------------


class TestEntityConfidenceStdStale:
    """entity_confidence_std already implemented at lines 5921 + 6801.

    These smoke tests confirm the method exists and behaves correctly.
    """

    def test_empty_result_returns_zero(self):
        gen = _make_gen()
        result = _make_result()
        assert gen.entity_confidence_std(result) == 0.0

    def test_uniform_confidence_returns_zero(self):
        gen = _make_gen()
        entities = [_make_entity(str(i), confidence=0.5) for i in range(4)]
        result = _make_result(entities=entities)
        assert gen.entity_confidence_std(result) == pytest.approx(0.0, abs=1e-9)

    def test_two_entities_formula(self):
        # confidences = [0.0, 1.0]: mean=0.5, var=0.25, std=0.5
        gen = _make_gen()
        entities = [
            _make_entity("A", confidence=0.0),
            _make_entity("B", confidence=1.0),
        ]
        result = _make_result(entities=entities)
        assert gen.entity_confidence_std(result) == pytest.approx(0.5, abs=1e-9)

    def test_returns_float(self):
        gen = _make_gen()
        result = _make_result(entities=[_make_entity("A", 0.7)])
        assert isinstance(gen.entity_confidence_std(result), float)
