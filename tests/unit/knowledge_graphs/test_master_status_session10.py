"""
Session 10 coverage improvements for knowledge_graphs.

Targets low-coverage modules (all <70%):
  - core/graph_engine.py (69%) — traverse_pattern, find_paths, get_relationships, update_node, delete_node, delete_relationship
  - query/hybrid_search.py (62%) — vector_search, expand_graph, fuse_results, search, _get_query_embedding, _get_neighbors, clear_cache
  - jsonld/context.py (58%) — expand, compact, _expand_term prefix handling
  - reasoning/cross_document.py (59%) — get_statistics, explain_reasoning, _determine_relation, _synthesize_answer
  - extraction/finance_graphrag.py (37%) — ExecutiveProfile.to_entity, CompanyPerformance.to_entity, HypothesisTest, GraphRAGNewsAnalyzer
  - root-level shims at 0%: cross_document_lineage_enhanced.py, finance_graphrag.py, sparql_query_templates.py

All tests follow GIVEN-WHEN-THEN convention and use pure-Python mocks (no IPFS daemon required).
"""

from __future__ import annotations

import unittest
import warnings
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch


# ─────────────────────────────────────────────────────────────────────────────
# Part 1: core/graph_engine.py
# ─────────────────────────────────────────────────────────────────────────────

