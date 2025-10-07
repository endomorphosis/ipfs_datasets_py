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

from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

work_dir = "/home/runner/work/ipfs_datasets_py/ipfs_datasets_py"
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
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk.llm_chunk_factory import (
    LLMChunkTestDataFactory
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
    import asyncio
    import logging
    from typing import Dict, List, Any, Optional
    from dataclasses import dataclass
    import re

    import tiktoken
    from transformers import AutoTokenizer
    import numpy as np
    from sentence_transformers import SentenceTransformer
except ImportError as e:
    raise ImportError(f"Failed to import necessary modules: {e}")


class TestLLMDocumentDataclassMethodsEquality:
    """Test LLMDocument dataclass auto-generated methods."""

    def test_equality_identical_documents(self):
        """
        GIVEN two LLMDocument instances with identical field values
        WHEN compared for equality
        THEN expect instances to be equal
        """

        # Given - create shared metadata to ensure identical timestamps
        shared_metadata = LLMChunkTestDataFactory.create_valid_baseline_data()["metadata"]
        
        # Create identical chunks using the same metadata
        chunk1 = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test chunk content",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10,
            metadata=shared_metadata
        )
        
        chunk2 = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test chunk content",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10,
            metadata=shared_metadata
        )
        
        # Create identical key entities
        entities = [{"type": "PERSON", "value": "John Doe", "confidence": 0.95}]
        
        # Create identical metadata
        metadata = {"processing_time": 1.23, "model": "test_model"}
        
        # Create identical document embedding
        embedding = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        
        # Create two identical documents
        document1 = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[chunk1],
            summary="Test summary",
            key_entities=entities.copy(),
            processing_metadata=metadata.copy(),
            document_embedding=embedding.copy()
        )
        
        document2 = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[chunk2],
            summary="Test summary",
            key_entities=entities.copy(),
            processing_metadata=metadata.copy(),
            document_embedding=embedding.copy()
        )
        
        # When/Then - test equality
        assert document1 == document2, "Identical documents should be equal"

    def test_inequality_identical_documents(self):
        """
        GIVEN two LLMDocument instances with identical field values
        WHEN compared for inequality
        THEN expect instances to not be unequal
        """
        # Given - create shared metadata to ensure identical timestamps
        shared_metadata = LLMChunkTestDataFactory.create_valid_baseline_data()["metadata"]
        
        # Create identical chunks using the same metadata
        chunk1 = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test chunk content",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10,
            metadata=shared_metadata
        )
        
        chunk2 = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test chunk content",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10,
            metadata=shared_metadata
        )
        
        # Create identical key entities
        entities = [{"type": "PERSON", "value": "John Doe", "confidence": 0.95}]
        
        # Create identical metadata
        metadata = {"processing_time": 1.23, "model": "test_model"}
        
        # Create identical document embedding
        embedding = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        
        # Create two identical documents
        document1 = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[chunk1],
            summary="Test summary",
            key_entities=entities.copy(),
            processing_metadata=metadata.copy(),
            document_embedding=embedding.copy()
        )
        
        document2 = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[chunk2],
            summary="Test summary",
            key_entities=entities.copy(),
            processing_metadata=metadata.copy(),
            document_embedding=embedding.copy()
        )
        
        # When/Then - test inequality
        assert not (document1 != document2), "Identical documents should not be unequal"

    def test_equality_reflexivity(self):
        """
        GIVEN an LLMDocument instance
        WHEN compared for equality with itself
        THEN expect it to be equal to itself
        """
        # Given - create metadata
        shared_metadata = LLMChunkTestDataFactory.create_valid_baseline_data()["metadata"]
        
        chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test chunk content",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10,
            metadata=shared_metadata
        )
        
        document = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[chunk],
            summary="Test summary",
            key_entities=[{"type": "PERSON", "value": "John Doe", "confidence": 0.95}],
            processing_metadata={"processing_time": 1.23, "model": "test_model"},
            document_embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32)
        )
        
        # When/Then - test reflexivity
        assert document == document, "Document should equal itself"

    def test_equality_none_embeddings(self):
        """
        GIVEN two LLMDocument instances with identical fields and None embeddings
        WHEN compared for equality
        THEN expect them to be equal
        """
        # Given - create shared metadata to ensure identical timestamps
        shared_metadata = LLMChunkTestDataFactory.create_valid_baseline_data()["metadata"]
        
        # Create identical chunks using the same metadata
        chunk1 = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test chunk content",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10,
            metadata=shared_metadata
        )
        
        chunk2 = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test chunk content",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10,
            metadata=shared_metadata
        )
        
        # Create identical key entities
        entities = [{"type": "PERSON", "value": "John Doe", "confidence": 0.95}]
        
        # Create identical metadata
        metadata = {"processing_time": 1.23, "model": "test_model"}
        
        document3 = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[chunk1],
            summary="Test summary",
            key_entities=entities.copy(),
            processing_metadata=metadata.copy(),
            document_embedding=None
        )
        
        document4 = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[chunk2],
            summary="Test summary",
            key_entities=entities.copy(),
            processing_metadata=metadata.copy(),
            document_embedding=None
        )
        
        # When/Then
        assert document3 == document4, "Documents with None embeddings should be equal"


