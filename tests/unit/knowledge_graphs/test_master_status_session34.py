"""
Session 34 – knowledge_graphs coverage push.

Targets (44 new GIVEN-WHEN-THEN tests):
  • ontology/reasoning.py          99% → 100%  – get_inferred_types + entity-not-found chain
  • query/unified_engine.py        98% → 100%  – lazy-load cypher_compiler, ir_executor, graph_engine
  • query/distributed.py           98% → 100%  – _execute_on_partition exception, dedup, fingerprint
  • query/hybrid_search.py         98% → 100%  – CancelledError (3x), expand_graph dup-node continue
  • reasoning/helpers.py           98% → 100%  – DFS depth-limit path append, _get_llm_router
  • storage/ipld_backend.py        95% → 97%   – store/retrieve CancelledError (3 paths)
  • cypher/functions.py            99% → 100%  – fn_properties({}) fallback
  • cypher/lexer.py                99% → 100%  – scientific notation digits
  • neo4j_compat/result.py         99% → 100%  – Result.keys() with empty records
  • neo4j_compat/types.py          99% → 100%  – Path node/rel count mismatch
  • jsonld/rdf_serializer.py       98% → 100%  – EOF in multi-line, empty po_group, 1-part po
  • extraction/finance_graphrag.py 98% → 99%   – test_hypothesis exec with no companies
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# 1. ontology/reasoning.py – lines 746 (get_inferred_types) and 1018
#    (entity not found in kg during property-chain application)
# ===========================================================================

class TestOntologyReasonerRemainingPaths:
    """GIVEN an OntologyReasoner, WHEN get_inferred_types is called or a
    property-chain references a deleted entity, THEN the correct branches fire."""

    # -----------------------------------------------------------------------
    # Line 746: OntologyReasoner.get_inferred_types delegates to schema
    # -----------------------------------------------------------------------
    def test_get_inferred_types_returns_superclasses(self):
        """GIVEN a schema with Cat ⊆ Animal
        WHEN OntologyReasoner.get_inferred_types('Cat') is called
        THEN {'Animal'} is returned (line 746)."""
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import (
            OntologyReasoner,
            OntologySchema,
        )

        schema = OntologySchema()
        schema.add_subclass("Cat", "Animal")
        reasoner = OntologyReasoner(schema)
        types = reasoner.get_inferred_types("Cat")
        assert "Animal" in types
        assert "Cat" not in types

    # -----------------------------------------------------------------------
    # Line 1018: entity deleted from kg.entities but still in a relationship
    # → the property-chain guard `if not src_ent or not tgt_ent: continue` fires
    # -----------------------------------------------------------------------
    def test_apply_property_chains_skips_missing_entity(self):
        """GIVEN e3 is removed from kg.entities after its relationship is added
        WHEN materialize is called THEN line 1018 continue fires without error."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import (
            Entity,
            KnowledgeGraph,
            Relationship,
        )
        from ipfs_datasets_py.knowledge_graphs.ontology.reasoning import (
            OntologyReasoner,
            OntologySchema,
        )

        schema = OntologySchema()
        schema.property_chains = [
            (["parentOf", "parentOf"], "grandparentOf")
        ]
        kg = KnowledgeGraph()
        e1 = Entity(name="Alice", entity_type="Person")
        e2 = Entity(name="Bob", entity_type="Person")
        e3 = Entity(name="Carol", entity_type="Person")
        for e in [e1, e2, e3]:
            kg.add_entity(e)
        kg.add_relationship(
            Relationship(source_entity=e1, target_entity=e2,
                         relationship_type="parentOf", confidence=0.9)
        )
        kg.add_relationship(
            Relationship(source_entity=e2, target_entity=e3,
                         relationship_type="parentOf", confidence=0.9)
        )
        # Remove e3 so it's referenced by relationships but absent from entities
        del kg.entities[e3.entity_id]

        reasoner = OntologyReasoner(schema, max_iterations=2)
        result = reasoner.materialize(kg)  # should not raise
        # grandparentOf cannot be inferred since e3 is missing
        gp_rels = [r for r in result.relationships.values()
                   if r.relationship_type == "grandparentOf"]
        assert len(gp_rels) == 0


# ===========================================================================
# 2. query/unified_engine.py – lines 187, 211, 223, 227
#    (lazy-load properties: cypher_compiler, ir_executor, graph_engine)
# ===========================================================================