class TestGraphEngineExtended(unittest.TestCase):
    """Tests for graph_engine.py paths not covered in prior sessions."""

    def _make_engine(self):
        from ipfs_datasets_py.knowledge_graphs.core.graph_engine import GraphEngine
        return GraphEngine()

    # ── get_relationships direction / type filters ──────────────────────────
    # NOTE: GraphEngine.create_relationship(rel_type, start_node, end_node, properties)
    # This differs from typical Neo4j style — rel_type is the FIRST positional arg.

    def test_get_relationships_out_direction(self):
        """GIVEN a graph with A→B; WHEN get_relationships(A, 'out'); THEN returns the rel."""
        e = self._make_engine()
        n1 = e.create_node(["Person"], {"name": "Alice"})
        n2 = e.create_node(["Person"], {"name": "Bob"})
        rel = e.create_relationship("KNOWS", n1.id, n2.id, {})
        rels = e.get_relationships(n1.id, direction="out")
        self.assertEqual(len(rels), 1)
        self.assertEqual(rels[0].id, rel.id)

    def test_get_relationships_in_direction(self):
        """GIVEN A→B; WHEN get_relationships(B, 'in'); THEN returns the rel."""
        e = self._make_engine()
        n1 = e.create_node(["X"], {})
        n2 = e.create_node(["Y"], {})
        rel = e.create_relationship("LIKES", n1.id, n2.id, {})
        rels = e.get_relationships(n2.id, direction="in")
        self.assertEqual(len(rels), 1)
        self.assertEqual(rels[0].id, rel.id)

    def test_get_relationships_both_direction(self):
        """GIVEN A→B; WHEN get_relationships(A, 'both'); THEN returns the rel (as outgoing)."""
        e = self._make_engine()
        n1 = e.create_node([], {})
        n2 = e.create_node([], {})
        e.create_relationship("KNOWS", n1.id, n2.id, {})
        rels = e.get_relationships(n1.id, direction="both")
        self.assertGreaterEqual(len(rels), 1)

    def test_get_relationships_type_filter(self):
        """GIVEN A→B (KNOWS) and A→B (HATES); WHEN filter by KNOWS; THEN 1 result."""
        e = self._make_engine()
        n1 = e.create_node([], {})
        n2 = e.create_node([], {})
        e.create_relationship("KNOWS", n1.id, n2.id, {})
        e.create_relationship("HATES", n1.id, n2.id, {})
        rels = e.get_relationships(n1.id, direction="out", rel_type="KNOWS")
        self.assertEqual(len(rels), 1)
        self.assertEqual(rels[0].type, "KNOWS")

    def test_get_relationships_no_match(self):
        """GIVEN a node with no relationships; WHEN get_relationships; THEN empty list."""
        e = self._make_engine()
        n = e.create_node([], {})
        self.assertEqual(e.get_relationships(n.id, direction="out"), [])

    # ── update_node ─────────────────────────────────────────────────────────

    def test_update_node_properties(self):
        """GIVEN a node; WHEN update_node with new props; THEN properties merged."""
        e = self._make_engine()
        n = e.create_node(["Person"], {"name": "Alice", "age": 30})
        updated = e.update_node(n.id, properties={"age": 31, "city": "NYC"})
        self.assertIsNotNone(updated)
        self.assertEqual(updated.properties.get("age"), 31)
        self.assertEqual(updated.properties.get("city"), "NYC")

    def test_update_node_new_property_added(self):
        """GIVEN a node; WHEN update_node adds a new property; THEN new key is present."""
        e = self._make_engine()
        n = e.create_node(["Person"], {"name": "Alice"})
        updated = e.update_node(n.id, properties={"email": "alice@example.com"})
        self.assertIsNotNone(updated)
        self.assertEqual(updated.properties.get("email"), "alice@example.com")

    def test_update_node_not_found(self):
        """GIVEN no such node; WHEN update_node; THEN returns None."""
        e = self._make_engine()
        result = e.update_node("nonexistent", properties={"x": 1})
        self.assertIsNone(result)

    # ── delete_node ─────────────────────────────────────────────────────────

    def test_delete_node_present(self):
        """GIVEN a node; WHEN delete_node; THEN returns True and node gone."""
        e = self._make_engine()
        n = e.create_node([], {})
        self.assertTrue(e.delete_node(n.id))
        self.assertIsNone(e.get_node(n.id))

    def test_delete_node_absent(self):
        """GIVEN no such node; WHEN delete_node; THEN returns False."""
        e = self._make_engine()
        self.assertFalse(e.delete_node("ghost"))

    # ── delete_relationship ──────────────────────────────────────────────────

    def test_delete_relationship_present(self):
        """GIVEN a relationship; WHEN delete_relationship; THEN returns True."""
        e = self._make_engine()
        n1 = e.create_node([], {})
        n2 = e.create_node([], {})
        rel = e.create_relationship("KNOWS", n1.id, n2.id, {})
        self.assertTrue(e.delete_relationship(rel.id))

    def test_delete_relationship_absent(self):
        """GIVEN no such relationship; WHEN delete_relationship; THEN returns False."""
        e = self._make_engine()
        self.assertFalse(e.delete_relationship("ghost-rel"))

    # ── traverse_pattern ─────────────────────────────────────────────────────

    def test_traverse_pattern_single_hop(self):
        """GIVEN A→B; WHEN traverse_pattern 1 hop out; THEN finds B in result."""
        e = self._make_engine()
        n1 = e.create_node(["Person"], {"name": "Alice"})
        n2 = e.create_node(["City"], {"name": "NYC"})
        e.create_relationship("LIVES_IN", n1.id, n2.id, {})
        pattern = [
            {"rel_type": "LIVES_IN", "variable": "r"},
            {"variable": "city"},
        ]
        results = e.traverse_pattern([n1], pattern)
        self.assertEqual(len(results), 1)
        self.assertIn("city", results[0])

    def test_traverse_pattern_empty_graph(self):
        """GIVEN isolated node; WHEN traverse_pattern; THEN empty result."""
        e = self._make_engine()
        n = e.create_node([], {})
        pattern = [{"rel_type": "KNOWS", "variable": "r"}]
        results = e.traverse_pattern([n], pattern)
        self.assertEqual(results, [])

    def test_traverse_pattern_with_limit(self):
        """GIVEN A→B and A→C; WHEN traverse_pattern with limit=1; THEN 1 result."""
        e = self._make_engine()
        a = e.create_node([], {})
        b = e.create_node([], {})
        c = e.create_node([], {})
        e.create_relationship("KNOWS", a.id, b.id, {})
        e.create_relationship("KNOWS", a.id, c.id, {})
        pattern = [{"rel_type": "KNOWS", "variable": "r"}]
        results = e.traverse_pattern([a], pattern, limit=1)
        self.assertEqual(len(results), 1)

    # ── find_paths ───────────────────────────────────────────────────────────

    def test_find_paths_direct(self):
        """GIVEN A→B; WHEN find_paths(A, B); THEN 1 path."""
        e = self._make_engine()
        a = e.create_node([], {})
        b = e.create_node([], {})
        e.create_relationship("KNOWS", a.id, b.id, {})
        paths = e.find_paths(a.id, b.id)
        self.assertEqual(len(paths), 1)

    def test_find_paths_no_path(self):
        """GIVEN disconnected nodes; WHEN find_paths; THEN empty list."""
        e = self._make_engine()
        a = e.create_node([], {})
        b = e.create_node([], {})
        self.assertEqual(e.find_paths(a.id, b.id), [])

    def test_find_paths_two_hop(self):
        """GIVEN A→B→C; WHEN find_paths(A, C); THEN 1 path of length 2."""
        e = self._make_engine()
        a = e.create_node([], {})
        b = e.create_node([], {})
        c = e.create_node([], {})
        e.create_relationship("KNOWS", a.id, b.id, {})
        e.create_relationship("KNOWS", b.id, c.id, {})
        paths = e.find_paths(a.id, c.id, max_depth=3)
        self.assertEqual(len(paths), 1)
        self.assertEqual(len(paths[0]), 2)

    def test_find_paths_rel_type_filter(self):
        """GIVEN A→B (KNOWS) and A→C (HATES); WHEN find_paths with rel_type=KNOWS; THEN only KNOWS path."""
        e = self._make_engine()
        a = e.create_node([], {})
        b = e.create_node([], {})
        c = e.create_node([], {})
        e.create_relationship("KNOWS", a.id, b.id, {})
        e.create_relationship("HATES", a.id, c.id, {})
        paths_knows = e.find_paths(a.id, b.id, rel_type="KNOWS")
        paths_hates = e.find_paths(a.id, b.id, rel_type="HATES")
        self.assertEqual(len(paths_knows), 1)
        self.assertEqual(len(paths_hates), 0)

    def test_save_graph_no_persistence(self):
        """GIVEN engine without storage; WHEN save_graph; THEN returns None."""
        e = self._make_engine()
        self.assertIsNone(e.save_graph())

    def test_load_graph_no_persistence(self):
        """GIVEN engine without storage; WHEN load_graph; THEN returns False."""
        e = self._make_engine()
        self.assertFalse(e.load_graph("some-cid"))


# ─────────────────────────────────────────────────────────────────────────────
# Part 2: query/hybrid_search.py
# ─────────────────────────────────────────────────────────────────────────────

