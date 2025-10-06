#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer.py
# Auto-generated on 2025-07-07 02:28:56"

import os
import time
import asyncio
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock, AsyncMock


import numpy as np
import openai
import pytest
import gc

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


def _make_mock_openai_client():
    """Create a proper mock AsyncOpenAI client with correct structure."""
    mock_client = AsyncMock(spec=openai.AsyncOpenAI)
    
    # Create nested mock structure
    mock_client.chat = AsyncMock()
    mock_client.chat.completions = AsyncMock()
    
    # Mock the create method to return a proper response structure
    mock_response = AsyncMock()
    mock_choice = AsyncMock()
    mock_choice.message.content = "Business"
    mock_choice.logprobs = AsyncMock()
    mock_choice.logprobs.content = [AsyncMock()]
    mock_choice.logprobs.content[0].top_logprobs = [
        AsyncMock(token="Business", logprob=-0.693)
    ]
    mock_response.choices = [mock_choice]

    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    return mock_client


def _make_mock_choices():
    mock_response = Mock()
    mock_response.choices = [Mock()]
    mock_response.choices[0].logprobs = Mock()
    mock_response.choices[0].logprobs.content = [Mock()]
    return mock_response


@pytest.fixture
def document_metadata():
    """Mock document metadata for testing."""
    return {
        'document_id': 'test_doc_001',
        'title': 'Machine Learning Basics',
        'author': 'Test Author'
    }


@pytest.fixture
def element1(element_factory):
    content = "Introduction to Machine Learning"
    subtype = "header"
    return element_factory(content, subtype)


@pytest.fixture
def element2(element_factory):
    content = 'Machine learning enables computers to learn patterns from data without explicit programming.'
    subtype = 'paragraph'
    return element_factory(content, subtype)


@pytest.fixture
def decomposed_content_metadata():
    return {
        'page_count': 1,
        'title': 'ML Basics'
    }


@pytest.fixture
def document_content(element1, element2, decomposed_content_metadata):
    """Mock decomposed content for testing."""
    return {
        'pages': [{'elements': [element1, element2]}],
        'metadata': decomposed_content_metadata,
        'structure': {'page_count': 1, 'title': 'ML Basics'}
    }


@pytest.fixture(params=[1, 5, 10])
def number_of_pages(request):
    """Parameterize number of pages for testing."""
    return request.param


@pytest.fixture
def multiple_page_document_content(number_of_pages, element_factory) -> dict:
    """Generate mock document content with multiple pages."""
    pages = []
    for idx in range(number_of_pages):
        element1 = element_factory(f'Header on page {idx + 1}', 'header')
        element2 = element_factory(f'This is some sample text content on page {idx + 1}. ' * 10, 'paragraph')
        elements = [element1, element2]
        pages.append({'elements': elements})

    return {
        'pages': pages,
        'metadata': {'page_count': number_of_pages, 'title': f'Document with {number_of_pages} pages'},
        'structure': {'page_count': number_of_pages, 'title': f'Document with {number_of_pages} pages'}
    }


@pytest.fixture
def elements_per_page():
    return 20


@pytest.fixture
def number_of_pages():
    return 100

@pytest.fixture
def large_document_timeout_limit():
    return 120 # seconds

@pytest.fixture
def large_document(elements_per_page, number_of_pages, element_factory):
    large_pages = []
    try:
        for page_num in range(number_of_pages):
            elements = []
            for elem_num in range(elements_per_page):
                content = f'Page {page_num + 1}, element {elem_num + 1}. ' * 50
                element = element_factory(content, 'paragraph', {'x': 100, 'y': elem_num * 50})
                elements.append(element)
            large_pages.append({'elements': elements})

        large_content = {
            'pages': large_pages,
            'metadata': {'page_count': number_of_pages, 'title': 'Large Document'},
            'structure': {'page_count': number_of_pages, 'title': 'ML Basics'}
        }
        yield large_content
    finally:
        # Free memory
        large_content = None
        del large_content 
        gc.collect()


@pytest.fixture
def multiple_documents(element_factory):
    documents = []
    for i in range(3):
        content = f'Document {i + 1} unique content for concurrent testing.' * 50
        element = element_factory(content, 'paragraph')
        doc_content = {
            'pages': [
                {
                    'elements': [element]
                }
            ],
            "metadata": {'page_count': 1, 'title': f'Document {i + 1}'},
        }
        doc_metadata = {'document_id': f'concurrent_test_{i + 1}', 'title': f'Concurrent Test {i + 1}'}
        documents.append((doc_content, doc_metadata))
    return documents


