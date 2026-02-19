"""
Tests for Workstream I improvements:
  - core.types (type aliases, TypedDicts, Protocols)
  - extraction._entity_helpers extraction
  - core._legacy_graph_engine extraction
  - query/__init__ naming normalization (import + docstring)

Tests follow GIVEN-WHEN-THEN format per repository standards.
"""

import pytest
from typing import get_type_hints


class TestCoreTypesModule:
    """Type aliases, TypedDicts, and Protocols in core/types.py are importable and usable."""

    def test_type_aliases_importable(self):
        """
        GIVEN: core.types module
        WHEN: Importing type aliases
        THEN: All aliases are available and have the right base types
        """
        # GIVEN / WHEN
        from ipfs_datasets_py.knowledge_graphs.core.types import (
            GraphProperties,
            NodeLabels,
            CID,
        )
        from typing import get_origin, get_args, Dict, List, Any

        # THEN
        # GraphProperties == Dict[str, Any]
        assert get_origin(GraphProperties) is dict
        # NodeLabels == List[str]
        assert get_origin(NodeLabels) is list
        assert CID is str

    def test_typeddicts_importable(self):
        """
        GIVEN: core.types module
        WHEN: Importing TypedDicts
        THEN: All TypedDicts can be instantiated as plain dicts
        """
        # GIVEN / WHEN
        from ipfs_datasets_py.knowledge_graphs.core.types import (
            GraphStats,
            NodeRecord,
            RelationshipRecord,
            WALStats,
            QuerySummary,
        )

        # THEN – TypedDicts are dict subclasses at runtime; use them as dicts
        gs: GraphStats = {"node_count": 5, "relationship_count": 3}
        nr: NodeRecord = {"id": "n1", "labels": ["Person"], "properties": {"name": "Alice"}}
        rr: RelationshipRecord = {
            "id": "r1", "type": "KNOWS", "start_node": "n1", "end_node": "n2",
            "properties": {},
        }
        ws: WALStats = {"head_cid": None, "entry_count": 0, "needs_compaction": False}
        qs: QuerySummary = {"query_type": "Cypher", "query": "MATCH (n) RETURN n"}

        assert gs["node_count"] == 5
        assert nr["id"] == "n1"
        assert rr["type"] == "KNOWS"
        assert ws["entry_count"] == 0
        assert qs["query_type"] == "Cypher"

    def test_protocols_importable(self):
        """
        GIVEN: core.types module
        WHEN: Importing Protocol classes
        THEN: Protocols are usable as type annotations (runtime-checkable)
        """
        # GIVEN / WHEN
        from ipfs_datasets_py.knowledge_graphs.core.types import (
            StorageBackend,
            GraphEngineProtocol,
        )

        # THEN – Protocols are classes
        assert isinstance(StorageBackend, type)
        assert isinstance(GraphEngineProtocol, type)

    def test_core_init_exports_types(self):
        """
        GIVEN: knowledge_graphs.core package
        WHEN: Importing type utilities from the package root
        THEN: All type utilities are accessible
        """
        # GIVEN / WHEN
        from ipfs_datasets_py.knowledge_graphs.core import (
            GraphProperties,
            NodeLabels,
            CID,
            GraphStats,
            StorageBackend,
            GraphEngineProtocol,
        )

        # THEN
        assert GraphProperties is not None
        assert NodeLabels is not None
        assert CID is str
        assert GraphStats is not None
        assert StorageBackend is not None
        assert GraphEngineProtocol is not None

    def test_graphengine_satisfies_protocol(self):
        """
        GIVEN: GraphEngine and GraphEngineProtocol
        WHEN: Checking structural compatibility
        THEN: GraphEngine has all methods required by the protocol
        """
        # GIVEN
        from ipfs_datasets_py.knowledge_graphs.core.graph_engine import GraphEngine
        from ipfs_datasets_py.knowledge_graphs.core.types import GraphEngineProtocol

        required = {"create_node", "get_node", "find_nodes", "create_relationship"}

        # WHEN
        engine_methods = {m for m in dir(GraphEngine) if not m.startswith("__")}

        # THEN
        missing = required - engine_methods
        assert not missing, f"GraphEngine is missing protocol methods: {missing}"


