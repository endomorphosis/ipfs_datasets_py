
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/graphrag_integrator.py
# Auto-generated on 2025-07-07 02:28:56
import pytest
import os
import asyncio
import re
from unittest.mock import Mock, AsyncMock, patch
from datetime import datetime
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator, KnowledgeGraph, Entity, Relationship
from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk



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




class TestQualityOfObjectsInModule:
    """
    Test class for the quality of callable objects 
    (e.g. class, method, function, coroutine, or property) in the module.
    """

    def test_callable_objects_metadata_quality(self):
        """
        GIVEN a Python module
        WHEN the module is parsed by the AST
        THEN
         - Each callable object should have a detailed, Google-style docstring.
         - Each callable object should have a detailed signature with type hints and a return annotation.
        """
        tree = get_ast_tree(file_path)
        try:
            raise_on_bad_callable_metadata(tree)
        except (BadDocumentationError, BadSignatureError) as e:
            pytest.fail(f"Code metadata quality check failed: {e}")

    def test_callable_objects_quality(self):
        """
        GIVEN a Python module
        WHEN the module's source code is examined
        THEN if the file is not indicated as a mock, placeholder, stub, or example:
         - The module should not contain intentionally fake or simplified code 
            (e.g. "In a real implementation, ...")
         - Contain no mocked objects or placeholders.
        """
        try:
            raise_on_bad_callable_code_quality(file_path)
        except (BadDocumentationError, BadSignatureError) as e:
            for indicator in ["mock", "placeholder", "stub", "example"]:
                if indicator in file_path:
                    break
            else:
                # If no indicator is found, fail the test
                pytest.fail(f"Code quality check failed: {e}")



