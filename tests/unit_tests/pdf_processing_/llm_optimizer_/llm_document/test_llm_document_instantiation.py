#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer.py
# Auto-generated on 2025-07-07 02:28:56"

from datetime import datetime
import pytest
import os

import os
import pytest
import time
import numpy as np
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
file_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/llm_optimizer.py")
md_path = os.path.join(work_dir, "ipfs_datasets_py/pdf_processing/llm_optimizer_stubs.md")

# Make sure the input file and documentation file exist.
assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."

from ipfs_datasets_py.pdf_processing.llm_optimizer import (
    ChunkOptimizer,
    LLMOptimizer,
    TextProcessor,
    LLMChunk,
    LLMDocument
)

from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_document.llm_document_factory import (
    LLMDocumentTestDataFactory
)


# Check if each classes methods are accessible:
assert LLMOptimizer._initialize_models
assert LLMOptimizer.optimize_for_llm
assert LLMOptimizer._extract_structured_text
assert LLMOptimizer._generate_document_summary
assert LLMOptimizer._create_optimal_chunks
assert LLMOptimizer._create_chunk
assert LLMOptimizer._establish_chunk_relationships
assert LLMOptimizer._generate_embeddings
assert LLMOptimizer._extract_key_entities
assert LLMOptimizer._generate_document_embedding
assert LLMOptimizer._count_tokens
assert LLMOptimizer._get_chunk_overlap
assert TextProcessor.split_sentences
assert TextProcessor.extract_keywords
assert ChunkOptimizer.optimize_chunk_boundaries


# 4. Check if the modules's imports are accessible:
try:
    import anyio
    import logging
    from typing import Dict, List, Any, Optional
    from dataclasses import dataclass
    import re

    from pydantic import (
        BaseModel, 
        Field, 
        field_validator,
        NonNegativeInt,
        ValidationError
    )
    import tiktoken
    from transformers import AutoTokenizer
    import numpy as np
    from sentence_transformers import SentenceTransformer
except ImportError as e:
    raise ImportError(f"Failed to import necessary modules: {e}")



