"""Batch-118 feature tests.

Methods under test:
  - LogicValidator.isolated_entities(ontology)
  - LogicValidator.max_degree_entity(ontology)
  - LogicValidator.entity_type_counts(ontology)
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


def _ent(eid, etype="person"):
    return {"id": eid, "type": etype}


def _rel(src, tgt, rtype="knows"):
    return {"source_id": src, "target_id": tgt, "type": rtype}


# ---------------------------------------------------------------------------
# LogicValidator.isolated_entities
# ---------------------------------------------------------------------------

class TestIsolatedEntities:
    def test_empty_ontology(self):
        v = _make_validator()
        assert v.isolated_entities(_ont()) == []

    def test_all_isolated(self):
        v = _make_validator()
        ont = _ont(entities=[_ent("a"), _ent("b")])
        assert sorted(v.isolated_entities(ont)) == ["a", "b"]

    def test_none_isolated(self):
        v = _make_validator()
        ont = _ont(
            entities=[_ent("a"), _ent("b")],
            relationships=[_rel("a", "b")],
        )
        assert v.isolated_entities(ont) == []

    def test_partial(self):
        v = _make_validator()
        ont = _ont(
            entities=[_ent("a"), _ent("b"), _ent("c")],
            relationships=[_rel("a", "b")],
        )
        assert v.isolated_entities(ont) == ["c"]

    def test_returns_sorted(self):
        v = _make_validator()
        ont = _ont(entities=[_ent("z"), _ent("a"), _ent("m")])
        result = v.isolated_entities(ont)
        assert result == sorted(result)


# ---------------------------------------------------------------------------
# LogicValidator.max_degree_entity
# ---------------------------------------------------------------------------

class TestMaxDegreeEntity:
    def test_no_relationships(self):
        v = _make_validator()
        ont = _ont(entities=[_ent("a")])
        assert v.max_degree_entity(ont) is None

    def test_empty_ontology(self):
        v = _make_validator()
        assert v.max_degree_entity(_ont()) is None

    def test_single_rel(self):
        v = _make_validator()
        ont = _ont(
            entities=[_ent("a"), _ent("b")],
            relationships=[_rel("a", "b")],
        )
        result = v.max_degree_entity(ont)
        assert result in {"a", "b"}

    def test_hub_entity(self):
        v = _make_validator()
        ont = _ont(
            entities=[_ent("hub"), _ent("x"), _ent("y"), _ent("z")],
            relationships=[_rel("hub", "x"), _rel("hub", "y"), _rel("hub", "z")],
        )
        assert v.max_degree_entity(ont) == "hub"


# ---------------------------------------------------------------------------
# LogicValidator.entity_type_counts
# ---------------------------------------------------------------------------

class TestEntityTypeCounts:
    def test_empty(self):
        v = _make_validator()
        assert v.entity_type_counts(_ont()) == {}

    def test_single_type(self):
        v = _make_validator()
        ont = _ont(entities=[_ent("a", "person"), _ent("b", "person")])
        counts = v.entity_type_counts(ont)
        assert counts["person"] == 2

    def test_multiple_types(self):
        v = _make_validator()
        ont = _ont(entities=[_ent("a", "person"), _ent("b", "org"), _ent("c", "person")])
        counts = v.entity_type_counts(ont)
        assert counts["person"] == 2
        assert counts["org"] == 1

    def test_total_sums_to_entity_count(self):
        v = _make_validator()
        ont = _ont(entities=[_ent("a", "x"), _ent("b", "y"), _ent("c", "x")])
        counts = v.entity_type_counts(ont)
        assert sum(counts.values()) == 3