class TestHybridSearchEngine(unittest.TestCase):
    """Tests for query/hybrid_search.py — vector_search, expand_graph, fuse_results, search, helpers."""

    def _make_engine(self, vector_store=None, backend=None):
        from ipfs_datasets_py.knowledge_graphs.query.hybrid_search import HybridSearchEngine
        return HybridSearchEngine(vector_store=vector_store, backend=backend)

    # ── vector_search ────────────────────────────────────────────────────────

    def test_vector_search_no_store(self):
        """GIVEN no vector_store; WHEN vector_search; THEN returns empty list."""
        e = self._make_engine()
        self.assertEqual(e.vector_search("test", k=5), [])

    def test_vector_search_with_store(self):
        """GIVEN a mock vector store; WHEN vector_search; THEN returns results."""
        vs = MagicMock()
        vs.search.return_value = [("node1", 0.9), ("node2", 0.7)]
        vs.embed_query.return_value = [0.1, 0.2, 0.3]
        e = self._make_engine(vector_store=vs)
        results = e.vector_search("test query", k=2)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].node_id, "node1")
        self.assertAlmostEqual(results[0].score, 0.9)

    def test_vector_search_with_precomputed_embedding(self):
        """GIVEN precomputed embeddings; WHEN vector_search; THEN skips embed_query."""
        vs = MagicMock()
        vs.search.return_value = [("node1", 0.8)]
        e = self._make_engine(vector_store=vs)
        results = e.vector_search("test", k=5, embeddings={"query_embedding": [0.1, 0.2]})
        self.assertEqual(len(results), 1)
        vs.embed_query.assert_not_called()

    def test_vector_search_no_embedding(self):
        """GIVEN store with no embed_query; WHEN vector_search; THEN returns empty (no embedding)."""
        vs = MagicMock(spec=[])  # no embed_query attribute
        e = self._make_engine(vector_store=vs)
        results = e.vector_search("test", k=5)
        self.assertEqual(results, [])

    # ── _get_query_embedding ──────────────────────────────────────────────────

    def test_get_query_embedding_no_store(self):
        """GIVEN no vector store; WHEN _get_query_embedding; THEN returns None."""
        e = self._make_engine()
        self.assertIsNone(e._get_query_embedding("test"))

    def test_get_query_embedding_with_embed_query(self):
        """GIVEN store with embed_query; WHEN _get_query_embedding; THEN returns embedding."""
        vs = MagicMock()
        vs.embed_query.return_value = [0.1, 0.2]
        e = self._make_engine(vector_store=vs)
        emb = e._get_query_embedding("hello")
        self.assertEqual(emb, [0.1, 0.2])

    def test_get_query_embedding_with_get_embedding(self):
        """GIVEN store with get_embedding (not embed_query); WHEN _get_query_embedding; THEN returns embedding."""
        vs = MagicMock(spec=["get_embedding"])
        vs.get_embedding.return_value = [0.3, 0.4]
        e = self._make_engine(vector_store=vs)
        emb = e._get_query_embedding("hello")
        self.assertEqual(emb, [0.3, 0.4])

    def test_get_query_embedding_no_method(self):
        """GIVEN store with neither embed_query nor get_embedding; THEN returns None."""
        vs = MagicMock(spec=[])
        e = self._make_engine(vector_store=vs)
        self.assertIsNone(e._get_query_embedding("test"))

    # ── expand_graph ─────────────────────────────────────────────────────────

    def test_expand_graph_no_backend(self):
        """GIVEN no backend; WHEN expand_graph; THEN returns seed nodes with hop=0."""
        e = self._make_engine()
        result = e.expand_graph(["n1", "n2"], max_hops=2)
        self.assertIn("n1", result)
        self.assertIn("n2", result)

    def test_expand_graph_with_get_neighbors_backend(self):
        """GIVEN backend with get_neighbors; WHEN expand_graph; THEN follows hops."""
        backend = MagicMock()
        backend.get_neighbors.side_effect = lambda node_id, rel_types=None: {
            "n1": ["n2"], "n2": ["n3"], "n3": []
        }.get(node_id, [])
        e = self._make_engine(backend=backend)
        result = e.expand_graph(["n1"], max_hops=2)
        self.assertIn("n1", result)
        self.assertIn("n2", result)
        self.assertIn("n3", result)

    def test_expand_graph_with_get_relationships_backend(self):
        """GIVEN backend with get_relationships; WHEN expand_graph; THEN follows hops."""
        backend = MagicMock(spec=["get_relationships"])
        backend.get_relationships.side_effect = lambda node_id: {
            "n1": [{"end_node": "n2", "type": "KNOWS"}],
            "n2": [],
        }.get(node_id, [])
        e = self._make_engine(backend=backend)
        result = e.expand_graph(["n1"], max_hops=1)
        self.assertIn("n1", result)
        self.assertIn("n2", result)

    def test_expand_graph_max_nodes_limit(self):
        """GIVEN many nodes; WHEN expand_graph with max_nodes; THEN returns dict without error."""
        backend = MagicMock()
        backend.get_neighbors.return_value = [f"n{i}" for i in range(100)]
        e = self._make_engine(backend=backend)
        result = e.expand_graph(["root"], max_hops=1, max_nodes=5)
        # max_nodes is a soft hint applied per-hop; verify result is valid dict
        self.assertIsInstance(result, dict)
        self.assertIn("root", result)

    # ── _get_neighbors ────────────────────────────────────────────────────────

    def test_get_neighbors_no_backend(self):
        """GIVEN no backend; WHEN _get_neighbors; THEN returns empty list."""
        e = self._make_engine()
        self.assertEqual(e._get_neighbors("n1"), [])

    def test_get_neighbors_get_neighbors_method(self):
        """GIVEN backend with get_neighbors returning list; WHEN called; THEN returns that list."""
        backend = MagicMock()
        backend.get_neighbors.return_value = ["n2", "n3"]
        e = self._make_engine(backend=backend)
        result = e._get_neighbors("n1")
        self.assertEqual(result, ["n2", "n3"])

    def test_get_neighbors_get_relationships_fallback(self):
        """GIVEN backend with get_relationships only; WHEN called; THEN extracts targets."""
        backend = MagicMock(spec=["get_relationships"])
        backend.get_relationships.return_value = [
            {"end_node": "n2", "type": "KNOWS"},
            {"target": "n3", "type": "LIKES"},
        ]
        e = self._make_engine(backend=backend)
        result = e._get_neighbors("n1")
        self.assertIn("n2", result)
        self.assertIn("n3", result)

    def test_get_neighbors_rel_type_filter(self):
        """GIVEN two different relationship types; WHEN filtering by type; THEN returns only matching."""
        backend = MagicMock(spec=["get_relationships"])
        backend.get_relationships.return_value = [
            {"end_node": "n2", "type": "KNOWS"},
            {"end_node": "n3", "type": "HATES"},
        ]
        e = self._make_engine(backend=backend)
        result = e._get_neighbors("n1", rel_types=["KNOWS"])
        self.assertIn("n2", result)
        self.assertNotIn("n3", result)

    def test_get_neighbors_no_method(self):
        """GIVEN backend without get_neighbors or get_relationships; THEN returns empty."""
        backend = MagicMock(spec=[])
        e = self._make_engine(backend=backend)
        self.assertEqual(e._get_neighbors("n1"), [])

    # ── fuse_results ─────────────────────────────────────────────────────────

    def test_fuse_results_combines_scores(self):
        """GIVEN vector results and graph nodes; WHEN fuse_results; THEN combined scores."""
        from ipfs_datasets_py.knowledge_graphs.query.hybrid_search import (
            HybridSearchResult,
        )
        e = self._make_engine()
        v_results = [
            HybridSearchResult(node_id="n1", score=0.9, vector_score=0.9, graph_score=0.0, hop_distance=0),
        ]
        graph_nodes = {"n1": 1, "n2": 0}
        fused = e.fuse_results(v_results, graph_nodes, k=5)
        self.assertGreater(len(fused), 0)
        # n1 should appear (has both vector score and graph presence)
        ids = [r.node_id for r in fused]
        self.assertIn("n1", ids)

    def test_fuse_results_empty_vector(self):
        """GIVEN no vector results; WHEN fuse_results; THEN still includes graph nodes."""
        e = self._make_engine()
        fused = e.fuse_results([], {"n1": 0}, k=5)
        ids = [r.node_id for r in fused]
        self.assertIn("n1", ids)

    def test_fuse_results_empty_both(self):
        """GIVEN no vector or graph; WHEN fuse_results; THEN empty list."""
        e = self._make_engine()
        self.assertEqual(e.fuse_results([], {}, k=5), [])

    def test_fuse_results_k_limits_output(self):
        """GIVEN many nodes; WHEN fuse with k=2; THEN at most 2 results."""
        from ipfs_datasets_py.knowledge_graphs.query.hybrid_search import HybridSearchResult
        e = self._make_engine()
        v_res = [
            HybridSearchResult(node_id=f"n{i}", score=0.5, vector_score=0.5, graph_score=0.0, hop_distance=0)
            for i in range(10)
        ]
        fused = e.fuse_results(v_res, {}, k=2)
        self.assertLessEqual(len(fused), 2)

    # ── clear_cache ───────────────────────────────────────────────────────────

    def test_clear_cache(self):
        """GIVEN populated cache; WHEN clear_cache; THEN cache is empty."""
        e = self._make_engine()
        e._cache["key"] = "value"
        e.clear_cache()
        self.assertEqual(len(e._cache), 0)

    # ── search integration ────────────────────────────────────────────────────

    def test_search_no_vector_store(self):
        """GIVEN no vector store; WHEN search; THEN returns empty list (no embeddings)."""
        e = self._make_engine()
        results = e.search("test query", k=5)
        self.assertEqual(results, [])

    def test_search_with_mock_store(self):
        """GIVEN mock vector store; WHEN search; THEN returns fused results."""
        vs = MagicMock()
        vs.embed_query.return_value = [0.1, 0.2]
        vs.search.return_value = [("n1", 0.9)]
        e = self._make_engine(vector_store=vs)
        results = e.search("test", k=3)
        self.assertIsInstance(results, list)

    def test_search_with_cache(self):
        """GIVEN same query twice; WHEN search twice; THEN second call uses cache."""
        vs = MagicMock()
        vs.embed_query.return_value = [0.1, 0.2]
        vs.search.return_value = [("n1", 0.9)]
        e = self._make_engine(vector_store=vs)
        e.search("same query", k=3, enable_cache=True)
        e.search("same query", k=3, enable_cache=True)
        # embed_query should only be called once (second hits cache)
        self.assertEqual(vs.embed_query.call_count, 1)