@pytest.fixture
def max_chunk_size(llm_optimizer_with_mocks):
    return llm_optimizer_with_mocks.max_chunk_size


@pytest.fixture
def min_chunk_size(llm_optimizer_with_mocks):
    return llm_optimizer_with_mocks.min_chunk_size


@pytest.fixture
def llm_optimizer_with_no_embedding_model(llm_optimizer_with_mocks):
    """Fixture to test without embedding model."""
    llm_optimizer_with_mocks.embedding_model = None
    return llm_optimizer_with_mocks


@pytest.fixture
def llm_optimizer_with_no_tokenizer(llm_optimizer_with_mocks):
    """Fixture to test without tokenizer."""
    llm_optimizer_with_mocks.embedding_model = Mock()
    llm_optimizer_with_mocks.embedding_model.encode.return_value = np.random.rand(384)
    llm_optimizer_with_mocks.tokenizer = None
    return llm_optimizer_with_mocks


@pytest.fixture
def valid_args(document_content, document_metadata):
    """Helper to call optimize_for_llm with valid args."""
    return (document_content, document_metadata)


@pytest.fixture
def error_scenarios():
    output_dict = {
        "no_elements": {'pages': [{'elements': []},{'elements': []}]},
        "empty_pages": {'pages': []},
        "invalid_content_key": {'metadata': {'title': 'Test'}, 'structure': {}},
        "empty_content": {
            'pages': [{
                'elements': [
                {
                    'content': '', 
                    'type': 'text', 
                    'subtype': 
                    'paragraph', 
                    'position': {'x': 0, 'y': 0}, 
                    'confidence': 0.9
                }, 
                {
                    'content': '   ', 
                    'type': 'text', 
                    'subtype': 'paragraph',
                    'position': {'x': 0, 'y': 50}, 
                    'confidence': 0.8
                }]}],
            'metadata': {'title': 'Test'}, 
            'structure': {}
        }
    }
    return output_dict


UNICODE_TEXT = (
    "Título en español: Introducción al aprendizaje automático 🤖\n",
    "Français: L'intelligence artificielle révolutionne l'industrie. 中文测试内容\n",
    "Mathematical symbols: α, β, γ, ∑, ∫, ∂, ∇, ∞, ≈, ≠, ≤, ≥",
)

@pytest.fixture
def unicode_text() -> tuple[str, str, str]:
    UNICODE_TEXT 


def split_unicode_text():
    """Helper function to split unicode text into words."""
    words = []
    for line in UNICODE_TEXT:
        words.extend(
            [word for word in line.split(' ') if word.strip()]
        )
    return words


@pytest.fixture
def unicode_content(unicode_text, element_factory):
    element1 = element_factory(unicode_text[0], 'header')
    element2 = element_factory(unicode_text[1], 'paragraph')
    element3 = element_factory(unicode_text[2], 'paragraph')
    unicode_content = {
        'pages': [
            {'elements': [element1, element2, element3]}
        ]
    }
    return unicode_content

@pytest.fixture
def content_scenarios(
    document_content,
    unicode_content, 
    large_document,
    multiple_page_document_content,
    ):
    return {
        "document_content": document_content,
        "unicode_content": unicode_content,
        "large_document": large_document,
        "multiple_page_document_content": multiple_page_document_content
    }


