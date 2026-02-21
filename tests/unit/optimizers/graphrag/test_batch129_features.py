"""Batch-129 feature tests.

Methods under test:
  - LogicValidator.self_loop_count(ontology)
  - LogicValidator.average_entity_degree(ontology)
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
# LogicValidator.self_loop_count
# ---------------------------------------------------------------------------

class TestSelfLoopCount:
    def test_empty(self):
        v = _make_validator()
        assert v.self_loop_count(_ont()) == 0

    def test_no_loops(self):
        v = _make_validator()
        ont = _ont(relationships=[_rel("a", "b"), _rel("b", "c")])
        assert v.self_loop_count(ont) == 0

    def test_one_loop(self):
        v = _make_validator()
        ont = _ont(relationships=[_rel("a", "a"), _rel("b", "c")])
        assert v.self_loop_count(ont) == 1

    def test_multiple_loops(self):
        v = _make_validator()
        ont = _ont(relationships=[_rel("a", "a"), _rel("b", "b")])
        assert v.self_loop_count(ont) == 2

    def test_only_loops(self):
        v = _make_validator()
        ont = _ont(relationships=[_rel("x", "x")])
        assert v.self_loop_count(ont) == 1


# ---------------------------------------------------------------------------
# LogicValidator.average_entity_degree
# ---------------------------------------------------------------------------

class TestAverageEntityDegree:
    def test_empty_entities(self):
        v = _make_validator()
        assert v.average_entity_degree(_ont()) == 0.0

    def test_no_relationships(self):
        v = _make_validator()
        ont = _ont(entities=[_ent("a"), _ent("b")])
        assert v.average_entity_degree(ont) == pytest.approx(0.0)

    def test_single_relationship(self):
        v = _make_validator()
        ont = _ont(
            entities=[_ent("a"), _ent("b")],
            relationships=[_rel("a", "b")],
        )
        # a: degree 1, b: degree 1 → mean = 1.0
        assert v.average_entity_degree(ont) == pytest.approx(1.0)

    def test_hub_increases_average(self):
        v = _make_validator()
        ont = _ont(
            entities=[_ent("hub"), _ent("x"), _ent("y"), _ent("z")],
            relationships=[_rel("hub", "x"), _rel("hub", "y"), _rel("hub", "z")],
        )
        # hub: 3, x/y/z: 1 each → mean = (3+1+1+1)/4 = 1.5
        assert v.average_entity_degree(ont) == pytest.approx(1.5)

    def test_positive_when_relationships_exist(self):
        v = _make_validator()
        ont = _ont(
            entities=[_ent("a"), _ent("b")],
            relationships=[_rel("a", "b")],
        )
        assert v.average_entity_degree(ont) > 0.0