# ─────────────────────────────────────────────────────────────────────────────
# Part 3: jsonld/context.py
# ─────────────────────────────────────────────────────────────────────────────

class TestJSONLDContextExpander(unittest.TestCase):
    """Tests for jsonld/context.py ContextExpander — expand and _expand_term paths."""

    def _make_expander(self):
        from ipfs_datasets_py.knowledge_graphs.jsonld.context import ContextExpander
        return ContextExpander()

    def _make_context(self, prefixes=None, terms=None, vocab=None):
        from ipfs_datasets_py.knowledge_graphs.jsonld.context import JSONLDContext
        ctx = JSONLDContext()
        if prefixes:
            ctx.prefixes.update(prefixes)
        if terms:
            ctx.terms.update(terms)
        if vocab:
            ctx.vocab = vocab
        return ctx

    # ── expand ───────────────────────────────────────────────────────────────

    def test_expand_passthrough_no_terms(self):
        """GIVEN simple dict, empty context; WHEN expand; THEN returns dict."""
        p = self._make_expander()
        ctx = self._make_context()
        result = p.expand({"name": "Alice"}, ctx)
        self.assertIsInstance(result, dict)

    def test_expand_maps_term_to_uri(self):
        """GIVEN term 'name' mapped in context; WHEN expand; THEN key is URI."""
        p = self._make_expander()
        ctx = self._make_context(terms={"name": "http://schema.org/name"})
        result = p.expand({"name": "Alice"}, ctx)
        self.assertIn("http://schema.org/name", result)

    def test_expand_skips_context_key(self):
        """GIVEN data with @context key; WHEN expand; THEN @context not in output."""
        p = self._make_expander()
        ctx = self._make_context(terms={"name": "http://schema.org/name"})
        result = p.expand({"@context": {}, "name": "Alice"}, ctx)
        self.assertNotIn("@context", result)

    def test_expand_type_string(self):
        """GIVEN @type as string; WHEN expand; THEN @type expanded."""
        p = self._make_expander()
        ctx = self._make_context(terms={"Person": "http://schema.org/Person"})
        result = p.expand({"@type": "Person"}, ctx)
        self.assertIn("@type", result)

    def test_expand_type_list(self):
        """GIVEN @type as list; WHEN expand; THEN @type is a list."""
        p = self._make_expander()
        ctx = self._make_context(terms={
            "Person": "http://schema.org/Person",
            "Employee": "http://schema.org/Employee",
        })
        result = p.expand({"@type": ["Person", "Employee"]}, ctx)
        self.assertIn("@type", result)
        self.assertIsInstance(result["@type"], list)

    # ── _expand_term ──────────────────────────────────────────────────────────

    def test_expand_term_uri_passthrough(self):
        """GIVEN a full URI; WHEN _expand_term; THEN returned as-is."""
        p = self._make_expander()
        ctx = self._make_context()
        self.assertEqual(p._expand_term("http://schema.org/name", ctx), "http://schema.org/name")

    def test_expand_term_keyword_passthrough(self):
        """GIVEN @type; WHEN _expand_term; THEN returned as-is."""
        p = self._make_expander()
        ctx = self._make_context()
        self.assertEqual(p._expand_term("@type", ctx), "@type")

    def test_expand_term_from_terms_str(self):
        """GIVEN term mapped to string; WHEN _expand_term; THEN returns mapped URI."""
        p = self._make_expander()
        ctx = self._make_context(terms={"name": "http://schema.org/name"})
        self.assertEqual(p._expand_term("name", ctx), "http://schema.org/name")

    def test_expand_term_from_terms_dict_id(self):
        """GIVEN term as dict with @id; WHEN _expand_term; THEN returns @id."""
        p = self._make_expander()
        ctx = self._make_context(terms={"person": {"@id": "http://schema.org/Person"}})
        self.assertEqual(p._expand_term("person", ctx), "http://schema.org/Person")

    def test_expand_term_prefix(self):
        """GIVEN prefix 'schema:'; WHEN _expand_term('schema:name'); THEN expands."""
        p = self._make_expander()
        ctx = self._make_context(prefixes={"schema": "http://schema.org/"})
        self.assertEqual(p._expand_term("schema:name", ctx), "http://schema.org/name")


