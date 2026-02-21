"""Batch-174 feature tests.

Methods under test:
  - OntologyOptimizer.score_cumulative_min()
  - OntologyOptimizer.history_below_median_count()
  - OntologyPipeline.first_score()
  - OntologyPipeline.score_below_mean_count()
  - OntologyCritic.dimension_improvement_rate(before, after)
  - LogicValidator.leaf_node_count(ontology)
  - OntologyGenerator.relationship_confidence_mean(result)
  - OntologyGenerator.entities_above_confidence(result, threshold)
"""
import pytest
from unittest.mock import MagicMock


class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg
        self.trend = "stable"


def _push_opt(o, avg):
    o._history.append(_FakeEntry(avg))


def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


def _make_pipeline():
    from ipfs_datasets_py.optimizers.graphrag.ontology_pipeline import OntologyPipeline
    return OntologyPipeline()


def _push_run(p, score):
    r = MagicMock()
    r.score.overall = score
    p._run_history.append(r)


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


class _FakeRel:
    def __init__(self, src, tgt, confidence=1.0):
        self.source_id = src
        self.target_id = tgt
        self.type = "r"
        self.confidence = confidence


class _FakeOntology:
    def __init__(self, rels):
        self.relationships = rels


def _make_entity(eid, confidence=0.5):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="T", text=eid, confidence=confidence)


def _make_result(entities, rels=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities, relationships=rels or [], confidence=1.0, metadata={}, errors=[]
    )


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


# ── OntologyOptimizer.score_cumulative_min ────────────────────────────────────

class TestScoreCumulativeMin:
    def test_empty_returns_empty(self):
        o = _make_optimizer()
        assert o.score_cumulative_min() == []

    def test_values(self):
        o = _make_optimizer()
        for v in [0.8, 0.3, 0.6, 0.2]:
            _push_opt(o, v)
        assert o.score_cumulative_min() == pytest.approx([0.8, 0.3, 0.3, 0.2])

    def test_monotone_decreasing(self):
        o = _make_optimizer()
        for v in [1.0, 0.8, 0.6]:
            _push_opt(o, v)
        assert o.score_cumulative_min() == pytest.approx([1.0, 0.8, 0.6])

    def test_length_matches_history(self):
        o = _make_optimizer()
        for v in [0.5, 0.7, 0.4]:
            _push_opt(o, v)
        assert len(o.score_cumulative_min()) == 3


# ── OntologyOptimizer.history_below_median_count ──────────────────────────────

class TestHistoryBelowMedianCount:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.history_below_median_count() == 0

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.history_below_median_count() == 0

    def test_basic(self):
        o = _make_optimizer()
        for v in [0.2, 0.5, 0.8]:
            _push_opt(o, v)
        # median = 0.5; only 0.2 < 0.5
        assert o.history_below_median_count() == 1

    def test_all_same(self):
        o = _make_optimizer()
        for _ in range(4):
            _push_opt(o, 0.5)
        assert o.history_below_median_count() == 0


# ── OntologyPipeline.first_score ──────────────────────────────────────────────

class TestPipelineFirstScore:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.first_score() == pytest.approx(0.0)

    def test_returns_first(self):
        p = _make_pipeline()
        _push_run(p, 0.6)
        _push_run(p, 0.9)
        assert p.first_score() == pytest.approx(0.6)


# ── OntologyPipeline.score_below_mean_count ───────────────────────────────────

class TestScoreBelowMeanCount:
    def test_empty_returns_zero(self):
        p = _make_pipeline()
        assert p.score_below_mean_count() == 0

    def test_single_returns_zero(self):
        p = _make_pipeline()
        _push_run(p, 0.5)
        assert p.score_below_mean_count() == 0

    def test_below_mean(self):
        p = _make_pipeline()
        for v in [0.2, 0.5, 0.8]:
            _push_run(p, v)
        # mean = 0.5; only 0.2 is strictly below
        assert p.score_below_mean_count() == 1

    def test_all_same_returns_zero(self):
        p = _make_pipeline()
        for _ in range(3):
            _push_run(p, 0.5)
        assert p.score_below_mean_count() == 0