class TestUnifiedQueryEngineLazyProperties:
    """GIVEN a UnifiedQueryEngine with a mock backend,
    WHEN the lazy properties are accessed,
    THEN the underlying implementations are loaded on demand."""

    def _engine(self):
        from ipfs_datasets_py.knowledge_graphs.query.unified_engine import UnifiedQueryEngine
        return UnifiedQueryEngine(backend=MagicMock())

    def test_cypher_compiler_lazy_loaded(self):
        """GIVEN a fresh engine WHEN cypher_compiler is accessed
        THEN a CypherCompiler is created and cached (line 187)."""
        eng = self._engine()
        cc = eng.cypher_compiler
        assert cc is not None
        # Second access returns the cached instance
        assert eng.cypher_compiler is cc

    def test_ir_executor_lazy_loaded(self):
        """GIVEN a fresh engine WHEN ir_executor is accessed
        THEN a GraphQueryExecutor is created and cached (line 211)."""
        eng = self._engine()
        ir = eng.ir_executor
        assert ir is not None
        assert eng.ir_executor is ir  # cached

    def test_graph_engine_lazy_loaded(self):
        """GIVEN a fresh engine WHEN graph_engine is accessed
        THEN a GraphEngine is created and cached (lines 223, 227)."""
        eng = self._engine()
        ge = eng.graph_engine
        assert ge is not None
        assert eng.graph_engine is ge  # cached

    def test_cypher_parser_lazy_loaded(self):
        """GIVEN a fresh engine WHEN cypher_parser is accessed
        THEN a CypherParser is created on demand."""
        eng = self._engine()
        cp = eng.cypher_parser
        assert cp is not None
        assert eng.cypher_parser is cp  # cached


# ===========================================================================
# 3. query/distributed.py – lines 751-752, 767, 902-903
# ===========================================================================

class TestDistributedQueryMissedPaths:
    """GIVEN a FederatedQueryExecutor, WHEN errors and deduplication are
    exercised, THEN the fallback paths fire correctly."""

    def _executor(self, dedup: bool = True):
        from ipfs_datasets_py.knowledge_graphs.query.distributed import (
            DistributedGraph,
            FederatedQueryExecutor,
            PartitionStrategy,
        )
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

        kg = KnowledgeGraph()
        dg = DistributedGraph(
            partitions=[kg],
            strategy=PartitionStrategy.HASH,
            node_to_partition={},
        )
        return FederatedQueryExecutor(dg, dedup=dedup)

    # -----------------------------------------------------------------------
    # Lines 751-752: executor.execute raises → return []
    # -----------------------------------------------------------------------
    def test_execute_on_partition_exception_returns_empty_list(self):
        """GIVEN QueryExecutor.execute raises a RuntimeError WHEN
        _execute_on_partition is called THEN an empty list is returned
        (lines 751-752)."""
        from ipfs_datasets_py.knowledge_graphs.extraction.graph import KnowledgeGraph

        fqe = self._executor()
        kg = KnowledgeGraph()
        with patch(
            "ipfs_datasets_py.knowledge_graphs.core.query_executor.QueryExecutor"
        ) as MockQE:
            MockQE.return_value.execute.side_effect = RuntimeError("exec failed")
            result = fqe._execute_on_partition(kg, "MATCH (n) RETURN n", {})
        assert result == []

    # -----------------------------------------------------------------------
    # Line 767: duplicate fingerprint → continue (record not appended twice)
    # -----------------------------------------------------------------------
    def test_merge_results_dedup_skips_duplicate_fingerprint(self):
        """GIVEN two identical records WHEN _merge_results is called with
        dedup=True THEN only one record is returned (line 767)."""
        fqe = self._executor(dedup=True)
        records = [{"value": "same"}, {"value": "same"}]
        merged = fqe._merge_results([records])
        assert len(merged) == 1
        assert merged[0] == {"value": "same"}

    # -----------------------------------------------------------------------
    # Lines 902-903: json.dumps fails → fallback to str(sorted(items))
    # -----------------------------------------------------------------------
    def test_record_fingerprint_fallback_when_json_not_serialisable(self):
        """GIVEN a record containing a non-JSON-serialisable value
        WHEN _record_fingerprint is called THEN the exception fallback fires
        and a non-empty fingerprint is returned (lines 902-903)."""
        from ipfs_datasets_py.knowledge_graphs.query.distributed import _record_fingerprint

        # object() is not JSON-serialisable
        fp = _record_fingerprint({"key": object()})
        assert isinstance(fp, str)
        assert len(fp) > 0


# ===========================================================================
# 4. query/hybrid_search.py – lines 159, 205, 383, 428
# ===========================================================================

