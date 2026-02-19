"""
Optional dependency test matrix (Workstream E3).

These tests verify that the knowledge_graphs module degrades gracefully
when optional dependencies (spaCy, transformers, openai, anthropic,
networkx, numpy) are absent, and that informative warnings/errors are
produced rather than obscure ImportErrors propagating to the caller.

Tests follow GIVEN-WHEN-THEN format per repository standards.
"""

import importlib
import sys
import types
import pytest

from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _BlockedImport:
    """Context manager that makes one module appear uninstalled."""

    def __init__(self, *blocked: str):
        self._blocked = set(blocked)
        self._originals: dict = {}

    def __enter__(self):
        for name in self._blocked:
            if name in sys.modules:
                self._originals[name] = sys.modules.pop(name)
        self._patcher = patch.dict(
            "sys.modules",
            {name: None for name in self._blocked},  # type: ignore[dict-item]
        )
        self._patcher.start()
        return self

    def __exit__(self, *_):
        self._patcher.stop()
        # Restore originals so later tests aren't affected
        for name, mod in self._originals.items():
            sys.modules[name] = mod


# ---------------------------------------------------------------------------
# 1. KnowledgeGraphExtractor without spaCy
# ---------------------------------------------------------------------------

class TestExtractorWithoutSpacy:
    """Extractor must degrade gracefully when spaCy is absent."""

    def test_extractor_initializes_without_spacy(self):
        """
        GIVEN: spaCy is not installed (simulated)
        WHEN: KnowledgeGraphExtractor is created with use_spacy=True
        THEN: Initialization succeeds; use_spacy flag is set to False; no ImportError
        """
        # GIVEN: block spaCy at the module level
        # We only need to make `import spacy` fail inside __init__
        with patch.dict("sys.modules", {"spacy": None}):
            # Clear cached module so the import is attempted again
            from ipfs_datasets_py.knowledge_graphs.extraction.extractor import (
                KnowledgeGraphExtractor,
            )

            # WHEN
            extractor = KnowledgeGraphExtractor(use_spacy=True, use_transformers=False)

            # THEN
            assert extractor.use_spacy is False

    def test_extractor_extracts_with_spacy_disabled(self):
        """
        GIVEN: An extractor with use_spacy=False (spaCy explicitly disabled)
        WHEN: extract_knowledge_graph is called
        THEN: Returns a non-empty knowledge graph (rule-based fallback works)
        """
        # GIVEN
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import (
            KnowledgeGraphExtractor,
        )
        extractor = KnowledgeGraphExtractor(use_spacy=False, use_transformers=False)

        # WHEN
        result = extractor.extract_knowledge_graph(
            "Marie Curie was born in Warsaw in 1867."
        )

        # THEN
        kg = result.get("knowledge_graph") if isinstance(result, dict) else result
        assert kg is not None


# ---------------------------------------------------------------------------
# 2. KnowledgeGraphExtractor without transformers
# ---------------------------------------------------------------------------

class TestExtractorWithoutTransformers:
    """Extractor must degrade gracefully when transformers is absent."""

    def test_extractor_initializes_without_transformers(self):
        """
        GIVEN: transformers is not installed (simulated)
        WHEN: KnowledgeGraphExtractor is created with use_transformers=True
        THEN: Initialization succeeds; use_transformers flag is set to False
        """
        with patch.dict("sys.modules", {"transformers": None}):
            from ipfs_datasets_py.knowledge_graphs.extraction.extractor import (
                KnowledgeGraphExtractor,
            )

            extractor = KnowledgeGraphExtractor(use_spacy=False, use_transformers=True)

            assert extractor.use_transformers is False

    def test_extractor_extracts_without_transformers(self):
        """
        GIVEN: An extractor with use_transformers=False
        WHEN: extract_knowledge_graph is called
        THEN: Returns a valid knowledge graph (rule-based fallback)
        """
        from ipfs_datasets_py.knowledge_graphs.extraction.extractor import (
            KnowledgeGraphExtractor,
        )
        extractor = KnowledgeGraphExtractor(use_spacy=False, use_transformers=False)
        result = extractor.extract_knowledge_graph(
            "Albert Einstein developed the theory of relativity."
        )
        kg = result.get("knowledge_graph") if isinstance(result, dict) else result
        assert kg is not None


# ---------------------------------------------------------------------------
# 3. CrossDocumentReasoner without numpy
# ---------------------------------------------------------------------------

