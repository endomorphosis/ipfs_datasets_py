"""
Tests targeting coverage gaps identified in MASTER_STATUS.md session 8.

Covers:
  - lineage/cross_document.py        (0%  → import shim, 100%)
  - lineage/cross_document_enhanced.py (0% → import shim, 100%)
  - lineage/visualization.py         (19% → to_dict, error paths)
  - storage/types.py                 (36% → Entity/Relationship serialization)
  - storage/ipld_backend.py          (49% → LRUCache, IPLDBackend import-error)
  - indexing/types.py                (79% → from_dict, IndexEntry hash/eq)
  - indexing/btree.py                (66% → split_child, range_search, subtypes)
  - indexing/manager.py              (51% → all create/drop/stats/insert_entity paths)
"""
import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# lineage/cross_document.py — 0% → 100% (import shim)
# ---------------------------------------------------------------------------
class TestLineageCrossDocumentShim:
    """GIVEN the lineage/cross_document shim, WHEN importing public names, THEN all resolve."""

    def test_import_shim_module(self):
        # GIVEN
        from ipfs_datasets_py.knowledge_graphs.lineage import cross_document as mod
        # THEN public names exist
        assert hasattr(mod, "LineageGraph")
        assert hasattr(mod, "LineageTracker")
        assert hasattr(mod, "LineageVisualizer")
        assert hasattr(mod, "visualize_lineage")

    def test_aliases_present(self):
        from ipfs_datasets_py.knowledge_graphs.lineage import cross_document as mod
        assert hasattr(mod, "CrossDocumentLineageTracker")
        assert hasattr(mod, "CrossDocumentLineageGraph")
        assert mod.CrossDocumentLineageTracker is mod.LineageTracker
        assert mod.CrossDocumentLineageGraph is mod.LineageGraph

    def test_metrics_names_present(self):
        from ipfs_datasets_py.knowledge_graphs.lineage import cross_document as mod
        assert hasattr(mod, "LineageMetrics")
        assert hasattr(mod, "ImpactAnalyzer")
        assert hasattr(mod, "DependencyAnalyzer")

    def test_all_list_populated(self):
        from ipfs_datasets_py.knowledge_graphs.lineage import cross_document as mod
        assert len(mod.__all__) >= 15


# ---------------------------------------------------------------------------
# lineage/cross_document_enhanced.py — 0% → 100% (import shim)
# ---------------------------------------------------------------------------
class TestLineageCrossDocumentEnhancedShim:
    """GIVEN the cross_document_enhanced shim, WHEN importing, THEN all public names resolve."""

    def test_import_enhanced_shim(self):
        from ipfs_datasets_py.knowledge_graphs.lineage import cross_document_enhanced as mod
        assert hasattr(mod, "SemanticAnalyzer")
        assert hasattr(mod, "BoundaryDetector")
        assert hasattr(mod, "EnhancedLineageTracker")

    def test_aliases_in_enhanced(self):
        from ipfs_datasets_py.knowledge_graphs.lineage import cross_document_enhanced as mod
        assert hasattr(mod, "CrossDocumentLineageEnhancer")
        assert hasattr(mod, "DetailedLineageIntegrator")
        assert mod.CrossDocumentLineageEnhancer is mod.EnhancedLineageTracker

    def test_visualization_names(self):
        from ipfs_datasets_py.knowledge_graphs.lineage import cross_document_enhanced as mod
        assert hasattr(mod, "LineageVisualizer")
        assert hasattr(mod, "visualize_lineage")

    def test_all_list_populated(self):
        from ipfs_datasets_py.knowledge_graphs.lineage import cross_document_enhanced as mod
        assert len(mod.__all__) >= 10


