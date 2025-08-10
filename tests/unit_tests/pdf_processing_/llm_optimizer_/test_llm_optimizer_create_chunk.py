#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer.py
# Auto-generated on 2025-07-07 02:28:56"

from datetime import datetime
import pytest
import os
import time
import unittest.mock
from datetime import datetime
from unittest.mock import Mock, patch, MagicMock

from pydantic import ValidationError

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
    LLMDocument,
    LLMChunkMetadata,
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


class TestLLMOptimizerCreateChunk:
    """Test LLMOptimizer._create_chunk method."""

    def setup_method(self):
        self.optimizer = LLMOptimizer()
        self.chunk_id = 1
        self.page_num = 1
        self.content = "Test content"
        self.source_elements = ["paragraph"]
        self.expected_chunk_id = "chunk_0001"

    @pytest.mark.asyncio
    async def test_create_chunk_returns_llm_chunk_instance(self):
        """
        GIVEN valid content, chunk_id, page_num, and metadata
        WHEN _create_chunk is called
        THEN expect LLMChunk instance returned
        """
        # Given
        content = "This is a comprehensive paragraph containing multiple sentences for analysis."

        # When
        chunk = await self.optimizer._create_chunk(content, self.chunk_id, self.page_num, self.source_elements)
        
        # Then
        assert isinstance(chunk, LLMChunk), f"Should return LLMChunk instance, got {type(chunk).__name__}"

    @pytest.mark.asyncio
    async def test_create_chunk_sets_correct_chunk_id(self):
        """
        GIVEN valid parameters with chunk_id
        WHEN _create_chunk is called
        THEN expect chunk_id formatted correctly
        """
        # When
        chunk = await self.optimizer._create_chunk(self.content, self.chunk_id, self.page_num, self.source_elements)
        
        # Then
        assert chunk.chunk_id == self.expected_chunk_id, f"Expected chunk ID '{self.expected_chunk_id}', got '{chunk.chunk_id}'"

    @pytest.mark.asyncio
    async def test_create_chunk_preserves_content_exactly(self):
        """
        GIVEN content string
        WHEN _create_chunk is called
        THEN expect content preserved exactly
        """
        # Given
        content = "This is a comprehensive paragraph containing multiple sentences for analysis."

        # When
        chunk = await self.optimizer._create_chunk(content, self.chunk_id, self.page_num, self.source_elements)
        
        # Then
        assert chunk.content == content, f"Content should match input exactly\n===Expected===\n{content}\n===chunk.content===\n{chunk.content}"

    @pytest.mark.asyncio
    async def test_create_chunk_sets_correct_page_number(self):
        """
        GIVEN page_num parameter
        WHEN _create_chunk is called
        THEN expect source_page set correctly
        """
        # When
        chunk = await self.optimizer._create_chunk(self.content, self.chunk_id, self.page_num, self.source_elements)
        
        # Then
        assert chunk.source_page == self.page_num, f"Expected page number {self.page_num}, got {chunk.source_page}"

    @pytest.mark.asyncio
    async def test_create_chunk_token_count_is_integer(self):
        """
        GIVEN valid content
        WHEN _create_chunk is called
        THEN expect token_count is integer
        """
        # When
        chunk = await self.optimizer._create_chunk(self.content, self.chunk_id, self.page_num, self.source_elements)
        
        # Then
        assert isinstance(chunk.token_count, int), f"token_count must be integer, got {type(chunk.token_count).__name__}"

    @pytest.mark.asyncio
    async def test_create_chunk_token_count_is_positive(self):
        """
        GIVEN non-empty content
        WHEN _create_chunk is called
        THEN expect positive token count
        """
        # When
        chunk = await self.optimizer._create_chunk(self.content, self.chunk_id, self.page_num, self.source_elements)
        
        # Then
        assert chunk.token_count > 0, f"token_count must be positive for non-empty content, got {chunk.token_count}"

    @pytest.mark.asyncio
    async def test_create_chunk_token_count_is_reasonable(self):
        """
        GIVEN content with known word count
        WHEN _create_chunk is called
        THEN expect reasonable token count relative to word count
        """
        # Given
        content = "This is a comprehensive paragraph containing multiple sentences for analysis. " \
                 "It includes various elements such as technical terms, numerical references, " \
                 "and contextual information that would be typical in a research document."

        # When
        chunk = await self.optimizer._create_chunk(content, self.chunk_id, self.page_num, self.source_elements)
        
        # Then
        word_count = len(content.split())
        assert 30 <= chunk.token_count <= word_count * 2, f"token_count {chunk.token_count} seems unreasonable for {word_count} words"

    @pytest.mark.asyncio
    async def test_create_chunk_semantic_types_not_none(self):
        """
        GIVEN valid content
        WHEN _create_chunk is called
        THEN expect semantic_types is not None
        """
        # When
        chunk = await self.optimizer._create_chunk(self.content, self.chunk_id, self.page_num, self.source_elements)
        
        # Then
        assert chunk.semantic_types is not None, "Semantic type should be determined, but got None instead."

    @pytest.mark.asyncio
    async def test_create_chunk_semantic_types_is_string(self):
        """
        GIVEN valid content
        WHEN _create_chunk is called
        THEN expect semantic_types is string
        """
        # When
        chunk = await self.optimizer._create_chunk(self.content, self.chunk_id, self.page_num, self.source_elements)
        
        # Then
        assert isinstance(chunk.semantic_types, str), f"Semantic type should be string, got {type(chunk.semantic_types).__name__}"

    @pytest.mark.asyncio
    async def test_create_chunk_semantic_types_not_empty(self):
        """
        GIVEN valid content
        WHEN _create_chunk is called
        THEN expect semantic_types is not empty
        """
        # When
        chunk = await self.optimizer._create_chunk(self.content, self.chunk_id, self.page_num, self.source_elements)
        
        # Then
        assert len(chunk.semantic_types) > 0, f"Semantic type should not be empty (i.e. greater than 0), got {len(chunk.semantic_types)}"

    @pytest.mark.asyncio
    async def test_create_chunk_semantic_types_is_expected_value(self):
        """
        GIVEN paragraph content
        WHEN _create_chunk is called
        THEN expect semantic_types is appropriate for paragraph content
        """
        # Given
        content = "This is a paragraph of text content."

        # When
        chunk = await self.optimizer._create_chunk(content, self.chunk_id, self.page_num, self.source_elements)
        
        # Then
        expected_semantic_types = ["text", "paragraph", "header", "table", "figure", "caption"]
        assert chunk.semantic_types in expected_semantic_types, f"Unexpected semantic type '{chunk.semantic_types}'. Expected one of {expected_semantic_types}."

    @pytest.mark.asyncio
    async def test_create_chunk_source_elements_not_none(self):
        """
        GIVEN source_elements parameter
        WHEN _create_chunk is called
        THEN expect source_elements is not None
        """
        # When
        chunk = await self.optimizer._create_chunk(self.content, self.chunk_id, self.page_num, self.source_elements)
        
        # Then
        assert chunk.source_elements is not None, "Source element should be populated, got None instead."

    @pytest.mark.asyncio
    async def test_create_chunk_source_elements_is_list(self):
        """
        GIVEN source_elements parameter
        WHEN _create_chunk is called
        THEN expect source_elements is list
        """
        # When
        chunk = await self.optimizer._create_chunk(self.content, self.chunk_id, self.page_num, self.source_elements)
        
        # Then
        assert isinstance(chunk.source_elements, list), f"Source element should be a list, got {type(chunk.source_elements).__name__} instead."

    @pytest.mark.asyncio
    async def test_create_chunk_content_no_leading_whitespace(self):
        """
        GIVEN content that may have whitespace
        WHEN _create_chunk is called
        THEN expect content does not start with whitespace
        """
        # Given
        content = "Test content without leading space"

        # When
        chunk = await self.optimizer._create_chunk(content, self.chunk_id, self.page_num, self.source_elements)
        
        # Then
        assert not chunk.content.startswith(" "), "Content should not start with whitespace"

    @pytest.mark.asyncio
    async def test_create_chunk_content_no_trailing_whitespace(self):
        """
        GIVEN content that may have whitespace
        WHEN _create_chunk is called
        THEN expect content does not end with whitespace
        """
        # Given
        content = "Test content without trailing space"

        # When
        chunk = await self.optimizer._create_chunk(content, self.chunk_id, self.page_num, self.source_elements)
        
        # Then
        assert not chunk.content.endswith(" "), "Content should not end with whitespace"

    @pytest.mark.asyncio
    async def test_create_chunk_content_properly_trimmed(self):
        """
        GIVEN content
        WHEN _create_chunk is called
        THEN expect content is properly trimmed of whitespace
        """
        # Given
        content = "Test content that should be trimmed"

        # When
        chunk = await self.optimizer._create_chunk(content, self.chunk_id, self.page_num, self.source_elements)
        
        # Then
        assert len(chunk.content.strip()) == len(chunk.content), "Content should be properly trimmed"

    @pytest.mark.asyncio
    async def test_create_chunk_empty_string_raises_error(self):
        """
        GIVEN empty content string
        WHEN _create_chunk is called
        THEN expect ValueError to be raised
        """
        # Given
        empty_content = ""
        
        # When/Then
        with pytest.raises(ValueError):
            await self.optimizer._create_chunk(empty_content, self.expected_chunk_id, self.page_num, self.source_elements)

    @pytest.mark.asyncio
    async def test_create_chunk_whitespace_only_raises_error(self):
        """
        GIVEN content with only whitespace
        WHEN _create_chunk is called
        THEN expect ValueError to be raised
        """
        # Given
        whitespace_content = "   "
        
        # When/Then
        with pytest.raises(ValueError):
            await self.optimizer._create_chunk(whitespace_content, self.expected_chunk_id, self.page_num, self.source_elements)

    @pytest.mark.asyncio
    async def test_create_chunk_whitespace_characters_only_raises_error(self):
        """
        GIVEN content with only whitespace characters (newlines, tabs)
        WHEN _create_chunk is called
        THEN expect ValueError to be raised
        """
        # Given
        whitespace_chars_content = "\n\t  \n"
        
        # When/Then
        with pytest.raises(ValueError):
            await self.optimizer._create_chunk(whitespace_chars_content, self.expected_chunk_id, self.page_num, self.source_elements)

    @pytest.mark.asyncio
    async def test_create_chunk_none_content_raises_error(self):
        """
        GIVEN None as content
        WHEN _create_chunk is called
        THEN expect ValueError to be raised
        """
        # Given
        none_content = None
        
        # When/Then
        with pytest.raises(ValueError):
            await self.optimizer._create_chunk(none_content, self.expected_chunk_id, self.page_num, self.source_elements)

    @pytest.mark.asyncio
    async def test_create_chunk_empty_string_error_message_descriptive(self):
        """
        GIVEN empty content string
        WHEN _create_chunk is called
        THEN expect error message mentions empty content issue
        """
        # Given
        empty_content = ""
        
        # When/Then
        with pytest.raises(ValueError) as exc_info:
            await self.optimizer._create_chunk(empty_content, self.expected_chunk_id, self.page_num, self.source_elements)
        
        error_msg = str(exc_info.value).lower()
        assert any(keyword in error_msg for keyword in ["empty", "content", "whitespace", "invalid"]), \
            f"Error message should mention empty content issue: {exc_info.value}"

    @pytest.mark.asyncio
    async def test_create_chunk_none_content_error_message_descriptive(self):
        """
        GIVEN None as content
        WHEN _create_chunk is called
        THEN expect error message mentions None/null content issue
        """
        # Given
        none_content = None
        
        # When/Then
        with pytest.raises(ValueError) as exc_info:
            await self.optimizer._create_chunk(none_content, self.expected_chunk_id, self.page_num, self.source_elements)
        
        error_msg = str(exc_info.value).lower()
        assert any(keyword in error_msg for keyword in ["none", "null", "content", "empty"]), \
            f"Error message should mention None/empty content issue: {exc_info.value}"