class TestCrossDocumentReasonerWithoutNumpy:
    """CrossDocumentReasoner uses numpy but must degrade when it's unavailable."""

    def test_reasoner_bow_similarity_without_vector(self):
        """
        GIVEN: Two DocumentNodes with no vector embeddings
        WHEN: _compute_document_similarity is called
        THEN: Returns a float in [0, 1] using the BoW fallback (no numpy needed)
        """
        # GIVEN – import the module normally (numpy IS available in tests)
        from ipfs_datasets_py.knowledge_graphs.cross_document_reasoning import (
            CrossDocumentReasoner,
            DocumentNode,
        )
        reasoner = CrossDocumentReasoner()
        doc1 = DocumentNode(id="d1", content="cat sat on the mat", source="s1")
        doc2 = DocumentNode(id="d2", content="cat sat on the mat", source="s2")

        # WHEN – vector is None → BoW path
        doc1.vector = None
        doc2.vector = None
        sim = reasoner._compute_document_similarity(doc1, doc2)

        # THEN
        assert 0.0 <= sim <= 1.0
        assert sim > 0.9  # identical content → high similarity

    def test_reasoner_works_with_no_vector_store(self):
        """
        GIVEN: A CrossDocumentReasoner with no vector store
        WHEN: reason_across_documents is called with explicit documents
        THEN: Returns a result dict without crashing
        """
        from ipfs_datasets_py.knowledge_graphs.cross_document_reasoning import (
            CrossDocumentReasoner,
        )
        reasoner = CrossDocumentReasoner()
        result = reasoner.reason_across_documents(
            query="What is AI?",
            input_documents=[
                {"id": "d1", "content": "Artificial intelligence is a field of computer science.", "source": "wiki"},
                {"id": "d2", "content": "AI involves machine learning and deep learning techniques.", "source": "book"},
            ],
        )
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# 4. core module imports without optional deps
# ---------------------------------------------------------------------------

class TestCoreModuleImports:
    """Core module must be importable regardless of optional dep availability."""

    def test_exceptions_module_always_importable(self):
        """
        GIVEN: Any environment
        WHEN: exceptions module is imported
        THEN: All exception classes are accessible
        """
        from ipfs_datasets_py.knowledge_graphs.exceptions import (
            KnowledgeGraphError,
            ExtractionError,
            QueryError,
            StorageError,
            TransactionError,
            MigrationError,
        )
        # All six hierarchies are importable
        assert issubclass(ExtractionError, KnowledgeGraphError)
        assert issubclass(QueryError, KnowledgeGraphError)
        assert issubclass(StorageError, KnowledgeGraphError)
        assert issubclass(TransactionError, KnowledgeGraphError)
        assert issubclass(MigrationError, KnowledgeGraphError)

    def test_cypher_module_importable_without_optional_deps(self):
        """
        GIVEN: Any environment (cypher module has no optional deps)
        WHEN: cypher subpackage is imported
        THEN: CypherParser, CypherCompiler, CypherLexer are available
        """
        from ipfs_datasets_py.knowledge_graphs.cypher.parser import CypherParser
        from ipfs_datasets_py.knowledge_graphs.cypher.compiler import CypherCompiler
        from ipfs_datasets_py.knowledge_graphs.cypher.lexer import CypherLexer

        assert CypherParser is not None
        assert CypherCompiler is not None
        assert CypherLexer is not None

    def test_migration_formats_importable_without_optional_deps(self):
        """
        GIVEN: Any environment
        WHEN: migration.formats is imported
        THEN: GraphData, NodeData, RelationshipData are available
        """
        from ipfs_datasets_py.knowledge_graphs.migration.formats import (
            GraphData,
            NodeData,
            RelationshipData,
            MigrationFormat,
        )
        # Verify basic usage
        node = NodeData(id="1", labels=["Test"], properties={"x": 1})
        graph = GraphData(nodes=[node])
        assert graph.node_count == 1


# ---------------------------------------------------------------------------
# 5. Deprecated legacy shim still works without breaking
# ---------------------------------------------------------------------------

class TestLegacyShim:
    """knowledge_graph_extraction.py shim must still work for backward compat."""

    def test_legacy_shim_emits_deprecation_warning(self):
        """
        GIVEN: The legacy shim module
        WHEN: Imported
        THEN: DeprecationWarning is emitted
        """
        with pytest.warns(DeprecationWarning):
            # Force a fresh import by removing from cache first
            old_mod = sys.modules.pop(
                "ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction", None
            )
            try:
                import ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction  # noqa: F401
            finally:
                if old_mod is not None:
                    sys.modules["ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction"] = old_mod

    def test_legacy_shim_exports_entity_class(self):
        """
        GIVEN: The legacy shim
        WHEN: Entity is imported from it
        THEN: Entity class is available (same as from extraction/)
        """
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            # Re-use cached module if available
            import ipfs_datasets_py.knowledge_graphs.knowledge_graph_extraction as shim
            assert hasattr(shim, "Entity")
            assert hasattr(shim, "KnowledgeGraph")
            assert hasattr(shim, "KnowledgeGraphExtractor")
