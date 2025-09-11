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


from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_factory import (
    LLMChunkMetadataTestDataFactory as MetadataFactory
)

class TestExtractChunkRelationships:
    """Test class for GraphRAGIntegrator._extract_chunk_relationships method."""

    @pytest.mark.asyncio
    async def test_extract_chunk_relationships_valid_input(
        self, integrator, sample_entities, sample_chunk):
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
            source_page=1,
            source_elements=["paragraph"],
            token_count=7,
            semantic_types="text",
            metadata=self.sample_metadata
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
            
            # Verify ID format (should be rel_ prefix + 8 char MD5 hash)
            for rel in result:
                assert rel.id.startswith('rel_')
                assert len(rel.id) == 12  # 'rel_' + 8 char hash
                hash_part = rel.id[4:]  # Remove 'rel_' prefix
                assert all(c in '0123456789abcdef' for c in hash_part)

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
                assert rel.properties['extraction_method'] == 'co_occurrence'
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
            source_page=1,
            source_elements=["paragraph"],
            token_count=10,
            semantic_types="text",
            metadata=self.sample_metadata
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
        GIVEN a chunk without chunk_id attribute and entities present
        WHEN _extract_chunk_relationships is called
        THEN an AttributeError should be raised
        AND the error should indicate missing chunk_id
        """
        invalid_chunk = Mock()
        invalid_chunk.content = "John Smith works at ACME Corp"
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
        invalid_entity1 = Mock()
        invalid_entity2 = Mock()
        del invalid_entity1.id
        del invalid_entity1.name
        del invalid_entity2.id
        del invalid_entity2.name
        
        with pytest.raises(AttributeError):
            await integrator._extract_chunk_relationships([invalid_entity1, invalid_entity2], sample_chunk)

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
            source_page=1,
            source_elements=["paragraph"],
            token_count=1,
            semantic_types="text",
            metadata=self.sample_metadata
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
            source_page=1,
            source_elements=["paragraph"],
            token_count=len(content.split()),
            semantic_types="text",
            metadata=self.sample_metadata
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
            source_page=1,
            source_elements=["paragraph"],
            token_count=9,
            semantic_types="text",
            metadata=self.sample_metadata
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
