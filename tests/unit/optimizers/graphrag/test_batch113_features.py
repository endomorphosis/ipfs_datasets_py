"""Batch-113 feature tests.

Methods under test:
  - EntityExtractionResult.confidence_stats()
  - OntologyCritic.compare_runs(score_a, score_b)
  - OntologyLearningAdapter.reset_and_load(records)
  - OntologyMediator.reset_action_counts()
  - LogicValidator.count_relationship_types(ontology)
"""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _entity(eid, etype="Person", text="Alice", confidence=0.9):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type=etype, text=text, confidence=confidence)


def _result(entities=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities or [],
        relationships=[],
        confidence=1.0,
    )


def _make_critic():
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    return OntologyCritic(use_llm=False)


def _make_score(v):
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import CriticScore
    return CriticScore(completeness=v, consistency=v, clarity=v, granularity=v, domain_alignment=v)


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _make_mediator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_mediator import OntologyMediator
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    from ipfs_datasets_py.optimizers.graphrag.ontology_critic import OntologyCritic
    return OntologyMediator(generator=OntologyGenerator(), critic=OntologyCritic(use_llm=False))


def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator, ProverConfig
    return LogicValidator(ProverConfig())


# ---------------------------------------------------------------------------
# EntityExtractionResult.confidence_stats
# ---------------------------------------------------------------------------

class TestEntityConfidenceStats:
    def test_empty_result(self):
        r = _result()
        stats = r.confidence_stats()
        assert stats["count"] == 0.0
        assert stats["mean"] == 0.0

    def test_single_entity(self):
        r = _result([_entity("e1", confidence=0.8)])
        stats = r.confidence_stats()
        assert stats["count"] == 1.0
        assert stats["mean"] == pytest.approx(0.8)
        assert stats["std"] == pytest.approx(0.0)

    def test_multiple_entities(self):
        r = _result([_entity("e1", confidence=0.4), _entity("e2", confidence=0.8)])
        stats = r.confidence_stats()
        assert stats["mean"] == pytest.approx(0.6)
        assert stats["min"] == pytest.approx(0.4)
        assert stats["max"] == pytest.approx(0.8)
        assert stats["std"] > 0.0

    def test_all_keys_present(self):
        r = _result([_entity("e1")])
        for key in ("count", "mean", "min", "max", "std"):
            assert key in r.confidence_stats()


# ---------------------------------------------------------------------------
# OntologyCritic.compare_runs
# ---------------------------------------------------------------------------

class TestCompareRuns:
    def test_improvement_detected(self):
        c = _make_critic()
        a = _make_score(0.5)
        b = _make_score(0.8)
        result = c.compare_runs(a, b)
        assert result["improved"] is True
        assert result["overall_delta"] > 0

    def test_decline_detected(self):
        c = _make_critic()
        a = _make_score(0.8)
        b = _make_score(0.5)
        result = c.compare_runs(a, b)
        assert result["improved"] is False
        assert result["overall_delta"] < 0

    def test_no_change(self):
        c = _make_critic()
        a = _make_score(0.7)
        b = _make_score(0.7)
        result = c.compare_runs(a, b)
        assert result["improved"] is False
        assert result["overall_delta"] == pytest.approx(0.0)

    def test_dim_deltas_present(self):
        c = _make_critic()
        a = _make_score(0.4)
        b = _make_score(0.7)
        result = c.compare_runs(a, b)
        dims = ("completeness", "consistency", "clarity", "granularity", "domain_alignment")
        for d in dims:
            assert d in result["dim_deltas"]

    def test_all_dim_deltas_positive_on_improvement(self):
        c = _make_critic()
        a = _make_score(0.3)
        b = _make_score(0.9)
        result = c.compare_runs(a, b)
        for v in result["dim_deltas"].values():
            assert v > 0


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.reset_and_load
# ---------------------------------------------------------------------------

class TestResetAndLoad:
    def test_clears_existing_feedback(self):
        a = _make_adapter()
        a.apply_feedback(0.9)
        a.apply_feedback(0.8)
        a.reset_and_load([])
        assert a.has_feedback() is False

    def test_loads_new_records(self):
        a = _make_adapter()
        a.apply_feedback(0.2)
        # Build a new set by applying to a fresh adapter
        b = _make_adapter()
        b.apply_feedback(0.7)
        b.apply_feedback(0.8)
        records = list(b._feedback)
        n = a.reset_and_load(records)
        assert n == 2
        assert a.feedback_count() == 2

    def test_returns_count(self):
        a = _make_adapter()
        b = _make_adapter()
        b.apply_feedback(0.5)
        records = list(b._feedback)
        result = a.reset_and_load(records)
        assert isinstance(result, int)


# ---------------------------------------------------------------------------
# OntologyMediator.reset_action_counts
# ---------------------------------------------------------------------------

class TestResetActionCounts:
    def test_clears_counts(self):
        m = _make_mediator()
        m._action_counts["add"] = 5
        m._action_counts["remove"] = 3
        m.reset_action_counts()
        assert m.total_action_count() == 0

    def test_returns_count_of_cleared_types(self):
        m = _make_mediator()
        m._action_counts["a"] = 1
        m._action_counts["b"] = 2
        n = m.reset_action_counts()
        assert n == 2

    def test_empty_returns_zero(self):
        m = _make_mediator()
        assert m.reset_action_counts() == 0


# ---------------------------------------------------------------------------
# LogicValidator.count_relationship_types
# ---------------------------------------------------------------------------

class TestCountRelationshipTypes:
    def test_empty(self):
        v = _make_validator()
        assert v.count_relationship_types({}) == {}

    def test_single_type(self):
        v = _make_validator()
        ont = {"relationships": [{"id": "r1", "type": "owns"}, {"id": "r2", "type": "owns"}]}
        result = v.count_relationship_types(ont)
        assert result == {"owns": 2}

    def test_multiple_types(self):
        v = _make_validator()
        ont = {
            "relationships": [
                {"id": "r1", "type": "owns"},
                {"id": "r2", "type": "causes"},
                {"id": "r3", "type": "owns"},
            ]
        }
        result = v.count_relationship_types(ont)
        assert result["owns"] == 2
        assert result["causes"] == 1

    def test_ignores_missing_type(self):
        v = _make_validator()
        ont = {"relationships": [{"id": "r1", "source_id": "a", "target_id": "b"}]}
        result = v.count_relationship_types(ont)
        assert result == {}

    def test_edges_alias(self):
        v = _make_validator()
        ont = {"edges": [{"type": "links"}]}
        result = v.count_relationship_types(ont)
        assert result == {"links": 1}