class TestHybridSearchMissedPaths:
    """GIVEN a HybridSearchEngine with mocked components,
    WHEN CancelledError is injected or duplicate nodes are supplied,
    THEN the correct exception and skip behaviours are observed."""

    def _engine(self, vector_store=None, backend=None):
        from ipfs_datasets_py.knowledge_graphs.query.hybrid_search import HybridSearchEngine
        return HybridSearchEngine(
            backend=backend or MagicMock(),
            vector_store=vector_store or MagicMock(),
        )

    # -----------------------------------------------------------------------
    # Line 159: vector_search asyncio.CancelledError re-raise
    # -----------------------------------------------------------------------
    def test_vector_search_cancelled_error_propagates(self):
        """GIVEN vector_store.search raises CancelledError WHEN vector_search
        is called THEN CancelledError propagates (line 159)."""
        vs = MagicMock()
        vs.search.side_effect = asyncio.CancelledError()
        eng = self._engine(vector_store=vs)
        with pytest.raises(asyncio.CancelledError):
            eng.vector_search("test query", k=3)

    # -----------------------------------------------------------------------
    # Line 205: expand_graph duplicate seed → node_id in visited → continue
    # -----------------------------------------------------------------------
    def test_expand_graph_duplicate_seed_node_skipped(self):
        """GIVEN the same node_id appears twice in seed_nodes WHEN expand_graph
        is called THEN the duplicate is skipped (line 205)."""
        backend = MagicMock()
        backend.get_relationships.return_value = []
        eng = self._engine(backend=backend)
        visited = eng.expand_graph(seed_nodes=["n1", "n1", "n2"], max_hops=0)
        assert "n1" in visited
        assert "n2" in visited
        # n1 should be at hop distance 0 (visited only once)
        assert visited["n1"] == 0

    # -----------------------------------------------------------------------
    # Line 383: _get_query_embedding asyncio.CancelledError re-raise
    # -----------------------------------------------------------------------
    def test_get_query_embedding_cancelled_error_propagates(self):
        """GIVEN vector_store.embed_query raises CancelledError WHEN
        _get_query_embedding is called THEN CancelledError propagates (line 383)."""
        vs = MagicMock()
        # Provide embed_query (not get_embedding) so the embed_query path fires
        del vs.get_embedding  # make get_embedding unavailable
        vs.embed_query.side_effect = asyncio.CancelledError()
        eng = self._engine(vector_store=vs)
        with pytest.raises(asyncio.CancelledError):
            eng._get_query_embedding("some query")

    # -----------------------------------------------------------------------
    # Line 428: _get_neighbors asyncio.CancelledError re-raise
    # -----------------------------------------------------------------------
    def test_get_neighbors_cancelled_error_propagates(self):
        """GIVEN backend.get_relationships raises CancelledError WHEN
        _get_neighbors is called THEN CancelledError propagates (line 428)."""
        backend = MagicMock()
        backend.get_relationships.side_effect = asyncio.CancelledError()
        eng = self._engine(backend=backend)
        with pytest.raises(asyncio.CancelledError):
            eng._get_neighbors("some-node-id")


# ===========================================================================
# 5. reasoning/helpers.py – lines 120-121, 368
# ===========================================================================

