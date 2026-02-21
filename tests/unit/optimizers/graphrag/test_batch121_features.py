"""Batch-121 feature tests.

Methods under test:
  - OntologyGenerator.average_confidence(result)
  - OntologyGenerator.high_confidence_entities(result, threshold)
  - OntologyGenerator.entities_by_type(result, entity_type)
  - OntologyGenerator.deduplicate_entities(result)
"""
import pytest
import dataclasses as _dc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_generator():
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import OntologyGenerator
    return OntologyGenerator()


def _make_entity(eid, etype="person", confidence=0.8):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import Entity
    return Entity(id=eid, type=etype, text=eid, properties={}, confidence=confidence)


def _make_result(entities):
    from ipfs_datasets_py.optimizers.graphrag.ontology_generator import EntityExtractionResult
    return EntityExtractionResult(
        entities=entities,
        relationships=[],
        confidence=0.8,
    )


# ---------------------------------------------------------------------------
# OntologyGenerator.average_confidence
# ---------------------------------------------------------------------------

class TestAverageConfidence:
    def test_empty(self):
        g = _make_generator()
        result = _make_result([])
        assert g.average_confidence(result) == pytest.approx(0.0)

    def test_single(self):
        g = _make_generator()
        result = _make_result([_make_entity("a", confidence=0.7)])
        assert g.average_confidence(result) == pytest.approx(0.7)

    def test_multiple(self):
        g = _make_generator()
        result = _make_result([
            _make_entity("a", confidence=0.6),
            _make_entity("b", confidence=0.8),
            _make_entity("c", confidence=1.0),
        ])
        assert g.average_confidence(result) == pytest.approx(0.8)


# ---------------------------------------------------------------------------
# OntologyGenerator.high_confidence_entities
# ---------------------------------------------------------------------------

class TestHighConfidenceEntities:
    def test_empty(self):
        g = _make_generator()
        result = _make_result([])
        assert g.high_confidence_entities(result) == []

    def test_all_high(self):
        g = _make_generator()
        result = _make_result([
            _make_entity("a", confidence=0.9),
            _make_entity("b", confidence=0.85),
        ])
        assert len(g.high_confidence_entities(result)) == 2

    def test_none_high(self):
        g = _make_generator()
        result = _make_result([_make_entity("a", confidence=0.5)])
        assert g.high_confidence_entities(result) == []

    def test_custom_threshold(self):
        g = _make_generator()
        result = _make_result([
            _make_entity("a", confidence=0.3),
            _make_entity("b", confidence=0.6),
            _make_entity("c", confidence=0.9),
        ])
        high = g.high_confidence_entities(result, threshold=0.5)
        ids = [e.id for e in high]
        assert "b" in ids and "c" in ids
        assert "a" not in ids


# ---------------------------------------------------------------------------
# OntologyGenerator.entities_by_type
# ---------------------------------------------------------------------------

class TestEntitiesByType:
    def test_empty(self):
        g = _make_generator()
        result = _make_result([])
        assert g.filter_entities_by_type(result, "person") == []

    def test_matching(self):
        g = _make_generator()
        result = _make_result([
            _make_entity("a", etype="person"),
            _make_entity("b", etype="org"),
            _make_entity("c", etype="person"),
        ])
        persons = g.filter_entities_by_type(result, "person")
        assert len(persons) == 2
        assert all(e.type == "person" for e in persons)

    def test_no_match(self):
        g = _make_generator()
        result = _make_result([_make_entity("a", etype="org")])
        assert g.filter_entities_by_type(result, "person") == []


# ---------------------------------------------------------------------------
# OntologyGenerator.deduplicate_entities
# ---------------------------------------------------------------------------

class TestDeduplicateEntities:
    def test_no_duplicates(self):
        g = _make_generator()
        entities = [_make_entity("a"), _make_entity("b")]
        result = _make_result(entities)
        deduped = g.deduplicate_by_id(result)
        assert len(deduped.entities) == 2

    def test_removes_lower_confidence_dup(self):
        g = _make_generator()
        entities = [
            _make_entity("a", confidence=0.9),
            _make_entity("a", confidence=0.5),
        ]
        result = _make_result(entities)
        deduped = g.deduplicate_by_id(result)
        assert len(deduped.entities) == 1
        assert deduped.entities[0].confidence == pytest.approx(0.9)

    def test_entity_count_updated(self):
        g = _make_generator()
        entities = [
            _make_entity("a", confidence=0.9),
            _make_entity("a", confidence=0.5),
            _make_entity("b", confidence=0.7),
        ]
        result = _make_result(entities)
        deduped = g.deduplicate_by_id(result)
        assert len(deduped.entities) == 2

    def test_returns_new_result(self):
        g = _make_generator()
        result = _make_result([_make_entity("a")])
        deduped = g.deduplicate_by_id(result)
        assert deduped is not result
