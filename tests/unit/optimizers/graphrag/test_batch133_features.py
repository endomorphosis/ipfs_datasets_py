"""Batch-133 feature tests.

Methods under test:
  - EntityExtractionResult.entity_ids property
  - EntityExtractionResult.relationship_ids property
  - OntologyLearningAdapter.improvement_trend(window)
"""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_entity(eid, confidence=0.8):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type="person", text=eid, properties={}, confidence=confidence)


def _make_result(entities, relationships=None):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities,
        relationships=relationships or [],
        confidence=0.8,
    )


def _make_adapter():
    from ipfs_datasets_py.optimizers.graphrag.ontology_learning_adapter import OntologyLearningAdapter
    return OntologyLearningAdapter()


def _push(adapter, score):
    adapter.apply_feedback(score)


# ---------------------------------------------------------------------------
# EntityExtractionResult.entity_ids
# ---------------------------------------------------------------------------

class TestEntityIds:
    def test_empty(self):
        result = _make_result([])
        assert result.entity_ids == []

    def test_single(self):
        result = _make_result([_make_entity("alice")])
        assert result.entity_ids == ["alice"]

    def test_multiple(self):
        result = _make_result([_make_entity("a"), _make_entity("b"), _make_entity("c")])
        assert result.entity_ids == ["a", "b", "c"]

    def test_returns_list(self):
        result = _make_result([_make_entity("x")])
        assert isinstance(result.entity_ids, list)


# ---------------------------------------------------------------------------
# EntityExtractionResult.relationship_ids
# ---------------------------------------------------------------------------

class TestRelationshipIds:
    def test_empty(self):
        result = _make_result([])
        assert result.relationship_ids == []

    def test_relationships_without_id_skipped(self):
        from unittest.mock import MagicMock
        result = _make_result([], relationships=[MagicMock(spec=[])])
        # spec=[] means MagicMock has no attributes
        assert result.relationship_ids == []

    def test_returns_list(self):
        result = _make_result([])
        assert isinstance(result.relationship_ids, list)


# ---------------------------------------------------------------------------
# OntologyLearningAdapter.improvement_trend
# ---------------------------------------------------------------------------

class TestImprovementTrend:
    def test_empty_returns_zero(self):
        a = _make_adapter()
        assert a.improvement_trend() == 0.0

    def test_single_returns_zero(self):
        a = _make_adapter()
        _push(a, 0.5)
        assert a.improvement_trend() == 0.0

    def test_improving_positive(self):
        a = _make_adapter()
        _push(a, 0.3)
        _push(a, 0.7)
        assert a.improvement_trend() > 0.0

    def test_declining_negative(self):
        a = _make_adapter()
        _push(a, 0.9)
        _push(a, 0.5)
        assert a.improvement_trend() < 0.0

    def test_flat_near_zero(self):
        a = _make_adapter()
        _push(a, 0.6)
        _push(a, 0.6)
        assert a.improvement_trend() == pytest.approx(0.0)

    def test_window_limits_records(self):
        a = _make_adapter()
        for v in [0.9, 0.1, 0.4, 0.7]:
            _push(a, v)
        # Last 2 records: 0.4 → 0.7 = improving
        assert a.improvement_trend(window=2) > 0.0
