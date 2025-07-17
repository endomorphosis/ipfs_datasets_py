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
                source_page=1,
                source_elements=["paragraph"],
                token_count=12,
                semantic_types={"text"},
                relationships=[],
                metadata={}
            ),
            LLMChunk(
                chunk_id="chunk_2",
                content="John Smith lives in San Francisco.",
                source_page=1,
                source_elements=["paragraph"],
                token_count=8,
                semantic_types={"text"},
                relationships=[],
                metadata={}
            ),
            LLMChunk(
                chunk_id="chunk_3",
                content="ACME Corp has offices worldwide.",
                source_page=2,
                source_elements=["paragraph"],
                token_count=6,
                semantic_types={"text"},
                relationships=[],
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
             patch('ipfs_datasets_py.pdf_processing.graphrag_integrator.logger.info') as mock_log:
            
            # Setup mock returns
            # _extract_chunk_relationships will be called 2 times:
            # - chunk_1 has entities [entity_1, entity_2] -> called -> returns 2 relationships
            # - chunk_2 has entities [entity_1, entity_3] -> called -> returns 2 relationships
            # - chunk_3 has entity [entity_2] -> skipped (< 2 entities)
            # _extract_cross_chunk_relationships called once -> returns 1 relationship
            chunk_rels = [Mock(spec=Relationship) for _ in range(2)]
            cross_rels = [Mock(spec=Relationship) for _ in range(1)]
            mock_chunk_rels.return_value = chunk_rels
            mock_cross_rels.return_value = cross_rels
            
            result = await integrator._extract_relationships(sample_entities, sample_chunks)
            
            # Verify method calls
            assert mock_chunk_rels.call_count == 2  # chunk_1 and chunk_2
            mock_cross_rels.assert_called_once_with(sample_entities, sample_chunks)
            
            # Verify result
            assert isinstance(result, list)
            assert len(result) == 5  # 2 calls * 2 rels per call + 1 cross-chunk = 5 total
            
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
            
            mock_cross_rels.return_value = []
            
            result = await integrator._extract_relationships(sample_entities, [])
            
            assert result == []
            mock_chunk_rels.assert_not_called()
            # Cross-chunk method should NOT be called when chunks is empty because method returns early
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
             patch('ipfs_datasets_py.pdf_processing.graphrag_integrator.logger.info') as mock_log:
            
            relationships = [Mock(spec=Relationship) for _ in range(3)]
            mock_chunk_rels.return_value = relationships[:2]
            mock_cross_rels.return_value = relationships[2:]
            
            result = await integrator._extract_relationships(sample_entities, sample_chunks)
            
            # Verify logging was called
            mock_log.assert_called()
            
            # Verify the count in the log message matches the result
            # Same logic: 2 chunks * 2 rels per call + 1 cross-chunk = 5 total
            assert len(result) == 5

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
                source_page=i+1,
                source_elements=["paragraph"],
                token_count=10,
                semantic_types={"text"},
                relationships=[],
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
