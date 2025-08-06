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
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator, KnowledgeGraph, Entity, Relationship
from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk


from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

home_dir = os.path.expanduser('~')
file_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/graphrag_integrator.py")
md_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/graphrag_integrator_stubs.md")

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

from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk.llm_chunk_factory import (
    LLMChunkTestDataFactory as ChunkDataFactory
)

from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_factory import (
    LLMChunkMetadataTestDataFactory as MetadataFactory
)


ENTITY_EXTRACTION_CONFIDENCE = 0.7  # Minimum confidence for entity extraction


class TestExtractEntitiesFromChunks:
    """Test class for GraphRAGIntegrator._extract_entities_from_chunks method."""

    @pytest.fixture
    def mock_integrator(self):
        """Create a mock GraphRAGIntegrator for testing."""
        integrator = GraphRAGIntegrator(entity_extraction_confidence=ENTITY_EXTRACTION_CONFIDENCE)
        integrator._extract_entities_from_text = AsyncMock()
        return integrator

    @property
    def sample_metadata(self):
        """Create sample metadata for LLMChunk objects."""
        return LLMChunkMetadata(**MetadataFactory.create_valid_baseline_data())

    @pytest.fixture
    def sample_chunks(self):
        """Create sample LLMChunk objects for testing."""
        return [
            LLMChunk(
                content="Apple Inc. was founded by Steve Jobs in Cupertino.",
                chunk_id="chunk_1",
                source_page=1,
                source_elements=["paragraph"],
                token_count=12,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata,
                embedding=None
            ),
            LLMChunk(
                content="Steve Jobs became CEO of Apple Inc. in 1997.",
                chunk_id="chunk_2",
                source_page=1,
                source_elements=["paragraph"],
                token_count=10,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata,
                embedding=None
            ),
            LLMChunk(
                content="Microsoft Corporation is based in Redmond, Washington.",
                chunk_id="chunk_3",
                source_page=2,
                source_elements=["paragraph"],
                token_count=10,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata,
                embedding=None
            )
        ]

    @pytest.fixture
    def sample_entity_dicts(self):
        """Create sample entity dictionaries as returned by _extract_entities_from_text."""
        return [
            {
                'id': 'apple_inc_org',
                'name': 'Apple Inc.',
                'type': 'organization',
                'description': 'Technology company',
                'confidence': 0.9,
                'properties': {'founded': '1976'}
            },
            {
                'id': 'steve_jobs_person',
                'name': 'Steve Jobs',
                'type': 'person',
                'description': 'Co-founder of Apple Inc.',
                'confidence': 0.95,
                'properties': {'role': 'CEO'}
            },
            {
                'id': 'cupertino_location',
                'name': 'Cupertino',
                'type': 'location',
                'description': 'City in California',
                'confidence': 0.8,
                'properties': {'state': 'California'}
            }
        ]

    @pytest.mark.asyncio
    async def test_extract_entities_from_chunks_valid_input(self, mock_integrator, sample_chunks, sample_entity_dicts):
        """
        GIVEN valid LLMChunk objects with extractable entities
        WHEN _extract_entities_from_chunks is called
        THEN entities should be extracted and consolidated correctly
        AND duplicate entities should be merged
        AND confidence scores should be maximized
        """
        # Mock the _extract_entities_from_text method to return sample entities
        mock_integrator._extract_entities_from_text.side_effect = [
            [sample_entity_dicts[0], sample_entity_dicts[1]],  # chunk_1: Apple Inc, Steve Jobs
            [sample_entity_dicts[1]],  # chunk_2: Steve Jobs (duplicate)
            [sample_entity_dicts[2]]   # chunk_3: Cupertino
        ]
        
        result = await mock_integrator._extract_entities_from_chunks(sample_chunks)
        
        # Verify all chunks were processed
        assert mock_integrator._extract_entities_from_text.call_count == 3
        
        # Verify returned entities
        assert isinstance(result, list)
        assert len(result) == 3  # All 3 unique entities (Steve Jobs deduplicated)
        
        # Check that Entity objects were created with proper structure
        for entity in result:
            assert hasattr(entity, 'id')
            assert hasattr(entity, 'name')
            assert hasattr(entity, 'type')
            assert hasattr(entity, 'confidence')
            assert hasattr(entity, 'source_chunks')
            assert isinstance(entity.source_chunks, list)
        
        # Verify deduplication - Steve Jobs should appear in two chunks
        steve_jobs_entity = next((e for e in result if e.name == 'Steve Jobs'), None)
        assert steve_jobs_entity is not None
        assert len(steve_jobs_entity.source_chunks) == 2  # chunk_1 and chunk_2
        assert steve_jobs_entity.confidence == 0.95  # Maximum confidence
        
        # Should have Apple Inc., Steve Jobs, and Cupertino
        entity_names = {entity.name for entity in result}
        expected_names = {'Apple Inc.', 'Steve Jobs', 'Cupertino'}
        assert entity_names == expected_names

    @pytest.mark.asyncio
    async def test_extract_entities_from_chunks_empty_list(self, mock_integrator):
        """
        GIVEN an empty list of chunks
        WHEN _extract_entities_from_chunks is called
        THEN an empty list should be returned
        AND no entity extraction should be attempted
        """
        result = await mock_integrator._extract_entities_from_chunks([])
        
        assert result == []
        mock_integrator._extract_entities_from_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_entities_from_chunks_single_chunk(self, mock_integrator):
        """
        GIVEN a single LLMChunk with entities
        WHEN _extract_entities_from_chunks is called
        THEN entities should be extracted from that chunk
        AND entity IDs should be generated consistently
        AND source_chunks should contain the chunk ID
        """
        single_chunk = [LLMChunk(
            chunk_id="single_chunk",
            content="Tesla Inc. was founded by Elon Musk.",
            source_page=1,
            source_elements=["paragraph"],
            token_count=10,
            semantic_types="text",
            relationships=[],
            metadata=self.sample_metadata,
            embedding=None
        )]
        
        single_entity_dict = [[{
            'name': 'Tesla Inc.',
            'type': 'organization',
            'description': 'Electric vehicle company',
            'confidence': 0.8,
            'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'single_chunk'}
        }]]
        
        mock_integrator._extract_entities_from_text.side_effect = single_entity_dict
        
        result = await mock_integrator._extract_entities_from_chunks(single_chunk)
        
        assert len(result) == 1
        entity = result[0]
        assert entity.name == 'Tesla Inc.'
        assert 'single_chunk' in entity.source_chunks
        assert entity.id  # Should have a generated ID

    @pytest.mark.asyncio
    async def test_extract_entities_from_chunks_duplicate_entities_same_chunk(self, mock_integrator):
        """
        GIVEN a chunk containing the same entity mentioned multiple times
        WHEN _extract_entities_from_chunks is called
        THEN only one instance of the entity should be returned
        AND the confidence should be the maximum found
        AND source_chunks should list the chunk only once
        """
        duplicate_chunk = [LLMChunk(
            chunk_id="dup_chunk",
            content="Apple Inc. develops products. Apple Inc. is innovative.",
            source_page=1,
            source_elements=["paragraph"],
            token_count=15,
            semantic_types="text",
            relationships=[],
            metadata=self.sample_metadata,
            embedding=None
        )]
        
        # Simulate same entity extracted multiple times with different confidence
        duplicate_entities = [[
            {
                'name': 'Apple Inc.',
                'type': 'organization',
                'description': 'Technology company',
                'confidence': 0.8,
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'dup_chunk'}
            },
            {
                'name': 'Apple Inc.',
                'type': 'organization',
                'description': 'Technology company',
                'confidence': 0.9,  # Higher confidence
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'dup_chunk'}
            }
        ]]
        
        mock_integrator._extract_entities_from_text.side_effect = duplicate_entities
        
        result = await mock_integrator._extract_entities_from_chunks(duplicate_chunk)
        
        assert len(result) == 1
        entity = result[0]
        assert entity.name == 'Apple Inc.'
        assert entity.confidence == 0.9  # Should take maximum confidence
        assert entity.source_chunks == ['dup_chunk']  # Should appear only once

    @pytest.mark.asyncio
    async def test_extract_entities_from_chunks_duplicate_entities_different_chunks(self, mock_integrator):
        """
        GIVEN multiple chunks containing the same entity
        WHEN _extract_entities_from_chunks is called
        THEN only one instance of the entity should be returned
        AND source_chunks should include all relevant chunk IDs
        AND confidence should be the maximum across all mentions
        AND properties should be merged from all mentions
        """
        multi_chunks = [
            LLMChunk(chunk_id="chunk_a", content="Google was founded in 1998.", source_page=1, source_elements=["paragraph"], token_count=8, semantic_types="text", relationships=[], metadata=self.sample_metadata, embedding=None),
            LLMChunk(chunk_id="chunk_b", content="Google LLC is a search company.", source_page=1, source_elements=["paragraph"], token_count=8, semantic_types="text", relationships=[], metadata=self.sample_metadata, embedding=None)
        ]
        
        multi_entity_dicts = [
            [{
                'name': 'Google',
                'type': 'organization',
                'description': 'Search company',
                'confidence': 0.8,
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'chunk_a', 'founded': '1998'}
            }],
            [{
                'name': 'Google',
                'type': 'organization',
                'description': 'Search company',
                'confidence': 0.9,
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'chunk_b', 'type': 'LLC'}
            }]
        ]
        
        mock_integrator._extract_entities_from_text.side_effect = multi_entity_dicts
        
        result = await mock_integrator._extract_entities_from_chunks(multi_chunks)
        
        assert len(result) == 1
        entity = result[0]
        assert entity.name == 'Google'
        assert entity.confidence == 0.9  # Maximum confidence
        assert set(entity.source_chunks) == {'chunk_a', 'chunk_b'}
        # Properties should be merged
        assert 'founded' in entity.properties
        assert 'type' in entity.properties

    @pytest.mark.asyncio
    async def test_extract_entities_from_chunks_case_insensitive_deduplication(self, mock_integrator):
        """
        GIVEN chunks with entities that differ only in case (e.g., "Apple" vs "apple")
        WHEN _extract_entities_from_chunks is called
        THEN entities should be deduplicated in a case-insensitive manner
        AND the canonical name should be preserved from first occurrence
        """
        case_chunks = [
            LLMChunk(chunk_id="chunk_1", content="Apple Inc. is great.", source_page=1, source_elements=["paragraph"], token_count=6, semantic_types="text", relationships=[], metadata=self.sample_metadata, embedding=None),
            LLMChunk(chunk_id="chunk_2", content="apple inc. makes phones.", source_page=1, source_elements=["paragraph"], token_count=6, semantic_types="text", relationships=[], metadata=self.sample_metadata, embedding=None)
        ]
        
        case_entity_dicts = [
            [{
                'name': 'Apple Inc.',
                'type': 'organization',
                'description': 'Technology company',
                'confidence': 0.8,
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'chunk_1'}
            }],
            [{
                'name': 'apple inc.',
                'type': 'organization',
                'description': 'Technology company',
                'confidence': 0.75,
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'chunk_2'}
            }]
        ]
        
        mock_integrator._extract_entities_from_text.side_effect = case_entity_dicts
        
        result = await mock_integrator._extract_entities_from_chunks(case_chunks)
        
        assert len(result) == 1
        entity = result[0]
        assert entity.name == 'Apple Inc.'  # Should preserve first occurrence case
        assert set(entity.source_chunks) == {'chunk_1', 'chunk_2'}

    @pytest.mark.asyncio
    async def test_extract_entities_from_chunks_confidence_filtering(self, mock_integrator):
        """
        GIVEN chunks with entities of varying confidence levels
        WHEN _extract_entities_from_chunks is called
        THEN only entities with confidence >= entity_extraction_confidence should be returned
        AND low-confidence entities should be filtered out
        """
        # Set threshold to 0.7
        mock_integrator.entity_extraction_confidence = 0.7
        
        conf_chunks = [LLMChunk(
            chunk_id="conf_chunk",
            content="Various entities with different confidence levels.",
            source_page=1,
            source_elements=["paragraph"],
            token_count=8,
            semantic_types="text",
            relationships=[],
            metadata=self.sample_metadata,
            embedding=None
        )]
        
        mixed_confidence_entities = [[
            {
                'name': 'High Confidence Entity',
                'type': 'organization',
                'description': 'Highly confident',
                'confidence': 0.9,  # Above threshold
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'conf_chunk'}
            },
            {
                'name': 'Low Confidence Entity',
                'type': 'person',
                'description': 'Low confidence',
                'confidence': 0.5,  # Below threshold
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'conf_chunk'}
            },
            {
                'name': 'Borderline Entity',
                'type': 'location',
                'description': 'Exactly at threshold',
                'confidence': 0.7,  # Exactly at threshold
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'conf_chunk'}
            }
        ]]
        
        mock_integrator._extract_entities_from_text.side_effect = mixed_confidence_entities
        
        result = await mock_integrator._extract_entities_from_chunks(conf_chunks)
        
        # Should only include entities with confidence >= 0.7
        assert len(result) == 2
        entity_names = [entity.name for entity in result]
        assert 'High Confidence Entity' in entity_names
        assert 'Borderline Entity' in entity_names
        assert 'Low Confidence Entity' not in entity_names

    @pytest.mark.asyncio
    async def test_extract_entities_from_chunks_property_merging(self, mock_integrator):
        """
        GIVEN the same entity appears in multiple chunks with different properties
        WHEN _extract_entities_from_chunks is called
        THEN properties should be merged across all mentions
        AND conflicts should be resolved by first occurrence
        AND all unique properties should be preserved
        """
        prop_chunks = [
            LLMChunk(chunk_id="chunk_1", content="Amazon was founded in 1994.", source_page=1, source_elements=["paragraph"], token_count=8, semantic_types="text", relationships=[], metadata=self.sample_metadata, embedding=None),
            LLMChunk(chunk_id="chunk_2", content="Amazon is in Seattle.", source_page=1, source_elements=["paragraph"], token_count=5, semantic_types="text", relationships=[], metadata=self.sample_metadata, embedding=None)
        ]
        
        property_entity_dicts = [
            [{
                'name': 'Amazon',
                'type': 'organization',
                'description': 'E-commerce company',
                'confidence': 0.8,
                'properties': {
                    'extraction_method': 'regex_pattern_matching',
                    'source_chunk': 'chunk_1',
                    'founded': '1994',
                    'industry': 'e-commerce'
                }
            }],
            [{
                'name': 'Amazon',
                'type': 'organization',
                'description': 'Technology company',
                'confidence': 0.85,
                'properties': {
                    'extraction_method': 'regex_pattern_matching',
                    'source_chunk': 'chunk_2',
                    'location': 'Seattle',
                    'industry': 'technology'  # Conflict with first occurrence
                }
            }]
        ]
        
        mock_integrator._extract_entities_from_text.side_effect = property_entity_dicts
        
        result = await mock_integrator._extract_entities_from_chunks(prop_chunks)
        
        assert len(result) == 1
        entity = result[0]
        assert entity.properties['founded'] == '1994'
        assert entity.properties['location'] == 'Seattle'
        assert entity.properties['industry'] == 'e-commerce'  # First occurrence wins

    @pytest.mark.asyncio
    async def test_extract_entities_from_chunks_entity_id_generation(self, mock_integrator):
        """
        GIVEN entities with the same name and type
        WHEN _extract_entities_from_chunks is called
        THEN they should generate the same entity ID
        AND the ID should be based on name and type hash
        AND IDs should be consistent across multiple calls
        """
        id_chunks = [
            LLMChunk(chunk_id="chunk_1", content="Netflix is streaming.", source_page=1, source_elements=["paragraph"], token_count=4, semantic_types="text", relationships=[], metadata=self.sample_metadata, embedding=None),
            LLMChunk(chunk_id="chunk_2", content="Netflix has shows.", source_page=1, source_elements=["paragraph"], token_count=4, semantic_types="text", relationships=[], metadata=self.sample_metadata, embedding=None)
        ]
        
        id_entity_dicts = [
            [{
                'name': 'Netflix',
                'type': 'organization',
                'description': 'Streaming service',
                'confidence': 0.8,
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'chunk_1'}
            }],
            [{
                'name': 'Netflix',
                'type': 'organization',
                'description': 'Entertainment company',
                'confidence': 0.85,
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'chunk_2'}
            }]
        ]
        
        mock_integrator._extract_entities_from_text.side_effect = id_entity_dicts
        
        result1 = await mock_integrator._extract_entities_from_chunks(id_chunks)
        
        # Reset mock and call again
        mock_integrator._extract_entities_from_text.side_effect = id_entity_dicts
        result2 = await mock_integrator._extract_entities_from_chunks(id_chunks)
        
        assert len(result1) == 1
        assert len(result2) == 1
        assert result1[0].id == result2[0].id  # Should be consistent

    @pytest.mark.asyncio
    async def test_extract_entities_from_chunks_different_entity_types(self, mock_integrator):
        """
        GIVEN chunks containing entities of different types (person, organization, location, etc.)
        WHEN _extract_entities_from_chunks is called
        THEN all entity types should be extracted and preserved
        AND type-specific properties should be handled correctly
        """
        type_chunks = [LLMChunk(
            chunk_id="type_chunk",
            content="John Doe works at IBM in New York on 2024-01-15 for $100,000.",
            source_page=1,
            source_elements=["paragraph"],
            token_count=15,
            semantic_types="text",
            relationships=[],
            metadata=self.sample_metadata,
            embedding=None
        )]
        
        mixed_type_entities = [[
            {
                'name': 'John Doe',
                'type': 'person',
                'description': 'Person mentioned in document',
                'confidence': 0.9,
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'type_chunk'}
            },
            {
                'name': 'IBM',
                'type': 'organization',
                'description': 'Technology company',
                'confidence': 0.85,
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'type_chunk'}
            },
            {
                'name': 'New York',
                'type': 'location',
                'description': 'Geographic location',
                'confidence': 0.8,
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'type_chunk'}
            },
            {
                'name': '2024-01-15',
                'type': 'date',
                'description': 'Date mentioned in document',
                'confidence': 0.75,
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'type_chunk'}
            },
            {
                'name': '$100,000',
                'type': 'currency',
                'description': 'Currency amount mentioned in document',
                'confidence': 0.8,
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'type_chunk'}
            }
        ]]
        
        mock_integrator._extract_entities_from_text.side_effect = mixed_type_entities
        
        result = await mock_integrator._extract_entities_from_chunks(type_chunks)
        
        assert len(result) == 5
        entity_types = [entity.type for entity in result]
        expected_types = {'person', 'organization', 'location', 'date', 'currency'}
        assert set(entity_types) == expected_types

    @pytest.mark.asyncio
    async def test_extract_entities_from_chunks_chunk_without_entities(self, mock_integrator):
        """
        GIVEN chunks that contain no extractable entities
        WHEN _extract_entities_from_chunks is called
        THEN an empty list should be returned for those chunks
        AND no errors should be raised
        """
        empty_chunks = [
            LLMChunk(
                chunk_id="empty_1",
                content="This is just plain text without any entities.",
                source_page=1,
                source_elements=["paragraph"],
                token_count=10,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata,
                embedding=None
            ),
            LLMChunk(
                chunk_id="empty_2", 
                content="More text that has no named entities.",
                source_page=1,
                source_elements=["paragraph"],
                token_count=8,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata,
                embedding=None
            )
        ]
        
        # Mock returns empty lists for both chunks
        mock_integrator._extract_entities_from_text.side_effect = [[], []]
        
        result = await mock_integrator._extract_entities_from_chunks(empty_chunks)
        
        assert result == []
        assert mock_integrator._extract_entities_from_text.call_count == 2

    @pytest.mark.asyncio
    async def test_extract_entities_from_chunks_invalid_chunk_type(self, mock_integrator):
        """
        GIVEN a list containing non-LLMChunk objects
        WHEN _extract_entities_from_chunks is called
        THEN a TypeError should be raised
        AND the error should indicate expected chunk type
        """
        invalid_chunks = ["not_a_chunk", {"also": "not_a_chunk"}, 123]
        
        with pytest.raises(TypeError) as exc_info:
            await mock_integrator._extract_entities_from_chunks(invalid_chunks)
        
        assert "All chunks must be LLMChunk instances" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_extract_entities_from_chunks_chunk_missing_content(self, mock_integrator):
        """
        GIVEN chunks that are missing content attribute
        WHEN _extract_entities_from_chunks is called
        THEN an AttributeError should be raised
        AND the error should indicate missing content
        """
        invalid_chunk = MagicMock(spec_set=LLMChunk)
        del invalid_chunk.content  # Remove content attribute

        invalid_chunks = [invalid_chunk]
        
        with pytest.raises(AttributeError) as exc_info:
            await mock_integrator._extract_entities_from_chunks(invalid_chunks)
        
        assert "content" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_extract_entities_from_chunks_chunk_missing_chunk_id(self, mock_integrator):
        """
        GIVEN chunks that are missing chunk_id attribute
        WHEN _extract_entities_from_chunks is called
        THEN an AttributeError should be raised
        AND the error should indicate missing chunk_id
        """
        invalid_chunk = MagicMock(spec_set=LLMChunk)
        del invalid_chunk.chunk_id  # Remove content attribute

        invalid_chunks = [invalid_chunk]
        
        with pytest.raises(AttributeError) as exc_info:
            await mock_integrator._extract_entities_from_chunks(invalid_chunks)
        
        assert "chunk_id" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_extract_entities_from_chunks_extraction_service_failure(self, mock_integrator, sample_chunks):
        """
        GIVEN the underlying entity extraction service fails
        WHEN _extract_entities_from_chunks is called
        THEN the original exception should be propagated
        AND no partial results should be returned
        """
        mock_integrator._extract_entities_from_text.side_effect = Exception("Entity extraction service failed")
        
        with pytest.raises(RuntimeError) as exc_info:
            await mock_integrator._extract_entities_from_chunks(sample_chunks)
        
        assert "Entity extraction service failed" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_extract_entities_from_chunks_large_number_of_chunks(self, mock_integrator):
        """
        GIVEN a large number of chunks (>100)
        WHEN _extract_entities_from_chunks is called
        THEN all chunks should be processed
        AND performance should remain reasonable
        AND memory usage should not grow excessively
        """
        large_chunks = [
            LLMChunk(
                chunk_id=f"chunk_{i}",
                content=f"Entity{i} Corp is a company.",
                source_page=i // 10 + 1,
                source_elements=["paragraph"],
                token_count=7,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata,
                embedding=None
            ) for i in range(150)
        ]
        
        # Mock returns one entity per chunk
        mock_responses = [
            [{
                'name': f'Entity{i} Corp',
                'type': 'organization',
                'description': 'Company',
                'confidence': 0.8,
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': f'chunk_{i}'}
            }] for i in range(150)
        ]
        
        mock_integrator._extract_entities_from_text.side_effect = mock_responses
        

        start_time = time.time()
        result = await mock_integrator._extract_entities_from_chunks(large_chunks)
        end_time = time.time()
        
        # Should process all chunks
        assert len(result) == 150
        assert mock_integrator._extract_entities_from_text.call_count == 150
        
        # Should complete in reasonable time
        assert end_time - start_time < 30  # 30 seconds max

    @pytest.mark.asyncio
    async def test_extract_entities_from_chunks_entity_consolidation_order(self, mock_integrator):
        """
        GIVEN chunks processed in a specific order with duplicate entities
        WHEN _extract_entities_from_chunks is called
        THEN entity consolidation should be order-independent
        AND the final result should be deterministic
        """
        order_chunks = [
            LLMChunk(chunk_id="first", content="Facebook is social.", source_page=1, source_elements=["paragraph"], token_count=4, semantic_types="text", relationships=[], metadata=self.sample_metadata, embedding=None),
            LLMChunk(chunk_id="second", content="Facebook connects people.", source_page=1, source_elements=["paragraph"], token_count=4, semantic_types="text", relationships=[], metadata=self.sample_metadata, embedding=None)
        ]
        
        order_entity_dicts = [
            [{
                'name': 'Facebook',
                'type': 'organization',
                'description': 'Social media company',
                'confidence': 0.8,
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'first', 'purpose': 'social'}
            }],
            [{
                'name': 'Facebook',
                'type': 'organization',
                'description': 'Social media company',
                'confidence': 0.9,
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'second', 'purpose': 'connecting'}
            }]
        ]
        
        # Test first order
        mock_integrator._extract_entities_from_text.side_effect = order_entity_dicts
        result1 = await mock_integrator._extract_entities_from_chunks(order_chunks)
        
        # Test reverse order
        reversed_chunks = list(reversed(order_chunks))
        reversed_dicts = list(reversed(order_entity_dicts))
        mock_integrator._extract_entities_from_text.side_effect = reversed_dicts
        result2 = await mock_integrator._extract_entities_from_chunks(reversed_chunks)
        
        # Results should be consistent regardless of order
        assert len(result1) == len(result2) == 1
        assert result1[0].name == result2[0].name
        assert result1[0].confidence == result2[0].confidence == 0.9  # Max confidence

    @pytest.mark.asyncio
    async def test_extract_entities_from_chunks_confidence_maximization(self, mock_integrator):
        """
        GIVEN the same entity appears with different confidence scores across chunks
        WHEN _extract_entities_from_chunks is called
        THEN the final entity should have the maximum confidence score
        AND the confidence should be correctly updated during consolidation
        """
        conf_chunks = [
            LLMChunk(chunk_id="low_conf", content="Twitter is a platform.", source_page=1, source_elements=["paragraph"], token_count=5, semantic_types="text", relationships=[], metadata=self.sample_metadata, embedding=None),
            LLMChunk(chunk_id="high_conf", content="Twitter Inc. is social media.", source_page=1, source_elements=["paragraph"], token_count=6, semantic_types="text", relationships=[], metadata=self.sample_metadata, embedding=None),
            LLMChunk(chunk_id="med_conf", content="Twitter has users.", source_page=1, source_elements=["paragraph"], token_count=4, semantic_types="text", relationships=[], metadata=self.sample_metadata, embedding=None)
        ]
        
        confidence_entity_dicts = [
            [{
                'name': 'Twitter',
                'type': 'organization',
                'description': 'Social media platform',
                'confidence': 0.7,
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'low_conf'}
            }],
            [{
                'name': 'Twitter',
                'type': 'organization',
                'description': 'Social media platform',
                'confidence': 0.95,  # Highest
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'high_conf'}
            }],
            [{
                'name': 'Twitter',
                'type': 'organization',
                'description': 'Social media platform',
                'confidence': 0.8,
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'med_conf'}
            }]
        ]
        
        mock_integrator._extract_entities_from_text.side_effect = confidence_entity_dicts
        
        result = await mock_integrator._extract_entities_from_chunks(conf_chunks)
        
        assert len(result) == 1
        entity = result[0]
        assert entity.confidence == 0.95  # Should take maximum

    @pytest.mark.asyncio
    async def test_extract_entities_from_chunks_source_chunks_accumulation(self, mock_integrator):
        """
        GIVEN the same entity appears in multiple chunks
        WHEN _extract_entities_from_chunks is called
        THEN the source_chunks list should contain all chunk IDs where the entity appears
        AND there should be no duplicate chunk IDs in the list
        AND the order should be preserved
        """
        source_chunks = [
            LLMChunk(chunk_id="chunk_a", content="LinkedIn is professional.", source_page=1, source_elements=["paragraph"], token_count=4, semantic_types="text", relationships=[], metadata=self.sample_metadata, embedding=None),
            LLMChunk(chunk_id="chunk_b", content="LinkedIn connects professionals.", source_page=1, source_elements=["paragraph"], token_count=4, semantic_types="text", relationships=[], metadata=self.sample_metadata, embedding=None),
            LLMChunk(chunk_id="chunk_c", content="LinkedIn has job listings.", source_page=2, source_elements=["paragraph"], token_count=5, semantic_types="text", relationships=[], metadata=self.sample_metadata, embedding=None)
        ]
        
        source_entity_dicts = [
            [{
                'name': 'LinkedIn',
                'type': 'organization',
                'description': 'Professional network',
                'confidence': 0.8,
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'chunk_a'}
            }],
            [{
                'name': 'LinkedIn',
                'type': 'organization',
                'description': 'Professional network',
                'confidence': 0.85,
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'chunk_b'}
            }],
            [{
                'name': 'LinkedIn',
                'type': 'organization',
                'description': 'Professional network',
                'confidence': 0.9,
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'chunk_c'}
            }]
        ]
        
        mock_integrator._extract_entities_from_text.side_effect = source_entity_dicts
        
        result = await mock_integrator._extract_entities_from_chunks(source_chunks)
        
        assert len(result) == 1
        entity = result[0]
        assert entity.source_chunks == ['chunk_a', 'chunk_b', 'chunk_c']
        assert len(set(entity.source_chunks)) == len(entity.source_chunks)  # No duplicates

    @pytest.mark.asyncio
    async def test_extract_entities_from_chunks_empty_chunk_content(self, mock_integrator):
        """
        GIVEN chunks with empty or whitespace-only content
        WHEN _extract_entities_from_chunks is called
        THEN these chunks should be handled gracefully
        AND no entities should be extracted from empty content
        AND no errors should be raised
        """
        empty_content_chunks = [
            LLMChunk(chunk_id="empty", content="", source_page=1, source_elements=["paragraph"], token_count=0, semantic_types="text", relationships=[], metadata=self.sample_metadata, embedding=None),
            LLMChunk(chunk_id="whitespace", content="   \n\t  ", source_page=1, source_elements=["paragraph"], token_count=0, semantic_types="text", relationships=[], metadata=self.sample_metadata, embedding=None),
            LLMChunk(chunk_id="valid", content="Tesla makes cars.", source_page=1, source_elements=["paragraph"], token_count=4, semantic_types="text", relationships=[], metadata=self.sample_metadata, embedding=None)
        ]
        
        empty_responses = [
            [],  # Empty content
            [],  # Whitespace only
            [{  # Valid content
                'name': 'Tesla',
                'type': 'organization',
                'description': 'Electric vehicle company',
                'confidence': 0.8,
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'valid'}
            }]
        ]
        
        mock_integrator._extract_entities_from_text.side_effect = empty_responses
        
        result = await mock_integrator._extract_entities_from_chunks(empty_content_chunks)
        
        assert len(result) == 1  # Only the valid chunk should produce entities
        assert result[0].name == 'Tesla'

    @pytest.mark.asyncio
    async def test_extract_entities_from_chunks_special_characters_in_content(self, mock_integrator):
        """
        GIVEN chunks containing special characters, unicode, or non-standard text
        WHEN _extract_entities_from_chunks is called
        THEN entity extraction should handle these characters gracefully
        AND entities with special characters should be extracted correctly
        """
        special_chunks = [LLMChunk(
            chunk_id="special",
            content="Café René's company makes naïve AI systems with $1,000€ budget.",
            source_page=1,
            source_elements=["paragraph"],
            token_count=15,
            semantic_types="text",
            relationships=[],
            metadata=self.sample_metadata,
            embedding=None
        )]
        
        special_entities = [[
            {
                'name': "Café René's company",
                'type': 'organization',
                'description': 'Company with special characters',
                'confidence': 0.8,
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'special'}
            },
            {
                'name': '$1,000€',
                'type': 'currency',
                'description': 'Mixed currency format',
                'confidence': 0.75,
                'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'special'}
            }
        ]]
        
        mock_integrator._extract_entities_from_text.side_effect = special_entities
        
        result = await mock_integrator._extract_entities_from_chunks(special_chunks)
        
        assert len(result) == 2
        entity_names = [entity.name for entity in result]
        assert "Café René's company" in entity_names
        assert '$1,000€' in entity_names

    @pytest.mark.asyncio
    async def test_extract_entities_from_chunks_none_chunks_in_list(self, mock_integrator):
        """
        GIVEN a list containing None values mixed with valid chunks
        WHEN _extract_entities_from_chunks is called
        THEN a TypeError should be raised
        AND the error should indicate invalid chunk types
        """
        mixed_chunks = [
            LLMChunk(chunk_id="valid", content="Valid chunk.", source_page=1, source_elements=["paragraph"], token_count=3, semantic_types="text", relationships=[], metadata=self.sample_metadata, embedding=None),
            None,
            LLMChunk(chunk_id="also_valid", content="Another valid chunk.", source_page=1, source_elements=["paragraph"], token_count=4, semantic_types="text", relationships=[], metadata=self.sample_metadata, embedding=None)
        ]
        
        with pytest.raises(TypeError) as exc_info:
            await mock_integrator._extract_entities_from_chunks(mixed_chunks)
        
        assert "All chunks must be LLMChunk instances" in str(exc_info.value)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