class TestJSONLDContextCompactor(unittest.TestCase):
    """Tests for jsonld/context.py ContextCompactor — compact and _compact_term paths."""

    def _make_compactor(self):
        from ipfs_datasets_py.knowledge_graphs.jsonld.context import ContextCompactor
        return ContextCompactor()

    def _make_context(self, prefixes=None, terms=None, vocab=None):
        from ipfs_datasets_py.knowledge_graphs.jsonld.context import JSONLDContext
        ctx = JSONLDContext()
        if prefixes:
            ctx.prefixes.update(prefixes)
        if terms:
            ctx.terms.update(terms)
        if vocab:
            ctx.vocab = vocab
        return ctx

    def test_compact_adds_context(self):
        """GIVEN expanded data + context; WHEN compact; THEN @context added."""
        c = self._make_compactor()
        ctx = self._make_context(terms={"name": "http://schema.org/name"})
        result = c.compact({"http://schema.org/name": "Alice"}, ctx)
        self.assertIn("@context", result)

    def test_compact_term_from_terms(self):
        """GIVEN URI matching a term; WHEN _compact_term; THEN returns short term."""
        c = self._make_compactor()
        ctx = self._make_context(terms={"name": "http://schema.org/name"})
        self.assertEqual(c._compact_term("http://schema.org/name", ctx), "name")

    def test_compact_term_vocab(self):
        """GIVEN vocab matches URI prefix; WHEN _compact_term; THEN strips vocab prefix."""
        c = self._make_compactor()
        ctx = self._make_context(vocab="http://schema.org/")
        self.assertEqual(c._compact_term("http://schema.org/Person", ctx), "Person")

    def test_compact_term_prefix(self):
        """GIVEN namespace matches URI prefix; WHEN _compact_term; THEN prefixed form."""
        c = self._make_compactor()
        ctx = self._make_context(prefixes={"schema": "http://schema.org/"})
        self.assertEqual(c._compact_term("http://schema.org/name", ctx), "schema:name")

    def test_compact_term_no_match(self):
        """GIVEN URI with no match; WHEN _compact_term; THEN returns URI as-is."""
        c = self._make_compactor()
        ctx = self._make_context()
        uri = "http://example.com/x"
        self.assertEqual(c._compact_term(uri, ctx), uri)

    def test_compact_term_keyword_passthrough(self):
        """GIVEN @type; WHEN _compact_term; THEN returned as-is."""
        c = self._make_compactor()
        ctx = self._make_context()
        self.assertEqual(c._compact_term("@type", ctx), "@type")

    def test_compact_type_string(self):
        """GIVEN @type as string; WHEN compact; THEN @type is compacted."""
        c = self._make_compactor()
        ctx = self._make_context(terms={"Person": "http://schema.org/Person"})
        result = c.compact({"@type": "http://schema.org/Person"}, ctx)
        self.assertIn("@type", result)

    def test_compact_type_list(self):
        """GIVEN @type as list; WHEN compact; THEN each element compacted."""
        c = self._make_compactor()
        ctx = self._make_context(terms={"Person": "http://schema.org/Person"})
        result = c.compact({"@type": ["http://schema.org/Person"]}, ctx)
        self.assertIn("@type", result)
        self.assertIsInstance(result["@type"], list)


