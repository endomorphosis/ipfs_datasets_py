"""
Session 36 – knowledge_graphs coverage push.

Targets (22 new GIVEN-WHEN-THEN tests):
  • core/query_executor.py      99%→100% – is_cypher structural patterns (non-keyword), QueryError re-raise
  • core/_legacy_graph_engine.py 99%→100% – BFS visited guard (correct cycle setup)
  • lineage/enhanced.py         99%→100% – calculate_path_confidence no-edges, find_similar_nodes missing-node
  • query/hybrid_search.py      99%→100% – expand_graph node already visited in later hop
  • reasoning/cross_document.py 99%→100% – _compute_document_similarity zero norm
  • indexing/manager.py         99%→100% – insert_entity composite missing property → break
  • jsonld/context.py           98%→100% – _expand_object/@type non-str/non-list, same for compact
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# 1. core/query_executor.py – lines 118, 221
#    (is_cypher structural patterns; QueryError raise_on_error=True)
# ===========================================================================

class TestQueryExecutorRemainingPaths:
    """GIVEN a QueryExecutor, WHEN non-keyword structural Cypher patterns are
    used and QueryError is raised with raise_on_error=True, THEN the correct
    branches fire."""

    def _executor(self):
        from ipfs_datasets_py.knowledge_graphs.core.query_executor import QueryExecutor
        return QueryExecutor(graph_engine=MagicMock())

    # -----------------------------------------------------------------------
    # Line 118: structural patterns without leading Cypher keyword
    # -----------------------------------------------------------------------
    def test_is_cypher_query_empty_node_without_keyword(self):
        """GIVEN a query with '()' but no leading keyword WHEN _is_cypher_query
        is called THEN True is returned (line 118)."""
        qe = self._executor()
        # Query doesn't start with a Cypher keyword, but has the () pattern
        assert qe._is_cypher_query("n1 () n2") is True

    def test_is_cypher_query_arrow_without_keyword(self):
        """GIVEN a query with '-->' but no leading keyword WHEN _is_cypher_query
        is called THEN True is returned (line 118)."""
        qe = self._executor()
        assert qe._is_cypher_query("a-->b") is True

    def test_is_cypher_query_left_arrow_without_keyword(self):
        """GIVEN a query with '<--' but no leading keyword WHEN _is_cypher_query
        is called THEN True is returned (line 118)."""
        qe = self._executor()
        assert qe._is_cypher_query("a<--b") is True

    # -----------------------------------------------------------------------
    # Line 221: QueryError with raise_on_error=True → re-raised
    # -----------------------------------------------------------------------
    def test_execute_cypher_query_error_raise_on_error(self):
        """GIVEN _execute_ir_operations raises QueryError (not a subclass) and
        raise_on_error=True WHEN _execute_cypher is called THEN the QueryError
        is re-raised (line 221)."""
        from ipfs_datasets_py.knowledge_graphs.exceptions import QueryError
        import ipfs_datasets_py.knowledge_graphs.cypher as cymod

        qe = self._executor()
        ast = MagicMock(); ast.clauses = [MagicMock()]
        mock_parser = MagicMock(); mock_parser.parse.return_value = ast
        mock_compiler = MagicMock(); mock_compiler.compile.return_value = []

        with patch.object(qe, "_execute_ir_operations", side_effect=QueryError("qerror")):
            with patch.object(cymod, "CypherParser", return_value=mock_parser):
                with patch.object(cymod, "CypherCompiler", return_value=mock_compiler):
                    with pytest.raises(QueryError, match="qerror"):
                        qe._execute_cypher("MATCH (n) RETURN n", {}, raise_on_error=True)


# ===========================================================================
# 2. core/_legacy_graph_engine.py – line 588
#    (BFS visited guard: node that cycles back to an already-visited node)
# ===========================================================================

class TestLegacyGraphEngineVisitedGuard:
    """GIVEN a graph with a back-edge that points to an already-visited node,
    WHEN find_paths is called, THEN the BFS visited guard at line 588 fires."""

    def test_find_paths_bfs_visited_guard_with_back_edge(self):
        """GIVEN n1→n2, n1→n3, n3→n1 (n3 points back to n1 which is in visited)
        WHEN find_paths('n1', 'n2') is called THEN the back-edge n3→n1 triggers
        the visited guard (line 588) and the direct path n1→n2 is found."""
        from ipfs_datasets_py.knowledge_graphs.core._legacy_graph_engine import (
            _LegacyGraphEngine,
        )
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import (
            Node,
            Relationship as CompatRel,
        )

        engine = _LegacyGraphEngine()
        n1 = Node("n1", ["P"], {})
        n2 = Node("n2", ["P"], {})
        n3 = Node("n3", ["P"], {})
        engine._node_cache = {"n1": n1, "n2": n2, "n3": n3}

        r12 = CompatRel("r12", "KNOWS", n1, n2, {})  # n1→n2 (direct to end)
        r13 = CompatRel("r13", "KNOWS", n1, n3, {})  # n1→n3 (alternative)
        r31 = CompatRel("r31", "KNOWS", n3, n1, {})  # n3→n1 (back-edge → line 588)
        engine._relationship_cache = {"r12": r12, "r13": r13, "r31": r31}

        # BFS traversal:
        # 1. queue=[(n1,[],{n1})]; pop n1; follow r12→n2=end→append; follow r13→n3→queue
        # 2. queue=[(n3,[r13],{n1,n3})]; pop n3; follow r31→n1; n1 in visited → line 588
        paths = engine.find_paths("n1", "n2", max_depth=5)
        assert paths is not None
        assert len(paths) >= 1  # at least the direct n1→n2 path


# ===========================================================================
# 3. lineage/enhanced.py – lines 259, 424
# ===========================================================================

class TestLineageEnhancedCorrectedPaths:
    """GIVEN corrected test scenarios that actually trigger lines 259 and 424."""

    # -----------------------------------------------------------------------
    # Line 259: calculate_path_confidence with 2+ nodes but no edge data
    # -----------------------------------------------------------------------
    def test_calculate_path_confidence_two_nodes_no_edge_data(self):
        """GIVEN a path of 2 nodes and a graph with no 'edges' attribute WHEN
        calculate_path_confidence is called THEN confidences is empty and
        1.0 is returned (line 259)."""
        from ipfs_datasets_py.knowledge_graphs.lineage.enhanced import ConfidenceScorer

        cs = ConfidenceScorer()
        # Mock graph whose _graph does NOT have 'edges' → hasattr returns False
        graph = MagicMock(spec=[])  # spec=[] means no attributes
        # make _graph accessible but without 'edges'
        inner_graph = MagicMock(spec=[])
        object.__setattr__(graph, "_graph", inner_graph)

        # With an empty graph (no edges), confidences stays empty → return 1.0
        result = cs.calculate_path_confidence(graph, ["n1", "n2"])
        assert result == 1.0

    # -----------------------------------------------------------------------
    # Line 424: find_similar_nodes when node_id not found in graph
    # -----------------------------------------------------------------------
    def test_find_similar_nodes_returns_empty_for_nonexistent_node(self):
        """GIVEN a node_id not present in the graph WHEN find_similar_nodes
        is called THEN an empty list is returned (line 424)."""
        from ipfs_datasets_py.knowledge_graphs.lineage.enhanced import (
            EnhancedLineageTracker,
        )

        tracker = EnhancedLineageTracker()
        tracker.track_node("n1", "dataset", "Dataset 1")
        similar = tracker.find_similar_nodes("does_not_exist", threshold=0.0)
        assert similar == []


# ===========================================================================
# 4. query/hybrid_search.py – line 205
#    (expand_graph: node appears as seed AND as neighbor → visited in later hop)
# ===========================================================================

class TestHybridSearchExpandGraphVisited:
    """GIVEN n1 and n2 both as seed_nodes where n1→n2 exists,
    WHEN expand_graph is called with max_hops>0, THEN n2 is processed in
    hop 0 (from seed) and skipped in hop 1 (already visited, line 205)."""

    def test_expand_graph_seed_node_already_visited_in_next_hop(self):
        """GIVEN seed_nodes=[n1, n2] with n1→n2 neighbor relationship and
        max_hops=1 WHEN expand_graph is called THEN n2 is in visited from hop 0,
        and in hop 1 current_level={n2} but n2 is already visited → line 205."""
        from ipfs_datasets_py.knowledge_graphs.query.hybrid_search import (
            HybridSearchEngine,
        )

        backend = MagicMock()
        # n1's neighbors include n2; n2 has no neighbors
        def mock_get_neighbors(node_id, rel_types=None):
            return ["n2"] if node_id == "n1" else []

        backend.get_neighbors = mock_get_neighbors
        # Remove get_relationships to force _get_neighbors to use get_neighbors path
        del backend.get_relationships
        eng = HybridSearchEngine(backend=backend, vector_store=MagicMock())

        # hop 0: current = {n1, n2}
        #   process n1 → visited={n1:0}; neighbors=[n2]; n2 not in visited → next={n2}
        #   process n2 → visited={n1:0, n2:0}; no neighbors; next remains {n2}
        # hop 1: current = {n2}
        #   n2 IS in visited → line 205 continue
        visited = eng.expand_graph(seed_nodes=["n1", "n2"], max_hops=1)
        assert "n1" in visited
        assert "n2" in visited
        assert visited["n1"] == 0
        assert visited["n2"] == 0


# ===========================================================================
# 5. reasoning/cross_document.py – line 199
#    (_compute_document_similarity: zero norm → return 0.0)
# ===========================================================================

class TestCrossDocumentSimilarityZeroNorm:
    """GIVEN one document with empty content (zero-norm), WHEN
    _compute_document_similarity is called, THEN 0.0 is returned (line 199)."""

    def test_compute_document_similarity_empty_content_returns_zero(self):
        """GIVEN one document with empty content and one with actual content
        WHEN _compute_document_similarity is called THEN 0.0 is returned
        (line 199)."""
        from ipfs_datasets_py.knowledge_graphs.reasoning.cross_document import (
            CrossDocumentReasoner,
            DocumentNode,
        )

        reasoner = CrossDocumentReasoner()
        d1 = DocumentNode(id="d1", content="", source="src1")  # empty → zero norm
        d2 = DocumentNode(id="d2", content="relevant query text", source="src2")
        d1.relevance_score = 0.9
        d2.relevance_score = 0.8
        sim = reasoner._compute_document_similarity(d1, d2)
        assert sim == 0.0

    def test_compute_document_similarity_both_empty_returns_zero(self):
        """GIVEN both documents with empty content WHEN similarity is computed
        THEN 0.0 is returned (line 199)."""
        from ipfs_datasets_py.knowledge_graphs.reasoning.cross_document import (
            CrossDocumentReasoner,
            DocumentNode,
        )

        reasoner = CrossDocumentReasoner()
        d1 = DocumentNode(id="d1", content="", source="src1")
        d2 = DocumentNode(id="d2", content="", source="src2")
        d1.relevance_score = 1.0
        d2.relevance_score = 1.0
        sim = reasoner._compute_document_similarity(d1, d2)
        assert sim == 0.0


# ===========================================================================
# 6. indexing/manager.py – line 253
#    (insert_entity: CompositeIndex missing required property → break)
# ===========================================================================

class TestIndexManagerCompositeBreak:
    """GIVEN a CompositeIndex requiring two properties, WHEN an entity is
    inserted that is missing one property, THEN the break at line 253 fires."""

    def test_insert_entity_composite_missing_property_break(self):
        """GIVEN a CompositeIndex on ['name', 'age'] WHEN an entity with only
        'name' is inserted THEN line 253 break fires and no composite entry
        is created."""
        from ipfs_datasets_py.knowledge_graphs.indexing.manager import IndexManager

        manager = IndexManager()
        manager.create_composite_index(property_names=["name", "age"], label="Person")

        # Entity has 'name' but NOT 'age' → composite index break fires
        entity_no_age = {
            "id": "e_no_age",
            "type": "Person",
            "properties": {"name": "Alice"},  # missing 'age'
        }
        manager.insert_entity(entity_no_age)  # should not raise

        # Verify no composite entry was created for the missing-age entity
        comp_index_name = [
            n for n in manager.indexes if "composite" in n.lower()
        ][0]
        comp_idx = manager.indexes[comp_index_name]
        # search for Alice with age=30 should return nothing
        result = comp_idx.search_composite(["Alice", 30])
        assert result == []

    def test_insert_entity_composite_all_properties_present(self):
        """GIVEN a CompositeIndex on ['name', 'age'] WHEN an entity with both
        'name' and 'age' is inserted THEN the composite entry IS created."""
        from ipfs_datasets_py.knowledge_graphs.indexing.manager import IndexManager

        manager = IndexManager()
        manager.create_composite_index(property_names=["name", "age"], label="Person")

        entity_full = {
            "id": "e_full",
            "type": "Person",
            "properties": {"name": "Bob", "age": 25},
        }
        manager.insert_entity(entity_full)

        comp_index_name = [
            n for n in manager.indexes if "composite" in n.lower()
        ][0]
        comp_idx = manager.indexes[comp_index_name]
        result = comp_idx.search_composite(["Bob", 25])
        assert "e_full" in result


# ===========================================================================
# 7. jsonld/context.py – lines 125, 240
#    (_expand_object @type with non-str/non-list → passthrough;
#     _compact_object same)
# ===========================================================================

class TestJSONLDContextMissedPaths:
    """GIVEN JSON-LD objects with a non-string, non-list @type value,
    WHEN ContextExpander/_compact_object processes them, THEN the passthrough
    branches at lines 125 and 240 fire."""

    # -----------------------------------------------------------------------
    # Line 125: ContextExpander._expand_object @type is non-str/non-list
    # -----------------------------------------------------------------------
    def test_expand_object_type_integer_passthrough(self):
        """GIVEN an object with '@type' set to an integer (not str, not list)
        WHEN ContextExpander.expand is called THEN the integer is passed through
        unchanged (line 125)."""
        from ipfs_datasets_py.knowledge_graphs.jsonld.context import (
            ContextExpander,
            JSONLDContext,
        )

        ctx = JSONLDContext()
        exp = ContextExpander()
        obj = {"@id": "http://example.org/n1", "@type": 42}
        result = exp.expand(obj, ctx)
        # @type value 42 is not str or list → line 125 passthrough
        assert result.get("@type") == 42

    def test_expand_object_type_none_passthrough(self):
        """GIVEN '@type' set to None WHEN ContextExpander.expand is called
        THEN None is passed through (line 125)."""
        from ipfs_datasets_py.knowledge_graphs.jsonld.context import (
            ContextExpander,
            JSONLDContext,
        )

        ctx = JSONLDContext()
        exp = ContextExpander()
        obj = {"@id": "http://example.org/n2", "@type": None}
        result = exp.expand(obj, ctx)
        assert result.get("@type") is None

    # -----------------------------------------------------------------------
    # Line 240: ContextCompactor._compact_object @type is non-str/non-list
    # -----------------------------------------------------------------------
    def test_compact_object_type_integer_passthrough(self):
        """GIVEN a compactable object with '@type' set to an integer WHEN
        ContextCompactor.compact is called THEN the integer is passed through
        unchanged (line 240)."""
        from ipfs_datasets_py.knowledge_graphs.jsonld.context import (
            ContextCompactor,
            JSONLDContext,
        )

        ctx = JSONLDContext()
        comp = ContextCompactor()
        # Use the @type key directly (no prefix expansion needed)
        obj = {"@type": 99, "@id": "http://example.org/n3"}
        result = comp.compact(obj, ctx)
        assert result.get("@type") == 99

    def test_compact_object_type_none_passthrough(self):
        """GIVEN '@type' set to None WHEN ContextCompactor.compact is called
        THEN None is passed through (line 240)."""
        from ipfs_datasets_py.knowledge_graphs.jsonld.context import (
            ContextCompactor,
            JSONLDContext,
        )

        ctx = JSONLDContext()
        comp = ContextCompactor()
        obj = {"@type": None, "@id": "http://example.org/n4"}
        result = comp.compact(obj, ctx)
        assert result.get("@type") is None
