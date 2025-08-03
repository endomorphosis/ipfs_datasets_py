#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Test file for TestQueryEngineGetEntityDocuments

import pytest
import os
from unittest.mock import Mock, MagicMock, patch
from typing import List, Dict, Any

from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

home_dir = os.path.expanduser('~')
file_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine.py")
md_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine_stubs.md")

# Make sure the input file and documentation file exist.
assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."

from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator, Entity, Relationship
from ipfs_datasets_py.ipld.storage import IPLDStorage

# Check if each classes methods are accessible:
assert QueryEngine.query
assert QueryEngine._normalize_query
assert QueryEngine._detect_query_type
assert QueryEngine._process_entity_query
assert QueryEngine._process_relationship_query
assert QueryEngine._process_semantic_query
assert QueryEngine._process_document_query
assert QueryEngine._process_cross_document_query
assert QueryEngine._process_graph_traversal_query
assert QueryEngine._extract_entity_names_from_query
assert QueryEngine._get_entity_documents
assert QueryEngine._get_relationship_documents
assert QueryEngine._generate_query_suggestions
assert QueryEngine.get_query_analytics


class TestQueryEngineGetEntityDocuments:
    """Test QueryEngine._get_entity_documents method for entity document attribution."""

    @pytest.fixture
    def mock_graphrag_integrator(self):
        """Create a mock GraphRAG integrator with sample knowledge graphs."""
        mock_integrator = MagicMock(spec=GraphRAGIntegrator)
        
        # Create sample knowledge graphs with proper structure
        mock_kg1 = MagicMock()
        mock_kg1.document_id = "document_001"
        mock_kg1.document_chunks = {
            "document_001": ["doc1_chunk1", "doc1_chunk2", "doc1_chunk3", "doc1_chunk5", "doc1_chunk7"]
        }
        
        # Create second knowledge graph
        mock_kg2 = MagicMock()
        mock_kg2.document_id = "document_002"
        mock_kg2.document_chunks = {
            "document_002": ["doc2_chunk1", "doc2_chunk2", "doc2_chunk3", "doc2_chunk8"]
        }
        
        # Create additional knowledge graphs for tests that expect more documents
        mock_kg3 = MagicMock()
        mock_kg3.document_id = "document_003"
        mock_kg3.document_chunks = {
            "document_003": ["doc3_chunk1", "doc3_chunk2", "doc3_chunk3"]
        }
        
        mock_kg4 = MagicMock()
        mock_kg4.document_id = "document_004"
        mock_kg4.document_chunks = {
            "document_004": ["doc4_chunk1", "doc4_chunk2", "doc4_chunk3"]
        }
        
        mock_kg5 = MagicMock()
        mock_kg5.document_id = "document_005"
        mock_kg5.document_chunks = {
            "document_005": ["doc5_chunk1", "doc5_chunk2", "doc5_chunk3"]
        }
        
        # Set up the knowledge_graphs collection
        mock_integrator.knowledge_graphs = {
            "document_001": mock_kg1,
            "document_002": mock_kg2,
            "document_003": mock_kg3,
            "document_004": mock_kg4,
            "document_005": mock_kg5
        }
        
        return mock_integrator

    @pytest.fixture
    def mock_storage(self):
        """Create a mock IPLD storage."""
        return MagicMock(spec=IPLDStorage)

    @pytest.fixture
    def query_engine(self, mock_graphrag_integrator, mock_storage) -> QueryEngine:
        """Create a QueryEngine instance with mocked dependencies."""
        with patch('ipfs_datasets_py.pdf_processing.query_engine.SentenceTransformer'):
            engine = QueryEngine(
                graphrag_integrator=mock_graphrag_integrator,
                storage=mock_storage,
                embedding_model="test-model"
            )
            return engine

    def test_get_entity_documents_single_document_entity(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance with knowledge graphs
        AND entity with source_chunks from single document
        AND entity.source_chunks = ["doc1_chunk5", "doc1_chunk7"]
        WHEN _get_entity_documents is called
        THEN expect:
            - ["document_001"] returned
            - Document ID extracted from chunk identifier pattern
            - Single document attribution maintained
        """
        # Create entity with source chunks from single document
        entity = Entity(
            id="test_entity_001",
            name="Test Entity",
            type="Person",
            description="Test entity description",
            confidence=0.9,
            source_chunks=["doc1_chunk5", "doc1_chunk7"],
            properties={"role": "engineer", "company": "Tech Corp"}
        )
        
        # Call method under test
        result = query_engine._get_entity_documents(entity)
        
        # Verify single document returned
        assert result == ["document_001"]
        assert len(result) == 1

    def test_get_entity_documents_multi_document_entity(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance with knowledge graphs
        AND entity with source_chunks from multiple documents
        AND entity.source_chunks = ["doc1_chunk3", "doc2_chunk8", "doc3_chunk1"]
        WHEN _get_entity_documents is called
        THEN expect:
            - ["document_001", "document_002", "document_003"] returned
            - All source documents identified
            - No duplicate document IDs in result
        """
        # Create entity with source chunks from multiple documents
        entity = Entity(
            id="test_entity_002",
            name="Multi Doc Entity",
            type="Organization",
            description="Test entity description",
            confidence=0.9,
            source_chunks=["doc1_chunk3", "doc2_chunk8", "doc3_chunk1"],
            properties={}
        )
        
        # Call method under test
        result = query_engine._get_entity_documents(entity)
        
        # Verify multiple documents returned without duplicates
        expected = ["document_001", "document_002", "document_003"]
        assert set(result) == set(expected)
        assert len(result) == len(set(result))  # No duplicates

    def test_get_entity_documents_no_identifiable_documents(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND entity with source_chunks that don't match any document patterns
        AND entity appears in no identifiable documents
        WHEN _get_entity_documents is called
        THEN expect:
            - ["unknown"] returned
            - Graceful handling of unidentifiable sources
        """
        # Create entity with unidentifiable source chunks
        entity = Entity(
            id="test_entity_003",
            name="Unknown Source Entity",
            type="Concept",
            description="Test entity description",
            confidence=0.9,
            source_chunks=["random_chunk1", "unmatched_chunk2", "fake_chunk3"],
            properties={}
        )
        
        # Call method under test
        result = query_engine._get_entity_documents(entity)
        
        # Verify unknown document returned
        assert result == ["unknown"]

    def test_get_entity_documents_knowledge_graph_iteration(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance with multiple knowledge graphs
        AND entity present across different knowledge graphs
        WHEN _get_entity_documents is called
        THEN expect:
            - All knowledge graphs in GraphRAG integrator searched
            - Document matches aggregated across graphs
            - Comprehensive document identification
        """
        # Create entity with chunks from different knowledge graphs
        entity = Entity(
            id="test_entity_004",
            name="Cross Graph Entity",
            type="Technology",
            description="Test entity description",
            confidence=0.9,
            source_chunks=["doc1_chunk2", "doc4_chunk1", "doc5_chunk3"],
            properties={}
        )
        
        # Call method under test
        result = query_engine._get_entity_documents(entity)
        
        # Verify documents from multiple graphs are found
        expected = ["document_001", "document_004", "document_005"]
        assert set(result) == set(expected)

    def test_get_entity_documents_chunk_to_document_mapping(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND entity with various chunk identifier formats
        WHEN _get_entity_documents is called
        THEN expect:
            - Chunk identifiers correctly mapped to document IDs
            - Document chunk identifier patterns recognized
            - Robust chunk-to-document resolution
        """
        # Create entity with various chunk formats
        entity = Entity(
            id="test_entity_005",
            name="Varied Format Entity",
            type="Location",
            description="Test entity description",
            confidence=0.9,
            source_chunks=["doc1_chunk1", "doc2_chunk3", "doc4_chunk2"],
            properties={}
        )
        
        # Call method under test
        result = query_engine._get_entity_documents(entity)
        
        # Verify correct document mapping
        expected = ["document_001", "document_002", "document_004"]
        assert set(result) == set(expected)

    def test_get_entity_documents_empty_source_chunks(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND entity with empty source_chunks list
        WHEN _get_entity_documents is called
        THEN expect:
            - ["unknown"] returned
            - Empty source chunks handled gracefully
            - No exceptions raised
        """
        # Create entity with empty source chunks
        entity = Entity(
            id="test_entity_006",
            name="Empty Chunks Entity",
            type="Person",
            description="Test entity description",
            confidence=0.9,
            source_chunks=[],
            properties={}
        )
        
        # Call method under test
        result = query_engine._get_entity_documents(entity)
        
        # Verify unknown document returned for empty chunks
        assert result == ["unknown"]

    def test_get_entity_documents_invalid_entity_type(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND non-Entity object passed as parameter
        WHEN _get_entity_documents is called
        THEN expect TypeError to be raised
        """
        # Create non-Entity object
        invalid_entity = {"id": "fake", "name": "Not an Entity"}
        
        # Verify TypeError is raised
        with pytest.raises(TypeError, match="entity is not an Entity instance"):
            query_engine._get_entity_documents(invalid_entity)

    def test_get_entity_documents_missing_source_chunks_attribute(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND entity object lacking source_chunks attribute
        WHEN _get_entity_documents is called
        THEN expect AttributeError to be raised
        """
        # Create mock entity without source_chunks
        mock_entity = Mock(spec=Entity)
        del mock_entity.source_chunks  # Remove the attribute
        
        # Verify AttributeError is raised
        with pytest.raises(AttributeError, match="source_chunks"):
            query_engine._get_entity_documents(mock_entity)

    def test_get_entity_documents_corrupted_knowledge_graph(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance with corrupted knowledge graph data
        AND valid entity object
        WHEN _get_entity_documents is called
        THEN expect RuntimeError to be raised
        """
        # Corrupt the knowledge graphs by setting document_chunks to None
        first_kg = list(query_engine.graphrag.knowledge_graphs.values())[0]
        first_kg.document_chunks = None

        entity = Entity(
            id="test_entity_007",
            name="Test Entity",
            type="Person",
            description="Test entity description",
            confidence=0.9,
            source_chunks=["doc1_chunk1"],
            properties={}
        )

        # Verify RuntimeError is raised
        with pytest.raises(RuntimeError, match="knowledge graph data is corrupted"):
            query_engine._get_entity_documents(entity)

    def test_get_entity_documents_inaccessible_knowledge_graph(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance with inaccessible knowledge graph data
        AND valid entity object
        WHEN _get_entity_documents is called
        THEN expect RuntimeError to be raised
        """
        # Make knowledge graphs inaccessible
        query_engine.graphrag.knowledge_graphs = None
        
        entity = Entity(
            id="test_entity_008",
            name="Test Entity",
            type="Person",
            source_chunks=["doc1_chunk1"],
            description="Test entity description",
            confidence=0.9,
            properties={}
        )
        
        # Verify RuntimeError is raised
        with pytest.raises(RuntimeError, match="knowledge graph data is.*inaccessible"):
            query_engine._get_entity_documents(entity)

    def test_get_entity_documents_unique_document_ids(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND entity with source_chunks containing duplicate document references
        AND entity.source_chunks = ["doc1_chunk1", "doc1_chunk2", "doc1_chunk3"]
        WHEN _get_entity_documents is called
        THEN expect:
            - ["document_001"] returned (no duplicates)
            - Unique document IDs only
            - Duplicate document references consolidated
        """
        # Create entity with multiple chunks from same document
        entity = Entity(
            id="test_entity_009",
            name="Duplicate Doc Entity",
            type="Organization",
            source_chunks=["doc1_chunk1", "doc1_chunk2", "doc1_chunk3"],
            description="Test entity description",
            confidence=0.9,
            properties={}
        )
        
        # Call method under test
        result = query_engine._get_entity_documents(entity)
        
        # Verify no duplicates and single document
        assert result == ["document_001"]
        assert len(result) == 1

    def test_get_entity_documents_knowledge_graph_iteration_order(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance with multiple knowledge graphs
        AND entity appearing in different graphs
        WHEN _get_entity_documents is called
        THEN expect:
            - Documents returned in knowledge graph iteration order
            - Consistent ordering across calls
            - Deterministic result ordering
        """
        # Create entity with chunks in specific order across graphs
        entity = Entity(
            id="test_entity_010",
            name="Order Test Entity",
            type="Technology",
            source_chunks=["doc4_chunk1", "doc1_chunk1", "doc5_chunk1"],
            description="Test entity description",
            confidence=0.9,
            properties={}
        )
        
        # Call method multiple times
        result1 = query_engine._get_entity_documents(entity)
        result2 = query_engine._get_entity_documents(entity)
        
        # Verify consistent ordering
        assert result1 == result2
        # Documents should appear in knowledge graph iteration order
        expected_order = ["document_001", "document_004", "document_005"]
        assert result1 == expected_order

    def test_get_entity_documents_performance_with_large_graphs(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance with large knowledge graphs
        AND entity with many source chunks
        WHEN _get_entity_documents is called
        THEN expect:
            - Method completes within reasonable time
            - Performance scales appropriately with graph size
            - Memory usage remains controlled
        """
        import time
        
        # Create large knowledge graph
        large_chunks = {}
        for i in range(100):
            doc_id = f"document_{i:03d}"
            large_chunks[doc_id] = [f"doc{i}_chunk{j}" for j in range(50)]
        
        # Add to the first available knowledge graph, or create one if none exist
        if query_engine.graphrag.knowledge_graphs:
            # Get the first knowledge graph from the dictionary
            first_kg = next(iter(query_engine.graphrag.knowledge_graphs.values()))
            first_kg.document_chunks = large_chunks
        else:
            # Create a mock knowledge graph if none exist
            mock_kg = MagicMock()
            mock_kg.document_chunks = large_chunks
            query_engine.graphrag.knowledge_graphs["test_kg"] = mock_kg
        
        # Create entity with many chunks
        source_chunks = []
        for i in range(0, 50, 5):  # Every 5th document
            source_chunks.extend([f"doc{i}_chunk{j}" for j in range(0, 10, 2)])
        
        entity = Entity(
            id="test_entity_011",
            name="Large Graph Entity",
            type="Concept",
            description="Test entity description",
            confidence=0.9,
            source_chunks=source_chunks,
            properties={}
        )
        
        # Measure execution time
        start_time = time.time()
        result = query_engine._get_entity_documents(entity)
        execution_time = time.time() - start_time
        
        # Verify reasonable performance (should complete in under 1 second)
        assert execution_time < 1.0
        assert len(result) > 0  # Should find some documents

    def test_get_entity_documents_chunk_identifier_patterns(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND entity with various chunk identifier patterns
        AND different document naming conventions
        WHEN _get_entity_documents is called
        THEN expect:
            - Various chunk identifier formats handled
            - Document extraction robust across naming patterns
            - Flexible pattern matching implemented
        """
        # Add knowledge graph with different naming patterns
        mock_kg_patterns = MagicMock()
        mock_kg_patterns.document_chunks = {
            "document_001": ["doc1_chunk1", "doc1_section2", "doc1_para3"],
            "paper_002": ["paper2_ch1", "paper2_sec2"],
            "report_003": ["rep3_p1", "rep3_p2"]
        }
        query_engine.graphrag.knowledge_graphs["patterns_test_kg"] = mock_kg_patterns
        
        # Create entity with mixed patterns
        entity = Entity(
            id="test_entity_012",
            name="Pattern Test Entity",
            type="Method",
            source_chunks=["doc1_section2", "paper2_ch1", "rep3_p1"],
            description="Test entity description",
            confidence=0.9,
            properties={}
        )
        
        # Call method under test
        result = query_engine._get_entity_documents(entity)
        
        # Verify all pattern types are handled
        expected = ["document_001", "paper_002", "report_003"]
        assert set(result) == set(expected)

    def test_get_entity_documents_source_attribution_accuracy(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance with known document-chunk mappings
        AND entity with specific source chunks
        WHEN _get_entity_documents is called
        THEN expect:
            - Source attribution 100% accurate
            - Correct document IDs for each chunk
            - No false positives or missed documents
        """
        # Create entity with precisely mapped chunks
        entity = Entity(
            id="test_entity_013",
            name="Accuracy Test Entity",
            type="Process",
            source_chunks=["doc1_chunk5", "doc2_chunk8", "doc5_chunk3"],
            description="Test entity description",
            confidence=0.9,
            properties={}
        )
        
        # Call method under test
        result = query_engine._get_entity_documents(entity)
        
        # Verify exact attribution
        expected = ["document_001", "document_002", "document_005"]
        assert set(result) == set(expected)
        assert len(result) == 3  # No false positives

    def test_get_entity_documents_cross_graph_consistency(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance with entity appearing in multiple graphs
        AND same entity with different chunk references across graphs
        WHEN _get_entity_documents is called
        THEN expect:
            - Consistent document identification across graphs
            - All document sources aggregated properly
            - Cross-graph entity document mapping maintained
        """
        # Create entity with chunks across multiple graphs
        entity = Entity(
            id="test_entity_014",
            name="Cross Graph Consistency Entity",
            type="Framework",
            source_chunks=["doc1_chunk1", "doc4_chunk2", "doc5_chunk1"],
            description="Test entity description",
            confidence=0.9,
            properties={}
        )
        
        # Call method under test
        result = query_engine._get_entity_documents(entity)
        
        # Verify cross-graph aggregation
        expected = ["document_001", "document_004", "document_005"]
        assert set(result) == set(expected)

    def test_get_entity_documents_malformed_chunk_identifiers(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND entity with malformed or unexpected chunk identifier formats
        WHEN _get_entity_documents is called
        THEN expect:
            - Malformed identifiers handled gracefully
            - Valid identifiers still processed
            - No method failure due to format issues
        """
        # Create entity with mix of valid and malformed chunks
        entity = Entity(
            id="test_entity_015",
            name="Malformed Chunks Entity",
            type="Data",
            source_chunks=[
                "doc1_chunk1",  # Valid
                "malformed_identifier",  # Invalid
                "",  # Empty
                "doc2_chunk8",  # Valid
                "another_bad_format"  # Invalid
            ],
            description="Test entity description",
            confidence=0.9,
            properties={}
        )
        
        # Call method under test
        result = query_engine._get_entity_documents(entity)
        
        # Verify valid chunks are processed, malformed ones ignored
        expected = ["document_001", "document_002"]
        assert set(result) == set(expected)

    def test_get_entity_documents_none_entity_input(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND None passed as entity parameter
        WHEN _get_entity_documents is called
        THEN expect TypeError to be raised
        """
        # Verify TypeError is raised for None input
        with pytest.raises(TypeError, match="entity is not an Entity instance"):
            query_engine._get_entity_documents(None)

    def test_get_entity_documents_entity_id_preservation(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance
        AND entity with specific ID and source chunks
        WHEN _get_entity_documents is called
        THEN expect:
            - Original entity ID preserved and not modified
            - Entity object state unchanged
            - Method is read-only with respect to entity
        """
        # Create entity and store original state
        original_id = "test_entity_016"
        original_name = "Preservation Test Entity"
        original_chunks = ["doc1_chunk2", "doc2_chunk3"]
        
        entity = Entity(
            id=original_id,
            name=original_name,
            type="Algorithm",
            description="Test entity description",
            confidence=0.9,
            source_chunks=original_chunks.copy(),
            properties={}
        )
        
        # Call method under test
        result = query_engine._get_entity_documents(entity)
        
        # Verify entity state is unchanged
        assert entity.id == original_id
        assert entity.name == original_name
        assert entity.source_chunks == original_chunks
        
        # Verify result is correct
        expected = ["document_001", "document_002"]
        assert set(result) == set(expected)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])