# ── OntologyCritic.dimension_improvement_rate ────────────────────────────────

class TestDimensionImprovementRate:
    def test_all_improved_returns_one(self):
        c = _make_critic()
        before = _make_score(**{d: 0.3 for d in ["completeness", "consistency", "clarity",
                                                  "granularity", "relationship_coherence", "domain_alignment"]})
        after = _make_score(**{d: 0.8 for d in ["completeness", "consistency", "clarity",
                                                 "granularity", "relationship_coherence", "domain_alignment"]})
        assert c.dimension_improvement_rate(before, after) == pytest.approx(1.0)

    def test_none_improved_returns_zero(self):
        c = _make_critic()
        assert c.dimension_improvement_rate(_make_score(), _make_score()) == pytest.approx(0.0)

    def test_half_improved(self):
        c = _make_critic()
        before = _make_score(completeness=0.3, consistency=0.7, clarity=0.3,
                             granularity=0.7, relationship_coherence=0.3, domain_alignment=0.7)
        after = _make_score(completeness=0.8, consistency=0.7, clarity=0.8,
                            granularity=0.7, relationship_coherence=0.8, domain_alignment=0.7)
        rate = c.dimension_improvement_rate(before, after)
        assert rate == pytest.approx(0.5)


# ── LogicValidator.leaf_node_count ────────────────────────────────────────────

class TestLeafNodeCount:
    def test_no_rels_returns_zero(self):
        v = _make_validator()
        assert v.leaf_node_count(_FakeOntology([])) == 0

    def test_chain_has_one_leaf(self):
        v = _make_validator()
        rels = [_FakeRel("a", "b"), _FakeRel("b", "c")]
        assert v.leaf_node_count(_FakeOntology(rels)) == 1

    def test_all_sinks(self):
        v = _make_validator()
        rels = [_FakeRel("root", "x"), _FakeRel("root", "y")]
        assert v.leaf_node_count(_FakeOntology(rels)) == 2

    def test_cycle_no_leaves(self):
        v = _make_validator()
        rels = [_FakeRel("a", "b"), _FakeRel("b", "c"), _FakeRel("c", "a")]
        assert v.leaf_node_count(_FakeOntology(rels)) == 0


# ── OntologyGenerator.relationship_confidence_mean ───────────────────────────

class TestRelationshipConfidenceMean:
    def test_empty_returns_zero(self):
        gen = _make_generator()
        assert gen.relationship_confidence_mean(_make_result([], [])) == pytest.approx(0.0)

    def test_single_relationship(self):
        gen = _make_generator()
        rels = [_FakeRel("a", "b", confidence=0.8)]
        # Use actual Relationship objects
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
        r = Relationship(id="r1", type="t", source_id="a", target_id="b", confidence=0.8)
        assert gen.relationship_confidence_mean(_make_result([], [r])) == pytest.approx(0.8)

    def test_mean_of_two(self):
        gen = _make_generator()
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Relationship
        rels = [
            Relationship(id="r1", type="t", source_id="a", target_id="b", confidence=0.6),
            Relationship(id="r2", type="t", source_id="b", target_id="c", confidence=0.4),
        ]
        assert gen.relationship_confidence_mean(_make_result([], rels)) == pytest.approx(0.5)


# ── OntologyGenerator.entities_above_confidence ──────────────────────────────

class TestEntitiesAboveConfidence:
    def test_empty_returns_empty(self):
        gen = _make_generator()
        assert gen.entities_above_confidence(_make_result([])) == []

    def test_none_above_threshold(self):
        gen = _make_generator()
        entities = [_make_entity("e1", 0.3), _make_entity("e2", 0.5)]
        assert gen.entities_above_confidence(_make_result(entities), 0.7) == []

    def test_some_above(self):
        gen = _make_generator()
        entities = [_make_entity("e1", 0.9), _make_entity("e2", 0.3)]
        result = gen.entities_above_confidence(_make_result(entities), 0.7)
        assert len(result) == 1
        assert result[0].id == "e1"
