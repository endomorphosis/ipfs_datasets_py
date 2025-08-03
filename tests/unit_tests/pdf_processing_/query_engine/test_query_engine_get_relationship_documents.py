#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# Test file for TestQueryEngineGetRelationshipDocuments

import pytest
import os
from unittest.mock import Mock, patch, MagicMock
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
from ipfs_datasets_py.ipld import IPLDStorage

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


class TestQueryEngineGetRelationshipDocuments:
    """Test QueryEngine._get_relationship_documents method for relationship document attribution."""

    @pytest.fixture
    def mock_graphrag_integrator(self):
        """Create a mock GraphRAGIntegrator with test data."""
        mock_integrator = Mock(spec=GraphRAGIntegrator)
        
        # Mock knowledge graphs with documents and chunks
        mock_kg1 = Mock()
        mock_kg1.documents = {
            "document_001": {
                "chunks": ["doc1_chunk1", "doc1_chunk2", "doc1_chunk3", "doc1_chunk4", "doc1_chunk5", "doc1_chunk6"]
            },
            "document_002": {
                "chunks": ["doc2_chunk1", "doc2_chunk2", "doc2_chunk3", "doc2_chunk4", "doc2_chunk5"]
            }
        }
        
        mock_kg2 = Mock()
        mock_kg2.documents = {
            "document_003": {
                "chunks": ["doc3_chunk1", "doc3_chunk2", "doc3_chunk3"]
            },
            "document_005": {
                "chunks": ["doc5_chunk1", "doc5_chunk2", "doc5_chunk3", "doc5_chunk4", "doc5_chunk5"]
            }
        }
        
        mock_integrator.knowledge_graphs = [mock_kg1, mock_kg2]
        return mock_integrator

    @pytest.fixture
    def mock_storage(self):
        """Create a mock IPLDStorage."""
        return Mock(spec=IPLDStorage)

    @pytest.fixture
    def query_engine(self, mock_graphrag_integrator, mock_storage):
        """Create a QueryEngine instance with mocked dependencies."""
        with patch('ipfs_datasets_py.pdf_processing.query_engine.SentenceTransformer'):
            engine = QueryEngine(
                graphrag_integrator=mock_graphrag_integrator,
                storage=mock_storage,
                embedding_model="test-model"
            )
            return engine

    def test_get_relationship_documents_single_document_relationship(self, query_engine):
        """
        GIVEN a QueryEngine instance with knowledge graphs
        AND relationship with source_chunks from single document
        AND relationship.source_chunks = ["doc1_chunk3", "doc1_chunk6"]
        WHEN _get_relationship_documents is called
        THEN expect:
            - ["document_001"] returned
            - Document ID extracted from chunk identifier pattern
            - Single document attribution maintained
        """
        # Create relationship with source chunks from single document
        relationship = Mock(spec=Relationship)
        relationship.source_chunks = ["doc1_chunk3", "doc1_chunk6"]
        
        # Call the method
        result = query_engine._get_relationship_documents(relationship)
        
        # Verify single document returned
        assert result == ["document_001"]
        assert len(result) == 1

    def test_get_relationship_documents_multi_document_relationship(self, query_engine):
        """
        GIVEN a QueryEngine instance with knowledge graphs
        AND relationship with source_chunks from multiple documents
        AND relationship.source_chunks = ["doc1_chunk2", "doc3_chunk1", "doc5_chunk4"]
        WHEN _get_relationship_documents is called
        THEN expect:
            - ["document_001", "document_003", "document_005"] returned
            - All source documents identified
            - No duplicate document IDs in result
        """
        # Create relationship with source chunks from multiple documents
        relationship = Mock(spec=Relationship)
        relationship.source_chunks = ["doc1_chunk2", "doc3_chunk1", "doc5_chunk4"]
        
        # Call the method
        result = query_engine._get_relationship_documents(relationship)
        
        # Verify multiple documents returned
        assert set(result) == {"document_001", "document_003", "document_005"}
        assert len(result) == 3
        # Verify no duplicates
        assert len(result) == len(set(result))

    def test_get_relationship_documents_no_identifiable_documents(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND relationship with source_chunks that don't match any document patterns
        AND relationship appears in no identifiable documents
        WHEN _get_relationship_documents is called
        THEN expect:
            - ["unknown"] returned
            - Graceful handling of unidentifiable sources
        """
        # Create relationship with unidentifiable source chunks
        relationship = Mock(spec=Relationship)
        relationship.source_chunks = ["unknown_chunk1", "invalid_pattern", "xyz_abc"]
        
        # Call the method
        result = query_engine._get_relationship_documents(relationship)
        
        # Verify "unknown" returned for unidentifiable documents
        assert result == ["unknown"]

    def test_get_relationship_documents_knowledge_graph_iteration(self, query_engine):
        """
        GIVEN a QueryEngine instance with multiple knowledge graphs
        AND relationship present across different knowledge graphs
        WHEN _get_relationship_documents is called
        THEN expect:
            - All knowledge graphs in GraphRAG integrator searched
            - Document matches aggregated across graphs
            - Comprehensive document identification
        """
        # Create relationship with chunks across different knowledge graphs
        relationship = Mock(spec=Relationship)
        relationship.source_chunks = ["doc1_chunk1", "doc3_chunk2", "doc5_chunk3"]
        
        # Call the method
        result = query_engine._get_relationship_documents(relationship)
        
        # Verify documents from different knowledge graphs are found
        assert set(result) == {"document_001", "document_003", "document_005"}
        # Verify all knowledge graphs were searched (doc1 from kg1, doc3,doc5 from kg2)
        assert len(result) == 3

    def test_get_relationship_documents_chunk_to_document_mapping(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND relationship with various chunk identifier formats
        WHEN _get_relationship_documents is called
        THEN expect:
            - Chunk identifiers correctly mapped to document IDs
            - Document chunk identifier patterns recognized
            - Robust chunk-to-document resolution
        """
        # Create relationship with various chunk formats
        relationship = Mock(spec=Relationship)
        relationship.source_chunks = ["doc1_chunk4", "doc2_chunk1", "doc3_chunk3"]
        
        # Call the method
        result = query_engine._get_relationship_documents(relationship)
        
        # Verify correct document mapping
        assert set(result) == {"document_001", "document_002", "document_003"}

    def test_get_relationship_documents_empty_source_chunks(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND relationship with empty source_chunks list
        WHEN _get_relationship_documents is called
        THEN expect:
            - ["unknown"] returned
            - Empty source chunks handled gracefully
            - No exceptions raised
        """
        # Create relationship with empty source chunks
        relationship = Mock(spec=Relationship)
        relationship.source_chunks = []
        
        # Call the method - should not raise exception
        result = query_engine._get_relationship_documents(relationship)
        
        # Verify "unknown" returned for empty chunks
        assert result == ["unknown"]

    def test_get_relationship_documents_invalid_relationship_type(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND non-Relationship object passed as parameter
        WHEN _get_relationship_documents is called
        THEN expect TypeError to be raised
        """
        # Pass invalid type (string instead of Relationship)
        invalid_relationship = "not_a_relationship"
        
        # Verify TypeError is raised
        with pytest.raises(TypeError):
            query_engine._get_relationship_documents(invalid_relationship)

    def test_get_relationship_documents_missing_source_chunks_attribute(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND relationship object lacking source_chunks attribute
        WHEN _get_relationship_documents is called
        THEN expect AttributeError to be raised
        """
        # Create object without source_chunks attribute
        relationship = Mock()
        del relationship.source_chunks  # Remove the attribute
        
        # Verify AttributeError is raised
        with pytest.raises(AttributeError):
            query_engine._get_relationship_documents(relationship)

    def test_get_relationship_documents_corrupted_knowledge_graph(self, query_engine):
        """
        GIVEN a QueryEngine instance with corrupted knowledge graph data
        AND valid relationship object
        WHEN _get_relationship_documents is called
        THEN expect RuntimeError to be raised
        """
        # Create relationship
        relationship = Mock(spec=Relationship)
        relationship.source_chunks = ["doc1_chunk1"]
        
        # Corrupt the knowledge graph data
        query_engine.graphrag.knowledge_graphs[0].documents = None
        
        # Verify RuntimeError is raised
        with pytest.raises(RuntimeError):
            query_engine._get_relationship_documents(relationship)

    def test_get_relationship_documents_inaccessible_knowledge_graph(self, query_engine):
        """
        GIVEN a QueryEngine instance with inaccessible knowledge graph data
        AND valid relationship object
        WHEN _get_relationship_documents is called
        THEN expect RuntimeError to be raised
        """
        # Create relationship
        relationship = Mock(spec=Relationship)
        relationship.source_chunks = ["doc1_chunk1"]
        
        # Make knowledge graphs inaccessible
        query_engine.graphrag.knowledge_graphs = None
        
        # Verify RuntimeError is raised
        with pytest.raises(RuntimeError):
            query_engine._get_relationship_documents(relationship)

    def test_get_relationship_documents_unique_document_ids(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND relationship with source_chunks containing duplicate document references
        AND relationship.source_chunks = ["doc2_chunk1", "doc2_chunk2", "doc2_chunk5"]
        WHEN _get_relationship_documents is called
        THEN expect:
            - ["document_002"] returned (no duplicates)
            - Unique document IDs only
            - Duplicate document references consolidated
        """
        # Create relationship with chunks from same document
        relationship = Mock(spec=Relationship)
        relationship.source_chunks = ["doc2_chunk1", "doc2_chunk2", "doc2_chunk5"]
        
        # Call the method
        result = query_engine._get_relationship_documents(relationship)
        
        # Verify only unique document ID returned
        assert result == ["document_002"]
        assert len(result) == 1

    def test_get_relationship_documents_relationship_provenance_tracking(self, query_engine):
        """
        GIVEN a QueryEngine instance with relationships having provenance data
        AND relationship with documented evidence sources
        WHEN _get_relationship_documents is called
        THEN expect:
            - Relationship provenance accurately traced
            - Evidence documents correctly identified
            - Source verification maintained
        """
        # Create relationship with provenance data
        relationship = Mock(spec=Relationship)
        relationship.source_chunks = ["doc1_chunk2", "doc2_chunk3"]
        relationship.id = "rel_001"
        relationship.evidence = "Strong textual evidence"
        
        # Call the method
        result = query_engine._get_relationship_documents(relationship)
        
        # Verify provenance traced to correct documents
        assert set(result) == {"document_001", "document_002"}
        # Verify relationship object unchanged (read-only operation)
        assert relationship.id == "rel_001"
        assert relationship.evidence == "Strong textual evidence"

    def test_get_relationship_documents_cross_document_evidence(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND relationship with evidence spanning multiple documents
        WHEN _get_relationship_documents is called
        THEN expect:
            - All evidence documents identified
            - Cross-document relationship sources captured
            - Complete evidence trail maintained
        """
        # Create relationship with cross-document evidence
        relationship = Mock(spec=Relationship)
        relationship.source_chunks = ["doc1_chunk1", "doc2_chunk4", "doc3_chunk2", "doc5_chunk1"]
        
        # Call the method
        result = query_engine._get_relationship_documents(relationship)
        
        # Verify all evidence documents captured
        assert set(result) == {"document_001", "document_002", "document_003", "document_005"}
        assert len(result) == 4

    def test_get_relationship_documents_knowledge_graph_iteration_order(self, query_engine):
        """
        GIVEN a QueryEngine instance with multiple knowledge graphs
        AND relationship appearing in different graphs
        WHEN _get_relationship_documents is called
        THEN expect:
            - Documents returned in knowledge graph iteration order
            - Consistent ordering across calls
            - Deterministic result ordering
        """
        # Create relationship with chunks from both knowledge graphs
        relationship = Mock(spec=Relationship)
        relationship.source_chunks = ["doc3_chunk1", "doc1_chunk1", "doc5_chunk2"]
        
        # Call the method multiple times
        result1 = query_engine._get_relationship_documents(relationship)
        result2 = query_engine._get_relationship_documents(relationship)
        
        # Verify consistent ordering
        assert result1 == result2
        # Verify all documents found
        assert set(result1) == {"document_001", "document_003", "document_005"}

    def test_get_relationship_documents_performance_with_large_graphs(self, query_engine):
        """
        GIVEN a QueryEngine instance with large knowledge graphs
        AND relationship with many source chunks
        WHEN _get_relationship_documents is called
        THEN expect:
            - Method completes within reasonable time
            - Performance scales appropriately with graph size
            - Memory usage remains controlled
        """
        # Create large knowledge graph
        large_kg = Mock()
        large_documents = {}
        for i in range(100):
            doc_id = f"document_{i:03d}"
            chunks = [f"doc{i}_chunk{j}" for j in range(50)]
            large_documents[doc_id] = {"chunks": chunks}
        large_kg.documents = large_documents
        
        query_engine.graphrag.knowledge_graphs = [large_kg]
        
        # Create relationship with many chunks
        relationship = Mock(spec=Relationship)
        relationship.source_chunks = [f"doc{i}_chunk{i%50}" for i in range(0, 50, 5)]
        
        # Measure performance
        import time
        start_time = time.time()
        result = query_engine._get_relationship_documents(relationship)
        end_time = time.time()
        
        # Verify reasonable performance (should complete in under 1 second)
        assert (end_time - start_time) < 1.0
        # Verify correct number of documents found
        assert len(result) == 10  # Every 5th document from 0 to 45

    def test_get_relationship_documents_chunk_identifier_patterns(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND relationship with various chunk identifier patterns
        AND different document naming conventions
        WHEN _get_relationship_documents is called
        THEN expect:
            - Various chunk identifier formats handled
            - Document extraction robust across naming patterns
            - Flexible pattern matching implemented
        """
        # Extend knowledge graph with different naming patterns
        diverse_kg = Mock()
        diverse_kg.documents = {
            "document_001": {"chunks": ["doc1_chunk1", "doc1_part_a", "doc1_section_1"]},
            "document_ABC": {"chunks": ["docABC_chunk1", "docABC_piece_1"]},
            "doc_special_123": {"chunks": ["doc_special_123_chunk1", "doc_special_123_frag_1"]}
        }
        query_engine.graphrag.knowledge_graphs = [diverse_kg]
        
        # Create relationship with diverse chunk patterns
        relationship = Mock(spec=Relationship)
        relationship.source_chunks = ["doc1_chunk1", "docABC_chunk1", "doc_special_123_chunk1"]
        
        # Call the method
        result = query_engine._get_relationship_documents(relationship)
        
        # Verify flexible pattern matching
        assert set(result) == {"document_001", "document_ABC", "doc_special_123"}

    def test_get_relationship_documents_source_attribution_accuracy(self, query_engine):
        """
        GIVEN a QueryEngine instance with known document-chunk mappings
        AND relationship with specific source chunks
        WHEN _get_relationship_documents is called
        THEN expect:
            - Source attribution 100% accurate
            - Correct document IDs for each chunk
            - No false positives or missed documents
        """
        # Create relationship with known chunks
        relationship = Mock(spec=Relationship)
        relationship.source_chunks = ["doc1_chunk3", "doc2_chunk1", "doc3_chunk2"]
        
        # Call the method
        result = query_engine._get_relationship_documents(relationship)
        
        # Verify 100% accurate attribution
        expected_docs = {"document_001", "document_002", "document_003"}
        assert set(result) == expected_docs
        assert len(result) == 3

    def test_get_relationship_documents_cross_graph_consistency(self, query_engine):
        """
        GIVEN a QueryEngine instance with relationship appearing in multiple graphs
        AND same relationship with different chunk references across graphs
        WHEN _get_relationship_documents is called
        THEN expect:
            - Consistent document identification across graphs
            - All document sources aggregated properly
            - Cross-graph relationship document mapping maintained
        """
        # Create relationship appearing across knowledge graphs
        relationship = Mock(spec=Relationship)
        relationship.source_chunks = ["doc1_chunk1", "doc3_chunk1"]  # From different KGs
        
        # Call the method
        result = query_engine._get_relationship_documents(relationship)
        
        # Verify cross-graph consistency
        assert set(result) == {"document_001", "document_003"}
        assert len(result) == 2

    def test_get_relationship_documents_malformed_chunk_identifiers(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND relationship with malformed or unexpected chunk identifier formats
        WHEN _get_relationship_documents is called
        THEN expect:
            - Malformed identifiers handled gracefully
            - Valid identifiers still processed
            - No method failure due to format issues
        """
        # Create relationship with mix of valid and malformed chunks
        relationship = Mock(spec=Relationship)
        relationship.source_chunks = [
            "doc1_chunk1",      # Valid
            "malformed",        # Invalid
            "doc2_chunk2",      # Valid
            "###invalid###",    # Invalid
            "doc3_chunk1"       # Valid
        ]
        
        # Call the method - should not raise exception
        result = query_engine._get_relationship_documents(relationship)
        
        # Verify valid chunks processed, malformed ignored
        assert set(result) == {"document_001", "document_002", "document_003"}

    def test_get_relationship_documents_none_relationship_input(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND None passed as relationship parameter
        WHEN _get_relationship_documents is called
        THEN expect TypeError to be raised
        """
        # Pass None as relationship
        with pytest.raises(TypeError):
            query_engine._get_relationship_documents(None)

    def test_get_relationship_documents_relationship_id_preservation(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND relationship with specific ID and source chunks
        WHEN _get_relationship_documents is called
        THEN expect:
            - Original relationship ID preserved and not modified
            - Relationship object state unchanged
            - Method is read-only with respect to relationship
        """
        # Create relationship with specific state
        relationship = Mock(spec=Relationship)
        relationship.id = "original_id_123"
        relationship.source_chunks = ["doc1_chunk1", "doc2_chunk2"]
        relationship.confidence = 0.95
        relationship.type = "founded"
        
        # Store original state
        original_id = relationship.id
        original_chunks = relationship.source_chunks.copy()
        original_confidence = relationship.confidence
        original_type = relationship.type
        
        # Call the method
        result = query_engine._get_relationship_documents(relationship)
        
        # Verify relationship state unchanged
        assert relationship.id == original_id
        assert relationship.source_chunks == original_chunks
        assert relationship.confidence == original_confidence
        assert relationship.type == original_type
        
        # Verify method still works
        assert set(result) == {"document_001", "document_002"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])