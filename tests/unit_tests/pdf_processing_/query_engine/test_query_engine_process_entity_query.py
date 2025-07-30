#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine.py
# Auto-generated on 2025-07-07 02:28:56"

import pytest
import os
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, List, Any, Optional
from dataclasses import dataclass

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

# Check if the modules's imports are accessible:
import asyncio
import logging
import json
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
from datetime import datetime
import re

from sklearn.metrics.pairwise import cosine_similarity
from sentence_transformers import SentenceTransformer

from ipfs_datasets_py.ipld import IPLDStorage
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator, Entity, Relationship

# Mock data classes for testing
@dataclass
class MockQueryResult:
    id: str
    type: str
    content: str
    relevance_score: float
    source_document: str
    source_chunks: List[str]
    metadata: Dict[str, Any]

@dataclass
class MockEntity:
    id: str
    name: str
    type: str
    description: str
    confidence: float
    properties: Dict[str, Any]
    source_chunks: List[str]

class TestQueryEngineProcessEntityQuery:
    """Test QueryEngine._process_entity_query method for entity-focused query processing."""

    @pytest.fixture
    def mock_graphrag_integrator(self):
        """Create a mock GraphRAG integrator for testing."""
        mock = Mock(spec=GraphRAGIntegrator)
        
        # Create sample entities using actual Entity class from the module
        from ipfs_datasets_py.pdf_processing.graphrag_integrator import Entity
        
        mock_entities = [
            Entity(
                id="entity_001",
                name="Bill Gates",
                type="Person",
                description="Co-founder of Microsoft Corporation",
                confidence=0.95,
                properties={"occupation": "Business magnate", "company": "Microsoft"},
                source_chunks=["doc_001_chunk_001"]
            ),
            Entity(
                id="entity_002", 
                name="Microsoft",
                type="Organization",
                description="Technology company founded by Bill Gates and Paul Allen",
                confidence=0.98,
                properties={"industry": "Technology", "founded": "1975"},
                source_chunks=["doc_001_chunk_002", "doc_002_chunk_001"]
            ),
            Entity(
                id="entity_003",
                name="William Gates",
                type="Person", 
                description="Alternative name for Bill Gates",
                confidence=0.85,
                properties={"full_name": "William Henry Gates III"},
                source_chunks=["doc_001_chunk_003"]
            ),
            Entity(
                id="entity_004",
                name="Apple",
                type="Organization",
                description="Technology company",
                confidence=0.92,
                properties={"industry": "Technology", "founded": "1976"},
                source_chunks=["doc_002_chunk_002"]
            ),
            Entity(
                id="entity_005",
                name="Steve Jobs",
                type="Person",
                description="Co-founder of Apple Inc.",
                confidence=0.70,  # Low confidence entity
                properties={"occupation": "Entrepreneur"},
                source_chunks=["doc_002_chunk_003"]
            )
        ]
        
        # Set up global_entities as expected by the actual implementation
        mock.global_entities = {entity.id: entity for entity in mock_entities}
        
        # Mock knowledge graphs for document filtering
        mock_kg1 = Mock()
        mock_kg1.document_id = "doc_001"
        mock_kg1.chunks = [Mock(chunk_id="doc_001_chunk_001"), Mock(chunk_id="doc_001_chunk_002"), Mock(chunk_id="doc_001_chunk_003")]
        
        mock_kg2 = Mock()
        mock_kg2.document_id = "doc_002"
        mock_kg2.chunks = [Mock(chunk_id="doc_002_chunk_001"), Mock(chunk_id="doc_002_chunk_002"), Mock(chunk_id="doc_002_chunk_003")]
        
        mock.knowledge_graphs = {"doc_001": mock_kg1, "doc_002": mock_kg2}
        
        return mock

    @pytest.fixture
    def mock_storage(self):
        """Create a mock IPLD storage for testing."""
        return Mock(spec=IPLDStorage)

    @pytest.fixture
    def query_engine(self, mock_graphrag_integrator, mock_storage):
        """Create QueryEngine instance with mocked dependencies."""
        with patch('ipfs_datasets_py.pdf_processing.query_engine.SentenceTransformer'):
            engine = QueryEngine(
                graphrag_integrator=mock_graphrag_integrator,
                storage=mock_storage,
                embedding_model="test-model"
            )
            # Mock the _get_entity_documents method
            engine._get_entity_documents = Mock(return_value=["doc_001"])
            return engine

    @pytest.mark.asyncio
    async def test_process_entity_query_exact_name_match(self, query_engine):
        """
        GIVEN a QueryEngine instance with entities in knowledge graph
        AND normalized query "bill gates"
        AND entity with exact name match exists
        WHEN _process_entity_query is called
        THEN expect:
            - Entity with exact name match gets highest relevance score (1.0)
            - QueryResult returned with entity information
            - Source document attribution included
        """
        # Execute
        results = await query_engine._process_entity_query("bill gates", None, 10)
        
        # Verify
        assert len(results) > 0, "Should return at least one result for exact match"
        
        # Find the exact match result
        exact_match = next((r for r in results if "Bill Gates" in r.content), None)
        assert exact_match is not None, "Should find exact name match"
        assert exact_match.relevance_score == 1.0, "Exact match should have relevance score of 1.0"
        assert exact_match.type == "entity", "Result type should be 'entity'"
        assert exact_match.id == "entity_001", "Should return correct entity ID"
        assert "Person" in exact_match.content, "Should include entity type in content"
        assert exact_match.source_document == "doc_001", "Should include source document"
        assert len(exact_match.source_chunks) > 0, "Should include source chunks"
        
        # Verify metadata
        assert "entity_name" in exact_match.metadata
        assert "entity_type" in exact_match.metadata
        assert "confidence" in exact_match.metadata
        assert exact_match.metadata["entity_name"] == "Bill Gates"

    @pytest.mark.asyncio
    async def test_process_entity_query_fuzzy_name_matching(self, query_engine):
        """
        GIVEN a QueryEngine instance with entities
        AND normalized query "william gates" (fuzzy match for "Bill Gates")
        WHEN _process_entity_query is called
        THEN expect:
            - Fuzzy matching applied to entity names
            - Partial matches scored appropriately (< 1.0 but > 0.5)
            - Results ordered by relevance score
        """
        # Execute
        results = await query_engine._process_entity_query("william gates", None, 10)
        
        # Verify
        assert len(results) > 0, "Should return results for fuzzy matching"
        
        # Check for fuzzy matches
        william_gates_match = next((r for r in results if "William Gates" in r.content), None)
        bill_gates_match = next((r for r in results if "Bill Gates" in r.content), None)
        
        # Should find both variations
        assert william_gates_match is not None, "Should find William Gates"
        assert bill_gates_match is not None, "Should find Bill Gates as fuzzy match"
        
        # Check scoring
        assert 0.1 < william_gates_match.relevance_score <= 1.0, "Fuzzy match should have appropriate score"
        assert 0.1 < bill_gates_match.relevance_score <= 1.0, "Related entity should have appropriate score"
        
        # Results should be ordered by relevance
        for i in range(len(results) - 1):
            assert results[i].relevance_score >= results[i + 1].relevance_score, "Results should be ordered by relevance"

    @pytest.mark.asyncio
    async def test_process_entity_query_description_matching(self, query_engine):
        """
        GIVEN a QueryEngine instance with entities
        AND normalized query "ceo microsoft" (matches entity description)
        WHEN _process_entity_query is called
        THEN expect:
            - Description content analyzed for matches
            - Entities with relevant descriptions scored appropriately
            - Combined name and description scoring
        """
        # Execute
        results = await query_engine._process_entity_query("ceo microsoft", None, 10)
        
        # Verify
        assert len(results) > 0, "Should return results for description matching"
        
        # Should find Bill Gates and Microsoft based on description content
        bill_gates_result = next((r for r in results if "Bill Gates" in r.content), None)
        microsoft_result = next((r for r in results if "Microsoft" in r.content and "Organization" in r.content), None)
        
        assert bill_gates_result is not None, "Should find Bill Gates based on Microsoft description"
        assert microsoft_result is not None, "Should find Microsoft organization"
        
        # Both should have reasonable relevance scores
        assert bill_gates_result.relevance_score > 0.3, "Description match should have reasonable score"
        assert microsoft_result.relevance_score > 0.3, "Description match should have reasonable score"

    @pytest.mark.asyncio
    async def test_process_entity_query_entity_type_filter(self, query_engine):
        """
        GIVEN a QueryEngine instance with mixed entity types
        AND normalized query "technology companies"
        AND filters {"entity_type": "Organization"}
        WHEN _process_entity_query is called
        THEN expect:
            - Only Organization entities returned
            - Person entities filtered out
            - Filter applied before scoring
        """
        # Execute
        filters = {"entity_type": "Organization"}
        results = await query_engine._process_entity_query("technology companies", filters, 10)
        
        # Verify
        assert len(results) > 0, "Should return organization results"
        
        # All results should be organizations
        for result in results:
            assert "Organization" in result.content or result.metadata.get("entity_type") == "Organization", \
                "All results should be organizations when filtered"
        
        # Should not contain any Person entities
        person_results = [r for r in results if "Person" in r.content or r.metadata.get("entity_type") == "Person"]
        assert len(person_results) == 0, "Should not return Person entities when filtered for Organization"
        
        # Should find Microsoft and Apple
        entity_names = [r.metadata.get("entity_name", "") for r in results]
        assert "Microsoft" in entity_names, "Should find Microsoft"
        assert "Apple" in entity_names, "Should find Apple"

    @pytest.mark.asyncio
    async def test_process_entity_query_document_id_filter(self, query_engine):
        """
        GIVEN a QueryEngine instance with entities across multiple documents
        AND normalized query "founders"
        AND filters {"document_id": "doc_001"}
        WHEN _process_entity_query is called
        THEN expect:
            - Only entities appearing in doc_001 returned
            - Entities from other documents filtered out
            - _get_entity_documents used for filtering
        """
        # Setup mock to return different documents for different entities
        def mock_get_entity_documents(entity):
            doc_mapping = {
                "entity_001": ["doc_001"],
                "entity_002": ["doc_001", "doc_002"],
                "entity_003": ["doc_001"],
                "entity_004": ["doc_002"],
                "entity_005": ["doc_002"]
            }
            return doc_mapping.get(entity.id, ["unknown"])
        
        query_engine._get_entity_documents = Mock(side_effect=mock_get_entity_documents)
        
        # Execute
        filters = {"document_id": "doc_001"}
        results = await query_engine._process_entity_query("founders", filters, 10)
        
        # Verify
        assert len(results) > 0, "Should return results from doc_001"
        
        # All results should be from doc_001
        for result in results:
            assert result.source_document in ["doc_001", "multiple"], \
                f"Result {result.id} should be from doc_001, got {result.source_document}"
        
        # Should not include entities only in doc_002
        entity_ids = [r.id for r in results]
        assert "entity_004" not in entity_ids, "Should not include Apple (doc_002 only)"
        assert "entity_005" not in entity_ids, "Should not include Steve Jobs (doc_002 only)"

    @pytest.mark.asyncio
    async def test_process_entity_query_confidence_filter(self, query_engine):
        """
        GIVEN a QueryEngine instance with entities having confidence scores
        AND normalized query "companies"
        AND filters {"confidence": 0.8}
        WHEN _process_entity_query is called
        THEN expect:
            - Only entities with confidence >= 0.8 returned
            - Low confidence entities filtered out
        """
        # Execute
        filters = {"confidence": 0.8}
        results = await query_engine._process_entity_query("companies", filters, 10)
        
        # Verify
        assert len(results) > 0, "Should return high-confidence results"
        
        # All results should have confidence >= 0.8
        for result in results:
            confidence = result.metadata.get("confidence", 0.0)
            assert confidence >= 0.8, f"Result {result.id} should have confidence >= 0.8, got {confidence}"
        
        # Should not include Steve Jobs (confidence 0.70)
        entity_names = [r.metadata.get("entity_name", "") for r in results]
        assert "Steve Jobs" not in entity_names, "Should not include low confidence entity"
        
        # Should include high confidence entities
        assert "Bill Gates" in entity_names or "Microsoft" in entity_names, "Should include high confidence entities"

    @pytest.mark.asyncio
    async def test_process_entity_query_max_results_limiting(self, query_engine):
        """
        GIVEN a QueryEngine instance with many matching entities
        AND normalized query "companies"
        AND max_results = 5
        WHEN _process_entity_query is called
        THEN expect:
            - Exactly 5 results returned (or fewer if less available)
            - Results are top-scored entities
            - Results ordered by relevance score descending
        """
        # Execute with small limit
        results = await query_engine._process_entity_query("technology", None, 2)
        
        # Verify
        assert len(results) <= 2, "Should respect max_results limit"
        
        # Results should be ordered by relevance score
        for i in range(len(results) - 1):
            assert results[i].relevance_score >= results[i + 1].relevance_score, \
                "Results should be ordered by relevance score descending"
        
        # Test with larger limit
        all_results = await query_engine._process_entity_query("technology", None, 100)
        limited_results = await query_engine._process_entity_query("technology", None, 3)
        
        assert len(limited_results) <= 3, "Should respect smaller limit"
        assert len(limited_results) <= len(all_results), "Limited results should be subset"

    @pytest.mark.asyncio
    async def test_process_entity_query_no_matches_found(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND normalized query "nonexistent entity"
        WHEN _process_entity_query is called
        THEN expect:
            - Empty list returned
            - No exceptions raised
            - Method completes successfully
        """
        # Execute
        results = await query_engine._process_entity_query("nonexistent entity xyz", None, 10)
        
        # Verify
        assert isinstance(results, list), "Should return a list"
        assert len(results) == 0, "Should return empty list for no matches"

    @pytest.mark.asyncio
    async def test_process_entity_query_invalid_max_results(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND normalized query "test"
        AND max_results = -5 or 0
        WHEN _process_entity_query is called
        THEN expect ValueError to be raised
        """
        # Test negative max_results
        with pytest.raises(ValueError, match="max_results must be positive"):
            await query_engine._process_entity_query("test", None, -5)
        
        # Test zero max_results  
        with pytest.raises(ValueError, match="max_results must be positive"):
            await query_engine._process_entity_query("test", None, 0)

    @pytest.mark.asyncio
    async def test_process_entity_query_invalid_filters_type(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND normalized query "test"
        AND filters as list instead of dict
        WHEN _process_entity_query is called
        THEN expect TypeError to be raised
        """
        # Test with list instead of dict
        with pytest.raises(TypeError, match="filters must be a dictionary"):
            await query_engine._process_entity_query("test", ["invalid", "filters"], 10)
        
        # Test with string instead of dict
        with pytest.raises(TypeError, match="filters must be a dictionary"):
            await query_engine._process_entity_query("test", "invalid_filters", 10)

    @pytest.mark.asyncio
    async def test_process_entity_query_corrupted_graphrag_data(self, query_engine):
        """
        GIVEN a QueryEngine instance with corrupted GraphRAG data
        AND normalized query "test"
        WHEN _process_entity_query is called
        THEN expect RuntimeError to be raised
        """
        # Mock corrupted knowledge graphs
        query_engine.graphrag.global_entities = None
        
        with pytest.raises(RuntimeError, match="GraphRAG data is corrupted or inaccessible"):
            await query_engine._process_entity_query("test", None, 10)

    @pytest.mark.asyncio
    async def test_process_entity_query_result_structure_validation(self, query_engine):
        """
        GIVEN a QueryEngine instance with valid entities
        AND normalized query "bill gates"
        WHEN _process_entity_query is called
        THEN expect each QueryResult to have:
            - id: str (entity ID)
            - type: "entity"
            - content: str (formatted entity information)
            - relevance_score: float (0.0-1.0)
            - source_document: str
            - source_chunks: List[str]
            - metadata: Dict with entity details
        """
        # Execute
        results = await query_engine._process_entity_query("bill gates", None, 10)
        
        # Verify structure
        assert len(results) > 0, "Should return results"
        
        for result in results:
            # Check required attributes exist and have correct types
            assert hasattr(result, 'id'), "Result should have id attribute"
            assert isinstance(result.id, str), "id should be string"
            
            assert hasattr(result, 'type'), "Result should have type attribute"
            assert result.type == "entity", "type should be 'entity'"
            
            assert hasattr(result, 'content'), "Result should have content attribute"
            assert isinstance(result.content, str), "content should be string"
            assert len(result.content) > 0, "content should not be empty"
            
            assert hasattr(result, 'relevance_score'), "Result should have relevance_score attribute"
            assert isinstance(result.relevance_score, float), "relevance_score should be float"
            assert 0.0 <= result.relevance_score <= 1.0, "relevance_score should be between 0.0 and 1.0"
            
            assert hasattr(result, 'source_document'), "Result should have source_document attribute"
            assert isinstance(result.source_document, str), "source_document should be string"
            
            assert hasattr(result, 'source_chunks'), "Result should have source_chunks attribute"
            assert isinstance(result.source_chunks, list), "source_chunks should be list"
            
            assert hasattr(result, 'metadata'), "Result should have metadata attribute"
            assert isinstance(result.metadata, dict), "metadata should be dict"
            
            # Check required metadata fields
            required_metadata = ['entity_name', 'entity_type', 'confidence', 'properties']
            for field in required_metadata:
                assert field in result.metadata, f"metadata should contain {field}"

    @pytest.mark.asyncio
    async def test_process_entity_query_relevance_score_normalization(self, query_engine):
        """
        GIVEN a QueryEngine instance with entities
        AND normalized query with varying match quality
        WHEN _process_entity_query is called
        THEN expect:
            - All relevance scores between 0.0 and 1.0
            - Scores properly normalized across different matching types
            - Higher scores for better matches
        """
        # Execute
        results = await query_engine._process_entity_query("gates microsoft", None, 10)
        
        # Verify score normalization
        assert len(results) > 0, "Should return results"
        
        for result in results:
            assert 0.0 <= result.relevance_score <= 1.0, \
                f"Relevance score {result.relevance_score} should be between 0.0 and 1.0"
        
        # Verify scoring logic - exact matches should score higher
        bill_gates_result = next((r for r in results if "Bill Gates" in r.content), None)
        if bill_gates_result:
            # Should have high score for name match
            assert bill_gates_result.relevance_score > 0.5, "Name match should have high relevance"

    @pytest.mark.asyncio
    async def test_process_entity_query_source_attribution(self, query_engine):
        """
        GIVEN a QueryEngine instance with entities
        AND normalized query "founders"
        WHEN _process_entity_query is called
        THEN expect:
            - source_document field populated correctly
            - source_chunks field contains relevant chunk IDs
            - _get_entity_documents called for each entity
            - Traceability maintained to original content
        """
        # Execute
        results = await query_engine._process_entity_query("founders", None, 10)
        
        # Verify source attribution
        assert len(results) > 0, "Should return results"
        
        for result in results:
            # source_document should be populated
            assert result.source_document is not None, "source_document should not be None"
            assert len(result.source_document) > 0, "source_document should not be empty"
            
            # source_chunks should contain chunk IDs
            assert isinstance(result.source_chunks, list), "source_chunks should be list"
            # May be empty for some entity types, but should be list
            
        # Verify _get_entity_documents was called
        assert query_engine._get_entity_documents.called, "_get_entity_documents should have been called"

    @pytest.mark.asyncio
    async def test_process_entity_query_metadata_completeness(self, query_engine):
        """
        GIVEN a QueryEngine instance with entities
        AND normalized query "companies"
        WHEN _process_entity_query is called
        THEN expect QueryResult.metadata to contain:
            - entity_name: str
            - entity_type: str
            - confidence: float
            - properties: Dict (entity properties)
        """
        # Execute
        results = await query_engine._process_entity_query("companies", None, 10)
        
        # Verify metadata completeness
        assert len(results) > 0, "Should return results"
        
        for result in results:
            metadata = result.metadata
            
            # Check required metadata fields
            assert "entity_name" in metadata, "metadata should contain entity_name"
            assert isinstance(metadata["entity_name"], str), "entity_name should be string"
            
            assert "entity_type" in metadata, "metadata should contain entity_type"
            assert isinstance(metadata["entity_type"], str), "entity_type should be string"
            
            assert "confidence" in metadata, "metadata should contain confidence"
            assert isinstance(metadata["confidence"], (int, float)), "confidence should be numeric"
            
            assert "properties" in metadata, "metadata should contain properties"
            assert isinstance(metadata["properties"], dict), "properties should be dict"

    @pytest.mark.asyncio
    async def test_process_entity_query_combined_scoring_algorithm(self, query_engine):
        """
        GIVEN a QueryEngine instance with entities
        AND normalized query that matches both name and description
        WHEN _process_entity_query is called
        THEN expect:
            - Name similarity weighted appropriately
            - Description matching weighted appropriately
            - Exact matches prioritized over partial matches
            - Combined score reflects both factors
        """
        # Execute with query that should match both name and description
        results = await query_engine._process_entity_query("bill gates microsoft founder", None, 10)
        
        # Verify combined scoring
        assert len(results) > 0, "Should return results"
        
        # Find Bill Gates result - should score very high due to name + description match
        bill_gates_result = next((r for r in results if "Bill Gates" in r.content), None)
        microsoft_result = next((r for r in results if "Microsoft" in r.content and "Organization" in r.content), None)
        
        if bill_gates_result and microsoft_result:
            # Both should have high scores due to query matching both name and context
            assert bill_gates_result.relevance_score > 0.6, "Bill Gates should score high (name + context match)"
            assert microsoft_result.relevance_score > 0.6, "Microsoft should score high (name + context match)"

    @pytest.mark.asyncio
    async def test_process_entity_query_case_insensitive_matching(self, query_engine):
        """
        GIVEN a QueryEngine instance with entities
        AND normalized query should already be lowercase
        WHEN _process_entity_query is called
        THEN expect:
            - Case-insensitive matching against entity names
            - Consistent results regardless of original case
        """
        # Execute with different cases (though query should be normalized)
        results_lower = await query_engine._process_entity_query("bill gates", None, 10)
        results_mixed = await query_engine._process_entity_query("BILL GATES", None, 10)
        
        # Both should return results
        assert len(results_lower) > 0, "Lowercase query should return results"
        assert len(results_mixed) > 0, "Uppercase query should return results"
        
        # Should find Bill Gates in both cases
        lower_names = [r.metadata.get("entity_name", "") for r in results_lower]
        mixed_names = [r.metadata.get("entity_name", "") for r in results_mixed]
        
        assert "Bill Gates" in lower_names, "Should find Bill Gates with lowercase query"
        assert "Bill Gates" in mixed_names, "Should find Bill Gates with uppercase query"

    @pytest.mark.asyncio
    async def test_process_entity_query_multiple_knowledge_graphs(self, query_engine):
        """
        GIVEN a QueryEngine instance with multiple knowledge graphs
        AND normalized query "tech companies"
        WHEN _process_entity_query is called
        THEN expect:
            - All knowledge graphs searched
            - Results aggregated across graphs
            - No duplicate entities in results
        """
        # Execute
        results = await query_engine._process_entity_query("tech companies", None, 10)
        
        # Verify results from multiple graphs
        assert len(results) > 0, "Should return results"
        
        # Should find entities from both knowledge graphs
        entity_names = [r.metadata.get("entity_name", "") for r in results]
        
        # Microsoft is in first graph, Apple is in second graph
        microsoft_found = "Microsoft" in entity_names
        apple_found = "Apple" in entity_names
        
        assert microsoft_found or apple_found, "Should find entities from at least one knowledge graph"
        
        # Check for no duplicates
        entity_ids = [r.id for r in results]
        unique_ids = set(entity_ids)
        assert len(entity_ids) == len(unique_ids), "Should not have duplicate entity IDs"

    @pytest.mark.asyncio
    async def test_process_entity_query_entity_properties_matching(self, query_engine):
        """
        GIVEN a QueryEngine instance with entities having properties
        AND normalized query matching entity properties
        WHEN _process_entity_query is called
        THEN expect:
            - Entity properties considered in matching
            - Relevant property matches scored appropriately
            - Properties included in result metadata
        """
        # Execute with query that matches entity properties
        results = await query_engine._process_entity_query("business magnate", None, 10)
        
        # Verify property matching
        assert len(results) > 0, "Should return results for property matching"
        
        # Should find Bill Gates based on occupation property
        bill_gates_result = next((r for r in results if "Bill Gates" in r.content), None)
        
        if bill_gates_result:
            # Should have properties in metadata
            assert "properties" in bill_gates_result.metadata, "Should include properties in metadata"
            properties = bill_gates_result.metadata["properties"]
            assert isinstance(properties, dict), "Properties should be dict"
            
            # Should have reasonable relevance score for property match
            assert bill_gates_result.relevance_score > 0.2, "Property match should have reasonable score"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])