class TestLLMOptimizerCreateChunkTypesDetermination:
    """Test LLMOptimizer._create_chunk semantic types determination."""

    def setup_method(self):
        """Common setup for semantic types determination tests."""
        self.optimizer = LLMOptimizer()
        self.page_num = 1

    @pytest.mark.asyncio
    async def test_create_chunk_header_semantic_type_classification(self):
        """
        GIVEN content with header metadata
        WHEN _create_chunk is called
        THEN expect semantic type classified as header
        """
        # Given
        content = "Chapter 1: Introduction to Machine Learning"
        source_elements = ["header"]
        
        # When
        chunk = await self.optimizer._create_chunk(content, 1, self.page_num, source_elements)
        
        # Then
        assert chunk.semantic_types == "header"

    @pytest.mark.asyncio
    async def test_create_chunk_table_semantic_type_classification(self):
        """
        GIVEN content with table metadata
        WHEN _create_chunk is called
        THEN expect semantic type classified as table
        """
        # Given
        content = "Table 1: Results\nMethod A: 95%\nMethod B: 87%\nMethod C: 92%"
        source_elements = ["table"]
        
        # When
        chunk = await self.optimizer._create_chunk(content, 1, self.page_num, source_elements)
        
        # Then
        assert chunk.semantic_types == "table"

    @pytest.mark.asyncio
    async def test_create_chunk_figure_caption_semantic_type_classification(self):
        """
        GIVEN content with figure caption metadata
        WHEN _create_chunk is called
        THEN expect semantic type classified as figure_caption
        """
        # Given
        content = "Figure 2: Neural network architecture showing input, hidden, and output layers."
        source_elements = ["figure_caption"]
        
        # When
        chunk = await self.optimizer._create_chunk(content, 1, self.page_num, source_elements)
        
        # Then
        assert chunk.semantic_types == "figure_caption"

    @pytest.mark.asyncio
    async def test_create_chunk_mixed_content_table_priority(self):
        """
        GIVEN content with mixed elements containing table
        WHEN _create_chunk is called
        THEN expect table type due to priority hierarchy
        """
        # Given
        content = "The following table shows results:\nMethod A: 95%\nMethod B: 87%\nThis demonstrates clear performance differences."
        source_elements = ["paragraph", "table"]
        
        # When
        chunk = await self.optimizer._create_chunk(content, 1, self.page_num, source_elements)
        
        # Then
        assert chunk.semantic_types == "table"

    @pytest.mark.asyncio
    async def test_create_chunk_mixed_content_classification(self):
        """
        GIVEN content with multiple non-priority elements
        WHEN _create_chunk is called
        THEN expect semantic type classified as mixed
        """
        # Given
        content = "This content contains a list:\n1. Item 1\n2. Item 2\nAnd also has footer information."
        source_elements = ["list", "footer"]
        
        # When
        chunk = await self.optimizer._create_chunk(content, 1, self.page_num, source_elements)
        
        # Then
        assert chunk.semantic_types == "mixed"

    @pytest.mark.asyncio
    async def test_create_chunk_paragraph_semantic_type_classification(self):
        """
        GIVEN content with paragraph metadata
        WHEN _create_chunk is called
        THEN expect semantic type classified as text
        """
        # Given
        content = "This is a standard paragraph containing narrative text without any special formatting or tabular data."
        source_elements = ["paragraph"]
        
        # When
        chunk = await self.optimizer._create_chunk(content, 1, self.page_num, source_elements)
        
        # Then
        assert chunk.semantic_types == "text"

    @pytest.mark.asyncio
    async def test_create_chunk_text_with_table_keywords_classified_as_text(self):
        """
        GIVEN paragraph content mentioning table keywords
        WHEN _create_chunk is called
        THEN expect semantic type classified as text
        """
        # Given
        content = "The research table of contents includes methodology, results, and discussion sections."
        source_elements = ["paragraph"]
        
        # When
        chunk = await self.optimizer._create_chunk(content, 1, self.page_num, source_elements)
        
        # Then
        assert chunk.semantic_types == "text"

    @pytest.mark.asyncio
    async def test_create_chunk_text_with_header_keywords_classified_as_text(self):
        """
        GIVEN paragraph content mentioning header keywords
        WHEN _create_chunk is called
        THEN expect semantic type classified as text
        """
        # Given
        content = "The chapter discusses various header compression techniques used in network protocols."
        source_elements = ["paragraph"]
        
        # When
        chunk = await self.optimizer._create_chunk(content, 1, self.page_num, source_elements)
        
        # Then
        assert chunk.semantic_types == "text"

    @pytest.mark.asyncio
    async def test_create_chunk_header_priority_over_table(self):
        """
        GIVEN content with both header and table elements
        WHEN _create_chunk is called
        THEN expect header type due to priority hierarchy
        """
        # Given
        content = "Chapter 1: Results Table\nMethod A: 95%\nMethod B: 87%"
        source_elements = ["header", "table"]
        
        # When
        chunk = await self.optimizer._create_chunk(content, 1, self.page_num, source_elements)
        
        # Then
        assert chunk.semantic_types == "header"

    @pytest.mark.asyncio
    async def test_create_chunk_table_priority_over_figure_caption(self):
        """
        GIVEN content with both table and figure caption elements
        WHEN _create_chunk is called
        THEN expect table type due to priority hierarchy
        """
        # Given
        content = "Table 1: Performance metrics (see Figure 2)\nMethod A: 95%\nMethod B: 87%"
        source_elements = ["table", "figure_caption"]
        
        # When
        chunk = await self.optimizer._create_chunk(content, 1, self.page_num, source_elements)
        
        # Then
        assert chunk.semantic_types == "table"

    @pytest.mark.asyncio
    async def test_create_chunk_table_priority_over_figure_caption_in_content(self):
        """
        GIVEN figure caption content with table data
        WHEN _create_chunk is called
        THEN expect table type due to priority hierarchy
        """
        # Given
        content = "Figure 1: Data table showing Method A: 95%, Method B: 87%"
        source_elements = ["figure_caption", "table"]
        
        # When
        chunk = await self.optimizer._create_chunk(content, 1, self.page_num, source_elements)
        
        # Then
        assert chunk.semantic_types == "table"

    @pytest.mark.asyncio
    async def test_create_chunk_markdown_headers_content_based_classification(self):
        """
        GIVEN markdown-style header content without metadata
        WHEN _create_chunk is called
        THEN expect semantic type in expected range
        """
        # Given
        content = "# Introduction\n## Overview\nThis section provides an introduction."
        source_elements = ["text"]
        possible_types = ["header", "text", "mixed"]
        
        # When
        chunk = await self.optimizer._create_chunk(content, 1, self.page_num, source_elements)
        
        # Then
        assert chunk.semantic_types in possible_types

    @pytest.mark.asyncio
    async def test_create_chunk_markdown_table_content_based_classification(self):
        """
        GIVEN markdown table content without metadata
        WHEN _create_chunk is called
        THEN expect semantic type in expected range
        """
        # Given
        content = "| Column A | Column B |\n|----------|----------|\n| Value 1  | Value 2  |"
        source_elements = ["text"]
        possible_types = ["table", "mixed", "text"]
        
        # When
        chunk = await self.optimizer._create_chunk(content, 1, self.page_num, source_elements)
        
        # Then
        assert chunk.semantic_types in possible_types

    @pytest.mark.asyncio
    async def test_create_chunk_figure_caption_content_based_classification(self):
        """
        GIVEN figure caption format content without metadata
        WHEN _create_chunk is called
        THEN expect semantic type in expected range
        """
        # Given
        content = "Figure 1: This image shows the relationship between variables X and Y."
        source_elements = ["text"]
        possible_types = ["figure_caption", "text"]
        
        # When
        chunk = await self.optimizer._create_chunk(content, 1, self.page_num, source_elements)
        
        # Then
        assert chunk.semantic_types in possible_types

    @pytest.mark.asyncio
    async def test_create_chunk_unknown_element_type_fallback(self):
        """
        GIVEN content with unknown element type
        WHEN _create_chunk is called
        THEN expect fallback to text type
        """
        # Given
        content = "Valid content"
        source_elements = ["unknown_type"]
        
        # When
        chunk = await self.optimizer._create_chunk(content, 1, self.page_num, source_elements)
        
        # Then
        assert chunk.semantic_types == "text"

    @pytest.mark.asyncio
    async def test_create_chunk_multiple_semantic_indicators_classification(self):
        """
        GIVEN content with multiple semantic indicators
        WHEN _create_chunk is called
        THEN expect semantic type in expected range
        """
        # Given
        content = "Mixed content with Table: data and Figure: reference"
        source_elements = ["text", "list"]
        possible_types = ["mixed", "text"]
        
        # When
        chunk = await self.optimizer._create_chunk(content, 1, self.page_num, source_elements)
        
        # Then
        assert chunk.semantic_types in possible_types

    @pytest.mark.asyncio
    async def test_create_chunk_semantic_type_consistency_table_1(self):
        """
        GIVEN first table content
        WHEN _create_chunk is called
        THEN expect consistent table classification
        """
        # Given
        content = "Table 1: Research Results"
        source_elements = ["table"]
        
        # When
        chunk = await self.optimizer._create_chunk(content, 1, self.page_num, source_elements)
        
        # Then
        assert chunk.semantic_types == "table"

    @pytest.mark.asyncio
    async def test_create_chunk_semantic_type_consistency_table_2(self):
        """
        GIVEN second similar table content
        WHEN _create_chunk is called
        THEN expect consistent table classification
        """
        # Given
        content = "Table 2: Additional Results"
        source_elements = ["table"]
        
        # When
        chunk = await self.optimizer._create_chunk(content, 2, self.page_num, source_elements)
        
        # Then
        assert chunk.semantic_types == "table"

    @pytest.mark.asyncio
    async def test_create_chunk_semantic_types_is_string(self):
        """
        GIVEN any valid content
        WHEN _create_chunk is called
        THEN expect semantic_types to be string type
        """
        # Given
        content = "Test content"
        source_elements = ["paragraph"]
        
        # When
        chunk = await self.optimizer._create_chunk(content, 1, self.page_num, source_elements)
        
        # Then
        assert isinstance(chunk.semantic_types, str)

    @pytest.mark.asyncio
    async def test_create_chunk_semantic_types_not_empty(self):
        """
        GIVEN any valid content
        WHEN _create_chunk is called
        THEN expect semantic_types to not be empty
        """
        # Given
        content = "Test content"
        source_elements = ["paragraph"]
        
        # When
        chunk = await self.optimizer._create_chunk(content, 1, self.page_num, source_elements)
        
        # Then
        assert len(chunk.semantic_types) > 0

    @pytest.mark.asyncio
    async def test_create_chunk_has_semantic_types_attribute(self):
        """
        GIVEN any valid content
        WHEN _create_chunk is called
        THEN expect chunk to have semantic_types attribute
        """
        # Given
        content = "Test content"
        source_elements = ["paragraph"]
        
        # When
        chunk = await self.optimizer._create_chunk(content, 1, self.page_num, source_elements)
        
        # Then
        assert hasattr(chunk, 'semantic_types')

    @pytest.mark.asyncio
    async def test_create_chunk_returns_llm_chunk_for_semantic_classification(self):
        """
        GIVEN any valid content for semantic classification
        WHEN _create_chunk is called
        THEN expect LLMChunk instance returned
        """
        # Given
        content = "Test content for semantic classification"
        source_elements = ["paragraph"]
        
        # When
        chunk = await self.optimizer._create_chunk(content, 1, self.page_num, source_elements)
        
        # Then
        assert isinstance(chunk, LLMChunk)