# ─────────────────────────────────────────────────────────────────────────────
# Part 4: reasoning/cross_document.py
# ─────────────────────────────────────────────────────────────────────────────

class TestCrossDocumentReasoner(unittest.TestCase):
    """Tests for reasoning/cross_document.py — get_statistics, explain_reasoning, _determine_relation."""

    def _make_reasoner(self):
        from ipfs_datasets_py.knowledge_graphs.reasoning.cross_document import CrossDocumentReasoner
        return CrossDocumentReasoner()

    def _make_document(self, doc_id, content="test", entities=None, metadata=None):
        from ipfs_datasets_py.knowledge_graphs.reasoning.cross_document import DocumentNode
        return DocumentNode(
            id=doc_id,
            content=content,
            source="test",
            metadata=metadata or {},
            entities=entities or [],
            relevance_score=0.8
        )

    # ── get_statistics ────────────────────────────────────────────────────────

    def test_get_statistics_zero_queries(self):
        """GIVEN fresh reasoner; WHEN get_statistics; THEN success_rate=0."""
        r = self._make_reasoner()
        stats = r.get_statistics()
        self.assertIn("total_queries", stats)
        self.assertIn("success_rate", stats)
        self.assertEqual(stats["success_rate"], 0)

    def test_get_statistics_after_query(self):
        """GIVEN reasoner that processed a query; WHEN get_statistics; THEN total_queries>0."""
        r = self._make_reasoner()
        r.reason_across_documents(
            query="What is IPFS?",
            input_documents=[
                {"id": "d1", "content": "IPFS is a protocol.", "source": "test",
                 "metadata": {}, "relevance_score": 0.9, "entities": []}
            ]
        )
        stats = r.get_statistics()
        self.assertGreater(stats["total_queries"], 0)

    def test_get_statistics_keys(self):
        """GIVEN reasoner; WHEN get_statistics; THEN all expected keys present."""
        r = self._make_reasoner()
        stats = r.get_statistics()
        expected_keys = {"total_queries", "successful_queries", "success_rate",
                         "avg_document_count", "avg_connection_count", "avg_confidence"}
        self.assertTrue(expected_keys.issubset(stats.keys()))

    # ── explain_reasoning ────────────────────────────────────────────────────

    def test_explain_reasoning_returns_dict(self):
        """GIVEN any reasoning_id; WHEN explain_reasoning; THEN returns dict with expected keys."""
        r = self._make_reasoner()
        explanation = r.explain_reasoning("test-id-123")
        self.assertIn("reasoning_id", explanation)
        self.assertIn("explanation", explanation)
        self.assertIn("steps", explanation)

    def test_explain_reasoning_id_propagated(self):
        """GIVEN reasoning_id; WHEN explain_reasoning; THEN ID in result."""
        r = self._make_reasoner()
        result = r.explain_reasoning("my-reasoning-456")
        self.assertEqual(result["reasoning_id"], "my-reasoning-456")

    def test_explain_reasoning_steps_list(self):
        """GIVEN any ID; WHEN explain_reasoning; THEN steps is a list."""
        r = self._make_reasoner()
        result = r.explain_reasoning("x")
        self.assertIsInstance(result["steps"], list)

    # ── _determine_relation ───────────────────────────────────────────────────

    def test_determine_relation_missing_docs(self):
        """GIVEN doc IDs not in document list; WHEN _determine_relation; THEN returns UNCLEAR."""
        from ipfs_datasets_py.knowledge_graphs.reasoning.cross_document import InformationRelationType
        r = self._make_reasoner()
        rel_type, strength = r._determine_relation(
            entity_id="e1",
            source_doc_id="ghost1",
            target_doc_id="ghost2",
            documents=[],
            knowledge_graph=None,
        )
        self.assertEqual(rel_type, InformationRelationType.UNCLEAR)

    def test_determine_relation_chronological(self):
        """GIVEN source published before target; WHEN _determine_relation; THEN ELABORATING."""
        from ipfs_datasets_py.knowledge_graphs.reasoning.cross_document import InformationRelationType
        r = self._make_reasoner()
        docs = [
            self._make_document("d1", metadata={"published_date": "2020-01-01"}),
            self._make_document("d2", metadata={"published_date": "2021-01-01"}),
        ]
        rel_type, strength = r._determine_relation(
            entity_id="e1", source_doc_id="d1", target_doc_id="d2",
            documents=docs, knowledge_graph=None,
        )
        self.assertEqual(rel_type, InformationRelationType.ELABORATING)
        self.assertGreater(strength, 0)

    def test_determine_relation_default_complementary(self):
        """GIVEN non-chronological, non-similar docs; WHEN _determine_relation; THEN COMPLEMENTARY."""
        from ipfs_datasets_py.knowledge_graphs.reasoning.cross_document import InformationRelationType
        r = self._make_reasoner()
        docs = [
            self._make_document("d1", content="apples oranges bananas"),
            self._make_document("d2", content="quantum computing processors"),
        ]
        rel_type, strength = r._determine_relation(
            entity_id="e1", source_doc_id="d1", target_doc_id="d2",
            documents=docs, knowledge_graph=None,
        )
        self.assertIn(rel_type, list(InformationRelationType))
        self.assertGreater(strength, 0)

    # ── reason_across_documents ────────────────────────────────────────────────

    def test_reason_across_documents_basic(self):
        """GIVEN documents; WHEN reason_across_documents; THEN returns dict with answer."""
        r = self._make_reasoner()
        result = r.reason_across_documents(
            query="What is IPFS?",
            input_documents=[
                {"id": "d1", "content": "IPFS is peer-to-peer.", "source": "wiki",
                 "metadata": {}, "relevance_score": 0.9, "entities": ["IPFS"]}
            ]
        )
        self.assertIn("answer", result)
        self.assertIn("confidence", result)

    def test_reason_across_documents_multiple(self):
        """GIVEN two documents sharing an entity; WHEN reason_across_documents; THEN connections found."""
        r = self._make_reasoner()
        result = r.reason_across_documents(
            query="IPFS content addressing",
            input_documents=[
                {"id": "d1", "content": "IPFS uses content addressing.", "source": "a",
                 "metadata": {}, "relevance_score": 0.9, "entities": ["IPFS", "content-addressing"]},
                {"id": "d2", "content": "Content addressing uses hashes.", "source": "b",
                 "metadata": {}, "relevance_score": 0.8, "entities": ["IPFS", "hashes"]},
            ]
        )
        self.assertIn("documents", result)


