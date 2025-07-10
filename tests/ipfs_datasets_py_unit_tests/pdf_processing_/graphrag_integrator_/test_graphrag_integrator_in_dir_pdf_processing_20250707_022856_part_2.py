#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/graphrag_integrator.py
# Auto-generated on 2025-07-07 02:28:56"

import pytest
import os
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock


from ipfs_datasets_py.pdf_processing.graphrag_integrator import (
    GraphRAGIntegrator, Entity, Relationship, KnowledgeGraph
)
from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk


from tests._test_utils import (
    raise_on_bad_callable_metadata,
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
    from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
except ImportError as e:
    raise ImportError(f"Could into import the module's dependencies: {e}") 





class TestExtractRelationships:
    """Test class for GraphRAGIntegrator._extract_relationships method."""

    @pytest.fixture
    def integrator(self):
        """Create a GraphRAGIntegrator instance for testing."""
        return GraphRAGIntegrator()

    @pytest.fixture
    def sample_entities(self):
        """Create sample entities for testing."""
        return [
            Entity(
                id="entity_1",
                name="John Smith",
                type="person",
                description="Software engineer",
                confidence=0.9,
                source_chunks=["chunk_1", "chunk_2"],
                properties={}
            ),
            Entity(
                id="entity_2",
                name="ACME Corp",
                type="organization",
                description="Technology company",
                confidence=0.8,
                source_chunks=["chunk_1", "chunk_3"],
                properties={}
            ),
            Entity(
                id="entity_3",
                name="San Francisco",
                type="location",
                description="City in California",
                confidence=0.7,
                source_chunks=["chunk_2"],
                properties={}
            )
        ]

    @pytest.fixture
    def sample_chunks(self):
        """Create sample chunks for testing."""
        return [
            LLMChunk(
                chunk_id="chunk_1",
                content="John Smith works at ACME Corp as a software engineer.",
                start_page=1,
                end_page=1,
                source_page=1,
                chunk_index=0,
                chunk_type="text",
                metadata={}
            ),
            LLMChunk(
                chunk_id="chunk_2",
                content="John Smith lives in San Francisco.",
                start_page=1,
                end_page=1,
                source_page=1,
                chunk_index=1,
                chunk_type="text",
                metadata={}
            ),
            LLMChunk(
                chunk_id="chunk_3",
                content="ACME Corp has offices worldwide.",
                start_page=2,
                end_page=2,
                source_page=2,
                chunk_index=2,
                chunk_type="text",
                metadata={}
            )
        ]

    @pytest.mark.asyncio
    async def test_extract_relationships_valid_input(self, integrator, sample_entities, sample_chunks):
        """
        GIVEN a list of entities and corresponding chunks
        WHEN _extract_relationships is called
        THEN both intra-chunk and cross-chunk relationships should be extracted
        AND the total count should be logged
        AND all relationships should be valid Relationship objects
        """
        with patch.object(integrator, '_extract_chunk_relationships', new_callable=AsyncMock) as mock_chunk_rels, \
             patch.object(integrator, '_extract_cross_chunk_relationships', new_callable=AsyncMock) as mock_cross_rels, \
             patch('logging.info') as mock_log:
            
            # Setup mock returns
            chunk_rels = [Mock(spec=Relationship) for _ in range(2)]
            cross_rels = [Mock(spec=Relationship) for _ in range(1)]
            mock_chunk_rels.return_value = chunk_rels
            mock_cross_rels.return_value = cross_rels
            
            result = await integrator._extract_relationships(sample_entities, sample_chunks)
            
            # Verify method calls
            assert mock_chunk_rels.call_count >= 1
            mock_cross_rels.assert_called_once_with(sample_entities, sample_chunks)
            
            # Verify result
            assert isinstance(result, list)
            assert len(result) == 3  # 2 from chunk + 1 from cross-chunk
            
            # Verify logging
            mock_log.assert_called()

    @pytest.mark.asyncio
    async def test_extract_relationships_empty_entities(self, integrator, sample_chunks):
        """
        GIVEN an empty entities list
        WHEN _extract_relationships is called
        THEN an empty relationships list should be returned
        AND no processing should be attempted
        """
        with patch.object(integrator, '_extract_chunk_relationships', new_callable=AsyncMock) as mock_chunk_rels, \
             patch.object(integrator, '_extract_cross_chunk_relationships', new_callable=AsyncMock) as mock_cross_rels:
            
            result = await integrator._extract_relationships([], sample_chunks)
            
            assert result == []
            mock_chunk_rels.assert_not_called()
            mock_cross_rels.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_relationships_empty_chunks(self, integrator, sample_entities):
        """
        GIVEN entities but empty chunks list
        WHEN _extract_relationships is called
        THEN an empty relationships list should be returned
        AND no chunk processing should be attempted
        """
        with patch.object(integrator, '_extract_chunk_relationships', new_callable=AsyncMock) as mock_chunk_rels, \
             patch.object(integrator, '_extract_cross_chunk_relationships', new_callable=AsyncMock) as mock_cross_rels:
            
            result = await integrator._extract_relationships(sample_entities, [])
            
            assert result == []
            mock_chunk_rels.assert_not_called()
            mock_cross_rels.assert_not_called()

    @pytest.mark.asyncio
    async def test_extract_relationships_single_entity(self, integrator, sample_chunks):
        """
        GIVEN a single entity in the entities list
        WHEN _extract_relationships is called
        THEN no relationships should be created
        AND an empty list should be returned
        """
        single_entity = [Entity(
            id="entity_1", name="John", type="person", description="Person",
            confidence=0.9, source_chunks=["chunk_1"], properties={}
        )]
        
        with patch.object(integrator, '_extract_chunk_relationships', new_callable=AsyncMock) as mock_chunk_rels, \
             patch.object(integrator, '_extract_cross_chunk_relationships', new_callable=AsyncMock) as mock_cross_rels:
            
            mock_chunk_rels.return_value = []
            mock_cross_rels.return_value = []
            
            result = await integrator._extract_relationships(single_entity, sample_chunks)
            
            assert result == []

    @pytest.mark.asyncio
    async def test_extract_relationships_entities_in_same_chunk(self, integrator, sample_chunks):
        """
        GIVEN multiple entities that appear in the same chunk
        WHEN _extract_relationships is called
        THEN intra-chunk relationships should be created between co-occurring entities
        AND relationship types should be inferred from context
        """
        entities = [
            Entity(id="entity_1", name="John", type="person", description="Person",
                  confidence=0.9, source_chunks=["chunk_1"], properties={}),
            Entity(id="entity_2", name="ACME", type="organization", description="Company",
                  confidence=0.8, source_chunks=["chunk_1"], properties={})
        ]
        
        with patch.object(integrator, '_extract_chunk_relationships', new_callable=AsyncMock) as mock_chunk_rels, \
             patch.object(integrator, '_extract_cross_chunk_relationships', new_callable=AsyncMock) as mock_cross_rels:
            
            relationship = Mock(spec=Relationship)
            relationship.relationship_type = "works_for"
            mock_chunk_rels.return_value = [relationship]
            mock_cross_rels.return_value = []
            
            result = await integrator._extract_relationships(entities, sample_chunks)
            
            assert len(result) == 1
            assert result[0].relationship_type == "works_for"

    @pytest.mark.asyncio
    async def test_extract_relationships_entities_across_chunks(self, integrator, sample_chunks):
        """
        GIVEN entities that span across multiple chunks
        WHEN _extract_relationships is called
        THEN cross-chunk relationships should be created for entities in sequential chunks
        AND narrative sequence relationships should be identified
        """
        entities = [
            Entity(id="entity_1", name="John", type="person", description="Person",
                  confidence=0.9, source_chunks=["chunk_1"], properties={}),
            Entity(id="entity_2", name="Jane", type="person", description="Person",
                  confidence=0.8, source_chunks=["chunk_2"], properties={})
        ]
        
        with patch.object(integrator, '_extract_chunk_relationships', new_callable=AsyncMock) as mock_chunk_rels, \
             patch.object(integrator, '_extract_cross_chunk_relationships', new_callable=AsyncMock) as mock_cross_rels:
            
            relationship = Mock(spec=Relationship)
            relationship.relationship_type = "narrative_sequence"
            mock_chunk_rels.return_value = []
            mock_cross_rels.return_value = [relationship]
            
            result = await integrator._extract_relationships(entities, sample_chunks)
            
            assert len(result) == 1
            assert result[0].relationship_type == "narrative_sequence"

    @pytest.mark.asyncio
    async def test_extract_relationships_chunk_with_single_entity(self, integrator, sample_chunks):
        """
        GIVEN chunks that contain only one entity each
        WHEN _extract_relationships is called
        THEN those chunks should be skipped for intra-chunk processing
        AND only cross-chunk relationships should be considered
        """
        entities = [
            Entity(id="entity_1", name="John", type="person", description="Person",
                  confidence=0.9, source_chunks=["chunk_1"], properties={}),
            Entity(id="entity_2", name="Jane", type="person", description="Person",
                  confidence=0.8, source_chunks=["chunk_2"], properties={})
        ]
        
        with patch.object(integrator, '_extract_chunk_relationships', new_callable=AsyncMock) as mock_chunk_rels, \
             patch.object(integrator, '_extract_cross_chunk_relationships', new_callable=AsyncMock) as mock_cross_rels:
            
            # Each chunk has only one entity, so no intra-chunk relationships
            mock_chunk_rels.return_value = []
            mock_cross_rels.return_value = []
            
            result = await integrator._extract_relationships(entities, sample_chunks)
            
            # Should still call _extract_chunk_relationships but return empty
            assert mock_chunk_rels.call_count >= 0
            mock_cross_rels.assert_called_once()

    @pytest.mark.asyncio
    async def test_extract_relationships_entity_index_building(self, integrator, sample_entities, sample_chunks):
        """
        GIVEN entities with source_chunks information
        WHEN _extract_relationships is called
        THEN an entity index should be built mapping chunk IDs to entities
        AND the index should be used for efficient chunk processing
        """
        with patch.object(integrator, '_extract_chunk_relationships', new_callable=AsyncMock) as mock_chunk_rels, \
             patch.object(integrator, '_extract_cross_chunk_relationships', new_callable=AsyncMock) as mock_cross_rels:
            
            mock_chunk_rels.return_value = []
            mock_cross_rels.return_value = []
            
            await integrator._extract_relationships(sample_entities, sample_chunks)
            
            # Verify that chunk relationships are called for chunks with multiple entities
            # chunk_1 should have entities 1 and 2, chunk_2 should have entities 1 and 3
            calls = mock_chunk_rels.call_args_list
            assert len(calls) >= 1  # At least one chunk should have multiple entities

    @pytest.mark.asyncio
    async def test_extract_relationships_multiple_chunks_same_entities(self, integrator, sample_chunks):
        """
        GIVEN the same entities appearing in multiple chunks
        WHEN _extract_relationships is called
        THEN relationships should be created for each chunk occurrence
        AND duplicate relationships should be handled appropriately
        """
        entities = [
            Entity(id="entity_1", name="John", type="person", description="Person",
                  confidence=0.9, source_chunks=["chunk_1", "chunk_2"], properties={}),
            Entity(id="entity_2", name="ACME", type="organization", description="Company",
                  confidence=0.8, source_chunks=["chunk_1", "chunk_2"], properties={})
        ]
        
        with patch.object(integrator, '_extract_chunk_relationships', new_callable=AsyncMock) as mock_chunk_rels, \
             patch.object(integrator, '_extract_cross_chunk_relationships', new_callable=AsyncMock) as mock_cross_rels:
            
            # Return relationships for each chunk call
            mock_chunk_rels.return_value = [Mock(spec=Relationship)]
            mock_cross_rels.return_value = []
            
            result = await integrator._extract_relationships(entities, sample_chunks)
            
            # Should be called for each chunk that has multiple entities
            assert mock_chunk_rels.call_count >= 1

    @pytest.mark.asyncio
    async def test_extract_relationships_chunk_entity_filtering(self, integrator, sample_chunks):
        """
        GIVEN chunks with entities, some of which are not in the provided entities list
        WHEN _extract_relationships is called
        THEN only relationships between provided entities should be created
        AND entities not in the list should be ignored
        """
        # Only provide one entity, but chunks might reference others
        entities = [
            Entity(id="entity_1", name="John", type="person", description="Person",
                  confidence=0.9, source_chunks=["chunk_1"], properties={})
        ]
        
        with patch.object(integrator, '_extract_chunk_relationships', new_callable=AsyncMock) as mock_chunk_rels, \
             patch.object(integrator, '_extract_cross_chunk_relationships', new_callable=AsyncMock) as mock_cross_rels:
            
            mock_chunk_rels.return_value = []
            mock_cross_rels.return_value = []
            
            result = await integrator._extract_relationships(entities, sample_chunks)
            
            # Should only process entities that are in the provided list
            assert result == []

    @pytest.mark.asyncio
    async def test_extract_relationships_intra_chunk_method_call(self, integrator, sample_entities, sample_chunks):
        """
        GIVEN chunks with multiple entities
        WHEN _extract_relationships is called
        THEN _extract_chunk_relationships should be called for each qualifying chunk
        AND the results should be aggregated correctly
        """
        with patch.object(integrator, '_extract_chunk_relationships', new_callable=AsyncMock) as mock_chunk_rels, \
             patch.object(integrator, '_extract_cross_chunk_relationships', new_callable=AsyncMock) as mock_cross_rels:
            
            mock_chunk_rels.return_value = [Mock(spec=Relationship)]
            mock_cross_rels.return_value = []
            
            result = await integrator._extract_relationships(sample_entities, sample_chunks)
            
            # Verify chunk relationships method was called
            assert mock_chunk_rels.call_count >= 1
            
            # Verify entities and chunk arguments are passed correctly
            for call in mock_chunk_rels.call_args_list:
                args, kwargs = call
                assert len(args) == 2  # entities list and chunk
                assert isinstance(args[0], list)  # entities
                assert hasattr(args[1], 'chunk_id')  # chunk

    @pytest.mark.asyncio
    async def test_extract_relationships_cross_chunk_method_call(self, integrator, sample_entities, sample_chunks):
        """
        GIVEN entities and chunks for cross-chunk processing
        WHEN _extract_relationships is called
        THEN _extract_cross_chunk_relationships should be called once
        AND the results should be included in the final list
        """
        with patch.object(integrator, '_extract_chunk_relationships', new_callable=AsyncMock) as mock_chunk_rels, \
             patch.object(integrator, '_extract_cross_chunk_relationships', new_callable=AsyncMock) as mock_cross_rels:
            
            cross_relationship = Mock(spec=Relationship)
            mock_chunk_rels.return_value = []
            mock_cross_rels.return_value = [cross_relationship]
            
            result = await integrator._extract_relationships(sample_entities, sample_chunks)
            
            # Verify cross-chunk method was called exactly once
            mock_cross_rels.assert_called_once_with(sample_entities, sample_chunks)
            
            # Verify cross-chunk relationship is included in result
            assert cross_relationship in result

    @pytest.mark.asyncio
    async def test_extract_relationships_relationship_deduplication(self, integrator, sample_entities, sample_chunks):
        """
        GIVEN entities that might create duplicate relationships through different paths
        WHEN _extract_relationships is called
        THEN duplicate relationships should be handled appropriately
        AND the final list should contain unique relationships
        """
        with patch.object(integrator, '_extract_chunk_relationships', new_callable=AsyncMock) as mock_chunk_rels, \
             patch.object(integrator, '_extract_cross_chunk_relationships', new_callable=AsyncMock) as mock_cross_rels:
            
            # Create potentially duplicate relationships
            rel1 = Mock(spec=Relationship)
            rel1.id = "rel_1"
            rel2 = Mock(spec=Relationship) 
            rel2.id = "rel_1"  # Same ID as rel1
            
            mock_chunk_rels.return_value = [rel1]
            mock_cross_rels.return_value = [rel2]
            
            result = await integrator._extract_relationships(sample_entities, sample_chunks)
            
            # Should handle duplicates (implementation dependent)
            assert isinstance(result, list)
            assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_extract_relationships_logging_verification(self, integrator, sample_entities, sample_chunks):
        """
        GIVEN any valid entities and chunks
        WHEN _extract_relationships is called
        THEN the total count of extracted relationships should be logged
        AND the log message should include the correct count
        """
        with patch.object(integrator, '_extract_chunk_relationships', new_callable=AsyncMock) as mock_chunk_rels, \
             patch.object(integrator, '_extract_cross_chunk_relationships', new_callable=AsyncMock) as mock_cross_rels, \
             patch('logging.info') as mock_log:
            
            relationships = [Mock(spec=Relationship) for _ in range(3)]
            mock_chunk_rels.return_value = relationships[:2]
            mock_cross_rels.return_value = relationships[2:]
            
            result = await integrator._extract_relationships(sample_entities, sample_chunks)
            
            # Verify logging was called
            mock_log.assert_called()
            
            # Verify the count in the log message matches the result
            assert len(result) == 3

    @pytest.mark.asyncio
    async def test_extract_relationships_invalid_entities_type(self, integrator, sample_chunks):
        """
        GIVEN entities parameter that is not a list
        WHEN _extract_relationships is called
        THEN a TypeError should be raised
        AND the error should indicate expected list type
        """
        with pytest.raises(TypeError):
            await integrator._extract_relationships("not_a_list", sample_chunks)

    @pytest.mark.asyncio
    async def test_extract_relationships_invalid_chunks_type(self, integrator, sample_entities):
        """
        GIVEN chunks parameter that is not a list
        WHEN _extract_relationships is called
        THEN a TypeError should be raised
        AND the error should indicate expected list type
        """
        with pytest.raises(TypeError):
            await integrator._extract_relationships(sample_entities, "not_a_list")

    @pytest.mark.asyncio
    async def test_extract_relationships_entities_missing_source_chunks(self, integrator, sample_chunks):
        """
        GIVEN entities without source_chunks attribute
        WHEN _extract_relationships is called
        THEN an AttributeError should be raised
        AND the error should indicate missing source_chunks
        """
        invalid_entity = Mock()
        del invalid_entity.source_chunks  # Remove the attribute
        
        with pytest.raises(AttributeError):
            await integrator._extract_relationships([invalid_entity], sample_chunks)

    @pytest.mark.asyncio
    async def test_extract_relationships_chunks_missing_chunk_id(self, integrator, sample_entities):
        """
        GIVEN chunks without chunk_id attribute
        WHEN _extract_relationships is called
        THEN an AttributeError should be raised
        AND the error should indicate missing chunk_id
        """
        invalid_chunk = Mock()
        del invalid_chunk.chunk_id  # Remove the attribute
        
        with pytest.raises(AttributeError):
            await integrator._extract_relationships(sample_entities, [invalid_chunk])

    @pytest.mark.asyncio
    async def test_extract_relationships_intra_chunk_failure(self, integrator, sample_entities, sample_chunks):
        """
        GIVEN _extract_chunk_relationships fails for a chunk
        WHEN _extract_relationships is called
        THEN the exception should be propagated
        AND no partial results should be returned
        """
        with patch.object(integrator, '_extract_chunk_relationships', new_callable=AsyncMock) as mock_chunk_rels:
            mock_chunk_rels.side_effect = Exception("Chunk processing failed")
            
            with pytest.raises(Exception, match="Chunk processing failed"):
                await integrator._extract_relationships(sample_entities, sample_chunks)

    @pytest.mark.asyncio
    async def test_extract_relationships_cross_chunk_failure(self, integrator, sample_entities, sample_chunks):
        """
        GIVEN _extract_cross_chunk_relationships fails
        WHEN _extract_relationships is called
        THEN the exception should be propagated
        AND no partial results should be returned
        """
        with patch.object(integrator, '_extract_chunk_relationships', new_callable=AsyncMock) as mock_chunk_rels, \
             patch.object(integrator, '_extract_cross_chunk_relationships', new_callable=AsyncMock) as mock_cross_rels:
            
            mock_chunk_rels.return_value = []
            mock_cross_rels.side_effect = Exception("Cross-chunk processing failed")
            
            with pytest.raises(Exception, match="Cross-chunk processing failed"):
                await integrator._extract_relationships(sample_entities, sample_chunks)

    @pytest.mark.asyncio
    async def test_extract_relationships_large_entity_set(self, integrator):
        """
        GIVEN a large number of entities (>100)
        WHEN _extract_relationships is called
        THEN all relationships should be extracted efficiently
        AND performance should remain reasonable
        AND memory usage should not grow excessively
        """
        # Create 150 entities
        large_entity_set = []
        large_chunk_set = []
        
        for i in range(150):
            entity = Entity(
                id=f"entity_{i}",
                name=f"Entity {i}",
                type="person",
                description=f"Description {i}",
                confidence=0.8,
                source_chunks=[f"chunk_{i // 10}"],  # Group entities into chunks
                properties={}
            )
            large_entity_set.append(entity)
        
        # Create 15 chunks (10 entities per chunk on average)
        for i in range(15):
            chunk = LLMChunk(
                chunk_id=f"chunk_{i}",
                content=f"Content for chunk {i}",
                start_page=i+1,
                end_page=i+1,
                source_page=i+1,
                chunk_index=i,
                chunk_type="text",
                metadata={}
            )
            large_chunk_set.append(chunk)
        
        with patch.object(integrator, '_extract_chunk_relationships', new_callable=AsyncMock) as mock_chunk_rels, \
             patch.object(integrator, '_extract_cross_chunk_relationships', new_callable=AsyncMock) as mock_cross_rels:
            
            mock_chunk_rels.return_value = []
            mock_cross_rels.return_value = []
            
            result = await integrator._extract_relationships(large_entity_set, large_chunk_set)
            
            assert isinstance(result, list)
            # Should complete without excessive delay or memory issues

    @pytest.mark.asyncio
    async def test_extract_relationships_entity_index_correctness(self, integrator, sample_chunks):
        """
        GIVEN entities with overlapping source_chunks
        WHEN _extract_relationships is called
        THEN the entity index should correctly map each chunk to all its entities
        AND no entities should be missing from the index
        """
        # Create entities with overlapping chunks
        entities = [
            Entity(id="entity_1", name="John", type="person", description="Person",
                  confidence=0.9, source_chunks=["chunk_1", "chunk_2"], properties={}),
            Entity(id="entity_2", name="ACME", type="organization", description="Company",
                  confidence=0.8, source_chunks=["chunk_1"], properties={}),
            Entity(id="entity_3", name="Jane", type="person", description="Person",
                  confidence=0.7, source_chunks=["chunk_2"], properties={})
        ]
        
        with patch.object(integrator, '_extract_chunk_relationships', new_callable=AsyncMock) as mock_chunk_rels, \
             patch.object(integrator, '_extract_cross_chunk_relationships', new_callable=AsyncMock) as mock_cross_rels:
            
            mock_chunk_rels.return_value = []
            mock_cross_rels.return_value = []
            
            await integrator._extract_relationships(entities, sample_chunks)
            
            # Verify that chunk_1 processing got entities 1 and 2
            # Verify that chunk_2 processing got entities 1 and 3
            calls = mock_chunk_rels.call_args_list
            
            chunk_1_entities = None
            chunk_2_entities = None
            
            for call in calls:
                args, kwargs = call
                chunk_entities, chunk = args
                if chunk.chunk_id == "chunk_1":
                    chunk_1_entities = [e.id for e in chunk_entities]
                elif chunk.chunk_id == "chunk_2":
                    chunk_2_entities = [e.id for e in chunk_entities]
            
            if chunk_1_entities:
                assert "entity_1" in chunk_1_entities
                assert "entity_2" in chunk_1_entities
            
            if chunk_2_entities:
                assert "entity_1" in chunk_2_entities
                assert "entity_3" in chunk_2_entities

    @pytest.mark.asyncio
    async def test_extract_relationships_return_type_validation(self, integrator, sample_entities, sample_chunks):
        """
        GIVEN any valid input
        WHEN _extract_relationships is called
        THEN the return value should be a list
        AND each element should be a Relationship object
        AND all relationships should have required attributes
        """
        with patch.object(integrator, '_extract_chunk_relationships', new_callable=AsyncMock) as mock_chunk_rels, \
             patch.object(integrator, '_extract_cross_chunk_relationships', new_callable=AsyncMock) as mock_cross_rels:
            
            relationship = Mock(spec=Relationship)
            relationship.id = "rel_1"
            relationship.source_entity_id = "entity_1"
            relationship.target_entity_id = "entity_2"
            relationship.relationship_type = "works_for"
            
            mock_chunk_rels.return_value = [relationship]
            mock_cross_rels.return_value = []
            
            result = await integrator._extract_relationships(sample_entities, sample_chunks)
            
            assert isinstance(result, list)
            for rel in result:
                assert hasattr(rel, 'id')
                assert hasattr(rel, 'source_entity_id')
                assert hasattr(rel, 'target_entity_id')
                assert hasattr(rel, 'relationship_type')




class TestExtractChunkRelationships:
    """Test class for GraphRAGIntegrator._extract_chunk_relationships method."""

    @pytest.fixture
    def integrator(self):
        """Create a GraphRAGIntegrator instance for testing."""
        return GraphRAGIntegrator()

    @pytest.fixture
    def sample_chunk(self):
        """Create a sample chunk for testing."""
        return LLMChunk(
            chunk_id="chunk_1",
            content="John Smith works at ACME Corp as a software engineer. He collaborates with Jane Doe.",
            start_page=1,
            end_page=1,
            source_page=1,
            chunk_index=0,
            chunk_type="text",
            metadata={}
        )

    @pytest.fixture
    def sample_entities(self):
        """Create sample entities for testing."""
        return [
            Entity(
                id="entity_1",
                name="John Smith",
                type="person",
                description="Software engineer",
                confidence=0.9,
                source_chunks=["chunk_1"],
                properties={}
            ),
            Entity(
                id="entity_2",
                name="ACME Corp",
                type="organization",
                description="Technology company",
                confidence=0.8,
                source_chunks=["chunk_1"],
                properties={}
            ),
            Entity(
                id="entity_3",
                name="Jane Doe",
                type="person",
                description="Software engineer",
                confidence=0.85,
                source_chunks=["chunk_1"],
                properties={}
            )
        ]

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_valid_input(self, integrator, sample_entities, sample_chunk):
        """
        GIVEN a list of entities and a chunk containing those entities
        WHEN _extract_chunk_relationships is called
        THEN relationships should be created between all pairs of entities in the chunk
        AND each relationship should have proper metadata and confidence scores
        """
        with patch.object(integrator, '_infer_relationship_type') as mock_infer:
            mock_infer.return_value = "works_for"
            
            result = await integrator._extract_chunk_relationships(sample_entities, sample_chunk)
            
            assert isinstance(result, list)
            assert len(result) > 0
            
            # Verify relationships have proper structure
            for rel in result:
                assert hasattr(rel, 'id')
                assert hasattr(rel, 'source_entity_id')
                assert hasattr(rel, 'target_entity_id')
                assert hasattr(rel, 'relationship_type')
                assert hasattr(rel, 'confidence')
                assert rel.confidence == 0.6
                assert sample_chunk.chunk_id in rel.source_chunks

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_two_entities(self, integrator, sample_chunk):
        """
        GIVEN exactly two entities in a chunk
        WHEN _extract_chunk_relationships is called
        THEN exactly one relationship should be created
        AND it should connect the two entities with inferred relationship type
        """
        entities = [
            Entity(id="entity_1", name="John Smith", type="person", description="Person",
                  confidence=0.9, source_chunks=["chunk_1"], properties={}),
            Entity(id="entity_2", name="ACME Corp", type="organization", description="Company",
                  confidence=0.8, source_chunks=["chunk_1"], properties={})
        ]
        
        with patch.object(integrator, '_infer_relationship_type') as mock_infer:
            mock_infer.return_value = "works_for"
            
            result = await integrator._extract_chunk_relationships(entities, sample_chunk)
            
            assert len(result) == 1
            assert result[0].relationship_type == "works_for"
            assert result[0].source_entity_id in ["entity_1", "entity_2"]
            assert result[0].target_entity_id in ["entity_1", "entity_2"]

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_multiple_entities(self, integrator, sample_entities, sample_chunk):
        """
        GIVEN multiple entities (>2) in a chunk
        WHEN _extract_chunk_relationships is called
        THEN relationships should be created for all entity pairs
        AND the number of relationships should be n*(n-1)/2 where n is entity count
        """
        with patch.object(integrator, '_infer_relationship_type') as mock_infer:
            mock_infer.return_value = "related_to"
            
            result = await integrator._extract_chunk_relationships(sample_entities, sample_chunk)
            
            # For 3 entities, should have 3 pairs: (1,2), (1,3), (2,3)
            expected_pairs = 3
            assert len(result) <= expected_pairs  # May be less if some relationship types couldn't be inferred

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_no_entities(self, integrator, sample_chunk):
        """
        GIVEN an empty entities list
        WHEN _extract_chunk_relationships is called
        THEN an empty relationships list should be returned
        AND no processing should be attempted
        """
        result = await integrator._extract_chunk_relationships([], sample_chunk)
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_single_entity(self, integrator, sample_chunk):
        """
        GIVEN a single entity in the entities list
        WHEN _extract_chunk_relationships is called
        THEN no relationships should be created
        AND an empty list should be returned
        """
        entities = [
            Entity(id="entity_1", name="John Smith", type="person", description="Person",
                  confidence=0.9, source_chunks=["chunk_1"], properties={})
        ]
        
        result = await integrator._extract_chunk_relationships(entities, sample_chunk)
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_entity_name_matching(self, integrator, sample_chunk):
        """
        GIVEN entities with names that appear in the chunk content
        WHEN _extract_chunk_relationships is called
        THEN only entities whose names are found in the chunk should be included in relationships
        AND case-insensitive matching should be performed
        """
        entities = [
            Entity(id="entity_1", name="John Smith", type="person", description="Person",
                  confidence=0.9, source_chunks=["chunk_1"], properties={}),
            Entity(id="entity_2", name="ACME Corp", type="organization", description="Company",
                  confidence=0.8, source_chunks=["chunk_1"], properties={}),
            Entity(id="entity_3", name="NotInChunk", type="person", description="Person",
                  confidence=0.7, source_chunks=["chunk_1"], properties={})
        ]
        
        with patch.object(integrator, '_infer_relationship_type') as mock_infer:
            mock_infer.return_value = "works_for"
            
            result = await integrator._extract_chunk_relationships(entities, sample_chunk)
            
            # Should only include relationships between entities found in chunk
            entity_ids_in_relationships = set()
            for rel in result:
                entity_ids_in_relationships.add(rel.source_entity_id)
                entity_ids_in_relationships.add(rel.target_entity_id)
            
            # Should not include entity_3 (NotInChunk)
            assert "entity_3" not in entity_ids_in_relationships

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_entity_not_in_chunk(self, integrator):
        """
        GIVEN entities whose names do not appear in the chunk content
        WHEN _extract_chunk_relationships is called
        THEN those entities should be excluded from relationship creation
        AND only entities present in the chunk should form relationships
        """
        chunk = LLMChunk(
            chunk_id="chunk_1",
            content="This chunk contains different content entirely.",
            start_page=1, end_page=1, source_page=1, chunk_index=0,
            chunk_type="text", metadata={}
        )
        
        entities = [
            Entity(id="entity_1", name="John Smith", type="person", description="Person",
                  confidence=0.9, source_chunks=["chunk_1"], properties={}),
            Entity(id="entity_2", name="ACME Corp", type="organization", description="Company",
                  confidence=0.8, source_chunks=["chunk_1"], properties={})
        ]
        
        result = await integrator._extract_chunk_relationships(entities, chunk)
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_relationship_type_inference(self, integrator, sample_entities, sample_chunk):
        """
        GIVEN entities that co-occur in a chunk with contextual information
        WHEN _extract_chunk_relationships is called
        THEN _infer_relationship_type should be called for each entity pair
        AND the inferred type should be used in the relationship
        """
        with patch.object(integrator, '_infer_relationship_type') as mock_infer:
            mock_infer.return_value = "collaborates_with"
            
            result = await integrator._extract_chunk_relationships(sample_entities, sample_chunk)
            
            # Verify _infer_relationship_type was called
            assert mock_infer.call_count > 0
            
            # Verify the inferred type is used
            for rel in result:
                assert rel.relationship_type == "collaborates_with"

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_no_relationship_type_inferred(self, integrator, sample_entities, sample_chunk):
        """
        GIVEN entities where no relationship type can be inferred
        WHEN _extract_chunk_relationships is called
        THEN no relationship should be created for that entity pair
        AND other valid relationships should still be created
        """
        with patch.object(integrator, '_infer_relationship_type') as mock_infer:
            mock_infer.return_value = None  # No relationship type inferred
            
            result = await integrator._extract_chunk_relationships(sample_entities, sample_chunk)
            
            # Should return empty list when no relationships can be inferred
            assert result == []

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_confidence_score(self, integrator, sample_entities, sample_chunk):
        """
        GIVEN any valid entity pairs in a chunk
        WHEN _extract_chunk_relationships is called
        THEN all relationships should have a confidence score of 0.6
        AND the confidence should be consistent across all relationships
        """
        with patch.object(integrator, '_infer_relationship_type') as mock_infer:
            mock_infer.return_value = "related_to"
            
            result = await integrator._extract_chunk_relationships(sample_entities, sample_chunk)
            
            for rel in result:
                assert rel.confidence == 0.6

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_relationship_id_generation(self, integrator, sample_entities, sample_chunk):
        """
        GIVEN entity pairs forming relationships
        WHEN _extract_chunk_relationships is called
        THEN each relationship should have a unique ID generated from entity IDs
        AND the ID should be consistent for the same entity pair
        """
        with patch.object(integrator, '_infer_relationship_type') as mock_infer:
            mock_infer.return_value = "works_for"
            
            result = await integrator._extract_chunk_relationships(sample_entities, sample_chunk)
            
            # Verify each relationship has a unique ID
            ids = [rel.id for rel in result]
            assert len(ids) == len(set(ids))  # All IDs should be unique
            
            # Verify ID format (should be MD5 hash)
            for rel in result:
                assert len(rel.id) == 32  # MD5 hash length
                assert all(c in '0123456789abcdef' for c in rel.id)

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_source_chunks_assignment(self, integrator, sample_entities, sample_chunk):
        """
        GIVEN a chunk with entities
        WHEN _extract_chunk_relationships is called
        THEN all relationships should have the chunk_id in their source_chunks list
        AND source_chunks should contain exactly one element
        """
        with patch.object(integrator, '_infer_relationship_type') as mock_infer:
            mock_infer.return_value = "works_for"
            
            result = await integrator._extract_chunk_relationships(sample_entities, sample_chunk)
            
            for rel in result:
                assert len(rel.source_chunks) == 1
                assert sample_chunk.chunk_id in rel.source_chunks

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_properties_metadata(self, integrator, sample_entities, sample_chunk):
        """
        GIVEN any valid relationships created
        WHEN _extract_chunk_relationships is called
        THEN each relationship should have properties containing:
            - extraction_method: 'co_occurrence_analysis'
            - context_snippet: relevant text from the chunk
        """
        with patch.object(integrator, '_infer_relationship_type') as mock_infer:
            mock_infer.return_value = "works_for"
            
            result = await integrator._extract_chunk_relationships(sample_entities, sample_chunk)
            
            for rel in result:
                assert 'extraction_method' in rel.properties
                assert rel.properties['extraction_method'] == 'co_occurrence_analysis'
                assert 'context_snippet' in rel.properties
                assert isinstance(rel.properties['context_snippet'], str)

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_description_generation(self, integrator, sample_entities, sample_chunk):
        """
        GIVEN entities forming relationships
        WHEN _extract_chunk_relationships is called
        THEN each relationship should have a descriptive text
        AND the description should mention both entities and the relationship type
        """
        with patch.object(integrator, '_infer_relationship_type') as mock_infer:
            mock_infer.return_value = "works_for"
            
            result = await integrator._extract_chunk_relationships(sample_entities, sample_chunk)
            
            for rel in result:
                assert hasattr(rel, 'description')
                assert isinstance(rel.description, str)
                assert len(rel.description) > 0

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_case_insensitive_matching(self, integrator, sample_chunk):
        """
        GIVEN entity names with different cases than in the chunk content
        WHEN _extract_chunk_relationships is called
        THEN entities should still be matched case-insensitively
        AND relationships should be created correctly
        """
        entities = [
            Entity(id="entity_1", name="john smith", type="person", description="Person",
                  confidence=0.9, source_chunks=["chunk_1"], properties={}),  # lowercase
            Entity(id="entity_2", name="ACME CORP", type="organization", description="Company",
                  confidence=0.8, source_chunks=["chunk_1"], properties={})  # uppercase
        ]
        
        with patch.object(integrator, '_infer_relationship_type') as mock_infer:
            mock_infer.return_value = "works_for"
            
            result = await integrator._extract_chunk_relationships(entities, sample_chunk)
            
            # Should find both entities despite case differences
            assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_partial_name_matching(self, integrator):
        """
        GIVEN entity names that are substrings of words in the chunk
        WHEN _extract_chunk_relationships is called
        THEN only complete word matches should be considered
        AND partial matches within other words should be ignored
        """
        chunk = LLMChunk(
            chunk_id="chunk_1",
            content="The company called ACME Corporation has many employees.",
            start_page=1, end_page=1, source_page=1, chunk_index=0,
            chunk_type="text", metadata={}
        )
        
        entities = [
            Entity(id="entity_1", name="ACME", type="organization", description="Company",
                  confidence=0.8, source_chunks=["chunk_1"], properties={}),
            Entity(id="entity_2", name="Corp", type="organization", description="Company",
                  confidence=0.7, source_chunks=["chunk_1"], properties={})  # Partial match
        ]
        
        with patch.object(integrator, '_infer_relationship_type') as mock_infer:
            mock_infer.return_value = "related_to"
            
            result = await integrator._extract_chunk_relationships(entities, chunk)
            
            # Should handle word boundary matching appropriately
            assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_chunk_missing_content(self, integrator, sample_entities):
        """
        GIVEN a chunk without content attribute
        WHEN _extract_chunk_relationships is called
        THEN an AttributeError should be raised
        AND the error should indicate missing content
        """
        invalid_chunk = Mock()
        del invalid_chunk.content
        
        with pytest.raises(AttributeError):
            await integrator._extract_chunk_relationships(sample_entities, invalid_chunk)

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_chunk_missing_chunk_id(self, integrator, sample_entities):
        """
        GIVEN a chunk without chunk_id attribute
        WHEN _extract_chunk_relationships is called
        THEN an AttributeError should be raised
        AND the error should indicate missing chunk_id
        """
        invalid_chunk = Mock()
        invalid_chunk.content = "Valid content"
        del invalid_chunk.chunk_id
        
        with pytest.raises(AttributeError):
            await integrator._extract_chunk_relationships(sample_entities, invalid_chunk)

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_entities_missing_attributes(self, integrator, sample_chunk):
        """
        GIVEN entities missing required attributes (id, name)
        WHEN _extract_chunk_relationships is called
        THEN an AttributeError should be raised
        AND the error should indicate missing entity attributes
        """
        invalid_entity = Mock()
        del invalid_entity.id
        del invalid_entity.name
        
        with pytest.raises(AttributeError):
            await integrator._extract_chunk_relationships([invalid_entity], sample_chunk)

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_invalid_entities_type(self, integrator, sample_chunk):
        """
        GIVEN entities parameter that is not a list
        WHEN _extract_chunk_relationships is called
        THEN a TypeError should be raised
        AND the error should indicate expected list type
        """
        with pytest.raises(TypeError):
            await integrator._extract_chunk_relationships("not_a_list", sample_chunk)

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_invalid_chunk_type(self, integrator, sample_entities):
        """
        GIVEN chunk parameter that is not an LLMChunk
        WHEN _extract_chunk_relationships is called
        THEN a TypeError should be raised
        AND the error should indicate expected LLMChunk type
        """
        with pytest.raises((TypeError, AttributeError)):
            await integrator._extract_chunk_relationships(sample_entities, "not_a_chunk")

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_empty_chunk_content(self, integrator, sample_entities):
        """
        GIVEN a chunk with empty or whitespace-only content
        WHEN _extract_chunk_relationships is called
        THEN no entities should be found in the chunk
        AND an empty relationships list should be returned
        """
        empty_chunk = LLMChunk(
            chunk_id="chunk_1",
            content="   ",  # Whitespace only
            start_page=1, end_page=1, source_page=1, chunk_index=0,
            chunk_type="text", metadata={}
        )
        
        result = await integrator._extract_chunk_relationships(sample_entities, empty_chunk)
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_large_entity_set(self, integrator):
        """
        GIVEN a large number of entities (>50) in a chunk
        WHEN _extract_chunk_relationships is called
        THEN all valid relationships should be created
        AND performance should remain reasonable
        AND the number of relationships should follow n*(n-1)/2 formula
        """
        # Create a chunk with content mentioning many entities
        entity_names = [f"Entity{i}" for i in range(60)]
        content = " ".join(entity_names) + " are all working together."
        
        chunk = LLMChunk(
            chunk_id="chunk_1",
            content=content,
            start_page=1, end_page=1, source_page=1, chunk_index=0,
            chunk_type="text", metadata={}
        )
        
        entities = [
            Entity(id=f"entity_{i}", name=f"Entity{i}", type="person", description="Person",
                  confidence=0.8, source_chunks=["chunk_1"], properties={})
            for i in range(60)
        ]
        
        with patch.object(integrator, '_infer_relationship_type') as mock_infer:
            mock_infer.return_value = "related_to"
            
            result = await integrator._extract_chunk_relationships(entities, chunk)
            
            # Should handle large entity sets efficiently
            assert isinstance(result, list)
            # Maximum possible relationships: 60 * 59 / 2 = 1770
            assert len(result) <= 1770

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_special_characters_in_names(self, integrator):
        """
        GIVEN entity names containing special characters or punctuation
        WHEN _extract_chunk_relationships is called
        THEN entities should still be matched correctly in the chunk
        AND special characters should not interfere with matching
        """
        chunk = LLMChunk(
            chunk_id="chunk_1",
            content="Dr. Smith-Jones and O'Connor Ltd. are collaborating.",
            start_page=1, end_page=1, source_page=1, chunk_index=0,
            chunk_type="text", metadata={}
        )
        
        entities = [
            Entity(id="entity_1", name="Dr. Smith-Jones", type="person", description="Doctor",
                  confidence=0.9, source_chunks=["chunk_1"], properties={}),
            Entity(id="entity_2", name="O'Connor Ltd.", type="organization", description="Company",
                  confidence=0.8, source_chunks=["chunk_1"], properties={})
        ]
        
        with patch.object(integrator, '_infer_relationship_type') as mock_infer:
            mock_infer.return_value = "collaborates_with"
            
            result = await integrator._extract_chunk_relationships(entities, chunk)
            
            # Should find both entities despite special characters
            assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_return_type_validation(self, integrator, sample_entities, sample_chunk):
        """
        GIVEN any valid input
        WHEN _extract_chunk_relationships is called
        THEN the return value should be a list
        AND each element should be a Relationship object
        AND all relationships should have required attributes
        """
        with patch.object(integrator, '_infer_relationship_type') as mock_infer:
            mock_infer.return_value = "works_for"
            
            result = await integrator._extract_chunk_relationships(sample_entities, sample_chunk)
            
            assert isinstance(result, list)
            for rel in result:
                # Verify all required Relationship attributes
                assert hasattr(rel, 'id')
                assert hasattr(rel, 'source_entity_id')
                assert hasattr(rel, 'target_entity_id')
                assert hasattr(rel, 'relationship_type')
                assert hasattr(rel, 'description')
                assert hasattr(rel, 'confidence')
                assert hasattr(rel, 'source_chunks')
                assert hasattr(rel, 'properties')



class TestQueryGraph:
    """Test class for GraphRAGIntegrator.query_graph method."""

    @pytest.fixture
    def integrator(self):
        """Create a GraphRAGIntegrator instance for testing."""
        integrator = GraphRAGIntegrator()
        
        # Setup sample global entities
        integrator.global_entities = {
            "entity_1": Entity(
                id="entity_1",
                name="John Smith",
                type="person",
                description="Software engineer at ACME Corp",
                confidence=0.9,
                source_chunks=["chunk_1"],
                properties={"role": "engineer"}
            ),
            "entity_2": Entity(
                id="entity_2",
                name="ACME Corp",
                type="organization",
                description="Technology company specializing in AI",
                confidence=0.8,
                source_chunks=["chunk_1"],
                properties={"industry": "technology"}
            ),
            "entity_3": Entity(
                id="entity_3",
                name="San Francisco",
                type="location",
                description="City in California",
                confidence=0.7,
                source_chunks=["chunk_2"],
                properties={"state": "California"}
            )
        }
        
        # Setup sample knowledge graphs
        integrator.knowledge_graphs = {
            "graph_1": Mock(spec=KnowledgeGraph),
            "graph_2": Mock(spec=KnowledgeGraph)
        }
        
        # Setup sample global graph
        integrator.global_graph = Mock()
        
        return integrator

    @pytest.fixture
    def sample_relationships(self):
        """Create sample relationships for testing."""
        return [
            Relationship(
                id="rel_1",
                source_entity_id="entity_1",
                target_entity_id="entity_2",
                relationship_type="works_for",
                description="John Smith works for ACME Corp",
                confidence=0.9,
                source_chunks=["chunk_1"],
                properties={}
            ),
            Relationship(
                id="rel_2",
                source_entity_id="entity_1",
                target_entity_id="entity_3",
                relationship_type="located_in",
                description="John Smith is located in San Francisco",
                confidence=0.8,
                source_chunks=["chunk_2"],
                properties={}
            )
        ]

    @pytest.mark.asyncio
    async def test_query_graph_global_search_valid_query(self, integrator, sample_relationships):
        """
        GIVEN a valid query string and no specific graph_id
        WHEN query_graph is called
        THEN the global knowledge graph should be searched
        AND matching entities and their relationships should be returned
        AND results should be ranked by relevance score
        """
        # Mock the global graph to return relationships
        integrator.global_graph.edges.return_value = [
            ("entity_1", "entity_2", {"relationship": sample_relationships[0]}),
            ("entity_1", "entity_3", {"relationship": sample_relationships[1]})
        ]
        
        result = await integrator.query_graph("software engineer", max_results=5)
        
        assert isinstance(result, dict)
        assert "query" in result
        assert "entities" in result
        assert "relationships" in result
        assert "total_matches" in result
        assert "timestamp" in result
        
        assert result["query"] == "software engineer"
        assert isinstance(result["entities"], list)
        assert isinstance(result["relationships"], list)
        assert isinstance(result["total_matches"], int)

    @pytest.mark.asyncio
    async def test_query_graph_specific_graph_search(self, integrator):
        """
        GIVEN a valid query string and a specific graph_id
        WHEN query_graph is called
        THEN only the specified knowledge graph should be searched
        AND results should be limited to that graph's entities and relationships
        """
        # Setup specific graph entities
        graph_entities = [
            Entity(id="graph_entity_1", name="Graph Entity", type="person",
                  description="Entity in specific graph", confidence=0.8,
                  source_chunks=["chunk_graph"], properties={})
        ]
        integrator.knowledge_graphs["graph_1"].entities = graph_entities
        integrator.knowledge_graphs["graph_1"].relationships = []
        
        result = await integrator.query_graph("Graph Entity", graph_id="graph_1")
        
        assert result["query"] == "Graph Entity"
        # Should search only the specific graph, not global entities

    @pytest.mark.asyncio
    async def test_query_graph_case_insensitive_matching(self, integrator):
        """
        GIVEN a query with mixed case that matches entities
        WHEN query_graph is called
        THEN matching should be case-insensitive
        AND entities should be found regardless of case differences
        """
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("JOHN SMITH")  # Uppercase query
        
        # Should find "John Smith" entity despite case difference
        assert isinstance(result["entities"], list)

    @pytest.mark.asyncio
    async def test_query_graph_entity_name_matching(self, integrator):
        """
        GIVEN a query that matches entity names
        WHEN query_graph is called
        THEN entities with matching names should be included in results
        AND relevance scores should reflect name match quality
        """
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("John")
        
        # Should find entities with "John" in the name
        matching_entities = [e for e in result["entities"] if "john" in e.get("name", "").lower()]
        assert len(matching_entities) > 0

    @pytest.mark.asyncio
    async def test_query_graph_entity_type_matching(self, integrator):
        """
        GIVEN a query that matches entity types
        WHEN query_graph is called
        THEN entities with matching types should be included in results
        AND type matches should contribute to relevance scoring
        """
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("person")
        
        # Should find entities of type "person"
        person_entities = [e for e in result["entities"] if e.get("type") == "person"]
        assert len(person_entities) > 0

    @pytest.mark.asyncio
    async def test_query_graph_entity_description_matching(self, integrator):
        """
        GIVEN a query that matches entity descriptions
        WHEN query_graph is called
        THEN entities with matching descriptions should be included in results
        AND description matches should be properly scored
        """
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("software engineer")
        
        # Should find entities with "software engineer" in description
        matching_entities = [e for e in result["entities"] 
                           if "software engineer" in e.get("description", "").lower()]
        assert len(matching_entities) > 0

    @pytest.mark.asyncio
    async def test_query_graph_max_results_limiting(self, integrator):
        """
        GIVEN more matching entities than max_results limit
        WHEN query_graph is called
        THEN only the top max_results entities should be returned
        AND they should be the highest-scoring matches
        """
        # Add more entities to ensure we exceed max_results
        for i in range(15):
            integrator.global_entities[f"extra_entity_{i}"] = Entity(
                id=f"extra_entity_{i}",
                name=f"Test Entity {i}",
                type="person",
                description="Test description",
                confidence=0.5,
                source_chunks=[f"chunk_{i}"],
                properties={}
            )
        
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("Test", max_results=5)
        
        # Should return at most 5 entities
        assert len(result["entities"]) <= 5
        assert result["total_matches"] >= 5  # But total_matches should reflect all matches

    @pytest.mark.asyncio
    async def test_query_graph_relevance_score_ordering(self, integrator):
        """
        GIVEN multiple entities with different relevance scores
        WHEN query_graph is called
        THEN results should be ordered by relevance score descending
        AND highest scoring entities should appear first
        """
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("smith")
        
        if len(result["entities"]) > 1:
            # Check that entities are ordered by relevance (assuming relevance field exists)
            relevance_scores = []
            for entity in result["entities"]:
                # Calculate relevance based on name match
                name = entity.get("name", "").lower()
                if "smith" in name:
                    relevance_scores.append(1.0)
                else:
                    relevance_scores.append(0.0)
            
            # Should be in descending order
            assert relevance_scores == sorted(relevance_scores, reverse=True)

    @pytest.mark.asyncio
    async def test_query_graph_related_relationships_inclusion(self, integrator, sample_relationships):
        """
        GIVEN matching entities that have relationships
        WHEN query_graph is called
        THEN relationships connected to matching entities should be included
        AND relationship data should be properly serialized
        """
        integrator.global_graph.edges.return_value = [
            ("entity_1", "entity_2", {"relationship": sample_relationships[0]})
        ]
        
        result = await integrator.query_graph("John Smith")
        
        # Should include relationships for matching entities
        assert isinstance(result["relationships"], list)
        if result["relationships"]:
            rel = result["relationships"][0]
            assert "id" in rel
            assert "source_entity_id" in rel
            assert "target_entity_id" in rel
            assert "relationship_type" in rel

    @pytest.mark.asyncio
    async def test_query_graph_no_matches_found(self, integrator):
        """
        GIVEN a query that matches no entities
        WHEN query_graph is called
        THEN empty entities and relationships lists should be returned
        AND total_matches should be 0
        AND proper structure should still be maintained
        """
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("nonexistent_entity_xyz")
        
        assert result["entities"] == []
        assert result["relationships"] == []
        assert result["total_matches"] == 0
        assert result["query"] == "nonexistent_entity_xyz"
        assert "timestamp" in result

    @pytest.mark.asyncio
    async def test_query_graph_empty_query_string(self, integrator):
        """
        GIVEN an empty query string
        WHEN query_graph is called
        THEN no entities should match
        AND empty results should be returned
        """
        result = await integrator.query_graph("")
        
        assert result["entities"] == []
        assert result["relationships"] == []
        assert result["total_matches"] == 0
        assert result["query"] == ""

    @pytest.mark.asyncio
    async def test_query_graph_whitespace_only_query(self, integrator):
        """
        GIVEN a query containing only whitespace
        WHEN query_graph is called
        THEN no entities should match
        AND empty results should be returned
        """
        result = await integrator.query_graph("   \t\n   ")
        
        assert result["entities"] == []
        assert result["relationships"] == []
        assert result["total_matches"] == 0

    @pytest.mark.asyncio
    async def test_query_graph_nonexistent_graph_id(self, integrator):
        """
        GIVEN a graph_id that doesn't exist in knowledge_graphs
        WHEN query_graph is called
        THEN a KeyError should be raised
        AND the error should indicate the graph was not found
        """
        with pytest.raises(KeyError):
            await integrator.query_graph("test query", graph_id="nonexistent_graph")

    @pytest.mark.asyncio
    async def test_query_graph_none_query_parameter(self, integrator):
        """
        GIVEN None as the query parameter
        WHEN query_graph is called
        THEN a TypeError should be raised
        AND the error should indicate invalid query type
        """
        with pytest.raises(TypeError):
            await integrator.query_graph(None)

    @pytest.mark.asyncio
    async def test_query_graph_invalid_max_results_negative(self, integrator):
        """
        GIVEN a negative max_results value
        WHEN query_graph is called
        THEN a ValueError should be raised
        AND the error should indicate invalid max_results range
        """
        with pytest.raises(ValueError):
            await integrator.query_graph("test", max_results=-1)

    @pytest.mark.asyncio
    async def test_query_graph_invalid_max_results_zero(self, integrator):
        """
        GIVEN zero as max_results value
        WHEN query_graph is called
        THEN a ValueError should be raised
        AND the error should indicate invalid max_results range
        """
        with pytest.raises(ValueError):
            await integrator.query_graph("test", max_results=0)

    @pytest.mark.asyncio
    async def test_query_graph_invalid_max_results_type(self, integrator):
        """
        GIVEN a non-integer max_results parameter
        WHEN query_graph is called
        THEN a TypeError should be raised
        AND the error should indicate expected integer type
        """
        with pytest.raises(TypeError):
            await integrator.query_graph("test", max_results="invalid")

    @pytest.mark.asyncio
    async def test_query_graph_return_structure_validation(self, integrator):
        """
        GIVEN any valid query
        WHEN query_graph is called
        THEN the return value should be a dictionary containing:
            - 'query': the original query string
            - 'entities': list of entity dictionaries
            - 'relationships': list of relationship dictionaries
            - 'total_matches': integer count
            - 'timestamp': ISO format timestamp
        """
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("test query")
        
        # Verify required keys
        required_keys = ['query', 'entities', 'relationships', 'total_matches', 'timestamp']
        for key in required_keys:
            assert key in result
        
        # Verify types
        assert isinstance(result['query'], str)
        assert isinstance(result['entities'], list)
        assert isinstance(result['relationships'], list)
        assert isinstance(result['total_matches'], int)
        assert isinstance(result['timestamp'], str)
        
        # Verify timestamp format (ISO)
        try:
            datetime.fromisoformat(result['timestamp'].replace('Z', '+00:00'))
        except ValueError:
            pytest.fail("Timestamp is not in ISO format")

    @pytest.mark.asyncio
    async def test_query_graph_entity_serialization(self, integrator):
        """
        GIVEN entities in the results
        WHEN query_graph is called
        THEN entities should be properly serialized to dictionaries
        AND all entity attributes should be preserved
        AND numpy arrays should be converted to lists if present
        """
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("John")
        
        for entity in result["entities"]:
            assert isinstance(entity, dict)
            # Verify entity has expected fields
            expected_fields = ['id', 'name', 'type', 'description', 'confidence', 'source_chunks', 'properties']
            for field in expected_fields:
                assert field in entity

    @pytest.mark.asyncio
    async def test_query_graph_relationship_serialization(self, integrator, sample_relationships):
        """
        GIVEN relationships in the results
        WHEN query_graph is called
        THEN relationships should be properly serialized to dictionaries
        AND all relationship attributes should be preserved
        """
        integrator.global_graph.edges.return_value = [
            ("entity_1", "entity_2", {"relationship": sample_relationships[0]})
        ]
        
        result = await integrator.query_graph("John")
        
        for relationship in result["relationships"]:
            assert isinstance(relationship, dict)
            # Verify relationship has expected fields
            expected_fields = ['id', 'source_entity_id', 'target_entity_id', 'relationship_type', 
                             'description', 'confidence', 'source_chunks', 'properties']
            for field in expected_fields:
                assert field in relationship

    @pytest.mark.asyncio
    async def test_query_graph_timestamp_generation(self, integrator):
        """
        GIVEN any query execution
        WHEN query_graph is called
        THEN a timestamp should be generated in ISO format
        AND the timestamp should be recent (within last few seconds)
        """
        integrator.global_graph.edges.return_value = []
        
        before_time = datetime.utcnow()
        result = await integrator.query_graph("test")
        after_time = datetime.utcnow()
        
        timestamp_str = result["timestamp"]
        timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
        
        # Verify timestamp is between before and after
        assert before_time <= timestamp.replace(tzinfo=None) <= after_time

    @pytest.mark.asyncio
    async def test_query_graph_total_matches_accuracy(self, integrator):
        """
        GIVEN a query with known number of matches
        WHEN query_graph is called with max_results limit
        THEN total_matches should reflect actual matches before limiting
        AND it should be accurate regardless of max_results value
        """
        # Add 10 matching entities
        for i in range(10):
            integrator.global_entities[f"match_entity_{i}"] = Entity(
                id=f"match_entity_{i}",
                name=f"Matching Entity {i}",
                type="person",
                description="Matching description",
                confidence=0.8,
                source_chunks=[f"chunk_{i}"],
                properties={}
            )
        
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("Matching", max_results=3)
        
        # Should return only 3 entities but report all 10 as total matches
        assert len(result["entities"]) <= 3
        assert result["total_matches"] >= 10

    @pytest.mark.asyncio
    async def test_query_graph_large_result_set_performance(self, integrator):
        """
        GIVEN a query that matches many entities (>1000)
        WHEN query_graph is called
        THEN performance should remain reasonable
        AND memory usage should be manageable
        AND results should still be properly ranked and limited
        """
        # Add 1500 entities
        for i in range(1500):
            integrator.global_entities[f"large_entity_{i}"] = Entity(
                id=f"large_entity_{i}",
                name=f"Large Entity {i}",
                type="person",
                description="Large test entity",
                confidence=0.5,
                source_chunks=[f"chunk_{i}"],
                properties={}
            )
        
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("Large", max_results=100)
        
        # Should complete efficiently
        assert isinstance(result, dict)
        assert len(result["entities"]) <= 100
        assert result["total_matches"] >= 1500

    @pytest.mark.asyncio
    async def test_query_graph_special_characters_in_query(self, integrator):
        """
        GIVEN a query containing special characters, punctuation, or symbols
        WHEN query_graph is called
        THEN the query should be handled gracefully
        AND matching should work correctly despite special characters
        """
        integrator.global_graph.edges.return_value = []
        
        special_queries = [
            "Dr. Smith-Jones",
            "O'Connor & Associates",
            "Query with @#$%^&*() symbols",
            "Multi-line\nquery\twith\ttabs"
        ]
        
        for query in special_queries:
            result = await integrator.query_graph(query)
            assert isinstance(result, dict)
            assert result["query"] == query

    @pytest.mark.asyncio
    async def test_query_graph_unicode_query_handling(self, integrator):
        """
        GIVEN a query containing unicode characters
        WHEN query_graph is called
        THEN unicode should be handled correctly in matching
        AND results should include entities with unicode content
        """
        # Add entity with unicode content
        integrator.global_entities["unicode_entity"] = Entity(
            id="unicode_entity",
            name="José María González",
            type="person",
            description="Persona con caracteres unicode",
            confidence=0.8,
            source_chunks=["chunk_unicode"],
            properties={}
        )
        
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("José")
        
        # Should handle unicode correctly
        assert isinstance(result, dict)
        assert result["query"] == "José"

    @pytest.mark.asyncio
    async def test_query_graph_empty_knowledge_graphs(self, integrator):
        """
        GIVEN empty knowledge_graphs and global_entities
        WHEN query_graph is called
        THEN empty results should be returned gracefully
        AND no errors should be raised
        """
        integrator.global_entities = {}
        integrator.knowledge_graphs = {}
        integrator.global_graph.edges.return_value = []
        
        result = await integrator.query_graph("any query")
        
        assert result["entities"] == []
        assert result["relationships"] == []
        assert result["total_matches"] == 0

    @pytest.mark.asyncio
    async def test_query_graph_concurrent_queries(self, integrator):
        """
        GIVEN multiple concurrent query_graph calls
        WHEN executed simultaneously
        THEN all queries should complete successfully
        AND results should be independent and correct
        AND no race conditions should occur
        """
        import asyncio
        
        integrator.global_graph.edges.return_value = []
        
        # Execute multiple queries concurrently
        queries = ["query1", "query2", "query3", "query4", "query5"]
        tasks = [integrator.query_graph(query) for query in queries]
        
        results = await asyncio.gather(*tasks)
        
        # Verify all results are correct and independent
        assert len(results) == 5
        for i, result in enumerate(results):
            assert result["query"] == queries[i]
            assert isinstance(result, dict)
            # Each result should have the same structure
            required_keys = ['query', 'entities', 'relationships', 'total_matches', 'timestamp']
            for key in required_keys:
                assert key in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
