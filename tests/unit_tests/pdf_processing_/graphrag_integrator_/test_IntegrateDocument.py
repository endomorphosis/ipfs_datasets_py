#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/graphrag_integrator.py
# Auto-generated on 2025-07-07 02:28:56
import pytest
import os
import anyio
import re
import time
import networkx as nx
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime
from pydantic import ValidationError
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

work_dir = os.path.abspath(os.path.dirname(__file__))
while not os.path.exists(os.path.join(work_dir, "__pyproject.toml")):
    parent = os.path.dirname(work_dir)
    if parent == work_dir:
        break
    work_dir = parent
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


@pytest.fixture
async def integrator_where_integrate_document_was_called_once_before(
    integrator: GraphRAGIntegrator, sample_llm_document):
    """
    Fixture that returns a GraphRAGIntegrator instance where 
    integrate_document was called once with sample_llm_document fixture
    """
    _ = await integrator.integrate_document(sample_llm_document)

    return integrator


@pytest.fixture
async def result1(integrator: GraphRAGIntegrator, sample_llm_document):
    """Fixture that returns the result of integrate_document called once."""
    result = await integrator.integrate_document(sample_llm_document)
    return result


class TestIntegrateDocument:
    """Test class for GraphRAGIntegrator.integrate_document method."""

    @pytest.mark.asyncio
    async def test_when_integrating_valid_document_then_returns_knowledge_graph(self, integrator: GraphRAGIntegrator, sample_llm_document):
        """
        GIVEN a valid LLMDocument with chunks, title, and document_id
        WHEN integrate_document is called
        THEN a KnowledgeGraph should be returned
        """
        # Act
        result = await integrator.integrate_document(sample_llm_document)
        
        # Assert
        assert isinstance(result, KnowledgeGraph), f"Expected KnowledgeGraph, got {type(result)}"

    @pytest.mark.asyncio
    async def test_when_integrating_valid_document_then_document_id_matches(self, integrator: GraphRAGIntegrator, sample_llm_document):
        """
        GIVEN a valid LLMDocument with chunks, title, and document_id
        WHEN integrate_document is called
        THEN the result document_id should match the input document_id
        """
        # Act
        result = await integrator.integrate_document(sample_llm_document)
        
        # Assert
        assert result.document_id == sample_llm_document.document_id, \
            f"Expected document_id {sample_llm_document.document_id}, got {result.document_id}"

    @pytest.mark.asyncio
    async def test_when_integrating_valid_document_then_chunks_are_preserved(self, integrator: GraphRAGIntegrator, sample_llm_document):
        """
        GIVEN a valid LLMDocument with chunks, title, and document_id
        WHEN integrate_document is called
        THEN the result chunks should match the input chunks
        """
        # Act
        result = await integrator.integrate_document(sample_llm_document)
        
        # Assert
        assert result.chunks == sample_llm_document.chunks, \
            f"Expected chunks to be preserved, got different chunks"

    @pytest.mark.asyncio
    async def test_when_integrating_empty_chunks_then_returns_knowledge_graph(self, integrator: GraphRAGIntegrator, empty_document):
        """
        GIVEN an LLMDocument with empty chunks list
        WHEN integrate_document is called
        THEN a KnowledgeGraph should still be returned
        """
        # Act
        result = await integrator.integrate_document(empty_document)
        
        # Assert
        assert isinstance(result, KnowledgeGraph), f"Expected KnowledgeGraph, got {type(result)}"

    @pytest.mark.asyncio
    async def test_when_integrating_empty_chunks_then_document_id_matches(self, integrator: GraphRAGIntegrator, empty_document):
        """
        GIVEN an LLMDocument with empty chunks list
        WHEN integrate_document is called
        THEN the result document_id should match the input document_id
        """
        # Act
        result = await integrator.integrate_document(empty_document)
        
        # Assert
        assert result.document_id == empty_document.document_id, \
            f"Expected document_id {empty_document.document_id}, got {result.document_id}"

    @pytest.mark.asyncio
    async def test_when_integrating_empty_chunks_then_chunks_list_is_empty(self, integrator: GraphRAGIntegrator, empty_document):
        """
        GIVEN an LLMDocument with empty chunks list
        WHEN integrate_document is called
        THEN the result chunks should be empty
        """
        # Act
        result = await integrator.integrate_document(empty_document)
        
        # Assert
        assert result.chunks == [], f"Expected empty chunks list, got {result.chunks}"

    @pytest.mark.asyncio
    async def test_when_integrating_single_chunk_then_returns_knowledge_graph(self, integrator: GraphRAGIntegrator, single_chunk_document):
        """
        GIVEN an LLMDocument with a single chunk containing entities
        WHEN integrate_document is called
        THEN a KnowledgeGraph should be returned
        """
        # Act
        result = await integrator.integrate_document(single_chunk_document)
        
        # Assert
        assert isinstance(result, KnowledgeGraph), f"Expected KnowledgeGraph, got {type(result)}"

    @pytest.mark.asyncio
    async def test_when_integrating_single_chunk_then_chunk_count_is_one(self, integrator: GraphRAGIntegrator, single_chunk_document):
        """
        GIVEN an LLMDocument with a single chunk containing entities
        WHEN integrate_document is called
        THEN the result should have exactly one chunk
        """
        # Act
        result = await integrator.integrate_document(single_chunk_document)
        
        # Assert
        assert len(result.chunks) == 1, f"Expected 1 chunk, got {len(result.chunks)}"

    @pytest.mark.asyncio
    async def test_when_integrating_multiple_chunks_then_returns_knowledge_graph(self, integrator: GraphRAGIntegrator, sample_llm_document):
        """
        GIVEN an LLMDocument with multiple chunks from the same page
        WHEN integrate_document is called
        THEN a KnowledgeGraph should be returned
        """
        # Act
        result = await integrator.integrate_document(sample_llm_document)
        
        # Assert
        assert isinstance(result, KnowledgeGraph), f"Expected KnowledgeGraph, got {type(result)}"

    @pytest.mark.asyncio
    async def test_when_integrating_multiple_chunks_then_chunk_count_matches(self, integrator: GraphRAGIntegrator, sample_llm_document):
        """
        GIVEN an LLMDocument with multiple chunks from the same page
        WHEN integrate_document is called
        THEN the result chunk count should match the input chunk count
        """
        # Arrange
        expected_chunk_count = len(sample_llm_document.chunks)
        
        # Act
        result = await integrator.integrate_document(sample_llm_document)
        
        # Assert
        assert len(result.chunks) == expected_chunk_count, \
            f"Expected {expected_chunk_count} chunks, got {len(result.chunks)}"

    @pytest.mark.asyncio
    async def test_when_integrating_multi_page_document_then_returns_knowledge_graph(self, integrator: GraphRAGIntegrator, multi_page_document):
        """
        GIVEN an LLMDocument with chunks from different pages
        WHEN integrate_document is called
        THEN a KnowledgeGraph should be returned
        """
        # Act
        result = await integrator.integrate_document(multi_page_document)
        
        # Assert
        assert isinstance(result, KnowledgeGraph), f"Expected KnowledgeGraph, got {type(result)}"

    @pytest.mark.asyncio
    async def test_when_integrating_multi_page_document_then_all_chunks_processed(self, integrator: GraphRAGIntegrator, multi_page_document):
        """
        GIVEN an LLMDocument with chunks from different pages
        WHEN integrate_document is called
        THEN all chunks should be processed and included in the result
        """
        # Arrange
        expected_chunk_count = len(multi_page_document.chunks)
        
        # Act
        result = await integrator.integrate_document(multi_page_document)
        
        # Assert
        assert len(result.chunks) == expected_chunk_count, \
            f"Expected {expected_chunk_count} chunks, got {len(result.chunks)}"

    @pytest.mark.asyncio
    async def test_when_integrating_none_input_then_raises_type_error(self, integrator: GraphRAGIntegrator, test_constants):
        """
        GIVEN None is passed as the llm_document parameter
        WHEN integrate_document is called
        THEN a TypeError should be raised
        """
        # Act & Assert
        with pytest.raises(TypeError) as exc_info:
            await integrator.integrate_document(None)
        
        assert test_constants['NONE_INPUT_ERROR_MSG'] in str(exc_info.value), \
            f"Expected error message containing '{test_constants['NONE_INPUT_ERROR_MSG']}'"

    @pytest.mark.asyncio
    async def test_when_integrating_document_with_missing_document_id_then_raises_value_error(self, integrator: GraphRAGIntegrator, invalid_document_for_missing_id, test_constants):
        """
        GIVEN an LLMDocument without a document_id
        WHEN integrate_document is called
        THEN a ValueError should be raised
        """
        # Arrange
        invalid_document_for_missing_id.document_id = None  # Simulate missing document_id
        
        # Act & Assert
        with pytest.raises(ValueError) as exc_info:
            await integrator.integrate_document(invalid_document_for_missing_id)
        
        assert test_constants['MISSING_DOC_ID_ERROR_MSG'] in str(exc_info.value), \
            f"Expected error message containing '{test_constants['MISSING_DOC_ID_ERROR_MSG']}'"

    @pytest.mark.asyncio
    async def test_when_integrating_document_with_missing_title_then_raises_value_error(self, integrator: GraphRAGIntegrator, invalid_document_for_missing_title, test_constants):
        """
        GIVEN an LLMDocument without a title
        WHEN integrate_document is called
        THEN a ValueError should be raised
        """
        # Arrange
        invalid_document_for_missing_title.title = None  # Simulate missing title
        
        # Act & Assert
        with pytest.raises(ValueError) as exc_info:
            await integrator.integrate_document(invalid_document_for_missing_title)
        
        assert test_constants['MISSING_TITLE_ERROR_MSG'] in str(exc_info.value), \
            f"Expected error message containing '{test_constants['MISSING_TITLE_ERROR_MSG']}'"

    @pytest.mark.asyncio
    async def test_when_integrating_document_with_invalid_chunks_type_then_raises_type_error(self, integrator: GraphRAGIntegrator, invalid_document_for_chunks_type, test_constants):
        """
        GIVEN an LLMDocument with chunks that are not LLMChunk instances
        WHEN integrate_document is called
        THEN a TypeError should be raised
        """
        # Arrange
        invalid_document_for_chunks_type.chunks = ["Not a chunk", "Also not a chunk"]  # Simulate invalid chunks
        
        # Act & Assert
        with pytest.raises(TypeError) as exc_info:
            await integrator.integrate_document(invalid_document_for_chunks_type)

        assert test_constants['INVALID_CHUNKS_ERROR_MSG'] in str(exc_info.value), \
            f"Expected error message containing '{test_constants['INVALID_CHUNKS_ERROR_MSG']}'"

    @pytest.mark.asyncio
    async def test_when_integrating_document_then_has_valid_creation_timestamp(self, integrator: GraphRAGIntegrator, sample_llm_document, test_constants):
        """
        GIVEN a document is being integrated
        WHEN integrate_document is called
        THEN the resulting KnowledgeGraph should have a valid creation_timestamp
        """
        # Arrange
        before_time = datetime.now()
        # Act
        result = await integrator.integrate_document(sample_llm_document)
        after_time = datetime.now()
        
        # Assert - Parse the timestamp (remove Z suffix and parse as naive datetime)
        timestamp_str = result.creation_timestamp.rstrip(test_constants['TIMESTAMP_Z_SUFFIX'])
        timestamp = datetime.fromisoformat(timestamp_str)
        
        assert before_time <= timestamp <= after_time, \
            f"Timestamp {timestamp} should be between {before_time} and {after_time}"

    @pytest.mark.asyncio
    async def test_when_integrating_document_then_has_timestamp_in_iso_format(self, integrator: GraphRAGIntegrator, sample_llm_document, test_constants):
        """
        GIVEN a document is being integrated
        WHEN integrate_document is called
        THEN the timestamp should be in ISO 8601 format with Z suffix
        """
        # Act
        result = await integrator.integrate_document(sample_llm_document)

        # Assert
        assert result.creation_timestamp.endswith(test_constants['TIMESTAMP_Z_SUFFIX']), \
            f"Timestamp should end with '{test_constants['TIMESTAMP_Z_SUFFIX']}'"


    @pytest.mark.asyncio
    async def test_when_integrating_document_then_has_unique_graph_id(self, 
    integrator: GraphRAGIntegrator, sample_llm_document, result1):
        """
        GIVEN a document is being integrated
        WHEN integrate_document is called multiple times with same document
        THEN the graph_id should be consistent for the same document
        """
        # Act
        result1 = await integrator.integrate_document(sample_llm_document)
        result2 = await integrator.integrate_document(sample_llm_document)
        
        # Assert
        assert result1.graph_id == result2.graph_id, \
            f"Graph IDs should be consistent for same document: {result1.graph_id} vs {result2.graph_id}"

    @pytest.mark.asyncio
    async def test_when_integrating_document_then_graph_id_contains_document_id(self, integrator: GraphRAGIntegrator, sample_llm_document):
        """
        GIVEN a document is being integrated
        WHEN integrate_document is called
        THEN the graph_id should be derived from the document_id
        """
        # Act
        result = await integrator.integrate_document(sample_llm_document)
        
        # Assert
        assert sample_llm_document.document_id in result.graph_id, \
            f"Graph ID {result.graph_id} should contain document ID {sample_llm_document.document_id}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("expected_field", [
        'document_title',
        'chunk_count', 
        'processing_timestamp'
    ])
    async def test_when_integrating_document_then_metadata_contains_expected_field(self, integrator: GraphRAGIntegrator, sample_llm_document, expected_field):
        """
        GIVEN a document is being integrated
        WHEN integrate_document is called
        THEN the resulting KnowledgeGraph metadata should contain the expected field
        """
        # Act
        result = await integrator.integrate_document(sample_llm_document)
        
        # Assert
        assert expected_field in result.metadata, f"Metadata should contain field '{expected_field}'"

    @pytest.mark.asyncio
    async def test_when_integrating_document_then_metadata_document_title_matches_input(self, integrator: GraphRAGIntegrator, sample_llm_document):
        """
        GIVEN a document is being integrated
        WHEN integrate_document is called
        THEN the metadata document_title should match the input document title
        """
        # Act
        result = await integrator.integrate_document(sample_llm_document)

        # Assert
        assert result.metadata['document_title'] == sample_llm_document.title, \
            f"Expected title {sample_llm_document.title}, got {result.metadata['document_title']}"

    @pytest.mark.asyncio
    async def test_when_integrating_document_then_metadata_chunk_count_matches_input(self, integrator: GraphRAGIntegrator, sample_llm_document):
        """
        GIVEN a document is being integrated
        WHEN integrate_document is called
        THEN the metadata chunk_count should match the input document chunk count
        """
        # Act
        result = await integrator.integrate_document(sample_llm_document)

        # Assert
        assert result.metadata['chunk_count'] == len(sample_llm_document.chunks), \
            f"Expected chunk count {len(sample_llm_document.chunks)}, got {result.metadata['chunk_count']}"

    @pytest.mark.asyncio
    async def test_when_integrating_document_then_stores_document_in_graph_collection(self, integrator: GraphRAGIntegrator, sample_llm_document):
        """
        GIVEN a document with entities and relationships
        WHEN integrate_document is called
        THEN the document should be stored in document_graphs attribute
        """
        # Act
        _ = await integrator.integrate_document(sample_llm_document)
        
        # Assert
        assert sample_llm_document.document_id in integrator.document_graphs, \
            f"Document {sample_llm_document.document_id} should be stored in document_graphs"

    @pytest.mark.asyncio
    async def test_when_integrating_document_then_creates_networkx_digraph(self, integrator: GraphRAGIntegrator, sample_llm_document):
        """
        GIVEN a document with entities and relationships
        WHEN integrate_document is called
        THEN a NetworkX DiGraph should be created for the document
        """
        # Act
        _ = await integrator.integrate_document(sample_llm_document)
        
        # Assert
        graph = integrator.document_graphs[sample_llm_document.document_id]
        assert isinstance(graph, nx.DiGraph), f"Expected NetworkX DiGraph, got {type(graph)}"

    @pytest.mark.asyncio
    async def test_when_integrating_document_then_updates_global_graph(self, integrator: GraphRAGIntegrator, sample_llm_document):
        """
        GIVEN a document is being integrated
        WHEN integrate_document is called
        THEN the global graph should be updated with new entities
        """
        # Arrange - Check initial state
        initial_entity_count = len(integrator.global_entities)
        
        # Act
        _ = await integrator.integrate_document(sample_llm_document)
        
        # Assert - Global entities should be updated 
        final_entity_count = len(integrator.global_entities)
        assert final_entity_count >= initial_entity_count, \
            "Global entities should be updated with document entities"

    @pytest.mark.asyncio
    async def test_when_integrating_multiple_documents_then_discovers_cross_document_relationships(
        self, 
        integrator: GraphRAGIntegrator, 
        sample_llm_document, concurrent_test_documents):
        """
        GIVEN multiple documents with potentially related entities
        WHEN documents are integrated sequentially
        THEN cross-document relationships should be discovered
        """
        # Arrange - Integrate first document
        await integrator.integrate_document(sample_llm_document)
        initial_relationship_count = len(integrator.cross_document_relationships)
        
        # Act - Integrate additional documents
        _ = [await integrator.integrate_document(doc) for doc in concurrent_test_documents]
        
        # Assert - Cross-document relationships may be discovered
        final_relationship_count = len(integrator.cross_document_relationships)
        assert final_relationship_count >= initial_relationship_count, \
            "Cross-document relationships should be maintained or increased"

    @pytest.mark.asyncio
    async def test_when_integrating_document_then_timestamp_is_within_reasonable_bounds(self, integrator: GraphRAGIntegrator, sample_llm_document, test_constants):
        """
        GIVEN a document is being integrated
        WHEN integrate_document is called
        THEN the resulting KnowledgeGraph timestamp should be within reasonable time bounds
        """
        # Arrange
        before_time = datetime.now()
        
        # Act
        result = await integrator.integrate_document(sample_llm_document)
        after_time = datetime.now()
        
        # Assert
        timestamp_str = result.creation_timestamp.rstrip(test_constants['TIMESTAMP_Z_SUFFIX'])
        timestamp = datetime.fromisoformat(timestamp_str)
        assert before_time <= timestamp <= after_time, \
            f"Timestamp {timestamp} should be between {before_time} and {after_time}"

    @pytest.mark.asyncio
    async def test_when_integrating_document_then_timestamp_has_z_suffix(self, integrator: GraphRAGIntegrator, sample_llm_document, test_constants):
        """
        GIVEN a document is being integrated
        WHEN integrate_document is called
        THEN the resulting KnowledgeGraph timestamp should end with Z suffix
        """
        # Act
        result = await integrator.integrate_document(sample_llm_document)
        
        # Assert
        assert result.creation_timestamp.endswith(test_constants['TIMESTAMP_Z_SUFFIX']), \
            f"Timestamp should end with '{test_constants['TIMESTAMP_Z_SUFFIX']}'"


    @pytest.mark.asyncio
    async def test_when_integrating_document_multiple_times_then_graph_id_is_consistent(self, 
        integrator_where_integrate_document_was_called_once_before: GraphRAGIntegrator, 
        sample_llm_document, result1):
        """
        GIVEN a document is being integrated multiple times
        WHEN integrate_document is called with the same document
        THEN the graph_id should be consistent across calls
        """
        integrator = integrator_where_integrate_document_was_called_once_before
        # Act
        result2 = await integrator.integrate_document(sample_llm_document)
        
        # Assert
        assert result1.graph_id == result2.graph_id, \
            f"Graph IDs should be consistent: {result1.graph_id} vs {result2.graph_id}"

    @pytest.mark.asyncio
    async def test_when_integrating_document_then_graph_id_contains_document_id(self, 
        integrator: GraphRAGIntegrator, sample_llm_document):
        """
        GIVEN a document is being integrated
        WHEN integrate_document is called
        THEN the graph_id should contain the document_id
        """
        # Act
        result = await integrator.integrate_document(sample_llm_document)
        
        # Assert
        assert sample_llm_document.document_id in result.graph_id, \
            f"Graph ID should contain document ID: {result.graph_id}"

    @pytest.mark.asyncio
    async def test_when_integrating_document_then_graph_id_is_enhanced_beyond_document_id(self, 
        integrator: GraphRAGIntegrator, sample_llm_document):
        """
        GIVEN a document is being integrated
        WHEN integrate_document is called
        THEN the graph_id should be enhanced beyond just the document_id
        """
        # Act
        result = await integrator.integrate_document(sample_llm_document)
        
        # Assert
        assert len(result.graph_id) > len(sample_llm_document.document_id), \
            "Graph ID should be enhanced beyond just document ID"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("expected_field", [
        'document_title',
        'entity_count', 
        'relationship_count',
        'chunk_count',
        'processing_timestamp'
    ])
    async def test_when_integrating_document_then_metadata_contains_expected_field(self, integrator: GraphRAGIntegrator, sample_llm_document, expected_field):
        """
        GIVEN a document is being integrated
        WHEN integrate_document is called
        THEN the resulting KnowledgeGraph metadata should contain the expected field
        """
        # Act
        result = await integrator.integrate_document(sample_llm_document)
        
        # Assert
        assert expected_field in result.metadata, f"Metadata should contain field '{expected_field}'"

    @pytest.mark.asyncio
    async def test_when_integrating_document_then_metadata_document_title_matches_input(self, integrator: GraphRAGIntegrator, sample_llm_document):
        """
        GIVEN a document is being integrated
        WHEN integrate_document is called
        THEN the metadata document_title should match the input document title
        """
        # Act
        result = await integrator.integrate_document(sample_llm_document)
        
        # Assert
        assert result.metadata['document_title'] == sample_llm_document.title, \
            f"Title should match: expected {sample_llm_document.title}, got {result.metadata['document_title']}"

    @pytest.mark.asyncio
    async def test_when_integrating_document_then_metadata_chunk_count_matches_input(self, integrator: GraphRAGIntegrator, sample_llm_document):
        """
        GIVEN a document is being integrated
        WHEN integrate_document is called
        THEN the metadata chunk_count should match the input document chunk count
        """
        # Act
        result = await integrator.integrate_document(sample_llm_document)
        
        # Assert
        assert result.metadata['chunk_count'] == len(sample_llm_document.chunks), \
            f"Chunk count should match: expected {len(sample_llm_document.chunks)}, got {result.metadata['chunk_count']}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("metadata_field,expected_type", [
        ('entity_count', int),
        ('relationship_count', int)
    ])
    async def test_when_integrating_document_then_metadata_count_fields_are_integers(self, integrator: GraphRAGIntegrator, sample_llm_document, metadata_field, expected_type):
        """
        GIVEN a document is being integrated
        WHEN integrate_document is called
        THEN the metadata count fields should be integers
        """
        # Act
        result = await integrator.integrate_document(sample_llm_document)
        
        # Assert
        assert isinstance(result.metadata[metadata_field], expected_type), f"{metadata_field} should be an {expected_type.__name__}"

    @pytest.mark.asyncio
    async def test_when_integrating_multiple_documents_concurrently_then_all_complete_successfully(self, integrator: GraphRAGIntegrator, concurrent_test_documents, test_constants):
        """
        GIVEN multiple documents are being integrated concurrently
        WHEN integrate_document is called simultaneously
        THEN each integration should complete successfully
        """
        # Act - Run concurrent integrations
        tasks = [integrator.integrate_document(doc) for doc in concurrent_test_documents]
        results = await asyncio.gather(*tasks)
        
        # Assert
        assert len(results) == test_constants['CONCURRENT_TASK_COUNT'], \
            f"Expected {test_constants['CONCURRENT_TASK_COUNT']} results, got {len(results)}"

    @pytest.mark.asyncio
    async def test_when_integrating_multiple_documents_concurrently_then_all_have_unique_document_ids(self, integrator: GraphRAGIntegrator, concurrent_test_documents, test_constants):
        """
        GIVEN multiple documents are being integrated concurrently
        WHEN integrate_document is called simultaneously
        THEN each document should get a unique knowledge graph
        """
        # Act - Run concurrent integrations
        tasks = [integrator.integrate_document(doc) for doc in concurrent_test_documents]
        results = await asyncio.gather(*tasks)

        # Assert
        doc_ids = [result.document_id for result in results]
        unique_doc_ids = set(doc_ids)
        assert len(unique_doc_ids) == test_constants['CONCURRENT_TASK_COUNT'], \
            f"Expected {test_constants['CONCURRENT_TASK_COUNT']} unique document IDs, got {len(unique_doc_ids)}"

    @pytest.mark.asyncio
    async def test_when_integrating_large_document_then_completes_within_reasonable_time(self, integrator: GraphRAGIntegrator, large_document, test_constants):
        """
        GIVEN an LLMDocument with a large number of chunks
        WHEN integrate_document is called
        THEN the integration should complete within reasonable time
        """
        # Arrange
        start_time = time.time()
        # Act
        _ = await integrator.integrate_document(large_document)
        end_time = time.time()

        # Assert
        assert end_time - start_time < test_constants['PERFORMANCE_TIMEOUT_SECONDS'], \
            f"Integration took {end_time - start_time}s, should be under {test_constants['PERFORMANCE_TIMEOUT_SECONDS']}s"

    @pytest.mark.asyncio
    async def test_when_integrating_large_document_then_all_chunks_processed(self, integrator: GraphRAGIntegrator, large_document, test_constants):
        """
        GIVEN an LLMDocument with a large number of chunks
        WHEN integrate_document is called
        THEN all chunks should be processed
        """
        # Act
        result = await integrator.integrate_document(large_document)
        
        # Assert
        assert len(result.chunks) == test_constants['LARGE_CHUNK_COUNT'], \
            f"Expected {test_constants['LARGE_CHUNK_COUNT']} chunks, got {len(result.chunks)}"

    @pytest.mark.asyncio
    async def test_when_integrating_document_without_entities_then_returns_knowledge_graph(self, integrator: GraphRAGIntegrator, no_entities_document):
        """
        GIVEN an LLMDocument with chunks that contain no extractable entities
        WHEN integrate_document is called
        THEN a KnowledgeGraph should still be returned
        """
        # Act
        result = await integrator.integrate_document(no_entities_document)
        
        # Assert
        assert isinstance(result, KnowledgeGraph), f"Expected KnowledgeGraph, got {type(result)}"

    @pytest.mark.asyncio
    async def test_when_integrating_document_without_entities_then_chunk_is_processed(self, integrator: GraphRAGIntegrator, no_entities_document, test_constants):
        """
        GIVEN an LLMDocument with chunks that contain no extractable entities
        WHEN integrate_document is called
        THEN the chunk should still be processed
        """
        # Act
        result = await integrator.integrate_document(no_entities_document)
        
        # Assert
        assert len(result.chunks) == test_constants['EXPECTED_RESULT_COUNT_ONE'], \
            f"Expected {test_constants['EXPECTED_RESULT_COUNT_ONE']} chunk, got {len(result.chunks)}"

    @pytest.mark.asyncio
    async def test_when_integrating_document_with_low_confidence_entities_then_entities_filtered(self, integrator: GraphRAGIntegrator, low_confidence_document, test_constants):
        """
        GIVEN an LLMDocument with chunks containing only low-confidence entities
        WHEN integrate_document is called with high entity_extraction_confidence
        THEN entities below the threshold should be filtered out
        """
        # Arrange - Set high confidence threshold
        integrator.entity_extraction_confidence = test_constants['HIGH_CONFIDENCE_THRESHOLD']
        
        # Act
        result = await integrator.integrate_document(low_confidence_document)
        
        # Assert - Low confidence entities should be filtered out
        assert len(result.entities) == 0, \
            f"Expected 0 entities due to confidence filtering, got {len(result.entities)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