class TestLLMOptimizerOptimizeForLlm:
    """Test LLMOptimizer.optimize_for_llm main processing method."""


    @pytest.mark.asyncio
    async def test_optimize_for_llm_returns_llm_document(self, llm_optimizer_with_mocks, valid_args):
        """
        GIVEN valid document_content and document_metadata
        WHEN optimize_for_llm is called
        THEN expect LLMDocument instance returned
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(*valid_args)

        # Then
        assert isinstance(result, LLMDocument), \
            f"Expected result to be LLMDocument, got {type(result).__name__} instead."


    @pytest.mark.asyncio
    @pytest.mark.parametrize("metadata_field", ["document_id", "title"])
    async def test_optimize_for_llm_preserves_metadata_fields(
        self, llm_optimizer_with_mocks, valid_args, metadata_field):
        """
        GIVEN valid document_content and document_metadata with metadata fields
        WHEN optimize_for_llm is called
        THEN expect metadata fields preserved in result
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(*valid_args)

        # Then
        result_value = getattr(result, metadata_field)
        metadata_field_value = valid_args[1][metadata_field]
        assert result_value == metadata_field_value, \
            f"Expected {metadata_field} to be '{metadata_field_value}', got '{result_value}' instead"


    @pytest.mark.asyncio
    async def test_optimize_for_llm_creates_non_empty_chunks(self, llm_optimizer_with_mocks, valid_args):
        """
        GIVEN valid document_content with content
        WHEN optimize_for_llm is called
        THEN expect at least one chunk created
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(*valid_args)

        # Then
        assert len(result.chunks) > 0, \
            "Expected at least one chunk to be created, got 0 instead"


    @pytest.mark.asyncio
    async def test_optimize_for_llm_chunks_are_llm_chunk_instances(
        self, llm_optimizer_with_mocks: LLMOptimizer, valid_args):
        """
        GIVEN valid document_content
        WHEN optimize_for_llm is called
        THEN expect all chunks to be LLMChunk instances
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(*valid_args)

        # Then
        for idx, chunk in enumerate(result.chunks):
            assert isinstance(chunk, LLMChunk), \
                f"Expected chunk {idx} to be LLMChunk, got {type(chunk).__name__} instead"


    @pytest.mark.asyncio
    async def test_optimize_for_llm_chunks_have_content(self, llm_optimizer_with_mocks, valid_args):
        """
        GIVEN valid document_content
        WHEN optimize_for_llm is called
        THEN expect all chunks to have non-empty content
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(*valid_args)

        # Then
        for chunk in result.chunks:
            assert len(chunk.content) > 0, \
                f"Expected chunk content length to be greater than 0, got {len(chunk.content)} instead"


    @pytest.mark.asyncio
    async def test_optimize_for_llm_chunks_have_token_count(self, llm_optimizer_with_mocks, valid_args):
        """
        GIVEN valid document_content
        WHEN optimize_for_llm is called
        THEN expect all chunks to have positive token count
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(*valid_args)

        # Then
        for chunk in result.chunks:
            assert chunk.token_count > 0, \
                f"Expected chunk token_count to be greater than 0, got {chunk.token_count} instead"


    @pytest.mark.asyncio
    async def test_optimize_for_llm_creates_non_empty_summary(self, llm_optimizer_with_mocks, valid_args):
        """
        GIVEN valid document_content with content
        WHEN optimize_for_llm is called
        THEN expect non-empty summary
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(*valid_args)

        # Then
        assert len(result.summary) > 0, \
            f"Expected length of summary to be greater than 0, got {len(result.summary)} instead"


    @pytest.mark.asyncio
    @pytest.mark.parametrize("attribute,expected_type", [
        ("key_entities", list),
        ("processing_metadata", dict),
        ("summary", str),
        ("chunks", list)
    ])
    async def test_optimize_for_llm_creates_correct_attribute_types(
        self, llm_optimizer_with_mocks, valid_args, attribute, expected_type):
        """
        GIVEN valid document_content
        WHEN optimize_for_llm is called
        THEN expect attributes returned with correct types
        """
        # When
        print(valid_args)
        result = await llm_optimizer_with_mocks.optimize_for_llm(*valid_args)

        # Then
        actual_value = getattr(result, attribute)
        assert isinstance(actual_value, expected_type), \
            f"Expected {attribute} to be {expected_type.__name__}, got {type(actual_value).__name__} instead."


    @pytest.mark.asyncio
    @pytest.mark.parametrize("key", ["optimization_timestamp", "chunk_count", "total_tokens"])
    async def test_optimize_for_llm_includes_required_processing_metadata(
        self, llm_optimizer_with_mocks, valid_args, key):
        """
        GIVEN valid document_content
        WHEN optimize_for_llm is called
        THEN expect required metadata keys in processing_metadata
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(*valid_args)

        # Then
        assert key in result.processing_metadata, \
            f"Expected processing_metadata to include key '{key}'"


    @pytest.mark.asyncio
    async def test_optimize_for_llm_chunk_count_metadata_matches_actual_chunks(
        self, llm_optimizer_with_mocks, valid_args):
        """
        GIVEN valid document_content
        WHEN optimize_for_llm is called
        THEN expect chunk_count metadata to match actual chunk count
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(*valid_args)

        # Then
        chunk_count = result.processing_metadata['chunk_count']
        assert chunk_count == len(result.chunks), \
            f"Expected chunk_count metadata to be {len(result.chunks)}, got {chunk_count} instead"


    @pytest.mark.asyncio
    async def test_optimize_for_llm_missing_pages_key_raises_key_error(
        self, llm_optimizer_with_mocks, error_scenarios, document_metadata):
        """
        GIVEN document_content missing 'pages' key
        WHEN optimize_for_llm is called
        THEN expect KeyError raised
        """
        invalid_content = error_scenarios['invalid_content_key']

        with pytest.raises(KeyError):
            await llm_optimizer_with_mocks.optimize_for_llm(invalid_content, document_metadata)


    @pytest.mark.asyncio
    @pytest.mark.parametrize("arg_num", [0,1])
    async def test_optimize_for_llm_wrong_content_type_raises_type_error(
        self, arg_num, llm_optimizer_with_mocks, valid_args):
        """
        GIVEN an argument is None
        WHEN optimize_for_llm is called
        THEN expect TypeError raised
        """
        invalid_args = list(valid_args)
        invalid_args[arg_num] = None

        with pytest.raises(TypeError):
            await llm_optimizer_with_mocks.optimize_for_llm(*invalid_args)


    @pytest.mark.asyncio
    @pytest.mark.parametrize("arg_num", [0,1])
    async def test_optimize_for_llm_wrong_metadata_type_raises_type_error(
        self, arg_num, llm_optimizer_with_mocks, valid_args):
        """
        GIVEN an argument is None
        WHEN optimize_for_llm is called
        THEN expect TypeError raised
        """
        invalid_args = list(valid_args)
        invalid_args[arg_num] = None

        with pytest.raises(TypeError):
            await llm_optimizer_with_mocks.optimize_for_llm(*invalid_args)


    @pytest.mark.asyncio
    @pytest.mark.parametrize("content_type", ["empty_pages", "no_elements",])
    async def test_optimize_for_llm_invalid_content_raises_value_error(
        self, 
        llm_optimizer_with_mocks, 
        document_metadata, content_type, error_scenarios):
        """
        GIVEN document_content with empty pages or no elements
        WHEN optimize_for_llm is called
        THEN expect ValueError raised
        """
        invalid_content = error_scenarios[content_type]

        with pytest.raises(ValueError):
            await llm_optimizer_with_mocks.optimize_for_llm(invalid_content, document_metadata)


    @pytest.mark.asyncio
    @pytest.mark.parametrize("key", ["document_id", "title", "author"])
    async def test_optimize_for_llm_missing_document_id_raises_key_error(
        self, key, llm_optimizer_with_mocks, document_content, document_metadata):
        """
        GIVEN document_metadata missing any metadata key
        WHEN optimize_for_llm is called
        THEN expect KeyError raised
        """
        incomplete_metadata = document_metadata.copy()
        del incomplete_metadata[key]

        with pytest.raises(KeyError):
            await llm_optimizer_with_mocks.optimize_for_llm(document_content, incomplete_metadata)


    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "key,bad_value", 
        [
            ("document_id", 123),
            ("title", ["not", "a", "string"]),
            ("author", {"not": "a string"})
        ]
    )
    async def test_optimize_for_llm_invalid_metadata_type_then_raises_value_error(
        self, key, bad_value, llm_optimizer_with_mocks, document_content, document_metadata
    ):
        """
        GIVEN document_metadata with non-string metadata values
        WHEN optimize_for_llm is called
        THEN expect ValueError raised
        """
        invalid_type_metadata = document_metadata.copy()
        invalid_type_metadata[key] = bad_value

        with pytest.raises(ValueError):
            await llm_optimizer_with_mocks.optimize_for_llm(document_content, invalid_type_metadata)

    @pytest.mark.asyncio
    async def test_optimize_for_llm_empty_content_raises_value_error(
        self, llm_optimizer_with_mocks, error_scenarios, document_metadata
        ):
        """
        GIVEN document_content with no extractable text
        WHEN optimize_for_llm is called
        THEN expect ValueError raised
        """
        # Given
        empty_content = error_scenarios['empty_content']

        # When
        with pytest.raises(ValueError):
            result = await llm_optimizer_with_mocks.optimize_for_llm(empty_content, document_metadata)

    @pytest.mark.asyncio
    async def test_optimize_for_llm_large_document_returns_llm_document(
        self, llm_optimizer_with_mocks: LLMOptimizer, large_document, document_metadata, large_document_timeout_limit
        ):
        """
        GIVEN large document_content (>100 pages)
        WHEN optimize_for_llm is called
        THEN expect LLMDocument instance returned
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(
            large_document, document_metadata, timeout=large_document_timeout_limit)

        # Then
        assert isinstance(result, LLMDocument), \
            f"Expected result to be LLMDocument, got {type(result).__name__} instead."

    @pytest.mark.asyncio
    async def test_optimize_for_llm_large_document_creates_chunks(
        self, llm_optimizer_with_mocks, large_document, document_metadata, large_document_timeout_limit
        ):
        """
        GIVEN large document_content (>100 pages)
        WHEN optimize_for_llm is called
        THEN expect at least one chunk created
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(
            large_document, document_metadata, timeout=large_document_timeout_limit)

        # Then
        assert len(result.chunks) > 0, \
            f"Expected at least one chunk to be created, got {len(result.chunks)} instead"

    @pytest.mark.asyncio
    async def test_optimize_for_llm_large_document_completes_within_time_limit(
        self, llm_optimizer_with_mocks, large_document, document_metadata, expected_time_limit, large_document_timeout_limit
        ):
        """
        GIVEN large document_content (>100 pages)
        WHEN optimize_for_llm is called
        THEN expect processing completes within the expected time limit
        """
        # When
        start_time = time.time()
        _ = await llm_optimizer_with_mocks.optimize_for_llm(large_document, document_metadata)
        end_time = time.time() - start_time

        # Then
        assert end_time < expected_time_limit, \
            f"Expected processing time to be under {expected_time_limit} seconds, got {end_time:.2f} seconds instead."

    @pytest.mark.asyncio
    async def test_optimize_for_llm_large_document_processes_all_pages(
        self, llm_optimizer_with_mocks, large_document, document_metadata, number_of_pages, large_document_timeout_limit
        ):
        """
        GIVEN large document_content (>100 pages)
        WHEN optimize_for_llm is called
        THEN expect the number of processed pages equals the number of pages in the document
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(
            large_document, document_metadata, timeout=large_document_timeout_limit)

        # Then
        page_numbers = {chunk.source_page for chunk in result.chunks}
        assert len(page_numbers) == number_of_pages, \
            f"Expected chunks from {number_of_pages} pages, got {len(page_numbers)} instead."

    @pytest.mark.asyncio
    async def test_optimize_for_llm_large_document_respects_max_chunk_size(
        self, llm_optimizer_with_mocks, large_document, document_metadata, large_document_timeout_limit
        ):
        """
        GIVEN large document_content (>100 pages)
        WHEN optimize_for_llm is called
        THEN expect all chunks token_count to be less than or equal to max_chunk_size
        """
        max_chunk_size = llm_optimizer_with_mocks.max_chunk_size

        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(
            large_document, document_metadata, timeout=large_document_timeout_limit)

        # Then
        for idx, chunk in enumerate(result.chunks):
            assert chunk.token_count <= max_chunk_size, \
                f"Expected chunk {idx} token_count to be less than or equal to {max_chunk_size}, got {chunk.token_count} instead."

    @pytest.mark.asyncio
    async def test_optimize_for_llm_large_document_respects_min_chunk_size(
        self, llm_optimizer_with_mocks, large_document, document_metadata, min_chunk_size, large_document_timeout_limit
        ):
        """
        GIVEN large document_content (>100 pages)
        WHEN optimize_for_llm is called
        THEN expect all chunks token_count to be greater than or equal to min_chunk_size
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(
            large_document, document_metadata, timeout=large_document_timeout_limit)

        # Then
        for idx, chunk in enumerate(result.chunks):
            assert chunk.token_count >= min_chunk_size, \
                f"Expected chunk {idx} token_count to be greater than or equal to {min_chunk_size}, got {chunk.token_count} instead."

    @pytest.mark.asyncio
    async def test_optimize_for_llm_embedding_model_failure_raises_runtime_error(
        self, llm_optimizer_with_no_embedding_model, document_content, document_metadata, large_document_timeout_limit
        ):
        """
        GIVEN embedding model is None
        WHEN optimize_for_llm is called
        THEN expect RuntimeError raised
        """
        # When/Then
        with pytest.raises(RuntimeError, match=r"embedding model"):
            await llm_optimizer_with_no_embedding_model.optimize_for_llm(
                document_content, document_metadata
            )


    @pytest.mark.asyncio
    async def test_optimize_for_llm_tokenizer_failure_returns_llm_document(
        self, llm_optimizer_with_no_tokenizer, document_content, document_metadata
        ):
        """
        GIVEN tokenizer is None
        WHEN optimize_for_llm is called
        THEN expect LLMDocument returned
        """
        # When
        result = await llm_optimizer_with_no_tokenizer.optimize_for_llm(
            document_content, document_metadata
        )

        # Then
        assert isinstance(result, LLMDocument), \
            f"Expected result to be LLMDocument, got {type(result).__name__} instead."


    @pytest.mark.asyncio
    async def test_optimize_for_llm_tokenizer_failure_creates_chunks(
        self, llm_optimizer_with_no_tokenizer, document_content, document_metadata
        ):
        """
        GIVEN tokenizer is None
        WHEN optimize_for_llm is called
        THEN expect chunks created is greater than 0
        """
        # When
        result = await llm_optimizer_with_no_tokenizer.optimize_for_llm(
            document_content, document_metadata
        )

        # Then
        len_chunks = len(result.chunks)
        assert len_chunks > 0, \
            f"Expected at least one chunk to be created, got {len_chunks} instead"

    @pytest.mark.asyncio
    async def test_optimize_for_llm_concurrent_processing_returns_correct_count(
        self, llm_optimizer_with_mocks, multiple_documents
        ):
        """
        GIVEN multiple concurrent optimize_for_llm calls
        WHEN processing multiple documents simultaneously
        THEN expect correct number of results returned
        """
        # When - Process concurrently
        tasks = [
            llm_optimizer_with_mocks.optimize_for_llm(content, metadata)
            for content, metadata in multiple_documents
        ]
        results = await asyncio.gather(*tasks)

        # Then
        assert len(results) == len(multiple_documents), \
            f"Expected {len(multiple_documents)} results, got {len(results)} instead"

    @pytest.mark.asyncio
    async def test_optimize_for_llm_concurrent_processing_returns_llm_documents(
        self, llm_optimizer_with_mocks, multiple_documents
        ):
        """
        GIVEN multiple concurrent optimize_for_llm calls
        WHEN processing multiple documents simultaneously
        THEN expect all results to be LLMDocument instances
        """
        # When - Process concurrently
        tasks = [
            llm_optimizer_with_mocks.optimize_for_llm(content, metadata)
            for content, metadata in multiple_documents
        ]
        results = await asyncio.gather(*tasks)

        # Then
        for i, result in enumerate(results):
            assert isinstance(result, LLMDocument), \
                f"Expected result {i} to be LLMDocument, got {type(result).__name__} instead"

    @pytest.mark.asyncio
    async def test_optimize_for_llm_concurrent_processing_preserves_document_ids(
        self, llm_optimizer_with_mocks, multiple_documents
        ):
        """
        GIVEN multiple concurrent optimize_for_llm calls
        WHEN processing multiple documents simultaneously
        THEN expect document IDs preserved correctly
        """
        # When - Process concurrently
        tasks = [
            llm_optimizer_with_mocks.optimize_for_llm(content, metadata)
            for content, metadata in multiple_documents
        ]
        results = await asyncio.gather(*tasks)

        # Then
        for i, result in enumerate(results):
            expected_id = f'concurrent_test_{i + 1}'
            assert result.document_id == expected_id, \
                f"Expected document_id '{expected_id}', got '{result.document_id}' instead"

    @pytest.mark.asyncio
    async def test_optimize_for_llm_concurrent_processing_preserves_titles(
        self, llm_optimizer_with_mocks, multiple_documents
        ):
        """
        GIVEN multiple concurrent optimize_for_llm calls
        WHEN processing multiple documents simultaneously
        THEN expect titles preserved correctly
        """
        # When - Process concurrently
        tasks = [
            llm_optimizer_with_mocks.optimize_for_llm(content, metadata)
            for content, metadata in multiple_documents
        ]
        results = await asyncio.gather(*tasks)

        # Then
        for idx, result in enumerate(results):
            expected_title = f'Concurrent Test {idx + 1}'
            assert result.title == expected_title, \
                f"Expected title '{expected_title}' in result {idx}, got '{result.title}' instead"

    @pytest.mark.asyncio
    async def test_optimize_for_llm_concurrent_processing_creates_chunks(
        self, llm_optimizer_with_mocks, multiple_documents
        ):
        """
        GIVEN multiple concurrent optimize_for_llm calls
        WHEN processing multiple documents simultaneously
        THEN expect all results to have chunks
        """
        # When - Process concurrently
        tasks = [
            llm_optimizer_with_mocks.optimize_for_llm(content, metadata)
            for content, metadata in multiple_documents
        ]
        results = await asyncio.gather(*tasks)

        # Then
        for i, result in enumerate(results):
            assert len(result.chunks) > 0, \
                f"Expected result {i} to have chunks, got {len(result.chunks)} chunks instead"

    @pytest.mark.asyncio
    async def test_optimize_for_llm_concurrent_processing_preserves_content(
        self, llm_optimizer_with_mocks, multiple_documents
        ):
        """
        GIVEN multiple concurrent optimize_for_llm calls
        WHEN processing multiple documents simultaneously
        THEN expect document-specific content preserved in chunks
        """
        # When - Process concurrently
        tasks = [
            llm_optimizer_with_mocks.optimize_for_llm(content, metadata)
            for content, metadata in multiple_documents
        ]
        results = await asyncio.gather(*tasks)

        # Then
        for i, result in enumerate(results):
            expected_content = f'Document {i + 1}'
            assert expected_content in result.chunks[0].content, \
                f"Expected '{expected_content}' in chunk content, but it was not found"


    @pytest.mark.asyncio
    async def test_optimize_for_llm_unicode_content_returns_llm_document(
        self, llm_optimizer_with_mocks, unicode_content, document_metadata
        ):
        """
        GIVEN content with Unicode characters and special formatting
        WHEN optimize_for_llm is called
        THEN expect LLMDocument instance returned
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(unicode_content, document_metadata)
        
        # Then
        assert isinstance(result, LLMDocument), \
            f"Expected result to be LLMDocument, got {type(result).__name__} instead."

    @pytest.mark.asyncio
    async def test_optimize_for_llm_unicode_content_creates_chunks(
        self, llm_optimizer_with_mocks, unicode_content, document_metadata
        ):
        """
        GIVEN content with Unicode characters and special formatting
        WHEN optimize_for_llm is called
        THEN expect at least one chunk created
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(unicode_content, document_metadata)
        
        # Then
        assert len(result.chunks) > 0, \
            f"Expected at least one chunk to be created, got {len(result.chunks)} instead"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("word", split_unicode_text())
    async def test_optimize_for_llm_unicode_content_preserves_emoji(
        self, word, llm_optimizer_with_mocks, unicode_content, document_metadata,
        ):
        """
        GIVEN content with Unicode emoji characters
        WHEN optimize_for_llm is called
        THEN expect emoji characters preserved in content
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(unicode_content, document_metadata)

        # Then
        all_content = ' '.join(chunk.content for chunk in result.chunks)
        assert word in all_content, \
            f"Expected word '{word}' was not found in any chunk content"


    @pytest.mark.asyncio
    async def test_optimize_for_llm_unicode_content_chunks_are_strings(
        self, llm_optimizer_with_mocks, unicode_content,document_metadata
        ):
        """
        GIVEN content with Unicode characters
        WHEN optimize_for_llm is called
        THEN expect all chunk content to be string instances
        """
        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(unicode_content, document_metadata)

        # Then
        for idx, chunk in enumerate(result.chunks):
            assert isinstance(chunk.content, str), \
                f"Expected chunk {idx} content to be str, got {type(chunk.content).__name__} instead"


    @pytest.mark.asyncio
    async def test_optimize_for_llm_unicode_content_no_replacement_characters(
        self, llm_optimizer_with_mocks, unicode_content, document_metadata
        ):
        """
        GIVEN content with Unicode characters
        WHEN optimize_for_llm is called
        THEN expect no Unicode replacement characters in content
        """
        replacement_char = '�'

        # When
        result = await llm_optimizer_with_mocks.optimize_for_llm(unicode_content, document_metadata)

        # Then
        for idx, chunk in enumerate(result.chunks):
            assert replacement_char not in chunk.content, \
                f"Expected no replacement characters in chunk {idx} content, but found '�'"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
