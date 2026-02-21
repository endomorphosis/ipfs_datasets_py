"""Batch-175 feature tests.

Methods under test:
  - OntologyOptimizer.score_trend_strength()
  - OntologyLearningAdapter.feedback_volatility()
  - OntologyLearningAdapter.feedback_trend_direction()
  - OntologyGenerator.entity_type_entropy(result)
  - LogicValidator.root_node_count(ontology)
  - LogicValidator.isolated_node_count(ontology)
  - OntologyCritic.dimension_weighted_sum(score, weights)
"""
import pytest


class _FakeEntry:
    def __init__(self, avg):
        self.average_score = avg
        self.trend = "stable"


def _push_opt(o, avg):
    o._history.append(_FakeEntry(avg))


def _make_optimizer():
    from ipfs_datasets_py.optimizers.graphrag.ontology_optimizer import OntologyOptimizer
    return OntologyOptimizer()


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(adapter, score):
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import FeedbackRecord
    adapter._feedback.append(FeedbackRecord(final_score=score))


def _make_entity(eid, etype="T", confidence=0.5):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type=etype, text=eid, confidence=confidence)


def _make_result(entities, rels=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities, relationships=rels or [], confidence=1.0, metadata={}, errors=[]
    )


def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


class _FakeRel:
    def __init__(self, src, tgt):
        self.source_id = src
        self.target_id = tgt
        self.type = "r"


class _FakeOntology:
    def __init__(self, rels, entities=None):
        self.relationships = rels
        if entities is not None:
            self.entities = entities


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


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


# ── OntologyOptimizer.score_trend_strength ────────────────────────────────────

class TestScoreTrendStrength:
    def test_empty_returns_zero(self):
        o = _make_optimizer()
        assert o.score_trend_strength() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        assert o.score_trend_strength() == pytest.approx(0.0)

    def test_constant_returns_zero(self):
        o = _make_optimizer()
        for _ in range(4):
            _push_opt(o, 0.5)
        assert o.score_trend_strength() == pytest.approx(0.0)

    def test_strong_uptrend_positive(self):
        o = _make_optimizer()
        for v in [0.1, 0.3, 0.5, 0.7, 0.9]:
            _push_opt(o, v)
        assert o.score_trend_strength() > 0

    def test_returns_float(self):
        o = _make_optimizer()
        _push_opt(o, 0.5)
        _push_opt(o, 0.7)
        assert isinstance(o.score_trend_strength(), float)


# ── OntologyLearningAdapter.feedback_volatility ───────────────────────────────

class TestFeedbackVolatility:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_volatility() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_volatility() == pytest.approx(0.0)

    def test_constant_returns_zero(self):
        a = _make_adapter()
        for _ in range(4):
            _push_feedback(a, 0.5)
        assert a.feedback_volatility() == pytest.approx(0.0)

    def test_alternating_high_volatility(self):
        a = _make_adapter()
        _push_feedback(a, 0.0)
        _push_feedback(a, 1.0)
        _push_feedback(a, 0.0)
        # mean |1-0| + |0-1| / 2 = 1.0
        assert a.feedback_volatility() == pytest.approx(1.0)


# ── OntologyLearningAdapter.feedback_trend_direction ─────────────────────────

class TestFeedbackTrendDirection:
    def test_empty_returns_flat(self):
        a = _make_adapter()
        assert a.feedback_trend_direction() == "stable"

    def test_single_returns_flat(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_trend_direction() == "stable"

    def test_uptrend(self):
        a = _make_adapter()
        for v in [0.2, 0.5, 0.8]:
            _push_feedback(a, v)
        assert a.feedback_trend_direction() == "improving"

    def test_downtrend(self):
        a = _make_adapter()
        for v in [0.8, 0.5, 0.2]:
            _push_feedback(a, v)
        assert a.feedback_trend_direction() == "declining"


# ── OntologyGenerator.entity_type_entropy ────────────────────────────────────

class TestEntityTypeEntropy:
    def test_empty_returns_zero(self):
        gen = _make_generator()
        assert gen.entity_type_entropy(_make_result([])) == pytest.approx(0.0)

    def test_all_same_type_returns_zero(self):
        gen = _make_generator()
        entities = [_make_entity(f"e{i}", "T") for i in range(4)]
        assert gen.entity_type_entropy(_make_result(entities)) == pytest.approx(0.0)

    def test_equal_types_max_entropy(self):
        gen = _make_generator()
        entities = [_make_entity("e1", "A"), _make_entity("e2", "B"),
                    _make_entity("e3", "C"), _make_entity("e4", "D")]
        entropy = gen.entity_type_entropy(_make_result(entities))
        # 4 equal types → log2(4) = 2.0
        assert entropy == pytest.approx(2.0)

    def test_two_types_half_entropy(self):
        gen = _make_generator()
        entities = [_make_entity("e1", "A"), _make_entity("e2", "B")]
        assert gen.entity_type_entropy(_make_result(entities)) == pytest.approx(1.0)


# ── LogicValidator.root_node_count ────────────────────────────────────────────

class TestRootNodeCount:
    def test_no_rels_returns_zero(self):
        v = _make_validator()
        assert v.root_node_count(_FakeOntology([])) == 0

    def test_chain_has_one_root(self):
        v = _make_validator()
        rels = [_FakeRel("a", "b"), _FakeRel("b", "c")]
        assert v.root_node_count(_FakeOntology(rels)) == 1

    def test_cycle_no_roots(self):
        v = _make_validator()
        rels = [_FakeRel("a", "b"), _FakeRel("b", "c"), _FakeRel("c", "a")]
        assert v.root_node_count(_FakeOntology(rels)) == 0

    def test_multiple_roots(self):
        v = _make_validator()
        rels = [_FakeRel("r1", "c"), _FakeRel("r2", "c")]
        assert v.root_node_count(_FakeOntology(rels)) == 2


# ── LogicValidator.isolated_node_count ───────────────────────────────────────

class TestIsolatedNodeCount:
    def _entity(self, eid):
        from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
        return Entity(id=eid, type="T", text=eid)

    def test_no_entities_attr_returns_zero(self):
        v = _make_validator()
        assert v.isolated_node_count(_FakeOntology([])) == 0

    def test_all_connected(self):
        v = _make_validator()
        rels = [_FakeRel("a", "b")]
        entities = [self._entity("a"), self._entity("b")]
        onto = _FakeOntology(rels, entities=entities)
        assert v.isolated_node_count(onto) == 0

    def test_isolated_node(self):
        v = _make_validator()
        rels = [_FakeRel("a", "b")]
        entities = [self._entity("a"), self._entity("b"), self._entity("c")]
        onto = _FakeOntology(rels, entities=entities)
        assert v.isolated_node_count(onto) == 1


# ── OntologyCritic.dimension_weighted_sum ────────────────────────────────────

class TestDimensionWeightedSum:
    def test_equal_weights_equals_sum(self):
        c = _make_critic()
        score = _make_score()  # all 0.5
        ws = c.dimension_weighted_sum(score, weights={d: 1.0 for d in c._DIMENSIONS})
        assert ws == pytest.approx(3.0)  # 6 * 0.5

    def test_custom_weights(self):
        c = _make_critic()
        score = _make_score(completeness=1.0)
        weights = {d: 0.0 for d in c._DIMENSIONS}
        weights["completeness"] = 2.0
        assert c.dimension_weighted_sum(score, weights=weights) == pytest.approx(2.0)

    def test_default_weights_non_negative(self):
        c = _make_critic()
        result = c.dimension_weighted_sum(_make_score())
        assert result >= 0.0
