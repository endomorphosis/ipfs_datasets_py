#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer.py
# Auto-generated on 2025-07-07 02:28:56"

from datetime import datetime
import pytest
import os
from unittest.mock import Mock, patch, MagicMock

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

home_dir = os.path.expanduser('~')
file_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer.py")
md_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer_stubs.md")

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

from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk.llm_chunk_factory import (
    LLMChunkTestDataFactory as ChunkFactory
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

def _make_mock_chunks():
    # Create mock chunks for testing using factory
    return [
        ChunkFactory.create_chunk_instance(
            content="This is the first chunk of text for testing embeddings.",
            chunk_id="chunk_0000",
            source_page=1,
            source_elements=["paragraph"],
            token_count=12,
        ),
        ChunkFactory.create_chunk_instance(
            content="This is the second chunk with different content for embedding generation.",
            chunk_id="chunk_0001", 
            source_page=1,
            source_elements=["paragraph"],
        ),
        ChunkFactory.create_chunk_instance(
            content="Final chunk for comprehensive embedding testing scenarios.",
            chunk_id="chunk_0002",
            source_page=2,
            source_elements=["paragraph"],
            token_count=10,
        )
    ]

def _make_mock_embedding():
    return np.random.rand(3, 384)

class TestLLMOptimizerGenerateEmbeddings:
    """Test LLMOptimizer._generate_embeddings method."""

    def setup_method(self, method):
        """Set up test fixtures."""
        # Mock embedding data
        self.mock_embedding = _make_mock_embedding()
        self.mock_embeddings = np.random.rand(3, 384)  # For error test compatibility
        
        # Mock embedding model with standard configuration
        self.mock_embedding_model = MagicMock(spec=SentenceTransformer)
        
        def mock_encode(texts, **kwargs):
            # Return appropriate number of embeddings based on input
            num_texts = len(texts)
            return np.random.rand(num_texts, 384)
        
        self.mock_embedding_model.encode = MagicMock(side_effect=mock_encode)
        
        # Create fresh logger mock for each test
        self.mock_logger = MagicMock(spec_set=logging.Logger)
        
        # Create LLMOptimizer instance with mocked components
        self.optimizer = LLMOptimizer(
            logger=self.mock_logger,
            sentence_transformer=self.mock_embedding_model,
        )
        
        # Standard test chunks
        self.mock_chunks = _make_mock_chunks()
        
        # Large chunk set for batch processing tests
        self.large_chunks = []
        for i in range(50):
            chunk = ChunkFactory.create_chunk_instance(
                content=f"Content for chunk number {i} in batch processing test.",
                chunk_id=f"chunk_{i:04d}",
                source_page=i // 10 + 1,
                source_elements=["paragraph"],
                token_count=10,
            )
            self.large_chunks.append(chunk)
        
        # Batch embeddings for batch processing tests
        self.batch1_embeddings = np.random.rand(32, 384)
        self.batch2_embeddings = np.random.rand(18, 384)
        
        # Common mock configurations
        self.error_mock_model = Mock()
        self.error_mock_model.encode.side_effect = Exception("Embedding generation failed")
        
        self.memory_error_mock_model = Mock()
        self.memory_error_mock_model.encode.side_effect = MemoryError("Insufficient memory for embeddings")
        
        self.empty_chunks_mock_model = Mock()




    @pytest.mark.asyncio
    async def test_generate_embeddings_returns_correct_chunk_count(self):
        """
        GIVEN a list of chunks with valid content
        WHEN _generate_embeddings is called
        THEN the returned list should contain the same number of chunks
        """
        # Given
        chunks = self.mock_chunks.copy()

        # When
        result_chunks = await self.optimizer._generate_embeddings(chunks)
        
        # Then
        expected_length = len(self.mock_chunks)
        assert len(result_chunks) == expected_length, \
            f"Expected exactly {expected_length} chunks in the result, got {len(result_chunks)}"

    @pytest.mark.asyncio
    async def test_generate_embeddings_creates_numpy_array_embeddings(self):
        """
        GIVEN a list of chunks with valid content
        WHEN _generate_embeddings is called
        THEN each chunk should have an embedding as a numpy array
        """
        # Given
        chunks = self.mock_chunks.copy()

        # When
        result_chunks = await self.optimizer._generate_embeddings(chunks)
        
        # Then
        assert isinstance(result_chunks[0].embedding, np.ndarray), \
            f"First chunk embedding should be a numpy array, got {type(result_chunks[0].embedding).__name__}"

    @pytest.mark.asyncio
    async def test_generate_embeddings_creates_correct_embedding_shape(self):
        """
        GIVEN a list of chunks with valid content
        WHEN _generate_embeddings is called
        THEN each chunk embedding should have the expected shape (5,)
        """
        # Given
        chunks = self.mock_chunks.copy()

        # When
        result_chunks = await self.optimizer._generate_embeddings(chunks)
        
        # Then
        shape = (5,)
        assert result_chunks[0].embedding.shape == shape, \
            f"Embedding should have shape {shape}, got {result_chunks[0].embedding.shape}"

    @pytest.mark.asyncio
    async def test_generate_embeddings_preserves_embedding_values(self):
        """
        GIVEN a list of chunks with valid content and mock embeddings
        WHEN _generate_embeddings is called
        THEN the chunk embeddings should match the mock embedding values
        """
        # Given
        chunks = self.mock_chunks.copy()
        expected_embeddings = self.mock_embeddings
        
        # Override the mock for this specific test
        self.optimizer.embedding_model.encode = MagicMock(return_value=expected_embeddings)

        # When
        result_chunks = await self.optimizer._generate_embeddings(chunks)
        
        # Then
        np.testing.assert_array_equal(
            result_chunks[0].embedding, expected_embeddings[0], 
            "result_chunks[0].embedding did not match expected_embeddings[0] values"
        )

    @pytest.mark.asyncio
    async def test_generate_embeddings_calls_model_once(self):
        """
        GIVEN a list of chunks with valid content
        WHEN _generate_embeddings is called
        THEN the embedding model should be called exactly once
        """
        # Given
        chunks = self.mock_chunks.copy()

        # When
        result_chunks = await self.optimizer._generate_embeddings(chunks)

        # Then
        self.optimizer.embedding_model.encode.assert_called_once(), \
            "Embedding model should be called exactly once"

    @pytest.mark.asyncio
    async def test_generate_embeddings_passes_correct_content_count(self):
        """
        GIVEN a list of chunks with valid content
        WHEN _generate_embeddings is called
        THEN the model should receive the correct number of content strings
        """
        # Given
        chunks = self.mock_chunks.copy()

        # When
        result_chunks = await self.optimizer._generate_embeddings(chunks)

        # Then
        content_strings = 3
        call_args = self.optimizer.embedding_model.encode.call_args[0][0]
        assert len(call_args) == content_strings, \
            f"Model should receive exactly {content_strings} content strings, got {len(call_args)}"

    @pytest.mark.asyncio
    async def test_generate_embeddings_passes_correct_first_content(self):
        """
        GIVEN a list of chunks with valid content
        WHEN _generate_embeddings is called
        THEN the first content string passed to the model should match the first chunk
        """
        # Given
        chunks = self.mock_chunks.copy()

        # When
        result_chunks = await self.optimizer._generate_embeddings(chunks)
        
        # Then
        call_args = self.optimizer.embedding_model.encode.call_args[0][0]
        assert call_args[0] == chunks[0].content, \
            f"First content string should match first chunk content, got {call_args[0]}"

    @pytest.mark.asyncio
    async def test_generate_embeddings_model_unavailable_returns_correct_count(self):
        """
        GIVEN an embedding model that is None
        WHEN _generate_embeddings is called
        THEN the returned list should contain the same number of chunks as input
        """
        # Given
        chunks = self.mock_chunks.copy()
        self.optimizer.embedding_model = None
        
        # When
        result_chunks = await self.optimizer._generate_embeddings(chunks)
        
        # Then
        assert len(result_chunks) == len(chunks), \
            f"Should return the same number of chunks when model is unavailable, got {len(result_chunks)}"


    @pytest.mark.asyncio
    async def test_generate_embeddings_model_unavailable_returns_unchanged_chunks(self):
        """
        GIVEN an embedding model that is None
        WHEN _generate_embeddings is called
        THEN the returned chunks should be exactly the same as input chunks
        """
        # Given
        chunks = self.mock_chunks.copy()
        self.optimizer.embedding_model = None

        # When
        result_chunks = await self.optimizer._generate_embeddings(chunks)

        # Then
        assert result_chunks == chunks, "Should return unchanged chunks when model is unavailable"

    @pytest.mark.asyncio
    async def test_generate_embeddings_model_unavailable_logs_warning(self):
        """
        GIVEN an embedding model that is None
        WHEN _generate_embeddings is called
        THEN a warning should be logged about model unavailability
        """
        # Given
        chunks = self.mock_chunks.copy()
        self.optimizer.embedding_model = None
        
        # When
        result_chunks = await self.optimizer._generate_embeddings(chunks)
        
        # Then
        log_message = "No embedding model available, skipping embedding generation"
        self.mock_logger.warning.assert_called_once_with(log_message), \
            "Should log warning when model is unavailable"

    @pytest.mark.asyncio
    async def test_generate_embeddings_model_unavailable_preserves_none_embeddings(self):
        """
        GIVEN an embedding model that is None and chunks with None embeddings
        WHEN _generate_embeddings is called
        THEN all chunk embeddings should remain None
        """
        # Given - Create chunks with None embeddings
        chunks = [
            ChunkFactory.create_chunk_instance(
                content="This is the first chunk of text for testing embeddings.",
                chunk_id="chunk_0000",
                source_page=1,
                source_elements=["paragraph"],
                token_count=12,
                embedding=None
            )
        ]
        self.optimizer.embedding_model = None
        
        # When
        result_chunks = await self.optimizer._generate_embeddings(chunks)
        
        # Then
        assert result_chunks[0].embedding is None, \
            f"chunk embedding should remain None when model is unavailable, got {result_chunks[0].embedding}"


    @pytest.mark.asyncio
    async def test_generate_embeddings_empty_chunks_returns_empty_list(self):
        """
        GIVEN an empty list of chunks
        WHEN _generate_embeddings is called
        THEN an empty list should be returned
        """
        # Given
        chunks = []
        self.optimizer.embedding_model = self.empty_chunks_mock_model
        
        # When
        result_chunks = await self.optimizer._generate_embeddings(chunks)
        
        # Then
        assert result_chunks == [], f"Should return empty list for empty input, got {result_chunks}"

    @pytest.mark.asyncio
    async def test_generate_embeddings_empty_chunks_returns_zero_length(self):
        """
        GIVEN an empty list of chunks
        WHEN _generate_embeddings is called
        THEN the returned list should have zero length
        """
        # Given
        chunks = []
        self.optimizer.embedding_model = self.empty_chunks_mock_model
        
        # When
        result_chunks = await self.optimizer._generate_embeddings(chunks)
        
        # Then
        assert len(result_chunks) == 0, \
            f"Returned list should have zero length for empty input, got {len(result_chunks)}"

    @pytest.mark.asyncio
    async def test_generate_embeddings_empty_chunks_does_not_call_model(self):
        """
        GIVEN an empty list of chunks
        WHEN _generate_embeddings is called
        THEN the embedding model should not be called
        """
        # Given
        chunks = []
        self.optimizer.embedding_model = self.empty_chunks_mock_model
        
        # When
        result_chunks = await self.optimizer._generate_embeddings(chunks)
        
        # Then
        self.empty_chunks_mock_model.encode.assert_not_called(), \
            "Embedding model should not be called for empty input"

    @pytest.mark.asyncio
    async def test_generate_embeddings_batch_processing_returns_correct_count(self):
        """
        GIVEN a large number of chunks (50) requiring batch processing
        WHEN _generate_embeddings is called
        THEN the returned list should contain all 50 chunks
        """
        # Given
        mock_embedding_model = Mock()
        mock_embedding_model.encode.side_effect = [self.batch1_embeddings, self.batch2_embeddings]
        self.optimizer.embedding_model = mock_embedding_model
        
        # When
        result_chunks = await self.optimizer._generate_embeddings(self.large_chunks)
        
        # Then
        assert len(result_chunks) == 50, "Should return all 50 chunks after batch processing"

    @pytest.mark.asyncio
    async def test_generate_embeddings_batch_processing_creates_non_null_embeddings(self):
        """
        GIVEN a large number of chunks requiring batch processing
        WHEN _generate_embeddings is called
        THEN each chunk should have a non-None embedding
        """
        # Given
        mock_embedding_model = Mock()
        mock_embedding_model.encode.side_effect = [self.batch1_embeddings, self.batch2_embeddings]
        self.optimizer.embedding_model = mock_embedding_model
        
        # When
        result_chunks = await self.optimizer._generate_embeddings(self.large_chunks)
        
        # Then
        assert result_chunks[0].embedding is not None, "First chunk should have non-None embedding after batch processing"

    @pytest.mark.asyncio
    async def test_generate_embeddings_batch_processing_creates_numpy_arrays(self):
        """
        GIVEN a large number of chunks requiring batch processing
        WHEN _generate_embeddings is called
        THEN each chunk embedding should be a numpy array
        """
        # Given
        mock_embedding_model = Mock()
        mock_embedding_model.encode.side_effect = [self.batch1_embeddings, self.batch2_embeddings]
        self.optimizer.embedding_model = mock_embedding_model
        
        # When
        result_chunks = await self.optimizer._generate_embeddings(self.large_chunks)
        
        # Then
        assert isinstance(result_chunks[0].embedding, np.ndarray), "First chunk embedding should be numpy array after batch processing"

    @pytest.mark.asyncio
    async def test_generate_embeddings_batch_processing_creates_correct_shape(self):
        """
        GIVEN a large number of chunks requiring batch processing
        WHEN _generate_embeddings is called
        THEN each chunk embedding should have the correct shape (384,)
        """
        # Given
        mock_embedding_model = Mock()
        mock_embedding_model.encode.side_effect = [self.batch1_embeddings, self.batch2_embeddings]
        self.optimizer.embedding_model = mock_embedding_model
        
        # When
        result_chunks = await self.optimizer._generate_embeddings(self.large_chunks)
        
        # Then
        assert result_chunks[0].embedding.shape == (384,), "First chunk embedding should have shape (384,) after batch processing"

    @pytest.mark.asyncio
    async def test_generate_embeddings_batch_processing_calls_model_twice(self):
        """
        GIVEN 50 chunks requiring batch processing
        WHEN _generate_embeddings is called
        THEN the embedding model should be called exactly twice for batching
        """
        # Given
        mock_embedding_model = Mock()
        mock_embedding_model.encode.side_effect = [self.batch1_embeddings, self.batch2_embeddings]
        self.optimizer.embedding_model = mock_embedding_model
        
        # When
        result_chunks = await self.optimizer._generate_embeddings(self.large_chunks)
        
        # Then
        expected_call_count = 2
        actual_call_count = mock_embedding_model.encode.call_count
        assert actual_call_count == expected_call_count, \
            f"Embedding model should be called exactly {expected_call_count} for 50 chunks, got {actual_call_count}"

    @pytest.mark.asyncio
    async def test_generate_embeddings_batch_processing_first_batch_size(self):
        """
        GIVEN 50 chunks requiring batch processing
        WHEN _generate_embeddings is called
        THEN the first batch should contain 32 chunks
        """
        # Given
        mock_embedding_model = Mock()
        mock_embedding_model.encode.side_effect = [self.batch1_embeddings, self.batch2_embeddings]
        self.optimizer.embedding_model = mock_embedding_model
        
        # When
        result_chunks = await self.optimizer._generate_embeddings(self.large_chunks)
        
        # Then
        expected_batch_size = 32
        first_batch_call = mock_embedding_model.encode.call_args_list[0]
        actual_batch_size = len(first_batch_call[0][0])
        assert actual_batch_size == expected_batch_size, \
            f"First batch should contain exactly {expected_batch_size} chunks, got {actual_batch_size}"

    @pytest.mark.asyncio
    async def test_generate_embeddings_batch_processing_second_batch_size(self):
        """
        GIVEN 50 chunks requiring batch processing
        WHEN _generate_embeddings is called
        THEN the second batch should contain 18 chunks
        """
        # Given
        mock_embedding_model = Mock()
        mock_embedding_model.encode.side_effect = [self.batch1_embeddings, self.batch2_embeddings]
        self.optimizer.embedding_model = mock_embedding_model
        
        # When
        result_chunks = await self.optimizer._generate_embeddings(self.large_chunks)

        # Then
        expected_batch_size = 18
        second_batch_call = mock_embedding_model.encode.call_args_list[1]
        assert len(second_batch_call[0][0]) == expected_batch_size, \
            f"Second batch should contain exactly {expected_batch_size} chunks, got {len(second_batch_call[0][0])}"

    @pytest.mark.asyncio
    async def test_generate_embeddings_error_handling_returns_correct_count(self):
        """
        GIVEN chunks and an embedding model that raises an exception
        WHEN _generate_embeddings is called
        THEN the returned list should contain the same number of chunks as input
        """
        # Given
        chunks = self.mock_chunks.copy()
        self.optimizer.embedding_model = self.error_mock_model

        # When
        result_chunks = await self.optimizer._generate_embeddings(chunks)
        
        # Then
        expected_length = len(chunks)
        assert len(result_chunks) == expected_length, \
            f"Should return {expected_length} chunks even when embedding generation fails"

    @pytest.mark.asyncio
    async def test_generate_embeddings_error_handling_preserves_none_embeddings(self):
        """
        GIVEN chunks and an embedding model that raises an exception
        WHEN _generate_embeddings is called
        THEN all chunk embeddings should remain None
        """
        # Given
        chunks = self.mock_chunks.copy()
        self.optimizer.embedding_model = self.error_mock_model

        # When
        result_chunks = await self.optimizer._generate_embeddings(chunks)

        # Then
        assert result_chunks[0].embedding is None, "First chunk embedding should remain None after exception"

    @pytest.mark.asyncio
    async def test_generate_embeddings_error_handling_logs_error_once(self):
        """
        GIVEN chunks and an embedding model that raises an exception
        WHEN _generate_embeddings is called
        THEN an error should be logged exactly once
        """
        # Given
        chunks = self.mock_chunks.copy()
        self.optimizer.embedding_model = self.error_mock_model
        
        # When
        result_chunks = await self.optimizer._generate_embeddings(chunks)

        # Then
        self.optimizer.logger.error.assert_called_once(), \
            "Error should be logged exactly once when embedding generation fails"

    @pytest.mark.asyncio
    async def test_generate_embeddings_error_handling_logs_correct_message(self):
        """
        GIVEN chunks and an embedding model that raises an exception
        WHEN _generate_embeddings is called
        THEN the logged error message should contain the correct batch and error details
        """
        # Given
        chunks = self.mock_chunks.copy()
        self.optimizer.embedding_model = self.error_mock_model
        
        # When
        result_chunks = await self.optimizer._generate_embeddings(chunks)
        
        # Then
        expected_msg = "Failed to generate embeddings for batch 1: Embedding generation failed"
        log_call_args = self.optimizer.logger.error.call_args[0][0]
        assert expected_msg == log_call_args, \
            f"Error message should have been '{expected_msg}', got '{log_call_args}'"

    @pytest.mark.asyncio
    async def test_generate_embeddings_memory_error_returns_correct_count(self):
        """
        GIVEN chunks and an embedding model that raises MemoryError
        WHEN _generate_embeddings is called
        THEN the returned list should contain the same number of chunks as input
        """
        # Given
        chunks = self.mock_chunks.copy()
        self.optimizer.embedding_model = self.memory_error_mock_model

        # When
        result_chunks = await self.optimizer._generate_embeddings(chunks)
        
        # Then
        expected_length = 3
        assert len(result_chunks) == expected_length, \
            f"Should return {expected_length} chunks even when MemoryError occurs, got {len(result_chunks)}"

    @pytest.mark.asyncio
    async def test_generate_embeddings_memory_error_preserves_none_embeddings(self):
        """
        GIVEN chunks and an embedding model that raises MemoryError
        WHEN _generate_embeddings is called
        THEN all chunk embeddings should remain None
        """
        # Given
        chunks = self.mock_chunks.copy()
        self.optimizer.embedding_model = self.memory_error_mock_model
        
        # When
        result_chunks = await self.optimizer._generate_embeddings(chunks)
        
        # Then
        assert result_chunks[0].embedding is None, \
            "First chunk embedding should remain None after MemoryError"

    @pytest.mark.asyncio
    async def test_generate_embeddings_memory_error_logs_error_once(self):
        """
        GIVEN chunks and an embedding model that raises MemoryError
        WHEN _generate_embeddings is called
        THEN an error should be logged exactly once
        """
        # Given
        chunks = self.mock_chunks.copy()
        self.optimizer.embedding_model = self.memory_error_mock_model

        # When
        result_chunks = await self.optimizer._generate_embeddings(chunks)

        # Then
        self.optimizer.logger.error.assert_called_once(), \
            "Error should be logged exactly once when MemoryError occurs"

    @pytest.mark.asyncio
    async def test_generate_embeddings_memory_error_logs_correct_message(self):
        """
        GIVEN chunks and an embedding model that raises MemoryError
        WHEN _generate_embeddings is called
        THEN the logged error message should contain the correct memory error details
        """
        # Given
        chunks = self.mock_chunks.copy()
        self.optimizer.embedding_model = self.memory_error_mock_model
        
        # When
        result_chunks = await self.optimizer._generate_embeddings(chunks)

        # Then
        expected_msg = "Failed to generate embeddings for batch 1: Insufficient memory for embeddings"
        log_call_args = self.optimizer.logger.error.call_args[0][0]
        assert expected_msg == log_call_args, \
            f"Error message should have been '{expected_msg}', got '{log_call_args}'"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
