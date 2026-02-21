"""Batch-173 feature tests.

Methods under test:
  - OntologyGenerator.confidence_quartiles(result)
  - LogicValidator.triangle_count(ontology)
  - OntologyLearningAdapter.feedback_score_std()
  - OntologyLearningAdapter.feedback_last_improvement()
  - OntologyCritic.top_k_dimensions(score, k)
"""
import pytest


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


class _FakeRel:
    def __init__(self, src, tgt):
        self.source_id = src
        self.target_id = tgt
        self.type = "r"


class _FakeOntology:
    def __init__(self, rels):
        self.relationships = rels


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push_feedback(adapter, score):
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import FeedbackRecord
    adapter._feedback.append(FeedbackRecord(final_score=score))


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


# ── OntologyGenerator.confidence_quartiles ───────────────────────────────────

class TestConfidenceQuartiles:
    def test_empty_returns_zeros(self):
        gen = _make_generator()
        q = gen.confidence_quartiles(_make_result([]))
        assert q == {"q1": 0.0, "q2": 0.0, "q3": 0.0}

    def test_single_entity_all_same(self):
        gen = _make_generator()
        q = gen.confidence_quartiles(_make_result([_make_entity("e1", 0.7)]))
        assert q["q1"] == pytest.approx(0.7)
        assert q["q2"] == pytest.approx(0.7)
        assert q["q3"] == pytest.approx(0.7)

    def test_four_entities_ordering(self):
        gen = _make_generator()
        entities = [_make_entity(f"e{i}", c) for i, c in enumerate([0.1, 0.4, 0.6, 0.9])]
        q = gen.confidence_quartiles(_make_result(entities))
        assert q["q1"] <= q["q2"] <= q["q3"]

    def test_returns_dict_with_correct_keys(self):
        gen = _make_generator()
        q = gen.confidence_quartiles(_make_result([_make_entity("e1")]))
        assert set(q.keys()) == {"q1", "q2", "q3"}


# ── LogicValidator.triangle_count ─────────────────────────────────────────────

class TestTriangleCount:
    def test_empty_returns_zero(self):
        v = _make_validator()
        assert v.triangle_count(_FakeOntology([])) == 0

    def test_no_cycle_returns_zero(self):
        v = _make_validator()
        rels = [_FakeRel("a", "b"), _FakeRel("b", "c")]
        assert v.triangle_count(_FakeOntology(rels)) == 0

    def test_one_triangle(self):
        v = _make_validator()
        rels = [_FakeRel("a", "b"), _FakeRel("b", "c"), _FakeRel("c", "a")]
        assert v.triangle_count(_FakeOntology(rels)) == 1

    def test_two_triangles(self):
        v = _make_validator()
        rels = [
            _FakeRel("a", "b"), _FakeRel("b", "c"), _FakeRel("c", "a"),
            _FakeRel("x", "y"), _FakeRel("y", "z"), _FakeRel("z", "x"),
        ]
        assert v.triangle_count(_FakeOntology(rels)) == 2


# ── OntologyLearningAdapter.feedback_score_std ───────────────────────────────

class TestFeedbackScoreStd:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_score_std() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_score_std() == pytest.approx(0.0)

    def test_known_std(self):
        a = _make_adapter()
        _push_feedback(a, 0.0)
        _push_feedback(a, 1.0)
        assert a.feedback_score_std() == pytest.approx(0.5)

    def test_constant_scores_zero_std(self):
        a = _make_adapter()
        for _ in range(4):
            _push_feedback(a, 0.7)
        assert a.feedback_score_std() == pytest.approx(0.0)


# ── OntologyLearningAdapter.feedback_last_improvement ────────────────────────

class TestFeedbackLastImprovement:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.feedback_last_improvement() == pytest.approx(0.0)

    def test_single_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.5)
        assert a.feedback_last_improvement() == pytest.approx(0.0)

    def test_improving_returns_delta(self):
        a = _make_adapter()
        _push_feedback(a, 0.3)
        _push_feedback(a, 0.7)
        assert a.feedback_last_improvement() == pytest.approx(0.4)

    def test_declining_returns_zero(self):
        a = _make_adapter()
        _push_feedback(a, 0.9)
        _push_feedback(a, 0.4)
        assert a.feedback_last_improvement() == pytest.approx(0.0)

    def test_last_improvement_in_middle(self):
        a = _make_adapter()
        _push_feedback(a, 0.3)
        _push_feedback(a, 0.6)  # improve by 0.3
        _push_feedback(a, 0.4)  # decline
        # last improvement was step 1→2
        assert a.feedback_last_improvement() == pytest.approx(0.3)


# ── OntologyCritic.top_k_dimensions ──────────────────────────────────────────

class TestTopKDimensions:
    def test_top1_returns_single_item(self):
        critic = _make_critic()
        score = _make_score(completeness=0.9, consistency=0.3)
        top = critic.top_k_dimensions(score, k=1)
        assert top == ["completeness"]

    def test_top3_ordering(self):
        critic = _make_critic()
        score = _make_score(
            completeness=0.9, consistency=0.7, clarity=0.5,
            granularity=0.4, relationship_coherence=0.3, domain_alignment=0.1
        )
        top = critic.top_k_dimensions(score, k=3)
        assert top == ["completeness", "consistency", "clarity"]

    def test_k_larger_than_dims_clamped(self):
        critic = _make_critic()
        top = critic.top_k_dimensions(_make_score(), k=100)
        assert len(top) == 6

    def test_k_zero_returns_empty(self):
        critic = _make_critic()
        assert critic.top_k_dimensions(_make_score(), k=0) == []
