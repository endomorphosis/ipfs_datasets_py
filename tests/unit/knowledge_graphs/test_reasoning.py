"""
Unit tests for cross_document_reasoning module.

This module tests the cross-document reasoning functionality including
entity-mediated connections, information relation analysis, and answer synthesis.

Following GIVEN-WHEN-THEN format as per repository standards.
"""

import pytest
import numpy as np
from ipfs_datasets_py.knowledge_graphs.cross_document_reasoning import (
    InformationRelationType,
    DocumentNode,
    EntityMediatedConnection,
    CrossDocReasoning,
    CrossDocumentReasoner,
)


class TestInformationRelationType:
    """Test InformationRelationType enum."""
    
    def test_enum_values_exist(self):
        """
        GIVEN InformationRelationType enum
        WHEN accessing enum values
        THEN all expected types are defined
        """
        # THEN
        assert InformationRelationType.COMPLEMENTARY.value == "complementary"
        assert InformationRelationType.SUPPORTING.value == "supporting"
        assert InformationRelationType.CONTRADICTING.value == "contradicting"
        assert InformationRelationType.ELABORATING.value == "elaborating"
        assert InformationRelationType.PREREQUISITE.value == "prerequisite"
        assert InformationRelationType.CONSEQUENCE.value == "consequence"
        assert InformationRelationType.ALTERNATIVE.value == "alternative"
        assert InformationRelationType.UNCLEAR.value == "unclear"
    
    def test_enum_membership(self):
        """
        GIVEN InformationRelationType enum
        WHEN checking membership
        THEN can verify relation types
        """
        # WHEN/THEN
        assert InformationRelationType.COMPLEMENTARY in InformationRelationType
        assert InformationRelationType.CONTRADICTING in InformationRelationType


class TestDocumentNode:
    """Test DocumentNode dataclass."""
    
    def test_document_node_creation(self):
        """
        GIVEN document attributes
        WHEN creating DocumentNode
        THEN node is created with correct attributes
        """
        # GIVEN
        doc_id = "doc1"
        content = "Sample document content"
        source = "test_source.txt"
        
        # WHEN
        doc_node = DocumentNode(
            id=doc_id,
            content=content,
            source=source
        )
        
        # THEN
        assert doc_node.id == doc_id
        assert doc_node.content == content
        assert doc_node.source == source
        assert doc_node.metadata == {}
        assert doc_node.vector is None
        assert doc_node.relevance_score == 0.0
        assert doc_node.entities == []
    
    def test_document_node_with_all_fields(self):
        """
        GIVEN complete document attributes
        WHEN creating DocumentNode with all fields
        THEN all attributes are set correctly
        """
        # GIVEN
        doc_id = "doc2"
        content = "Test content"
        source = "test.txt"
        metadata = {"author": "Test Author"}
        vector = np.array([0.1, 0.2, 0.3])
        relevance_score = 0.85
        entities = ["entity1", "entity2"]
        
        # WHEN
        doc_node = DocumentNode(
            id=doc_id,
            content=content,
            source=source,
            metadata=metadata,
            vector=vector,
            relevance_score=relevance_score,
            entities=entities
        )
        
        # THEN
        assert doc_node.metadata == metadata
        assert np.array_equal(doc_node.vector, vector)
        assert doc_node.relevance_score == relevance_score
        assert doc_node.entities == entities