class TestLLMOptimizerCreateChunkIdFormatting:

    def setup_method(self):
        """Common setup for chunk ID formatting tests."""
        self.optimizer = LLMOptimizer()
        self.content = "Test content for chunk ID formatting validation"
        self.page_num = 1
        self.source_elements = ["paragraph"]

    @pytest.mark.asyncio
    async def test_create_chunk_id_is_string_type(self):
        """
        GIVEN any valid chunk_id (integer)
        WHEN _create_chunk is called
        THEN expect chunk.chunk_id to be string type
        """
        # Given
        chunk_id = 1
        
        # When
        chunk = await self.optimizer._create_chunk(self.content, chunk_id, self.page_num, self.source_elements)
        
        # Then
        assert isinstance(chunk.chunk_id, str)

    @pytest.mark.asyncio
    async def test_create_chunk_id_is_not_empty(self):
        """
        GIVEN any valid chunk_id (integer)
        WHEN _create_chunk is called
        THEN expect chunk.chunk_id to not be empty
        """
        # Given
        chunk_id = 1
        
        # When
        chunk = await self.optimizer._create_chunk(self.content, chunk_id, self.page_num, self.source_elements)
        
        # Then
        assert len(chunk.chunk_id) > 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("chunk_id,expected", [
        (1, "chunk_0001"),
        (42, "chunk_0042"), 
        (1000, "chunk_1000"),
        (0, "chunk_0000"),
        (99999, "chunk_99999")
    ])
    async def test_create_chunk_formats_id_correctly(self, chunk_id, expected):
        """
        GIVEN various integer chunk_ids
        WHEN _create_chunk is called
        THEN expect chunk.chunk_id formatted correctly
        """
        # When
        chunk = await self.optimizer._create_chunk(self.content, chunk_id, self.page_num, self.source_elements)
        
        # Then
        assert chunk.chunk_id == expected

    @pytest.mark.asyncio
    async def test_create_chunk_ids_remain_unique(self):
        """
        GIVEN multiple different chunk_ids (integers)
        WHEN _create_chunk is called for each
        THEN expect all chunk.chunk_ids to remain unique
        """
        # Given
        chunk_ids = [1, 2, 3]
        chunks = []
        
        # When
        for chunk_id in chunk_ids:
            chunk = await self.optimizer._create_chunk(self.content, chunk_id, self.page_num, self.source_elements)
            chunks.append(chunk)
        
        # Then
        actual_chunk_ids = [chunk.chunk_id for chunk in chunks]
        assert len(actual_chunk_ids) == len(set(actual_chunk_ids))

    @pytest.mark.asyncio
    async def test_create_chunk_id_consistency_across_calls(self):
        """
        GIVEN same chunk_id (integer) used multiple times
        WHEN _create_chunk is called multiple times
        THEN expect chunk.chunk_id to be consistent across calls
        """
        # Given
        chunk_id = 42
        
        # When
        chunk1 = await self.optimizer._create_chunk(self.content, chunk_id, self.page_num, self.source_elements)
        chunk2 = await self.optimizer._create_chunk(self.content, chunk_id, self.page_num, self.source_elements)
        
        # Then
        assert chunk1.chunk_id == chunk2.chunk_id

    @pytest.mark.asyncio
    async def test_create_chunk_zero_id_formatted_correctly(self):
        """
        GIVEN chunk_id of 0
        WHEN _create_chunk is called
        THEN expect chunk.chunk_id formatted correctly
        """
        # Given
        chunk_id = 0
        
        # When
        chunk = await self.optimizer._create_chunk(self.content, chunk_id, self.page_num, self.source_elements)
        
        # Then
        assert chunk.chunk_id == "chunk_0000"

    @pytest.mark.asyncio
    async def test_create_chunk_large_id_formatted_correctly(self):
        """
        GIVEN large chunk_id
        WHEN _create_chunk is called
        THEN expect chunk.chunk_id formatted correctly
        """
        # Given
        chunk_id = 123456
        
        # When
        chunk = await self.optimizer._create_chunk(self.content, chunk_id, self.page_num, self.source_elements)
        
        # Then
        assert chunk.chunk_id == "chunk_123456"

    @pytest.mark.asyncio
    async def test_create_chunk_negative_id_raises_error(self):
        """
        GIVEN negative chunk_id
        WHEN _create_chunk is called
        THEN expect ValueError to be raised
        """
        # Given
        chunk_id = -1
        
        # When/Then
        with pytest.raises(ValueError):
            await self.optimizer._create_chunk(self.content, chunk_id, self.page_num, self.source_elements)

    @pytest.mark.asyncio
    async def test_create_chunk_id_appears_in_string_representation(self):
        """
        GIVEN any valid chunk_id (integer)
        WHEN _create_chunk is called
        THEN expect formatted chunk_id to appear in string representation
        """
        # Given
        chunk_id = 1
        
        # When
        chunk = await self.optimizer._create_chunk(self.content, chunk_id, self.page_num, self.source_elements)
        
        # Then
        chunk_str = str(chunk)
        assert chunk.chunk_id in chunk_str

    @pytest.mark.asyncio
    async def test_create_chunk_id_appears_in_repr_representation(self):
        """
        GIVEN any valid chunk_id (integer)
        WHEN _create_chunk is called
        THEN expect formatted chunk_id to appear in repr representation
        """
        # Given
        chunk_id = 1
        
        # When
        chunk = await self.optimizer._create_chunk(self.content, chunk_id, self.page_num, self.source_elements)
        
        # Then
        chunk_repr = repr(chunk)
        assert chunk.chunk_id in chunk_repr

    @pytest.mark.asyncio
    async def test_create_chunk_string_id_raises_error(self):
        """
        GIVEN string chunk_id
        WHEN _create_chunk is called
        THEN expect TypeError to be raised
        """
        # Given
        chunk_id = "chunk_0001"
        
        # When/Then
        with pytest.raises(TypeError):
            await self.optimizer._create_chunk(self.content, chunk_id, self.page_num, self.source_elements)

    @pytest.mark.asyncio
    async def test_create_chunk_none_id_raises_error(self):
        """
        GIVEN None chunk_id
        WHEN _create_chunk is called
        THEN expect TypeError raised
        """
        # Given
        chunk_id = None
        
        # When/Then
        with pytest.raises(TypeError):
            await self.optimizer._create_chunk(self.content, chunk_id, self.page_num, self.source_elements)


