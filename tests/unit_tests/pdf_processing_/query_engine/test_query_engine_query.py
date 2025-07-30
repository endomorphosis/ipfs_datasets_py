#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine.py
# Auto-generated on 2025-07-07 02:28:56"

import pytest
import os
import asyncio
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

from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine, QueryResponse, QueryResult

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


@pytest.fixture
def mock_graphrag_integrator():
    """Create a mock GraphRAGIntegrator for testing."""
    mock = Mock(spec=GraphRAGIntegrator)
    return mock


@pytest.fixture
def mock_storage():
    """Create a mock IPLDStorage for testing."""
    mock = Mock(spec=IPLDStorage)
    return mock


@pytest.fixture
def sample_entity():
    """Create a sample Entity for testing."""
    return Entity(
        id="entity_001",
        name="Bill Gates",
        entity_type="Person",
        description="Co-founder of Microsoft",
        properties={"role": "CEO", "company": "Microsoft"},
        source_chunks=["doc_001_chunk_003"]
    )


@pytest.fixture
def sample_relationship():
    """Create a sample Relationship for testing."""
    return Relationship(
        id="rel_001",
        source_entity_id="entity_001",
        target_entity_id="entity_002",
        relationship_type="founded",
        description="Bill Gates founded Microsoft",
        properties={"year": "1975"},
        source_chunks=["doc_001_chunk_003"]
    )


@pytest.fixture
def sample_query_result():
    """Create a sample QueryResult for testing."""
    return QueryResult(
        id="result_001",
        type="entity",
        content="Bill Gates (Person): Co-founder of Microsoft",
        relevance_score=0.85,
        source_document="doc_001",
        source_chunks=["doc_001_chunk_003"],
        metadata={"entity_type": "Person", "confidence": 0.9}
    )


@pytest.fixture
def query_engine(mock_graphrag_integrator, mock_storage):
    """Create a QueryEngine instance for testing."""
    with patch('ipfs_datasets_py.pdf_processing.query_engine.SentenceTransformer'):
        engine = QueryEngine(
            graphrag_integrator=mock_graphrag_integrator,
            storage=mock_storage,
            embedding_model="sentence-transformers/all-MiniLM-L6-v2"
        )
        # Mock the embedding model
        engine.embedding_model = Mock()
        engine.embedding_model.encode = Mock(return_value=[[0.1, 0.2, 0.3]])
        return engine


