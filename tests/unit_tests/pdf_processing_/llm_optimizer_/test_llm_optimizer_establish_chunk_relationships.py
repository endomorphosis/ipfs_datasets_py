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
from unittest.mock import MagicMock

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
    LLMDocument,
    LLMChunkMetadata
)
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_factory import (
    LLMChunkMetadataTestDataFactory as MetadataFactory
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

def _make_mock_metadata():
    data = MetadataFactory.create_valid_baseline_data()
    return LLMChunkMetadata(**data)

class TestLLMOptimizerEstablishChunkRelationshipsSequentialChunks:
    """Test LLMOptimizer._establish_chunk_relationships method."""

    def setup_method(self):
        """Setup method to initialize common variables."""
        self.optimizer = LLMOptimizer(
            sentence_transformer=MagicMock()
        )
        self.sample_metadata = _make_mock_metadata()
        self.sequential_chunks = [
            LLMChunk(
                content="First chunk in sequence",
                chunk_id="chunk_0001",
                source_page=1,
                source_elements=["paragraph"],
                token_count=10,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata
            ),
            LLMChunk(
                content="Second chunk follows first",
                chunk_id="chunk_0002",
                source_page=1,
                source_elements=["paragraph"],
                token_count=12,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata
            ),
            LLMChunk(
                content="Third chunk completes sequence",
                chunk_id="chunk_0003",
                source_page=1,
                source_elements=["paragraph"],
                token_count=14,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata
            )
        ]

    def test_establish_chunk_relationships_first_chunk_relationships(self):
        """
        GIVEN list of sequential chunks on same page
        WHEN _establish_chunk_relationships is called
        THEN first chunk should have successor and same-page relationships
        """
        # When
        self.optimizer._establish_chunk_relationships(self.sequential_chunks)
        
        # Then
        expected_relationships = {'chunk_0002', 'chunk_0003'}  # successor + same-page chunks
        actual_relationships = set(self.sequential_chunks[0].relationships)
        assert actual_relationships == expected_relationships, \
            f"First chunk should have successor and same-page relationships, got {self.sequential_chunks[0].relationships}"

    def test_establish_chunk_relationships_second_chunk_references_first(self):
        """
        GIVEN list of sequential chunks
        WHEN _establish_chunk_relationships is called
        THEN second chunk should reference first chunk
        """
        # When
        self.optimizer._establish_chunk_relationships(self.sequential_chunks)
        
        # Then
        assert "chunk_0001" in self.sequential_chunks[1].relationships, \
            "Second chunk should reference first"

    def test_establish_chunk_relationships_third_chunk_references_second(self):
        """
        GIVEN list of sequential chunks
        WHEN _establish_chunk_relationships is called
        THEN third chunk should reference second chunk
        """
        # When
        self.optimizer._establish_chunk_relationships(self.sequential_chunks)
        
        # Then
        assert "chunk_0002" in self.sequential_chunks[2].relationships, \
            "Third chunk should reference second"

    def test_establish_chunk_relationships_each_chunk_references_previous(self):
        """
        GIVEN list of sequential chunks
        WHEN _establish_chunk_relationships is called
        THEN each chunk should reference its immediate predecessor
        """
        # When
        self.optimizer._establish_chunk_relationships(self.sequential_chunks)
        
        # Then
        for i in range(1, len(self.sequential_chunks)):
            current_chunk = self.sequential_chunks[i]
            previous_chunk_id = self.sequential_chunks[i-1].chunk_id
            assert previous_chunk_id in current_chunk.relationships, \
                f"Chunk {current_chunk.chunk_id} should reference {previous_chunk_id}"

class TestLLMOptimizerEstablishChunkRelationshipsSamePage:

    def setup_method(self):
        """Setup method to initialize common variables."""
        self.optimizer = LLMOptimizer(
            sentence_transformer=MagicMock()
        )
        self.sample_metadata = _make_mock_metadata()
        self.same_page_chunks = [
            LLMChunk(
                content="First paragraph on page 1",
                chunk_id="chunk_0001",
                source_page=1,
                source_elements=["paragraph"],
                token_count=10,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata
            ),
            LLMChunk(
                content="Second paragraph on page 1",
                chunk_id="chunk_0002",
                source_page=1,
                source_elements=["paragraph"],
                token_count=12,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata
            ),
            LLMChunk(
                content="Table on page 1",
                chunk_id="chunk_0003",
                source_page=1,
                source_elements=["table"],
                token_count=15,
                semantic_types="table",
                relationships=[],
                metadata=self.sample_metadata
            ),
            LLMChunk(
                content="First paragraph on page 2",
                chunk_id="chunk_0004",
                source_page=2,
                source_elements=["paragraph"],
                token_count=11,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata
            )
        ]

    def test_establish_chunk_relationships_same_page_sequential_links(self):
        """
        GIVEN chunks from the same page
        WHEN _establish_chunk_relationships is called
        THEN second chunk should reference first chunk on same page
        """
        # When
        self.optimizer._establish_chunk_relationships(self.same_page_chunks)
        
        # Then
        assert "chunk_0001" in self.same_page_chunks[1].relationships, \
            "Second chunk should reference first chunk (same page)"

    def test_establish_chunk_relationships_same_page_table_links(self):
        """
        GIVEN chunks from the same page including a table
        WHEN _establish_chunk_relationships is called
        THEN table chunk should reference previous paragraph on same page
        """
        # When
        self.optimizer._establish_chunk_relationships(self.same_page_chunks)
        
        # Then
        assert "chunk_0002" in self.same_page_chunks[2].relationships, \
            "Table chunk should reference previous paragraph (same page)"

    def test_establish_chunk_relationships_cross_page_chunk_has_relationships(self):
        """
        GIVEN chunks spanning multiple pages
        WHEN _establish_chunk_relationships is called
        THEN page 2 chunk should have some relationships for document continuity
        """
        # When
        self.optimizer._establish_chunk_relationships(self.same_page_chunks)
        
        # Then
        page_2_chunk = self.same_page_chunks[3]
        assert len(page_2_chunk.relationships) > 0, \
            "Page 2 chunk should have some relationships for document continuity"

    def test_establish_chunk_relationships_same_page_chunks_reference_previous(self):
        """
        GIVEN chunks from the same page
        WHEN _establish_chunk_relationships is called
        THEN each same-page chunk should reference its immediate predecessor
        """
        # When
        self.optimizer._establish_chunk_relationships(self.same_page_chunks)
        
        # Then
        page_1_chunks = [chunk for chunk in self.same_page_chunks if chunk.source_page == 1]
        
        for i in range(len(page_1_chunks) - 1):
            current_chunk = page_1_chunks[i + 1]
            previous_chunk_id = page_1_chunks[i].chunk_id
            assert previous_chunk_id in current_chunk.relationships, \
                f"Same-page chunk {current_chunk.chunk_id} should reference {previous_chunk_id}"


class TestLLMOptimizerEstablishChunkRelationshipsSingleChunk:

    def setup_method(self):
        """Setup method to initialize common variables."""
        self.optimizer = LLMOptimizer(
            sentence_transformer=MagicMock()
        )
        self.sample_metadata = _make_mock_metadata()
        self.single_chunk = [
            LLMChunk(
                content="Single lonely chunk",
                chunk_id="chunk_0001",
                source_page=1,
                source_elements=["paragraph"],
                token_count=10,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata
            )
        ]

    def test_establish_chunk_relationships_single_chunk_maintains_count(self):
        """
        GIVEN single chunk in list
        WHEN _establish_chunk_relationships is called
        THEN should still have one chunk
        """
        # When
        self.optimizer._establish_chunk_relationships(self.single_chunk)
        
        # Then
        assert len(self.single_chunk) == 1, "Should still have one chunk"

    def test_establish_chunk_relationships_single_chunk_empty_relationships(self):
        """
        GIVEN single chunk in list
        WHEN _establish_chunk_relationships is called
        THEN single chunk should have empty relationships
        """
        # When
        self.optimizer._establish_chunk_relationships(self.single_chunk)
        
        # Then
        assert self.single_chunk[0].relationships == [], "Single chunk should have empty relationships"

    def test_establish_chunk_relationships_single_chunk_preserves_id(self):
        """
        GIVEN single chunk in list
        WHEN _establish_chunk_relationships is called
        THEN chunk ID should be preserved
        """
        # When
        self.optimizer._establish_chunk_relationships(self.single_chunk)
        
        # Then
        assert self.single_chunk[0].chunk_id == "chunk_0001", "Chunk ID should be preserved"

    def test_establish_chunk_relationships_single_chunk_preserves_content(self):
        """
        GIVEN single chunk in list
        WHEN _establish_chunk_relationships is called
        THEN chunk content should be preserved
        """
        # When
        self.optimizer._establish_chunk_relationships(self.single_chunk)
        
        # Then
        assert self.single_chunk[0].content == "Single lonely chunk", "Chunk content should be preserved"


class TestLLMOptimizerEstablishChunkRelationshipsPerformanceLimits:

    def setup_method(self):
        """Setup method to initialize common variables."""
        self.optimizer = LLMOptimizer(
            sentence_transformer=MagicMock()
        )
        self.sample_metadata = _make_mock_metadata()
        num_chunks = 100
        self.large_chunk_list = []
        for i in range(num_chunks):
            chunk = LLMChunk(
                content=f"Chunk {i+1} content for performance testing",
                chunk_id=f"chunk_{i+1:04d}",
                source_page=(i // 10) + 1,  # 10 chunks per page
                source_elements=["paragraph"],
                token_count=15,
                semantic_types="text",
                relationships=[],
                metadata=self.sample_metadata
            )
            self.large_chunk_list.append(chunk)

    def test_establish_chunk_relationships_performance_time_limit(self):
        """
        GIVEN large number of chunks
        WHEN _establish_chunk_relationships is called
        THEN processing should complete within 5 seconds
        """
        # When - measure performance
        start_time = time.time()
        self.optimizer._establish_chunk_relationships(self.large_chunk_list)
        processing_time = time.time() - start_time
        
        # Then - verify performance
        expected_time = 5.0  # seconds
        assert processing_time < expected_time, \
            f"Processing 100 chunks took too long: {processing_time:.2f}s, expected < {expected_time}s"

    def test_establish_chunk_relationships_performance_minimum_relationships(self):
        """
        GIVEN large number of chunks (100)
        WHEN _establish_chunk_relationships is called
        THEN most chunks should have at least one 90 relationships established
        """
        # When
        self.optimizer._establish_chunk_relationships(self.large_chunk_list)
        
        # Then - verify some relationships are established
        chunks_with_relationships = [chunk for chunk in self.large_chunk_list if chunk.relationships]
        min_relationships = 90
        assert len(chunks_with_relationships) >= min_relationships, \
            f"At least {min_relationships} chunks should have relationships established, got {len(chunks_with_relationships)}"

    def test_establish_chunk_relationships_performance_sequential_relationships(self):
        """
        GIVEN large number of chunks (100)
        WHEN _establish_chunk_relationships is called
        THEN sequential relationships should exist for ALL chunks
        """
        # When
        self.optimizer._establish_chunk_relationships(self.large_chunk_list)
        
        # Then - verify sequential relationships exist for ALL chunks
        for i in range(1, len(self.large_chunk_list)):
            current_chunk = self.large_chunk_list[i]
            previous_chunk_id = self.large_chunk_list[i-1].chunk_id
            assert previous_chunk_id in current_chunk.relationships, \
            f"Sequential relationship missing for chunk {i+1}"

    def test_establish_chunk_relationships_performance_relationship_limits(self):
        """
        GIVEN large number of chunks
        WHEN _establish_chunk_relationships is called
        THEN relationship limits should be applied to prevent excessive connections
        """
        limit = 10
        # When
        self.optimizer._establish_chunk_relationships(self.large_chunk_list)
        
        # Then - verify relationship limits (no chunk should have excessive relationships)
        max_relationships = max(len(chunk.relationships) for chunk in self.large_chunk_list)
        assert max_relationships <= limit, \
            f"Should have at most {limit} relationships, found chunk with {max_relationships} relationships."


class TestLLMOptimizerEstablishChunkRelationshipsMalformedChunks:

    def setup_method(self):
        """Setup method to initialize common variables."""
        self.optimizer = LLMOptimizer(
            sentence_transformer=MagicMock()
        )
        self.sample_metadata = _make_mock_metadata()
        self.valid_chunk = LLMChunk(
            content="Valid chunk content",
            chunk_id="chunk_0001",
            source_page=1,
            source_elements=["paragraph"],
            token_count=10,
            semantic_types="text",
            relationships=[],
            metadata=self.sample_metadata
        )
        self.malformed_chunk_no_id = LLMChunk(
            content="Chunk without ID",
            chunk_id="",  # Empty ID should cause issues
            source_page=1,
            source_elements=["paragraph"],
            token_count=10,
            semantic_types="text",
            relationships=[],
            metadata=self.sample_metadata
        )

    def test_establish_chunk_relationships_malformed_chunks(self):
        """
        GIVEN chunks with missing required attributes
        WHEN _establish_chunk_relationships is called
        THEN expect:
            - AttributeError raised
            - Error handling for malformed data
        """
        # When/Then - test with malformed chunk
        malformed_chunks = [self.valid_chunk, self.malformed_chunk_no_id]

        with pytest.raises(AttributeError):
            # Attempt to establish relationships with malformed chunk
            self.optimizer._establish_chunk_relationships(malformed_chunks)

    def test_establish_chunk_relationships_malformed_chunks(self):
        """
        GIVEN chunks with invalid types
        WHEN _establish_chunk_relationships is called
        THEN expect:
            - TypeError raised
        """
        # Test with None in chunk list
        chunks_with_none = [self.valid_chunk, None]
        
        with pytest.raises(TypeError):
            self.optimizer._establish_chunk_relationships(chunks_with_none)

    def test_establish_chunk_relationships_empty_list(self):
        """
        GIVEN empty chunks list
        WHEN _establish_chunk_relationships is called
        THEN expect empty list returned
            - No processing errors
        """
        # Given
        empty_chunks = []
        self.optimizer._establish_chunk_relationships(empty_chunks)
        assert len(empty_chunks) == 0, f"Empty list should remain empty, got {empty_chunks}"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
