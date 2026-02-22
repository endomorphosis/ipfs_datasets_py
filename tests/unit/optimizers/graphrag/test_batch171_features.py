"""Batch-171 feature tests.

Methods under test:
  - OntologyOptimizer.history_trimmed_mean(trim)
  - OntologyOptimizer.score_z_scores()
  - OntologyCritic.dimension_entropy(score)
  - OntologyCritic.compare_scores(before, after)
  - OntologyGenerator.top_confidence_fraction(result, frac)
  - OntologyGenerator.relationship_source_set(result)
  - OntologyGenerator.relationship_target_set(result)
  - OntologyPipeline.score_std()
  - OntologyPipeline.improvement_count()
  - OntologyPipeline.score_range()
"""
import pytest
from unittest.mock import MagicMock


def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg
        self.trend = "stable"


def _push_opt(o, avg):
    o._history.append(_FakeEntry(avg))


def _make_score(**kwargs):
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
    defaults = dict(
        completeness=0.5, consistency=0.5, clarity=0.5,
        granularity=0.5, relationship_coherence=0.5, domain_alignment=0.5,
    )
    defaults.update(kwargs)
    return CriticScore(**defaults)


def _make_critic():
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    return OntologyCritic(use_llm=False)


def _make_entity(eid, confidence=0.5):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="T", text=eid, confidence=confidence)


def _make_relationship(sid, tid):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
    return Relationship(id=f"{sid}-{tid}", type="r", source_id=sid, target_id=tid)


def _make_result(entities, rels=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities, relationships=rels or [], confidence=1.0, metadata={}, errors=[]
    )


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline()


def _push_run(p, score):
    r = MagicMock()
    r.score.overall = score
    p._run_history.append(r)


# ---------------------------------------------------------------------------
# OntologyOptimizer.history_trimmed_mean
# ---------------------------------------------------------------------------