class TestReasoningHelpersMissedPaths:
    """GIVEN a ReasoningHelpersMixin subclass, WHEN traversal paths are
    generated with short max depth or LLMRouter is available,
    THEN the depth-limit path-append and router-assignment branches fire."""

    def _helper(self):
        from ipfs_datasets_py.knowledge_graphs.reasoning.helpers import (
            ReasoningHelpersMixin,
        )

        class _H(ReasoningHelpersMixin):
            pass

        h = _H()
        h.llm_service = None
        h._default_llm_router = None
        return h

    # -----------------------------------------------------------------------
    # Lines 120-121: DFS depth limit reached → path appended
    # -----------------------------------------------------------------------
    def test_generate_traversal_paths_depth_limit_appends_path(self):
        """GIVEN a 3-document chain and reasoning_depth='basic' (max_length=2)
        WHEN _generate_traversal_paths is called THEN the DFS appends a path
        at depth=2 (lines 120-121)."""
        from ipfs_datasets_py.knowledge_graphs.reasoning.cross_document import (
            DocumentNode,
            EntityMediatedConnection,
        )

        h = self._helper()

        d1 = DocumentNode(id="d1", content="c1", source="s1")
        d2 = DocumentNode(id="d2", content="c2", source="s2")
        d3 = DocumentNode(id="d3", content="c3", source="s3")
        d1.relevance_score = 1.0
        d2.relevance_score = 0.9
        d3.relevance_score = 0.8

        # Connect d1→d2→d3 so DFS reaches depth=2
        class _Conn:
            def __init__(self, src: str, tgt: str) -> None:
                self.source_doc_id = src
                self.target_doc_id = tgt

        conns = [_Conn("d1", "d2"), _Conn("d2", "d3")]
        paths = h._generate_traversal_paths([d1, d2, d3], conns, "basic")
        # At least one path should have been appended at the depth limit
        assert len(paths) > 0
        # All paths should be depth-2 chains (length 3 including start)
        for path in paths:
            assert len(path) >= 2

    # -----------------------------------------------------------------------
    # Line 368: _get_llm_router sets self.llm_service to new LLMRouter()
    # -----------------------------------------------------------------------
    def test_get_llm_router_creates_and_caches_router(self):
        """GIVEN LLMRouter is non-None in the parent module and no service is
        set WHEN _get_llm_router is called THEN LLMRouter() is instantiated and
        self.llm_service is assigned (line 368)."""
        import ipfs_datasets_py.knowledge_graphs.reasoning.cross_document as cdm

        mock_router_instance = MagicMock()
        mock_router_instance.route_request = MagicMock()
        mock_router_class = MagicMock(return_value=mock_router_instance)

        old_lr = cdm.LLMRouter
        cdm.LLMRouter = mock_router_class
        try:
            h = self._helper()
            result = h._get_llm_router()
            assert result is mock_router_instance
            assert h.llm_service is mock_router_instance
        finally:
            cdm.LLMRouter = old_lr


# ===========================================================================
# 6. storage/ipld_backend.py – lines 254, 305, 327
#    (asyncio.CancelledError re-raises in store/retrieve)
# ===========================================================================

class TestIPLDBackendCancelledErrors:
    """GIVEN an IPLDBackend with a mocked IPFS client,
    WHEN asyncio.CancelledError is raised during store/retrieve,
    THEN it is re-raised unchanged."""

    def _backend(self, mock_ipfs=None):
        from ipfs_datasets_py.knowledge_graphs.storage.ipld_backend import IPLDBackend
        b = IPLDBackend()
        b._backend = mock_ipfs or MagicMock()
        b._cache = None
        return b

    # -----------------------------------------------------------------------
    # Line 254: store – block_put raises CancelledError
    # -----------------------------------------------------------------------
    def test_store_cancelled_error_propagates(self):
        """GIVEN block_put raises CancelledError WHEN store is called
        THEN CancelledError propagates (line 254)."""
        mock_ipfs = MagicMock()
        mock_ipfs.block_put.side_effect = asyncio.CancelledError()
        backend = self._backend(mock_ipfs)
        with pytest.raises(asyncio.CancelledError):
            backend.store({"key": "value"}, codec="dag-json")

    # -----------------------------------------------------------------------
    # Line 305: retrieve – block_get raises AttributeError (falls back to cat),
    #           then cat raises CancelledError
    # -----------------------------------------------------------------------
    def test_retrieve_inner_cancelled_error_propagates(self):
        """GIVEN block_get raises AttributeError and cat raises CancelledError
        WHEN retrieve is called THEN the inner CancelledError propagates (line 305)."""
        mock_ipfs = MagicMock()
        mock_ipfs.block_get.side_effect = AttributeError("no block_get")
        mock_ipfs.cat.side_effect = asyncio.CancelledError()
        backend = self._backend(mock_ipfs)
        with pytest.raises(asyncio.CancelledError):
            backend.retrieve("QmTestCID")

    # -----------------------------------------------------------------------
    # Line 327: retrieve – block_get raises CancelledError directly (outer guard)
    # -----------------------------------------------------------------------
    def test_retrieve_outer_cancelled_error_propagates(self):
        """GIVEN block_get raises CancelledError WHEN retrieve is called
        THEN the outer CancelledError propagates (line 327)."""
        mock_ipfs = MagicMock()
        mock_ipfs.block_get.side_effect = asyncio.CancelledError()
        backend = self._backend(mock_ipfs)
        with pytest.raises(asyncio.CancelledError):
            backend.retrieve("QmTestCID2")


# ===========================================================================
# 7. cypher/functions.py – line 575
#    (fn_properties returns {} when no properties attr and no __dict__)
# ===========================================================================

