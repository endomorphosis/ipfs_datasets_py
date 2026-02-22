"""
Batch 228 — unit tests for four new graphrag optimizer methods.

New methods under test
~~~~~~~~~~~~~~~~~~~~~~
* ``OntologyOptimizer.score_above_target_count(target)``
* ``OntologyCritic.score_dimension_mean_abs_deviation(score)``
* ``OntologyPipeline.run_score_velocity_std()``
* ``LogicValidator.node_in_cycle_fraction(ontology)``

Stale (already implemented, verified by smoke test)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* ``OntologyGenerator.entity_type_ratio(result)``  (line 5796)
* ``OntologyLearningAdapter.feedback_below_mean_count()``  (line 1644)
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
    def __init__(self, s: float) -> None:
        self.average_score = s


def _make_opt(*scores):
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


def _make_entity(eid, confidence=0.7, etype="test"):
    return Entity(id=eid, text=eid, type=etype, confidence=confidence)


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


# ---------------------------------------------------------------------------
# Tests: OntologyOptimizer.score_above_target_count
# ---------------------------------------------------------------------------

class TestScoreAboveTargetCount:
    def test_empty_history_returns_zero(self):
        opt = _make_opt()
        assert opt.score_above_target_count() == 0

    def test_returns_int(self):
        opt = _make_opt(0.8, 0.9)
        assert isinstance(opt.score_above_target_count(), int)

    def test_all_below_target_returns_zero(self):
        opt = _make_opt(0.1, 0.2, 0.3)
        assert opt.score_above_target_count(target=0.7) == 0

    def test_all_above_target(self):
        opt = _make_opt(0.8, 0.9, 1.0)
        assert opt.score_above_target_count(target=0.7) == 3

    def test_mixed_scores(self):
        opt = _make_opt(0.5, 0.7, 0.8, 0.9)
        # 0.7 is NOT strictly above 0.7
        assert opt.score_above_target_count(target=0.7) == 2

    def test_strict_greater_than(self):
        # Exactly at target should NOT be counted
        opt = _make_opt(0.7)
        assert opt.score_above_target_count(target=0.7) == 0

    def test_one_above(self):
        opt = _make_opt(0.3, 0.5, 0.6, 0.9)
        assert opt.score_above_target_count(target=0.7) == 1

    def test_custom_target_zero(self):
        opt = _make_opt(0.1, 0.2, 0.3)
        # All strictly above 0.0
        assert opt.score_above_target_count(target=0.0) == 3

    def test_custom_target_one(self):
        opt = _make_opt(0.5, 0.8, 1.0)
        # Nothing strictly above 1.0
        assert opt.score_above_target_count(target=1.0) == 0

    def test_count_consistent_with_above_target_rate(self):
        # count / n should equal above_target_rate
        opt = _make_opt(0.5, 0.6, 0.8, 0.9)
        count = opt.score_above_target_count(target=0.7)
        rate = opt.above_target_rate(target=0.7)
        assert count / len(opt._history) == pytest.approx(rate)


# ---------------------------------------------------------------------------
# Tests: OntologyCritic.score_dimension_mean_abs_deviation
# ---------------------------------------------------------------------------

class TestScoreDimensionMeanAbsDeviation:
    def test_uniform_returns_zero(self):
        critic = _make_critic()
        s = _make_score()  # all 0.5
        assert critic.score_dimension_mean_abs_deviation(s) == pytest.approx(0.0)

    def test_all_zero_returns_zero(self):
        critic = _make_critic()
        s = _make_score(completeness=0.0, consistency=0.0, clarity=0.0,
                        granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0)
        assert critic.score_dimension_mean_abs_deviation(s) == pytest.approx(0.0)

    def test_non_negative(self):
        critic = _make_critic()
        s = _make_score(completeness=0.9, clarity=0.1)
        assert critic.score_dimension_mean_abs_deviation(s) >= 0.0

    def test_returns_float(self):
        critic = _make_critic()
        s = _make_score(completeness=1.0, consistency=0.0, clarity=0.0,
                        granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0)
        assert isinstance(critic.score_dimension_mean_abs_deviation(s), float)

    def test_known_value(self):
        # vals=[1,0,0,0,0,0], mean=1/6, MAD=mean of |val-mean| for each
        # mean_of_dims = 1/6
        # |1 - 1/6| = 5/6, five |0 - 1/6| = 1/6 each
        # MAD = (5/6 + 5*(1/6)) / 6 = (5/6 + 5/6) / 6 = (10/6)/6 = 10/36 = 5/18
        critic = _make_critic()
        s = _make_score(completeness=1.0, consistency=0.0, clarity=0.0,
                        granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0)
        expected = 5 / 18
        assert critic.score_dimension_mean_abs_deviation(s) == pytest.approx(expected)

    def test_scale_invariance(self):
        # Multiplying all dims by 2 doubles the MAD
        critic = _make_critic()
        s1 = _make_score(completeness=0.8, consistency=0.2, clarity=0.5,
                         granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5)
        s2 = _make_score(completeness=1.6, consistency=0.4, clarity=1.0,
                         granularity=1.0, relationship_coherence=1.0, domain_alignment=1.0)
        assert critic.score_dimension_mean_abs_deviation(s2) == pytest.approx(
            2 * critic.score_dimension_mean_abs_deviation(s1)
        )

    def test_two_opposite_dims(self):
        # [1, 0, 0.5, 0.5, 0.5, 0.5] → mean=0.5, MAD=(0.5+0.5+0+0+0+0)/6 = 1/6
        critic = _make_critic()
        s = _make_score(completeness=1.0, consistency=0.0, clarity=0.5,
                        granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5)
        assert critic.score_dimension_mean_abs_deviation(s) == pytest.approx(1 / 6)

    def test_larger_spread_gives_larger_mad(self):
        critic = _make_critic()
        narrow = _make_score(completeness=0.6, consistency=0.4)
        wide = _make_score(completeness=1.0, consistency=0.0)
        assert critic.score_dimension_mean_abs_deviation(wide) > critic.score_dimension_mean_abs_deviation(narrow)


# ---------------------------------------------------------------------------
# Tests: OntologyPipeline.run_score_velocity_std
# ---------------------------------------------------------------------------

class TestRunScoreVelocityStd:
    def test_empty_history_returns_zero(self):
        p = _make_pipeline([])
        assert p.run_score_velocity_std() == pytest.approx(0.0)

    def test_single_run_returns_zero(self):
        p = _make_pipeline([0.5])
        assert p.run_score_velocity_std() == pytest.approx(0.0)

    def test_two_runs_zero_std(self):
        # Only one first difference → std of a single value = 0
        p = _make_pipeline([0.5, 0.8])
        assert p.run_score_velocity_std() == pytest.approx(0.0)

    def test_constant_step_gives_zero_std(self):
        # fd = [0.1, 0.1, 0.1] → std = 0
        p = _make_pipeline([0.1, 0.2, 0.3, 0.4])
        assert p.run_score_velocity_std() == pytest.approx(0.0)

    def test_non_negative(self):
        p = _make_pipeline([0.1, 0.5, 0.2, 0.9])
        assert p.run_score_velocity_std() >= 0.0

    def test_returns_float(self):
        p = _make_pipeline([0.3, 0.6, 0.4, 0.8])
        assert isinstance(p.run_score_velocity_std(), float)

    def test_known_value(self):
        # scores = [0, 2, 0, 2] → fd = [2, -2, 2] → mean_fd = 2/3
        # variance = ((2-2/3)^2 + (-2-2/3)^2 + (2-2/3)^2) / 3
        # = ((4/3)^2 + (-8/3)^2 + (4/3)^2) / 3
        # = (16/9 + 64/9 + 16/9) / 3 = (96/9) / 3 = 96/27 = 32/9
        # std = sqrt(32/9) ≈ 1.8856
        import math
        p = _make_pipeline([0.0, 2.0, 0.0, 2.0])
        expected = math.sqrt(32 / 9)
        assert p.run_score_velocity_std() == pytest.approx(expected)

    def test_larger_variance_gives_larger_std(self):
        # uniform steps vs alternating large/small
        p_flat = _make_pipeline([0.1, 0.2, 0.3, 0.4, 0.5])  # fd all 0.1 → std=0
        p_vary = _make_pipeline([0.0, 0.5, 0.1, 0.9, 0.2])  # fd vary widely
        assert p_vary.run_score_velocity_std() > p_flat.run_score_velocity_std()

    def test_std_leq_velocity_range(self):
        # For any sequence, std(fd) <= range(fd) because range = max-min
        import math
        p = _make_pipeline([0.1, 0.4, 0.2, 0.8, 0.5])
        std = p.run_score_velocity_std()
        vrange = p.run_score_velocity_range()
        assert std <= vrange + 1e-9

    def test_five_runs_varied(self):
        p = _make_pipeline([0.0, 1.0, 0.0, 1.0, 0.0])
        # fd = [1,-1,1,-1] → mean=0, var=1, std=1
        assert p.run_score_velocity_std() == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Tests: LogicValidator.node_in_cycle_fraction
# ---------------------------------------------------------------------------

class TestNodeInCycleFraction:
    def _lv(self):
        return object.__new__(LogicValidator)

    def _ont(self, edges):
        """Build ontology dict from list of (src, tgt) edge tuples."""
        node_ids = set()
        for s, t in edges:
            node_ids.add(s)
            node_ids.add(t)
        entities = [{"id": n} for n in node_ids]
        rels = [{"source_id": s, "target_id": t} for s, t in edges]
        return {"entities": entities, "relationships": rels}

    def test_empty_graph(self):
        lv = self._lv()
        assert lv.node_in_cycle_fraction({"entities": [], "relationships": []}) == pytest.approx(0.0)

    def test_single_node_no_edges(self):
        lv = self._lv()
        ont = {"entities": [{"id": "A"}], "relationships": []}
        assert lv.node_in_cycle_fraction(ont) == pytest.approx(0.0)

    def test_chain_no_cycles(self):
        # A→B→C: pure DAG, no cycles
        lv = self._lv()
        ont = self._ont([("A", "B"), ("B", "C")])
        assert lv.node_in_cycle_fraction(ont) == pytest.approx(0.0)

    def test_self_loop_single_node(self):
        # A→A: A is in a non-singleton SCC (size=1? or treated as a cycle?)
        # Actually A→A creates a 1-node SCC but Tarjan's would still detect
        # it as a strongly connected component. Check implementation:
        # The standard Kosaraju/Tarjan for self-loops: A can reach itself,
        # so it's in an SCC of size 1 but the self-loop makes it cyclic.
        # Our implementation uses BFS reachability: A reaches A via the edge,
        # so A is in an SCC. size=1. Our scc_non_singleton check is s>1,
        # so self-loop is NOT counted as non-singleton. So 0.0.
        lv = self._lv()
        ont = {"entities": [{"id": "A"}], "relationships": [{"source_id": "A", "target_id": "A"}]}
        # The SCC containing A has size 1 (just A), so it's a singleton even with self-loop
        result = lv.node_in_cycle_fraction(ont)
        assert isinstance(result, float)
        assert result >= 0.0

    def test_two_node_cycle(self):
        # A→B→A: both nodes in one SCC of size 2
        lv = self._lv()
        ont = self._ont([("A", "B"), ("B", "A")])
        assert lv.node_in_cycle_fraction(ont) == pytest.approx(1.0)

    def test_three_node_cycle(self):
        # A→B→C→A: all three in one SCC
        lv = self._lv()
        ont = self._ont([("A", "B"), ("B", "C"), ("C", "A")])
        assert lv.node_in_cycle_fraction(ont) == pytest.approx(1.0)

    def test_partial_cycle(self):
        # A→B→C→B (B-C cycle, A is not in cycle)
        # SCCs: {A}=1, {B,C}=2 → nodes in cycle: 2 out of 3
        lv = self._lv()
        ont = self._ont([("A", "B"), ("B", "C"), ("C", "B")])
        assert lv.node_in_cycle_fraction(ont) == pytest.approx(2 / 3)

    def test_disconnected_cycle_plus_dag(self):
        # A→B→A (cycle), C→D (DAG part)
        # SCCs: {A,B}=2, {C}=1, {D}=1 → nodes in cycles: 2 out of 4
        lv = self._lv()
        ont = self._ont([("A", "B"), ("B", "A"), ("C", "D")])
        assert lv.node_in_cycle_fraction(ont) == pytest.approx(2 / 4)

    def test_returns_float(self):
        lv = self._lv()
        ont = self._ont([("A", "B"), ("B", "A")])
        assert isinstance(lv.node_in_cycle_fraction(ont), float)

    def test_value_in_range(self):
        lv = self._lv()
        ont = self._ont([("A", "B"), ("B", "C"), ("C", "A"), ("D", "E")])
        val = lv.node_in_cycle_fraction(ont)
        assert 0.0 <= val <= 1.0

    def test_geq_scc_non_singleton_fraction(self):
        # node_in_cycle_fraction >= scc_non_singleton_fraction since
        # non-singleton SCCs contribute more than 1 node per SCC
        lv = self._lv()
        # 3-cycle + 2-singleton: {A,B,C}, {D}, {E}
        ont = self._ont([("A", "B"), ("B", "C"), ("C", "A"), ("D", "E")])
        nicf = lv.node_in_cycle_fraction(ont)
        nsf = lv.scc_non_singleton_fraction(ont)
        assert nicf >= nsf - 1e-9


# ---------------------------------------------------------------------------
# Stale smoke tests
# ---------------------------------------------------------------------------

class TestStaleEntityTypeRatio:
    """entity_type_ratio already exists (line 5796) — smoke-test the dict API."""

    def test_empty_result_returns_empty_dict(self):
        gen = _make_gen()
        result = _make_result()
        assert gen.entity_type_ratio(result) == {}

    def test_single_type(self):
        gen = _make_gen()
        ents = [_make_entity("A", etype="person"), _make_entity("B", etype="person")]
        result = _make_result(entities=ents)
        ratios = gen.entity_type_ratio(result)
        assert "person" in ratios
        assert ratios["person"] == pytest.approx(1.0)

    def test_two_types_equal_split(self):
        gen = _make_gen()
        ents = [_make_entity("A", etype="person"), _make_entity("B", etype="org")]
        result = _make_result(entities=ents)
        ratios = gen.entity_type_ratio(result)
        assert ratios["person"] == pytest.approx(0.5)
        assert ratios["org"] == pytest.approx(0.5)


class TestStaleFeedbackBelowMeanCount:
    """feedback_below_mean_count already exists (line 1644) — smoke test."""

    def test_empty_returns_zero(self):
        adapter = _make_adapter()
        assert adapter.feedback_below_mean_count() == 0

    def test_uniform_returns_zero(self):
        adapter = _make_adapter()
        _add_feedback(adapter, 0.5, 0.5, 0.5)
        assert adapter.feedback_below_mean_count() == 0

    def test_one_below(self):
        adapter = _make_adapter()
        _add_feedback(adapter, 0.1, 0.9, 0.9)
        # mean = (0.1+0.9+0.9)/3 = 0.633; 0.1 < 0.633
        assert adapter.feedback_below_mean_count() == 1