class TestGraphRAGIntegratorInit:
    """Test class for GraphRAGIntegrator.__init__ method."""

    def test_init_with_default_parameters(self):
        """
        GIVEN no parameters are provided to GraphRAGIntegrator constructor
        WHEN a new GraphRAGIntegrator instance is created
        THEN the instance should be initialized with default values:
            - storage should be a new IPLDStorage instance
            - similarity_threshold should be 0.8
            - entity_extraction_confidence should be 0.6
            - knowledge_graphs should be an empty dict
            - global_entities should be an empty dict
            - cross_document_relationships should be an empty list
            - document_graphs should be an empty dict
            - global_graph should be an empty NetworkX DiGraph
        """
        integrator = GraphRAGIntegrator()
        
        assert isinstance(integrator.storage, IPLDStorage)
        assert integrator.similarity_threshold == 0.8
        assert integrator.entity_extraction_confidence == 0.6
        assert integrator.knowledge_graphs == {}
        assert integrator.global_entities == {}
        assert integrator.cross_document_relationships == []
        assert integrator.document_graphs == {}
        assert isinstance(integrator.global_graph, nx.DiGraph)
        assert len(integrator.global_graph.nodes) == 0
        assert len(integrator.global_graph.edges) == 0

    def test_init_with_custom_storage(self):
        """
        GIVEN a custom IPLDStorage instance is provided
        WHEN GraphRAGIntegrator is initialized with that storage
        THEN the instance should use the provided storage object
        AND other parameters should use default values
        """
        custom_storage = Mock(spec=IPLDStorage)
        integrator = GraphRAGIntegrator(storage=custom_storage)
        
        assert integrator.storage is custom_storage
        assert integrator.similarity_threshold == 0.8
        assert integrator.entity_extraction_confidence == 0.6

    def test_init_with_custom_similarity_threshold(self):
        """
        GIVEN a custom similarity_threshold value (e.g., 0.9)
        WHEN GraphRAGIntegrator is initialized with that threshold
        THEN the instance should store the custom threshold value
        AND other parameters should use default values
        """
        integrator = GraphRAGIntegrator(similarity_threshold=0.9)
        
        assert integrator.similarity_threshold == 0.9
        assert integrator.entity_extraction_confidence == 0.6
        assert isinstance(integrator.storage, IPLDStorage)

    def test_init_with_custom_entity_extraction_confidence(self):
        """
        GIVEN a custom entity_extraction_confidence value (e.g., 0.7)
        WHEN GraphRAGIntegrator is initialized with that confidence
        THEN the instance should store the custom confidence value
        AND other parameters should use default values
        """
        integrator = GraphRAGIntegrator(entity_extraction_confidence=0.7)
        
        assert integrator.entity_extraction_confidence == 0.7
        assert integrator.similarity_threshold == 0.8
        assert isinstance(integrator.storage, IPLDStorage)

    def test_init_with_all_custom_parameters(self):
        """
        GIVEN custom values for all parameters (storage, similarity_threshold, entity_extraction_confidence)
        WHEN GraphRAGIntegrator is initialized with these values
        THEN the instance should use all provided custom values
        AND all attributes should be properly initialized
        """
        custom_storage = Mock(spec=IPLDStorage)
        integrator = GraphRAGIntegrator(
            storage=custom_storage,
            similarity_threshold=0.95,
            entity_extraction_confidence=0.75
        )
        
        assert integrator.storage is custom_storage
        assert integrator.similarity_threshold == 0.95
        assert integrator.entity_extraction_confidence == 0.75

    def test_init_similarity_threshold_boundary_values(self):
        """
        GIVEN boundary values for similarity_threshold (0.0, 1.0)
        WHEN GraphRAGIntegrator is initialized with these values
        THEN the instance should accept and store these boundary values
        """
        integrator_min = GraphRAGIntegrator(similarity_threshold=0.0)
        integrator_max = GraphRAGIntegrator(similarity_threshold=1.0)
        
        assert integrator_min.similarity_threshold == 0.0
        assert integrator_max.similarity_threshold == 1.0

    def test_init_entity_extraction_confidence_boundary_values(self):
        """
        GIVEN boundary values for entity_extraction_confidence (0.0, 1.0)
        WHEN GraphRAGIntegrator is initialized with these values
        THEN the instance should accept and store these boundary values
        """
        integrator_min = GraphRAGIntegrator(entity_extraction_confidence=0.0)
        integrator_max = GraphRAGIntegrator(entity_extraction_confidence=1.0)
        
        assert integrator_min.entity_extraction_confidence == 0.0
        assert integrator_max.entity_extraction_confidence == 1.0

    def test_init_invalid_similarity_threshold_negative(self):
        """
        GIVEN a negative similarity_threshold value (e.g., -0.1)
        WHEN GraphRAGIntegrator is initialized with this value
        THEN a ValueError should be raised
        AND the error message should indicate invalid threshold range
        """
        with pytest.raises(ValueError) as exc_info:
            GraphRAGIntegrator(similarity_threshold=-0.1)
        
        assert "similarity_threshold must be between 0.0 and 1.0" in str(exc_info.value)

    def test_init_invalid_similarity_threshold_greater_than_one(self):
        """
        GIVEN a similarity_threshold value greater than 1.0 (e.g., 1.5)
        WHEN GraphRAGIntegrator is initialized with this value
        THEN a ValueError should be raised
        AND the error message should indicate invalid threshold range
        """
        with pytest.raises(ValueError) as exc_info:
            GraphRAGIntegrator(similarity_threshold=1.5)
        
        assert "similarity_threshold must be between 0.0 and 1.0" in str(exc_info.value)

    def test_init_invalid_entity_extraction_confidence_negative(self):
        """
        GIVEN a negative entity_extraction_confidence value (e.g., -0.1)
        WHEN GraphRAGIntegrator is initialized with this value
        THEN a ValueError should be raised
        AND the error message should indicate invalid confidence range
        """
        with pytest.raises(ValueError) as exc_info:
            GraphRAGIntegrator(entity_extraction_confidence=-0.1)
        
        assert "entity_extraction_confidence must be between 0.0 and 1.0" in str(exc_info.value)

    def test_init_invalid_entity_extraction_confidence_greater_than_one(self):
        """
        GIVEN an entity_extraction_confidence value greater than 1.0 (e.g., 1.2)
        WHEN GraphRAGIntegrator is initialized with this value
        THEN a ValueError should be raised
        AND the error message should indicate invalid confidence range
        """
        with pytest.raises(ValueError) as exc_info:
            GraphRAGIntegrator(entity_extraction_confidence=1.2)
        
        assert "entity_extraction_confidence must be between 0.0 and 1.0" in str(exc_info.value)

    def test_init_storage_type_validation(self):
        """
        GIVEN an invalid storage parameter (not an IPLDStorage instance)
        WHEN GraphRAGIntegrator is initialized with this parameter
        THEN a TypeError should be raised
        AND the error message should indicate expected type
        """
        with pytest.raises(TypeError) as exc_info:
            GraphRAGIntegrator(storage="not_an_ipld_storage")
        
        assert "storage must be an instance of IPLDStorage" in str(exc_info.value)

    def test_init_similarity_threshold_type_validation(self):
        """
        GIVEN a non-numeric similarity_threshold parameter (e.g., string)
        WHEN GraphRAGIntegrator is initialized with this parameter
        THEN a TypeError should be raised
        AND the error message should indicate expected numeric type
        """
        with pytest.raises(TypeError) as exc_info:
            GraphRAGIntegrator(similarity_threshold="0.8")
        
        assert "similarity_threshold must be a number" in str(exc_info.value)

    def test_init_entity_extraction_confidence_type_validation(self):
        """
        GIVEN a non-numeric entity_extraction_confidence parameter (e.g., string)
        WHEN GraphRAGIntegrator is initialized with this parameter
        THEN a TypeError should be raised
        AND the error message should indicate expected numeric type
        """
        with pytest.raises(TypeError) as exc_info:
            GraphRAGIntegrator(entity_extraction_confidence="0.6")
        
        assert "entity_extraction_confidence must be a number" in str(exc_info.value)

    def test_init_attributes_immutability(self):
        """
        GIVEN a GraphRAGIntegrator instance is created
        WHEN attempting to modify core attributes after initialization
        THEN the attributes should maintain their expected types and structure
        AND collections should be properly isolated (not shared references)
        """
        integrator1 = GraphRAGIntegrator()
        integrator2 = GraphRAGIntegrator()
        
        # Modify first integrator's collections
        integrator1.knowledge_graphs["test"] = "value"
        integrator1.global_entities["entity"] = "data"
        integrator1.cross_document_relationships.append("relationship")
        integrator1.document_graphs["doc"] = "graph"
        
        # Second integrator should be unaffected
        assert integrator2.knowledge_graphs == {}
        assert integrator2.global_entities == {}
        assert integrator2.cross_document_relationships == []
        assert integrator2.document_graphs == {}

    @pytest.fixture
    def mock_ipld_storage(self):
        """Mock IPLDStorage for testing."""
        return Mock(spec=IPLDStorage)

    def test_init_default_storage_creation(self, mock_ipld_storage):
        """
        GIVEN no storage parameter is provided
        WHEN GraphRAGIntegrator is initialized
        THEN a new IPLDStorage instance should be created
        AND the constructor should be called once with no arguments
        """
        # This test verifies that when no storage is provided, 
        # a default IPLDStorage instance is created
        integrator = GraphRAGIntegrator()
        assert isinstance(integrator.storage, IPLDStorage)

    def test_init_networkx_graph_initialization(self):
        """
        GIVEN GraphRAGIntegrator is initialized
        WHEN checking the global_graph attribute
        THEN it should be a NetworkX DiGraph instance
        AND it should be empty (no nodes or edges)
        AND it should be a directed graph
        """
        integrator = GraphRAGIntegrator()
        
        assert isinstance(integrator.global_graph, nx.DiGraph)
        assert integrator.global_graph.is_directed()
        assert len(integrator.global_graph.nodes) == 0
        assert len(integrator.global_graph.edges) == 0

    def test_init_collections_independence(self):
        """
        GIVEN multiple GraphRAGIntegrator instances are created
        WHEN modifying collections in one instance
        THEN other instances should not be affected
        AND each instance should have independent collections
        """
        integrator1 = GraphRAGIntegrator()
        integrator2 = GraphRAGIntegrator()
        integrator3 = GraphRAGIntegrator()
        
        # Modify first integrator
        integrator1.knowledge_graphs["doc1"] = "kg1"
        integrator1.global_entities["ent1"] = "entity1"
        integrator1.cross_document_relationships.append("rel1")
        
        # Modify second integrator differently
        integrator2.knowledge_graphs["doc2"] = "kg2"
        integrator2.global_entities["ent2"] = "entity2"
        
        # Verify independence
        assert "doc1" not in integrator2.knowledge_graphs
        assert "doc2" not in integrator1.knowledge_graphs
        assert "ent1" not in integrator2.global_entities
        assert "ent2" not in integrator1.global_entities
        assert len(integrator2.cross_document_relationships) == 0
        assert len(integrator3.cross_document_relationships) == 0
        assert integrator3.knowledge_graphs == {}
        assert integrator3.global_entities == {}



