"""
Batch 224 — unit tests for six new graphrag optimizer methods.

New methods under test
~~~~~~~~~~~~~~~~~~~~~~
* ``OntologyOptimizer.score_variance_to_range_ratio()``
* ``OntologyCritic.score_dimension_range_ratio(score)``
* ``OntologyGenerator.entity_confidence_above_threshold(result, threshold)``
* ``OntologyLearningAdapter.feedback_decline_streaks()``
* ``OntologyPipeline.run_score_jerk()``
* ``LogicValidator.scc_giant_fraction(ontology)``
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
# Tests: OntologyOptimizer.score_variance_to_range_ratio
# ---------------------------------------------------------------------------


class TestScoreVarianceToRangeRatio:

    def test_empty_returns_zero(self):
        opt = _make_opt()
        assert opt.score_variance_to_range_ratio() == 0.0

    def test_single_entry_returns_zero(self):
        opt = _make_opt(0.6)
        assert opt.score_variance_to_range_ratio() == 0.0

    def test_uniform_scores_returns_zero(self):
        opt = _make_opt(0.5, 0.5, 0.5)
        assert opt.score_variance_to_range_ratio() == 0.0

    def test_two_entries_formula(self):
        # scores = [0.0, 1.0]: range=1, mean=0.5, variance=0.25 → ratio=0.25
        opt = _make_opt(0.0, 1.0)
        result = opt.score_variance_to_range_ratio()
        assert abs(result - 0.25) < 1e-9

    def test_uniform_distribution_near_quarter(self):
        # For a "uniform" spread [0, 0.25, 0.5, 0.75, 1.0] the ratio approaches 1/12
        opt = _make_opt(0.0, 0.25, 0.5, 0.75, 1.0)
        result = opt.score_variance_to_range_ratio()
        assert 0.0 < result < 0.5

    def test_all_same_except_one_outlier(self):
        # [0.0, 1.0, 1.0, 1.0]: range=1, mean=0.75, variance=0.1875
        opt = _make_opt(0.0, 1.0, 1.0, 1.0)
        result = opt.score_variance_to_range_ratio()
        assert abs(result - 3 / 16) < 1e-9

    def test_returns_float(self):
        opt = _make_opt(0.3, 0.7)
        assert isinstance(opt.score_variance_to_range_ratio(), float)

    def test_non_negative(self):
        for n in range(1, 8):
            opt = _make_opt(*[i / n for i in range(n + 1)])
            assert opt.score_variance_to_range_ratio() >= 0.0

    def test_at_most_quarter_for_any_two_point(self):
        # For any two-point distribution variance/range² = 0.25 exactly
        opt = _make_opt(0.2, 0.8)
        assert abs(opt.score_variance_to_range_ratio() - 0.25) < 1e-9


# ---------------------------------------------------------------------------
# Tests: OntologyCritic.score_dimension_range_ratio
# ---------------------------------------------------------------------------


class TestScoreDimensionRangeRatio:

    def test_uniform_returns_zero(self):
        critic = _make_critic()
        s = _make_score()  # all 0.5
        assert critic.score_dimension_range_ratio(s) == 0.0

    def test_all_zero_returns_zero(self):
        critic = _make_critic()
        s = _make_score(
            completeness=0.0, consistency=0.0, clarity=0.0,
            granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0,
        )
        assert critic.score_dimension_range_ratio(s) == 0.0

    def test_single_nonzero_dim(self):
        # max=1.0 min=0.0 → (1-0)/(1+0) = 1.0
        critic = _make_critic()
        s = _make_score(
            completeness=0.0, consistency=0.0, clarity=0.0,
            granularity=0.0, relationship_coherence=0.0, domain_alignment=1.0,
        )
        result = critic.score_dimension_range_ratio(s)
        assert result == 1.0

    def test_example_from_docstring(self):
        # max=0.8 min=0.2 → (0.8-0.2)/(0.8+0.2) = 0.6
        critic = _make_critic()
        s = CriticScore(
            completeness=0.2, consistency=0.8, clarity=0.5,
            granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5,
        )
        result = critic.score_dimension_range_ratio(s)
        assert abs(result - 0.6) < 1e-9

    def test_returns_float(self):
        critic = _make_critic()
        s = _make_score(completeness=0.1, domain_alignment=0.9)
        assert isinstance(critic.score_dimension_range_ratio(s), float)

    def test_value_in_zero_one_range(self):
        critic = _make_critic()
        for lo, hi in [(0.0, 0.5), (0.1, 0.9), (0.3, 0.7), (0.4, 0.6)]:
            s = _make_score(completeness=lo, domain_alignment=hi)
            result = critic.score_dimension_range_ratio(s)
            assert 0.0 <= result <= 1.0

    def test_symmetric_to_score_range_ratio_pattern(self):
        # Test two extreme dims: same as OntologyOptimizer.score_range_ratio formula
        critic = _make_critic()
        lo, hi = 0.3, 0.7
        s = _make_score(completeness=lo, consistency=lo, clarity=lo,
                        granularity=lo, relationship_coherence=lo, domain_alignment=hi)
        expected = (hi - lo) / (hi + lo)
        assert abs(critic.score_dimension_range_ratio(s) - expected) < 1e-9


# ---------------------------------------------------------------------------
# Tests: OntologyGenerator.entity_confidence_above_threshold
# ---------------------------------------------------------------------------


class TestEntityConfidenceAboveThreshold:

    def test_empty_returns_zero(self):
        gen = _make_gen()
        result = _make_result()
        assert gen.entity_confidence_above_threshold(result) == 0

    def test_all_above_default_threshold(self):
        gen = _make_gen()
        entities = [_make_entity(str(i), confidence=0.8) for i in range(5)]
        result = _make_result(entities)
        assert gen.entity_confidence_above_threshold(result) == 5

    def test_none_above_threshold(self):
        gen = _make_gen()
        entities = [_make_entity(str(i), confidence=0.3) for i in range(4)]
        result = _make_result(entities)
        assert gen.entity_confidence_above_threshold(result, threshold=0.5) == 0

    def test_at_boundary_is_included(self):
        # threshold=0.5 → confidence>=0.5 counts
        gen = _make_gen()
        entities = [_make_entity("a", confidence=0.5), _make_entity("b", confidence=0.4)]
        result = _make_result(entities)
        assert gen.entity_confidence_above_threshold(result, threshold=0.5) == 1

    def test_complement_with_below_threshold(self):
        # above + below should equal the number of entities with non-None confidence
        gen = _make_gen()
        confidences = [0.1, 0.3, 0.5, 0.7, 0.9]
        entities = [_make_entity(str(i), c) for i, c in enumerate(confidences)]
        result = _make_result(entities)
        above = gen.entity_confidence_above_threshold(result, threshold=0.5)
        below = gen.entity_confidence_below_threshold(result, threshold=0.5)
        assert above + below == len(confidences)

    def test_returns_int(self):
        gen = _make_gen()
        result = _make_result([_make_entity("x", 0.8)])
        assert isinstance(gen.entity_confidence_above_threshold(result), int)

    def test_custom_threshold(self):
        gen = _make_gen()
        entities = [
            _make_entity("a", 0.2),
            _make_entity("b", 0.5),
            _make_entity("c", 0.8),
            _make_entity("d", 1.0),
        ]
        result = _make_result(entities)
        assert gen.entity_confidence_above_threshold(result, threshold=0.8) == 2  # 0.8, 1.0

    def test_non_negative(self):
        gen = _make_gen()
        result = _make_result([_make_entity("a", 0.0)])
        assert gen.entity_confidence_above_threshold(result) >= 0

    def test_all_at_zero_threshold(self):
        gen = _make_gen()
        entities = [_make_entity(str(i), 0.0) for i in range(3)]
        result = _make_result(entities)
        assert gen.entity_confidence_above_threshold(result, threshold=0.0) == 3


# ---------------------------------------------------------------------------
# Tests: OntologyLearningAdapter.feedback_decline_streaks
# ---------------------------------------------------------------------------


class TestFeedbackDeclineStreaks:

    def test_empty_returns_zero(self):
        adapter = _make_adapter()
        assert adapter.feedback_decline_streaks() == 0

    def test_single_returns_zero(self):
        adapter = _make_adapter()
        _add_feedback(adapter, 0.5)
        assert adapter.feedback_decline_streaks() == 0

    def test_all_increasing_returns_zero(self):
        adapter = _make_adapter()
        _add_feedback(adapter, 0.1, 0.3, 0.5, 0.7, 0.9)
        assert adapter.feedback_decline_streaks() == 0

    def test_single_decline(self):
        adapter = _make_adapter()
        _add_feedback(adapter, 0.9, 0.5)
        assert adapter.feedback_decline_streaks() == 1

    def test_two_declines(self):
        adapter = _make_adapter()
        _add_feedback(adapter, 0.9, 0.7, 0.5)
        assert adapter.feedback_decline_streaks() == 2

    def test_mixed_streak(self):
        # 0.9→0.7→0.8→0.5→0.3 — two separate decline runs of length 1 and 2
        adapter = _make_adapter()
        _add_feedback(adapter, 0.9, 0.7, 0.8, 0.5, 0.3)
        assert adapter.feedback_decline_streaks() == 2

    def test_docstring_example(self):
        adapter = _make_adapter()
        _add_feedback(adapter, 0.9, 0.7, 0.8, 0.5, 0.3)
        assert adapter.feedback_decline_streaks() == 2

    def test_uniform_scores_returns_zero(self):
        adapter = _make_adapter()
        _add_feedback(adapter, 0.5, 0.5, 0.5, 0.5)
        assert adapter.feedback_decline_streaks() == 0

    def test_returns_int(self):
        adapter = _make_adapter()
        _add_feedback(adapter, 0.8, 0.6)
        assert isinstance(adapter.feedback_decline_streaks(), int)

    def test_symmetric_to_improvement_streaks(self):
        # Reversed sequence → improvement_streaks == original decline_streaks
        scores = [0.3, 0.5, 0.4, 0.7, 0.9]
        adapter_fwd = _make_adapter()
        adapter_rev = _make_adapter()
        _add_feedback(adapter_fwd, *scores)
        _add_feedback(adapter_rev, *reversed(scores))
        assert adapter_fwd.feedback_improvement_streaks() == adapter_rev.feedback_decline_streaks()

    def test_long_streak(self):
        adapter = _make_adapter()
        _add_feedback(adapter, 1.0, 0.9, 0.8, 0.7, 0.6, 0.5)
        assert adapter.feedback_decline_streaks() == 5


# ---------------------------------------------------------------------------
# Tests: OntologyPipeline.run_score_jerk
# ---------------------------------------------------------------------------


class TestRunScoreJerk:

    def test_empty_returns_zero(self):
        p = _make_pipeline([])
        assert p.run_score_jerk() == 0.0

    def test_one_run_returns_zero(self):
        p = _make_pipeline([0.5])
        assert p.run_score_jerk() == 0.0

    def test_two_runs_returns_zero(self):
        p = _make_pipeline([0.3, 0.7])
        assert p.run_score_jerk() == 0.0

    def test_three_runs_returns_zero(self):
        # Three scores give 2 fd and 1 sd — not enough for td
        p = _make_pipeline([0.3, 0.6, 0.9])
        assert p.run_score_jerk() == 0.0

    def test_linear_sequence_jerk_is_zero(self):
        # Linear: fd all equal, sd all zero, td all zero
        p = _make_pipeline([0.0, 0.2, 0.4, 0.6])
        assert abs(p.run_score_jerk()) < 1e-9

    def test_constant_acceleration_jerk_is_zero(self):
        # Quadratic: fd linear, sd all equal, td all zero
        p = _make_pipeline([0.0, 0.1, 0.3, 0.6])
        # fd=[0.1, 0.2, 0.3], sd=[0.1, 0.1], td=[0.0]
        assert abs(p.run_score_jerk()) < 1e-9

    def test_increasing_acceleration_positive_jerk(self):
        # fd=[0.1, 0.2, 0.4], sd=[0.1, 0.2], td=[0.1]
        p = _make_pipeline([0.0, 0.1, 0.3, 0.7])
        assert p.run_score_jerk() > 0.0

    def test_decreasing_acceleration_negative_jerk(self):
        # scores=[0.0, 0.1, 0.3, 0.8, 0.9]
        # fd=[0.1, 0.2, 0.5, 0.1], sd=[0.1, 0.3, -0.4], td=[0.2, -0.7] → mean=-0.25
        p = _make_pipeline([0.0, 0.1, 0.3, 0.8, 0.9])
        assert p.run_score_jerk() < 0.0

    def test_returns_float(self):
        p = _make_pipeline([0.1, 0.2, 0.4, 0.8])
        assert isinstance(p.run_score_jerk(), float)

    def test_exact_value(self):
        # scores=[0.0, 0.1, 0.3, 0.7] → fd=[0.1, 0.2, 0.4] → sd=[0.1, 0.2] → td=[0.1]
        p = _make_pipeline([0.0, 0.1, 0.3, 0.7])
        assert abs(p.run_score_jerk() - 0.1) < 1e-9


# ---------------------------------------------------------------------------
# Tests: LogicValidator.scc_giant_fraction
# ---------------------------------------------------------------------------


class TestSccGiantFraction:

    def test_empty_ontology_returns_zero(self):
        lv = _make_lv()
        ont = _make_ont([], [])
        assert lv.scc_giant_fraction(ont) == 0.0

    def test_single_node_no_edges(self):
        lv = _make_lv()
        ont = _make_ont(["A"], [])
        # One SCC of size 1 → 1/1 = 1.0
        assert lv.scc_giant_fraction(ont) == 1.0

    def test_two_nodes_no_edges(self):
        lv = _make_lv()
        ont = _make_ont(["A", "B"], [])
        # Two SCCs of size 1 each → giant = 1 / 2 = 0.5
        assert lv.scc_giant_fraction(ont) == 0.5

    def test_fully_connected_cycle(self):
        lv = _make_lv()
        ont = _make_ont(["A", "B", "C"], [("A", "B"), ("B", "C"), ("C", "A")])
        # One SCC of size 3 → 3/3 = 1.0
        assert lv.scc_giant_fraction(ont) == 1.0

    def test_dag_no_large_scc(self):
        lv = _make_lv()
        ont = _make_ont(["A", "B", "C"], [("A", "B"), ("B", "C")])
        # Three trivial SCCs → giant = 1/3
        assert abs(lv.scc_giant_fraction(ont) - 1 / 3) < 1e-9

    def test_one_cycle_plus_isolated(self):
        lv = _make_lv()
        ont = _make_ont(["A", "B", "C", "D"], [("A", "B"), ("B", "A")])
        # SCC {A,B}=2, SCC {C}=1, SCC {D}=1 → giant = 2/4 = 0.5
        assert lv.scc_giant_fraction(ont) == 0.5

    def test_result_in_zero_one(self):
        lv = _make_lv()
        for edges in [[], [("A", "B")], [("A", "B"), ("B", "A")]]:
            ont = _make_ont(["A", "B"], edges)
            result = lv.scc_giant_fraction(ont)
            assert 0.0 <= result <= 1.0

    def test_returns_float(self):
        lv = _make_lv()
        ont = _make_ont(["A"], [])
        assert isinstance(lv.scc_giant_fraction(ont), float)

    def test_giant_leq_one(self):
        lv = _make_lv()
        ont = _make_ont(["A", "B", "C"], [("A", "B"), ("B", "C"), ("C", "A")])
        assert lv.scc_giant_fraction(ont) <= 1.0

    def test_consistent_with_sizes(self):
        lv = _make_lv()
        ont = _make_ont(["A", "B", "C", "D", "E"],
                        [("A", "B"), ("B", "A"), ("C", "D"), ("D", "C")])
        sizes = lv.strongly_connected_component_sizes(ont)
        total = sum(sizes)
        expected = sizes[0] / total
        assert abs(lv.scc_giant_fraction(ont) - expected) < 1e-9
