"""
Batch 223 — unit tests for five new graphrag optimizer methods.

New methods under test
~~~~~~~~~~~~~~~~~~~~~~
* ``OntologyOptimizer.score_range_ratio()``
* ``OntologyCritic.score_dimension_skewness(score)``
* ``OntologyGenerator.entity_confidence_below_threshold(result, threshold)``
* ``OntologyLearningAdapter.feedback_improvement_streaks()``
* ``LogicValidator.strongly_connected_component_sizes(ontology)``

Stale smoke-tests for already-implemented methods
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* ``OntologyPipeline.run_score_acceleration()``
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


def _make_adapter(*scores):
    """Build OntologyLearningAdapter with feedback from given scores."""
    adapter = OntologyLearningAdapter()
    for s in scores:
        adapter.apply_feedback(final_score=s, actions={})
    return adapter


def _make_critic():
    return object.__new__(OntologyCritic)


def _make_result(entities=None, relationships=None):
    ents = entities or []
    rels = relationships or []
    r = object.__new__(EntityExtractionResult)
    r.entities = ents
    r.relationships = rels
    r.confidence = 1.0
    return r


def _entity(eid, confidence=0.8):
    e = object.__new__(Entity)
    e.id = eid
    e.type = "TestType"
    e.text = eid
    e.confidence = confidence
    return e


def _rel(src, tgt, rtype="related"):
    r = object.__new__(Relationship)
    r.id = f"{src}-{tgt}"
    r.source_id = src
    r.target_id = tgt
    r.type = rtype
    r.confidence = 0.8
    return r


def _make_score(**kwargs):
    dims = {
        "completeness": 0.5, "consistency": 0.5, "clarity": 0.5,
        "granularity": 0.5, "relationship_coherence": 0.5, "domain_alignment": 0.5,
    }
    dims.update(kwargs)
    s = object.__new__(CriticScore)
    for k, v in dims.items():
        setattr(s, k, v)
    return s


_lv = LogicValidator()

# ---------------------------------------------------------------------------
# OntologyOptimizer.score_range_ratio
# ---------------------------------------------------------------------------

class TestScoreRangeRatio:
    """Tests for OntologyOptimizer.score_range_ratio()."""

    def test_empty_returns_zero(self):
        opt = _make_opt()
        assert opt.score_range_ratio() == 0.0

    def test_single_entry_zero_denominator(self):
        # max + min = 2*v; only zero when v == 0
        opt = _make_opt(0.5)
        # max=min=0.5 → (0)/(1.0) = 0.0
        assert opt.score_range_ratio() == 0.0

    def test_single_zero_entry(self):
        opt = _make_opt(0.0)
        assert opt.score_range_ratio() == 0.0

    def test_uniform_returns_zero(self):
        opt = _make_opt(0.7, 0.7, 0.7)
        assert opt.score_range_ratio() == 0.0

    def test_formula_basic(self):
        # max=0.9, min=0.1 → (0.8)/(1.0) = 0.8
        opt = _make_opt(0.1, 0.9)
        assert abs(opt.score_range_ratio() - 0.8) < 1e-9

    def test_formula_0_to_1(self):
        # max=1, min=0 → 1/1 = 1.0
        opt = _make_opt(0.0, 1.0)
        assert abs(opt.score_range_ratio() - 1.0) < 1e-9

    def test_max_plus_min_zero_returns_zero(self):
        # max=0.5, min=-0.5 → max+min=0
        opt = _make_opt(-0.5, 0.5)
        assert opt.score_range_ratio() == 0.0

    def test_non_negative_for_positive_scores(self):
        opt = _make_opt(0.2, 0.5, 0.8)
        assert opt.score_range_ratio() >= 0.0

    def test_returns_float(self):
        assert isinstance(_make_opt(0.3, 0.7).score_range_ratio(), float)

    def test_larger_history(self):
        opt = _make_opt(*[i * 0.1 for i in range(11)])  # 0.0 … 1.0
        # max=1.0, min=0.0 → 1.0/(1.0) = 1.0
        assert abs(opt.score_range_ratio() - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# OntologyCritic.score_dimension_skewness
# ---------------------------------------------------------------------------

class TestScoreDimensionSkewness:
    """Tests for OntologyCritic.score_dimension_skewness(score)."""

    def test_uniform_returns_zero(self):
        critic = _make_critic()
        s = _make_score()  # all 0.5
        assert critic.score_dimension_skewness(s) == 0.0

    def test_right_skewed(self):
        # five zeros and one large value → right-skewed (positive skewness)
        critic = _make_critic()
        s = _make_score(
            completeness=0.0, consistency=0.0, clarity=0.0,
            granularity=0.0, relationship_coherence=0.0, domain_alignment=1.0,
        )
        skew = critic.score_dimension_skewness(s)
        assert skew > 0.0

    def test_left_skewed(self):
        # five ones and one zero → left-skewed (negative skewness)
        critic = _make_critic()
        s = _make_score(
            completeness=1.0, consistency=1.0, clarity=1.0,
            granularity=1.0, relationship_coherence=1.0, domain_alignment=0.0,
        )
        skew = critic.score_dimension_skewness(s)
        assert skew < 0.0

    def test_symmetric_distribution_near_zero(self):
        # values 0.0, 0.2, 0.4, 0.6, 0.8, 1.0 → symmetric → skewness ≈ 0
        critic = _make_critic()
        s = _make_score(
            completeness=0.0, consistency=0.2, clarity=0.4,
            granularity=0.6, relationship_coherence=0.8, domain_alignment=1.0,
        )
        skew = critic.score_dimension_skewness(s)
        assert abs(skew) < 1e-9

    def test_returns_float(self):
        critic = _make_critic()
        s = _make_score()
        assert isinstance(critic.score_dimension_skewness(s), float)

    def test_all_zero_dims_zero_variance(self):
        critic = _make_critic()
        s = _make_score(
            completeness=0.0, consistency=0.0, clarity=0.0,
            granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0,
        )
        assert critic.score_dimension_skewness(s) == 0.0

    def test_population_formula_check(self):
        # Manual: vals=[1,0,0,0,0,0]; mean=1/6; compute expected skew
        critic = _make_critic()
        s = _make_score(
            completeness=1.0, consistency=0.0, clarity=0.0,
            granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0,
        )
        vals = [1.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        n = 6
        mean = sum(vals) / n
        variance = sum((v - mean) ** 2 for v in vals) / n
        std = variance ** 0.5
        m3 = sum((v - mean) ** 3 for v in vals) / n
        expected = m3 / (std ** 3)
        result = critic.score_dimension_skewness(s)
        assert abs(result - expected) < 1e-9

    def test_dimension_flip_negates_skewness(self):
        # Flipping the extreme dimension should negate the skewness
        critic = _make_critic()
        s1 = _make_score(completeness=1.0, domain_alignment=0.0)
        s2 = _make_score(completeness=0.0, domain_alignment=1.0)
        # s1 left-skewed, s2 right-skewed with same magnitude
        assert abs(critic.score_dimension_skewness(s1) + critic.score_dimension_skewness(s2)) < 1e-9


# ---------------------------------------------------------------------------
# OntologyGenerator.entity_confidence_below_threshold
# ---------------------------------------------------------------------------

class TestEntityConfidenceBelowThreshold:
    """Tests for OntologyGenerator.entity_confidence_below_threshold()."""

    def _gen(self):
        return object.__new__(OntologyGenerator)

    def test_empty_entities_returns_zero(self):
        gen = self._gen()
        result = _make_result()
        assert gen.entity_confidence_below_threshold(result) == 0

    def test_all_above_threshold(self):
        gen = self._gen()
        entities = [_entity("A", 0.8), _entity("B", 0.9)]
        result = _make_result(entities=entities)
        assert gen.entity_confidence_below_threshold(result, threshold=0.5) == 0

    def test_all_below_threshold(self):
        gen = self._gen()
        entities = [_entity("A", 0.1), _entity("B", 0.2)]
        result = _make_result(entities=entities)
        assert gen.entity_confidence_below_threshold(result, threshold=0.5) == 2

    def test_strict_less_than(self):
        # exactly at threshold should NOT be counted
        gen = self._gen()
        entities = [_entity("A", 0.5)]
        result = _make_result(entities=entities)
        assert gen.entity_confidence_below_threshold(result, threshold=0.5) == 0

    def test_just_below_threshold_counted(self):
        gen = self._gen()
        entities = [_entity("A", 0.4999)]
        result = _make_result(entities=entities)
        assert gen.entity_confidence_below_threshold(result, threshold=0.5) == 1

    def test_mixed_entities(self):
        gen = self._gen()
        entities = [
            _entity("A", 0.1),
            _entity("B", 0.5),  # at threshold — not counted
            _entity("C", 0.9),
        ]
        result = _make_result(entities=entities)
        assert gen.entity_confidence_below_threshold(result, threshold=0.5) == 1

    def test_default_threshold_0_5(self):
        gen = self._gen()
        entities = [_entity("A", 0.3), _entity("B", 0.8)]
        result = _make_result(entities=entities)
        assert gen.entity_confidence_below_threshold(result) == 1

    def test_returns_int(self):
        gen = self._gen()
        result = _make_result()
        assert isinstance(gen.entity_confidence_below_threshold(result), int)

    def test_threshold_zero_counts_negatives_only(self):
        gen = self._gen()
        entities = [_entity("A", 0.0), _entity("B", 0.1)]
        result = _make_result(entities=entities)
        # threshold=0.0 → strict < 0.0 → nothing qualifies
        assert gen.entity_confidence_below_threshold(result, threshold=0.0) == 0

    def test_threshold_one_counts_all_below_one(self):
        gen = self._gen()
        entities = [_entity("A", 0.5), _entity("B", 0.999), _entity("C", 1.0)]
        result = _make_result(entities=entities)
        # threshold=1.0 → 2 entities below 1.0
        assert gen.entity_confidence_below_threshold(result, threshold=1.0) == 2

    def test_non_negative(self):
        gen = self._gen()
        entities = [_entity(f"E{i}", i * 0.1) for i in range(10)]
        result = _make_result(entities=entities)
        assert gen.entity_confidence_below_threshold(result, threshold=0.5) >= 0


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.feedback_improvement_streaks
# ---------------------------------------------------------------------------

class TestFeedbackImprovementStreaks:
    """Tests for OntologyLearningAdapter.feedback_improvement_streaks()."""

    def test_empty_returns_zero(self):
        adapter = _make_adapter()
        assert adapter.feedback_improvement_streaks() == 0

    def test_single_entry_returns_zero(self):
        adapter = _make_adapter(0.5)
        assert adapter.feedback_improvement_streaks() == 0

    def test_all_improving(self):
        # 0.1→0.2→0.3→0.4 → 3 consecutive improvement steps
        adapter = _make_adapter(0.1, 0.2, 0.3, 0.4)
        assert adapter.feedback_improvement_streaks() == 3

    def test_no_improvement(self):
        # strictly decreasing
        adapter = _make_adapter(0.9, 0.7, 0.5, 0.3)
        assert adapter.feedback_improvement_streaks() == 0

    def test_single_improvement(self):
        adapter = _make_adapter(0.3, 0.8)
        assert adapter.feedback_improvement_streaks() == 1

    def test_longest_streak_after_reset(self):
        # 0.3→0.5 (1), 0.5→0.4 (reset), 0.4→0.6→0.8→0.9 (3 steps) → best=3
        adapter = _make_adapter(0.3, 0.5, 0.4, 0.6, 0.8, 0.9)
        assert adapter.feedback_improvement_streaks() == 3

    def test_two_streaks_returns_longer(self):
        # streak1: 2 steps, streak2: 3 steps → returns 3
        adapter = _make_adapter(0.1, 0.3, 0.5, 0.2, 0.4, 0.6, 0.8)
        assert adapter.feedback_improvement_streaks() == 3

    def test_flat_scores_no_streak(self):
        # equal scores don't count as improvement
        adapter = _make_adapter(0.5, 0.5, 0.5)
        assert adapter.feedback_improvement_streaks() == 0

    def test_strict_gt_not_geq(self):
        # flat after one rise
        adapter = _make_adapter(0.3, 0.5, 0.5, 0.5)
        assert adapter.feedback_improvement_streaks() == 1

    def test_returns_int(self):
        assert isinstance(_make_adapter(0.3, 0.7).feedback_improvement_streaks(), int)

    def test_non_negative(self):
        assert _make_adapter().feedback_improvement_streaks() >= 0


# ---------------------------------------------------------------------------
# LogicValidator.strongly_connected_component_sizes
# ---------------------------------------------------------------------------

class TestStronglyConnectedComponentSizes:
    """Tests for LogicValidator.strongly_connected_component_sizes(ontology)."""

    def test_empty_returns_empty(self):
        onto = {"entities": [], "relationships": []}
        assert _lv.strongly_connected_component_sizes(onto) == []

    def test_single_node_one_scc_of_size_one(self):
        onto = {"entities": [{"id": "A"}], "relationships": []}
        assert _lv.strongly_connected_component_sizes(onto) == [1]

    def test_two_nodes_no_cycle(self):
        onto = {
            "entities": [{"id": "A"}, {"id": "B"}],
            "relationships": [{"source_id": "A", "target_id": "B"}],
        }
        # A→B: two trivial SCCs, both size 1 → [1, 1]
        sizes = _lv.strongly_connected_component_sizes(onto)
        assert sizes == [1, 1]

    def test_two_nodes_bidirectional_one_scc(self):
        onto = {
            "entities": [{"id": "A"}, {"id": "B"}],
            "relationships": [
                {"source_id": "A", "target_id": "B"},
                {"source_id": "B", "target_id": "A"},
            ],
        }
        # A↔B: one SCC of size 2
        assert _lv.strongly_connected_component_sizes(onto) == [2]

    def test_three_cycle_one_scc(self):
        onto = {
            "entities": [{"id": "A"}, {"id": "B"}, {"id": "C"}],
            "relationships": [
                {"source_id": "A", "target_id": "B"},
                {"source_id": "B", "target_id": "C"},
                {"source_id": "C", "target_id": "A"},
            ],
        }
        assert _lv.strongly_connected_component_sizes(onto) == [3]

    def test_sorted_descending(self):
        # Two cycles (A↔B) and (C↔D↔E) → sizes 3, 2 sorted desc
        onto = {
            "entities": [{"id": n} for n in ["A", "B", "C", "D", "E"]],
            "relationships": [
                {"source_id": "A", "target_id": "B"},
                {"source_id": "B", "target_id": "A"},
                {"source_id": "C", "target_id": "D"},
                {"source_id": "D", "target_id": "E"},
                {"source_id": "E", "target_id": "C"},
            ],
        }
        sizes = _lv.strongly_connected_component_sizes(onto)
        assert sizes == sorted(sizes, reverse=True)
        assert sizes[0] >= sizes[-1]

    def test_sum_equals_total_nodes(self):
        onto = {
            "entities": [{"id": n} for n in ["A", "B", "C", "D"]],
            "relationships": [
                {"source_id": "A", "target_id": "B"},
                {"source_id": "B", "target_id": "A"},
            ],
        }
        sizes = _lv.strongly_connected_component_sizes(onto)
        assert sum(sizes) == 4

    def test_returns_list(self):
        onto = {"entities": [{"id": "X"}], "relationships": []}
        assert isinstance(_lv.strongly_connected_component_sizes(onto), list)

    def test_all_sizes_positive(self):
        onto = {
            "entities": [{"id": n} for n in ["A", "B", "C"]],
            "relationships": [],
        }
        sizes = _lv.strongly_connected_component_sizes(onto)
        assert all(s > 0 for s in sizes)


# ---------------------------------------------------------------------------
# Stale smoke-tests for OntologyPipeline.run_score_acceleration
# ---------------------------------------------------------------------------

class TestRunScoreAcceleration:
    """Smoke-tests confirming run_score_acceleration already exists."""

    def _make_pipeline(self, scores):
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

    def test_empty_returns_zero(self):
        p = self._make_pipeline([])
        assert p.run_score_acceleration() == 0.0

    def test_single_returns_zero(self):
        p = self._make_pipeline([0.5])
        assert p.run_score_acceleration() == 0.0

    def test_two_returns_zero(self):
        p = self._make_pipeline([0.3, 0.7])
        # only one delta → no pair of deltas → acceleration = 0
        assert p.run_score_acceleration() == 0.0

    def test_constant_run_returns_zero(self):
        p = self._make_pipeline([0.5, 0.5, 0.5, 0.5])
        assert p.run_score_acceleration() == 0.0

    def test_linear_run_returns_zero(self):
        # Linear = constant first derivative → zero second derivative
        p = self._make_pipeline([0.1, 0.3, 0.5, 0.7])
        assert abs(p.run_score_acceleration()) < 1e-9

    def test_returns_float(self):
        p = self._make_pipeline([0.1, 0.5, 0.2])
        assert isinstance(p.run_score_acceleration(), float)