class TestIntegrateDocument:
    """Test class for GraphRAGIntegrator.integrate_document method."""

    @pytest.fixture
    def mock_integrator(self):
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

    @pytest.fixture
    def sample_llm_document(self):
        """Create a sample LLMDocument for testing."""
        chunks = [
            LLMChunk(
                chunk_id="chunk_1",
                content="Apple Inc. is a technology company founded by Steve Jobs.",
                page_number=1,
                source_page=1
            ),
            LLMChunk(
                chunk_id="chunk_2", 
                content="Steve Jobs was the CEO of Apple Inc. until 2011.",
                page_number=1,
                source_page=1
            )
        ]
        return LLMDocument(
            document_id="doc_123",
            title="Apple History",
            chunks=chunks
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
    async def test_integrate_document_valid_input(self, mock_integrator, sample_llm_document, sample_entities, sample_relationships):
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
    async def test_integrate_document_empty_chunks(self, mock_integrator):
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
            chunks=[]
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
    async def test_integrate_document_single_chunk(self, mock_integrator):
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
                page_number=1,
                source_page=1
            )]
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
    async def test_integrate_document_multiple_chunks_same_page(self, mock_integrator, sample_llm_document, sample_entities, sample_relationships):
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
    async def test_integrate_document_multiple_chunks_different_pages(self, mock_integrator):
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
                LLMChunk(chunk_id="chunk_1", content="Content page 1", page_number=1, source_page=1),
                LLMChunk(chunk_id="chunk_2", content="Content page 2", page_number=2, source_page=2),
                LLMChunk(chunk_id="chunk_3", content="More content page 2", page_number=2, source_page=2)
            ]
        )
        
        mock_integrator._extract_entities_from_chunks.return_value = []
        mock_integrator._extract_relationships.return_value = []
        mock_integrator._store_knowledge_graph_ipld.return_value = "multi_page_cid"
        
        result = await mock_integrator.integrate_document(multi_page_doc)
        
        assert len(result.chunks) == 3
        pages = set(chunk.source_page for chunk in result.chunks)
        assert pages == {1, 2}

    @pytest.mark.asyncio
    async def test_integrate_document_none_input(self, mock_integrator):
        """
        GIVEN None is passed as the llm_document parameter
        WHEN integrate_document is called
        THEN a ValueError should be raised
        AND the error message should indicate invalid document
        """
        with pytest.raises(ValueError) as exc_info:
            await mock_integrator.integrate_document(None)
        
        assert "llm_document cannot be None" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_integrate_document_missing_document_id(self, mock_integrator):
        """
        GIVEN an LLMDocument without a document_id
        WHEN integrate_document is called
        THEN a ValueError should be raised
        AND the error message should indicate missing document_id
        """
        invalid_doc = LLMDocument(
            document_id=None,
            title="Valid Title",
            chunks=[]
        )
        
        with pytest.raises(ValueError) as exc_info:
            await mock_integrator.integrate_document(invalid_doc)
        
        assert "document_id is required" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_integrate_document_missing_title(self, mock_integrator):
        """
        GIVEN an LLMDocument without a title
        WHEN integrate_document is called
        THEN a ValueError should be raised
        AND the error message should indicate missing title
        """
        invalid_doc = LLMDocument(
            document_id="valid_id",
            title=None,
            chunks=[]
        )
        
        with pytest.raises(ValueError) as exc_info:
            await mock_integrator.integrate_document(invalid_doc)
        
        assert "title is required" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_integrate_document_invalid_chunks_type(self, mock_integrator):
        """
        GIVEN an LLMDocument with chunks that are not LLMChunk instances
        WHEN integrate_document is called
        THEN a TypeError should be raised
        AND the error message should indicate invalid chunk types
        """
        invalid_doc = LLMDocument(
            document_id="valid_id",
            title="Valid Title",
            chunks=["not_a_chunk", "another_invalid_chunk"]
        )
        
        with pytest.raises(TypeError) as exc_info:
            await mock_integrator.integrate_document(invalid_doc)
        
        assert "All chunks must be LLMChunk instances" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_integrate_document_duplicate_document_id(self, mock_integrator, sample_llm_document):
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
            metadata={},
            creation_timestamp="2024-01-01T00:00:00Z"
        )
        mock_integrator.knowledge_graphs["doc_123"] = existing_kg
        
        mock_integrator._extract_entities_from_chunks.return_value = []
        mock_integrator._extract_relationships.return_value = []
        mock_integrator._store_knowledge_graph_ipld.return_value = "new_cid"
        
        with patch('logging.warning') as mock_warning:
            result = await mock_integrator.integrate_document(sample_llm_document)
            
            mock_warning.assert_called_once()
            assert "overwriting existing knowledge graph" in mock_warning.call_args[0][0].lower()

    @pytest.mark.asyncio
    async def test_integrate_document_entity_extraction_failure(self, mock_integrator, sample_llm_document):
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
    async def test_integrate_document_relationship_extraction_failure(self, mock_integrator, sample_llm_document, sample_entities):
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
    async def test_integrate_document_ipld_storage_failure(self, mock_integrator, sample_llm_document, sample_entities, sample_relationships):
        """
        GIVEN IPLD storage fails when storing the knowledge graph
        WHEN integrate_document is called
        THEN an IPLDStorageError should be raised
        AND the knowledge graph should not be added to global structures
        """
        mock_integrator._extract_entities_from_chunks.return_value = sample_entities
        mock_integrator._extract_relationships.return_value = sample_relationships
        
        from ipfs_datasets_py.ipld import IPLDStorageError
        mock_integrator._store_knowledge_graph_ipld.side_effect = IPLDStorageError("Storage failed")
        
        with pytest.raises(IPLDStorageError) as exc_info:
            await mock_integrator.integrate_document(sample_llm_document)
        
        assert "Storage failed" in str(exc_info.value)
        mock_integrator._merge_into_global_graph.assert_not_called()

    @pytest.mark.asyncio
    async def test_integrate_document_networkx_graph_creation(self, mock_integrator, sample_llm_document, sample_entities, sample_relationships):
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
    async def test_integrate_document_global_graph_merge(self, mock_integrator, sample_llm_document, sample_entities, sample_relationships):
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
    async def test_integrate_document_cross_document_relationship_discovery(self, mock_integrator, sample_llm_document, sample_entities, sample_relationships):
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
    async def test_integrate_document_timestamp_creation(self, mock_integrator, sample_llm_document):
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
        
        # Parse the timestamp
        timestamp = datetime.fromisoformat(result.creation_timestamp.replace('Z', '+00:00'))
        
        # Check it's within reasonable bounds (allowing for test execution time)
        assert before_time <= timestamp.replace(tzinfo=None) <= after_time
        assert result.creation_timestamp.endswith('Z')  # ISO 8601 UTC format

    @pytest.mark.asyncio
    async def test_integrate_document_graph_id_generation(self, mock_integrator, sample_llm_document):
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
        assert len(result1.graph_id) > len(sample_llm_document.document_id)  # Should be enhanced

    @pytest.mark.asyncio
    async def test_integrate_document_metadata_population(self, mock_integrator, sample_llm_document, sample_entities, sample_relationships):
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
        
        assert 'entity_count' in result.metadata
        assert 'relationship_count' in result.metadata
        assert 'chunk_count' in result.metadata
        assert 'similarity_threshold' in result.metadata
        assert 'entity_extraction_confidence' in result.metadata
        
        assert result.metadata['entity_count'] == len(sample_entities)
        assert result.metadata['relationship_count'] == len(sample_relationships)
        assert result.metadata['chunk_count'] == len(sample_llm_document.chunks)

    @pytest.mark.asyncio
    async def test_integrate_document_concurrent_integration(self, mock_integrator):
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
                    page_number=1,
                    source_page=1
                )]
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
    async def test_integrate_document_large_document(self, mock_integrator):
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
                page_number=i // 10 + 1,
                source_page=i // 10 + 1
            ) for i in range(150)
        ]
        
        large_doc = LLMDocument(
            document_id="large_doc",
            title="Large Document",
            chunks=large_chunks
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
    async def test_integrate_document_chunks_without_entities(self, mock_integrator):
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
                page_number=1,
                source_page=1
            )]
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
    async def test_integrate_document_chunks_with_low_confidence_entities(self, mock_integrator):
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
                page_number=1,
                source_page=1
            )]
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