class TestLLMDocumentInstantiation:
    """Test LLMDocument instantiation with various parameter combinations."""

    def test_instantiation_with_all_fields(self):
        """
        GIVEN all required LLMDocument fields with valid values
        WHEN LLMDocument is instantiated
        THEN expect:
            - Instance created successfully
            - All fields accessible with correct values
            - No errors or exceptions raised
        """
        # Given
        document_data = LLMDocumentTestDataFactory.create_valid_baseline_data()
        
        # When
        document = LLMDocument(**document_data)
        
        # Then
        assert document.document_id == document_data["document_id"]
        assert document.title == document_data["title"]
        assert len(document.chunks) == len(document_data["chunks"])
        assert document.chunks == document_data["chunks"]
        assert document.summary == document_data["summary"]
        assert document.key_entities == document_data["key_entities"]
        assert document.processing_metadata == document_data["processing_metadata"]
        if document_data["document_embedding"] is not None:
            assert np.array_equal(document.document_embedding, document_data["document_embedding"])
        else:
            assert document.document_embedding is None

    def test_instantiation_with_minimal_fields(self):
        """
        GIVEN only required LLMDocument fields (no defaults)
        WHEN LLMDocument is instantiated
        THEN expect:
            - Instance created successfully if all required fields provided
            - Default values applied where appropriate
        """
        # Given
        document_data = LLMDocumentTestDataFactory.create_minimal_valid_data()
        
        # When - using minimal required fields
        document = LLMDocument(**document_data)
        
        # Then
        assert document.document_id == document_data["document_id"]
        assert document.title == document_data["title"]
        assert len(document.chunks) == len(document_data["chunks"])
        assert document.summary == document_data["summary"]
        assert document.key_entities == document_data["key_entities"]
        assert document.processing_metadata == document_data["processing_metadata"]
        assert document.document_embedding is None  # Default value

    def test_instantiation_missing_required_fields(self):
        """
        GIVEN missing required fields during instantiation
        WHEN LLMDocument is instantiated
        THEN expect ValidationError to be raised for missing required parameters
        """
        from pydantic import ValidationError
        
        # When/Then - missing document_id
        data_missing_id = LLMDocumentTestDataFactory.create_data_missing_field("document_id")
        with pytest.raises(ValueError):
            LLMDocument(**data_missing_id)
        
        # When/Then - missing multiple fields
        with pytest.raises(ValueError):
            LLMDocument(document_id="doc_001")
        
        # When/Then - missing chunks field
        data_missing_chunks = LLMDocumentTestDataFactory.create_data_missing_field("chunks")
        with pytest.raises(ValueError):
            LLMDocument(**data_missing_chunks)

    def test_instantiation_with_none_document_embedding(self):
        """
        GIVEN document_embedding field set to None
        WHEN LLMDocument is instantiated
        THEN expect:
            - Instance created successfully
            - document_embedding field properly set to None
            - Optional type handling works correctly
        """
        # Given
        document_data = LLMDocumentTestDataFactory.create_minimal_valid_data()
        document_data["document_embedding"] = None
        
        # When
        document = LLMDocument(**document_data)
        
        # Then
        assert document.document_embedding is None

    def test_instantiation_with_numpy_document_embedding(self):
        """
        GIVEN document_embedding field set to numpy array
        WHEN LLMDocument is instantiated
        THEN expect:
            - Instance created successfully
            - document_embedding field contains numpy array
            - Array shape and dtype preserved
        """
        # Given
        document_embedding = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float32)
        document_data = LLMDocumentTestDataFactory.create_minimal_valid_data()
        document_data["document_embedding"] = document_embedding
        
        # When
        document = LLMDocument(**document_data)
        
        # Then
        assert isinstance(document.document_embedding, np.ndarray)
        assert np.array_equal(document.document_embedding, document_embedding)
        assert document.document_embedding.shape == (5,)
        assert document.document_embedding.dtype == np.float32

    def test_instantiation_with_empty_chunks_list(self):
        """
        GIVEN chunks field as empty list
        WHEN LLMDocument is instantiated
        THEN expect:
            - Instance created successfully
            - chunks field is empty list
            - List type maintained
        """
        # Given
        document_data = LLMDocumentTestDataFactory.create_minimal_valid_data()
        document_data["chunks"] = []
        
        # When
        document = LLMDocument(**document_data)
        
        # Then
        assert isinstance(document.chunks, list)
        assert len(document.chunks) == 0
        assert document.chunks == []

    def test_instantiation_with_populated_chunks(self):
        """
        GIVEN chunks field with list of LLMChunk instances
        WHEN LLMDocument is instantiated
        THEN expect:
            - Instance created successfully
            - chunks field contains provided LLMChunk instances
            - List order preserved
            - All chunk instances accessible
        """
        from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk.llm_chunk_factory import (
            LLMChunkTestDataFactory
        )
        
        # Given
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk content",
                chunk_id="chunk_0001",
                source_page=1
            ),
            LLMChunkTestDataFactory.create_chunk_instance(
                content="Second chunk content",
                chunk_id="chunk_0002",
                source_page=1,
                relationships=["chunk_0001"]
            ),
            LLMChunkTestDataFactory.create_chunk_instance(
                content="Third chunk content",
                chunk_id="chunk_0003",
                source_page=2,
                relationships=["chunk_0002"]
            )
        ]
        
        # When
        document = LLMDocumentTestDataFactory.create_document_instance(
            document_id="doc_001",
            title="Multi-chunk Document",
            chunks=chunks,
            summary="Document with multiple chunks"
        )
        
        # Then
        assert isinstance(document.chunks, list)
        assert len(document.chunks) == 3
        assert document.chunks == chunks
        assert document.chunks[0].chunk_id == "chunk_0001"
        assert document.chunks[1].chunk_id == "chunk_0002"
        assert document.chunks[2].chunk_id == "chunk_0003"
        
        # Verify all chunks are accessible and correct type
        for i, chunk in enumerate(document.chunks):
            assert isinstance(chunk, LLMChunk)
            assert chunk == chunks[i]

    def test_instantiation_with_empty_key_entities(self):
        """
        GIVEN key_entities field as empty list
        WHEN LLMDocument is instantiated
        THEN expect:
            - Instance created successfully
            - key_entities field is empty list
        """
        # Given
        document_data = LLMDocumentTestDataFactory.create_minimal_valid_data()
        document_data["key_entities"] = []
        
        # When
        document = LLMDocument(**document_data)
        
        # Then
        assert isinstance(document.key_entities, list)
        assert len(document.key_entities) == 0
        assert document.key_entities == []

    def test_instantiation_with_populated_key_entities(self):
        """
        GIVEN key_entities field with list of entity dictionaries
        WHEN LLMDocument is instantiated
        THEN expect:
            - Instance created successfully
            - key_entities field contains provided entity data
            - Entity structure preserved
        """
        # Given
        key_entities = [
            {"type": "PERSON", "value": "John Doe", "confidence": 0.95, "start": 0, "end": 8},
            {"type": "ORG", "value": "OpenAI", "confidence": 0.92, "start": 18, "end": 24},
            {"type": "GPE", "value": "San Francisco", "confidence": 0.88, "start": 28, "end": 41}
        ]
        
        # When
        document = LLMDocumentTestDataFactory.create_document_instance(
            document_id="doc_001",
            title="Entity Rich Document",
            summary="Document with multiple entities",
            key_entities=key_entities
        )
        
        # Then
        assert isinstance(document.key_entities, list)
        assert len(document.key_entities) == 3
        assert document.key_entities == key_entities
        
        # Verify entity structure
        assert document.key_entities[0]["type"] == "PERSON"
        assert document.key_entities[0]["value"] == "John Doe"
        assert document.key_entities[1]["type"] == "ORG"
        assert document.key_entities[1]["value"] == "OpenAI"
        assert document.key_entities[2]["type"] == "GPE"
        assert document.key_entities[2]["value"] == "San Francisco"
        
        # Verify all entities have expected keys
        for entity in document.key_entities:
            assert isinstance(entity, dict)
            assert "type" in entity
            assert "value" in entity
            assert "confidence" in entity


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
