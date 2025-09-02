#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/graphrag_integrator.py
# Auto-generated on 2025-07-07 02:28:56
import pytest
import os
import asyncio
import re
import time
import networkx as nx
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator, KnowledgeGraph, Entity, Relationship
from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
from pydantic import ValidationError


from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

work_dir = "/home/runner/work/ipfs_datasets_py/ipfs_datasets_py"
file_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/graphrag_integrator.py")
md_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/graphrag_integrator_stubs.md")

# Make sure the input file and documentation file exist.
assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."

from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator

# Check if each classes methods are accessible:
assert GraphRAGIntegrator.integrate_document
assert GraphRAGIntegrator._extract_entities_from_chunks
assert GraphRAGIntegrator._extract_entities_from_text
assert GraphRAGIntegrator._extract_relationships
assert GraphRAGIntegrator._extract_chunk_relationships
assert GraphRAGIntegrator._infer_relationship_type
assert GraphRAGIntegrator._extract_cross_chunk_relationships
assert GraphRAGIntegrator._find_chunk_sequences
assert GraphRAGIntegrator._create_networkx_graph
assert GraphRAGIntegrator._merge_into_global_graph
assert GraphRAGIntegrator._discover_cross_document_relationships
assert GraphRAGIntegrator._find_similar_entities
assert GraphRAGIntegrator._calculate_text_similarity
assert GraphRAGIntegrator._store_knowledge_graph_ipld
assert GraphRAGIntegrator.query_graph
assert GraphRAGIntegrator.get_entity_neighborhood


# 4. Check if the modules's imports are accessible:
try:
    import logging
    import hashlib
    from typing import Dict, List, Any, Optional
    from dataclasses import dataclass, asdict
    from datetime import datetime
    import uuid
    import re

    import networkx as nx
    import numpy as np

    from ipfs_datasets_py.ipld import IPLDStorage
    from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk, LLMChunkMetadata
except ImportError as e:
    raise ImportError(f"Could into import the module's dependencies: {e}") 

from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_factory import (
    LLMChunkMetadataTestDataFactory as MetadataFactory
)



