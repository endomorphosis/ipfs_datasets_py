#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer.py
# Auto-generated on 2025-07-07 02:28:56"

from datetime import datetime
import pytest
import os
import time
import numpy as np
from unittest.mock import Mock, patch

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
    LLMChunkMetadata,
    LLMDocumentProcessingMetadata
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


# ================================
# FIXTURES
# ================================


@pytest.fixture
def results_from_multiple_runs(
    llm_optimizer_with_mocks, 
    consistency_decomposed_content, 
    consistency_document_metadata, 
    number_of_runs
    ) -> list[LLMDocument]:
    results = []
    for _ in range(number_of_runs):
        result = asyncio.run(
            llm_optimizer_with_mocks.optimize_for_llm(
                consistency_decomposed_content, 
                consistency_document_metadata
            )
        )
        results.append(result)
    return results


def get_metadata_key_list() -> list[str]:
    """Extract metadata keys from LLMChunkMetadata dataclass."""
    keys = [field.name for field in LLMDocumentProcessingMetadata.model_fields.keys()]
    print(f"Extracted metadata keys: {keys}")
    return keys

# ================================
# TEST CLASSES
# ================================


class TestLLMOptimizerIntegration:
    """Test LLMOptimizer integration and end-to-end workflows."""

    @pytest.mark.asyncio
    async def test_complete_optimization_pipeline_returns_llm_document(
        self, llm_optimizer_with_mocks, realistic_decomposed_content, realistic_document_metadata):
        """
        GIVEN realistic PDF decomposition output
        WHEN complete optimization pipeline is executed
        THEN expect LLMDocument to be returned
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(realistic_decomposed_content, realistic_document_metadata)
        
        # Then
        assert isinstance(result, LLMDocument), \
            f"Expected result to be LLMDocument, got {type(result).__name__} instead."

    @pytest.mark.parametrize("metadata_key,expected_attr", [
        ('document_id', 'document_id'),
        ('title', 'title'),
    ])
    @pytest.mark.asyncio
    async def test_complete_optimization_pipeline_preserves_metadata(
        self, llm_optimizer_with_mocks, realistic_decomposed_content, realistic_document_metadata, metadata_key, expected_attr):
        """
        GIVEN realistic PDF decomposition output
        WHEN complete optimization pipeline is executed
        THEN expect metadata to be preserved
        """
        # Given
        expected_value = realistic_document_metadata[metadata_key]

        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(realistic_decomposed_content, realistic_document_metadata)
        
        # Then
        actual_value = getattr(result, expected_attr)
        assert actual_value == expected_value, \
            f"Expected {expected_attr} to be '{expected_value}', got '{actual_value}' instead."

    @pytest.mark.parametrize("attribute,expected_type", [
        ("summary", str),
        ("chunks", list),
    ])
    @pytest.mark.asyncio
    async def test_complete_optimization_pipeline_has_correct_types(self, llm_optimizer_with_mocks, realistic_decomposed_content, realistic_document_metadata, attribute, expected_type):
        """
        GIVEN realistic PDF decomposition output
        WHEN complete optimization pipeline is executed
        THEN expect the document attribute to have the correct type:
            - 'summary' should be a string
            - 'chunks' should be a list
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(realistic_decomposed_content, realistic_document_metadata)
        
        # Then
        actual_value = getattr(result, attribute)
        assert isinstance(actual_value, expected_type), \
            f"Expected {attribute} to be {expected_type.__name__}, got {type(actual_value).__name__}"

    @pytest.mark.asyncio
    async def test_complete_optimization_pipeline_creates_non_empty_chunks(self, llm_optimizer_with_mocks, realistic_decomposed_content, realistic_document_metadata):
        """
        GIVEN realistic PDF decomposition output
        WHEN complete optimization pipeline is executed
        THEN expect chunks list to be non-empty
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(realistic_decomposed_content, realistic_document_metadata)
        
        # Then
        assert len(result.chunks) > 0, f"Expected non-empty chunks list, got {len(result.chunks)}"

    @pytest.mark.asyncio
    async def test_complete_optimization_pipeline_chunk_structure_is_llm_chunk(self, llm_optimizer_with_mocks, realistic_decomposed_content, realistic_document_metadata):
        """
        GIVEN realistic PDF decomposition output
        WHEN complete optimization pipeline is executed
        THEN expect each chunk to be an LLMChunk instance
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(realistic_decomposed_content, realistic_document_metadata)
        
        # Then
        for idx, chunk in enumerate(result.chunks):
            assert isinstance(chunk, LLMChunk), f"Expected chunk[{idx}] to be LLMChunk, got {type(chunk)}"


    @pytest.mark.asyncio
    async def test_complete_optimization_pipeline_chunk_has_non_empty_content(self, llm_optimizer_with_mocks, realistic_decomposed_content, realistic_document_metadata):
        """
        GIVEN realistic PDF decomposition output
        WHEN complete optimization pipeline is executed
        THEN expect each chunk to have non-empty content
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(realistic_decomposed_content, realistic_document_metadata)
        
        # Then
        for idx, chunk in enumerate(result.chunks):
            assert len(chunk.content) > 0, \
                f"Expected the length of chunk[{idx}].content to be positive, got {chunk.token_count}"


    @pytest.mark.asyncio
    async def test_complete_optimization_pipeline_chunk_has_positive_token_count(self, llm_optimizer_with_mocks, realistic_decomposed_content, realistic_document_metadata):
        """
        GIVEN realistic PDF decomposition output
        WHEN complete optimization pipeline is executed
        THEN expect each chunk to have a positive token count
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(realistic_decomposed_content, realistic_document_metadata)
        
        # Then
        for idx, chunk in enumerate(result.chunks):
            assert chunk.token_count > 0, \
                f"Expected chunk[{idx}].token_count to be positive, got {chunk.token_count}"


    @pytest.mark.parametrize("attribute,expected_type", [
        ("content", str),
        ("chunk_id", str),
        ("token_count", int),
        ("semantic_types", str),
        ("relationships", list),
        ("metadata", LLMChunkMetadata),
    ])
    @pytest.mark.asyncio
    async def test_complete_optimization_pipeline_chunk_has_correct_attribute_types(self, llm_optimizer_with_mocks, realistic_decomposed_content, realistic_document_metadata, attribute, expected_type):
        """
        GIVEN realistic PDF decomposition output
        WHEN complete optimization pipeline is executed
        THEN expect each chunk to have attributes with correct types
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(realistic_decomposed_content, realistic_document_metadata)
        
        # Then
        for idx, chunk in enumerate(result.chunks):
            actual_value = getattr(chunk, attribute)
            assert isinstance(actual_value, expected_type), \
            f"expected chunk[{idx}].{attribute} to be a {expected_type.__name__}, got {type(actual_value).__name__}"


    @pytest.mark.asyncio
    async def test_complete_optimization_pipeline_has_non_empty_summary(self, llm_optimizer_with_mocks, realistic_decomposed_content, realistic_document_metadata):
        """
        GIVEN realistic PDF decomposition output
        WHEN complete optimization pipeline is executed
        THEN expect document to have a non-empty summary
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(realistic_decomposed_content, realistic_document_metadata)
        
        # Then
        assert len(result.summary) > 0, \
            f"Expected non-empty summary, got length {len(result.summary)}"

    @pytest.mark.parametrize("attribute,expected_type", [
        ("key_entities", list),
        ("processing_metadata", dict)
    ])
    @pytest.mark.asyncio
    async def test_complete_optimization_pipeline_has_correct_attribute_types(self, llm_optimizer_with_mocks, realistic_decomposed_content, realistic_document_metadata, attribute, expected_type):
        """
        GIVEN realistic PDF decomposition output
        WHEN complete optimization pipeline is executed
        THEN expect document to have attributes with correct types
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(realistic_decomposed_content, realistic_document_metadata)
        
        # Then
        actual_value = getattr(result, attribute)
        assert isinstance(actual_value, expected_type), \
            f"expected {attribute} to be a {expected_type.__name__}, got {type(actual_value).__name__}"

    @pytest.mark.asyncio
    async def test_complete_optimization_pipeline_completes_within_time_limit(
        self, llm_optimizer_with_mocks, realistic_decomposed_content, realistic_document_metadata, time_limit):
        """
        GIVEN realistic PDF decomposition output
        WHEN complete optimization pipeline is executed
        THEN expect processing to complete within 30 seconds
        """
        # When
        start_time = time.time()
        _ = await llm_optimizer_with_mocks.optimize_for_llm(realistic_decomposed_content, realistic_document_metadata)
        processing_time = time.time() - start_time

        # Then
        assert processing_time < time_limit, \
            f"expected processing to complete within {time_limit} seconds, got {processing_time} seconds."

    @pytest.mark.parametrize("metadata_key", get_metadata_key_list())
    @pytest.mark.asyncio
    async def test_complete_optimization_pipeline_includes_metadata(self, llm_optimizer_with_mocks, realistic_decomposed_content, realistic_document_metadata, metadata_key):
        """
        GIVEN realistic PDF decomposition output
        WHEN complete optimization pipeline is executed
        THEN expect processing metadata to include expected keys
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(realistic_decomposed_content, realistic_document_metadata)
        print(result)

        # Then
        assert metadata_key in result.processing_metadata, \
            f"Expected metadata key '{metadata_key}' not found in processing metadata."

    @pytest.mark.asyncio
    async def test_pipeline_error_invalid_content_missing_pages(self, llm_optimizer_with_mocks, invalid_decomposed_content, simple_document_metadata):
        """
        GIVEN invalid decomposed content (missing pages)
        WHEN optimization pipeline is executed
        THEN expect KeyError to be raised with message that mentions 'pages'
        """
        # When & Then - Should raise appropriate error
        with pytest.raises(KeyError, match=r"(?i)pages") as exc_info:
            await llm_optimizer_with_mocks.optimize_for_llm(invalid_decomposed_content, simple_document_metadata)

    @pytest.mark.asyncio
    async def test_pipeline_error_embedding_model_failure_returns_document(self, llm_optimizer_with_mocks, simple_decomposed_content, simple_document_metadata):
        """
        GIVEN valid content but embedding model failure
        WHEN optimization pipeline is executed
        THEN expect LLMDocument to be returned
        """
        # Mock embedding model to raise error
        llm_optimizer_with_mocks.embedding_model.encode.side_effect = RuntimeError("Model failed")

        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(simple_decomposed_content, simple_document_metadata)

        # Then
        assert isinstance(result, LLMDocument), \
            f"Expected result to be LLMDocument after embedding_model failure, got {type(result).__name__} instead."

    @pytest.mark.asyncio
    async def test_pipeline_error_embedding_model_failure_chunks_no_embeddings(self, llm_optimizer_with_mocks, simple_decomposed_content, simple_document_metadata):
        """
        GIVEN valid content but embedding model failure
        WHEN optimization pipeline is executed
        THEN expect chunks to exist but without embeddings
        """
        # Mock embedding model to raise error
        llm_optimizer_with_mocks.embedding_model.encode.side_effect = RuntimeError("Model failed")

        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(simple_decomposed_content, simple_document_metadata)

        # Then - Chunks should exist but without embeddings
        for chunk in result.chunks:
            assert chunk.embedding is None, \
                f"Expected chunk.embedding to be None due to embedding model failure, got {type(chunk.embedding).__name__} instead."