class TestEntityMediatedConnection:
    """Test EntityMediatedConnection dataclass."""
    
    def test_connection_creation(self):
        """
        GIVEN entity and document information
        WHEN creating EntityMediatedConnection
        THEN connection is created correctly
        """
        # GIVEN
        entity_id = "e1"
        entity_name = "Apple Inc."
        entity_type = "organization"
        source_doc_id = "doc1"
        target_doc_id = "doc2"
        relation_type = InformationRelationType.COMPLEMENTARY
        connection_strength = 0.8
        
        # WHEN
        connection = EntityMediatedConnection(
            entity_id=entity_id,
            entity_name=entity_name,
            entity_type=entity_type,
            source_doc_id=source_doc_id,
            target_doc_id=target_doc_id,
            relation_type=relation_type,
            connection_strength=connection_strength
        )
        
        # THEN
        assert connection.entity_id == entity_id
        assert connection.entity_name == entity_name
        assert connection.entity_type == entity_type
        assert connection.source_doc_id == source_doc_id
        assert connection.target_doc_id == target_doc_id
        assert connection.relation_type == relation_type
        assert connection.connection_strength == connection_strength
        assert connection.context == {}
    
    def test_connection_with_context(self):
        """
        GIVEN connection with context
        WHEN creating EntityMediatedConnection
        THEN context is stored correctly
        """
        # GIVEN
        context = {"sentence": "Apple was founded in 1976", "confidence": 0.95}
        
        # WHEN
        connection = EntityMediatedConnection(
            entity_id="e1",
            entity_name="Apple",
            entity_type="organization",
            source_doc_id="doc1",
            target_doc_id="doc2",
            relation_type=InformationRelationType.SUPPORTING,
            connection_strength=0.9,
            context=context
        )
        
        # THEN
        assert connection.context == context


class TestCrossDocReasoning:
    """Test CrossDocReasoning dataclass."""
    
    def test_cross_doc_reasoning_creation(self):
        """
        GIVEN query and reasoning ID
        WHEN creating CrossDocReasoning
        THEN object is created with defaults
        """
        # GIVEN
        reasoning_id = "r1"
        query = "What is Apple Inc.?"
        
        # WHEN
        reasoning = CrossDocReasoning(
            id=reasoning_id,
            query=query
        )
        
        # THEN
        assert reasoning.id == reasoning_id
        assert reasoning.query == query
        assert reasoning.query_embedding is None
        assert reasoning.documents == []
        assert reasoning.entity_connections == []
        assert reasoning.traversal_paths == []
        assert reasoning.reasoning_depth == "moderate"
        assert reasoning.answer is None
        assert reasoning.confidence == 0.0
        assert reasoning.reasoning_trace_id is None
    
    def test_cross_doc_reasoning_with_data(self):
        """
        GIVEN complete reasoning data
        WHEN creating CrossDocReasoning
        THEN all attributes are set
        """
        # GIVEN
        reasoning_id = "r2"
        query = "Test query"
        query_embedding = np.array([0.1, 0.2])
        documents = [DocumentNode(id="d1", content="content", source="source")]
        entity_connections = [
            EntityMediatedConnection(
                entity_id="e1",
                entity_name="Test",
                entity_type="test",
                source_doc_id="d1",
                target_doc_id="d2",
                relation_type=InformationRelationType.COMPLEMENTARY,
                connection_strength=0.7
            )
        ]
        traversal_paths = [["d1", "d2", "d3"]]
        answer = "Test answer"
        confidence = 0.85
        
        # WHEN
        reasoning = CrossDocReasoning(
            id=reasoning_id,
            query=query,
            query_embedding=query_embedding,
            documents=documents,
            entity_connections=entity_connections,
            traversal_paths=traversal_paths,
            reasoning_depth="deep",
            answer=answer,
            confidence=confidence
        )
        
        # THEN
        assert np.array_equal(reasoning.query_embedding, query_embedding)
        assert reasoning.documents == documents
        assert reasoning.entity_connections == entity_connections
        assert reasoning.traversal_paths == traversal_paths
        assert reasoning.reasoning_depth == "deep"
        assert reasoning.answer == answer
        assert reasoning.confidence == confidence


