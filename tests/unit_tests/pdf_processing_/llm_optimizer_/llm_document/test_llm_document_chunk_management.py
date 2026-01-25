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
    import anyio
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


class TestLLMDocumentChunkManagement:
    """Test LLMDocument chunk collection management and operations."""

    def test_chunks_list_modification(self):
        """
        GIVEN LLMDocument instance with chunks list
        WHEN chunks list is modified (append, remove, etc.)
        THEN expect:
            - Modifications reflected in instance
            - List mutability works as expected
            - No corruption of existing chunks
        """
        # Given
        initial_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Initial chunk content",
            chunk_id="chunk_0001",
            source_page=1
        )
        
        document = LLMDocumentTestDataFactory.create_document_instance(
            document_id="doc_001",
            title="Modifiable Document",
            chunks=[initial_chunk],
            summary="Document for testing modifications"
        )
        
        # When - append new chunk
        new_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="New chunk content",
            chunk_id="chunk_0002",
            source_page=1,
            relationships=["chunk_0001"]
        )
        
        document.chunks.append(new_chunk)
        
        # Then - modifications should be reflected
        assert len(document.chunks) == 2
        assert document.chunks[0] == initial_chunk
        assert document.chunks[1] == new_chunk
        
        # When - remove chunk
        document.chunks.remove(initial_chunk)
        
        # Then - chunk should be removed
        assert len(document.chunks) == 1
        assert document.chunks[0] == new_chunk
        assert initial_chunk not in document.chunks

    def test_chunk_access_by_index(self):
        """
        GIVEN LLMDocument instance with multiple chunks
        WHEN accessing chunks by index
        THEN expect:
            - Correct chunk returned for each index
            - IndexError for invalid indices
            - Consistent ordering maintained
        """
        # Given
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk",
                chunk_id="chunk_0001",
                source_page=1
            ),
            LLMChunkTestDataFactory.create_chunk_instance(
                content="Second chunk",
                chunk_id="chunk_0002",
                source_page=1,
                relationships=["chunk_0001"]
            ),
            LLMChunkTestDataFactory.create_chunk_instance(
                content="Third chunk",
                chunk_id="chunk_0003",
                source_page=2,
                relationships=["chunk_0002"]
            )
        ]
        
        document = LLMDocumentTestDataFactory.create_document_instance(
            document_id="doc_001",
            title="Multi-chunk Document",
            chunks=chunks,
            summary="Document with multiple chunks for indexing"
        )
        
        # When/Then - valid indices
        assert document.chunks[0] == chunks[0]
        assert document.chunks[1] == chunks[1]
        assert document.chunks[2] == chunks[2]
        assert document.chunks[-1] == chunks[2]  # Negative indexing
        assert document.chunks[-2] == chunks[1]
        
        # When/Then - invalid indices should raise IndexError
        with pytest.raises(IndexError):
            _ = document.chunks[3]
        
        with pytest.raises(IndexError):
            _ = document.chunks[-4]

    def test_chunk_iteration(self):
        """
        GIVEN LLMDocument instance with chunks
        WHEN iterating over chunks
        THEN expect:
            - All chunks accessible via iteration
            - Iteration order matches list order
            - No chunks skipped or duplicated
        """
        # Given
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content=f"Chunk {i} content",
                chunk_id=f"chunk_{i:04d}",
                source_page=1
            )
            for i in range(1, 6)  # Create 5 chunks
        ]
        
        document = LLMDocumentTestDataFactory.create_document_instance(
            document_id="doc_001",
            title="Iteration Test Document",
            chunks=chunks,
            summary="Document for testing chunk iteration"
        )
        
        # When - iterate over chunks
        iterated_chunks = []
        for chunk in document.chunks:
            iterated_chunks.append(chunk)
        
        # Then - all chunks should be accessible in correct order
        assert len(iterated_chunks) == 5
        assert iterated_chunks == chunks
        
        # Verify order is preserved
        for i, chunk in enumerate(document.chunks):
            assert chunk.chunk_id == f"chunk_{i+1:04d}"
            assert chunk.content == f"Chunk {i+1} content"
        
        # Test list comprehension iteration
        chunk_ids = [chunk.chunk_id for chunk in document.chunks]
        expected_ids = [f"chunk_{i:04d}" for i in range(1, 6)]
        assert chunk_ids == expected_ids

    def test_chunk_count_property(self):
        """
        GIVEN LLMDocument instance with chunks
        WHEN getting chunk count
        THEN expect:
            - Correct count returned via len(chunks)
            - Count updates when chunks modified
        """
        # Given - document with initial chunks
        initial_chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk",
                chunk_id="chunk_0001",
                source_page=1
            ),
            LLMChunkTestDataFactory.create_chunk_instance(
                content="Second chunk",
                chunk_id="chunk_0002",
                source_page=1,
                relationships=["chunk_0001"]
            )
        ]
        
        document = LLMDocumentTestDataFactory.create_document_instance(
            document_id="doc_001",
            title="Count Test Document",
            chunks=initial_chunks,
            summary="Document for testing chunk counting"
        )
        
        # When/Then - initial count
        assert len(document.chunks) == 2
        
        # When - add chunk
        new_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Third chunk",
            chunk_id="chunk_0003",
            source_page=2,
            relationships=["chunk_0002"]
        )
        document.chunks.append(new_chunk)
        
        # Then - count should update
        assert len(document.chunks) == 3
        
        # When - remove chunk
        document.chunks.pop()
        
        # Then - count should decrease
        assert len(document.chunks) == 2
        
        # When - clear all chunks
        document.chunks.clear()
        
        # Then - count should be zero
        assert len(document.chunks) == 0

    def test_chunk_relationship_integrity(self):
        """
        GIVEN LLMDocument instance with chunks containing relationships
        WHEN accessing chunk relationships
        THEN expect:
            - All relationship references valid
            - Bidirectional relationships consistent
            - No broken or invalid chunk ID references
        """
        # Given - chunks with relationships
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk content",
                chunk_id="chunk_0001",
                source_page=1,
                relationships=[]  # No predecessors
            ),
            LLMChunkTestDataFactory.create_chunk_instance(
                content="Second chunk content",
                chunk_id="chunk_0002",
                source_page=1,
                relationships=["chunk_0001"]  # References first chunk
            ),
            LLMChunkTestDataFactory.create_chunk_instance(
                content="Third chunk content",
                chunk_id="chunk_0003",
                source_page=2,
                relationships=["chunk_0001", "chunk_0002"]  # References both previous
            )
        ]
        
        document = LLMDocumentTestDataFactory.create_document_instance(
            document_id="doc_001",
            title="Relationship Test Document",
            chunks=chunks,
            summary="Document for testing chunk relationships"
        )
        
        # When/Then - verify relationships exist and are valid
        chunk_ids = {chunk.chunk_id for chunk in document.chunks}
        
        for chunk in document.chunks:
            # All relationship references should point to existing chunks
            for related_id in chunk.relationships:
                assert related_id in chunk_ids, f"Chunk {chunk.chunk_id} references non-existent chunk {related_id}"
        
        # Verify specific relationships
        assert document.chunks[0].relationships == []
        assert document.chunks[1].relationships == ["chunk_0001"]
        assert set(document.chunks[2].relationships) == {"chunk_0001", "chunk_0002"}
        
        # Verify no self-references
        for chunk in document.chunks:
            assert chunk.chunk_id not in chunk.relationships, f"Chunk {chunk.chunk_id} contains self-reference"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
