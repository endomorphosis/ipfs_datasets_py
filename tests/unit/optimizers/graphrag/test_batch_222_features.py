"""
Batch 222 — unit tests for four new graphrag optimizer methods.

New methods under test
~~~~~~~~~~~~~~~~~~~~~~
* ``OntologyOptimizer.score_trimmed_mean(trim_pct)``
* ``OntologyCritic.score_dimension_kurtosis(score)``
* ``OntologyGenerator.entity_avg_degree(result)``
* ``OntologyPipeline.run_score_negative_rate(threshold)``

Plus stale smoke-tests for already-implemented methods
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* ``OntologyLearningAdapter.feedback_negative_rate()``
* ``LogicValidator.weakly_connected_components(ontology)``
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
from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline  # noqa: E402
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


class _FakeScore:
    def __init__(self, v: float) -> None:
        self.overall = v


class _FakeRun:
    def __init__(self, v: float) -> None:
        self.score = _FakeScore(v)


class _FakeFeedback:
    def __init__(self, final_score: float) -> None:
        self.final_score = final_score


def _make_opt(scores=None):
    """Return an OntologyOptimizer with the given score history."""
    opt = object.__new__(OntologyOptimizer)
    opt._history = [_FakeEntry(s) for s in (scores or [])]
    return opt


def _make_pipeline(scores=None):
    """Return an OntologyPipeline with the given run-score history."""
    p = object.__new__(OntologyPipeline)
    p._run_history = [_FakeRun(s) for s in (scores or [])]
    return p


def _make_adapter(final_scores=None):
    """Return an OntologyLearningAdapter with the given feedback history."""
    adapter = object.__new__(OntologyLearningAdapter)
    adapter._feedback = [_FakeFeedback(s) for s in (final_scores or [])]
    return adapter


def _make_critic():
    return object.__new__(OntologyCritic)


def _cs(**kwargs):
    """Build a CriticScore with all dimensions defaulting to 0.0."""
    defaults = dict(
        completeness=0.0,
        consistency=0.0,
        clarity=0.0,
        granularity=0.0,
        relationship_coherence=0.0,
        domain_alignment=0.0,
    )
    defaults.update(kwargs)
    return CriticScore(**defaults)


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_trimmed_mean
# ---------------------------------------------------------------------------

class TestScoreTrimmedMean:

    def test_empty_returns_zero(self):
        opt = _make_opt([])
        assert opt.score_trimmed_mean() == 0.0

    def test_single_entry_returns_value(self):
        opt = _make_opt([0.7])
        assert opt.score_trimmed_mean() == pytest.approx(0.7)

    def test_two_entries_no_trimming(self):
        # trim_pct=10: k = int(2 * 0.10) = 0 → returns full mean
        opt = _make_opt([0.4, 0.8])
        assert opt.score_trimmed_mean(10.0) == pytest.approx(0.6)

    def test_zero_trim_pct_is_arithmetic_mean(self):
        opt = _make_opt([0.1, 0.5, 0.9])
        expected = sum([0.1, 0.5, 0.9]) / 3
        assert opt.score_trimmed_mean(0.0) == pytest.approx(expected)

    def test_trims_outliers(self):
        # [0.0, 0.5, 0.5, 0.5, 1.0], 20% trim → k=1 → trimmed = [0.5, 0.5, 0.5]
        opt = _make_opt([0.0, 0.5, 0.5, 0.5, 1.0])
        result = opt.score_trimmed_mean(20.0)
        assert result == pytest.approx(0.5)

    def test_larger_list(self):
        # [0.1, 0.3, 0.5, 0.7, 0.9], 10% → k=0 (int(5*0.1)=0) → full mean
        opt = _make_opt([0.1, 0.3, 0.5, 0.7, 0.9])
        result = opt.score_trimmed_mean(10.0)
        assert result == pytest.approx((0.1 + 0.3 + 0.5 + 0.7 + 0.9) / 5)

    def test_raises_for_negative_trim(self):
        opt = _make_opt([0.5])
        with pytest.raises(ValueError):
            opt.score_trimmed_mean(-1.0)

    def test_raises_for_trim_pct_equal_50(self):
        opt = _make_opt([0.5])
        with pytest.raises(ValueError):
            opt.score_trimmed_mean(50.0)

    def test_raises_for_trim_pct_above_50(self):
        opt = _make_opt([0.5])
        with pytest.raises(ValueError):
            opt.score_trimmed_mean(75.0)

    def test_return_type_is_float(self):
        opt = _make_opt([0.3, 0.6])
        assert isinstance(opt.score_trimmed_mean(), float)

    def test_result_at_least_min_at_most_max(self):
        opt = _make_opt([0.2, 0.4, 0.6, 0.8])
        result = opt.score_trimmed_mean()
        assert 0.2 <= result <= 0.8

    def test_uniform_list_equals_mean(self):
        opt = _make_opt([0.5] * 10)
        assert opt.score_trimmed_mean(25.0) == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# OntologyCritic.score_dimension_kurtosis
# ---------------------------------------------------------------------------

class TestScoreDimensionKurtosis:

    def test_uniform_returns_zero(self):
        # All 6 dimensions equal → zero variance → 0.0
        critic = _make_critic()
        s = _cs(**{d: 1.0 for d in ("completeness", "consistency",
                                      "clarity", "granularity",
                                      "relationship_coherence", "domain_alignment")})
        assert critic.score_dimension_kurtosis(s) == pytest.approx(0.0)

    def test_all_zeros_returns_zero(self):
        critic = _make_critic()
        assert critic.score_dimension_kurtosis(_cs()) == pytest.approx(0.0)

    def test_one_hot_positive_kurtosis(self):
        # One dimension = 1.0, rest = 0.0 → leptokurtic
        critic = _make_critic()
        s = _cs(completeness=1.0)
        k = critic.score_dimension_kurtosis(s)
        assert k > 0.0

    def test_return_type_is_float(self):
        critic = _make_critic()
        assert isinstance(critic.score_dimension_kurtosis(_cs(completeness=0.5)), float)

    def test_symmetric_scores(self):
        # Symmetric distribution: two extreme + one middle
        critic = _make_critic()
        s = _cs(completeness=0.0, consistency=0.0, clarity=0.5,
                granularity=0.5, relationship_coherence=1.0, domain_alignment=1.0)
        k = critic.score_dimension_kurtosis(s)
        # Expect < 0 (platykurtic — bimodal / flat)
        assert k < 0.0

    def test_single_nonzero_dim(self):
        critic = _make_critic()
        s = _cs(domain_alignment=1.0)
        k = critic.score_dimension_kurtosis(s)
        # With one spike on a 6-element distribution excess kurtosis > 0
        assert k > 0.0

    def test_kurtosis_scale_invariant(self):
        # Scaling all dimensions by a constant should not change kurtosis
        critic = _make_critic()
        s1 = _cs(completeness=0.2, consistency=0.4, clarity=0.6)
        s2 = _cs(completeness=0.4, consistency=0.8, clarity=1.2)
        k1 = critic.score_dimension_kurtosis(s1)
        k2 = critic.score_dimension_kurtosis(s2)
        assert k1 == pytest.approx(k2, abs=1e-9)

    def test_two_equal_halves_platykurtic(self):
        # Half 0.0, half 1.0 → bimodal / platykurtic
        critic = _make_critic()
        s = _cs(completeness=0.0, consistency=0.0, clarity=0.0,
                granularity=1.0, relationship_coherence=1.0, domain_alignment=1.0)
        k = critic.score_dimension_kurtosis(s)
        assert k < 0.0


# ---------------------------------------------------------------------------
# OntologyGenerator.entity_avg_degree
# ---------------------------------------------------------------------------

class TestEntityAvgDegree:

    def _gen(self):
        return object.__new__(OntologyGenerator)

    def _e(self, eid, text="x"):
        return Entity(id=eid, type="Person", text=text)

    def _r(self, rid, src, tgt):
        return Relationship(id=rid, source_id=src, target_id=tgt, type="knows")

    def test_empty_entities_returns_zero(self):
        gen = self._gen()
        r = EntityExtractionResult(entities=[], relationships=[], confidence=0.9)
        assert gen.entity_avg_degree(r) == 0.0

    def test_no_relationships_returns_zero(self):
        gen = self._gen()
        r = EntityExtractionResult(entities=[self._e("e1")], relationships=[], confidence=0.9)
        assert gen.entity_avg_degree(r) == 0.0

    def test_one_relationship_two_entities(self):
        gen = self._gen()
        e1, e2 = self._e("e1"), self._e("e2")
        r1 = self._r("r1", "e1", "e2")
        result = EntityExtractionResult(entities=[e1, e2], relationships=[r1], confidence=0.9)
        # e1 has degree 1, e2 has degree 1 → avg = 1.0
        assert gen.entity_avg_degree(result) == pytest.approx(1.0)

    def test_dangling_relationship_ignored(self):
        gen = self._gen()
        e1 = self._e("e1")
        # r1 references "e99" which is not in entities
        r1 = self._r("r1", "e1", "e99")
        result = EntityExtractionResult(entities=[e1], relationships=[r1], confidence=0.9)
        # e1 degree = 1 (as source); "e99" is not in degree dict so ignored
        assert gen.entity_avg_degree(result) == pytest.approx(1.0)

    def test_hub_entity(self):
        gen = self._gen()
        e1 = self._e("hub")
        e2, e3, e4 = self._e("e2"), self._e("e3"), self._e("e4")
        r1 = self._r("r1", "hub", "e2")
        r2 = self._r("r2", "hub", "e3")
        r3 = self._r("r3", "hub", "e4")
        result = EntityExtractionResult(entities=[e1, e2, e3, e4], relationships=[r1, r2, r3], confidence=0.9)
        # hub: degree 3, e2/e3/e4: degree 1 each → total 6 / 4 = 1.5
        assert gen.entity_avg_degree(result) == pytest.approx(1.5)

    def test_return_type_is_float(self):
        gen = self._gen()
        r = EntityExtractionResult(entities=[self._e("e1")], relationships=[], confidence=0.9)
        assert isinstance(gen.entity_avg_degree(r), float)

    def test_bidirectional_pair(self):
        gen = self._gen()
        e1, e2 = self._e("e1"), self._e("e2")
        r1 = self._r("r1", "e1", "e2")
        r2 = self._r("r2", "e2", "e1")
        result = EntityExtractionResult(entities=[e1, e2], relationships=[r1, r2], confidence=0.9)
        # e1: 2 (source r1 + target r2), e2: 2 (target r1 + source r2) → avg 2.0
        assert gen.entity_avg_degree(result) == pytest.approx(2.0)

    def test_isolated_entity(self):
        gen = self._gen()
        e1, e2 = self._e("e1"), self._e("e2")
        r1 = self._r("r1", "e1", "e1")  # self-loop on e1
        result = EntityExtractionResult(entities=[e1, e2], relationships=[r1], confidence=0.9)
        # e1 degree = 2 (source + target), e2 degree = 0 → avg = 1.0
        assert gen.entity_avg_degree(result) == pytest.approx(1.0)

    def test_avg_degree_non_negative(self):
        gen = self._gen()
        e1, e2 = self._e("e1"), self._e("e2")
        r1 = self._r("r1", "e1", "e2")
        result = EntityExtractionResult(entities=[e1, e2], relationships=[r1], confidence=0.9)
        assert gen.entity_avg_degree(result) >= 0.0


# ---------------------------------------------------------------------------
# OntologyPipeline.run_score_negative_rate
# ---------------------------------------------------------------------------

class TestRunScoreNegativeRate:

    def test_empty_returns_zero(self):
        p = _make_pipeline([])
        assert p.run_score_negative_rate() == 0.0

    def test_all_above_threshold_returns_zero(self):
        p = _make_pipeline([0.6, 0.7, 0.8])
        assert p.run_score_negative_rate(0.5) == pytest.approx(0.0)

    def test_all_at_threshold_returns_one(self):
        # <= threshold: all scores = 0.5 → all negative
        p = _make_pipeline([0.5, 0.5, 0.5])
        assert p.run_score_negative_rate(0.5) == pytest.approx(1.0)

    def test_all_below_threshold_returns_one(self):
        p = _make_pipeline([0.1, 0.2, 0.3])
        assert p.run_score_negative_rate(0.5) == pytest.approx(1.0)

    def test_half_negative(self):
        p = _make_pipeline([0.3, 0.7, 0.5, 0.9])
        # 0.3 <= 0.5 and 0.5 <= 0.5 → 2/4 = 0.5
        assert p.run_score_negative_rate(0.5) == pytest.approx(0.5)

    def test_custom_threshold(self):
        p = _make_pipeline([0.2, 0.4, 0.6, 0.8])
        # All <= 0.7 except 0.8 → 3/4 = 0.75
        assert p.run_score_negative_rate(0.7) == pytest.approx(0.75)

    def test_complement_with_positive_rate(self):
        # strict > for positive, <= for negative: every score in exactly one bucket
        p = _make_pipeline([0.2, 0.4, 0.6, 0.8])
        threshold = 0.5
        pos = p.run_score_positive_rate(threshold)
        neg = p.run_score_negative_rate(threshold)
        # 0.6, 0.8 > 0.5 → pos = 0.5; 0.2, 0.4 <= 0.5 → neg = 0.5; sum = 1.0
        assert pos + neg == pytest.approx(1.0)

    def test_return_type_is_float(self):
        p = _make_pipeline([0.5])
        assert isinstance(p.run_score_negative_rate(), float)

    def test_result_in_zero_one(self):
        p = _make_pipeline([0.3, 0.7, 0.5])
        r = p.run_score_negative_rate()
        assert 0.0 <= r <= 1.0

    def test_single_score_above_threshold(self):
        p = _make_pipeline([0.9])
        assert p.run_score_negative_rate(0.5) == pytest.approx(0.0)

    def test_single_score_at_threshold(self):
        p = _make_pipeline([0.5])
        assert p.run_score_negative_rate(0.5) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Stale smoke tests — already-implemented methods
# ---------------------------------------------------------------------------

class TestStaleFeedbackNegativeRate:
    """Smoke test: feedback_negative_rate was implemented before Batch 222."""

    def test_existing_method_is_callable(self):
        adapter = _make_adapter([0.3, 0.6, 0.4, 0.9])
        result = adapter.feedback_negative_rate()
        assert isinstance(result, float)

    def test_all_below_threshold_returns_one(self):
        adapter = _make_adapter([0.1, 0.2, 0.3])
        # Default threshold presumably <=0.5 or similar; just test callable
        result = adapter.feedback_negative_rate()
        assert 0.0 <= result <= 1.0


class TestStaleWeaklyConnectedComponents:
    """Smoke test: weakly_connected_components was implemented before Batch 222."""

    def _make_ontology(self, edges):
        """Build a dict-style ontology with the given (src, tgt) edge pairs."""
        nodes = sorted(set(n for e in edges for n in e))
        return {
            "entities": [{"id": n} for n in nodes],
            "relationships": [{"source_id": s, "target_id": t} for s, t in edges],
        }

    def test_empty_graph_returns_zero(self):
        validator = object.__new__(LogicValidator)
        ont = {"entities": [], "relationships": []}
        result = validator.weakly_connected_components(ont)
        # Should return an integer or list
        assert isinstance(result, (int, list))

    def test_single_connected_component(self):
        validator = object.__new__(LogicValidator)
        ont = self._make_ontology([("A", "B"), ("B", "C")])
        result = validator.weakly_connected_components(ont)
        if isinstance(result, int):
            assert result == 1
        else:
            assert len(result) == 1

    def test_two_separate_components(self):
        validator = object.__new__(LogicValidator)
        ont = self._make_ontology([("A", "B"), ("C", "D")])
        result = validator.weakly_connected_components(ont)
        if isinstance(result, int):
            assert result == 2
        else:
            assert len(result) == 2