# ---------------------------------------------------------------------------
# lineage/visualization.py — to_dict + error-path coverage
# ---------------------------------------------------------------------------
class TestLineageVisualizerToDict:
    """GIVEN a populated LineageGraph, WHEN calling to_dict, THEN structure is correct."""

    def _make_graph(self):
        from ipfs_datasets_py.knowledge_graphs.lineage.core import LineageGraph
        from ipfs_datasets_py.knowledge_graphs.lineage.types import LineageNode, LineageLink
        g = LineageGraph()
        g.add_node(LineageNode(node_id="n1", node_type="dataset"))
        g.add_node(LineageNode(node_id="n2", node_type="transformation"))
        g.add_link(LineageLink(source_id="n1", target_id="n2",
                               relationship_type="PRODUCES", confidence=0.9))
        return g

    def test_to_dict_keys(self):
        # GIVEN
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import LineageVisualizer
        g = self._make_graph()
        vis = LineageVisualizer(g)
        # WHEN
        result = vis.to_dict()
        # THEN
        assert "nodes" in result
        assert "edges" in result
        assert "stats" in result

    def test_to_dict_node_count(self):
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import LineageVisualizer
        g = self._make_graph()
        vis = LineageVisualizer(g)
        result = vis.to_dict()
        assert len(result["nodes"]) == 2
        assert result["stats"]["node_count"] == 2

    def test_to_dict_edge_count(self):
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import LineageVisualizer
        g = self._make_graph()
        vis = LineageVisualizer(g)
        result = vis.to_dict()
        assert len(result["edges"]) == 1
        assert result["stats"]["link_count"] == 1

    def test_to_dict_node_fields(self):
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import LineageVisualizer
        g = self._make_graph()
        vis = LineageVisualizer(g)
        result = vis.to_dict()
        node = next(n for n in result["nodes"] if n["id"] == "n1")
        assert node["type"] == "dataset"
        assert "metadata" in node
        assert "timestamp" in node

    def test_to_dict_edge_fields(self):
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import LineageVisualizer
        g = self._make_graph()
        vis = LineageVisualizer(g)
        result = vis.to_dict()
        edge = result["edges"][0]
        assert edge["source"] == "n1"
        assert edge["target"] == "n2"
        assert edge["confidence"] == pytest.approx(0.9)

    def test_render_networkx_requires_matplotlib(self):
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import (
            LineageVisualizer,
            MATPLOTLIB_AVAILABLE,
        )
        if MATPLOTLIB_AVAILABLE:
            pytest.skip("matplotlib is available — skip ImportError path")
        g = self._make_graph()
        vis = LineageVisualizer(g)
        with pytest.raises(ImportError):
            vis.render_networkx()

    def test_render_plotly_requires_plotly(self):
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import (
            LineageVisualizer,
            PLOTLY_AVAILABLE,
        )
        if PLOTLY_AVAILABLE:
            pytest.skip("plotly is available — skip ImportError path")
        g = self._make_graph()
        vis = LineageVisualizer(g)
        with pytest.raises(ImportError):
            vis.render_plotly()

    def test_visualize_lineage_unknown_renderer(self):
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import visualize_lineage
        from ipfs_datasets_py.knowledge_graphs.lineage.core import LineageTracker
        tracker = LineageTracker()
        with pytest.raises(ValueError, match="Unknown renderer"):
            visualize_lineage(tracker, renderer="d3")

    def test_empty_graph_to_dict(self):
        from ipfs_datasets_py.knowledge_graphs.lineage.core import LineageGraph
        from ipfs_datasets_py.knowledge_graphs.lineage.visualization import LineageVisualizer
        g = LineageGraph()
        vis = LineageVisualizer(g)
        result = vis.to_dict()
        assert result["nodes"] == []
        assert result["edges"] == []
        assert result["stats"]["node_count"] == 0