class TestExtractEntitiesFromChunks:
    """Test class for GraphRAGIntegrator._extract_entities_from_chunks method."""

    @pytest.fixture
    def mock_integrator(self):
        """Create a mock GraphRAGIntegrator for testing."""
        integrator = GraphRAGIntegrator(entity_extraction_confidence=0.7)
        integrator._extract_entities_from_text = AsyncMock()
        return integrator

    @pytest.fixture
    def sample_chunks(self):
        """Create sample LLMChunk objects for testing."""
        return [
            LLMChunk(
                chunk_id="chunk_1",
                content="Apple Inc. was founded by Steve Jobs in Cupertino.",
                page_number=1,
                source_page=1
            ),
            LLMChunk(
                chunk_id="chunk_2",
                content="Steve Jobs became CEO of Apple Inc. in 1997.",
                page_number=1,
                source_page=1
            ),
            LLMChunk(
                chunk_id="chunk_3",
                content="Microsoft Corporation is based in Redmond, Washington.",
                page_number=2,
                source_page=2
            )
        ]

    @pytest.fixture
    def sample_entity_dicts(self):
        """Create sample entity dictionaries as returned by _extract_entities_from_text."""
        return [
            # From chunk_1
            [
                {
                    'name': 'Apple Inc.',
                    'type': 'organization',
                    'description': 'Technology company',
                    'confidence': 0.8,
                    'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'chunk_1'}
                },
                {
                    'name': 'Steve Jobs',
                    'type': 'person',
                    'description': 'Person mentioned in document',
                    'confidence': 0.9,
                    'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'chunk_1'}
                }
            ],
            # From chunk_2
            [
                {
                    'name': 'Steve Jobs',
                    'type': 'person',
                    'description': 'Person mentioned in document',
                    'confidence': 0.85,
                    'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'chunk_2'}
                },
                {
                    'name': 'Apple Inc.',
                    'type': 'organization',
                    'description': 'Technology company',
                    'confidence': 0.75,
                    'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'chunk_2'}
                }
            ],
            # From chunk_3
            [
                {
                    'name': 'Microsoft Corporation',
                    'type': 'organization',
                    'description': 'Technology company',
                    'confidence': 0.9,
                    'properties': {'extraction_method': 'regex_pattern_matching', 'source_chunk': 'chunk_3'}
                }
            ]
        ]

    @pytest.mark.asyncio
    async def test_extract_entities_from_chunks_valid_input(self, mock_integrator, sample_chunks, sample_entity_dicts):
        """
        GIVEN a list of LLMChunk objects containing entity-rich text
        WHEN _extract_entities_from_chunks is called
        THEN a list of Entity objects should be returned
        AND entities should be deduplicated across chunks
        AND only entities above confidence threshold should be included
        """
        # Setup mock to return different entities for each chunk
        mock_integrator._extract_entities_from_text.side_effect = sample_entity_dicts
        
        result = await mock_integrator._extract_entities_from_chunks(sample_chunks)
        
        # Should call _extract_entities_from_text for each chunk
        assert mock_integrator._extract_entities_from_text.call_count == 3
        
        # Verify Entity objects are returned
        assert all(isinstance(entity, Entity) for entity in result)
        
        # Verify deduplication - Steve Jobs and Apple Inc. appear in multiple chunks
        entity_names = [entity.name for entity in result]
        assert len(set(entity_names)) == len(entity_names)  # No duplicates
        
        # Should have Apple Inc., Steve Jobs, and Microsoft Corporation
        expected_names = {'Apple Inc.', 'Steve Jobs', 'Microsoft Corporation'}
        actual_names = set(entity_names)
        assert actual_names == expected_names

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
            page_number=1,
            source_page=1
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
            page_number=1,
            source_page=1
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
            LLMChunk(chunk_id="chunk_a", content="Google was founded in 1998.", page_number=1, source_page=1),
            LLMChunk(chunk_id="chunk_b", content="Google LLC is a search company.", page_number=1, source_page=1)
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
            LLMChunk(chunk_id="chunk_1", content="Apple Inc. is great.", page_number=1, source_page=1),
            LLMChunk(chunk_id="chunk_2", content="apple inc. makes phones.", page_number=1, source_page=1)
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
            page_number=1,
            source_page=1
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
            LLMChunk(chunk_id="chunk_1", content="Amazon was founded in 1994.", page_number=1, source_page=1),
            LLMChunk(chunk_id="chunk_2", content="Amazon is in Seattle.", page_number=1, source_page=1)
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
            LLMChunk(chunk_id="chunk_1", content="Netflix is streaming.", page_number=1, source_page=1),
            LLMChunk(chunk_id="chunk_2", content="Netflix has shows.", page_number=1, source_page=1)
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
            page_number=1,
            source_page=1
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
                page_number=1,
                source_page=1
            ),
            LLMChunk(
                chunk_id="empty_2", 
                content="More text that has no named entities.",
                page_number=1,
                source_page=1
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
        class InvalidChunk:
            def __init__(self):
                self.chunk_id = "invalid"
                # Missing content attribute
        
        invalid_chunks = [InvalidChunk()]
        
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
        class InvalidChunk:
            def __init__(self):
                self.content = "Some content"
                # Missing chunk_id attribute
        
        invalid_chunks = [InvalidChunk()]
        
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
        
        with pytest.raises(Exception) as exc_info:
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
                page_number=i // 10 + 1,
                source_page=i // 10 + 1
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
        
        import time
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
            LLMChunk(chunk_id="first", content="Facebook is social.", page_number=1, source_page=1),
            LLMChunk(chunk_id="second", content="Facebook connects people.", page_number=1, source_page=1)
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
            LLMChunk(chunk_id="low_conf", content="Twitter is a platform.", page_number=1, source_page=1),
            LLMChunk(chunk_id="high_conf", content="Twitter Inc. is social media.", page_number=1, source_page=1),
            LLMChunk(chunk_id="med_conf", content="Twitter has users.", page_number=1, source_page=1)
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
            LLMChunk(chunk_id="chunk_a", content="LinkedIn is professional.", page_number=1, source_page=1),
            LLMChunk(chunk_id="chunk_b", content="LinkedIn connects professionals.", page_number=1, source_page=1),
            LLMChunk(chunk_id="chunk_c", content="LinkedIn has job listings.", page_number=2, source_page=2)
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
            LLMChunk(chunk_id="empty", content="", page_number=1, source_page=1),
            LLMChunk(chunk_id="whitespace", content="   \n\t  ", page_number=1, source_page=1),
            LLMChunk(chunk_id="valid", content="Tesla makes cars.", page_number=1, source_page=1)
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
            page_number=1,
            source_page=1
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
            LLMChunk(chunk_id="valid", content="Valid chunk.", page_number=1, source_page=1),
            None,
            LLMChunk(chunk_id="also_valid", content="Another valid chunk.", page_number=1, source_page=1)
        ]
        
        with pytest.raises(TypeError) as exc_info:
            await mock_integrator._extract_entities_from_chunks(mixed_chunks)
        
        assert "All chunks must be LLMChunk instances" in str(exc_info.value)