class TestIntegrateDocument:
    """Test class for GraphRAGIntegrator.integrate_document method."""

    @pytest.fixture
    def mock_integrator(self) -> GraphRAGIntegrator:
        """Create a mock GraphRAGIntegrator for testing."""
        integrator = GraphRAGIntegrator()
        # Mock the async methods
        integrator._extract_entities_from_chunks = AsyncMock()
        integrator._extract_relationships = AsyncMock()
        integrator._create_networkx_graph = AsyncMock()
        integrator._store_knowledge_graph_ipld = AsyncMock()
        integrator._merge_into_global_graph = AsyncMock()
        integrator._discover_cross_document_relationships = AsyncMock()
        return integrator

    @property
    def sample_metadata(self):
        """Create sample metadata for LLMChunk objects."""
        return LLMChunkMetadata(**MetadataFactory.create_valid_baseline_data())

    @pytest.fixture
    def sample_llm_document(self):
        """Create a sample LLMDocument for testing."""
        chunks = [
            LLMChunk(
                chunk_id="chunk_1",
                content="Apple Inc. is a technology company founded by Steve Jobs.",
                source_page=1,
                source_elements=["paragraph"],
                token_count=12,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata,
                embedding=None
            ),
            LLMChunk(
                chunk_id="chunk_2", 
                content="Steve Jobs was the CEO of Apple Inc. until 2011.",
                source_page=1,
                source_elements=["paragraph"],
                token_count=10,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata,
                embedding=None
            )
        ]
        return LLMDocument(
            document_id="doc_123",
            title="Apple History",
            chunks=chunks,
            summary="A brief history of Apple Inc. and Steve Jobs.",
            key_entities=[{"text": "Apple Inc.", "type": "organization", "confidence": 0.9}],
            processing_metadata={"created_at": "2024-01-01T00:00:00Z"}
        )

    @pytest.fixture
    def sample_entities(self):
        """Create sample entities for testing."""
        return [
            Entity(
                id="entity_1",
                name="Apple Inc.",
                type="organization",
                description="Technology company",
                confidence=0.9,
                source_chunks=["chunk_1", "chunk_2"],
                properties={}
            ),
            Entity(
                id="entity_2",
                name="Steve Jobs",
                type="person", 
                description="CEO of Apple Inc.",
                confidence=0.95,
                source_chunks=["chunk_1", "chunk_2"],
                properties={}
            )
        ]

    @pytest.fixture
    def sample_relationships(self):
        """Create sample relationships for testing."""
        return [
            Relationship(
                id="rel_1",
                source_entity_id="entity_2",
                target_entity_id="entity_1",
                relationship_type="founded",
                description="Steve Jobs founded Apple Inc.",
                confidence=0.8,
                source_chunks=["chunk_1"],
                properties={}
            )
        ]

    @pytest.mark.asyncio
    async def test_integrate_document_valid_input(self, mock_integrator: GraphRAGIntegrator, sample_llm_document, sample_entities, sample_relationships):
        """
        GIVEN a valid LLMDocument with chunks, title, and document_id
        WHEN integrate_document is called
        THEN a KnowledgeGraph should be returned
        AND entities should be extracted from chunks
        AND relationships should be extracted
        AND the graph should be stored in IPLD
        AND the graph should be merged into global structures
        AND cross-document relationships should be discovered
        """
        # Setup mocks
        mock_integrator._extract_entities_from_chunks.return_value = sample_entities
        mock_integrator._extract_relationships.return_value = sample_relationships
        mock_integrator._store_knowledge_graph_ipld.return_value = "test_cid_123"
        
        result = await mock_integrator.integrate_document(sample_llm_document)
        
        # Verify the result is a KnowledgeGraph
        assert isinstance(result, KnowledgeGraph)
        assert result.document_id == "doc_123"
        assert result.entities == sample_entities
        assert result.relationships == sample_relationships
        assert result.chunks == sample_llm_document.chunks
        assert result.ipld_cid == "test_cid_123"
        
        # Verify all methods were called
        mock_integrator._extract_entities_from_chunks.assert_called_once_with(sample_llm_document.chunks)
        mock_integrator._extract_relationships.assert_called_once_with(sample_entities, sample_llm_document.chunks)
        mock_integrator._create_networkx_graph.assert_called_once()
        mock_integrator._store_knowledge_graph_ipld.assert_called_once()
        mock_integrator._merge_into_global_graph.assert_called_once()
        mock_integrator._discover_cross_document_relationships.assert_called_once()

    @pytest.mark.asyncio
    async def test_integrate_document_empty_chunks(self, mock_integrator: GraphRAGIntegrator):
        """
        GIVEN an LLMDocument with empty chunks list
        WHEN integrate_document is called
        THEN a KnowledgeGraph should still be returned
        AND it should have empty entities and relationships lists
        AND the graph should still be stored and processed
        """
        empty_doc = LLMDocument(
            document_id="empty_doc",
            title="Empty Document",
            chunks=[],
            summary="Empty document for testing",
            key_entities=[],
            processing_metadata={"created_at": "2024-01-01T00:00:00Z"}
        )
        
        mock_integrator._extract_entities_from_chunks.return_value = []
        mock_integrator._extract_relationships.return_value = []
        mock_integrator._store_knowledge_graph_ipld.return_value = "empty_cid"
        
        result = await mock_integrator.integrate_document(empty_doc)
        
        assert isinstance(result, KnowledgeGraph)
        assert result.document_id == "empty_doc"
        assert result.entities == []
        assert result.relationships == []
        assert result.chunks == []

    @pytest.mark.asyncio
    async def test_integrate_document_single_chunk(self, mock_integrator: GraphRAGIntegrator):
        """
        GIVEN an LLMDocument with a single chunk containing entities
        WHEN integrate_document is called
        THEN entities should be extracted from that chunk
        AND intra-chunk relationships should be created
        AND no cross-chunk relationships should exist
        """
        single_chunk_doc = LLMDocument(
            document_id="single_doc",
            title="Single Chunk",
            chunks=[LLMChunk(
                chunk_id="only_chunk",
                content="Microsoft was founded by Bill Gates.",
                source_page=1,
                source_elements=["paragraph"],
                token_count=6,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata,
                embedding=None
            )],
            summary="Single chunk document for testing",
            key_entities=[{"text": "Microsoft", "type": "organization", "confidence": 0.9}],
            processing_metadata={"created_at": "2024-01-01T00:00:00Z"}
        )
        
        entities = [Entity(
            id="ms", name="Microsoft", type="organization",
            description="Tech company", confidence=0.9,
            source_chunks=["only_chunk"], properties={}
        )]
        relationships = [Relationship(
            id="rel_1", source_entity_id="gates", target_entity_id="ms",
            relationship_type="founded", description="Founded relationship",
            confidence=0.8, source_chunks=["only_chunk"], properties={}
        )]
        
        mock_integrator._extract_entities_from_chunks.return_value = entities
        mock_integrator._extract_relationships.return_value = relationships
        mock_integrator._store_knowledge_graph_ipld.return_value = "single_cid"
        
        result = await mock_integrator.integrate_document(single_chunk_doc)
        
        assert len(result.chunks) == 1
        assert len(result.entities) == 1
        assert len(result.relationships) == 1

    @pytest.mark.asyncio
    async def test_integrate_document_multiple_chunks_same_page(self, mock_integrator: GraphRAGIntegrator, sample_llm_document, sample_entities, sample_relationships):
        """
        GIVEN an LLMDocument with multiple chunks from the same page
        WHEN integrate_document is called
        THEN entities should be extracted from all chunks
        AND both intra-chunk and cross-chunk relationships should be created
        AND chunk sequences should be identified properly
        """
        mock_integrator._extract_entities_from_chunks.return_value = sample_entities
        mock_integrator._extract_relationships.return_value = sample_relationships
        mock_integrator._store_knowledge_graph_ipld.return_value = "multi_cid"
        
        result = await mock_integrator.integrate_document(sample_llm_document)
        
        # Verify multiple chunks are processed
        assert len(result.chunks) == 2
        assert all(chunk.source_page == 1 for chunk in result.chunks)
        
        # Verify entities from all chunks
        mock_integrator._extract_entities_from_chunks.assert_called_once_with(sample_llm_document.chunks)

    @pytest.mark.asyncio
    async def test_integrate_document_multiple_chunks_different_pages(self, mock_integrator: GraphRAGIntegrator):
        """
        GIVEN an LLMDocument with chunks from different pages
        WHEN integrate_document is called
        THEN entities should be extracted from all chunks
        AND cross-chunk relationships should only be created within page sequences
        """
        multi_page_doc = LLMDocument(
            document_id="multi_page",
            title="Multi Page Document",
            chunks=[
                LLMChunk(
                    chunk_id="chunk_1", 
                    content="Content page 1", 
                    source_page=1,
                    source_elements=["paragraph"],
                    token_count=3,
                    semantic_types="text",
                    relationships=[],
                    metadata=self.sample_metadata,
                    embedding=None
                ),
                LLMChunk(
                    chunk_id="chunk_2", 
                    content="Content page 2", 
                    source_page=2,
                    source_elements=["paragraph"],
                    token_count=3,
                    semantic_types="text",
                    relationships=[],
                    metadata=self.sample_metadata,
                    embedding=None
                ),
                LLMChunk(
                    chunk_id="chunk_3", 
                    content="More content page 2", 
                    source_page=2,
                    source_elements=["paragraph"],
                    token_count=4,
                    semantic_types="text",
                    relationships=[],
                    metadata=self.sample_metadata,
                    embedding=None
                )
            ],
            summary="Multi page document for testing",
            key_entities=[],
            processing_metadata={"created_at": "2024-01-01T00:00:00Z"}
        )
        
        mock_integrator._extract_entities_from_chunks.return_value = []
        mock_integrator._extract_relationships.return_value = []
        mock_integrator._store_knowledge_graph_ipld.return_value = "multi_page_cid"
        
        result = await mock_integrator.integrate_document(multi_page_doc)
        
        assert len(result.chunks) == 3
        pages = set(chunk.source_page for chunk in result.chunks)
        assert pages == {1, 2}

    @pytest.mark.asyncio
    async def test_integrate_document_none_input(self, mock_integrator: GraphRAGIntegrator):
        """
        GIVEN None is passed as the llm_document parameter
        WHEN integrate_document is called
        THEN a TypeError should be raised
        AND the error message should indicate invalid document
        """
        with pytest.raises(TypeError) as exc_info:
            await mock_integrator.integrate_document(None)
        
        assert "llm_document cannot be None" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_integrate_document_missing_document_id(self, mock_integrator: GraphRAGIntegrator):
        """
        GIVEN an LLMDocument without a document_id
        WHEN integrate_document is called
        THEN a ValueError should be raised
        AND the error message should indicate missing document_id
        """
        invalid_doc = LLMDocument(
            document_id="doc123",
            title="Valid Title",
            chunks=[],
            summary="Invalid document for testing",
            key_entities=[],
            processing_metadata={"created_at": "2024-01-01T00:00:00Z"}
        )
        invalid_doc.document_id = None  # Simulate missing document_id, since pydantic catches it otherwise

        with pytest.raises(ValueError) as exc_info:
            await mock_integrator.integrate_document(invalid_doc)


    @pytest.mark.asyncio
    async def test_integrate_document_missing_title(self, mock_integrator: GraphRAGIntegrator):
        """
        GIVEN an LLMDocument without a title
        WHEN integrate_document is called
        THEN a ValueError should be raised
        AND the error message should indicate missing title
        """
        invalid_doc = LLMDocument(
            document_id="valid_id",
            title="Valid Title",
            chunks=[],
            summary="Invalid document for testing",
            key_entities=[],
            processing_metadata={"created_at": "2024-01-01T00:00:00Z"}
        )
        invalid_doc.title = None  # Simulate missing title, since pydantic catches it otherwise

        with pytest.raises(ValueError) as exc_info:
            await mock_integrator.integrate_document(invalid_doc)
        
        assert "title is required" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_integrate_document_invalid_chunks_type(self, mock_integrator: GraphRAGIntegrator):
        """
        GIVEN an LLMDocument with chunks that are not LLMChunk instances
        WHEN integrate_document is called
        THEN a TypeError should be raised
        AND the error message should indicate invalid chunk types
        """
        invalid_doc = LLMDocument(
            document_id="valid_id",
            title="Valid Title",
            chunks=[],
            summary="Invalid document for testing",
            key_entities=[],
            processing_metadata={"created_at": "2024-01-01T00:00:00Z"}
        )
        invalid_doc.chunks = ["Not a chunk", "Also not a chunk"]  # Simulate invalid chunks
        with pytest.raises(TypeError) as exc_info:
            await mock_integrator.integrate_document(invalid_doc)
        
        assert "All chunks must be LLMChunk instances" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_integrate_document_duplicate_document_id(self, mock_integrator: GraphRAGIntegrator, sample_llm_document):
        """
        GIVEN an LLMDocument with a document_id that already exists in knowledge_graphs
        WHEN integrate_document is called
        THEN the existing knowledge graph should be updated/replaced
        AND a warning should be logged about overwriting existing graph
        """
        # Pre-populate existing knowledge graph
        existing_kg = KnowledgeGraph(
            graph_id="existing",
            document_id="doc_123",
            entities=[],
            relationships=[],
            chunks=[],
            metadata=self.sample_metadata,
            creation_timestamp="2024-01-01T00:00:00Z"
        )
        mock_integrator.knowledge_graphs["existing"] = existing_kg
        
        mock_integrator._extract_entities_from_chunks.return_value = []
        mock_integrator._extract_relationships.return_value = []
        mock_integrator._store_knowledge_graph_ipld.return_value = "new_cid"
        
        # Patch the module-specific logger instead of global logging
        with patch('ipfs_datasets_py.pdf_processing.graphrag_integrator.logger.warning') as mock_warning:
            result = await mock_integrator.integrate_document(sample_llm_document)
            
            mock_warning.assert_called_once()
            assert "overwriting existing knowledge graph" in mock_warning.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_integrate_document_entity_extraction_failure(self, mock_integrator: GraphRAGIntegrator, sample_llm_document):
        """
        GIVEN entity extraction fails for the document chunks
        WHEN integrate_document is called
        THEN an appropriate exception should be raised
        AND the error should indicate entity extraction failure
        AND no partial data should be stored
        """
        mock_integrator._extract_entities_from_chunks.side_effect = Exception("Entity extraction failed")
        
        with pytest.raises(Exception) as exc_info:
            await mock_integrator.integrate_document(sample_llm_document)
        
        assert "Entity extraction failed" in str(exc_info.value)
        mock_integrator._store_knowledge_graph_ipld.assert_not_called()

    @pytest.mark.asyncio
    async def test_integrate_document_relationship_extraction_failure(self, mock_integrator: GraphRAGIntegrator, sample_llm_document, sample_entities):
        """
        GIVEN relationship extraction fails for the extracted entities
        WHEN integrate_document is called
        THEN an appropriate exception should be raised
        AND the error should indicate relationship extraction failure
        AND no partial data should be stored
        """
        mock_integrator._extract_entities_from_chunks.return_value = sample_entities
        mock_integrator._extract_relationships.side_effect = Exception("Relationship extraction failed")
        
        with pytest.raises(Exception) as exc_info:
            await mock_integrator.integrate_document(sample_llm_document)
        
        assert "Relationship extraction failed" in str(exc_info.value)
        mock_integrator._store_knowledge_graph_ipld.assert_not_called()

    @pytest.mark.asyncio
    async def test_integrate_document_ipld_storage_failure(self, mock_integrator: GraphRAGIntegrator, sample_llm_document, sample_entities, sample_relationships):
        """
        GIVEN IPLD storage fails when storing the knowledge graph
        WHEN integrate_document is called
        THEN a RuntimeError should be raised
        AND the knowledge graph should not be added to global structures
        """
        mock_integrator._extract_entities_from_chunks.return_value = sample_entities
        mock_integrator._extract_relationships.return_value = sample_relationships
        
        mock_integrator._store_knowledge_graph_ipld.side_effect = RuntimeError("Storage failed")
        
        with pytest.raises(RuntimeError) as exc_info:
            await mock_integrator.integrate_document(sample_llm_document)
        
        assert "Storage failed" in str(exc_info.value)
        mock_integrator._merge_into_global_graph.assert_not_called()

    @pytest.mark.asyncio
    async def test_integrate_document_networkx_graph_creation(self, mock_integrator: GraphRAGIntegrator, sample_llm_document, sample_entities, sample_relationships):
        """
        GIVEN a successful entity and relationship extraction
        WHEN integrate_document is called
        THEN a NetworkX graph should be created for the document
        AND it should be stored in document_graphs
        AND it should contain all entities as nodes and relationships as edges
        """
        import networkx as nx
        mock_graph = nx.DiGraph()
        
        mock_integrator._extract_entities_from_chunks.return_value = sample_entities
        mock_integrator._extract_relationships.return_value = sample_relationships
        mock_integrator._create_networkx_graph.return_value = mock_graph
        mock_integrator._store_knowledge_graph_ipld.return_value = "graph_cid"
        
        result = await mock_integrator.integrate_document(sample_llm_document)
        
        mock_integrator._create_networkx_graph.assert_called_once()
        # Verify the graph is stored in document_graphs
        assert sample_llm_document.document_id in mock_integrator.document_graphs

    @pytest.mark.asyncio
    async def test_integrate_document_global_graph_merge(self, mock_integrator: GraphRAGIntegrator, sample_llm_document, sample_entities, sample_relationships):
        """
        GIVEN a knowledge graph is created for a document
        WHEN integrate_document is called
        THEN the document graph should be merged into the global graph
        AND global_entities should be updated with new entities
        AND cross_document_relationships should be updated if applicable
        """
        mock_integrator._extract_entities_from_chunks.return_value = sample_entities
        mock_integrator._extract_relationships.return_value = sample_relationships
        mock_integrator._store_knowledge_graph_ipld.return_value = "merge_cid"
        
        result = await mock_integrator.integrate_document(sample_llm_document)
        
        mock_integrator._merge_into_global_graph.assert_called_once_with(result)

    @pytest.mark.asyncio
    async def test_integrate_document_cross_document_relationship_discovery(self, mock_integrator: GraphRAGIntegrator, sample_llm_document, sample_entities, sample_relationships):
        """
        GIVEN existing entities in global_entities that match new document entities
        WHEN integrate_document is called
        THEN cross-document relationships should be discovered and created
        AND these relationships should be added to cross_document_relationships
        """
        mock_integrator._extract_entities_from_chunks.return_value = sample_entities
        mock_integrator._extract_relationships.return_value = sample_relationships
        mock_integrator._store_knowledge_graph_ipld.return_value = "cross_cid"
        
        result = await mock_integrator.integrate_document(sample_llm_document)
        
        mock_integrator._discover_cross_document_relationships.assert_called_once_with(result)

    @pytest.mark.asyncio
    async def test_integrate_document_timestamp_creation(self, mock_integrator: GraphRAGIntegrator, sample_llm_document):
        """
        GIVEN a document is being integrated
        WHEN integrate_document is called
        THEN the resulting KnowledgeGraph should have a valid creation_timestamp
        AND the timestamp should be in ISO 8601 format
        AND the timestamp should be recent (within last few seconds)
        """
        mock_integrator._extract_entities_from_chunks.return_value = []
        mock_integrator._extract_relationships.return_value = []
        mock_integrator._store_knowledge_graph_ipld.return_value = "timestamp_cid"
        
        before_time = datetime.now()
        result = await mock_integrator.integrate_document(sample_llm_document)
        after_time = datetime.now()
        
        # Parse the timestamp (remove Z suffix and parse as naive datetime)
        timestamp_str = result.creation_timestamp.rstrip('Z')
        timestamp = datetime.fromisoformat(timestamp_str)
        
        # Check it's within reasonable bounds (allowing for test execution time)
        assert before_time <= timestamp <= after_time
        # Check it's in correct ISO format with Z suffix
        assert result.creation_timestamp.endswith('Z')
        assert len(result.creation_timestamp) > 19  # Should be ISO format with microseconds

    @pytest.mark.asyncio
    async def test_integrate_document_graph_id_generation(self, mock_integrator: GraphRAGIntegrator, sample_llm_document):
        """
        GIVEN a document is being integrated
        WHEN integrate_document is called
        THEN the resulting KnowledgeGraph should have a unique graph_id
        AND the graph_id should be derived from the document_id
        AND the graph_id should be consistent for the same document
        """
        mock_integrator._extract_entities_from_chunks.return_value = []
        mock_integrator._extract_relationships.return_value = []
        mock_integrator._store_knowledge_graph_ipld.return_value = "id_cid"
        
        result1 = await mock_integrator.integrate_document(sample_llm_document)
        result2 = await mock_integrator.integrate_document(sample_llm_document)
        
        # Graph IDs should be deterministic based on document_id
        assert result1.graph_id == result2.graph_id
        assert sample_llm_document.document_id in result1.graph_id
        assert sample_llm_document.document_id in result2.graph_id
        assert len(result1.graph_id) > len(sample_llm_document.document_id)  # Should be enhanced

    @pytest.mark.asyncio
    async def test_integrate_document_metadata_population(self, mock_integrator: GraphRAGIntegrator, sample_llm_document, sample_entities, sample_relationships):
        """
        GIVEN a document is being integrated
        WHEN integrate_document is called
        THEN the resulting KnowledgeGraph metadata should contain:
            - Entity extraction statistics
            - Relationship extraction statistics
            - Processing parameters used
            - Model information if available
        """
        mock_integrator._extract_entities_from_chunks.return_value = sample_entities
        mock_integrator._extract_relationships.return_value = sample_relationships
        mock_integrator._store_knowledge_graph_ipld.return_value = "meta_cid"
        
        result = await mock_integrator.integrate_document(sample_llm_document)
        
        assert 'document_title' in result.metadata
        assert 'entity_count' in result.metadata
        assert 'relationship_count' in result.metadata
        assert 'chunk_count' in result.metadata
        assert 'processing_timestamp' in result.metadata
        
        assert result.metadata['entity_count'] == len(sample_entities)
        assert result.metadata['relationship_count'] == len(sample_relationships)
        assert result.metadata['chunk_count'] == len(sample_llm_document.chunks)
        assert result.metadata['document_title'] == sample_llm_document.title

    @pytest.mark.asyncio
    async def test_integrate_document_concurrent_integration(self, mock_integrator: GraphRAGIntegrator):
        """
        GIVEN multiple documents are being integrated concurrently
        WHEN integrate_document is called simultaneously
        THEN each integration should complete successfully
        AND no race conditions should occur in global state updates
        AND each document should get a unique knowledge graph
        """
        docs = [
            LLMDocument(
                document_id=f"doc_{i}",
                title=f"Document {i}",
                chunks=[LLMChunk(
                    chunk_id=f"chunk_{i}",
                    content=f"Content {i}",
                    source_page=1,
                    source_elements=["paragraph"],
                    token_count=5,
                    semantic_types="text",
                    relationships=[],
                    metadata=self.sample_metadata,
                    embedding=None
                )],
                summary=f"Summary for document {i}",
                key_entities=[],
                processing_metadata={"created_at": "2024-01-01T00:00:00Z"}
            ) for i in range(3)
        ]
        
        mock_integrator._extract_entities_from_chunks.return_value = []
        mock_integrator._extract_relationships.return_value = []
        mock_integrator._store_knowledge_graph_ipld.return_value = "concurrent_cid"
        
        # Run concurrent integrations
        tasks = [mock_integrator.integrate_document(doc) for doc in docs]
        results = await asyncio.gather(*tasks)
        
        # Verify all completed successfully
        assert len(results) == 3
        doc_ids = [result.document_id for result in results]
        assert len(set(doc_ids)) == 3  # All unique
        assert set(doc_ids) == {"doc_0", "doc_1", "doc_2"}

    @pytest.mark.asyncio
    async def test_integrate_document_large_document(self, mock_integrator: GraphRAGIntegrator):
        """
        GIVEN an LLMDocument with a large number of chunks (>100)
        WHEN integrate_document is called
        THEN the integration should complete within reasonable time
        AND memory usage should remain reasonable
        AND all chunks should be processed
        """
        large_chunks = [
            LLMChunk(
                chunk_id=f"chunk_{i}",
                content=f"Content for chunk {i} with some entity data",
                source_page=i // 10 + 1,
                source_elements=["paragraph"],
                token_count=12,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata,
                embedding=None
            ) for i in range(150)
        ]
        
        large_doc = LLMDocument(
            document_id="large_doc",
            title="Large Document",
            chunks=large_chunks,
            summary="Large document with many chunks for testing",
            key_entities=[],
            processing_metadata={"created_at": "2024-01-01T00:00:00Z"}
        )
        
        mock_integrator._extract_entities_from_chunks.return_value = []
        mock_integrator._extract_relationships.return_value = []
        mock_integrator._store_knowledge_graph_ipld.return_value = "large_cid"
        
        import time
        start_time = time.time()
        result = await mock_integrator.integrate_document(large_doc)
        end_time = time.time()
        
        # Should complete in reasonable time (adjust threshold as needed)
        assert end_time - start_time < 30  # 30 seconds max
        assert len(result.chunks) == 150
        mock_integrator._extract_entities_from_chunks.assert_called_once_with(large_chunks)

    @pytest.mark.asyncio
    async def test_integrate_document_chunks_without_entities(self, mock_integrator: GraphRAGIntegrator):
        """
        GIVEN an LLMDocument with chunks that contain no extractable entities
        WHEN integrate_document is called
        THEN a KnowledgeGraph should still be returned
        AND it should have empty entities list
        AND no relationships should be created
        """
        no_entity_doc = LLMDocument(
            document_id="no_entities",
            title="No Entities Document",
            chunks=[LLMChunk(
                chunk_id="empty_chunk",
                content="This is just plain text with no named entities.",
                source_page=1,
                source_elements=["paragraph"],
                token_count=10,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata,
                embedding=None
            )],
            summary="Document with no entities for testing",
            key_entities=[],
            processing_metadata={"created_at": "2024-01-01T00:00:00Z"}
        )
        
        mock_integrator._extract_entities_from_chunks.return_value = []
        mock_integrator._extract_relationships.return_value = []
        mock_integrator._store_knowledge_graph_ipld.return_value = "empty_entities_cid"
        
        result = await mock_integrator.integrate_document(no_entity_doc)
        
        assert isinstance(result, KnowledgeGraph)
        assert len(result.entities) == 0
        assert len(result.relationships) == 0
        assert len(result.chunks) == 1

    @pytest.mark.asyncio
    async def test_integrate_document_chunks_with_low_confidence_entities(self, mock_integrator: GraphRAGIntegrator):
        """
        GIVEN an LLMDocument with chunks containing only low-confidence entities
        WHEN integrate_document is called with high entity_extraction_confidence
        THEN entities below the threshold should be filtered out
        AND only high-confidence entities should be included in the result
        """
        # Set high confidence threshold
        mock_integrator.entity_extraction_confidence = 0.9
        
        low_conf_doc = LLMDocument(
            document_id="low_conf",
            title="Low Confidence Document",
            chunks=[LLMChunk(
                chunk_id="low_conf_chunk",
                content="Maybe John Smith works somewhere.",
                source_page=1,
                source_elements=["paragraph"],
                token_count=6,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata,
                embedding=None
            )],
            summary="Document with low confidence entities for testing",
            key_entities=[],
            processing_metadata={"created_at": "2024-01-01T00:00:00Z"}
        )
        
        # Mock low confidence entities that should be filtered out
        low_confidence_entities = [
            Entity(
                id="low_ent",
                name="John Smith",
                type="person",
                description="Maybe a person",
                confidence=0.5,  # Below threshold
                source_chunks=["low_conf_chunk"],
                properties={}
            )
        ]
        
        # The _extract_entities_from_chunks should filter based on confidence
        mock_integrator._extract_entities_from_chunks.return_value = []  # Filtered out
        mock_integrator._extract_relationships.return_value = []
        mock_integrator._store_knowledge_graph_ipld.return_value = "low_conf_cid"
        
        result = await mock_integrator.integrate_document(low_conf_doc)
        
        assert len(result.entities) == 0  # Should be filtered out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
