"""Batch-132 feature tests.

Methods under test:
  - LogicValidator.shortest_path_length(ontology, source, target)
  - LogicValidator.reachable_from(ontology, source)
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
# LogicValidator.shortest_path_length
# ---------------------------------------------------------------------------

class TestShortestPathLength:
    def test_same_node(self):
        v = _make_validator()
        ont = _ont(entities=[_ent("a")])
        assert v.shortest_path_length(ont, "a", "a") == 0

    def test_direct_connection(self):
        v = _make_validator()
        ont = _ont(
            entities=[_ent("a"), _ent("b")],
            relationships=[_rel("a", "b")],
        )
        assert v.shortest_path_length(ont, "a", "b") == 1

    def test_two_hops(self):
        v = _make_validator()
        ont = _ont(
            entities=[_ent("a"), _ent("b"), _ent("c")],
            relationships=[_rel("a", "b"), _rel("b", "c")],
        )
        assert v.shortest_path_length(ont, "a", "c") == 2

    def test_no_path(self):
        v = _make_validator()
        ont = _ont(
            entities=[_ent("a"), _ent("b"), _ent("c")],
            relationships=[_rel("a", "b")],
        )
        assert v.shortest_path_length(ont, "a", "c") == -1

    def test_undirected(self):
        v = _make_validator()
        ont = _ont(
            entities=[_ent("a"), _ent("b")],
            relationships=[_rel("a", "b")],
        )
        # Should work in both directions
        assert v.shortest_path_length(ont, "b", "a") == 1


# ---------------------------------------------------------------------------
# LogicValidator.reachable_from
# ---------------------------------------------------------------------------

class TestReachableFrom:
    def test_isolated_node(self):
        v = _make_validator()
        ont = _ont(entities=[_ent("a"), _ent("b")])
        assert v.reachable_from(ont, "a") == []

    def test_direct_neighbour(self):
        v = _make_validator()
        ont = _ont(
            entities=[_ent("a"), _ent("b")],
            relationships=[_rel("a", "b")],
        )
        assert v.reachable_from(ont, "a") == ["b"]

    def test_chain_reachable(self):
        v = _make_validator()
        ont = _ont(
            entities=[_ent("a"), _ent("b"), _ent("c")],
            relationships=[_rel("a", "b"), _rel("b", "c")],
        )
        result = v.reachable_from(ont, "a")
        assert "b" in result
        assert "c" in result
        assert "a" not in result

    def test_unreachable_excluded(self):
        v = _make_validator()
        ont = _ont(
            entities=[_ent("a"), _ent("b"), _ent("c")],
            relationships=[_rel("a", "b")],
        )
        result = v.reachable_from(ont, "a")
        assert "c" not in result

    def test_returns_sorted(self):
        v = _make_validator()
        ont = _ont(
            entities=[_ent("z"), _ent("a"), _ent("m")],
            relationships=[_rel("z", "a"), _rel("z", "m")],
        )
        result = v.reachable_from(ont, "z")
        assert result == sorted(result)