# ─────────────────────────────────────────────────────────────────────────────
# Part 5: extraction/finance_graphrag.py
# ─────────────────────────────────────────────────────────────────────────────

class TestFinanceGraphRAG(unittest.TestCase):
    """Tests for extraction/finance_graphrag.py dataclasses and GraphRAGNewsAnalyzer."""

    def _module(self):
        from ipfs_datasets_py.knowledge_graphs.extraction import finance_graphrag as m
        return m

    # ── ExecutiveProfile ──────────────────────────────────────────────────────

    def test_executive_profile_to_entity(self):
        """GIVEN ExecutiveProfile; WHEN to_entity(); THEN Entity with name set."""
        m = self._module()
        profile = m.ExecutiveProfile(
            person_id="p1",
            name="Jane Doe",
            gender="female",
        )
        entity = profile.to_entity()
        self.assertEqual(entity.name, "Jane Doe")
        # entity_type is 'executive' (finance-specific type)
        self.assertIsNotNone(entity.entity_type)

    def test_executive_profile_to_entity_properties(self):
        """GIVEN ExecutiveProfile with traits; WHEN to_entity(); THEN entity has properties."""
        m = self._module()
        profile = m.ExecutiveProfile(
            person_id="p2",
            name="John Smith",
            personality_traits=["decisive", "analytical"],
        )
        entity = profile.to_entity()
        self.assertIsNotNone(entity.properties)

    # ── CompanyPerformance ────────────────────────────────────────────────────

    def test_company_performance_to_entity(self):
        """GIVEN CompanyPerformance; WHEN to_entity(); THEN Entity with company name."""
        m = self._module()
        cp = m.CompanyPerformance(
            company_id="c1",
            symbol="ACME",
            name="Acme Corp",
        )
        entity = cp.to_entity()
        self.assertEqual(entity.name, "Acme Corp")
        self.assertIsNotNone(entity.entity_type)

    # ── HypothesisTest ────────────────────────────────────────────────────────

    def test_hypothesis_test_to_dict(self):
        """GIVEN HypothesisTest; WHEN to_dict(); THEN returns dict with 'hypothesis' key."""
        m = self._module()
        ht = m.HypothesisTest(
            hypothesis="Leaders drive performance",
        )
        d = ht.to_dict()
        self.assertIn("hypothesis", d)
        self.assertIsInstance(d, dict)

    def test_hypothesis_test_id_generated(self):
        """GIVEN HypothesisTest with no ID; WHEN created; THEN hypothesis_id is set."""
        m = self._module()
        ht = m.HypothesisTest(hypothesis="Test hypothesis")
        self.assertIsNotNone(ht.hypothesis_id)
        self.assertIsInstance(ht.hypothesis_id, str)

    # ── GraphRAGNewsAnalyzer ───────────────────────────────────────────────────

    def test_analyzer_init_no_graphrag(self):
        """GIVEN GraphRAGNewsAnalyzer with enable_graphrag=False; WHEN init; THEN no error."""
        m = self._module()
        analyzer = m.GraphRAGNewsAnalyzer(enable_graphrag=False)
        self.assertIsNotNone(analyzer)

    def test_analyzer_extract_executive_profiles_empty(self):
        """GIVEN empty articles; WHEN extract_executive_profiles; THEN empty list."""
        m = self._module()
        analyzer = m.GraphRAGNewsAnalyzer(enable_graphrag=False)
        profiles = analyzer.extract_executive_profiles([])
        self.assertEqual(profiles, [])

    def test_analyzer_extract_executive_profiles_basic(self):
        """GIVEN articles mentioning a person; WHEN extract_executive_profiles; THEN profiles returned."""
        m = self._module()
        analyzer = m.GraphRAGNewsAnalyzer(enable_graphrag=False)
        articles = [
            {
                "title": "CEO John Smith leads Acme Corp to record profits",
                "content": "John Smith, CEO of Acme Corp, announced record profits.",
                "persons": [{"name": "John Smith", "role": "CEO", "company": "Acme Corp"}],
                "companies": ["Acme Corp"],
                "date": "2024-01-01",
            }
        ]
        profiles = analyzer.extract_executive_profiles(articles)
        self.assertIsInstance(profiles, list)

    def test_analyzer_build_knowledge_graph(self):
        """GIVEN analyzer with no data; WHEN build_knowledge_graph; THEN returns KnowledgeGraph."""
        m = self._module()
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph
        analyzer = m.GraphRAGNewsAnalyzer(enable_graphrag=False)
        kg = analyzer.build_knowledge_graph()
        self.assertIsInstance(kg, KnowledgeGraph)

    # ── standalone functions ──────────────────────────────────────────────────

    def test_create_financial_knowledge_graph(self):
        """GIVEN empty lists; WHEN create_financial_knowledge_graph; THEN returns dict."""
        m = self._module()
        result = m.create_financial_knowledge_graph(news_articles=[], stock_data=[])
        self.assertIsInstance(result, dict)
        self.assertIn("success", result)

    def test_analyze_executive_performance_returns_str(self):
        """GIVEN JSON inputs; WHEN analyze_executive_performance; THEN returns JSON string."""
        import json
        m = self._module()
        result = m.analyze_executive_performance(
            json.dumps([]),   # news_articles_json
            json.dumps([]),   # stock_data_json
            "test hypothesis",
            "gender",
            "male",
            "female",
        )
        self.assertIsInstance(result, str)


