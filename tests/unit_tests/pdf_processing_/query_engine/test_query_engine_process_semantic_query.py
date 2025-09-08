#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/query_engine.py
# Auto-generated on 2025-07-07 02:28:56"

import pytest
import os
import asyncio
import numpy as np
from unittest.mock import Mock, AsyncMock, patch
from typing import Dict, List, Any, Optional

from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

work_dir = "/home/runner/work/ipfs_datasets_py/ipfs_datasets_py"
file_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/query_engine.py")
md_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/query_engine_stubs.md")

# Make sure the input file and documentation file exist.
assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."

from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine, QueryResult

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


class TestQueryEngineProcessSemanticQuery:
    """Test QueryEngine._process_semantic_query method for semantic search using embeddings."""

    @pytest.fixture
    def mock_graphrag(self):
        """Create mock GraphRAGIntegrator for testing."""
        mock = Mock(spec=GraphRAGIntegrator)
        
        # Create mock chunks with all required attributes
        chunk_001 = Mock(
            chunk_id="chunk_001",
            content="Artificial intelligence is revolutionizing technology",
            embedding=np.array([0.1, 0.2, 0.3, 0.4]),
            document_id="doc_001",
            page_number=1,
            source_page=1,
            token_count=100,
            semantic_types="paragraph",
            relationships=[]
        )
        
        chunk_002 = Mock(
            chunk_id="chunk_002", 
            content="Machine learning applications in healthcare",
            embedding=np.array([0.2, 0.3, 0.4, 0.5]),
            document_id="doc_001",
            page_number=2,
            source_page=2,
            token_count=150,
            semantic_types="paragraph",
            relationships=[]
        )
        
        chunk_003 = Mock(
            chunk_id="chunk_003",
            content="Introduction to neural networks",
            embedding=np.array([0.05, 0.1, 0.15, 0.2]),
            document_id="doc_001",
            page_number=3,
            source_page=3,
            token_count=80,
            semantic_types="heading",
            relationships=[]
        )
        
        chunk_004 = Mock(
            chunk_id="chunk_004",
            content="Deep learning frameworks and tools",
            embedding=np.array([0.15, 0.25, 0.35, 0.45]),
            document_id="doc_002",
            page_number=1,
            source_page=1,
            token_count=120,
            semantic_types="paragraph",
            relationships=[]
        )
        
        # Create mock entities with proper name configuration
        entity_001 = Mock()
        entity_001.name = "AI"
        entity_001.entity_id = "ent_001"
        entity_001.source_chunks = ["chunk_001"]
        
        entity_002 = Mock()
        entity_002.name = "Machine Learning"
        entity_002.entity_id = "ent_002"
        entity_002.source_chunks = ["chunk_002"]
        
        # Create mock knowledge graphs
        mock.knowledge_graphs = {
            "doc_001": Mock(
                document_id="doc_001",
                chunks=[chunk_001, chunk_002, chunk_003],
                entities=[entity_001, entity_002]
            ),
            "doc_002": Mock(
                document_id="doc_002",
                chunks=[chunk_004],
                entities=[]
            )
        }
        
        # Add global_entities attribute that the implementation expects
        mock.global_entities = {
            "ent_001": entity_001,
            "ent_002": entity_002
        }
        
        return mock

    @pytest.fixture
    def mock_storage(self):
        """Create mock IPLDStorage for testing."""
        return Mock(spec=IPLDStorage)

    @pytest.fixture
    def mock_embedding_model(self):
        """Create mock SentenceTransformer for testing."""
        mock = Mock(spec=SentenceTransformer)
        # Return 4D array to match chunk embeddings
        mock.encode.return_value = np.array([[0.1, 0.2, 0.3, 0.4]])
        return mock

    @pytest.fixture
    def query_engine(self, mock_graphrag, mock_storage, mock_embedding_model) -> QueryEngine:
        """Create QueryEngine instance with mocked dependencies."""
        engine = QueryEngine.__new__(QueryEngine)
        engine.graphrag = mock_graphrag
        engine.storage = mock_storage
        engine.embedding_model = mock_embedding_model
        engine.embedding_cache = {}
        engine.query_cache = {}
        return engine

    @pytest.mark.asyncio
    async def test_process_semantic_query_successful_embedding_matching(self, query_engine):
        """
        GIVEN a QueryEngine instance with loaded embedding model
        AND normalized query "artificial intelligence applications"
        AND chunks with embeddings in knowledge graphs
        WHEN _process_semantic_query is called
        THEN expect:
            - Query embedding computed using sentence transformer
            - Cosine similarity calculated between query and chunk embeddings
            - Results ordered by similarity score descending
            - Top matching chunks returned as QueryResults
        """
        query = "artificial intelligence applications"
        
        # Mock cosine similarity to return predictable scores
        with patch('ipfs_datasets_py.pdf_processing.query_engine.cosine_similarity') as mock_cosine:
            # Return individual similarity scores for each chunk
            mock_cosine.side_effect = [
                np.array([[0.9]]),  # chunk_001
                np.array([[0.7]]),  # chunk_002  
                np.array([[0.3]]),  # chunk_003
                np.array([[0.6]])   # chunk_004
            ]
            
            results = await query_engine._process_semantic_query(query, None, 10)
            
            # Verify embedding model was called
            query_engine.embedding_model.encode.assert_called_once_with([query])
            
            # Verify cosine similarity was called for each chunk
            assert mock_cosine.call_count == 4
            
            # Verify results are ordered by similarity
            assert len(results) == 4
            assert results[0].relevance_score == 0.9
            assert results[1].relevance_score == 0.7
            assert results[2].relevance_score == 0.6
            assert results[3].relevance_score == 0.3
            
            # Verify result structure
            assert all(isinstance(r, QueryResult) for r in results)
            assert all(r.type == "chunk" for r in results)
            assert results[0].id == "chunk_001"

    @pytest.mark.asyncio
    async def test_process_semantic_query_no_embedding_model(self, query_engine):
        """
        GIVEN a QueryEngine instance with embedding_model = None
        AND normalized query "machine learning"
        WHEN _process_semantic_query is called
        THEN expect RuntimeError to be raised with appropriate message
        """
        query_engine.embedding_model = None
        query = "machine learning"
        
        with pytest.raises(RuntimeError, match="No embedding model available"):
            await query_engine._process_semantic_query(query, None, 10)

    @pytest.mark.asyncio
    async def test_process_semantic_query_embedding_computation_failure(self, query_engine):
        """
        GIVEN a QueryEngine instance with embedding model
        AND normalized query "test query"
        AND embedding model raises exception during encoding
        WHEN _process_semantic_query is called
        THEN expect RuntimeError to be raised
        """
        query = "test query"
        query_engine.embedding_model.encode.side_effect = Exception("Model encoding failed")
        
        with pytest.raises(RuntimeError, match="Embedding computation failed"):
            await query_engine._process_semantic_query(query, None, 10)

    @pytest.mark.asyncio
    async def test_process_semantic_query_chunks_without_embeddings(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND chunks missing embedding attributes
        AND normalized query "test"
        WHEN _process_semantic_query is called
        THEN expect:
            - AttributeError raised when accessing missing embedding attribute
        """
        query = "test"
        
        # Add chunk without embedding attribute
        chunk_no_embedding = Mock(
            chunk_id="chunk_no_embed",
            content="Content without embedding",
            document_id="doc_001",
            page_number=4,
            semantic_types={"paragraph"}
        )
        del chunk_no_embedding.embedding  # Remove embedding attribute
        
        query_engine.graphrag.knowledge_graphs["doc_001"].chunks.append(chunk_no_embedding)
        
        with pytest.raises(AttributeError, match="embedding"):
            await query_engine._process_semantic_query(query, None, 10)

    @pytest.mark.asyncio
    async def test_process_semantic_query_document_id_filter(self, query_engine):
        """
        GIVEN a QueryEngine instance with chunks across multiple documents
        AND normalized query "artificial intelligence"
        AND filters {"document_id": "doc_001"}
        WHEN _process_semantic_query is called
        THEN expect:
            - Only chunks from doc_001 processed
            - Chunks from other documents filtered out
            - Semantic search limited to specified document
        """
        query = "artificial intelligence"
        filters = {"document_id": "doc_001"}
        
        with patch('ipfs_datasets_py.pdf_processing.query_engine.cosine_similarity') as mock_cosine:
            # Return enough values for all chunks (4 total)
            mock_cosine.return_value = np.array([[0.9], [0.7], [0.3], [0.5]])
            
            results = await query_engine._process_semantic_query(query, filters, 10)
            
            # Should only have chunks from doc_001 (3 chunks)
            assert len(results) == 3
            assert all(r.source_document == "doc_001" for r in results)

    @pytest.mark.asyncio
    async def test_process_semantic_query_semantic_types_filter(self, query_engine):
        """
        GIVEN a QueryEngine instance with chunks of different semantic types
        AND normalized query "research methodology"
        AND filters {"semantic_types": "paragraph"}
        WHEN _process_semantic_query is called
        THEN expect:
            - Only paragraph-type chunks processed
            - Headings, lists, tables filtered out
            - Semantic type filtering applied before similarity calculation
        """
        query = "research methodology"
        filters = {"semantic_types": "paragraph"}
        
        with patch('ipfs_datasets_py.pdf_processing.query_engine.cosine_similarity') as mock_cosine:
            # Return enough values for all chunks (4 total)
            mock_cosine.return_value = np.array([[0.8], [0.6], [0.5], [0.7]])
            
            results = await query_engine._process_semantic_query(query, filters, 10)
            
            # Should only have paragraph chunks (3 total: 2 from doc_001, 1 from doc_002)
            assert len(results) == 3
            for result in results:
                assert result.metadata["semantic_types"] == "paragraph"

    @pytest.mark.asyncio
    async def test_process_semantic_query_min_similarity_threshold(self, query_engine):
        """
        GIVEN a QueryEngine instance with chunks
        AND normalized query "technology trends"
        AND filters {"min_similarity": 0.7}
        WHEN _process_semantic_query is called
        THEN expect:
            - Only chunks with similarity >= 0.7 included in results
            - Low similarity chunks filtered out
            - Similarity threshold applied after computation
        """
        query = "technology trends"
        filters = {"min_similarity": 0.7}
        
        with patch('ipfs_datasets_py.pdf_processing.query_engine.cosine_similarity') as mock_cosine:
            mock_cosine.side_effect = [
                np.array([[0.9]]),  # chunk_001
                np.array([[0.8]]),  # chunk_002
                np.array([[0.5]]),  # chunk_003
                np.array([[0.6]])   # chunk_004
            ]
            
            results = await query_engine._process_semantic_query(query, filters, 10)
            
            # Should only have chunks with similarity >= 0.7
            assert len(results) == 2
            assert all(r.relevance_score >= 0.7 for r in results)
            assert results[0].relevance_score == 0.9
            assert results[1].relevance_score == 0.8

    @pytest.mark.asyncio
    async def test_process_semantic_query_page_range_filter(self, query_engine):
        """
        GIVEN a QueryEngine instance with chunks from different pages
        AND normalized query "research conclusions"
        AND filters {"page_range": (2, 3)}
        WHEN _process_semantic_query is called
        THEN expect:
            - Only chunks from pages 2-3 processed
            - Chunks from other pages filtered out
            - Page range filtering applied before similarity calculation
        """
        query = "research conclusions"
        filters = {"page_range": (2, 3)}
        
        with patch('ipfs_datasets_py.pdf_processing.query_engine.cosine_similarity') as mock_cosine:
            # Return enough values for all chunks (4 total)
            mock_cosine.return_value = np.array([[0.8], [0.6], [0.7], [0.5]])
            
            results = await query_engine._process_semantic_query(query, filters, 10)
            
            # Should only have chunks from pages 2-3 (chunk_002 and chunk_003)
            assert len(results) == 2
            page_numbers = [r.metadata.get("source_page", r.metadata.get("page_number", 0)) for r in results]
            assert all(2 <= page_num <= 3 for page_num in page_numbers)

    @pytest.mark.asyncio
    async def test_process_semantic_query_max_results_limiting(self, query_engine):
        """
        GIVEN a QueryEngine instance with many matching chunks
        AND normalized query "machine learning"
        AND max_results = 2
        WHEN _process_semantic_query is called
        THEN expect:
            - Exactly 2 results returned (or fewer if less available)
            - Results are highest similarity chunks
            - Results ordered by similarity score descending
        """
        query = "machine learning"
        max_results = 2
        
        with patch('ipfs_datasets_py.pdf_processing.query_engine.cosine_similarity') as mock_cosine:
            mock_cosine.side_effect = [
                np.array([[0.9]]),  # chunk_001
                np.array([[0.8]]),  # chunk_002
                np.array([[0.7]]),  # chunk_003
                np.array([[0.6]])   # chunk_004
            ]
            
            results = await query_engine._process_semantic_query(query, None, max_results)
            
            # Should return exactly 2 results (highest similarity)
            assert len(results) == 2
            assert results[0].relevance_score == 0.9
            assert results[1].relevance_score == 0.8

    @pytest.mark.asyncio
    async def test_process_semantic_query_no_matching_chunks(self, query_engine):
        """
        GIVEN a QueryEngine instance with no chunks meeting filter criteria
        AND normalized query "test"
        WHEN _process_semantic_query is called
        THEN expect:
            - Empty list returned
            - No exceptions raised
            - Method completes successfully
        """
        query = "test"
        filters = {"document_id": "nonexistent_doc"}
        
        results = await query_engine._process_semantic_query(query, filters, 10)
        
        assert results == []

    @pytest.mark.asyncio
    async def test_process_semantic_query_invalid_max_results(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND normalized query "test"
        AND max_results = -2 or 0
        WHEN _process_semantic_query is called
        THEN expect ValueError to be raised
        """
        query = "test"
        
        with pytest.raises(ValueError, match="max_results must be positive"):
            await query_engine._process_semantic_query(query, None, -2)
            
        with pytest.raises(ValueError, match="max_results must be positive"):
            await query_engine._process_semantic_query(query, None, 0)

    @pytest.mark.asyncio
    async def test_process_semantic_query_invalid_similarity_threshold(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND normalized query "test"
        AND filters {"min_similarity": 1.5} (invalid range)
        WHEN _process_semantic_query is called
        THEN expect ValueError to be raised
        """
        query = "test"
        filters = {"min_similarity": 1.5}
        
        with pytest.raises(ValueError, match="min_similarity must be between 0.0 and 1.0"):
            await query_engine._process_semantic_query(query, filters, 10)
            
        filters = {"min_similarity": -0.1}
        with pytest.raises(ValueError, match="min_similarity must be between 0.0 and 1.0"):
            await query_engine._process_semantic_query(query, filters, 10)

    @pytest.mark.asyncio
    async def test_process_semantic_query_invalid_filters_type(self, query_engine):
        """
        GIVEN a QueryEngine instance
        AND normalized query "test"
        AND filters as tuple instead of dict
        WHEN _process_semantic_query is called
        THEN expect TypeError to be raised
        """
        query = "test"
        filters = ("document_id", "doc_001")  # Invalid tuple instead of dict
        
        with pytest.raises(TypeError, match="filters must be a dictionary"):
            await query_engine._process_semantic_query(query, filters, 10)

    @pytest.mark.asyncio
    async def test_process_semantic_query_result_structure_validation(self, query_engine):
        """
        GIVEN a QueryEngine instance with valid chunks
        AND normalized query "artificial intelligence"
        WHEN _process_semantic_query is called
        THEN expect each QueryResult to have:
            - id: str (chunk_id)
            - type: "chunk"
            - content: str (chunk content, possibly truncated)
            - relevance_score: float (cosine similarity 0.0-1.0)
            - source_document: str
            - source_chunks: List[str] (single chunk ID)
            - metadata: Dict with semantic search details
        """
        query = "artificial intelligence"
        
        with patch('ipfs_datasets_py.pdf_processing.query_engine.cosine_similarity') as mock_cosine:
            mock_cosine.return_value = np.array([[0.85]])
            
            results = await query_engine._process_semantic_query(query, None, 1)
            
            result = results[0]
            assert isinstance(result.id, str)
            assert result.type == "chunk"
            assert isinstance(result.content, str)
            assert isinstance(result.relevance_score, float)
            assert 0.0 <= result.relevance_score <= 1.0
            assert isinstance(result.source_document, str)
            assert isinstance(result.source_chunks, list)
            assert len(result.source_chunks) == 1
            assert isinstance(result.metadata, dict)
            
            # Verify metadata contains expected fields
            assert "document_id" in result.metadata
            assert "source_page" in result.metadata
            assert "semantic_types" in result.metadata
            assert "similarity_score" in result.metadata

    @pytest.mark.asyncio
    async def test_process_semantic_query_content_truncation(self, query_engine):
        """
        GIVEN a QueryEngine instance with very long chunks
        AND normalized query "detailed analysis"
        WHEN _process_semantic_query is called
        THEN expect:
            - Long chunk content truncated in results for readability
            - Full content available in metadata
            - Truncation indicated appropriately
        """
        query = "detailed analysis"
        
        # Create chunk with very long content
        long_content = "This is a very long chunk content. " * 50  # 1750 characters
        long_chunk = Mock(
            chunk_id="long_chunk",
            content=long_content,
            embedding=np.array([0.1, 0.2, 0.3, 0.4]),
            document_id="doc_001",
            page_number=1,
            semantic_types={"paragraph"}
        )
        
        query_engine.graphrag.knowledge_graphs["doc_001"].chunks = [long_chunk]
        
        with patch('ipfs_datasets_py.pdf_processing.query_engine.cosine_similarity') as mock_cosine:
            mock_cosine.return_value = np.array([[0.8]])
            
            results = await query_engine._process_semantic_query(query, None, 1)
            
            result = results[0]
            # Content should be truncated (less than original)
            assert len(result.content) < len(long_content)
            assert "..." in result.content or len(result.content) == 500  # Typical truncation length
            
            # Full content should be in metadata
            assert "full_content" in result.metadata
            assert len(result.metadata["full_content"]) == len(long_content)

    @pytest.mark.asyncio
    async def test_process_semantic_query_related_entities_identification(self, query_engine):
        """
        GIVEN a QueryEngine instance with chunks and entities
        AND normalized query "technology companies"
        WHEN _process_semantic_query is called
        THEN expect:
            - Related entities identified by checking entity source chunks
            - Entity names included in result metadata
            - Entity identification enhances result context
        """
        query = "technology companies"
        
        with patch('ipfs_datasets_py.pdf_processing.query_engine.cosine_similarity') as mock_cosine:
            mock_cosine.return_value = np.array([[0.9, 0.7, 0.5, 0.6]])
            
            results = await query_engine._process_semantic_query(query, None, 4)
            
            # Check that related entities are identified
            chunk_001_result = next(r for r in results if r.id == "chunk_001")
            assert "related_entities" in chunk_001_result.metadata
            related_entities = chunk_001_result.metadata["related_entities"]
            assert len(related_entities) > 0
            assert "AI" in related_entities
            
            chunk_002_result = next(r for r in results if r.id == "chunk_002")
            assert "related_entities" in chunk_002_result.metadata
            related_entities = chunk_002_result.metadata["related_entities"]
            assert len(related_entities) > 0
            assert "Machine Learning" in related_entities

    @pytest.mark.asyncio
    async def test_process_semantic_query_similarity_score_accuracy(self, query_engine: QueryEngine):
        """
        GIVEN a QueryEngine instance with known embeddings
        AND normalized query with predictable similarity scores
        WHEN _process_semantic_query is called
        THEN expect:
            - Cosine similarity computed correctly
            - Scores between 0.0 and 1.0
            - Higher scores for more similar content
            - Similarity computation uses correct embedding dimensions
        """
        query = "test similarity"
        
        # Use real cosine similarity calculation
        with patch.object(query_engine.embedding_model, 'encode') as mock_encode:
            # Set up predictable embeddings - encode returns array for single query
            query_embedding = np.array([1.0, 0.0, 0.0, 0.0])
            mock_encode.return_value = [query_embedding]  # encode([query]) returns list
            
            # Set chunk embeddings to known values (all positive for proper cosine similarity range)
            query_engine.graphrag.knowledge_graphs["doc_001"].chunks[0].embedding = np.array([1.0, 0.0, 0.0, 0.0])  # Perfect match
            query_engine.graphrag.knowledge_graphs["doc_001"].chunks[1].embedding = np.array([0.5, 0.5, 0.5, 0.5])  # Partial match
            query_engine.graphrag.knowledge_graphs["doc_001"].chunks[2].embedding = np.array([0.0, 1.0, 0.0, 0.0])  # Orthogonal
            query_engine.graphrag.knowledge_graphs["doc_002"].chunks[0].embedding = np.array([0.0, 0.0, 1.0, 0.0])  # Different direction
            
            results = await query_engine._process_semantic_query(query, None, 10)
            
            # Verify similarity scores are reasonable
            assert len(results) == 4
            
            # Cosine similarity range is [0.0, 1.0] for positive embeddings
            assert all(0.0 <= r.relevance_score <= 1.0 for r in results)
            
            # Perfect match should have highest score
            assert results[0].relevance_score > results[1].relevance_score
            assert results[1].relevance_score > results[2].relevance_score

    @pytest.mark.asyncio
    async def test_process_semantic_query_metadata_completeness(self, query_engine):
        """
        GIVEN a QueryEngine instance with chunks
        AND normalized query "research methodology"
        WHEN _process_semantic_query is called
        THEN expect QueryResult.metadata to contain:
            - document_id: str
            - page_number: int
            - semantic_types: str
            - related_entities: List[str]
            - full_content: str (if truncated)
            - similarity_score: float
        """
        query = "research methodology"
        
        with patch('ipfs_datasets_py.pdf_processing.query_engine.cosine_similarity') as mock_cosine:
            mock_cosine.return_value = np.array([[0.8]])
            
            results = await query_engine._process_semantic_query(query, None, 1)
            
            result = results[0]
            metadata = result.metadata
            
            # Verify all required metadata fields
            assert isinstance(metadata["document_id"], str)
            assert isinstance(metadata["source_page"], int)
            assert isinstance(metadata["semantic_types"], str)
            assert isinstance(metadata["related_entities"], list)
            assert isinstance(metadata["similarity_score"], (int, float))
            assert isinstance(metadata["related_entities"], list)
            assert isinstance(metadata["similarity_score"], float)
            
            # Verify values make sense
            assert metadata["similarity_score"] == result.relevance_score
            assert metadata["document_id"] == result.source_document

    @pytest.mark.asyncio
    async def test_process_semantic_query_embedding_caching(self, query_engine):
        """
        GIVEN a QueryEngine instance with embedding cache
        AND same query executed multiple times
        WHEN _process_semantic_query is called
        THEN expect:
            - Query embedding cached after first computation
            - Subsequent calls use cached embedding
            - Performance improved on repeated queries
        """
        query = "cached query test"
        
        with patch('ipfs_datasets_py.pdf_processing.query_engine.cosine_similarity') as mock_cosine:
            mock_cosine.return_value = np.array([[0.8, 0.6, 0.4, 0.5]])
            
            # First call
            results1 = await query_engine._process_semantic_query(query, None, 10)
            
            # Verify embedding model was called
            assert query_engine.embedding_model.encode.call_count == 1
            
            # Verify embedding is cached
            assert query in query_engine.embedding_cache
            
            # Second call with same query
            results2 = await query_engine._process_semantic_query(query, None, 10)
            
            # Verify embedding model was not called again
            assert query_engine.embedding_model.encode.call_count == 1
            
            # Results should be identical
            assert len(results1) == len(results2)
            assert all(r1.relevance_score == r2.relevance_score for r1, r2 in zip(results1, results2))

    @pytest.mark.asyncio
    async def test_process_semantic_query_multiple_knowledge_graphs(self, query_engine):
        """
        GIVEN a QueryEngine instance with multiple knowledge graphs
        AND normalized query "innovation strategies"
        WHEN _process_semantic_query is called
        THEN expect:
            - Chunks from all knowledge graphs processed
            - Results aggregated across graphs
            - No duplicate chunks in results
        """
        query = "innovation strategies"
        
        # Add another knowledge graph
        query_engine.graphrag.knowledge_graphs["doc_003"] = Mock(
            document_id="doc_003",  # Set the document_id on the KG itself
            chunks=[
                Mock(
                    chunk_id="chunk_005",
                    content="Innovation in software development",
                    embedding=np.array([0.3, 0.4, 0.5, 0.6]),
                    document_id="doc_003",
                    page_number=1,
                    semantic_types={"paragraph"}
                )
            ],
            entities=[]
        )
        
        with patch('ipfs_datasets_py.pdf_processing.query_engine.cosine_similarity') as mock_cosine:
            mock_cosine.return_value = np.array([[0.9, 0.8, 0.7, 0.6, 0.5]])
            
            results = await query_engine._process_semantic_query(query, None, 10)
            
            # Should have chunks from all knowledge graphs
            assert len(results) == 5
            
            # Should have chunks from all documents
            doc_ids = {r.source_document for r in results}
            assert "doc_001" in doc_ids
            assert "doc_002" in doc_ids
            assert "doc_003" in doc_ids
            
            # No duplicate chunk IDs
            chunk_ids = [r.id for r in results]
            assert len(chunk_ids) == len(set(chunk_ids))


if __name__ == "__main__":
    pytest.main([__file__, "-v"])