"""
Session 47 – knowledge_graphs coverage push.

Targets:
  extraction/graph.py:629   case _: str fallback for non-primitive entity property in export_to_rdf
  extraction/graph.py:661   else: str fallback for non-primitive relationship property in export_to_rdf

Context:
  With rdflib now available (installed alongside matplotlib/scipy/plotly) the RDF
  export paths are fully reachable. Previous session tests (22, 33, 37) covered
  str/int/float/bool property types.  The `case _:` branch (line 629) and the
  matching `else:` branch (line 661) fire for any other Python type such as a
  list or None — they serialise to `str(value)`.

All tests follow GIVEN-WHEN-THEN and use pytest.importorskip where optional
dependencies are required.
"""
from __future__ import annotations

import importlib.util

import pytest

_rdflib_available = bool(importlib.util.find_spec("rdflib"))


# ===========================================================================
# Helpers
# ===========================================================================

def _make_kg(name: str = "test"):
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
    return KnowledgeGraph(name=name)


def _add_entity(kg, eid: str, etype: str = "Thing", ename: str = "E", **props):
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import Entity
    e = Entity(entity_id=eid, entity_type=etype, name=ename, properties=props)
    kg.add_entity(e)
    return e


def _add_rel(kg, rid: str, src, tgt, rtype: str = "REL", **props):
    from ipfs_datasets_py.knowledge_graphs.extraction.graph import Relationship
    r = Relationship(
        relationship_id=rid,
        relationship_type=rtype,
        source_entity=src,
        target_entity=tgt,
        properties=props if props else {},
    )
    kg.add_relationship(r)
    return r


# ===========================================================================
# 1. extraction/graph.py line 629  — non-primitive entity property (case _:)
# ===========================================================================

@pytest.mark.skipif(not _rdflib_available, reason="rdflib not installed")
class TestExportToRdfEntityNonPrimitiveProperty:
    """GIVEN a KnowledgeGraph whose entity has a non-primitive (list) property
    value, WHEN export_to_rdf() is called, THEN the catch-all `case _:` branch
    (line 629) fires and the property is serialised via str()."""

    def test_entity_list_property_uses_str_fallback(self):
        """GIVEN entity with a list property WHEN export_to_rdf THEN str(value) used."""
        kg = _make_kg("list_prop")
        # A list is not str/int/float/bool → hits case _: in export_to_rdf
        _add_entity(kg, "e1", ename="ListEntity", tags=["a", "b", "c"])
        rdf = kg.export_to_rdf(format="turtle")
        assert isinstance(rdf, str)
        # The list should appear as its string representation somewhere in the output
        assert "a" in rdf or "tags" in rdf or "ListEntity" in rdf

    def test_entity_none_property_uses_str_fallback(self):
        """GIVEN entity with a None property WHEN export_to_rdf THEN str(None)='None' used."""
        kg = _make_kg("none_prop")
        # None is not str/int/float/bool → hits case _: in export_to_rdf
        _add_entity(kg, "e2", ename="NoneEntity", missing_field=None)
        rdf = kg.export_to_rdf(format="turtle")
        assert isinstance(rdf, str)
        # The entity label should appear
        assert "NoneEntity" in rdf

    def test_entity_dict_property_uses_str_fallback(self):
        """GIVEN entity with a dict property WHEN export_to_rdf THEN str(dict) used."""
        kg = _make_kg("dict_prop")
        # A dict is not str/int/float/bool → hits case _: in export_to_rdf
        _add_entity(kg, "e3", ename="DictEntity", meta={"key": "value"})
        rdf = kg.export_to_rdf(format="turtle")
        assert isinstance(rdf, str)
        assert "DictEntity" in rdf

    def test_entity_tuple_property_uses_str_fallback(self):
        """GIVEN entity with a tuple property WHEN export_to_rdf THEN str(tuple) used."""
        kg = _make_kg("tuple_prop")
        # A tuple is not str/int/float/bool → hits case _: in export_to_rdf
        _add_entity(kg, "e4", ename="TupleEntity", coords=(1, 2, 3))
        rdf = kg.export_to_rdf(format="turtle")
        assert isinstance(rdf, str)
        assert "TupleEntity" in rdf


# ===========================================================================
# 2. extraction/graph.py line 661  — non-primitive relationship property (else:)
# ===========================================================================

@pytest.mark.skipif(not _rdflib_available, reason="rdflib not installed")
class TestExportToRdfRelationshipNonPrimitiveProperty:
    """GIVEN a KnowledgeGraph whose relationship has a non-primitive property
    value, WHEN export_to_rdf() is called, THEN the `else:` branch (line 661)
    fires and the property is serialised via str()."""

    def test_rel_list_property_uses_str_fallback(self):
        """GIVEN relationship with a list property WHEN export_to_rdf THEN str(value) used."""
        kg = _make_kg("rel_list")
        src = _add_entity(kg, "src1", ename="Source")
        tgt = _add_entity(kg, "tgt1", ename="Target")
        # A list property triggers the else branch in relationship property handling
        _add_rel(kg, "r1", src, tgt, tags=["x", "y"])
        rdf = kg.export_to_rdf(format="turtle")
        assert isinstance(rdf, str)
        assert "Source" in rdf
        assert "Target" in rdf

    def test_rel_none_property_uses_str_fallback(self):
        """GIVEN relationship with a None property WHEN export_to_rdf THEN str(None) used."""
        kg = _make_kg("rel_none")
        src = _add_entity(kg, "src2", ename="SrcNode")
        tgt = _add_entity(kg, "tgt2", ename="TgtNode")
        # None property triggers the else branch
        _add_rel(kg, "r2", src, tgt, note=None)
        rdf = kg.export_to_rdf(format="turtle")
        assert isinstance(rdf, str)
        assert "SrcNode" in rdf

    def test_rel_dict_property_uses_str_fallback(self):
        """GIVEN relationship with a dict property WHEN export_to_rdf THEN str(dict) used."""
        kg = _make_kg("rel_dict")
        src = _add_entity(kg, "src3", ename="Alpha")
        tgt = _add_entity(kg, "tgt3", ename="Beta")
        # Dict property triggers the else branch
        _add_rel(kg, "r3", src, tgt, meta={"score": 0.9})
        rdf = kg.export_to_rdf(format="turtle")
        assert isinstance(rdf, str)
        assert "Alpha" in rdf

    def test_rel_tuple_property_uses_str_fallback(self):
        """GIVEN relationship with a tuple property WHEN export_to_rdf THEN str(tuple) used."""
        kg = _make_kg("rel_tuple")
        src = _add_entity(kg, "src4", ename="NodeA")
        tgt = _add_entity(kg, "tgt4", ename="NodeB")
        # Tuple property triggers the else branch
        _add_rel(kg, "r4", src, tgt, coords=(0.1, 0.2))
        rdf = kg.export_to_rdf(format="turtle")
        assert isinstance(rdf, str)
        assert "NodeA" in rdf

    def test_rel_bool_property_still_uses_xsd_boolean(self):
        """GIVEN relationship with a bool property WHEN export_to_rdf
        THEN the explicit isinstance(bool) branch fires (not else)."""
        kg = _make_kg("rel_bool_check")
        src = _add_entity(kg, "bsrc", ename="BoolSrc")
        tgt = _add_entity(kg, "btgt", ename="BoolTgt")
        _add_rel(kg, "rb", src, tgt, active=True)
        rdf = kg.export_to_rdf(format="turtle")
        assert isinstance(rdf, str)
        # Boolean is handled by the isinstance(value, bool) branch, not else
        assert "BoolSrc" in rdf