class TestLLMDocumentDataclassMethodsInequality:


    def test_inequality_different_document_id(self):
        """
        GIVEN two LLMDocument instances with different document_id
        WHEN compared for equality
        THEN expect instances to be unequal
        """
        # Given - create base document
        base_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test chunk content",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        base_document = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[base_chunk],
            summary="Test summary",
            key_entities=[{"type": "PERSON", "value": "John Doe", "confidence": 0.95}],
            processing_metadata={"processing_time": 1.23},
            document_embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32)
        )
        
        # When/Then - test different document_id
        different_id = LLMDocument(
            document_id="doc_002",  # Different ID
            title="Test Document",
            chunks=[base_chunk],
            summary="Test summary",
            key_entities=[{"type": "PERSON", "value": "John Doe", "confidence": 0.95}],
            processing_metadata={"processing_time": 1.23},
            document_embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32)
        )
        assert base_document != different_id, "Documents with different IDs should be unequal"

    def test_inequality_different_title(self):
        """
        GIVEN two LLMDocument instances with different title
        WHEN compared for equality
        THEN expect instances to be unequal
        """
        # Given - create base document
        base_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test chunk content",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        base_document = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[base_chunk],
            summary="Test summary",
            key_entities=[{"type": "PERSON", "value": "John Doe", "confidence": 0.95}],
            processing_metadata={"processing_time": 1.23},
            document_embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32)
        )
        
        # When/Then - test different title
        different_title = LLMDocument(
            document_id="doc_001",
            title="Different Title",  # Different title
            chunks=[base_chunk],
            summary="Test summary",
            key_entities=[{"type": "PERSON", "value": "John Doe", "confidence": 0.95}],
            processing_metadata={"processing_time": 1.23},
            document_embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32)
        )
        assert base_document != different_title, "Documents with different titles should be unequal"

    def test_inequality_different_summary(self):
        """
        GIVEN two LLMDocument instances with different summary
        WHEN compared for equality
        THEN expect instances to be unequal
        """
        # Given - create base document
        base_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test chunk content",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        base_document = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[base_chunk],
            summary="Test summary",
            key_entities=[{"type": "PERSON", "value": "John Doe", "confidence": 0.95}],
            processing_metadata={"processing_time": 1.23},
            document_embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32)
        )
        
        # When/Then - test different summary
        different_summary = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[base_chunk],
            summary="Different summary",  # Different summary
            key_entities=[{"type": "PERSON", "value": "John Doe", "confidence": 0.95}],
            processing_metadata={"processing_time": 1.23},
            document_embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32)
        )
        assert base_document != different_summary, "Documents with different summaries should be unequal"

    def test_inequality_different_entities(self):
        """
        GIVEN two LLMDocument instances with different key_entities
        WHEN compared for equality
        THEN expect instances to be unequal
        """
        # Given - create base document
        base_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test chunk content",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        base_document = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[base_chunk],
            summary="Test summary",
            key_entities=[{"type": "PERSON", "value": "John Doe", "confidence": 0.95}],
            processing_metadata={"processing_time": 1.23},
            document_embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32)
        )
        
        # When/Then - test different entities
        different_entities = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[base_chunk],
            summary="Test summary",
            key_entities=[{"type": "ORG", "value": "OpenAI", "confidence": 0.92}],  # Different entities
            processing_metadata={"processing_time": 1.23},
            document_embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32)
        )
        assert base_document != different_entities, "Documents with different entities should be unequal"

    def test_inequality_different_metadata(self):
        """
        GIVEN two LLMDocument instances with different processing_metadata
        WHEN compared for equality
        THEN expect instances to be unequal
        """
        # Given - create base document
        base_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test chunk content",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        base_document = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[base_chunk],
            summary="Test summary",
            key_entities=[{"type": "PERSON", "value": "John Doe", "confidence": 0.95}],
            processing_metadata={"processing_time": 1.23},
            document_embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32)
        )
        
        # When/Then - test different metadata
        different_metadata = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[base_chunk],
            summary="Test summary",
            key_entities=[{"type": "PERSON", "value": "John Doe", "confidence": 0.95}],
            processing_metadata={"processing_time": 2.45},  # Different metadata
            document_embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32)
        )
        assert base_document != different_metadata, "Documents with different metadata should be unequal"

    def test_inequality_different_embedding(self):
        """
        GIVEN two LLMDocument instances with different document_embedding
        WHEN compared for equality
        THEN expect instances to be unequal
        """
        # Given - create base document
        base_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test chunk content",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        base_document = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[base_chunk],
            summary="Test summary",
            key_entities=[{"type": "PERSON", "value": "John Doe", "confidence": 0.95}],
            processing_metadata={"processing_time": 1.23},
            document_embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32)
        )
        
        # When/Then - test different embedding
        different_embedding = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[base_chunk],
            summary="Test summary",
            key_entities=[{"type": "PERSON", "value": "John Doe", "confidence": 0.95}],
            processing_metadata={"processing_time": 1.23},
            document_embedding=np.array([0.4, 0.5, 0.6], dtype=np.float32)  # Different embedding
        )
        assert base_document != different_embedding, "Documents with different embeddings should be unequal"

    def test_inequality_none_vs_array_embedding(self):
        """
        GIVEN two LLMDocument instances with None vs array document_embedding
        WHEN compared for equality
        THEN expect instances to be unequal
        """
        # Given - create base document
        base_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test chunk content",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        base_document = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[base_chunk],
            summary="Test summary",
            key_entities=[{"type": "PERSON", "value": "John Doe", "confidence": 0.95}],
            processing_metadata={"processing_time": 1.23},
            document_embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32)
        )
        
        # When/Then - test None vs array embedding
        none_embedding = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[base_chunk],
            summary="Test summary",
            key_entities=[{"type": "PERSON", "value": "John Doe", "confidence": 0.95}],
            processing_metadata={"processing_time": 1.23},
            document_embedding=None  # None vs array
        )
        assert base_document != none_embedding, "Documents with None vs array embedding should be unequal"