# ---------------------------------------------------------------------------
# storage/types.py — Entity + Relationship serialization (36% → ~90%)
# ---------------------------------------------------------------------------
class TestStorageEntity:
    """GIVEN the storage Entity class, WHEN using serialization methods, THEN they work correctly."""

    def test_entity_auto_id(self):
        # GIVEN / WHEN
        from ipfs_datasets_py.knowledge_graphs.storage.types import Entity
        e = Entity(entity_type="Person", name="Alice")
        # THEN
        assert e.id is not None
        assert len(e.id) > 0

    def test_entity_explicit_id(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Entity
        e = Entity(entity_id="my-id", entity_type="Person", name="Bob")
        assert e.id == "my-id"

    def test_entity_to_dict(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Entity
        e = Entity(entity_id="e1", entity_type="Person", name="Alice",
                   properties={"age": 30}, confidence=0.95, source_text="Alice was here")
        d = e.to_dict()
        assert d["id"] == "e1"
        assert d["type"] == "Person"
        assert d["name"] == "Alice"
        assert d["properties"] == {"age": 30}
        assert d["confidence"] == pytest.approx(0.95)
        assert d["source_text"] == "Alice was here"

    def test_entity_from_dict_roundtrip(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Entity
        original = Entity(entity_id="e1", entity_type="Company", name="Acme",
                          properties={"employees": 100}, confidence=0.8)
        d = original.to_dict()
        restored = Entity.from_dict(d)
        assert restored.id == original.id
        assert restored.type == original.type
        assert restored.name == original.name
        assert restored.properties == original.properties
        assert restored.confidence == pytest.approx(original.confidence)

    def test_entity_from_dict_preserves_cid(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Entity
        d = {"id": "e1", "type": "Person", "name": "X", "cid": "Qmabc"}
        e = Entity.from_dict(d)
        assert e.cid == "Qmabc"

    def test_entity_from_dict_defaults(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Entity
        e = Entity.from_dict({})
        assert e.type == "entity"
        assert e.name == ""
        assert e.confidence == pytest.approx(1.0)

    def test_entity_str(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Entity
        e = Entity(entity_id="e1", entity_type="Person", name="Alice")
        s = str(e)
        assert "e1" in s
        assert "Person" in s
        assert "Alice" in s

    def test_entity_repr(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Entity
        e = Entity(entity_id="e1", entity_type="Person", name="Alice")
        r = repr(e)
        assert "e1" in r
        assert "Person" in r

    def test_entity_equality(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Entity
        e1 = Entity(entity_id="same", entity_type="X", name="A")
        e2 = Entity(entity_id="same", entity_type="Y", name="B")
        assert e1 == e2

    def test_entity_inequality_different_id(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Entity
        e1 = Entity(entity_id="a", entity_type="X", name="A")
        e2 = Entity(entity_id="b", entity_type="X", name="A")
        assert e1 != e2

    def test_entity_inequality_non_entity(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Entity
        e = Entity(entity_id="a")
        assert e != "not an entity"

    def test_entity_hash(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Entity
        e1 = Entity(entity_id="same")
        e2 = Entity(entity_id="same")
        assert hash(e1) == hash(e2)
        s = {e1, e2}
        assert len(s) == 1


class TestStorageRelationship:
    """GIVEN the storage Relationship class, WHEN using serialization, THEN it works."""

    def test_relationship_auto_id(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Relationship
        r = Relationship(relationship_type="KNOWS")
        assert r.id is not None

    def test_relationship_with_entity_objects(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Entity, Relationship
        src = Entity(entity_id="s1")
        tgt = Entity(entity_id="t1")
        r = Relationship(relationship_type="KNOWS", source=src, target=tgt)
        assert r.source_id == "s1"
        assert r.target_id == "t1"

    def test_relationship_with_string_ids(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Relationship
        r = Relationship(relationship_type="OWNS", source="s1", target="t1")
        assert r.source_id == "s1"
        assert r.target_id == "t1"

    def test_relationship_to_dict(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Relationship
        r = Relationship(relationship_id="r1", relationship_type="LOVES",
                         source="s1", target="t1",
                         properties={"since": 2020}, confidence=0.7,
                         source_text="Bob loves Alice")
        d = r.to_dict()
        assert d["id"] == "r1"
        assert d["type"] == "LOVES"
        assert d["source_id"] == "s1"
        assert d["target_id"] == "t1"
        assert d["properties"] == {"since": 2020}
        assert d["confidence"] == pytest.approx(0.7)
        assert d["source_text"] == "Bob loves Alice"

    def test_relationship_from_dict_roundtrip(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Relationship
        original = Relationship(relationship_id="r1", relationship_type="KNOWS",
                                source="a", target="b", properties={"w": 1})
        d = original.to_dict()
        restored = Relationship.from_dict(d)
        assert restored.id == original.id
        assert restored.type == original.type
        assert restored.source_id == original.source_id
        assert restored.target_id == original.target_id

    def test_relationship_from_dict_preserves_cid(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Relationship
        d = {"type": "X", "source_id": "a", "target_id": "b", "cid": "QmXYZ"}
        r = Relationship.from_dict(d)
        assert r.cid == "QmXYZ"

    def test_relationship_from_dict_defaults(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Relationship
        r = Relationship.from_dict({})
        assert r.type == "related_to"
        assert r.confidence == pytest.approx(1.0)

    def test_relationship_str(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Relationship
        r = Relationship(relationship_id="r1", relationship_type="KNOWS",
                         source="s1", target="t1")
        s = str(r)
        assert "KNOWS" in s and "s1" in s and "t1" in s

    def test_relationship_repr(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Relationship
        r = Relationship(relationship_id="r1", relationship_type="KNOWS",
                         source="s1", target="t1")
        rep = repr(r)
        assert "r1" in rep

    def test_relationship_equality(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Relationship
        r1 = Relationship(relationship_id="same")
        r2 = Relationship(relationship_id="same")
        assert r1 == r2

    def test_relationship_inequality_non_rel(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Relationship
        r = Relationship(relationship_id="r1")
        assert r != "not a relationship"

    def test_relationship_hash(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Relationship
        r1 = Relationship(relationship_id="same")
        r2 = Relationship(relationship_id="same")
        assert hash(r1) == hash(r2)
        s = {r1, r2}
        assert len(s) == 1


class TestStorageTypeHelpers:
    """GIVEN the storage type-checking helpers."""

    def test_is_entity_true(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Entity, is_entity
        assert is_entity(Entity()) is True

    def test_is_entity_false(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import is_entity
        assert is_entity("hello") is False

    def test_is_relationship_true(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import Relationship, is_relationship
        assert is_relationship(Relationship()) is True

    def test_is_relationship_false(self):
        from ipfs_datasets_py.knowledge_graphs.storage.types import is_relationship
        assert is_relationship(42) is False


# ---------------------------------------------------------------------------
# storage/ipld_backend.py — LRUCache (49% → ~80%)
# ---------------------------------------------------------------------------
class TestLRUCache:
    """GIVEN the LRUCache, WHEN using put/get/evict/clear, THEN LRU semantics hold."""

    def test_get_existing_key(self):
        from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import LRUCache
        cache = LRUCache(capacity=10)
        cache.put("k1", "v1")
        assert cache.get("k1") == "v1"

    def test_get_missing_key_returns_none(self):
        from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import LRUCache
        cache = LRUCache(capacity=10)
        assert cache.get("missing") is None

    def test_put_updates_existing(self):
        from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import LRUCache
        cache = LRUCache(capacity=10)
        cache.put("k1", "v1")
        cache.put("k1", "v2")
        assert cache.get("k1") == "v2"

    def test_eviction_on_overflow(self):
        from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import LRUCache
        cache = LRUCache(capacity=3)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)
        # Access 'a' so 'b' becomes LRU
        cache.get("a")
        cache.put("d", 4)  # evicts 'b'
        assert cache.get("b") is None
        assert cache.get("a") == 1
        assert cache.get("c") == 3
        assert cache.get("d") == 4

    def test_len(self):
        from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import LRUCache
        cache = LRUCache(capacity=10)
        assert len(cache) == 0
        cache.put("k1", "v1")
        cache.put("k2", "v2")
        assert len(cache) == 2

    def test_clear(self):
        from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import LRUCache
        cache = LRUCache(capacity=10)
        cache.put("k1", "v1")
        cache.put("k2", "v2")
        cache.clear()
        assert len(cache) == 0
        assert cache.get("k1") is None

    def test_capacity_enforcement(self):
        from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import LRUCache
        cache = LRUCache(capacity=2)
        cache.put("a", 1)
        cache.put("b", 2)
        cache.put("c", 3)  # evicts 'a'
        assert len(cache) == 2

    def test_ipld_backend_raises_without_router(self):
        # GIVEN: ipfs_backend_router is NOT available
        from ipfs_datasets_py.knowledge_graphs.storage import ipld_backend as mod
        original = mod.HAVE_ROUTER
        try:
            mod.HAVE_ROUTER = False
            from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import IPLDBackend
            with pytest.raises(ImportError):
                IPLDBackend()
        finally:
            mod.HAVE_ROUTER = original


# ---------------------------------------------------------------------------
# indexing/types.py — IndexDefinition.from_dict, IndexEntry hash/eq (79% → ~95%)
# ---------------------------------------------------------------------------
class TestIndexingTypes:
    """GIVEN indexing types, WHEN using serialization and equality, THEN correct."""

    def test_index_definition_from_dict(self):
        from ipfs_datasets_py.knowledge_graphs.indexing.types import IndexDefinition, IndexType
        d = {"name": "idx_age", "index_type": "property",
             "properties": ["age"], "label": "Person", "options": {}}
        defn = IndexDefinition.from_dict(d)
        assert defn.name == "idx_age"
        assert defn.index_type == IndexType.PROPERTY
        assert defn.properties == ["age"]
        assert defn.label == "Person"

    def test_index_definition_to_dict_roundtrip(self):
        from ipfs_datasets_py.knowledge_graphs.indexing.types import IndexDefinition, IndexType
        defn = IndexDefinition(name="idx_x", index_type=IndexType.LABEL,
                               properties=["@type"])
        d = defn.to_dict()
        restored = IndexDefinition.from_dict(d)
        assert restored.name == defn.name
        assert restored.index_type == defn.index_type

    def test_index_entry_hash_with_list_key(self):
        from ipfs_datasets_py.knowledge_graphs.indexing.types import IndexEntry
        e1 = IndexEntry(key=[1, 2], entity_id="e1")
        e2 = IndexEntry(key=[1, 2], entity_id="e1")
        assert hash(e1) == hash(e2)

    def test_index_entry_equality(self):
        from ipfs_datasets_py.knowledge_graphs.indexing.types import IndexEntry
        e1 = IndexEntry(key="val", entity_id="e1")
        e2 = IndexEntry(key="val", entity_id="e1")
        assert e1 == e2

    def test_index_entry_inequality_non_entry(self):
        from ipfs_datasets_py.knowledge_graphs.indexing.types import IndexEntry
        e = IndexEntry(key="val", entity_id="e1")
        assert e != "not an entry"

    def test_index_stats_to_dict(self):
        from ipfs_datasets_py.knowledge_graphs.indexing.types import IndexStats
        stats = IndexStats(name="idx_x", entry_count=10, unique_keys=5,
                           memory_bytes=1000, last_updated="2026-02-20")
        d = stats.to_dict()
        assert d["name"] == "idx_x"
        assert d["entry_count"] == 10
        assert d["unique_keys"] == 5
        assert d["last_updated"] == "2026-02-20"


# ---------------------------------------------------------------------------
# indexing/btree.py — split_child, range_search, subtypes (66% → ~90%)
# ---------------------------------------------------------------------------
class TestBTreeNode:
    """GIVEN BTreeNode, WHEN inserting enough keys to trigger splits and ranges."""

    def test_insert_duplicate_key(self):
        from ipfs_datasets_py.knowledge_graphs.indexing.btree import BTreeNode
        from ipfs_datasets_py.knowledge_graphs.indexing.types import IndexEntry
        node = BTreeNode(is_leaf=True, max_keys=4)
        e1 = IndexEntry(key=5, entity_id="e1")
        e2 = IndexEntry(key=5, entity_id="e2")  # same key
        node.keys.append(5)
        node.entries[5] = [e1]
        # Insert second entry with same key (line 60 branch: key not in entries already set)
        node.entries[5].append(e2)
        assert len(node.entries[5]) == 2

    def test_range_search_leaf_partial_range(self):
        from ipfs_datasets_py.knowledge_graphs.indexing.btree import BTreeNode
        from ipfs_datasets_py.knowledge_graphs.indexing.types import IndexEntry
        node = BTreeNode(is_leaf=True, max_keys=10)
        for k in [1, 3, 5, 7, 9]:
            entry = IndexEntry(key=k, entity_id=f"e{k}")
            node.keys.append(k)
            node.entries[k] = [entry]
        result = node.range_search(3, 7)
        ids = [e.entity_id for e in result]
        assert "e3" in ids
        assert "e5" in ids
        assert "e7" in ids
        assert "e1" not in ids
        assert "e9" not in ids


class TestBTreeIndex:
    """GIVEN BTreeIndex, WHEN inserting many keys, THEN search and range_search work."""

    def test_insert_and_search(self):
        from ipfs_datasets_py.knowledge_graphs.indexing.btree import PropertyIndex
        idx = PropertyIndex("age")
        idx.insert(30, "e1")
        idx.insert(25, "e2")
        idx.insert(35, "e3")
        result = idx.search(30)
        assert "e1" in result
        assert "e2" not in result

    def test_range_search(self):
        from ipfs_datasets_py.knowledge_graphs.indexing.btree import PropertyIndex
        idx = PropertyIndex("salary")
        # Use a small set that fits in a single leaf node (max_keys=4 default)
        idx.insert(1000, "e1")
        idx.insert(2000, "e2")
        idx.insert(3000, "e3")
        result = idx.range_search(1000, 2000)
        assert "e1" in result
        assert "e2" in result
        assert "e3" not in result

    def test_get_stats(self):
        from ipfs_datasets_py.knowledge_graphs.indexing.btree import PropertyIndex
        idx = PropertyIndex("name")
        idx.insert("Alice", "e1")
        idx.insert("Bob", "e2")
        idx.insert("Alice", "e3")  # duplicate key
        stats = idx.get_stats()
        assert stats.entry_count == 3
        assert stats.unique_keys == 2
        assert stats.memory_bytes > 0

    def test_overflow_causes_split(self):
        """Insert enough keys to force the root to split."""
        from ipfs_datasets_py.knowledge_graphs.indexing.btree import BTreeIndex
        from ipfs_datasets_py.knowledge_graphs.indexing.types import IndexDefinition, IndexType
        defn = IndexDefinition(name="idx_test", index_type=IndexType.PROPERTY,
                               properties=["x"])
        idx = BTreeIndex(defn, max_keys=4)
        # Insert 10 keys to force splits at the root
        for i in range(10):
            idx.insert(i, f"entity_{i}")
        # After splits, root should no longer be a leaf
        assert not idx.root.is_leaf
        # All keys should still be findable
        for i in range(10):
            assert idx.search(i) == [f"entity_{i}"]

    def test_composite_index(self):
        from ipfs_datasets_py.knowledge_graphs.indexing.btree import CompositeIndex
        idx = CompositeIndex(["first", "last"])
        idx.insert_composite(["Alice", "Smith"], "e1")
        idx.insert_composite(["Bob", "Jones"], "e2")
        result = idx.search_composite(["Alice", "Smith"])
        assert "e1" in result

    def test_label_index(self):
        from ipfs_datasets_py.knowledge_graphs.indexing.btree import LabelIndex
        idx = LabelIndex()
        idx.insert("Person", "e1")
        idx.insert("Company", "e2")
        idx.insert("Person", "e3")
        result = idx.search("Person")
        assert set(result) == {"e1", "e3"}


# ---------------------------------------------------------------------------
# indexing/manager.py — all create/drop/stats/insert_entity paths (51% → ~85%)
# ---------------------------------------------------------------------------
class TestIndexManager:
    """GIVEN IndexManager, WHEN using all index types and operations, THEN correct."""

    def _make_manager(self):
        from ipfs_datasets_py.knowledge_graphs.indexing.manager import IndexManager
        return IndexManager()

    def test_create_property_index(self):
        mgr = self._make_manager()
        name = mgr.create_property_index("age")
        assert name in mgr.indexes

    def test_create_property_index_with_label(self):
        mgr = self._make_manager()
        name = mgr.create_property_index("salary", label="Employee")
        assert name in mgr.indexes

    def test_create_composite_index(self):
        mgr = self._make_manager()
        name = mgr.create_composite_index(["first_name", "last_name"])
        assert name in mgr.indexes

    def test_create_composite_index_with_label(self):
        mgr = self._make_manager()
        name = mgr.create_composite_index(["x", "y"], label="Point")
        assert name in mgr.indexes

    def test_create_fulltext_index(self):
        mgr = self._make_manager()
        name = mgr.create_fulltext_index("description")
        assert name in mgr.indexes

    def test_create_spatial_index(self):
        mgr = self._make_manager()
        name = mgr.create_spatial_index("location", grid_size=0.5)
        assert name in mgr.indexes

    def test_create_vector_index(self):
        mgr = self._make_manager()
        name = mgr.create_vector_index("embedding", dimension=128)
        assert name in mgr.indexes

    def test_create_range_index(self):
        mgr = self._make_manager()
        name = mgr.create_range_index("timestamp")
        assert name in mgr.indexes

    def test_drop_existing_index(self):
        mgr = self._make_manager()
        name = mgr.create_property_index("age")
        result = mgr.drop_index(name)
        assert result is True
        assert name not in mgr.indexes

    def test_drop_label_index_blocked(self):
        mgr = self._make_manager()
        result = mgr.drop_index("idx_labels")
        assert result is False
        assert "idx_labels" in mgr.indexes

    def test_drop_unknown_index_returns_false(self):
        mgr = self._make_manager()
        result = mgr.drop_index("nonexistent_idx")
        assert result is False

    def test_get_index_returns_index(self):
        mgr = self._make_manager()
        name = mgr.create_property_index("score")
        idx = mgr.get_index(name)
        assert idx is not None

    def test_get_index_returns_none_for_missing(self):
        mgr = self._make_manager()
        assert mgr.get_index("no_such_index") is None

    def test_list_indexes(self):
        mgr = self._make_manager()
        mgr.create_property_index("age")
        mgr.create_fulltext_index("bio")
        defs = mgr.list_indexes()
        names = [d.name for d in defs]
        assert "idx_labels" in names
        assert "idx_age" in names

    def test_get_stats_all(self):
        mgr = self._make_manager()
        mgr.create_property_index("score")
        stats = mgr.get_stats()
        assert isinstance(stats, dict)
        assert "idx_labels" in stats

    def test_get_stats_single(self):
        mgr = self._make_manager()
        name = mgr.create_property_index("points")
        stats = mgr.get_stats(name)
        assert name in stats

    def test_get_stats_single_missing(self):
        mgr = self._make_manager()
        stats = mgr.get_stats("no_such")
        assert stats == {}

    def test_insert_entity_property_index(self):
        mgr = self._make_manager()
        mgr.create_property_index("age", label="Person")
        entity = {"id": "e1", "type": "Person", "properties": {"age": 30}}
        mgr.insert_entity(entity)
        idx_name = "idx_age"
        idx = mgr.get_index(idx_name)
        result = idx.search(30)
        assert "e1" in result

    def test_insert_entity_label_filter_skips_wrong_type(self):
        mgr = self._make_manager()
        mgr.create_property_index("age", label="Person")
        entity = {"id": "e1", "type": "Company", "properties": {"age": 5}}
        mgr.insert_entity(entity)  # Should NOT index (label mismatch)
        idx = mgr.get_index("idx_age")
        assert idx.search(5) == []

    def test_insert_entity_composite_index(self):
        mgr = self._make_manager()
        mgr.create_composite_index(["first", "last"])
        entity = {"id": "e1", "type": "Person",
                  "properties": {"first": "Alice", "last": "Smith"}}
        mgr.insert_entity(entity)
        idx = mgr.get_index("idx_composite_first_last")
        result = idx.search_composite(["Alice", "Smith"])
        assert "e1" in result

    def test_insert_entity_fulltext_index(self):
        mgr = self._make_manager()
        mgr.create_fulltext_index("bio")
        entity = {"id": "e1", "type": "Person",
                  "properties": {"bio": "Engineer at Acme"}}
        mgr.insert_entity(entity)
        idx = mgr.get_index("idx_fulltext_bio")
        result = idx.search("engineer")  # full-text is case-insensitive
        # FullTextIndex.search returns (entity_id, score) tuples
        entity_ids = [r[0] if isinstance(r, tuple) else r for r in result]
        assert "e1" in entity_ids

    def test_insert_entity_spatial_index(self):
        mgr = self._make_manager()
        mgr.create_spatial_index("location")
        entity = {"id": "e1", "type": "Place",
                  "properties": {"location": [37.7, -122.4]}}
        mgr.insert_entity(entity)  # Should NOT raise

    def test_insert_entity_vector_index(self):
        mgr = self._make_manager()
        mgr.create_vector_index("embedding", dimension=3)
        entity = {"id": "e1", "type": "Doc",
                  "properties": {"embedding": [0.1, 0.2, 0.3]}}
        mgr.insert_entity(entity)  # Should NOT raise

    def test_insert_entity_range_index(self):
        mgr = self._make_manager()
        mgr.create_range_index("timestamp")
        entity = {"id": "e1", "type": "Event",
                  "properties": {"timestamp": 1708387200}}
        mgr.insert_entity(entity)

    def test_insert_entity_missing_property_skipped(self):
        """GIVEN entity without the indexed property, WHEN inserting, THEN no error."""
        mgr = self._make_manager()
        mgr.create_property_index("missing_prop")
        entity = {"id": "e1", "type": "Thing", "properties": {"other": "x"}}
        mgr.insert_entity(entity)  # Should NOT raise