class TestEntityHelpersExtraction:
    """The 4 helper functions moved to _entity_helpers.py are accessible from both locations."""

    def test_helpers_importable_from_new_module(self):
        """
        GIVEN: extraction._entity_helpers module
        WHEN: Importing all 4 helper functions
        THEN: They are importable and callable
        """
        # GIVEN / WHEN
        from ipfs_datasets_py.knowledge_graphs.extraction._entity_helpers import (
            _map_spacy_entity_type,
            _map_transformers_entity_type,
            _rule_based_entity_extraction,
            _string_similarity,
        )

        # THEN
        assert callable(_map_spacy_entity_type)
        assert callable(_map_transformers_entity_type)
        assert callable(_rule_based_entity_extraction)
        assert callable(_string_similarity)

    def test_helpers_still_importable_from_extractor(self):
        """
        GIVEN: extraction.extractor module (backward compat)
        WHEN: Importing helpers from the old location
        THEN: They import from extractor as before
        """
        # GIVEN / WHEN
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import (
            _map_spacy_entity_type,
            _map_transformers_entity_type,
            _rule_based_entity_extraction,
            _string_similarity,
        )

        # THEN
        assert callable(_map_spacy_entity_type)
        assert callable(_string_similarity)

    def test_helpers_are_same_object(self):
        """
        GIVEN: Both import paths
        WHEN: Importing from both
        THEN: The re-exported symbols are the same function objects (no duplication)
        """
        # GIVEN / WHEN
        from ipfs_datasets_py.knowledge_graphs.extraction._entity_helpers import (
            _map_spacy_entity_type as h,
            _string_similarity as ss,
        )
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import (
            _map_spacy_entity_type as e,
            _string_similarity as ess,
        )

        # THEN
        assert h is e
        assert ss is ess

    def test_map_spacy_entity_type_correct(self):
        """
        GIVEN: _map_spacy_entity_type
        WHEN: Called with known spaCy labels
        THEN: Returns correct normalized types
        """
        # GIVEN / WHEN
        from ipfs_datasets_py.knowledge_graphs.extraction._entity_helpers import (
            _map_spacy_entity_type,
        )

        # THEN
        assert _map_spacy_entity_type("PERSON") == "person"
        assert _map_spacy_entity_type("ORG") == "organization"
        assert _map_spacy_entity_type("GPE") == "location"
        assert _map_spacy_entity_type("UNKNOWN_TAG") == "entity"

    def test_string_similarity_bounds(self):
        """
        GIVEN: _string_similarity
        WHEN: Called with identical, disjoint, and partial-overlap strings
        THEN: Returns values in [0, 1]
        """
        from ipfs_datasets_py.knowledge_graphs.extraction._entity_helpers import (
            _string_similarity,
        )

        assert _string_similarity("hello world", "hello world") == 1.0
        assert _string_similarity("hello", "goodbye") == 0.0
        score = _string_similarity("hello world", "hello there")
        assert 0.0 < score < 1.0
        assert _string_similarity("", "hello") == 0.0

    def test_rule_based_extraction_returns_entities(self):
        """
        GIVEN: _rule_based_entity_extraction
        WHEN: Called with a text containing a known name
        THEN: Returns a non-empty list of Entity objects
        """
        from ipfs_datasets_py.knowledge_graphs.extraction._entity_helpers import (
            _rule_based_entity_extraction,
        )

        entities = _rule_based_entity_extraction("Marie Curie won the Nobel Prize in 2020.")
        assert isinstance(entities, list)
        # At minimum the year 2020 and probably the name should be found
        assert len(entities) >= 1

    def test_extractor_file_size_reduced(self):
        """
        GIVEN: extraction/extractor.py
        WHEN: Counting lines
        THEN: File has fewer than 1700 lines (was 1760; target ≤ 1700)
        """
        import importlib.util, os
        spec = importlib.util.find_spec("ipfs_datasets_py.knowledge_graphs.extraction.extractor")
        assert spec is not None
        path = spec.origin
        with open(path) as f:
            lines = f.readlines()
        assert len(lines) <= 1700, f"extractor.py has {len(lines)} lines, expected ≤ 1700"