class TestLLMDocumentDataclassMethodsString:

    def test_string_representation_returns_string(self):
        """
        GIVEN LLMDocument instance
        WHEN converted to string representation
        THEN expect string type is returned
        """
        # Given
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk content",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=10
            )
        ]
        
        document = LLMDocument(
            document_id="doc_001",
            title="Advanced Document Processing Analysis",
            chunks=chunks,
            summary="This document analyzes advanced techniques for document processing and optimization.",
            key_entities=[
                {"type": "PERSON", "value": "John Doe", "confidence": 0.95}
            ],
            processing_metadata={
                "processing_time": 2.45,
                "model": "advanced_optimizer_v2",
                "chunk_count": 1
            },
            document_embedding=np.array([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32)
        )
        
        # When
        str_repr = str(document)
        
        # Then
        assert isinstance(str_repr, str), "String representation should be string type"

    def test_string_representation_not_empty(self):
        """
        GIVEN LLMDocument instance
        WHEN converted to string representation
        THEN expect non-empty string
        """
        # Given
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk content",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=10
            )
        ]
        
        document = LLMDocument(
            document_id="doc_001",
            title="Advanced Document Processing Analysis",
            chunks=chunks,
            summary="This document analyzes advanced techniques for document processing and optimization.",
            key_entities=[],
            processing_metadata={},
            document_embedding=None
        )
        
        # When
        str_repr = str(document)
        
        # Then
        assert len(str_repr) > 0, "String representation should not be empty"

    def test_string_representation_contains_document_id(self):
        """
        GIVEN LLMDocument instance
        WHEN converted to string representation
        THEN expect document ID to be included
        """
        # Given
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk content",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=10
            )
        ]
        
        document = LLMDocument(
            document_id="doc_001",
            title="Advanced Document Processing Analysis",
            chunks=chunks,
            summary="This document analyzes advanced techniques.",
            key_entities=[],
            processing_metadata={},
            document_embedding=None
        )
        
        # When
        str_repr = str(document)
        
        # Then
        assert "doc_001" in str_repr, "Document ID should be in string representation"

    def test_string_representation_contains_title(self):
        """
        GIVEN LLMDocument instance
        WHEN converted to string representation
        THEN expect title to be included
        """
        # Given
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk content",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=10
            )
        ]
        
        document = LLMDocument(
            document_id="doc_001",
            title="Advanced Document Processing Analysis",
            chunks=chunks,
            summary="This document analyzes advanced techniques.",
            key_entities=[],
            processing_metadata={},
            document_embedding=None
        )
        
        # When
        str_repr = str(document)
        
        # Then
        assert "Advanced Document Processing Analysis" in str_repr, "Title should be in string representation"

    def test_string_representation_contains_chunk_count(self):
        """
        GIVEN LLMDocument instance with multiple chunks
        WHEN converted to string representation
        THEN expect chunk count to be represented
        """
        # Given
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk content",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=10
            ),
            LLMChunkTestDataFactory.create_chunk_instance(
                content="Second chunk content",
                chunk_id="chunk_0002",
                source_page=1,
                token_count=12
            )
        ]
        
        document = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=chunks,
            summary="Test summary",
            key_entities=[],
            processing_metadata={},
            document_embedding=None
        )
        
        # When
        str_repr = str(document)
        
        # Then
        assert "2" in str_repr, "Chunk count should be represented"

    def test_string_representation_is_concise(self):
        """
        GIVEN LLMDocument instance
        WHEN converted to string representation
        THEN expect readable and concise format
        """
        # Given
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk content",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=10
            )
        ]
        
        document = LLMDocument(
            document_id="doc_001",
            title="Advanced Document Processing Analysis",
            chunks=chunks,
            summary="This document analyzes advanced techniques for document processing and optimization.",
            key_entities=[
                {"type": "PERSON", "value": "John Doe", "confidence": 0.95},
                {"type": "ORG", "value": "OpenAI", "confidence": 0.92}
            ],
            processing_metadata={
                "processing_time": 2.45,
                "model": "advanced_optimizer_v2",
                "chunk_count": 1
            },
            document_embedding=np.array([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32)
        )
        
        # When
        str_repr = str(document)
        
        # Then
        assert len(str_repr) < 500, "String representation should be concise and readable"

    def test_string_representation_with_none_embedding(self):
        """
        GIVEN LLMDocument instance with None embedding
        WHEN converted to string representation
        THEN expect string type is returned
        """
        # Given
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk content",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=10
            )
        ]
        
        document = LLMDocument(
            document_id="doc_002",
            title="Test Document",
            chunks=chunks,
            summary="Test summary",
            key_entities=[],
            processing_metadata={},
            document_embedding=None
        )
        
        # When
        str_repr = str(document)
        
        # Then
        assert isinstance(str_repr, str), "String representation with None embedding should be string"

    def test_string_representation_with_none_embedding_contains_id(self):
        """
        GIVEN LLMDocument instance with None embedding
        WHEN converted to string representation
        THEN expect document ID to be present
        """
        # Given
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk content",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=10
            )
        ]
        
        document = LLMDocument(
            document_id="doc_002",
            title="Test Document",
            chunks=chunks,
            summary="Test summary",
            key_entities=[],
            processing_metadata={},
            document_embedding=None
        )
        
        # When
        str_repr = str(document)
        
        # Then
        assert "doc_002" in str_repr, "Document ID should be present even with None embedding"

    def test_string_representation_empty_chunks_returns_string(self):
        """
        GIVEN LLMDocument instance with empty chunks
        WHEN converted to string representation
        THEN expect string type is returned
        """
        # Given
        document = LLMDocument(
            document_id="doc_003",
            title="Empty Document",
            chunks=[],
            summary="Empty document",
            key_entities=[],
            processing_metadata={},
            document_embedding=None
        )
        
        # When
        str_repr = str(document)
        
        # Then
        assert isinstance(str_repr, str), "String representation of empty document should be string"

    def test_string_representation_empty_chunks_contains_id(self):
        """
        GIVEN LLMDocument instance with empty chunks
        WHEN converted to string representation
        THEN expect document ID to be present
        """
        # Given
        document = LLMDocument(
            document_id="doc_003",
            title="Empty Document",
            chunks=[],
            summary="Empty document",
            key_entities=[],
            processing_metadata={},
            document_embedding=None
        )
        
        # When
        str_repr = str(document)
        
        # Then
        assert "doc_003" in str_repr, "Document ID should be present even in empty document"

    def test_string_representation_empty_chunks_shows_zero_count(self):
        """
        GIVEN LLMDocument instance with empty chunks
        WHEN converted to string representation
        THEN expect zero chunk count to be represented
        """
        # Given
        document = LLMDocument(
            document_id="doc_003",
            title="Empty Document",
            chunks=[],
            summary="Empty document",
            key_entities=[],
            processing_metadata={},
            document_embedding=None
        )
        
        # When
        str_repr = str(document)
        
        # Then
        assert "0" in str_repr, "Zero chunk count should be represented"