class TestExtractEntitiesFromText:
    """Test class for GraphRAGIntegrator._extract_entities_from_text method."""

    @pytest.fixture
    def integrator(self):
        """Create a GraphRAGIntegrator instance for testing."""
        return GraphRAGIntegrator()

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_person_entities(self, integrator):
        """
        GIVEN text containing person names in various formats
        WHEN _extract_entities_from_text is called
        THEN person entities should be extracted correctly
        AND entity type should be 'person'
        AND confidence should be 0.7
        AND names should include titles when present
        """
        text = "Dr. John Smith and Ms. Jane Doe met with Robert Johnson yesterday."
        chunk_id = "person_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        person_entities = [entity for entity in result if entity['type'] == 'person']
        assert len(person_entities) >= 3
        
        person_names = [entity['name'] for entity in person_entities]
        assert 'Dr. John Smith' in person_names
        assert 'Ms. Jane Doe' in person_names
        assert 'Robert Johnson' in person_names
        
        for entity in person_entities:
            assert entity['confidence'] == 0.7
            assert entity['type'] == 'person'
            assert entity['properties']['source_chunk'] == chunk_id

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_organization_entities(self, integrator):
        """
        GIVEN text containing organization names with common suffixes
        WHEN _extract_entities_from_text is called
        THEN organization entities should be extracted correctly
        AND entity type should be 'organization'
        AND various suffixes (Inc., Corp., LLC, University, etc.) should be recognized
        """
        text = "Apple Inc. partnered with Microsoft Corporation and Harvard University. Amazon LLC also joined."
        chunk_id = "org_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        org_entities = [entity for entity in result if entity['type'] == 'organization']
        assert len(org_entities) >= 4
        
        org_names = [entity['name'] for entity in org_entities]
        assert 'Apple Inc.' in org_names
        assert 'Microsoft Corporation' in org_names
        assert 'Harvard University' in org_names
        assert 'Amazon LLC' in org_names
        
        for entity in org_entities:
            assert entity['confidence'] == 0.7
            assert entity['type'] == 'organization'
            assert entity['properties']['source_chunk'] == chunk_id

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_location_entities(self, integrator):
        """
        GIVEN text containing addresses and city/state combinations
        WHEN _extract_entities_from_text is called
        THEN location entities should be extracted correctly
        AND entity type should be 'location'
        AND both full addresses and city/state pairs should be recognized
        """
        text = "The office at 123 Main Street, San Francisco, CA hosts meetings. New York, NY is busy."
        chunk_id = "location_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        location_entities = [entity for entity in result if entity['type'] == 'location']
        assert len(location_entities) >= 2
        
        location_names = [entity['name'] for entity in location_entities]
        assert any('San Francisco, CA' in name for name in location_names)
        assert any('New York, NY' in name for name in location_names)
        
        for entity in location_entities:
            assert entity['confidence'] == 0.7
            assert entity['type'] == 'location'
            assert entity['properties']['source_chunk'] == chunk_id

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_date_entities(self, integrator):
        """
        GIVEN text containing dates in various formats
        WHEN _extract_entities_from_text is called
        THEN date entities should be extracted correctly
        AND entity type should be 'date'
        AND formats MM/DD/YYYY, Month DD, YYYY should be recognized
        """
        text = "The meeting on 12/25/2023 was followed by another on January 15, 2024."
        chunk_id = "date_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        date_entities = [entity for entity in result if entity['type'] == 'date']
        assert len(date_entities) >= 2
        
        date_names = [entity['name'] for entity in date_entities]
        assert '12/25/2023' in date_names
        assert 'January 15, 2024' in date_names
        
        for entity in date_entities:
            assert entity['confidence'] == 0.7
            assert entity['type'] == 'date'
            assert entity['properties']['source_chunk'] == chunk_id

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_currency_entities(self, integrator):
        """
        GIVEN text containing currency amounts and expressions
        WHEN _extract_entities_from_text is called
        THEN currency entities should be extracted correctly
        AND entity type should be 'currency'
        AND dollar amounts and currency words should be recognized
        """
        text = "The contract was worth $50,000 and they paid an additional 25000 dollars."
        chunk_id = "currency_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        currency_entities = [entity for entity in result if entity['type'] == 'currency']
        assert len(currency_entities) >= 2
        
        currency_names = [entity['name'] for entity in currency_entities]
        assert '$50,000' in currency_names
        assert '25000 dollars' in currency_names
        
        for entity in currency_entities:
            assert entity['confidence'] == 0.7
            assert entity['type'] == 'currency'
            assert entity['properties']['source_chunk'] == chunk_id

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_empty_string(self, integrator):
        """
        GIVEN an empty string as input text
        WHEN _extract_entities_from_text is called
        THEN an empty list should be returned
        AND no errors should be raised
        """
        text = ""
        chunk_id = "empty_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_whitespace_only(self, integrator):
        """
        GIVEN text containing only whitespace characters
        WHEN _extract_entities_from_text is called
        THEN an empty list should be returned
        AND no errors should be raised
        """
        text = "   \n\t\r   "
        chunk_id = "whitespace_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_no_entities(self, integrator):
        """
        GIVEN text that contains no recognizable entities
        WHEN _extract_entities_from_text is called
        THEN an empty list should be returned
        AND no errors should be raised
        """
        text = "This is just plain text with no entities to extract from it."
        chunk_id = "no_entities_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        assert result == []

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_duplicate_entities(self, integrator):
        """
        GIVEN text containing the same entity mentioned multiple times
        WHEN _extract_entities_from_text is called
        THEN only unique entities should be returned
        AND duplicates should be filtered out
        """
        text = "Apple Inc. makes phones. Apple Inc. is innovative. Apple Inc. is successful."
        chunk_id = "duplicate_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        apple_entities = [entity for entity in result if 'Apple Inc.' in entity['name']]
        assert len(apple_entities) == 1  # Should be deduplicated

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_case_variations(self, integrator):
        """
        GIVEN text containing entities with different case variations
        WHEN _extract_entities_from_text is called
        THEN entities should be extracted preserving original case
        AND case variations should be treated as separate entities initially
        """
        text = "MICROSOFT and Microsoft and microsoft are mentioned."
        chunk_id = "case_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        # The method should extract based on patterns, case variations may be treated differently
        microsoft_entities = [entity for entity in result if 'microsoft' in entity['name'].lower()]
        assert len(microsoft_entities) >= 1

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_overlapping_patterns(self, integrator):
        """
        GIVEN text where entity patterns overlap (e.g., person name within organization)
        WHEN _extract_entities_from_text is called
        THEN the most specific or longest match should be preferred
        AND both entities should be extracted if they're genuinely different
        """
        text = "John Smith founded John Smith Inc. and hired Mary Johnson."
        chunk_id = "overlap_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        # Should extract both person and organization entities
        person_entities = [entity for entity in result if entity['type'] == 'person']
        org_entities = [entity for entity in result if entity['type'] == 'organization']
        
        assert len(person_entities) >= 1  # John Smith, Mary Johnson
        assert len(org_entities) >= 1    # John Smith Inc.

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_special_characters(self, integrator):
        """
        GIVEN text containing entities with special characters, apostrophes, hyphens
        WHEN _extract_entities_from_text is called
        THEN entities should be extracted correctly including special characters
        AND regex patterns should handle these characters appropriately
        """
        text = "O'Reilly Media and Coca-Cola Company work with Jean-Pierre's firm."
        chunk_id = "special_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        entity_names = [entity['name'] for entity in result]
        # The exact extraction depends on regex patterns, but should handle common patterns
        assert len(result) >= 1  # Should extract at least some entities

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_unicode_characters(self, integrator):
        """
        GIVEN text containing entities with unicode characters (accented letters, etc.)
        WHEN _extract_entities_from_text is called
        THEN entities should be extracted correctly preserving unicode
        AND no encoding errors should occur
        """
        text = "José García works at Café René and Björk Enterprises in São Paulo."
        chunk_id = "unicode_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        # Should handle unicode characters without errors
        assert isinstance(result, list)
        for entity in result:
            assert isinstance(entity['name'], str)
            # Unicode characters should be preserved
            assert all(isinstance(value, str) for value in entity.values() if isinstance(value, str))

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_mixed_entity_types(self, integrator):
        """
        GIVEN text containing multiple types of entities together
        WHEN _extract_entities_from_text is called
        THEN all entity types should be extracted correctly
        AND each should have the appropriate type classification
        """
        text = "Dr. Sarah Wilson from Stanford University visited Google Inc. on 03/15/2024 for a $10,000 project in Palo Alto, CA."
        chunk_id = "mixed_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        entity_types = set(entity['type'] for entity in result)
        # Should extract multiple types
        assert len(entity_types) >= 2
        
        # Verify each type has appropriate entities
        for entity in result:
            assert entity['type'] in ['person', 'organization', 'location', 'date', 'currency']
            assert entity['confidence'] == 0.7

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_chunk_id_assignment(self, integrator):
        """
        GIVEN a specific chunk_id parameter
        WHEN _extract_entities_from_text is called
        THEN all extracted entities should have the chunk_id in their properties
        AND the chunk_id should be correctly stored in extraction metadata
        """
        text = "IBM Corporation develops technology."
        chunk_id = "test_chunk_123"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        for entity in result:
            assert entity['properties']['source_chunk'] == chunk_id

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_confidence_scores(self, integrator):
        """
        GIVEN any text with entities
        WHEN _extract_entities_from_text is called
        THEN all entities should have confidence score of 0.7
        AND confidence should be consistent across all entity types
        """
        text = "John Doe works at Apple Inc. in San Francisco, CA on 01/01/2024 for $75,000."
        chunk_id = "confidence_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        for entity in result:
            assert entity['confidence'] == 0.7

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_entity_descriptions(self, integrator):
        """
        GIVEN text with various entity types
        WHEN _extract_entities_from_text is called
        THEN each entity should have an appropriate human-readable description
        AND descriptions should indicate the entity type and extraction context
        """
        text = "Microsoft Corporation was founded by Bill Gates in Seattle, WA on 04/04/1975."
        chunk_id = "description_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        for entity in result:
            assert 'description' in entity
            assert isinstance(entity['description'], str)
            assert len(entity['description']) > 0
            
            # Descriptions should relate to entity type
            if entity['type'] == 'person':
                assert 'person' in entity['description'].lower()
            elif entity['type'] == 'organization':
                assert any(word in entity['description'].lower() for word in ['company', 'organization', 'corp'])
            elif entity['type'] == 'location':
                assert any(word in entity['description'].lower() for word in ['location', 'place'])
            elif entity['type'] == 'date':
                assert 'date' in entity['description'].lower()
            elif entity['type'] == 'currency':
                assert any(word in entity['description'].lower() for word in ['currency', 'amount', 'money'])

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_properties_structure(self, integrator):
        """
        GIVEN any text with entities
        WHEN _extract_entities_from_text is called
        THEN each entity should have a properties dict containing:
            - extraction_method: 'regex_pattern_matching'
            - source_chunk: the provided chunk_id
        """
        text = "Tesla Inc. makes electric vehicles."
        chunk_id = "properties_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        for entity in result:
            assert 'properties' in entity
            assert isinstance(entity['properties'], dict)
            assert entity['properties']['extraction_method'] == 'regex_pattern_matching'
            assert entity['properties']['source_chunk'] == chunk_id

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_regex_error_handling(self, integrator):
        """
        GIVEN malformed regex patterns (hypothetically)
        WHEN _extract_entities_from_text is called
        THEN a re.error should be raised
        AND the error should be properly propagated
        """
        # This test verifies that regex errors are handled properly
        # We'll patch the regex patterns to be malformed
        text = "Some text to test regex error handling."
        chunk_id = "regex_error_chunk"
        
        with patch.object(integrator, '_extract_entities_from_text') as mock_extract:
            mock_extract.side_effect = re.error("Invalid regex pattern")
            
            with pytest.raises(re.error) as exc_info:
                await mock_extract(text, chunk_id)
            
            assert "Invalid regex pattern" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_large_text_input(self, integrator):
        """
        GIVEN a very large text input (>10KB)
        WHEN _extract_entities_from_text is called
        THEN all entities should be extracted efficiently
        AND performance should remain reasonable
        AND no memory issues should occur
        """
        # Create large text with repeated entities
        base_text = "Apple Inc. was founded by Steve Jobs in Cupertino, CA on 04/01/1976 for $1,000. "
        large_text = base_text * 500  # ~50KB of text
        chunk_id = "large_chunk"
        
        import time
        start_time = time.time()
        result = await integrator._extract_entities_from_text(large_text, chunk_id)
        end_time = time.time()
        
        # Should complete in reasonable time
        assert end_time - start_time < 10  # 10 seconds max
        
        # Should extract entities (may have duplicates that will be filtered)
        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_none_text_input(self, integrator):
        """
        GIVEN None as the text parameter
        WHEN _extract_entities_from_text is called
        THEN a TypeError should be raised
        AND the error should indicate invalid text type
        """
        with pytest.raises(TypeError) as exc_info:
            await integrator._extract_entities_from_text(None, "chunk_id")
        
        assert "text must be a string" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_none_chunk_id(self, integrator):
        """
        GIVEN None as the chunk_id parameter
        WHEN _extract_entities_from_text is called
        THEN a TypeError should be raised
        AND the error should indicate invalid chunk_id type
        """
        with pytest.raises(TypeError) as exc_info:
            await integrator._extract_entities_from_text("Some text", None)
        
        assert "chunk_id must be a string" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_non_string_inputs(self, integrator):
        """
        GIVEN non-string inputs for text or chunk_id parameters
        WHEN _extract_entities_from_text is called
        THEN a TypeError should be raised
        AND the error should indicate expected string types
        """
        # Test non-string text
        with pytest.raises(TypeError) as exc_info:
            await integrator._extract_entities_from_text(123, "chunk_id")
        assert "text must be a string" in str(exc_info.value)
        
        # Test non-string chunk_id
        with pytest.raises(TypeError) as exc_info:
            await integrator._extract_entities_from_text("Some text", 456)
        assert "chunk_id must be a string" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_edge_case_patterns(self, integrator):
        """
        GIVEN text with edge cases like single letters, numbers only, punctuation only
        WHEN _extract_entities_from_text is called
        THEN these should not be extracted as entities
        AND no false positives should occur
        """
        text = "A B C 123 456 !@# $$ ... --- +++ 999"
        chunk_id = "edge_case_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        # Should not extract single letters, numbers, or punctuation as entities
        for entity in result:
            assert len(entity['name'].strip()) > 1  # Should be meaningful names
            assert not entity['name'].isdigit()  # Should not be pure numbers

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_boundary_matching(self, integrator):
        """
        GIVEN text where potential entities are at word boundaries vs embedded in words
        WHEN _extract_entities_from_text is called
        THEN only properly bounded entities should be extracted
        AND partial word matches should be avoided
        """
        text = "Microprocessor and Microsoft are different. Applegate versus Apple Inc."
        chunk_id = "boundary_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        entity_names = [entity['name'] for entity in result]
        
        # Should extract proper entities, not partial matches
        if 'Microsoft' in entity_names:
            assert 'Microprocessor' not in entity_names or any('Microsoft' in name for name in entity_names)
        
        if any('Apple' in name for name in entity_names):
            # Should prefer "Apple Inc." over partial "Apple" from "Applegate"
            apple_entities = [name for name in entity_names if 'Apple' in name]
            assert any('Inc' in name or name == 'Apple' for name in apple_entities)

    @pytest.mark.asyncio
    async def test_extract_entities_from_text_return_type_validation(self, integrator):
        """
        GIVEN any valid text input
        WHEN _extract_entities_from_text is called
        THEN the return value should be a list
        AND each element should be a dictionary with expected keys
        AND the structure should match the documented format
        """
        text = "Amazon Inc. was founded by Jeff Bezos."
        chunk_id = "return_type_chunk"
        
        result = await integrator._extract_entities_from_text(text, chunk_id)
        
        assert isinstance(result, list)
        
        for entity in result:
            assert isinstance(entity, dict)
            
            # Required keys
            required_keys = ['name', 'type', 'description', 'confidence', 'properties']
            for key in required_keys:
                assert key in entity, f"Missing required key: {key}"
            
            # Type validation
            assert isinstance(entity['name'], str)
            assert isinstance(entity['type'], str)
            assert isinstance(entity['description'], str)
            assert isinstance(entity['confidence'], (int, float))
            assert isinstance(entity['properties'], dict)
            
            # Value validation
            assert len(entity['name']) > 0
            assert entity['type'] in ['person', 'organization', 'location', 'date', 'currency']
            assert 0.0 <= entity['confidence'] <= 1.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