class TestLegacyGraphEngineExtraction:
    """The _LegacyGraphEngine class was moved to core/_legacy_graph_engine.py."""

    def test_legacy_engine_importable_from_new_module(self):
        """
        GIVEN: core._legacy_graph_engine module
        WHEN: Importing _LegacyGraphEngine
        THEN: Class is importable and instantiable
        """
        from ipfs_datasets_py.knowledge_graphs.core._legacy_graph_engine import _LegacyGraphEngine
        engine = _LegacyGraphEngine()
        assert engine is not None

    def test_legacy_engine_still_importable_from_query_executor(self):
        """
        GIVEN: core.query_executor module (backward compat)
        WHEN: Importing _LegacyGraphEngine
        THEN: Same class is accessible
        """
        from ipfs_datasets_py.knowledge_graphs.core.query_executor import _LegacyGraphEngine
        engine = _LegacyGraphEngine()
        assert engine is not None

    def test_legacy_engine_same_object(self):
        """
        GIVEN: Both import paths for _LegacyGraphEngine
        WHEN: Importing from both
        THEN: The re-exported symbol is the same class object
        """
        from ipfs_datasets_py.knowledge_graphs.core._legacy_graph_engine import (
            _LegacyGraphEngine as A,
        )
        from ipfs_datasets_py.knowledge_graphs.core.query_executor import (
            _LegacyGraphEngine as B,
        )
        assert A is B

    def test_query_executor_file_size_reduced(self):
        """
        GIVEN: core/query_executor.py
        WHEN: Counting lines
        THEN: File has fewer than 600 lines (was 1189; target ≤ 600)
        """
        import importlib.util
        spec = importlib.util.find_spec("ipfs_datasets_py.knowledge_graphs.core.query_executor")
        assert spec is not None
        path = spec.origin
        with open(path) as f:
            lines = f.readlines()
        assert len(lines) <= 600, f"query_executor.py has {len(lines)} lines, expected ≤ 600"

    def test_legacy_engine_create_node(self):
        """
        GIVEN: A _LegacyGraphEngine instance
        WHEN: create_node() is called
        THEN: Returns a Node with correct labels and properties
        """
        from ipfs_datasets_py.knowledge_graphs.core._legacy_graph_engine import _LegacyGraphEngine
        engine = _LegacyGraphEngine()
        node = engine.create_node(labels=["Person"], properties={"name": "Alice"})
        assert "Person" in node.labels
        assert node["name"] == "Alice"

    def test_legacy_engine_find_nodes(self):
        """
        GIVEN: A _LegacyGraphEngine with 3 nodes
        WHEN: find_nodes() is called with a label filter
        THEN: Returns only matching nodes
        """
        from ipfs_datasets_py.knowledge_graphs.core._legacy_graph_engine import _LegacyGraphEngine
        engine = _LegacyGraphEngine()
        engine.create_node(labels=["Person"], properties={"name": "Alice"})
        engine.create_node(labels=["Person"], properties={"name": "Bob"})
        engine.create_node(labels=["Company"], properties={"name": "Acme"})

        people = engine.find_nodes(labels=["Person"])
        assert len(people) == 2
        companies = engine.find_nodes(labels=["Company"])
        assert len(companies) == 1


class TestQueryModuleNamingGuide:
    """The query/__init__.py docstring contains the naming/role guide."""

    def test_query_init_has_role_guide(self):
        """
        GIVEN: query/__init__.py
        WHEN: Reading its module docstring
        THEN: Contains role descriptions for GraphEngine, QueryExecutor, UnifiedQueryEngine
        """
        import ipfs_datasets_py.knowledge_graphs.query as q

        doc = q.__doc__ or ""
        assert "GraphEngine" in doc
        assert "QueryExecutor" in doc
        assert "UnifiedQueryEngine" in doc
        # Should include the role guide section header
        assert "role guide" in doc.lower() or "Component role" in doc

    def test_query_init_exports_unchanged(self):
        """
        GIVEN: query/__init__.py
        WHEN: Importing from it
        THEN: UnifiedQueryEngine, HybridSearchEngine, BudgetManager still available
        """
        from ipfs_datasets_py.knowledge_graphs.query import (
            UnifiedQueryEngine,
            HybridSearchEngine,
            BudgetManager,
        )
        assert callable(UnifiedQueryEngine)
        assert callable(HybridSearchEngine)
        assert callable(BudgetManager)