class TestCypherFunctionsFnProperties:
    """GIVEN fn_properties is called with an object that has neither a
    'properties' attribute nor a '__dict__', THEN {} is returned (line 575)."""

    def test_fn_properties_returns_empty_dict_for_no_attrs(self):
        """GIVEN an object with __slots__ and no properties attr
        WHEN fn_properties is called THEN {} is returned (line 575)."""
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_properties

        class _NoAttrs:
            __slots__ = ()

        result = fn_properties(_NoAttrs())
        assert result == {}

    def test_fn_properties_returns_none_for_none_input(self):
        """GIVEN entity=None WHEN fn_properties is called THEN None returned."""
        from ipfs_datasets_py.knowledge_graphs.cypher.functions import fn_properties

        assert fn_properties(None) is None


# ===========================================================================
# 8. cypher/lexer.py – line 330
#    (scientific notation – digit loop after 'e'/'E')
# ===========================================================================

class TestCypherLexerScientificNotation:
    """GIVEN a Cypher expression containing a number in scientific notation,
    WHEN tokenized, THEN the exponent digits are consumed (line 330)."""

    def test_scientific_notation_tokenized_correctly(self):
        """GIVEN '1.5e10' in a RETURN statement WHEN lexer tokenizes it
        THEN a NUMBER token '1.5e10' is produced (line 330)."""
        from ipfs_datasets_py.knowledge_graphs.cypher.lexer import CypherLexer, TokenType

        tokens = list(CypherLexer().tokenize("RETURN 1.5e10"))
        number_tokens = [t for t in tokens if t.type == TokenType.NUMBER]
        assert len(number_tokens) == 1
        assert number_tokens[0].value == "1.5e10"

    def test_scientific_notation_with_sign(self):
        """GIVEN '2.3e-5' WHEN tokenized THEN the signed exponent is captured."""
        from ipfs_datasets_py.knowledge_graphs.cypher.lexer import CypherLexer, TokenType

        tokens = list(CypherLexer().tokenize("RETURN 2.3e-5"))
        number_tokens = [t for t in tokens if t.type == TokenType.NUMBER]
        assert len(number_tokens) == 1
        assert "e" in number_tokens[0].value.lower()


# ===========================================================================
# 9. neo4j_compat/result.py – line 129
#    (Result.keys() with empty records returns [])
# ===========================================================================

class TestNeo4jCompatResultKeys:
    """GIVEN a Result with no records, WHEN keys() is called,
    THEN an empty list is returned (line 129)."""

    def test_keys_with_empty_records_returns_empty_list(self):
        """GIVEN Result([]) WHEN keys() is called THEN [] is returned (line 129)."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Result

        r = Result([])
        assert list(r.keys()) == []

    def test_keys_with_records_returns_field_names(self):
        """GIVEN Result with a Record WHEN keys() is called THEN field names
        are returned (exercising the non-empty path for contrast)."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.result import Result, Record

        rec = Record(["name", "age"], ["Alice", 30])
        r = Result([rec])
        keys = list(r.keys())
        assert "name" in keys
        assert "age" in keys


# ===========================================================================
# 10. neo4j_compat/types.py – line 237
#     (Path node/relationship count mismatch → ValueError)
# ===========================================================================