class TestLLMOptimizerCreateChunkMetadataEnhancement:

    def setup_method(self):
        """Common setup for metadata enhancement tests."""
        self.optimizer = LLMOptimizer()
        self.base_content = "Test content for metadata validation"
        self.chunk_id = 1
        self.page_num = 1
        self.source_elements = ["paragraph"]

    @pytest.mark.asyncio
    async def test_create_chunk_metadata_returns_llm_chunk_metadata(self):
        """
        GIVEN basic content
        WHEN _create_chunk is called
        THEN expect metadata to be LLMChunkMetadata instance
        """
        # When
        chunk = await self.optimizer._create_chunk(
            self.base_content, self.chunk_id, self.page_num, self.source_elements
        )
        
        # Then
        assert isinstance(chunk.metadata, LLMChunkMetadata), \
            f"metadata should be LLMChunkMetadata, got {type(chunk.metadata).__name__}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("field_name", [
        "creation_timestamp",
        "word_count", 
        "character_count",
        "processing_method",
        "tokenizer_used",
        "token_count"
    ])
    async def test_create_chunk_metadata_contains_required_fields(self, field_name):
        """
        GIVEN basic content
        WHEN _create_chunk is called
        THEN expect required metadata fields to be present
        """
        # When
        chunk = await self.optimizer._create_chunk(
            self.base_content, self.chunk_id, self.page_num, self.source_elements
        )
        
        # Then
        assert hasattr(chunk.metadata, field_name), \
            f"{field_name} field should be present in metadata"

    @pytest.mark.asyncio
    async def test_create_chunk_metadata_timestamp_is_float(self):
        """
        GIVEN basic content
        WHEN _create_chunk is called
        THEN expect creation_timestamp field to be a float
        """
        # When
        chunk = await self.optimizer._create_chunk(
            self.base_content, self.chunk_id, self.page_num, self.source_elements
        )
        
        # Then
        timestamp_value = chunk.metadata.creation_timestamp
        assert isinstance(timestamp_value, float), f"Timestamp should be float, got {type(timestamp_value)}"

    @pytest.mark.asyncio
    async def test_create_chunk_metadata_timestamp_within_processing_window(self):
        """
        GIVEN basic content
        WHEN _create_chunk is called
        THEN expect creation_timestamp to be within processing time window
        """
        # Given
        before_creation = time.time()
        
        # When
        chunk = await self.optimizer._create_chunk(
            self.base_content, self.chunk_id, self.page_num, self.source_elements
        )
        
        # Then
        after_creation = time.time()
        timestamp_value = chunk.metadata.creation_timestamp
        assert before_creation <= timestamp_value <= after_creation, \
            f"Timestamp is outside processing window: {timestamp_value} not in [{before_creation}, {after_creation}]"

    @pytest.mark.asyncio
    async def test_create_chunk_metadata_word_count_is_integer(self):
        """
        GIVEN basic content
        WHEN _create_chunk is called
        THEN expect word_count field to be integer
        """
        # When
        chunk = await self.optimizer._create_chunk(
            self.base_content, self.chunk_id, self.page_num, self.source_elements
        )
        
        # Then
        count_value = chunk.metadata.word_count
        assert isinstance(count_value, int), f"word_count field should be integer, got {type(count_value)}"

    @pytest.mark.asyncio
    async def test_create_chunk_metadata_word_count_non_negative(self):
        """
        GIVEN basic content
        WHEN _create_chunk is called
        THEN expect word_count field to be non-negative
        """
        # When
        chunk = await self.optimizer._create_chunk(
            self.base_content, self.chunk_id, self.page_num, self.source_elements
        )
        
        # Then
        count_value = chunk.metadata.word_count
        assert count_value >= 0, f"word_count field should be non-negative, got {count_value}"

    @pytest.mark.asyncio
    async def test_create_chunk_metadata_word_count_accurate(self):
        """
        GIVEN content with known word count
        WHEN _create_chunk is called
        THEN expect word_count metadata to be accurate
        """
        # Given
        content = "This content has exactly seven distinct words here"
        actual_word_count = len(content.split())
        
        # When
        chunk = await self.optimizer._create_chunk(
            content, self.chunk_id, self.page_num, self.source_elements
        )
        
        # Then
        assert chunk.metadata.word_count == actual_word_count, \
            f"Word count mismatch: expected {actual_word_count}, got {chunk.metadata.word_count}"

    @pytest.mark.asyncio
    async def test_create_chunk_metadata_character_count_accurate(self):
        """
        GIVEN content with known character count
        WHEN _create_chunk is called
        THEN expect character_count metadata to be accurate
        """
        # Given
        content = "Test content for character counting"
        actual_char_count = len(content)
        
        # When
        chunk = await self.optimizer._create_chunk(
            content, self.chunk_id, self.page_num, self.source_elements
        )
        
        # Then
        assert chunk.metadata.character_count == actual_char_count, \
            f"Character count mismatch: expected {actual_char_count}, got {chunk.metadata.character_count}"

    @pytest.mark.asyncio
    async def test_create_chunk_metadata_processing_method_is_string(self):
        """
        GIVEN basic content
        WHEN _create_chunk is called
        THEN expect processing_method field to be string
        """
        # When
        chunk = await self.optimizer._create_chunk(
            self.base_content, self.chunk_id, self.page_num, self.source_elements
        )
        
        # Then
        processing_value = chunk.metadata.processing_method
        assert isinstance(processing_value, str), f"processing_method field should be string, got {type(processing_value)}"

    @pytest.mark.asyncio
    async def test_create_chunk_metadata_processing_method_not_empty(self):
        """
        GIVEN basic content
        WHEN _create_chunk is called
        THEN expect processing_method field to be non-empty
        """
        # When
        chunk = await self.optimizer._create_chunk(
            self.base_content, self.chunk_id, self.page_num, self.source_elements
        )
        
        # Then
        processing_value = chunk.metadata.processing_method
        assert len(processing_value) > 0, f"processing_method field should not be empty"

    @pytest.mark.asyncio
    async def test_create_chunk_metadata_tokenizer_field_valid(self):
        """
        GIVEN basic content
        WHEN _create_chunk is called
        THEN expect tokenizer_used field to contain recognized tokenizer
        """
        # When
        chunk = await self.optimizer._create_chunk(
            self.base_content, self.chunk_id, self.page_num, self.source_elements
        )
        
        # Then
        processing_value = chunk.metadata.tokenizer_used
        expected_tokenizers = ["gpt-3.5-turbo", "gpt-4", "tiktoken", "transformers"]
        assert any(tokenizer in processing_value for tokenizer in expected_tokenizers), \
            f"Tokenizer field should contain recognized tokenizer: {processing_value}"

    @pytest.mark.asyncio
    async def test_create_chunk_metadata_processing_method_valid(self):
        """
        GIVEN basic content
        WHEN _create_chunk is called
        THEN expect processing_method field to contain recognized method
        """
        # When
        chunk = await self.optimizer._create_chunk(
            self.base_content, self.chunk_id, self.page_num, self.source_elements
        )
        
        # Then
        processing_value = chunk.metadata.processing_method
        expected_methods = ["llm_optimization", "text_chunking", "semantic_analysis"]
        assert any(method in processing_value for method in expected_methods), \
            f"Processing method should be recognized: {processing_value}"

    @pytest.mark.asyncio
    async def test_create_chunk_metadata_token_count_matches_attribute(self):
        """
        GIVEN basic content
        WHEN _create_chunk is called
        THEN expect metadata token_count to match chunk.token_count attribute
        """
        # When
        chunk = await self.optimizer._create_chunk(
            self.base_content, self.chunk_id, self.page_num, self.source_elements
        )
        
        # Then
        assert chunk.metadata.token_count == chunk.token_count, \
            f"Metadata token_count should match chunk.token_count: metadata={chunk.metadata.token_count}, attribute={chunk.token_count}"

    @pytest.mark.asyncio
    async def test_create_chunk_metadata_semantic_types_matches_attribute(self):
        """
        GIVEN basic content
        WHEN _create_chunk is called
        THEN expect metadata semantic_types to match chunk.semantic_types attribute
        """
        # When
        chunk = await self.optimizer._create_chunk(
            self.base_content, self.chunk_id, self.page_num, self.source_elements
        )
        
        # Then
        assert chunk.metadata.semantic_type == chunk.semantic_types, \
            f"Metadata semantic_types should match chunk.semantic_types: metadata={chunk.metadata.semantic_type}, attribute={chunk.semantic_types}"

    @pytest.mark.asyncio
    async def test_create_chunk_metadata_size_reasonable(self):
        """
        GIVEN basic content
        WHEN _create_chunk is called
        THEN expect metadata size to be reasonable (not excessively large)
        """
        # When
        MAX_SIZE = 10000
        chunk = await self.optimizer._create_chunk(
            self.base_content, self.chunk_id, self.page_num, self.source_elements
        )
        
        # Then
        metadata_size = len(str(chunk.metadata))
        assert metadata_size < MAX_SIZE, \
            f"Enhanced metadata should be reasonable size, got {metadata_size} characters"

    @pytest.mark.asyncio
    async def test_create_chunk_metadata_enhancement_consistent_across_chunks(self):
        """
        GIVEN multiple chunks created
        WHEN _create_chunk is called for each
        THEN expect consistent enhancement patterns across chunks
        """
        # When
        chunk1 = await self.optimizer._create_chunk(
            "First test content",
            1,
            1,
            ["paragraph"]
        )
        
        chunk2 = await self.optimizer._create_chunk(
            "Second test content",
            2,
            1,
            ["paragraph"]
        )
        
        # Then
        # Compare the fields present in both metadata instances
        chunk1_fields = set(chunk1.metadata.__dict__.keys())
        chunk2_fields = set(chunk2.metadata.__dict__.keys())
        
        common_fields = chunk1_fields.intersection(chunk2_fields)
        assert len(common_fields) >= len(chunk1_fields) * 0.7, \
            f"Chunks should have consistent enhancement patterns: {chunk1_fields} " \
            f"vs {chunk2_fields}"

    @pytest.mark.asyncio
    async def test_create_chunk_metadata_enhances_minimal_input(self):
        """
        GIVEN minimal metadata input
        WHEN _create_chunk is called
        THEN expect metadata to be enhanced even with minimal input
        """
        # Given
        content = "Test content with minimal metadata"
        chunk_id = 1
        
        # When
        chunk = await self.optimizer._create_chunk(content, chunk_id, self.page_num, self.source_elements)
        
        # Then
        # Should have metadata fields beyond the basic LLMChunk attributes
        metadata_fields = set(chunk.metadata.__dict__.keys())
        
        # Basic fields that might be in metadata
        basic_expected_fields = {"chunk_id", "content", "source_page", "token_count", "semantic_types", "source_elements"}
        enhanced_fields = metadata_fields - basic_expected_fields
        
        assert len(enhanced_fields) > 0, \
            f"enhanced_fields = metadata_fields - basic_expected_fields " \
            f"should be greater than 0, got {len(enhanced_fields)}"