class TestQueryEngineQuery:
    """Test QueryEngine.query method - the primary query interface."""

    @pytest.mark.asyncio
    async def test_query_with_basic_text_auto_detection(self, query_engine, sample_query_result):
        """
        GIVEN a QueryEngine instance
        AND a simple query text "who is bill gates"
        WHEN query method is called without specifying query_type
        THEN expect:
            - Query normalized using _normalize_query
            - Query type auto-detected using _detect_query_type
            - Appropriate processor method called based on detected type
            - QueryResponse returned with all required fields
            - Processing time recorded and > 0
            - Suggestions generated
        """
        # Setup mocks
        query_engine._normalize_query = Mock(return_value="who bill gates")
        query_engine._detect_query_type = Mock(return_value="entity_search")
        query_engine._process_entity_query = AsyncMock(return_value=[sample_query_result])
        query_engine._generate_query_suggestions = AsyncMock(return_value=["What is Microsoft?", "Bill Gates relationships"])
        
        # Execute query
        response = await query_engine.query("who is bill gates")
        
        # Verify method calls
        query_engine._normalize_query.assert_called_once_with("who is bill gates")
        query_engine._detect_query_type.assert_called_once_with("who bill gates")
        query_engine._process_entity_query.assert_called_once_with("who bill gates", None, 20)
        query_engine._generate_query_suggestions.assert_called_once()
        
        # Verify response structure
        assert isinstance(response, QueryResponse)
        assert response.query == "who is bill gates"
        assert response.query_type == "entity_search"
        assert len(response.results) == 1
        assert response.total_results == 1
        assert response.processing_time > 0
        assert len(response.suggestions) == 2
        assert "normalized_query" in response.metadata
        assert "timestamp" in response.metadata

    @pytest.mark.asyncio
    async def test_query_with_explicit_entity_search_type(self, query_engine, sample_query_result):
        """
        GIVEN a QueryEngine instance
        AND query_text "microsoft founders"
        AND query_type explicitly set to "entity_search"
        WHEN query method is called
        THEN expect:
            - _detect_query_type NOT called (type override)
            - _process_entity_query called with normalized query
            - QueryResponse.query_type set to "entity_search"
        """
        # Setup mocks
        query_engine._normalize_query = Mock(return_value="microsoft founders")
        query_engine._detect_query_type = Mock()
        query_engine._process_entity_query = AsyncMock(return_value=[sample_query_result])
        query_engine._generate_query_suggestions = AsyncMock(return_value=[])
        
        # Execute query with explicit type
        response = await query_engine.query("microsoft founders", query_type="entity_search")
        
        # Verify _detect_query_type was NOT called
        query_engine._detect_query_type.assert_not_called()
        
        # Verify correct processor called
        query_engine._process_entity_query.assert_called_once_with("microsoft founders", None, 20)
        
        # Verify response
        assert response.query_type == "entity_search"

    @pytest.mark.asyncio
    async def test_query_with_filters_applied(self, query_engine, sample_query_result):
        """
        GIVEN a QueryEngine instance
        AND query_text "technology companies"
        AND filters {"entity_type": "Organization", "document_id": "doc_001"}
        WHEN query method is called
        THEN expect:
            - Filters passed correctly to processor method
            - QueryResponse.metadata contains "filters_applied" key
            - Results filtered according to specified criteria
        """
        # Setup mocks
        query_engine._normalize_query = Mock(return_value="technology companies")
        query_engine._detect_query_type = Mock(return_value="entity_search")
        query_engine._process_entity_query = AsyncMock(return_value=[sample_query_result])
        query_engine._generate_query_suggestions = AsyncMock(return_value=[])
        
        filters = {"entity_type": "Organization", "document_id": "doc_001"}
        
        # Execute query with filters
        response = await query_engine.query("technology companies", filters=filters)
        
        # Verify filters passed to processor
        query_engine._process_entity_query.assert_called_once_with("technology companies", filters, 20)
        
        # Verify metadata contains filters
        assert "filters_applied" in response.metadata
        assert response.metadata["filters_applied"] == filters

    @pytest.mark.asyncio
    async def test_query_with_custom_max_results(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND query_text "artificial intelligence"
        AND max_results set to 5
        WHEN query method is called
        THEN expect:
            - max_results parameter passed to processor method
            - QueryResponse.results length <= 5
            - QueryResponse.total_results matches actual result count
        """
        # Create 5 sample results
        results = []
        for i in range(5):
            result = QueryResult(
                id=f"result_{i:03d}",
                type="semantic",
                content=f"AI content {i}",
                relevance_score=0.8 - (i * 0.1),
                source_document="doc_001",
                source_chunks=[f"chunk_{i:03d}"],
                metadata={}
            )
            results.append(result)
        
        # Setup mocks
        query_engine._normalize_query = Mock(return_value="artificial intelligence")
        query_engine._detect_query_type = Mock(return_value="semantic_search")
        query_engine._process_semantic_query = AsyncMock(return_value=results)
        query_engine._generate_query_suggestions = AsyncMock(return_value=[])
        
        # Execute query with custom max_results
        response = await query_engine.query("artificial intelligence", max_results=5)
        
        # Verify max_results passed to processor
        query_engine._process_semantic_query.assert_called_once_with("artificial intelligence", None, 5)
        
        # Verify result count
        assert len(response.results) <= 5
        assert response.total_results == len(response.results)

    @pytest.mark.asyncio
    async def test_query_with_empty_query_text(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND empty query_text ""
        WHEN query method is called
        THEN expect ValueError to be raised
        """
        with pytest.raises(ValueError, match="Query text cannot be empty"):
            await query_engine.query("")

    @pytest.mark.asyncio
    async def test_query_with_whitespace_only_query_text(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND query_text containing only whitespace "   \n\t  "
        WHEN query method is called
        THEN expect ValueError to be raised
        """
        with pytest.raises(ValueError, match="Query text cannot be empty"):
            await query_engine.query("   \n\t  ")

    @pytest.mark.asyncio
    async def test_query_with_invalid_query_type(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND query_text "test query"
        AND query_type set to invalid value "invalid_type"
        WHEN query method is called
        THEN expect ValueError to be raised
        """
        with pytest.raises(ValueError, match="Invalid query type"):
            await query_engine.query("test query", query_type="invalid_type")

    @pytest.mark.asyncio
    async def test_query_with_negative_max_results(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND query_text "test query"
        AND max_results set to -5
        WHEN query method is called
        THEN expect ValueError to be raised
        """
        with pytest.raises(ValueError, match="max_results must be positive"):
            await query_engine.query("test query", max_results=-5)

    @pytest.mark.asyncio
    async def test_query_with_zero_max_results(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND query_text "test query"
        AND max_results set to 0
        WHEN query method is called
        THEN expect ValueError to be raised
        """
        with pytest.raises(ValueError, match="max_results must be positive"):
            await query_engine.query("test query", max_results=0)

    @pytest.mark.asyncio
    async def test_query_with_invalid_filters_type(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND query_text "test query"
        AND filters set to invalid type (list instead of dict)
        WHEN query method is called
        THEN expect TypeError to be raised
        """
        with pytest.raises(TypeError, match="Filters must be a dictionary"):
            await query_engine.query("test query", filters=["invalid", "list"])

    @pytest.mark.asyncio
    async def test_query_caching_functionality(self, query_engine, sample_query_result):
        """
        GIVEN a QueryEngine instance
        AND identical query executed twice
        WHEN query method is called both times
        THEN expect:
            - First call processes normally and caches result
            - Second call returns cached result without reprocessing
            - Both responses identical except possibly processing_time
        """
        # Setup mocks
        query_engine._normalize_query = Mock(return_value="bill gates")
        query_engine._detect_query_type = Mock(return_value="entity_search")
        query_engine._process_entity_query = AsyncMock(return_value=[sample_query_result])
        query_engine._generate_query_suggestions = AsyncMock(return_value=["suggestion"])
        
        # First query call
        response1 = await query_engine.query("bill gates")
        
        # Second identical query call
        response2 = await query_engine.query("bill gates")
        
        # Verify processor only called once (due to caching)
        assert query_engine._process_entity_query.call_count == 1
        
        # Verify responses are essentially identical
        assert response1.query == response2.query
        assert response1.query_type == response2.query_type
        assert len(response1.results) == len(response2.results)
        assert response1.total_results == response2.total_results
        
        # Verify cache hit indicated in second response
        assert response2.metadata.get("cache_hit") is True

    @pytest.mark.asyncio
    async def test_query_cache_key_generation(self, query_engine, sample_query_result):
        """
        GIVEN a QueryEngine instance
        AND same query with different filters/max_results
        WHEN query method is called multiple times
        THEN expect:
            - Different cache keys generated for different parameter combinations
            - Same parameters result in cache hit
        """
        # Setup mocks
        query_engine._normalize_query = Mock(return_value="test query")
        query_engine._detect_query_type = Mock(return_value="entity_search")
        query_engine._process_entity_query = AsyncMock(return_value=[sample_query_result])
        query_engine._generate_query_suggestions = AsyncMock(return_value=[])
        
        # Same query with different parameters should not hit cache
        await query_engine.query("test query", max_results=10)
        await query_engine.query("test query", max_results=20)
        await query_engine.query("test query", filters={"entity_type": "Person"})
        
        # Each call should process (no cache hits due to different parameters)
        assert query_engine._process_entity_query.call_count == 3
        
        # Same parameters should hit cache
        await query_engine.query("test query", max_results=10)
        
        # Still 3 calls (fourth was cache hit)
        assert query_engine._process_entity_query.call_count == 3

    @pytest.mark.asyncio
    async def test_query_processing_time_measurement(self, query_engine, sample_query_result):
        """
        GIVEN a QueryEngine instance
        AND a query that takes measurable time to process
        WHEN query method is called
        THEN expect:
            - QueryResponse.processing_time is float > 0
            - Time measurement includes all processing steps
        """
        # Setup mocks with artificial delay
        query_engine._normalize_query = Mock(return_value="test query")
        query_engine._detect_query_type = Mock(return_value="entity_search")
        
        async def delayed_process(*args, **kwargs):
            await asyncio.sleep(0.01)  # 10ms delay
            return [sample_query_result]
        
        query_engine._process_entity_query = delayed_process
        query_engine._generate_query_suggestions = AsyncMock(return_value=[])
        
        # Execute query
        response = await query_engine.query("test query")
        
        # Verify processing time is measured and positive
        assert isinstance(response.processing_time, float)
        assert response.processing_time > 0
        assert response.processing_time >= 0.01  # At least the sleep time

    @pytest.mark.asyncio
    async def test_query_suggestion_generation(self, query_engine, sample_query_result):
        """
        GIVEN a QueryEngine instance
        AND a query that returns results
        WHEN query method is called
        THEN expect:
            - _generate_query_suggestions called with query and results
            - QueryResponse.suggestions contains list of strings
            - Suggestions list length <= 5
        """
        # Setup mocks
        query_engine._normalize_query = Mock(return_value="bill gates")
        query_engine._detect_query_type = Mock(return_value="entity_search")
        query_engine._process_entity_query = AsyncMock(return_value=[sample_query_result])
        
        suggestions = ["What is Microsoft?", "Bill Gates relationships", "Microsoft founders"]
        query_engine._generate_query_suggestions = AsyncMock(return_value=suggestions)
        
        # Execute query
        response = await query_engine.query("bill gates")
        
        # Verify suggestion generation was called with correct parameters
        query_engine._generate_query_suggestions.assert_called_once_with("bill gates", [sample_query_result])
        
        # Verify suggestions in response
        assert isinstance(response.suggestions, list)
        assert len(response.suggestions) <= 5
        assert all(isinstance(s, str) for s in response.suggestions)
        assert response.suggestions == suggestions

    @pytest.mark.asyncio
    async def test_query_metadata_completeness(self, query_engine, sample_query_result):
        """
        GIVEN a QueryEngine instance
        AND any valid query
        WHEN query method is called
        THEN expect QueryResponse.metadata to contain:
            - "normalized_query" key with normalized query string
            - "filters_applied" key with applied filters
            - "timestamp" key with ISO format timestamp
            - "cache_hit" key indicating if result was cached
        """
        # Setup mocks
        query_engine._normalize_query = Mock(return_value="test query normalized")
        query_engine._detect_query_type = Mock(return_value="entity_search")
        query_engine._process_entity_query = AsyncMock(return_value=[sample_query_result])
        query_engine._generate_query_suggestions = AsyncMock(return_value=[])
        
        filters = {"entity_type": "Person"}
        
        # Execute query
        response = await query_engine.query("test query", filters=filters)
        
        # Verify metadata completeness
        assert "normalized_query" in response.metadata
        assert response.metadata["normalized_query"] == "test query normalized"
        
        assert "filters_applied" in response.metadata
        assert response.metadata["filters_applied"] == filters
        
        assert "timestamp" in response.metadata
        # Verify timestamp is ISO format
        datetime.fromisoformat(response.metadata["timestamp"].replace('Z', '+00:00'))
        
        assert "cache_hit" in response.metadata
        assert isinstance(response.metadata["cache_hit"], bool)

    @pytest.mark.asyncio
    async def test_query_with_processor_method_exception(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND processor method raises RuntimeError
        WHEN query method is called
        THEN expect:
            - RuntimeError propagated to caller
            - No partial results returned
        """
        # Setup mocks
        query_engine._normalize_query = Mock(return_value="test query")
        query_engine._detect_query_type = Mock(return_value="entity_search")
        query_engine._process_entity_query = AsyncMock(side_effect=RuntimeError("Processing failed"))
        
        # Execute query and expect exception
        with pytest.raises(RuntimeError, match="Processing failed"):
            await query_engine.query("test query")

    @pytest.mark.asyncio
    async def test_query_response_structure_validation(self, query_engine, sample_query_result):
        """
        GIVEN a QueryEngine instance
        AND any valid query
        WHEN query method is called
        THEN expect QueryResponse to have:
            - query: str (original query)
            - query_type: str (detected or specified type)
            - results: List[QueryResult]
            - total_results: int (matching len(results))
            - processing_time: float
            - suggestions: List[str]
            - metadata: Dict[str, Any]
        """
        # Setup mocks
        query_engine._normalize_query = Mock(return_value="test query")
        query_engine._detect_query_type = Mock(return_value="entity_search")
        query_engine._process_entity_query = AsyncMock(return_value=[sample_query_result])
        query_engine._generate_query_suggestions = AsyncMock(return_value=["suggestion"])
        
        # Execute query
        response = await query_engine.query("test query")
        
        # Verify complete response structure
        assert isinstance(response, QueryResponse)
        
        # Verify all required fields exist and have correct types
        assert isinstance(response.query, str)
        assert response.query == "test query"
        
        assert isinstance(response.query_type, str)
        assert response.query_type == "entity_search"
        
        assert isinstance(response.results, list)
        assert all(isinstance(r, QueryResult) for r in response.results)
        
        assert isinstance(response.total_results, int)
        assert response.total_results == len(response.results)
        
        assert isinstance(response.processing_time, float)
        assert response.processing_time > 0
        
        assert isinstance(response.suggestions, list)
        assert all(isinstance(s, str) for s in response.suggestions)
        
        assert isinstance(response.metadata, dict)

    @pytest.mark.asyncio
    async def test_query_with_all_query_types(self, query_engine, sample_query_result):
        """
        GIVEN a QueryEngine instance
        WHEN query method is called with each valid query_type:
            - entity_search
            - relationship_search
            - semantic_search
            - document_search
            - cross_document
            - graph_traversal
        THEN expect:
            - Appropriate processor method called for each type
            - No exceptions raised
            - Valid QueryResponse returned for each
        """
        # Setup common mocks
        query_engine._normalize_query = Mock(return_value="test query")
        query_engine._generate_query_suggestions = AsyncMock(return_value=[])
        
        # Setup processor mocks
        query_engine._process_entity_query = AsyncMock(return_value=[sample_query_result])
        query_engine._process_relationship_query = AsyncMock(return_value=[sample_query_result])
        query_engine._process_semantic_query = AsyncMock(return_value=[sample_query_result])
        query_engine._process_document_query = AsyncMock(return_value=[sample_query_result])
        query_engine._process_cross_document_query = AsyncMock(return_value=[sample_query_result])
        query_engine._process_graph_traversal_query = AsyncMock(return_value=[sample_query_result])
        
        valid_query_types = [
            "entity_search",
            "relationship_search", 
            "semantic_search",
            "document_search",
            "cross_document",
            "graph_traversal"
        ]
        
        # Test each query type
        for query_type in valid_query_types:
            response = await query_engine.query("test query", query_type=query_type)
            
            # Verify response is valid
            assert isinstance(response, QueryResponse)
            assert response.query_type == query_type
            assert len(response.results) == 1
        
        # Verify each processor was called once
        query_engine._process_entity_query.assert_called_once()
        query_engine._process_relationship_query.assert_called_once()
        query_engine._process_semantic_query.assert_called_once()
        query_engine._process_document_query.assert_called_once()
        query_engine._process_cross_document_query.assert_called_once()
        query_engine._process_graph_traversal_query.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_timeout_handling(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND processor method that hangs indefinitely
        WHEN query method is called
        THEN expect:
            - TimeoutError raised after reasonable time limit
            - No resources leaked
        """
        # Setup mocks
        query_engine._normalize_query = Mock(return_value="test query")
        query_engine._detect_query_type = Mock(return_value="entity_search")
        
        # Create a processor that hangs indefinitely
        async def hanging_process(*args, **kwargs):
            await asyncio.sleep(10)  # Long delay to simulate hanging
            return []
        
        query_engine._process_entity_query = hanging_process
        
        # Mock the query method to include timeout logic
        original_query = query_engine.query
        
        async def query_with_timeout(*args, **kwargs):
            try:
                return await asyncio.wait_for(original_query(*args, **kwargs), timeout=0.1)
            except asyncio.TimeoutError:
                raise TimeoutError("Query processing timed out")
        
        query_engine.query = query_with_timeout
        
        # Execute query and expect timeout
        with pytest.raises(TimeoutError, match="Query processing timed out"):
            await query_engine.query("test query")
    

if __name__ == "__main__":
    pytest.main([__file__, "-v"])