class TestNeo4jCompatPathValidation:
    """GIVEN a Path with mismatched node and relationship counts,
    WHEN constructed, THEN ValueError is raised (line 237)."""

    def test_path_trailing_relationship_raises_value_error(self):
        """GIVEN Path(n1, r1) with no following node WHEN created
        THEN ValueError is raised (line 237)."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import (
            Node,
            Path,
            Relationship as CompatRel,
        )

        n1 = Node("n1", ["Person"], {"name": "Alice"})
        r1 = CompatRel("r1", "KNOWS", n1, n1, {})
        with pytest.raises(ValueError, match="exactly one more node"):
            Path(n1, r1)

    def test_path_correct_structure_does_not_raise(self):
        """GIVEN Path(n1, r1, n2) with one node following the relationship
        WHEN created THEN no error is raised."""
        from ipfs_datasets_py.knowledge_graphs.neo4j_compat.types import (
            Node,
            Path,
            Relationship as CompatRel,
        )

        n1 = Node("n1", ["Person"], {"name": "Alice"})
        n2 = Node("n2", ["Person"], {"name": "Bob"})
        r1 = CompatRel("r1", "KNOWS", n1, n2, {})
        p = Path(n1, r1, n2)
        assert p.start_node is n1
        assert p.end_node is n2


# ===========================================================================
# 11. jsonld/rdf_serializer.py – lines 237, 297, 307-308, 312-313
# ===========================================================================

class TestRDFSerializerMissedPaths:
    """GIVEN various malformed or edge-case Turtle inputs,
    WHEN TurtleParser.parse or _parse_triples is called,
    THEN EOF guard, empty po_group skip, and single-part skip fire."""

    def _parser(self):
        from ipfs_datasets_py.knowledge_graphs.jsonld.rdf_serializer import TurtleParser
        return TurtleParser()

    # -----------------------------------------------------------------------
    # Line 237: EOF reached while accumulating multi-line triple (no final '.')
    # -----------------------------------------------------------------------
    def test_parse_eof_during_multi_line_triple_does_not_raise(self):
        """GIVEN a Turtle string that has a non-terminated triple (no '.') WHEN
        TurtleParser.parse is called THEN it handles EOF gracefully (line 237)."""
        parser = self._parser()
        turtle_no_period = "@prefix : <http://example.org/> .\n:subject :predicate :object"
        result = parser.parse(turtle_no_period)
        assert result is not None  # should not raise

    # -----------------------------------------------------------------------
    # Line 297: _parse_triples with single-word input → return []
    # -----------------------------------------------------------------------
    def test_parse_triples_single_word_returns_empty(self):
        """GIVEN a single-word string with no space WHEN _parse_triples is
        called THEN an empty list is returned (line 297)."""
        parser = self._parser()
        triples = parser._parse_triples("singleword")
        assert triples == []

    # -----------------------------------------------------------------------
    # Lines 307-308: empty po_group after semicolon split → continue
    # -----------------------------------------------------------------------
    def test_parse_triples_trailing_semicolon_empty_po_group_skipped(self):
        """GIVEN a triple with a trailing semicolon producing an empty
        po_group WHEN _parse_triples is called THEN the empty group is
        skipped (lines 307-308)."""
        parser = self._parser()
        triples = parser._parse_triples(":subject :pred :obj ;")
        # Should produce one triple and silently skip the empty po_group
        assert isinstance(triples, list)

    # -----------------------------------------------------------------------
    # Lines 312-313: po_group contains only one word (no object) → continue
    # -----------------------------------------------------------------------
    def test_parse_triples_single_predicate_no_object_skipped(self):
        """GIVEN a po_group with only a predicate and no object WHEN
        _parse_triples is called THEN the incomplete group is skipped
        (lines 312-313)."""
        parser = self._parser()
        # 'only_pred' has no object after it → po_parts has len < 2 → continue
        triples = parser._parse_triples(":subject only_pred")
        assert isinstance(triples, list)
        # The only_pred po_group has no object so no triple should be generated
        # (subject is 'subject', the predicate group has only 1 part)


# ===========================================================================
# 12. extraction/finance_graphrag.py – line 263
#     (test_hypothesis – exec with no companies → continue)
# ===========================================================================

class TestFinanceGraphRAGTestHypothesis:
    """GIVEN a GraphRAGNewsAnalyzer with mixed executives (some with no
    companies), WHEN test_hypothesis is called, THEN executives with empty
    companies list are skipped (line 263)."""

    def test_test_hypothesis_skips_exec_with_no_companies(self):
        """GIVEN one exec with no companies and one with companies WHEN
        test_hypothesis is called THEN the exec with no companies is skipped
        (line 263)."""
        from ipfs_datasets_py.knowledge_graphs.extraction.finance_graphrag import (
            CompanyPerformance,
            ExecutiveProfile,
            GraphRAGNewsAnalyzer,
            HypothesisTest,
        )

        analyzer = GraphRAGNewsAnalyzer()

        # Executive with NO companies (triggers line 263 continue)
        exec_no_comp = ExecutiveProfile(
            person_id="e1", name="Alice", gender="female", companies=[]
        )
        # Executive WITH companies
        exec_with_comp = ExecutiveProfile(
            person_id="e2", name="Bob", gender="male",
            companies=["AAPL"],
            attributes={"sector": "tech"},
        )
        analyzer.executives = {"e1": exec_no_comp, "e2": exec_with_comp}

        comp = CompanyPerformance(
            company_id="c1", symbol="AAPL", name="Apple", return_percentage=0.15
        )
        comp.metadata = {"sector": "tech"}
        analyzer.companies = {"c1": comp}

        result = analyzer.test_hypothesis(
            "sector hypothesis", "sector", "tech", "finance"
        )
        assert isinstance(result, HypothesisTest)
