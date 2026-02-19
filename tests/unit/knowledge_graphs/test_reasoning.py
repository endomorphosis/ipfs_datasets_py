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

    def test_determine_relation_supporting_when_similar(self):
        """
        GIVEN two documents with highly similar content
        WHEN determining relation between them
        THEN relation is SUPPORTING with high confidence
        """
        # GIVEN
        reasoner = CrossDocumentReasoner()
        doc1 = DocumentNode(id="d1", content="Apple was founded in 1976 in California.", source="s1")
        doc2 = DocumentNode(id="d2", content="Apple was founded in 1976 in California.", source="s2")

        # WHEN
        relation, strength = reasoner._determine_relation(
            entity_id="e1",
            source_doc_id="d1",
            target_doc_id="d2",
            documents=[doc1, doc2],
            knowledge_graph=None,
        )

        # THEN
        assert relation == InformationRelationType.SUPPORTING
        assert 0.0 <= strength <= 1.0
        assert strength >= 0.8

    def test_determine_relation_elaborating_when_chronological(self):
        """
        GIVEN two documents where the target is published later
        WHEN determining relation between them
        THEN relation is ELABORATING regardless of similarity
        """
        # GIVEN
        reasoner = CrossDocumentReasoner()
        doc1 = DocumentNode(
            id="d1",
            content="Topic overview.",
            source="s1",
            metadata={"published_date": "2020-01-01"},
        )
        doc2 = DocumentNode(
            id="d2",
            content="Different content entirely.",
            source="s2",
            metadata={"published_date": "2022-01-01"},
        )

        # WHEN
        relation, strength = reasoner._determine_relation(
            entity_id="e1",
            source_doc_id="d1",
            target_doc_id="d2",
            documents=[doc1, doc2],
            knowledge_graph=None,
        )

        # THEN
        assert relation == InformationRelationType.ELABORATING
        assert 0.0 <= strength <= 1.0

    def test_determine_relation_complementary_when_dissimilar(self):
        """
        GIVEN two documents with low similarity and no chronology info
        WHEN determining relation between them
        THEN relation defaults to COMPLEMENTARY
        """
        # GIVEN
        reasoner = CrossDocumentReasoner()
        doc1 = DocumentNode(id="d1", content="Cats are mammals.", source="s1")
        doc2 = DocumentNode(id="d2", content="The stock market fluctuates daily.", source="s2")

        # WHEN
        relation, strength = reasoner._determine_relation(
            entity_id="e1",
            source_doc_id="d1",
            target_doc_id="d2",
            documents=[doc1, doc2],
            knowledge_graph=None,
        )

        # THEN
        assert relation == InformationRelationType.COMPLEMENTARY
        assert 0.0 <= strength <= 1.0


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



class TestConfigurableRelationThresholds:
    """Tests for D1: configurable relation classification thresholds."""

    def test_default_relation_thresholds_stored(self):
        """
        GIVEN: A CrossDocumentReasoner with default parameters
        WHEN: Inspecting threshold attributes
        THEN: The default values are stored on the instance
        """
        # GIVEN / WHEN
        reasoner = CrossDocumentReasoner()

        # THEN
        assert reasoner.relation_similarity_threshold == 0.8
        assert reasoner.relation_supporting_strength == 0.85
        assert reasoner.relation_elaborating_strength == 0.75
        assert reasoner.relation_complementary_strength == 0.7

    def test_custom_relation_thresholds_stored(self):
        """
        GIVEN: A CrossDocumentReasoner with custom threshold parameters
        WHEN: Inspecting threshold attributes
        THEN: The custom values are stored on the instance
        """
        # GIVEN / WHEN
        reasoner = CrossDocumentReasoner(
            relation_similarity_threshold=0.9,
            relation_supporting_strength=0.95,
            relation_elaborating_strength=0.8,
            relation_complementary_strength=0.6,
        )

        # THEN
        assert reasoner.relation_similarity_threshold == 0.9
        assert reasoner.relation_supporting_strength == 0.95
        assert reasoner.relation_elaborating_strength == 0.8
        assert reasoner.relation_complementary_strength == 0.6

    def test_custom_similarity_threshold_changes_classification(self):
        """
        GIVEN: Two documents with moderate similarity (~0.6–0.7)
        WHEN: One reasoner uses default threshold (0.8) and another uses 0.5
        THEN: The stricter reasoner classifies as COMPLEMENTARY, the lenient one as SUPPORTING
        """
        # GIVEN – use documents with distinct but overlapping content
        doc1 = DocumentNode(
            id="d1",
            content="machine learning algorithms data patterns training",
            source="s1",
        )
        doc2 = DocumentNode(
            id="d2",
            content="machine learning models data features prediction",
            source="s2",
        )

        strict_reasoner = CrossDocumentReasoner(relation_similarity_threshold=0.95)
        lenient_reasoner = CrossDocumentReasoner(relation_similarity_threshold=0.01)

        # WHEN
        strict_rel, _ = strict_reasoner._determine_relation(
            entity_id="e", source_doc_id="d1", target_doc_id="d2",
            documents=[doc1, doc2], knowledge_graph=None,
        )
        lenient_rel, _ = lenient_reasoner._determine_relation(
            entity_id="e", source_doc_id="d1", target_doc_id="d2",
            documents=[doc1, doc2], knowledge_graph=None,
        )

        # THEN – strict should fall back to COMPLEMENTARY; lenient should be SUPPORTING
        assert strict_rel == InformationRelationType.COMPLEMENTARY
        assert lenient_rel == InformationRelationType.SUPPORTING

    def test_custom_elaborating_strength_reflected_in_result(self):
        """
        GIVEN: A chronological document pair and a custom elaborating_strength of 0.5
        WHEN: _determine_relation is called
        THEN: The returned strength equals the custom value (0.5)
        """
        # GIVEN
        doc1 = DocumentNode(
            id="d1", content="overview.", source="s1",
            metadata={"published_date": "2020-01-01"},
        )
        doc2 = DocumentNode(
            id="d2", content="follow-up.", source="s2",
            metadata={"published_date": "2023-01-01"},
        )
        reasoner = CrossDocumentReasoner(relation_elaborating_strength=0.5)

        # WHEN
        rel_type, strength = reasoner._determine_relation(
            entity_id="e", source_doc_id="d1", target_doc_id="d2",
            documents=[doc1, doc2], knowledge_graph=None,
        )

        # THEN
        assert rel_type == InformationRelationType.ELABORATING
        assert strength == pytest.approx(0.5)

    def test_custom_complementary_strength_reflected_in_result(self):
        """
        GIVEN: Two dissimilar documents and a custom complementary_strength of 0.3
        WHEN: _determine_relation is called
        THEN: The returned strength equals the custom value (0.3)
        """
        # GIVEN
        doc1 = DocumentNode(id="d1", content="Cats are independent animals.", source="s1")
        doc2 = DocumentNode(id="d2", content="The economy grew by three percent.", source="s2")
        reasoner = CrossDocumentReasoner(relation_complementary_strength=0.3)

        # WHEN
        rel_type, strength = reasoner._determine_relation(
            entity_id="e", source_doc_id="d1", target_doc_id="d2",
            documents=[doc1, doc2], knowledge_graph=None,
        )

        # THEN
        assert rel_type == InformationRelationType.COMPLEMENTARY
        assert strength == pytest.approx(0.3)