class TestLLMDocumentDataclassMethodsRepr:

    def test_repr_returns_string(self):
        """
        GIVEN LLMDocument instance
        WHEN repr() is called
        THEN expect string type is returned
        """
        # Given
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk content for testing repr",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=15
            )
        ]
        
        document = LLMDocument(
            document_id="doc_debug_001",
            title="Debug Document for Repr Testing",
            chunks=chunks,
            summary="Comprehensive summary for debugging representation functionality.",
            key_entities=[
                {"type": "PERSON", "value": "Alice Smith", "confidence": 0.95}
            ],
            processing_metadata={
                "processing_time": 3.67,
                "model": "debug_optimizer_v1"
            },
            document_embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32)
        )
        
        # When
        repr_str = repr(document)
        
        # Then
        assert isinstance(repr_str, str), "Repr should return string"

    def test_repr_not_empty(self):
        """
        GIVEN LLMDocument instance
        WHEN repr() is called
        THEN expect non-empty string
        """
        # Given
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk content",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=15
            )
        ]
        
        document = LLMDocument(
            document_id="doc_debug_001",
            title="Debug Document",
            chunks=chunks,
            summary="Test summary",
            key_entities=[],
            processing_metadata={},
            document_embedding=None
        )
        
        # When
        repr_str = repr(document)
        
        # Then
        assert len(repr_str) > 0, "Repr should not be empty"

    def test_repr_contains_class_or_id_identifier(self):
        """
        GIVEN LLMDocument instance
        WHEN repr() is called
        THEN expect class name or document ID to be present
        """
        # Given
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk content",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=15
            )
        ]
        
        document = LLMDocument(
            document_id="doc_debug_001",
            title="Debug Document",
            chunks=chunks,
            summary="Test summary",
            key_entities=[],
            processing_metadata={},
            document_embedding=None
        )
        
        # When
        repr_str = repr(document)
        
        # Then
        assert "LLMDocument" in repr_str or "doc_debug_001" in repr_str, "Repr should identify the class or instance"

    def test_repr_contains_key_elements(self):
        """
        GIVEN LLMDocument instance
        WHEN repr() is called
        THEN expect at least 2 key identifying elements
        """
        # Given
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk content",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=15
            )
        ]
        
        document = LLMDocument(
            document_id="doc_debug_001",
            title="Debug Document for Repr Testing",
            chunks=chunks,
            summary="Test summary",
            key_entities=[
                {"type": "PERSON", "value": "Alice Smith", "confidence": 0.95}
            ],
            processing_metadata={},
            document_embedding=None
        )
        
        # When
        repr_str = repr(document)
        
        # Then
        key_elements = ["doc_debug_001", "Debug Document", "chunks", "entities"]
        present_elements = sum(1 for element in key_elements if element in repr_str)
        assert present_elements >= 2, f"Repr should contain at least 2 key elements, found {present_elements}"

    def test_repr_more_detailed_than_str(self):
        """
        GIVEN LLMDocument instance
        WHEN repr() is called
        THEN expect repr to be at least as detailed as str()
        """
        # Given
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk content",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=15
            )
        ]
        
        document = LLMDocument(
            document_id="doc_debug_001",
            title="Debug Document",
            chunks=chunks,
            summary="Test summary",
            key_entities=[],
            processing_metadata={},
            document_embedding=None
        )

        # When
        len_repr = len(repr(document))
        len_str = len(str(document))

        # Then
        assert len_repr >= len_str, f"Repr '{len_repr}' should be at least as detailed as str '{len_str}'"

    def test_repr_not_excessively_verbose(self):
        """
        GIVEN LLMDocument instance
        WHEN repr() is called
        THEN expect repr to not be excessively long
        """
        # Given
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk content for testing repr",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=15
            ),
            LLMChunkTestDataFactory.create_chunk_instance(
                content="Second chunk with relationships",
                chunk_id="chunk_0002",
                source_page=2,
                token_count=20
            )
        ]
        
        document = LLMDocument(
            document_id="doc_debug_001",
            title="Debug Document for Repr Testing",
            chunks=chunks,
            summary="Comprehensive summary for debugging representation functionality.",
            key_entities=[
                {"type": "PERSON", "value": "Alice Smith", "confidence": 0.95},
                {"type": "ORG", "value": "TechCorp", "confidence": 0.88},
                {"type": "GPE", "value": "New York", "confidence": 0.92}
            ],
            processing_metadata={
                "processing_time": 3.67,
                "model": "debug_optimizer_v1",
                "version": "1.0.0",
                "chunk_count": 2,
                "entity_count": 3,
                "total_tokens": 35
            },
            document_embedding=np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], dtype=np.float32)
        )
        MAX_LENGTH = 2000

        # When
        repr_str = repr(document)
        
        # Then
        assert len(repr_str) < MAX_LENGTH, f"Repr must be less than {MAX_LENGTH} characters long, got {len(repr_str)}"

    def test_repr_with_none_embedding_returns_string(self):
        """
        GIVEN LLMDocument instance with None embedding
        WHEN repr() is called
        THEN expect string type is returned
        """
        # Given
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk content",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=15
            )
        ]
        
        document = LLMDocument(
            document_id="doc_none_001",
            title="None Embedding Document",
            chunks=chunks,
            summary="Document with None embedding",
            key_entities=[],
            processing_metadata={},
            document_embedding=None
        )
        
        # When
        repr_str = repr(document)
        
        # Then
        assert isinstance(repr_str, str), "Repr with None embedding should be string"

    def test_repr_with_none_embedding_contains_identifier(self):
        """
        GIVEN LLMDocument instance with None embedding
        WHEN repr() is called
        THEN expect identifying information to be present
        """
        # Given
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk content",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=15
            )
        ]
        
        document = LLMDocument(
            document_id="doc_none_001",
            title="None Embedding Document",
            chunks=chunks,
            summary="Document with None embedding",
            key_entities=[],
            processing_metadata={},
            document_embedding=None
        )
        
        # When
        repr_str = repr(document)
        
        # Then
        assert "doc_none_001" in repr_str or "None Embedding Document" in repr_str, "Repr should contain identifying information"

    def test_repr_minimal_document_returns_string(self):
        """
        GIVEN minimal LLMDocument instance
        WHEN repr() is called
        THEN expect string type is returned
        """
        # Given
        document = LLMDocument(
            document_id="minimal",
            title="Minimal",
            chunks=[],
            summary="",
            key_entities=[],
            processing_metadata={},
            document_embedding=None
        )
        
        # When
        repr_str = repr(document)
        
        # Then
        assert isinstance(repr_str, str), "Repr of minimal document should be string"

    def test_repr_minimal_document_contains_identifier(self):
        """
        GIVEN minimal LLMDocument instance
        WHEN repr() is called
        THEN expect basic identifying information to be present
        """
        # Given
        document = LLMDocument(
            document_id="minimal",
            title="Minimal",
            chunks=[],
            summary="",
            key_entities=[],
            processing_metadata={},
            document_embedding=None
        )
        
        # When
        repr_str = repr(document)
        
        # Then
        assert "minimal" in repr_str or "Minimal" in repr_str, "Repr should contain basic identifying information"

    def test_repr_minimal_document_has_substance(self):
        """
        GIVEN minimal LLMDocument instance
        WHEN repr() is called
        THEN expect repr to have some substance
        """
        # Given
        document = LLMDocument(
            document_id="minimal",
            title="Minimal",
            chunks=[],
            summary="",
            key_entities=[],
            processing_metadata={},
            document_embedding=None
        )
        
        # When
        repr_str = repr(document)
        
        # Then
        assert len(repr_str) > 10, "Even minimal repr should have some substance"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