class TestCreateChunkTokenCountingFailure:
    """Tests for _create_chunk method handling token counting failures."""

    def setup_method(self):
        """Setup optimizer and test data."""
        self.optimizer = LLMOptimizer()
        self.content = "This is valid content that should normally count tokens correctly."
        self.chunk_id = 1
        self.page_num = 1
        self.source_elements = ["paragraph"]

    @pytest.mark.asyncio
    async def test_token_counting_exception_returns_llm_chunk(self):
        """GIVEN token counting raises exception WHEN _create_chunk called THEN return LLMChunk."""
        with unittest.mock.patch.object(self.optimizer, '_count_tokens', side_effect=Exception("Token counting failed")):
            chunk = await self.optimizer._create_chunk(self.content, self.chunk_id, self.page_num, self.source_elements)
            assert isinstance(chunk, LLMChunk), f"Expected LLMChunk, got {type(chunk)}"

    @pytest.mark.asyncio
    async def test_token_counting_exception_preserves_content(self):
        """GIVEN token counting raises exception WHEN _create_chunk called THEN preserve content."""
        with unittest.mock.patch.object(self.optimizer, '_count_tokens', side_effect=Exception("Token counting failed")):
            chunk = await self.optimizer._create_chunk(self.content, self.chunk_id, self.page_num, self.source_elements)
            assert chunk.content == self.content, f"Expected content '{self.content}', got '{chunk.content}'"

    @pytest.mark.asyncio
    async def test_token_counting_exception_preserves_chunk_id(self):
        """GIVEN token counting raises exception WHEN _create_chunk called THEN preserve chunk_id."""
        with unittest.mock.patch.object(self.optimizer, '_count_tokens', side_effect=Exception("Token counting failed")):
            chunk = await self.optimizer._create_chunk(self.content, self.chunk_id, self.page_num, self.source_elements)
            assert chunk.chunk_id == "chunk_0001", f"Expected chunk_id 'chunk_0001', got '{chunk.chunk_id}'"

    @pytest.mark.asyncio
    async def test_token_counting_exception_provides_integer_token_count(self):
        """GIVEN token counting raises exception WHEN _create_chunk called THEN token_count is integer."""
        with unittest.mock.patch.object(self.optimizer, '_count_tokens', side_effect=Exception("Token counting failed")):
            chunk = await self.optimizer._create_chunk(self.content, self.chunk_id, self.page_num, self.source_elements)
            assert isinstance(chunk.token_count, int), f"Expected int token_count, got {type(chunk.token_count)} with value {chunk.token_count}"

    @pytest.mark.asyncio
    async def test_token_counting_exception_provides_positive_token_count(self):
        """GIVEN token counting raises exception WHEN _create_chunk called THEN token_count is positive."""
        with unittest.mock.patch.object(self.optimizer, '_count_tokens', side_effect=Exception("Token counting failed")):
            chunk = await self.optimizer._create_chunk(self.content, self.chunk_id, self.page_num, self.source_elements)
            assert chunk.token_count > 0, f"Expected positive token_count, got {chunk.token_count}"

    @pytest.mark.asyncio
    async def test_token_counting_exception_provides_bounded_fallback(self):
        """
        GIVEN token counting raises exception 
        WHEN _create_chunk called 
        THEN fallback is 1 <= count <= max(3*words, chars).
        """
        with unittest.mock.patch.object(self.optimizer, '_count_tokens', side_effect=Exception("Token counting failed")):
            chunk = await self.optimizer._create_chunk(self.content, self.chunk_id, self.page_num, self.source_elements)
            word_count = len(self.content.split())
            char_count = len(self.content)
            upper_bound = max(word_count * 3, char_count)
            assert 1 <= chunk.token_count <= upper_bound, f"Expected 1 <= {chunk.token_count} <= {upper_bound} (words={word_count}, chars={char_count})"

    @pytest.mark.asyncio
    async def test_none_token_count_raises_error(self):
        """GIVEN token counting returns None WHEN _create_chunk called THEN raise error."""
        with unittest.mock.patch.object(self.optimizer, '_count_tokens', return_value=None):
            with pytest.raises(RuntimeError):
                await self.optimizer._create_chunk(self.content, self.chunk_id, self.page_num, self.source_elements)

    @pytest.mark.asyncio
    async def test_negative_token_count_raises_error(self):
        """GIVEN token counting returns negative WHEN _create_chunk called THEN raise error."""
        with unittest.mock.patch.object(self.optimizer, '_count_tokens', return_value=-1):
            with pytest.raises(RuntimeError):
                await self.optimizer._create_chunk(self.content, self.chunk_id, self.page_num, self.source_elements)

    @pytest.mark.asyncio
    async def test_string_token_count_raises_error(self):
        """GIVEN token counting returns string WHEN _create_chunk called THEN raise error."""
        with unittest.mock.patch.object(self.optimizer, '_count_tokens', return_value="invalid"):
            with pytest.raises((ValueError, TypeError)):
                await self.optimizer._create_chunk(self.content, self.chunk_id, self.page_num, self.source_elements)

    @pytest.mark.asyncio
    async def test_unicode_content_returns_llm_chunk(self):
        """GIVEN unicode content WHEN _create_chunk called THEN return LLMChunk."""
        content = "Content with unicode: 你好世界 🌍 αβγ"
        chunk = await self.optimizer._create_chunk(content, self.chunk_id, self.page_num, self.source_elements)
        assert isinstance(chunk, LLMChunk), f"Expected LLMChunk for unicode content, got {type(chunk)}"

    @pytest.mark.asyncio
    async def test_unicode_content_preserves_exact_content(self):
        """GIVEN unicode content WHEN _create_chunk called THEN preserve content with no character changes."""
        content = "Content with unicode: 你好世界 🌍 αβγ"
        chunk = await self.optimizer._create_chunk(content, self.chunk_id, self.page_num, self.source_elements)
        assert chunk.content == content, f"Expected exact unicode content '{content}', got '{chunk.content}'"

    @pytest.mark.asyncio
    async def test_emoji_content_provides_zero_or_positive_token_count(self):
        """GIVEN emoji content WHEN _create_chunk called THEN token_count >= 0."""
        content = "Content with emoji: 😀🎉🔥💯"
        chunk = await self.optimizer._create_chunk(content, self.chunk_id, self.page_num, self.source_elements)
        assert chunk.token_count >= 0, f"Expected token_count >= 0 for emoji content, got {chunk.token_count}"

    @pytest.mark.asyncio
    async def test_very_long_token_returns_integer_count(self):
        """GIVEN 1000+ character word WHEN _create_chunk called THEN return integer token_count."""
        content = "Content with very long word: " + "x" * 1000
        chunk = await self.optimizer._create_chunk(content, self.chunk_id, self.page_num, self.source_elements)
        assert isinstance(chunk.token_count, int), f"Expected int token_count for 1000+ char word, got {type(chunk.token_count)} with value {chunk.token_count}"

    @pytest.mark.asyncio
    async def test_whitespace_heavy_content_returns_zero_or_positive_count(self):
        """GIVEN content with leading/trailing whitespace WHEN _create_chunk called THEN token_count >= 0."""
        content = "\n\t\r   Whitespace heavy content   \n\t\r"
        chunk = await self.optimizer._create_chunk(content, self.chunk_id, self.page_num, self.source_elements)
        assert chunk.token_count >= 0, f"Expected token_count >= 0 for whitespace content, got {chunk.token_count}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