class TestLLMOptimizerConsistency:
    """Test LLMOptimizer consistency and reproducibility across multiple runs."""

    @pytest.mark.asyncio
    async def test_pipeline_consistency_document_id(self, results_from_multiple_runs):
        """
        GIVEN consistent test content and metadata
        WHEN the optimization pipeline is executed multiple times
        THEN the document ID should remain identical across all runs
        """
        # When - Run multiple times
        results = results_from_multiple_runs

        # Then - Verify document ID consistency
        first_result = results[0]
        for result in results[1:]:
            assert result.document_id == first_result.document_id, \
                f"Expected document_id '{first_result.document_id}', got '{result.document_id}'"

    @pytest.mark.asyncio
    async def test_pipeline_consistency_title(self, results_from_multiple_runs):
        """
        GIVEN consistent test content and metadata
        WHEN the optimization pipeline is executed multiple times
        THEN the document title should remain identical across all runs
        """
        # When - Run multiple times
        results = results_from_multiple_runs

        # Then - Verify title consistency
        first_result = results[0]
        for result in results[1:]:
            assert result.title == first_result.title, \
                f"Expected title '{first_result.title}', got '{result.title}'"

    @pytest.mark.asyncio
    async def test_pipeline_consistency_chunk_count(self, results_from_multiple_runs):
        """
        GIVEN consistent test content and metadata
        WHEN the optimization pipeline is executed multiple times
        THEN the number of chunks produced should be identical across all runs
        """
        # When - Run multiple times
        results = results_from_multiple_runs

        # Then - Verify chunk count consistency
        first_result = results[0]
        for result in results[1:]:
            assert len(result.chunks) == len(first_result.chunks), \
                f"Expected {len(first_result.chunks)} chunks, got {len(result.chunks)}"

    @pytest.mark.asyncio
    async def test_pipeline_consistency_chunk_content(self, results_from_multiple_runs):
        """
        GIVEN consistent test content and metadata
        WHEN the optimization pipeline is executed multiple times
        THEN each chunk's text content should be identical across all runs
        """
        # When - Run multiple times
        results = results_from_multiple_runs

        # Then - Verify chunk content consistency
        first_result = results[0]
        for result in results[1:]:
            for i, (chunk1, chunk2) in enumerate(zip(first_result.chunks, result.chunks)):
                assert chunk1.content == chunk2.content, \
                    f"Expected chunk[{i}].content to be identical across runs, got '{chunk1.content}' vs '{chunk2.content}'"

    @pytest.mark.asyncio
    async def test_pipeline_consistency_chunk_ids(self, results_from_multiple_runs):
        """
        GIVEN consistent test content and metadata
        WHEN the optimization pipeline is executed multiple times
        THEN each chunk's ID should be identical across all runs
        """
        # When - Run multiple times
        results = results_from_multiple_runs

        # Then - Verify chunk ID consistency
        first_result = results[0]
        for result in results[1:]:
            for i, (chunk1, chunk2) in enumerate(zip(first_result.chunks, result.chunks)):
                assert chunk1.chunk_id == chunk2.chunk_id, \
                    f"Expected chunk[{i}].chunk_id to be identical across runs, got '{chunk1.chunk_id}' and '{chunk2.chunk_id}'"

    @pytest.mark.asyncio
    async def test_pipeline_consistency_token_counts(self, results_from_multiple_runs):
        """
        GIVEN consistent test content and metadata
        WHEN the optimization pipeline is executed multiple times
        THEN each chunk's token count should be identical across all runs
        """
        # When - Run multiple times
        results = results_from_multiple_runs

        # Then - Verify token count consistency
        first_result = results[0]
        for result in results[1:]:
            for i, (chunk1, chunk2) in enumerate(zip(first_result.chunks, result.chunks)):
                assert chunk1.token_count == chunk2.token_count

    @pytest.mark.asyncio
    async def test_pipeline_consistency_semantic_types(self, results_from_multiple_runs):
        """
        GIVEN consistent test content and metadata
        WHEN the optimization pipeline is executed multiple times
        THEN each chunk's semantic type classification should be identical across all runs
        """
        # When - Run multiple times
        results = results_from_multiple_runs

        # Then - Verify semantic types consistency
        first_result = results[0]
        for result in results[1:]:
            for i, (chunk1, chunk2) in enumerate(zip(first_result.chunks, result.chunks)):
                assert chunk1.semantic_types == chunk2.semantic_types, \
                    f"Expected chunk[{i}].semantic_types to be identical across runs, got '{chunk1.semantic_types}' vs '{chunk2.semantic_types}'"

    @pytest.mark.asyncio
    async def test_pipeline_consistency_source_pages(self, results_from_multiple_runs):
        """
        GIVEN consistent test content and metadata
        WHEN the optimization pipeline is executed multiple times
        THEN each chunk's source page number should be identical across all runs
        """
        # When - Run multiple times
        results = results_from_multiple_runs

        # Then - Verify source page consistency
        first_result = results[0]
        for result in results[1:]:
            for i, (chunk1, chunk2) in enumerate(zip(first_result.chunks, result.chunks)):
                assert chunk1.source_page == chunk2.source_page, \
                    f"Expected chunk[{i}].source_page to be identical across runs, got '{chunk1.source_page}' vs '{chunk2.source_page}'"

    @pytest.mark.asyncio
    async def test_pipeline_consistency_summary(self, results_from_multiple_runs):
        """
        GIVEN consistent test content and metadata
        WHEN the optimization pipeline is executed multiple times
        THEN the document summary should be identical across all runs
        """
        # When - Run multiple times
        results = results_from_multiple_runs

        # Then - Verify summary consistency
        first_result = results[0]
        for result in results[1:]:
            assert result.summary == first_result.summary, \
                f"Expected summary to be identical across runs, got '{first_result.summary}' vs '{result.summary}'"

    @pytest.mark.asyncio
    async def test_pipeline_consistency_entity_count(self, results_from_multiple_runs):
        """
        GIVEN consistent test content and metadata
        WHEN the optimization pipeline is executed multiple times
        THEN the number of extracted entities should be identical across all runs
        """
        # When - Run multiple times
        results = results_from_multiple_runs

        # Then - Verify entity count consistency
        first_result = results[0]
        for result in results[1:]:
            assert len(result.key_entities) == len(first_result.key_entities), \
                f"Expected {len(first_result.key_entities)} key_entities, got {len(result.key_entities)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