class TestHistoryTrimmedMean:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_trimmed_mean() == pytest.approx(0.0)

    def test_no_trim_equals_mean(self):
        o = _make_optimizer()
        for v in [0.2, 0.5, 0.8]:
            _push_opt(o, v)
        assert o.history_trimmed_mean(trim=0.0) == pytest.approx(0.5)

    def test_trim_removes_extremes(self):
        o = _make_optimizer()
        for v in [0.0, 0.5, 0.5, 0.5, 1.0]:
            _push_opt(o, v)
        # 10% trim on 5 items → removes 0 (int(5*0.1)=0), same as no trim
        # Use 25% trim → removes 1 each end → [0.5, 0.5, 0.5] mean = 0.5
        result = o.history_trimmed_mean(trim=0.25)
        assert result == pytest.approx(0.5)

    def test_returns_float(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert isinstance(o.history_trimmed_mean(), float)


# ---------------------------------------------------------------------------
# OntologyOptimizer.score_z_scores
# ---------------------------------------------------------------------------

class TestScoreZScores:
    def test_empty_returns_empty(self):
        o = _make_optimizer()
        assert o.score_z_scores() == []

    def test_single_returns_empty(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.score_z_scores() == []

    def test_constant_returns_zeros(self):
        o = _make_optimizer()
        for _ in range(4):
            _push_opt(o, 0.5)
        result = o.score_z_scores()
        assert all(z == pytest.approx(0.0) for z in result)

    def test_known_z_scores(self):
        o = _make_optimizer()
        _push_opt(o, 0.0)
        _push_opt(o, 1.0)
        zs = o.score_z_scores()
        assert len(zs) == 2
        assert abs(zs[0]) == pytest.approx(abs(zs[1]))  # symmetric

    def test_length_matches_history(self):
        o = _make_optimizer()
        for v in [0.3, 0.5, 0.7, 0.9]:
            _push_opt(o, v)
        assert len(o.score_z_scores()) == 4


# ---------------------------------------------------------------------------
# OntologyCritic.dimension_entropy
# ---------------------------------------------------------------------------

class TestDimensionEntropy:
    def test_all_zero_returns_zero(self):
        critic = _make_critic()
        score = _make_score(completeness=0.0, consistency=0.0, clarity=0.0,
                            granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0)
        assert critic.dimension_entropy(score) == pytest.approx(0.0)

    def test_equal_values_max_entropy(self):
        critic = _make_critic()
        score = _make_score()  # all 0.5
        entropy = critic.dimension_entropy(score)
        # all equal → max entropy for 6 dims = log2(6)
        assert entropy == pytest.approx(pytest.approx(2.585, abs=0.01))

    def test_concentrated_low_entropy(self):
        critic = _make_critic()
        score = _make_score(completeness=1.0, consistency=0.0, clarity=0.0,
                            granularity=0.0, relationship_coherence=0.0, domain_alignment=0.0)
        assert critic.dimension_entropy(score) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# OntologyCritic.compare_scores
# ---------------------------------------------------------------------------

class TestCompareScores:
    def test_same_scores_zero_diffs(self):
        critic = _make_critic()
        score = _make_score()
        diffs = critic.compare_scores(score, score)
        for d in critic._DIMENSIONS:
            assert diffs[d] == pytest.approx(0.0)

    def test_improvement_reflected(self):
        critic = _make_critic()
        before = _make_score(completeness=0.3)
        after = _make_score(completeness=0.8)
        diffs = critic.compare_scores(before, after)
        assert diffs["completeness"] == pytest.approx(0.5)

    def test_has_overall_key(self):
        critic = _make_critic()
        diffs = critic.compare_scores(_make_score(), _make_score())
        assert "overall" in diffs


# ---------------------------------------------------------------------------
# OntologyGenerator.top_confidence_fraction
# ---------------------------------------------------------------------------

class TestTopConfidenceFraction:
    def test_empty_returns_empty(self):
        gen = _make_generator()
        assert gen.top_confidence_fraction(_make_result([]), 0.5) == []

    def test_top_half(self):
        gen = _make_generator()
        entities = [_make_entity("e1", 0.9), _make_entity("e2", 0.5), _make_entity("e3", 0.3), _make_entity("e4", 0.1)]
        result = gen.top_confidence_fraction(_make_result(entities), 0.5)
        assert len(result) == 2
        assert result[0].id == "e1"

    def test_full_fraction(self):
        gen = _make_generator()
        entities = [_make_entity("e1", 0.9), _make_entity("e2", 0.5)]
        result = gen.top_confidence_fraction(_make_result(entities), 1.0)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# OntologyGenerator.relationship_source_set / target_set
# ---------------------------------------------------------------------------

class TestRelationshipSets:
    def test_empty_result(self):
        gen = _make_generator()
        result = _make_result([], [])
        assert gen.relationship_source_set(result) == set()
        assert gen.relationship_target_set(result) == set()

    def test_sources_and_targets(self):
        gen = _make_generator()
        rels = [_make_relationship("a", "b"), _make_relationship("a", "c")]
        result = _make_result([], rels)
        assert gen.relationship_source_set(result) == {"a"}
        assert gen.relationship_target_set(result) == {"b", "c"}


# ---------------------------------------------------------------------------
# OntologyPipeline.score_std / improvement_count / score_range
# ---------------------------------------------------------------------------

class TestPipelineScoreStats:
    def test_std_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.score_std() == pytest.approx(0.0)

    def test_std_single_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.score_std() == pytest.approx(0.0)

    def test_std_known_value(self):
        p = _make_pipeline()
        _push_run(p, 0.0)
        _push_run(p, 1.0)
        # pop std of [0, 1] = 0.5
        assert p.score_std() == pytest.approx(0.5)

    def test_improvement_count_empty(self):
        p = _make_pipeline()
        assert p.improvement_count() == 0

    def test_improvement_count_all_improving(self):
        p = _make_pipeline()
        for v in [0.3, 0.5, 0.7, 0.9]:
            _push_run(p, v)
        assert p.improvement_count() == 3

    def test_improvement_count_none(self):
        p = _make_pipeline()
        for v in [0.9, 0.7, 0.5]:
            _push_run(p, v)
        assert p.improvement_count() == 0

    def test_score_range_empty(self):
        p = _make_pipeline()
        lo, hi = p.score_range()
        assert lo == pytest.approx(0.0)
        assert hi == pytest.approx(0.0)

    def test_score_range_value(self):
        p = _make_pipeline()
        for v in [0.2, 0.8, 0.5]:
            _push_run(p, v)
        lo, hi = p.score_range()
        assert lo == pytest.approx(0.2)
        assert hi == pytest.approx(0.8)