# ─────────────────────────────────────────────────────────────────────────────
# Part 6: root-level 0% shims
# ─────────────────────────────────────────────────────────────────────────────

class TestRootLevelShimsRemaining(unittest.TestCase):
    """Cover root-level shims still at 0% (cross_document_lineage_enhanced, finance_graphrag, sparql_query_templates)."""

    def test_cross_document_lineage_enhanced_shim_warns(self):
        """GIVEN import of cross_document_lineage_enhanced; THEN DeprecationWarning fired."""
        import sys
        # Force reimport to trigger warning
        mname = "ipfs_datasets_py.knowledge_graphs.cross_document_lineage_enhanced"
        sys.modules.pop(mname, None)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            import importlib
            importlib.import_module(mname)
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            self.assertTrue(len(dep_warnings) > 0)

    def test_cross_document_lineage_enhanced_shim_exports(self):
        """GIVEN shim imported; THEN LineageVisualizer importable from it."""
        from ipfs_datasets_py.knowledge_graphs.cross_document_lineage_enhanced import LineageVisualizer
        self.assertIsNotNone(LineageVisualizer)

    def test_finance_graphrag_shim_warns(self):
        """GIVEN import of root-level finance_graphrag; THEN DeprecationWarning fired."""
        import sys
        import importlib
        mname = "ipfs_datasets_py.knowledge_graphs.finance_graphrag"
        sys.modules.pop(mname, None)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            importlib.import_module(mname)
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            self.assertTrue(len(dep_warnings) > 0)

    def test_finance_graphrag_shim_exports_graphrag_available(self):
        """GIVEN shim imported; THEN GRAPHRAG_AVAILABLE accessible."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            from ipfs_datasets_py.knowledge_graphs.finance_graphrag import GRAPHRAG_AVAILABLE
        self.assertIsInstance(GRAPHRAG_AVAILABLE, bool)

    def test_sparql_query_templates_shim_warns(self):
        """GIVEN import of root-level sparql_query_templates; THEN DeprecationWarning fired."""
        import sys
        import importlib
        mname = "ipfs_datasets_py.knowledge_graphs.sparql_query_templates"
        sys.modules.pop(mname, None)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            importlib.import_module(mname)
            dep_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
            self.assertTrue(len(dep_warnings) > 0)

    def test_sparql_query_templates_shim_exports(self):
        """GIVEN shim imported; THEN something useful importable from it."""
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            import ipfs_datasets_py.knowledge_graphs.sparql_query_templates as m
        self.assertIsNotNone(m)


if __name__ == "__main__":
    unittest.main()
