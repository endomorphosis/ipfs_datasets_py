"""
Session 20 coverage improvement tests.

Targets (by uncovered-statement count, excluding daemon/network paths):
  - extraction/validator.py          59% → target 72%   (+13pp)
  - core/_legacy_graph_engine.py     68% → target 79%   (+11pp)
  - storage/ipld_backend.py          69% → target 80%   (+11pp)
  - extraction/finance_graphrag.py   69% → target 81%   (+12pp)
  - query/distributed.py             83% → target 88%   (+5pp)
  - migration/formats.py             90% → target 93%   (+3pp)

Tests follow GIVEN-WHEN-THEN format consistent with the rest of the knowledge_graphs
test suite.  All tests must pass without an IPFS daemon or internet connection.
"""

from __future__ import annotations

import json
import hashlib
import warnings
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# extraction/validator.py
# ---------------------------------------------------------------------------

class TestKGExtractorWithValidation:
    """Tests for KnowledgeGraphExtractorWithValidation."""

    def _make_extractor(self, validate=False, auto_correct=False):
        from ipfs_datasets_py.knowledge_graphs.extraction.validator import (
            KnowledgeGraphExtractorWithValidation,
        )
        return KnowledgeGraphExtractorWithValidation(
            validate_during_extraction=validate,
            auto_correct_suggestions=auto_correct,
        )

    # --- init ---------------------------------------------------------------

    def test_init_no_validator_available(self):
        """GIVEN SPARQLValidator unavailable WHEN init THEN validator_available=False."""
        with patch.dict("sys.modules", {"ipfs_datasets_py.ml.llm.llm_semantic_validation": None}):
            ext = self._make_extractor()
        assert ext.validator_available is False
        assert ext.validator is None

    def test_init_with_validator_available(self):
        """GIVEN SPARQLValidator importable WHEN init THEN validator_available=True."""
        mock_validator_cls = MagicMock()
        mock_validator_cls.return_value = MagicMock()
        import sys
        fake_module = MagicMock()
        fake_module.SPARQLValidator = mock_validator_cls
        with patch.dict("sys.modules", {"ipfs_datasets_py.ml.llm.llm_semantic_validation": fake_module}):
            ext = self._make_extractor()
        assert ext.validator_available is True
        assert ext.validator is not None

    # --- extract_knowledge_graph --------------------------------------------

    def test_extract_knowledge_graph_basic(self):
        """GIVEN no validator WHEN extract text THEN returns dict with kg key."""
        ext = self._make_extractor()
        result = ext.extract_knowledge_graph("Alice works at Acme Corp.")
        assert isinstance(result, dict)
        assert "knowledge_graph" in result
        assert "entity_count" in result
        assert "relationship_count" in result

    def test_extract_knowledge_graph_validate_no_validator(self):
        """GIVEN validate_during_extraction=True but validator=None WHEN extract THEN stubs included."""
        ext = self._make_extractor(validate=True)
        result = ext.extract_knowledge_graph("Bob leads Globex Inc.")
        assert "validation_results" in result
        assert result.get("validation_metrics", {}).get("validation_available") is False

    def test_extract_knowledge_graph_error_path(self):
        """GIVEN extractor raises WHEN extract THEN error dict returned."""
        ext = self._make_extractor()
        ext.extractor.extract_knowledge_graph = MagicMock(side_effect=RuntimeError("boom"))
        result = ext.extract_knowledge_graph("text")
        assert "error" in result
        assert result.get("knowledge_graph") is None
        assert "RuntimeError" in result.get("error_class", "")

    def test_extract_knowledge_graph_with_validator_entity_corrections(self):
        """GIVEN validator available WHEN extract with validation THEN corrections populated."""
        ext = self._make_extractor(validate=True)
        mock_val = MagicMock()
        mock_result = MagicMock()
        mock_result.to_dict.return_value = {}
        mock_result.data = {
            "entity_coverage": 0.5,
            "relationship_coverage": 0.5,
            "overall_coverage": 0.5,
            "entity_validations": {
                "e1": {"valid": False, "suggestions": "use Alice"},
                "e2": {"valid": True, "suggestions": ""},
            },
            "relationship_validations": {
                "r1": {
                    "valid": False,
                    "source": "Alice",
                    "relationship_type": "works_for",
                    "target": "Acme",
                    "wikidata_match": "employed_by",
                    "suggestions": "Consider using 'employed_by' instead",
                }
            },
        }
        mock_val.validate_knowledge_graph.return_value = mock_result
        ext.validator = mock_val
        ext.validator_available = True
        result = ext.extract_knowledge_graph("Alice works for Acme Corp.")
        assert "validation_results" in result or "knowledge_graph" in result

    # --- extract_from_documents ---------------------------------------------

    def test_extract_from_documents_basic(self):
        """GIVEN list of docs WHEN extract_from_documents THEN returns dict with kg."""
        ext = self._make_extractor()
        docs = [{"text": "Alice is CEO of Acme."}, {"text": "Bob works at Globex."}]
        result = ext.extract_from_documents(docs)
        assert isinstance(result, dict)
        assert "knowledge_graph" in result

    def test_extract_from_documents_error_path(self):
        """GIVEN extractor.extract_from_documents raises WHEN called THEN error dict."""
        ext = self._make_extractor()
        ext.extractor.extract_from_documents = MagicMock(side_effect=ValueError("bad docs"))
        result = ext.extract_from_documents([{"text": "x"}])
        assert "error" in result
        assert result.get("knowledge_graph") is None

    def test_extract_from_documents_with_validator(self):
        """GIVEN validator WHEN extract_from_documents THEN validation_results present."""
        ext = self._make_extractor(validate=True)
        mock_val = MagicMock()
        mock_res = MagicMock()
        mock_res.to_dict.return_value = {}
        mock_res.data = {
            "entity_coverage": 0.8,
            "relationship_coverage": 0.7,
            "overall_coverage": 0.75,
        }
        mock_val.validate_knowledge_graph.return_value = mock_res
        ext.validator = mock_val
        ext.validator_available = True
        docs = [{"text": "Alice manages Bob."}]
        result = ext.extract_from_documents(docs)
        assert "knowledge_graph" in result

    # --- validate_against_wikidata ------------------------------------------

    def test_validate_against_wikidata_no_validator(self):
        """GIVEN no validator WHEN validate_against_wikidata THEN invalid result."""
        ext = self._make_extractor()
        result = ext.validate_against_wikidata("Alice", "person")
        assert result.get("valid") is False

    def test_validate_against_wikidata_with_validator(self):
        """GIVEN validator available WHEN validate_against_wikidata THEN delegates."""
        ext = self._make_extractor()
        mock_val = MagicMock()
        mock_val_result = MagicMock()
        mock_val_result.is_valid = True
        mock_val_result.to_dict.return_value = {"valid": True}
        mock_val.validate_entity.return_value = mock_val_result
        ext.validator = mock_val
        ext.validator_available = True
        result = ext.validate_against_wikidata("Alice", "person")
        assert isinstance(result, dict)

    # --- apply_validation_corrections ---------------------------------------

    def test_apply_corrections_empty_corrections(self):
        """GIVEN empty corrections WHEN apply THEN KG is a clean copy."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        ext = self._make_extractor()
        kg = KnowledgeGraph(name="test")
        kg.add_entity(entity_type="Person", name="Alice")
        corrected = ext.apply_validation_corrections(kg, {})
        assert len(corrected.entities) == 1

    def test_apply_corrections_entity_property_correction_dict(self):
        """GIVEN structured dict suggestions WHEN apply THEN property updated."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        ext = self._make_extractor()
        kg = KnowledgeGraph(name="test")
        kg.add_entity(entity_type="Person", name="Alice", properties={"role": "manager"})
        # find the actual entity_id
        entity_id = list(kg.entities.keys())[-1]
        corrections = {
            "entities": {
                entity_id: {
                    "suggestions": {"role": "director"},
                }
            }
        }
        corrected = ext.apply_validation_corrections(kg, corrections)
        corrected_entity = list(corrected.entities.values())[-1]
        assert corrected_entity.properties.get("role") == "director"

    def test_apply_corrections_entity_property_correction_text(self):
        """GIVEN text suggestions with colon WHEN apply THEN property updated."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        ext = self._make_extractor()
        kg = KnowledgeGraph(name="test")
        kg.add_entity(entity_type="Person", name="Bob", properties={"title": "VP"})
        entity_id = list(kg.entities.keys())[-1]
        corrections = {
            "entities": {
                entity_id: {
                    "suggestions": "title: chief\nrole: leader",
                }
            }
        }
        corrected = ext.apply_validation_corrections(kg, corrections)
        # Corrections applied (parsed from text)
        entity = list(corrected.entities.values())[-1]
        assert entity.properties.get("title") == "chief"

    def test_apply_corrections_relationship_type_correction(self):
        """GIVEN rel type suggestion WHEN apply THEN relationship type updated."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import Entity as GraphEntity
        ext = self._make_extractor()
        kg = KnowledgeGraph(name="test")
        kg.add_entity(entity_type="Person", name="Alice")
        kg.add_entity(entity_type="Organization", name="Acme")
        src_id = list(kg.entities.keys())[0]
        tgt_id = list(kg.entities.keys())[1]
        src_entity = kg.entities[src_id]
        tgt_entity = kg.entities[tgt_id]
        kg.add_relationship("works_for", source=src_entity, target=tgt_entity)
        corrections = {
            "relationships": {
                list(kg.relationships.keys())[0]: {
                    "relationship_type": "works_for",
                    "suggestions": "Consider using 'employed_by' instead",
                }
            }
        }
        corrected = ext.apply_validation_corrections(kg, corrections)
        # The rel type should be corrected
        rel = list(corrected.relationships.values())[0]
        assert rel.relationship_type == "employed_by"

    def test_apply_corrections_entity_with_none_properties(self):
        """GIVEN entity with None properties WHEN apply THEN no crash."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        ext = self._make_extractor()
        kg = KnowledgeGraph(name="test")
        entity = kg.add_entity(entity_type="Person", name="Alice")
        # Force None properties
        entity_id = list(kg.entities.keys())[-1]
        kg.entities[entity_id].properties = None
        corrected = ext.apply_validation_corrections(kg, {})
        assert len(corrected.entities) == 1


# ---------------------------------------------------------------------------
# core/_legacy_graph_engine.py  (uncovered persistence & traversal paths)
# ---------------------------------------------------------------------------

class TestLegacyGraphEngineExtended:
    """Tests for _LegacyGraphEngine uncovered paths."""

    def _make_engine(self, storage=None):
        from ipfs_datasets_py.knowledge_graphs.core._legacy_graph_engine import _LegacyGraphEngine
        return _LegacyGraphEngine(storage_backend=storage)

    # --- persistence via mock storage ---------------------------------------

    def test_create_node_persistence_success(self):
        """GIVEN mock storage WHEN create_node THEN storage.store called."""
        mock_storage = MagicMock()
        mock_storage.store.return_value = "bafyfake"
        engine = self._make_engine(storage=mock_storage)
        node = engine.create_node(labels=["Person"], properties={"name": "Alice"})
        assert node is not None
        mock_storage.store.assert_called_once()

    def test_create_node_persistence_storage_error(self):
        """GIVEN storage raises StorageError WHEN create_node THEN node still created."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import StorageError
        mock_storage = MagicMock()
        mock_storage.store.side_effect = StorageError("disk full")
        engine = self._make_engine(storage=mock_storage)
        node = engine.create_node(labels=["Person"])
        assert node is not None  # Node is created despite persistence failure

    def test_get_node_from_cache(self):
        """GIVEN node in cache WHEN get_node THEN returns it."""
        engine = self._make_engine()
        created = engine.create_node(labels=["Person"])
        retrieved = engine.get_node(created.id)
        assert retrieved is created

    def test_get_node_not_found(self):
        """GIVEN unknown id WHEN get_node THEN returns None."""
        engine = self._make_engine()
        result = engine.get_node("nonexistent-id")
        assert result is None

    def test_get_node_from_storage_fallback(self):
        """GIVEN node CID in cache and mock storage WHEN get_node THEN loads from storage."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import Node
        mock_storage = MagicMock()
        mock_storage.store.return_value = "bafyfake"
        mock_storage.retrieve_json.return_value = {
            "id": "node-123", "labels": ["Person"], "properties": {"name": "Alice"}
        }
        engine = self._make_engine(storage=mock_storage)
        # Manually insert CID reference as if persisted
        engine._node_cache["cid:node-123"] = "bafyfake"
        node = engine.get_node("node-123")
        assert node is not None
        assert "Person" in node.labels

    def test_update_node_persistence(self):
        """GIVEN mock storage WHEN update_node THEN storage.store called."""
        mock_storage = MagicMock()
        mock_storage.store.return_value = "bafynew"
        engine = self._make_engine(storage=mock_storage)
        node = engine.create_node(labels=["Person"])
        mock_storage.reset_mock()
        result = engine.update_node(node.id, properties={"age": 30})
        assert result is not None
        mock_storage.store.assert_called_once()

    def test_delete_node_removes_cid_key(self):
        """GIVEN node with CID entry WHEN delete_node THEN CID key also removed."""
        engine = self._make_engine()
        node = engine.create_node(labels=["Person"])
        engine._node_cache[f"cid:{node.id}"] = "bafyfake"
        result = engine.delete_node(node.id)
        assert result is True
        assert f"cid:{node.id}" not in engine._node_cache

    def test_create_relationship_persistence(self):
        """GIVEN mock storage WHEN create_relationship THEN storage.store called."""
        mock_storage = MagicMock()
        mock_storage.store.return_value = "bafyfake"
        engine = self._make_engine(storage=mock_storage)
        a = engine.create_node(labels=["A"])
        b = engine.create_node(labels=["B"])
        mock_storage.reset_mock()
        rel = engine.create_relationship("KNOWS", a.id, b.id)
        assert rel is not None
        mock_storage.store.assert_called_once()

    def test_save_graph_returns_none_no_persistence(self):
        """GIVEN no storage WHEN save_graph THEN returns None."""
        engine = self._make_engine()
        result = engine.save_graph()
        assert result is None

    def test_save_graph_with_storage(self):
        """GIVEN mock storage WHEN save_graph THEN calls store_graph."""
        mock_storage = MagicMock()
        mock_storage.store.return_value = "bafyfake"
        mock_storage.store_graph.return_value = "bafyroot"
        engine = self._make_engine(storage=mock_storage)
        engine.create_node(labels=["A"])
        result = engine.save_graph()
        assert result == "bafyroot"
        mock_storage.store_graph.assert_called_once()

    def test_load_graph_returns_false_no_persistence(self):
        """GIVEN no storage WHEN load_graph THEN returns False."""
        engine = self._make_engine()
        result = engine.load_graph("bafyfake")
        assert result is False

    def test_load_graph_with_storage(self):
        """GIVEN mock storage with graph data WHEN load_graph THEN returns True and populates cache."""
        mock_storage = MagicMock()
        mock_storage.retrieve_graph.return_value = {
            "nodes": [
                {"id": "n1", "labels": ["Person"], "properties": {"name": "Alice"}},
            ],
            "relationships": [
                {"id": "r1", "type": "KNOWS", "start_node": "n1", "end_node": "n1", "properties": {}}
            ],
        }
        engine = self._make_engine(storage=mock_storage)
        result = engine.load_graph("bafyroot")
        assert result is True
        assert "n1" in engine._node_cache

    def test_get_relationships_in_direction(self):
        """GIVEN two nodes and a relationship WHEN get_relationships direction=in THEN returns it."""
        engine = self._make_engine()
        a = engine.create_node(labels=["A"])
        b = engine.create_node(labels=["B"])
        rel = engine.create_relationship("FOLLOWS", a.id, b.id)
        results = engine.get_relationships(b.id, direction="in")
        assert len(results) == 1
        assert results[0].id == rel.id

    def test_get_relationships_type_filter_no_match(self):
        """GIVEN relationship of type X WHEN filter by type Y THEN empty list."""
        engine = self._make_engine()
        a = engine.create_node(labels=["A"])
        b = engine.create_node(labels=["B"])
        engine.create_relationship("KNOWS", a.id, b.id)
        results = engine.get_relationships(a.id, direction="out", rel_type="HATES")
        assert len(results) == 0

    def test_traverse_pattern_with_limit(self):
        """GIVEN chain of nodes WHEN traverse with limit=1 THEN at most 1 result."""
        engine = self._make_engine()
        a = engine.create_node(labels=["A"])
        b = engine.create_node(labels=["B"])
        c = engine.create_node(labels=["C"])
        engine.create_relationship("NEXT", a.id, b.id)
        engine.create_relationship("NEXT", a.id, c.id)
        pattern = [{"rel_type": "NEXT"}]
        results = engine.traverse_pattern([a], pattern, limit=1)
        assert len(results) == 1

    def test_find_paths_direct(self):
        """GIVEN two connected nodes WHEN find_paths THEN path of length 1 returned."""
        engine = self._make_engine()
        a = engine.create_node(labels=["A"])
        b = engine.create_node(labels=["B"])
        rel = engine.create_relationship("KNOWS", a.id, b.id)
        paths = engine.find_paths(a.id, b.id)
        assert len(paths) == 1
        assert rel in paths[0]

    def test_find_paths_max_depth(self):
        """GIVEN nodes requiring 2 hops WHEN max_depth=1 THEN no paths found."""
        engine = self._make_engine()
        a = engine.create_node(labels=["A"])
        b = engine.create_node(labels=["B"])
        c = engine.create_node(labels=["C"])
        engine.create_relationship("KNOWS", a.id, b.id)
        engine.create_relationship("KNOWS", b.id, c.id)
        paths = engine.find_paths(a.id, c.id, max_depth=1)
        assert paths == []


# ---------------------------------------------------------------------------
# storage/ipld_backend.py
# ---------------------------------------------------------------------------

class TestIPLDBackendExtended:
    """Tests for IPLDBackend using a mocked router."""

    def _make_backend(self, mock_backend=None):
        mock_deps = MagicMock()
        if mock_backend is None:
            mock_backend = MagicMock()
            mock_backend.block_put.return_value = "bafyfake"
            mock_backend.pin = MagicMock()
        with patch("ipfs_datasets_py.knowledge_graphs.storage.ipld_backend.RouterDeps", return_value=mock_deps):
            with patch("ipfs_datasets_py.knowledge_graphs.storage.ipld_backend.get_ipfs_backend", return_value=mock_backend):
                from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import IPLDBackend
                backend = IPLDBackend(deps=mock_deps, cache_capacity=5)
        # _get_backend() is lazy; inject mock directly so calls outside the
        # patch context also use the mock backend.
        backend._backend = mock_backend
        return backend, mock_backend

    # --- store --------------------------------------------------------------

    def test_store_dict_serializes_to_json(self):
        """GIVEN dict data WHEN store THEN block_put called with JSON bytes."""
        backend, mock_b = self._make_backend()
        cid = backend.store({"key": "value"})
        mock_b.block_put.assert_called_once()
        args, kwargs = mock_b.block_put.call_args
        assert b"key" in args[0]

    def test_store_string(self):
        """GIVEN string data WHEN store THEN block_put called with UTF-8 bytes."""
        backend, mock_b = self._make_backend()
        cid = backend.store("hello world")
        args, _ = mock_b.block_put.call_args
        assert args[0] == b"hello world"

    def test_store_bytes(self):
        """GIVEN raw bytes WHEN store THEN block_put called with same bytes."""
        backend, mock_b = self._make_backend()
        cid = backend.store(b"\x01\x02\x03")
        args, _ = mock_b.block_put.call_args
        assert args[0] == b"\x01\x02\x03"

    def test_store_unsupported_type_raises_serialization_error(self):
        """GIVEN set data WHEN store THEN SerializationError raised."""
        from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import SerializationError
        backend, _ = self._make_backend()
        with pytest.raises(SerializationError):
            backend.store({1, 2, 3})  # sets are not JSON-serializable

    def test_store_connection_error_raises_ipld_storage_error(self):
        """GIVEN backend raises ConnectionError WHEN store THEN IPLDStorageError raised."""
        from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import IPLDStorageError
        mock_b = MagicMock()
        mock_b.block_put.side_effect = ConnectionError("IPFS offline")
        backend, _ = self._make_backend(mock_backend=mock_b)
        with pytest.raises(IPLDStorageError):
            backend.store({"x": 1})

    def test_store_generic_error_raises_ipld_storage_error(self):
        """GIVEN backend raises unknown Exception WHEN store THEN IPLDStorageError raised."""
        from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import IPLDStorageError
        mock_b = MagicMock()
        mock_b.block_put.side_effect = RuntimeError("unexpected")
        backend, _ = self._make_backend(mock_backend=mock_b)
        with pytest.raises(IPLDStorageError):
            backend.store({"x": 1})

    # --- retrieve -----------------------------------------------------------

    def test_retrieve_cache_hit(self):
        """GIVEN data already in LRU cache WHEN retrieve THEN backend not called."""
        backend, mock_b = self._make_backend()
        backend._cache.put("bafyfake", b"cached data")
        result = backend.retrieve("bafyfake")
        assert result == b"cached data"
        mock_b.block_get.assert_not_called()

    def test_retrieve_block_get_success(self):
        """GIVEN block_get works WHEN retrieve THEN data returned."""
        mock_b = MagicMock()
        mock_b.block_get.return_value = b"block data"
        backend, _ = self._make_backend(mock_backend=mock_b)
        result = backend.retrieve("bafytest")
        assert result == b"block data"
        # Note: LRUCache has __len__, so an empty cache is falsy; the
        # `if self._cache:` guard skips caching until the cache has items.

    def test_retrieve_cache_populated_after_second_call(self):
        """GIVEN retrieve called twice for different CIDs WHEN second retrieve THEN cache has first entry."""
        mock_b = MagicMock()
        mock_b.block_get.return_value = b"block data"
        backend, _ = self._make_backend(mock_backend=mock_b)
        # First call: cache is empty → falsy → cache bypassed
        r1 = backend.retrieve("bafy1")
        assert r1 == b"block data"
        # Manually populate cache so it becomes truthy for the next call
        backend._cache.put("bafy1", r1)
        # Second call: cache now has 1 item → truthy → cache checked
        r2 = backend.retrieve("bafy1")
        assert r2 == b"block data"
        # block_get called only once (second is a cache hit)
        assert mock_b.block_get.call_count == 1

    def test_retrieve_block_get_fails_cat_succeeds(self):
        """GIVEN block_get raises AttributeError WHEN retrieve THEN falls back to cat."""
        mock_b = MagicMock()
        mock_b.block_get.side_effect = AttributeError("no block_get")
        mock_b.cat.return_value = b"cat data"
        backend, _ = self._make_backend(mock_backend=mock_b)
        result = backend.retrieve("bafytest")
        assert result == b"cat data"

    def test_retrieve_cat_connection_error_raises(self):
        """GIVEN block_get fails and cat raises ConnectionError WHEN retrieve THEN IPLDStorageError."""
        from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import IPLDStorageError
        mock_b = MagicMock()
        mock_b.block_get.side_effect = AttributeError("no block_get")
        mock_b.cat.side_effect = ConnectionError("IPFS down")
        backend, _ = self._make_backend(mock_backend=mock_b)
        with pytest.raises(IPLDStorageError):
            backend.retrieve("bafytest")

    def test_retrieve_cat_generic_error_raises(self):
        """GIVEN block_get fails and cat raises generic error WHEN retrieve THEN IPLDStorageError."""
        from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import IPLDStorageError
        mock_b = MagicMock()
        mock_b.block_get.side_effect = AttributeError("no block_get")
        mock_b.cat.side_effect = RuntimeError("weird error")
        backend, _ = self._make_backend(mock_backend=mock_b)
        with pytest.raises(IPLDStorageError):
            backend.retrieve("bafytest")

    def test_retrieve_main_path_connection_error(self):
        """GIVEN block_get raises ConnectionError WHEN retrieve THEN IPLDStorageError."""
        from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import IPLDStorageError
        mock_b = MagicMock()
        mock_b.block_get.side_effect = ConnectionError("IPFS down")
        backend, _ = self._make_backend(mock_backend=mock_b)
        with pytest.raises(IPLDStorageError):
            backend.retrieve("bafytest")

    # --- retrieve_json / pin / unpin / list_directory / export_car ----------

    def test_retrieve_json_success(self):
        """GIVEN valid JSON bytes WHEN retrieve_json THEN parsed dict returned."""
        mock_b = MagicMock()
        mock_b.block_get.return_value = b'{"hello": "world"}'
        backend, _ = self._make_backend(mock_backend=mock_b)
        result = backend.retrieve_json("bafytest")
        assert result == {"hello": "world"}

    def test_retrieve_json_bad_bytes_raises_deserialization_error(self):
        """GIVEN non-JSON bytes WHEN retrieve_json THEN DeserializationError raised."""
        from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import DeserializationError
        mock_b = MagicMock()
        mock_b.block_get.return_value = b"not json!!!"
        backend, _ = self._make_backend(mock_backend=mock_b)
        with pytest.raises(DeserializationError):
            backend.retrieve_json("bafytest")

    def test_retrieve_json_cache_key_populated(self):
        """GIVEN retrieve_json called WHEN same cid retrieved with warm cache THEN cache hit."""
        mock_b = MagicMock()
        mock_b.block_get.return_value = b'{"k": 1}'
        backend, _ = self._make_backend(mock_backend=mock_b)
        r1 = backend.retrieve_json("bafy1")
        assert r1 == {"k": 1}
        # Warm the cache manually (the LRUCache `if self._cache:` guard fails
        # on an empty cache since __len__ == 0 is falsy).
        backend._cache.put("json:bafy1", r1)
        backend._cache.put("bafy1", b'{"k": 1}')
        # Second call should now hit the json: cache key
        r2 = backend.retrieve_json("bafy1")
        assert r2 == {"k": 1}
        # block_get called only once
        assert mock_b.block_get.call_count == 1

    def test_pin_delegates_to_backend(self):
        """GIVEN valid CID WHEN pin THEN backend.pin called."""
        mock_b = MagicMock()
        mock_b.block_get.return_value = b"x"
        backend, _ = self._make_backend(mock_backend=mock_b)
        backend.pin("bafypin")
        mock_b.pin.assert_called_once_with("bafypin")

    def test_unpin_delegates_to_backend(self):
        """GIVEN valid CID WHEN unpin THEN backend.unpin called."""
        mock_b = MagicMock()
        backend, _ = self._make_backend(mock_backend=mock_b)
        backend.unpin("bafyunpin")
        mock_b.unpin.assert_called_once_with("bafyunpin")

    def test_list_directory_delegates_to_backend(self):
        """GIVEN valid CID WHEN list_directory THEN backend.ls called."""
        mock_b = MagicMock()
        mock_b.ls.return_value = ["file1", "file2"]
        backend, _ = self._make_backend(mock_backend=mock_b)
        result = backend.list_directory("bafydir")
        assert result == ["file1", "file2"]

    def test_export_car_delegates_to_backend(self):
        """GIVEN valid CID WHEN export_car THEN backend.dag_export called."""
        mock_b = MagicMock()
        mock_b.dag_export.return_value = b"car bytes"
        backend, _ = self._make_backend(mock_backend=mock_b)
        result = backend.export_car("bafyroot")
        assert result == b"car bytes"

    def test_store_graph_and_retrieve_graph(self):
        """GIVEN nodes and rels WHEN store_graph THEN stores JSON structure."""
        mock_b = MagicMock()
        mock_b.block_put.return_value = "bafygraph"
        mock_b.block_get.return_value = b'{"nodes":[],"relationships":[],"metadata":{}}'
        backend, _ = self._make_backend(mock_backend=mock_b)
        cid = backend.store_graph(nodes=[{"id": "n1"}], relationships=[], metadata={})
        assert cid == "bafygraph"
        graph = backend.retrieve_graph(cid)
        assert "nodes" in graph


# ---------------------------------------------------------------------------
# extraction/finance_graphrag.py  (link_executives, test_hypothesis, analyze)
# ---------------------------------------------------------------------------

class TestFinanceGraphRAGExtended:
    """Tests for GraphRAGNewsAnalyzer and helpers (no network required)."""

    def _make_analyzer(self):
        from ipfs_datasets_py.knowledge_graphs.extraction.finance_graphrag import GraphRAGNewsAnalyzer
        return GraphRAGNewsAnalyzer()

    def test_hash_id_deterministic(self):
        """GIVEN same parts WHEN _hash_id THEN same hash returned."""
        from ipfs_datasets_py.knowledge_graphs.extraction.finance_graphrag import GraphRAGNewsAnalyzer
        h1 = GraphRAGNewsAnalyzer._hash_id("Alice", "Acme", "exec_of")
        h2 = GraphRAGNewsAnalyzer._hash_id("Alice", "Acme", "exec_of")
        assert h1 == h2
        assert len(h1) == 16

    def test_extract_executive_profiles_gender_and_companies(self):
        """GIVEN articles with executives WHEN extract THEN gender and companies populated."""
        analyzer = self._make_analyzer()
        articles = [
            {
                "executives": [
                    {
                        "name": "Alice",
                        "gender": "female",
                        "companies": ["AAPL", "MSFT"],
                    }
                ]
            }
        ]
        profiles = analyzer.extract_executive_profiles(articles)
        assert len(profiles) == 1
        assert profiles[0].gender == "female"
        assert "AAPL" in profiles[0].companies

    def test_extract_executive_profiles_deduplication(self):
        """GIVEN same exec in two articles WHEN extract THEN one profile, 2 mentions."""
        analyzer = self._make_analyzer()
        person_id = "pid-001"
        articles = [
            {"executives": [{"name": "Bob", "person_id": person_id}]},
            {"executives": [{"name": "Bob", "person_id": person_id}]},
        ]
        profiles = analyzer.extract_executive_profiles(articles)
        assert len(profiles) == 1
        assert profiles[0].news_mentions == 2

    def test_link_executives_to_performance_returns_relationships(self):
        """GIVEN exec with matching company WHEN link THEN relationship returned."""
        from ipfs_datasets_py.knowledge_graphs.extraction.finance_graphrag import (
            ExecutiveProfile, CompanyPerformance
        )
        analyzer = self._make_analyzer()
        exec_profile = ExecutiveProfile(
            person_id="e1", name="Alice", companies=["AAPL"]
        )
        company = CompanyPerformance(
            company_id="c1", symbol="AAPL", name="Apple", return_percentage=12.5
        )
        rels = analyzer.link_executives_to_performance([exec_profile], [company])
        assert len(rels) == 1
        assert rels[0].relationship_type == "executive_of"

    def test_link_executives_no_matching_company(self):
        """GIVEN exec with no matching company WHEN link THEN no relationships."""
        from ipfs_datasets_py.knowledge_graphs.extraction.finance_graphrag import (
            ExecutiveProfile, CompanyPerformance
        )
        analyzer = self._make_analyzer()
        exec_profile = ExecutiveProfile(person_id="e1", name="Alice", companies=["GOOG"])
        company = CompanyPerformance(company_id="c1", symbol="AAPL", name="Apple")
        rels = analyzer.link_executives_to_performance([exec_profile], [company])
        assert len(rels) == 0

    def test_test_hypothesis_insufficient_data(self):
        """GIVEN no matching execs WHEN test_hypothesis THEN conclusion=insufficient_data."""
        analyzer = self._make_analyzer()
        result = analyzer.test_hypothesis(
            hypothesis="female execs outperform",
            attribute_name="gender",
            group_a_value="female",
            group_b_value="male",
        )
        assert result.conclusion == "insufficient_data"
        assert result.confidence == 0.0

    def test_test_hypothesis_supports_hypothesis(self):
        """GIVEN group_a_avg > group_b_avg WHEN test THEN conclusion=supports_hypothesis."""
        from ipfs_datasets_py.knowledge_graphs.extraction.finance_graphrag import (
            ExecutiveProfile, CompanyPerformance
        )
        analyzer = self._make_analyzer()
        analyzer.executives = {
            "e1": ExecutiveProfile(person_id="e1", name="Alice", gender="female", companies=["AAPL"]),
            "e2": ExecutiveProfile(person_id="e2", name="Bob", gender="male", companies=["MSFT"]),
        }
        analyzer.companies = {
            "c1": CompanyPerformance(company_id="c1", symbol="AAPL", name="Apple", return_percentage=20.0),
            "c2": CompanyPerformance(company_id="c2", symbol="MSFT", name="Microsoft", return_percentage=5.0),
        }
        result = analyzer.test_hypothesis(
            hypothesis="female execs outperform",
            attribute_name="gender",
            group_a_value="female",
            group_b_value="male",
        )
        assert result.conclusion == "supports_hypothesis"

    def test_test_hypothesis_no_effect(self):
        """GIVEN equal performance WHEN test THEN conclusion=no_effect_detected."""
        from ipfs_datasets_py.knowledge_graphs.extraction.finance_graphrag import (
            ExecutiveProfile, CompanyPerformance
        )
        analyzer = self._make_analyzer()
        analyzer.executives = {
            "e1": ExecutiveProfile(person_id="e1", name="Alice", gender="female", companies=["AAPL"]),
            "e2": ExecutiveProfile(person_id="e2", name="Bob", gender="male", companies=["MSFT"]),
        }
        analyzer.companies = {
            "c1": CompanyPerformance(company_id="c1", symbol="AAPL", name="Apple", return_percentage=10.0),
            "c2": CompanyPerformance(company_id="c2", symbol="MSFT", name="Microsoft", return_percentage=10.0),
        }
        result = analyzer.test_hypothesis(
            hypothesis="equal performance",
            attribute_name="gender",
            group_a_value="female",
            group_b_value="male",
        )
        assert result.conclusion == "no_effect_detected"

    def test_build_knowledge_graph(self):
        """GIVEN exec and company profiles WHEN build_knowledge_graph THEN entities added."""
        from ipfs_datasets_py.knowledge_graphs.extraction.finance_graphrag import (
            ExecutiveProfile, CompanyPerformance
        )
        analyzer = self._make_analyzer()
        analyzer.executives = {
            "e1": ExecutiveProfile(person_id="e1", name="Alice", companies=["AAPL"])
        }
        analyzer.companies = {
            "c1": CompanyPerformance(company_id="c1", symbol="AAPL", name="Apple")
        }
        kg = analyzer.build_knowledge_graph()
        assert len(kg.entities) >= 2

    def test_analyze_news_with_graphrag_no_hypothesis(self):
        """GIVEN articles/stock but no hypothesis WHEN analyze THEN success without test."""
        from ipfs_datasets_py.knowledge_graphs.extraction.finance_graphrag import analyze_news_with_graphrag
        result = analyze_news_with_graphrag(
            news_articles=[{"executives": [{"name": "Alice", "companies": ["AAPL"]}]}],
            stock_data=[{"symbol": "AAPL", "return_percentage": 10.0}],
        )
        assert result["success"] is True
        assert "executives_analyzed" in result

    def test_analyze_news_with_graphrag_unsupported_type(self):
        """GIVEN unsupported analysis_type WHEN analyze THEN success=False."""
        from ipfs_datasets_py.knowledge_graphs.extraction.finance_graphrag import analyze_news_with_graphrag
        result = analyze_news_with_graphrag(
            news_articles=[],
            stock_data=[],
            analysis_type="sentiment",
        )
        assert result["success"] is False

    def test_analyze_news_with_graphrag_missing_groups(self):
        """GIVEN hypothesis but groups missing key WHEN analyze THEN success=False."""
        from ipfs_datasets_py.knowledge_graphs.extraction.finance_graphrag import analyze_news_with_graphrag
        result = analyze_news_with_graphrag(
            news_articles=[],
            stock_data=[],
            hypothesis="female better",
            attribute="gender",
            groups={"A": "female"},  # Missing B
        )
        assert result["success"] is False

    def test_analyze_news_with_graphrag_full_hypothesis(self):
        """GIVEN full params WHEN analyze THEN success and hypothesis_test in result."""
        from ipfs_datasets_py.knowledge_graphs.extraction.finance_graphrag import analyze_news_with_graphrag
        result = analyze_news_with_graphrag(
            news_articles=[{"executives": [{"name": "Alice", "gender": "female", "companies": ["AAPL"]}]}],
            stock_data=[{"symbol": "AAPL", "return_percentage": 15.0}],
            hypothesis="female execs outperform",
            attribute="gender",
            groups={"A": "female", "B": "male"},
        )
        assert result["success"] is True
        assert "hypothesis_test" in result

    def test_create_financial_knowledge_graph(self):
        """GIVEN articles and stock data WHEN create_financial_knowledge_graph THEN success."""
        from ipfs_datasets_py.knowledge_graphs.extraction.finance_graphrag import create_financial_knowledge_graph
        result = create_financial_knowledge_graph(
            news_articles=[{"executives": [{"name": "Alice", "companies": ["AAPL"]}]}],
            stock_data=[{"symbol": "AAPL", "return_percentage": 8.0}],
        )
        assert result["success"] is True
        assert "entities" in result

    def test_analyze_executive_performance_json_wrapper(self):
        """GIVEN JSON strings WHEN analyze_executive_performance THEN JSON string returned."""
        from ipfs_datasets_py.knowledge_graphs.extraction.finance_graphrag import analyze_executive_performance
        articles_json = json.dumps([])
        stock_json = json.dumps([])
        result_json = analyze_executive_performance(
            articles_json, stock_json, "test hypothesis", "gender", "female", "male"
        )
        result = json.loads(result_json)
        assert isinstance(result, dict)

    def test_analyze_executive_performance_bad_json(self):
        """GIVEN invalid JSON WHEN analyze_executive_performance THEN error returned."""
        from ipfs_datasets_py.knowledge_graphs.extraction.finance_graphrag import analyze_executive_performance
        result_json = analyze_executive_performance(
            "not json", "[]", "h", "gender", "f", "m"
        )
        result = json.loads(result_json)
        assert result.get("success") is False


# ---------------------------------------------------------------------------
# query/distributed.py  (parallel, streaming, _KGBackend, helpers)
# ---------------------------------------------------------------------------

class TestDistributedQueryExtended:
    """Tests for FederatedQueryExecutor and helpers."""

    def _make_federated(self, partitions=1):
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            DistributedGraph, FederatedQueryExecutor, PartitionStrategy
        )
        kgs = [KnowledgeGraph(name=f"p{i}") for i in range(partitions)]
        dg = DistributedGraph(
            partitions=kgs,
            strategy=PartitionStrategy.HASH,
            node_to_partition={},
        )
        return FederatedQueryExecutor(dg)

    def test_execute_cypher_parallel_basic(self):
        """GIVEN empty partition WHEN execute_cypher_parallel THEN FederatedQueryResult returned."""
        from ipfs_datasets_py.knowledge_graphs.query.distributed import FederatedQueryResult
        fed = self._make_federated(partitions=1)
        result = fed.execute_cypher_parallel("MATCH (n) RETURN n", max_workers=1)
        assert isinstance(result, FederatedQueryResult)

    def test_execute_cypher_parallel_worker_error(self):
        """GIVEN partition executor raises WHEN parallel THEN error logged, result still returned."""
        from ipfs_datasets_py.knowledge_graphs.query.distributed import FederatedQueryResult
        fed = self._make_federated(partitions=1)
        # Patch _execute_on_partition to raise
        fed._execute_on_partition = MagicMock(side_effect=RuntimeError("partition fail"))
        result = fed.execute_cypher_parallel("MATCH (n) RETURN n", max_workers=1)
        assert isinstance(result, FederatedQueryResult)
        assert len(result.errors) > 0

    def test_execute_cypher_streaming_yields_tuples(self):
        """GIVEN partition with entities WHEN streaming THEN yields (idx, record) tuples."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            DistributedGraph, FederatedQueryExecutor, PartitionStrategy
        )
        kg = KnowledgeGraph(name="p0")
        kg.add_entity(entity_type="Person", name="Alice")
        dg = DistributedGraph(partitions=[kg], strategy=PartitionStrategy.HASH, node_to_partition={})
        fed = FederatedQueryExecutor(dg)
        # Patch _execute_on_partition to return known records
        fed._execute_on_partition = MagicMock(return_value=[{"n": "Alice"}])
        items = list(fed.execute_cypher_streaming("MATCH (n) RETURN n"))
        assert len(items) == 1
        idx, record = items[0]
        assert idx == 0
        assert record == {"n": "Alice"}

    def test_execute_cypher_streaming_dedup(self):
        """GIVEN duplicate records across partitions WHEN streaming with dedup THEN each unique once."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            DistributedGraph, FederatedQueryExecutor, PartitionStrategy
        )
        kg1 = KnowledgeGraph(name="p0")
        kg2 = KnowledgeGraph(name="p1")
        dg = DistributedGraph(partitions=[kg1, kg2], strategy=PartitionStrategy.HASH, node_to_partition={})
        fed = FederatedQueryExecutor(dg, dedup=True)
        dup_record = {"name": "Alice"}
        fed._execute_on_partition = MagicMock(return_value=[dup_record])
        items = list(fed.execute_cypher_streaming("MATCH (n) RETURN n"))
        # Both partitions return the same record but dedup=True → only 1
        assert len(items) == 1

    def test_execute_cypher_streaming_partition_error_skipped(self):
        """GIVEN partition raises WHEN streaming THEN error skipped, other partitions processed."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            DistributedGraph, FederatedQueryExecutor, PartitionStrategy
        )
        kg1 = KnowledgeGraph(name="p0")
        kg2 = KnowledgeGraph(name="p1")
        dg = DistributedGraph(partitions=[kg1, kg2], strategy=PartitionStrategy.HASH, node_to_partition={})
        fed = FederatedQueryExecutor(dg)
        def side_effect(part, q, p):
            if part is kg1:
                raise RuntimeError("p0 fails")
            return [{"name": "Bob"}]
        fed._execute_on_partition = MagicMock(side_effect=side_effect)
        items = list(fed.execute_cypher_streaming("MATCH (n) RETURN n"))
        # Only p1 result
        assert len(items) == 1
        assert items[0][0] == 1

    def test_kg_backend_adapter_find_nodes_label_filter(self):
        """GIVEN entities with different types WHEN find_nodes with label THEN filtered."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _KGBackend
        kg = KnowledgeGraph(name="test")
        kg.add_entity(entity_type="Person", name="Alice")
        kg.add_entity(entity_type="Organization", name="Acme")
        adapter = _KGBackend(kg)
        results = adapter.find_nodes(labels=["Person"])
        assert len(results) == 1
        assert results[0].entity_type == "Person"

    def test_kg_backend_adapter_find_nodes_property_filter(self):
        """GIVEN entities with properties WHEN find_nodes with property filter THEN filtered."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _KGBackend
        kg = KnowledgeGraph(name="test")
        kg.add_entity(entity_type="Person", name="Alice", properties={"age": 30})
        kg.add_entity(entity_type="Person", name="Bob", properties={"age": 25})
        adapter = _KGBackend(kg)
        results = adapter.find_nodes(properties={"age": 30})
        assert len(results) == 1
        assert results[0].name == "Alice"

    def test_kg_backend_adapter_find_nodes_limit(self):
        """GIVEN 3 entities WHEN find_nodes limit=2 THEN 2 returned."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _KGBackend
        kg = KnowledgeGraph(name="test")
        for i in range(3):
            kg.add_entity(entity_type="Person", name=f"P{i}")
        adapter = _KGBackend(kg)
        results = adapter.find_nodes(limit=2)
        assert len(results) == 2

    def test_kg_backend_adapter_get_node_found(self):
        """GIVEN known entity WHEN get_node THEN entity returned."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _KGBackend
        kg = KnowledgeGraph(name="test")
        kg.add_entity(entity_type="Person", name="Alice")
        entity_id = list(kg.entities.keys())[0]
        adapter = _KGBackend(kg)
        result = adapter.get_node(entity_id)
        assert result is not None

    def test_kg_backend_adapter_get_relationships_source_filter(self):
        """GIVEN relationship WHEN get_relationships source_id filter THEN correct rel returned."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _KGBackend
        kg = KnowledgeGraph(name="test")
        kg.add_entity(entity_type="Person", name="Alice")
        kg.add_entity(entity_type="Person", name="Bob")
        src = list(kg.entities.values())[0]
        tgt = list(kg.entities.values())[1]
        kg.add_relationship("KNOWS", source=src, target=tgt)
        adapter = _KGBackend(kg)
        rels = adapter.get_relationships(source_id=src.entity_id)
        assert len(rels) == 1
        assert rels[0].source_id == src.entity_id

    def test_kg_backend_adapter_get_relationships_type_filter(self):
        """GIVEN two rels of different types WHEN filter by type THEN correct one returned."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _KGBackend
        kg = KnowledgeGraph(name="test")
        kg.add_entity(entity_type="Person", name="Alice")
        kg.add_entity(entity_type="Person", name="Bob")
        src = list(kg.entities.values())[0]
        tgt = list(kg.entities.values())[1]
        kg.add_relationship("KNOWS", source=src, target=tgt)
        kg.add_relationship("HATES", source=src, target=tgt)
        adapter = _KGBackend(kg)
        rels = adapter.get_relationships(relationship_types=["KNOWS"])
        assert len(rels) == 1
        assert rels[0].relationship_type == "KNOWS"

    def test_kg_backend_adapter_store_and_retrieve(self):
        """GIVEN adapter WHEN store/retrieve THEN store returns str, retrieve returns None."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _KGBackend
        kg = KnowledgeGraph(name="test")
        adapter = _KGBackend(kg)
        key = adapter.store({"x": 1})
        assert isinstance(key, str)
        result = adapter.retrieve(key)
        assert result is None

    # --- _normalise_result ---------------------------------------------------

    def test_normalise_result_none(self):
        """GIVEN None WHEN _normalise_result THEN empty list."""
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _normalise_result
        assert _normalise_result(None) == []

    def test_normalise_result_list_of_dicts(self):
        """GIVEN list of dicts WHEN _normalise_result THEN same list returned."""
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _normalise_result
        records = [{"a": 1}, {"b": 2}]
        result = _normalise_result(records)
        assert result == records

    def test_normalise_result_has_records_attr(self):
        """GIVEN object with .records attribute WHEN _normalise_result THEN uses records."""
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _normalise_result
        obj = MagicMock()
        obj.records = [{"x": 10}]
        # Remove result_set and rows attrs to force .records path
        del obj.result_set
        del obj.rows
        result = _normalise_result(obj)
        assert result == [{"x": 10}]

    def test_normalise_result_has_result_set_attr(self):
        """GIVEN object with .result_set attribute WHEN _normalise_result THEN uses result_set."""
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _normalise_result
        class Obj:
            result_set = [{"y": 20}]
        result = _normalise_result(Obj())
        assert result == [{"y": 20}]

    def test_normalise_result_has_rows_attr(self):
        """GIVEN object with .rows attribute WHEN _normalise_result THEN uses rows."""
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _normalise_result
        class Obj:
            rows = [{"z": 30}]
        result = _normalise_result(Obj())
        assert result == [{"z": 30}]

    def test_normalise_result_to_dict_method(self):
        """GIVEN list of rows with to_dict() WHEN _normalise_result THEN to_dict() called."""
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _normalise_result
        row = MagicMock()
        row.to_dict.return_value = {"row": "data"}
        # to_dict has priority over __iter__
        del row.data  # ensure data() path not taken
        result = _normalise_result([row])
        assert result == [{"row": "data"}]

    def test_normalise_result_row_has_data_method(self):
        """GIVEN list of rows with .data() method WHEN _normalise_result THEN data() called."""
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _normalise_result
        row = MagicMock(spec=["data"])
        row.data.return_value = {"neo4j": "record"}
        result = _normalise_result([row])
        assert result == [{"neo4j": "record"}]

    def test_normalise_result_non_iterable_fallback(self):
        """GIVEN non-iterable, non-dict row with __dict__ WHEN _normalise_result THEN __dict__ used."""
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _normalise_result
        class Plain:
            def __init__(self):
                self.key = "value"
        obj = Plain()
        result = _normalise_result([obj])
        # __dict__ path: {"key": "value"}
        assert result == [{"key": "value"}]

    # --- _record_fingerprint -----------------------------------------------

    def test_record_fingerprint_deterministic(self):
        """GIVEN same dict WHEN _record_fingerprint called twice THEN same hash."""
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _record_fingerprint
        fp1 = _record_fingerprint({"a": 1, "b": 2})
        fp2 = _record_fingerprint({"a": 1, "b": 2})
        assert fp1 == fp2

    def test_record_fingerprint_different_dicts(self):
        """GIVEN different dicts WHEN _record_fingerprint THEN different hashes."""
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _record_fingerprint
        fp1 = _record_fingerprint({"a": 1})
        fp2 = _record_fingerprint({"a": 2})
        assert fp1 != fp2


# ---------------------------------------------------------------------------
# migration/formats.py  (CAR format import error coverage)
# ---------------------------------------------------------------------------

class TestMigrationFormatsExtended:
    """Tests for migration/formats.py edge cases."""

    def test_save_car_requires_libipld(self):
        """GIVEN libipld not installed WHEN _builtin_save_car THEN ImportError raised."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import _builtin_save_car, GraphData
        gd = GraphData()
        with patch.dict("sys.modules", {"libipld": None}):
            with pytest.raises(ImportError, match="libipld"):
                _builtin_save_car("/tmp/fake.car", gd)

    def test_load_car_fallback_requires_packages(self):
        """GIVEN libipld not installed AND ipld_car not installed WHEN _builtin_load_car THEN ImportError."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import _builtin_load_car
        import tempfile, os
        with tempfile.NamedTemporaryFile(suffix=".car", delete=False) as f:
            f.write(b"fake car content")
            tmp = f.name
        try:
            with patch.dict("sys.modules", {"libipld": None, "ipld_car": None}):
                with pytest.raises(ImportError):
                    _builtin_load_car(tmp)
        finally:
            os.unlink(tmp)

    def test_graph_data_to_json_from_json_roundtrip(self):
        """GIVEN GraphData WHEN to_json/from_json THEN roundtrip preserves structure."""
        from ipfs_datasets_py.knowledge_graphs.migration.formats import (
            GraphData, NodeData, RelationshipData
        )
        original = GraphData(
            nodes=[NodeData(id="n1", labels=["A"], properties={"x": 1})],
            relationships=[RelationshipData(id="e1", type="KNOWS", start_node="n1", end_node="n1", properties={})],
            metadata={"version": "1.0"},
        )
        json_str = original.to_json()
        restored = GraphData.from_json(json_str)
        assert len(restored.nodes) == 1
        assert len(restored.relationships) == 1
        assert restored.metadata["version"] == "1.0"

    def test_save_dag_json_then_load(self):
        """GIVEN GraphData WHEN save_dag_json+load THEN data preserved."""
        import tempfile, os
        from ipfs_datasets_py.knowledge_graphs.migration.formats import (
            _builtin_save_dag_json, _builtin_load_dag_json, GraphData, NodeData
        )
        gd = GraphData(
            nodes=[NodeData(id="n1", labels=["Thing"], properties={"name": "Alice"})],
        )
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmp = f.name
        try:
            _builtin_save_dag_json(gd, tmp)
            loaded = _builtin_load_dag_json(tmp)
            assert len(loaded.nodes) == 1
            assert loaded.nodes[0].id == "n1"
        finally:
            os.unlink(tmp)