class TestCrossDocumentReasoner:
    """Test CrossDocumentReasoner class."""
    
    def test_reasoner_initialization(self):
        """
        GIVEN no parameters
        WHEN creating CrossDocumentReasoner
        THEN reasoner is initialized with defaults
        """
        # WHEN
        reasoner = CrossDocumentReasoner()
        
        # THEN
        assert reasoner is not None
        assert reasoner.query_optimizer is not None
        assert reasoner.reasoning_tracer is not None
        assert reasoner.llm_service is None
        assert reasoner.min_connection_strength == 0.6
        assert reasoner.max_reasoning_depth == 3
        assert reasoner.enable_contradictions is True
        assert reasoner.entity_match_threshold == 0.85
        assert reasoner.total_queries == 0
        assert reasoner.successful_queries == 0
    
    def test_reasoner_initialization_with_params(self):
        """
        GIVEN custom parameters
        WHEN creating CrossDocumentReasoner
        THEN reasoner is initialized with custom values
        """
        # GIVEN
        min_strength = 0.7
        max_depth = 5
        enable_contra = False
        entity_threshold = 0.9
        
        # WHEN
        reasoner = CrossDocumentReasoner(
            min_connection_strength=min_strength,
            max_reasoning_depth=max_depth,
            enable_contradictions=enable_contra,
            entity_match_threshold=entity_threshold
        )
        
        # THEN
        assert reasoner.min_connection_strength == min_strength
        assert reasoner.max_reasoning_depth == max_depth
        assert reasoner.enable_contradictions == enable_contra
        assert reasoner.entity_match_threshold == entity_threshold
    
    def test_reason_across_documents_method_exists(self):
        """
        GIVEN a CrossDocumentReasoner
        WHEN checking for reason_across_documents method
        THEN method exists and is callable
        """
        # GIVEN
        reasoner = CrossDocumentReasoner()
        
        # THEN
        assert hasattr(reasoner, 'reason_across_documents')
        assert callable(reasoner.reason_across_documents)
    
    def test_reason_across_documents_basic(self):
        """
        GIVEN a simple query
        WHEN calling reason_across_documents with minimal params
        THEN returns result dictionary with expected structure
        """
        # GIVEN
        reasoner = CrossDocumentReasoner()
        query = "What is Python?"
        
        # WHEN
        result = reasoner.reason_across_documents(query=query)
        
        # THEN
        assert isinstance(result, dict)
        assert "answer" in result or "documents" in result
        # Should increment query count
        assert reasoner.total_queries >= 1
    
    def test_reason_across_documents_with_documents(self):
        """
        GIVEN a query and input documents
        WHEN calling reason_across_documents
        THEN processes the documents
        """
        # GIVEN
        reasoner = CrossDocumentReasoner()
        query = "Test query"
        input_docs = [
            {"id": "doc1", "content": "Document 1 content", "metadata": {}},
            {"id": "doc2", "content": "Document 2 content", "metadata": {}}
        ]
        
        # WHEN
        result = reasoner.reason_across_documents(
            query=query,
            input_documents=input_docs,
            reasoning_depth="basic"
        )
        
        # THEN
        assert isinstance(result, dict)
        assert reasoner.total_queries >= 1
    
    def test_statistics_tracking(self):
        """
        GIVEN multiple reasoning calls
        WHEN tracking statistics
        THEN statistics are updated correctly
        """
        # GIVEN
        reasoner = CrossDocumentReasoner()
        initial_count = reasoner.total_queries
        
        # WHEN
        reasoner.reason_across_documents(query="Query 1")
        reasoner.reason_across_documents(query="Query 2")
        
        # THEN
        assert reasoner.total_queries == initial_count + 2
        assert reasoner.total_queries > initial_count


# Integration tests
class TestCrossDocumentReasoningIntegration:
    """Integration tests for cross-document reasoning."""
    
    @pytest.mark.integration
    def test_end_to_end_reasoning(self):
        """
        GIVEN a query and documents
        WHEN performing end-to-end reasoning
        THEN produces coherent result
        """
        # GIVEN
        reasoner = CrossDocumentReasoner()
        query = "What is machine learning?"
        documents = [
            {
                "id": "doc1",
                "content": "Machine learning is a branch of artificial intelligence.",
                "metadata": {"source": "textbook"}
            },
            {
                "id": "doc2",
                "content": "ML algorithms learn patterns from data.",
                "metadata": {"source": "article"}
            }
        ]
        
        # WHEN
        result = reasoner.reason_across_documents(
            query=query,
            input_documents=documents,
            reasoning_depth="moderate"
        )
        
        # THEN
        assert isinstance(result, dict)
        # Result should have key fields
        assert any(key in result for key in ["answer", "documents", "confidence"])
