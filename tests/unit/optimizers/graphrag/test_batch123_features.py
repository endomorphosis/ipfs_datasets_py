"""Batch-123 feature tests.

Methods under test:
  - LogicValidator.relationship_type_set(ontology)
  - LogicValidator.is_connected(ontology)
  - LogicValidator.duplicate_relationship_count(ontology)
"""
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_validator():
    from ipfs_datasets_py.optimizers.graphrag.logic_validator import LogicValidator
    return LogicValidator()


def _ont(entities=None, relationships=None):
    return {
        "entities": entities or [],
        "relationships": relationships or [],
    }


def _ent(eid):
    return {"id": eid, "type": "person"}


def _rel(src, tgt, rtype="knows"):
    return {"source_id": src, "target_id": tgt, "type": rtype}


# ---------------------------------------------------------------------------
# LogicValidator.relationship_type_set
# ---------------------------------------------------------------------------

class TestRelationshipTypeSet:
    def test_empty(self):
        v = _make_validator()
        assert v.relationship_type_set(_ont()) == set()

    def test_single_type(self):
        v = _make_validator()
        ont = _ont(relationships=[_rel("a", "b", "knows"), _rel("c", "d", "knows")])
        assert v.relationship_type_set(ont) == {"knows"}

    def test_multiple_types(self):
        v = _make_validator()
        ont = _ont(relationships=[_rel("a", "b", "knows"), _rel("a", "c", "works_with")])
        rts = v.relationship_type_set(ont)
        assert "knows" in rts
        assert "works_with" in rts
        assert len(rts) == 2

    def test_returns_set(self):
        v = _make_validator()
        result = v.relationship_type_set(_ont())
        assert isinstance(result, set)


# ---------------------------------------------------------------------------
# LogicValidator.is_connected
# ---------------------------------------------------------------------------

class TestIsConnected:
    def test_empty_entities(self):
        v = _make_validator()
        assert v.is_connected(_ont()) is True

    def test_single_entity(self):
        v = _make_validator()
        ont = _ont(entities=[_ent("a")])
        assert v.is_connected(ont) is True

    def test_connected_graph(self):
        v = _make_validator()
        ont = _ont(
            entities=[_ent("a"), _ent("b"), _ent("c")],
            relationships=[_rel("a", "b"), _rel("b", "c")],
        )
        assert v.is_connected(ont) is True

    def test_disconnected_graph(self):
        v = _make_validator()
        ont = _ont(
            entities=[_ent("a"), _ent("b"), _ent("c"), _ent("d")],
            relationships=[_rel("a", "b"), _rel("c", "d")],
        )
        assert v.is_connected(ont) is False

    def test_isolated_entity(self):
        v = _make_validator()
        ont = _ont(
            entities=[_ent("a"), _ent("b"), _ent("isolated")],
            relationships=[_rel("a", "b")],
        )
        assert v.is_connected(ont) is False


# ---------------------------------------------------------------------------
# LogicValidator.duplicate_relationship_count
# ---------------------------------------------------------------------------

class TestDuplicateRelationshipCount:
    def test_empty(self):
        v = _make_validator()
        assert v.duplicate_relationship_count(_ont()) == 0

    def test_no_duplicates(self):
        v = _make_validator()
        ont = _ont(relationships=[_rel("a", "b"), _rel("b", "c")])
        assert v.duplicate_relationship_count(ont) == 0

    def test_one_duplicate(self):
        v = _make_validator()
        ont = _ont(relationships=[_rel("a", "b"), _rel("a", "b")])
        assert v.duplicate_relationship_count(ont) == 1

    def test_multiple_duplicates(self):
        v = _make_validator()
        ont = _ont(relationships=[_rel("a", "b"), _rel("a", "b"), _rel("a", "b")])
        assert v.duplicate_relationship_count(ont) == 2

    def test_different_types_not_duplicate(self):
        v = _make_validator()
        ont = _ont(relationships=[_rel("a", "b", "knows"), _rel("a", "b", "works_with")])
        assert v.duplicate_relationship_count(ont) == 0
