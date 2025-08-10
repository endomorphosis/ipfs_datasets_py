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



class TestLLMOptimizerCreateOptimalChunksValidInput:
    """Test LLMOptimizer._create_optimal_chunks method."""

    def setup_method(self):
        self.optimizer = LLMOptimizer()

    @property
    def valid_structured_text(self):
        # Valid structured text
        structured_text = {
            "pages": [
                {
                    "page_number": 1,
                    "elements": [
                        {
                            "type": "paragraph",
                            "content": "This is the first paragraph with substantial content for chunking analysis. It contains multiple sentences to demonstrate proper segmentation and processing capabilities.",
                            "metadata": {"element_id": "p1"}
                        },
                        {
                            "type": "paragraph", 
                            "content": "This is the second paragraph that continues the document narrative. It provides additional context and information for comprehensive content processing.",
                            "metadata": {"element_id": "p2"}
                        }
                    ],
                    "full_text": "Combined content for page analysis and processing."
                }
            ]
        }
        return structured_text

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_returns_list(self):
        """
        GIVEN valid structured_text
        WHEN _create_optimal_chunks is called
        THEN expect list returned
        """
        # When
        chunks = await self.optimizer._create_optimal_chunks(self.valid_structured_text)
        
        # Then
        assert isinstance(chunks, list), f"Should return list of chunks, got {type(chunks).__name__}"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_creates_chunks(self):
        """
        GIVEN valid structured_text
        WHEN _create_optimal_chunks is called
        THEN expect at least one chunk created
        """
        # When
        chunks = await self.optimizer._create_optimal_chunks(self.valid_structured_text)
        
        # Then
        assert len(chunks) > 0, "Should create at least one chunk for valid content"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_returns_llm_chunk_instances(self):
        """
        GIVEN valid structured_text
        WHEN _create_optimal_chunks is called
        THEN expect all items are LLMChunk instances
        """
        # When
        chunks = await self.optimizer._create_optimal_chunks(self.valid_structured_text)
        
        # Then
        for chunk in chunks:
            assert isinstance(chunk, LLMChunk), \
                f"All items should be LLMChunk instances, got {type(chunk)}"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_respects_max_token_limits(self):
        """
        GIVEN valid structured_text
        WHEN _create_optimal_chunks is called
        THEN expect all chunks respect maximum token limits
        """
        # When
        chunks = await self.optimizer._create_optimal_chunks(self.valid_structured_text)
        
        # Then
        for i, chunk in enumerate(chunks):
            assert chunk.token_count <= self.optimizer.max_chunk_size, \
                f"Chunk {i} exceeds max size: {chunk.token_count} > {self.optimizer.max_chunk_size}"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_respects_min_token_limits_or_single_chunk(self):
        """
        GIVEN valid structured_text
        WHEN _create_optimal_chunks is called
        THEN expect all chunks respect minimum token limits or only one chunk exists
        """
        # When
        chunks = await self.optimizer._create_optimal_chunks(self.valid_structured_text)
        
        # Then
        for i, chunk in enumerate(chunks):
            assert chunk.token_count >= self.optimizer.min_chunk_size or len(chunks) == 1, f"Chunk {i} below min size: {chunk.token_count} < {self.optimizer.min_chunk_size}"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_content_is_string(self):
        """
        GIVEN valid structured_text
        WHEN _create_optimal_chunks is called
        THEN expect all chunk content is string type
        """
        # When
        chunks = await self.optimizer._create_optimal_chunks(self.valid_structured_text)
        
        # Then
        for i, chunk in enumerate(chunks):
            assert isinstance(chunk.content, str), f"Chunk {i} content should be string"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_content_not_empty(self):
        """
        GIVEN valid structured_text
        WHEN _create_optimal_chunks is called
        THEN expect all chunks have non-empty content
        """
        # When
        chunks = await self.optimizer._create_optimal_chunks(self.valid_structured_text)
        
        # Then
        for i, chunk in enumerate(chunks):
            assert len(chunk.content.strip()) > 0, f"Chunk {i} should have non-empty content"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_chunk_id_is_string(self):
        """
        GIVEN valid structured_text
        WHEN _create_optimal_chunks is called
        THEN expect all chunk IDs are string type
        """
        # When
        chunks = await self.optimizer._create_optimal_chunks(self.valid_structured_text)
        
        # Then
        for i, chunk in enumerate(chunks):
            assert isinstance(chunk.chunk_id, str), \
                f"Chunk {i} should have string ID, got {type(chunk.chunk_id).__name__}"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_source_page_valid(self):
        """
        GIVEN valid structured_text
        WHEN _create_optimal_chunks is called
        THEN expect all chunks have valid source page numbers
        """
        # When
        chunks = await self.optimizer._create_optimal_chunks(self.valid_structured_text)
        
        # Then
        for i, chunk in enumerate(chunks):
            assert chunk.source_page > 0, \
            f"Chunk {i} should have valid page number, got {chunk.source_page}"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_semantic_types_is_set(self):
        """
        GIVEN valid structured_text
        WHEN _create_optimal_chunks is called
        THEN expect all chunks have semantic types as set
        """
        # When
        chunks = await self.optimizer._create_optimal_chunks(self.valid_structured_text)
        
        # Then
        for i, chunk in enumerate(chunks):
            assert isinstance(chunk.semantic_types, str), \
                f"Chunk {i} should have semantic type set, got {type(chunk.semantic_types)}"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_relationships_is_list(self):
        """
        GIVEN valid structured_text
        WHEN _create_optimal_chunks is called
        THEN expect all chunks have relationships as list
        """
        # When
        chunks = await self.optimizer._create_optimal_chunks(self.valid_structured_text)
        
        # Then
        for i, chunk in enumerate(chunks):
            assert isinstance(chunk.relationships, list), \
                f"Chunk {i} should have relationships list, got {type(chunk.relationships).__name__}"



class TestLLMOptimizerCreateOptimalChunksLimitAdherence:

    def setup_method(self):
        MAX_CHUNK_SIZE = 50  # Example max chunk size
        MIN_CHUNK_SIZE = 20
        CHUNK_OVERLAP = 10  # Example overlap size
        self.optimizer = LLMOptimizer(
            max_chunk_size=MAX_CHUNK_SIZE, 
            chunk_overlap=MIN_CHUNK_SIZE, 
            min_chunk_size=CHUNK_OVERLAP
        )

    @property
    def structured_text(self):
        BIG_NUMBER = 20
        # Create large content that will exceed max_chunk_size
        large_content = " ".join(
            [f"This is sentence number {i} with substantial content for testing token limits." 
             for i in range(BIG_NUMBER)]
        )

        structured_text = {
            "pages": [
                {
                    "page_number": 1,
                    "elements": [
                        {
                            "type": "paragraph",
                            "content": large_content,
                            "metadata": {"element_id": "large_p1"}
                        }
                    ],
                    "full_text": large_content
                }
            ]
        }
        return structured_text

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_returns_list(self):
        """
        GIVEN content that exceeds max_chunk_size
        WHEN _create_optimal_chunks is called
        THEN expect list of chunks returned
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        assert isinstance(chunks, list), "Should return list of chunks"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_creates_multiple_chunks(self):
        """
        GIVEN content that exceeds max_chunk_size
        WHEN _create_optimal_chunks is called
        THEN expect multiple chunks created
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        assert len(chunks) > 1, "Large content should be split into multiple chunks"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_have_token_count(self):
        """
        GIVEN content that exceeds max_chunk_size
        WHEN _create_optimal_chunks is called
        THEN expect all chunks have token_count attribute
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        assert all(hasattr(chunk, 'token_count') for chunk in chunks), "All chunks should have token_count"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_have_chunk_id(self):
        """
        GIVEN content that exceeds max_chunk_size
        WHEN _create_optimal_chunks is called
        THEN expect all chunks have chunk_id attribute
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        assert all(hasattr(chunk, 'chunk_id') for chunk in chunks), "All chunks should have chunk_id"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_have_relationships(self):
        """
        GIVEN content that exceeds max_chunk_size
        WHEN _create_optimal_chunks is called
        THEN expect all chunks have relationships attribute
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        assert all(hasattr(chunk, 'relationships') for chunk in chunks), "All chunks should have relationships"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_respect_max_size(self):
        """
        GIVEN content that exceeds max_chunk_size
        WHEN _create_optimal_chunks is called
        THEN expect no chunk exceeds max_chunk_size token limit
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        for i, chunk in enumerate(chunks):
            assert chunk.token_count <= self.optimizer.max_chunk_size, \
                f"Chunk {i} (id: {chunk.chunk_id}) exceeds max_chunk_size: " \
                f"{chunk.token_count} > {self.optimizer.max_chunk_size}"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_respect_min_size_except_last(self):
        """
        GIVEN content that exceeds max_chunk_size
        WHEN _create_optimal_chunks is called
        THEN expect all chunks except last meet min_chunk_size
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        for i, chunk in enumerate(chunks[:-1]):  # All but last chunk
            assert chunk.token_count >= self.optimizer.min_chunk_size, \
                f"Chunk {i} (id: {chunk.chunk_id}) below min_chunk_size: {chunk.token_count} < {self.optimizer.min_chunk_size}"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_last_chunk_has_content(self):
        """
        GIVEN content that exceeds max_chunk_size
        WHEN _create_optimal_chunks is called
        THEN expect last chunk has content
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        last_chunk = chunks[-1]
        assert last_chunk.token_count > 0, "Last chunk should have some content"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_first_chunk_no_previous_relationship(self):
        """
        GIVEN content that exceeds max_chunk_size
        WHEN _create_optimal_chunks is called
        THEN expect first chunk should not have previous relationship
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        first_chunk = chunks[0]
        prev_relationships = [rel for rel in first_chunk.relationships if 'previous' in rel.get('type', '').lower()]
        assert len(prev_relationships) == 0, f"First chunk should not have previous relationships"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_middle_chunks_have_previous_relationship(self):
        """
        GIVEN content that exceeds max_chunk_size
        WHEN _create_optimal_chunks is called
        THEN expect middle and last chunks have relationship to previous chunk
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        for i in range(1, len(chunks)):
            chunk = chunks[i]
            prev_relationships = [rel for rel in chunk.relationships if 'previous' in rel.get('type', '').lower()]
            assert len(prev_relationships) > 0, f"Chunk {i} should have relationship to previous chunk"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_previous_relationships_point_to_correct_chunk(self):
        """
        GIVEN content that exceeds max_chunk_size
        WHEN _create_optimal_chunks is called
        THEN expect previous relationships point to correct previous chunk
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        for i in range(1, len(chunks)):
            chunk = chunks[i]
            previous_chunk_id = chunks[i-1].chunk_id
            prev_relationships = [rel for rel in chunk.relationships if 'previous' in rel.get('type', '').lower()]
            prev_chunk_ids = [rel.get('target_chunk_id') for rel in prev_relationships]
            assert previous_chunk_id in prev_chunk_ids, \
                f"Chunk {i} should reference previous chunk {previous_chunk_id}, found: {prev_chunk_ids}"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_last_chunk_no_next_relationship(self):
        """
        GIVEN content that exceeds max_chunk_size
        WHEN _create_optimal_chunks is called
        THEN expect last chunk should not have next relationship
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        last_chunk = chunks[-1]
        next_relationships = [rel for rel in last_chunk.relationships if 'next' in rel.get('type', '').lower()]
        assert len(next_relationships) == 0, f"Last chunk should not have next relationships"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_first_and_middle_chunks_have_next_relationship(self):
        """
        GIVEN content that exceeds max_chunk_size
        WHEN _create_optimal_chunks is called
        THEN expect first and middle chunks have relationship to next chunk
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        for i in range(len(chunks) - 1):
            chunk = chunks[i]
            next_relationships = [rel for rel in chunk.relationships if 'next' in rel.get('type', '').lower()]
            assert len(next_relationships) > 0, f"Chunk {i} should have relationship to next chunk"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_next_relationships_point_to_correct_chunk(self):
        """
        GIVEN content that exceeds max_chunk_size
        WHEN _create_optimal_chunks is called
        THEN expect next relationships point to correct next chunk
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        for i in range(len(chunks) - 1):
            chunk = chunks[i]
            next_chunk_id = chunks[i+1].chunk_id
            next_relationships = [rel for rel in chunk.relationships if 'next' in rel.get('type', '').lower()]
            next_chunk_ids = [rel.get('target_chunk_id') for rel in next_relationships]
            assert next_chunk_id in next_chunk_ids, \
                f"Chunk {i} should reference next chunk {next_chunk_id}, found: {next_chunk_ids}"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_preserve_content(self):
        """
        GIVEN content that exceeds max_chunk_size
        WHEN _create_optimal_chunks is called
        THEN expect total content is preserved across chunks
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        total_chunk_content = " ".join([chunk.content.strip() for chunk in chunks])
        assert len(total_chunk_content) > 0, "Combined chunks should preserve content"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_unique_chunk_ids(self):
        """
        GIVEN content that exceeds max_chunk_size
        WHEN _create_optimal_chunks is called
        THEN expect all chunk IDs are unique
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        chunk_ids = [chunk.chunk_id for chunk in chunks]
        assert len(chunk_ids) == len(set(chunk_ids)), "All chunk IDs should be unique"



class TestLLMOptimizerCreateOptimalChunksPageBoundaryRespect:

    def setup_method(self):
        MAX_CHUNK_SIZE = 100  # Example max chunk size
        MIN_CHUNK_SIZE = 30
        CHUNK_OVERLAP = 20  # Example overlap size
        self.optimizer = LLMOptimizer(
            max_chunk_size=MAX_CHUNK_SIZE, 
            chunk_overlap=CHUNK_OVERLAP, 
            min_chunk_size=MIN_CHUNK_SIZE
        )

    @property
    def multi_page_text(self):
        # Content spanning multiple pages
        structured_text = {
            "pages": [
                {
                    "page_number": 1,
                    "elements": [
                        {
                            "type": "paragraph",
                            "content": "This is the first paragraph on page 1. It contains substantial content that establishes the document context and introduces key concepts for analysis.",
                            "metadata": {"element_id": "p1_1"}
                        },
                        {
                            "type": "paragraph",
                            "content": "This is the second paragraph on page 1. It continues the narrative with additional details and supporting information for comprehensive understanding.",
                            "metadata": {"element_id": "p1_2"}
                        }
                    ],
                    "full_text": "Page 1 content combined for analysis."
                },
                {
                    "page_number": 2,
                    "elements": [
                        {
                            "type": "paragraph",
                            "content": "This paragraph begins page 2 and transitions from the previous page content. It maintains document flow while introducing new concepts and detailed analysis.",
                            "metadata": {"element_id": "p2_1"}
                        },
                        {
                            "type": "table",
                            "content": "Table 1: Key Research Results\nMethod A: 95% accuracy\nMethod B: 87% accuracy\nMethod C: 92% accuracy\nAnalysis shows significant performance differences.",
                            "metadata": {"table_id": "table_2_1", "element_id": "t2_1"}
                        }
                    ],
                    "full_text": "Page 2 content with table data."
                },
                {
                    "page_number": 3,
                    "elements": [
                        {
                            "type": "paragraph",
                            "content": "Page 3 concludes the analysis with comprehensive findings and recommendations. The synthesis of previous pages provides complete understanding.",
                            "metadata": {"element_id": "p3_1"}
                        }
                    ],
                    "full_text": "Page 3 conclusion content."
                }
            ]
        }
        return structured_text

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_returns_list_for_multi_page(self):
        """
        GIVEN content spanning multiple pages
        WHEN _create_optimal_chunks is called
        THEN expect list of chunks returned
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.multi_page_text)
        
        # Then
        assert isinstance(chunks, list), "Should return list of chunks"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_creates_chunks_for_multi_page(self):
        """
        GIVEN content spanning multiple pages
        WHEN _create_optimal_chunks is called
        THEN expect at least one chunk created
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.multi_page_text)
        
        # Then
        assert len(chunks) > 0, "Should create chunks for multi-page content"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_have_source_page_attribute(self):
        """
        GIVEN content spanning multiple pages
        WHEN _create_optimal_chunks is called
        THEN expect all chunks have source_page attribute
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.multi_page_text)
        
        # Then
        for i, chunk in enumerate(chunks):
            assert hasattr(chunk, 'source_page'), f"Chunk {i} should have source_page attribute"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_source_page_is_integer(self):
        """
        GIVEN content spanning multiple pages
        WHEN _create_optimal_chunks is called
        THEN expect all chunks have integer source_page values
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.multi_page_text)
        
        # Then
        for i, chunk in enumerate(chunks):
            assert isinstance(chunk.source_page, int), f"Chunk {i} source_page should be integer"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_source_page_in_valid_range(self):
        """
        GIVEN content spanning multiple pages
        WHEN _create_optimal_chunks is called
        THEN expect all chunks have source_page within document page range
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.multi_page_text)
        
        # Then
        for i, chunk in enumerate(chunks):
            assert 1 <= chunk.source_page <= 3, \
                f"Chunk {i} source_page {chunk.source_page} should be between 1 and 3"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_all_pages_represented(self):
        """
        GIVEN content spanning multiple pages
        WHEN _create_optimal_chunks is called
        THEN expect all document pages represented in chunks
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.multi_page_text)
        
        # Then
        page_numbers_in_chunks = {chunk.source_page for chunk in chunks}
        expected_pages = {1, 2, 3}
        assert expected_pages.issubset(page_numbers_in_chunks), f"All pages should be represented, found pages: {page_numbers_in_chunks}"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_each_page_has_chunks(self):
        """
        GIVEN content spanning multiple pages
        WHEN _create_optimal_chunks is called
        THEN expect each page has at least one associated chunk
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.multi_page_text)
        
        # Then
        page_chunks = {}
        for chunk in chunks:
            page_num = chunk.source_page
            if page_num not in page_chunks:
                page_chunks[page_num] = []
            page_chunks[page_num].append(chunk)
        
        expected_pages = {1, 2, 3}
        for page_num in expected_pages:
            assert page_num in page_chunks, f"Page {page_num} should have associated chunks"
            assert len(page_chunks[page_num]) > 0, f"Page {page_num} should have at least one chunk"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_relationships_point_to_existing_chunks(self):
        """
        GIVEN content spanning multiple pages
        WHEN _create_optimal_chunks is called
        THEN expect chunk relationships point to existing chunks
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.multi_page_text)
        
        # Then
        chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}
        
        for chunk in chunks:
            for relationship in chunk.relationships:
                if 'target_chunk_id' in relationship:
                    target_id = relationship['target_chunk_id']
                    assert target_id in chunk_by_id, f"Relationship target {target_id} should exist in chunks"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_cross_page_relationships_logical(self):
        """
        GIVEN content spanning multiple pages
        WHEN _create_optimal_chunks is called
        THEN expect cross-page relationships only between adjacent or same pages
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.multi_page_text)
        
        # Then
        chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}
        
        for chunk in chunks:
            for relationship in chunk.relationships:
                if 'target_chunk_id' in relationship:
                    target_id = relationship['target_chunk_id']
                    if target_id in chunk_by_id:
                        related_chunk = chunk_by_id[target_id]
                        page_distance = abs(chunk.source_page - related_chunk.source_page)
                        assert page_distance <= 1, f"Chunk on page {chunk.source_page} should not relate to chunk on distant page {related_chunk.source_page}"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_page_1_content_preserved(self):
        """
        GIVEN content spanning multiple pages
        WHEN _create_optimal_chunks is called
        THEN expect page 1 content themes preserved in page 1 chunks
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.multi_page_text)
        
        # Then
        page_1_chunks = [chunk for chunk in chunks if chunk.source_page == 1]
        page_1_content = " ".join(chunk.content for chunk in page_1_chunks).lower()
        assert "page 1" in page_1_content or "first" in page_1_content or "context" in page_1_content, "Page 1 chunks should contain page 1 content themes"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_page_2_content_preserved(self):
        """
        GIVEN content spanning multiple pages
        WHEN _create_optimal_chunks is called
        THEN expect page 2 content themes preserved in page 2 chunks
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.multi_page_text)
        
        # Then
        page_2_chunks = [chunk for chunk in chunks if chunk.source_page == 2]
        page_2_content = " ".join(chunk.content for chunk in page_2_chunks).lower()
        assert "page 2" in page_2_content or "table" in page_2_content or "method" in page_2_content or "accuracy" in page_2_content, "Page 2 chunks should contain page 2 content themes"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_page_3_content_preserved(self):
        """
        GIVEN content spanning multiple pages
        WHEN _create_optimal_chunks is called
        THEN expect page 3 content themes preserved in page 3 chunks
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.multi_page_text)
        
        # Then
        page_3_chunks = [chunk for chunk in chunks if chunk.source_page == 3]
        page_3_content = " ".join(chunk.content for chunk in page_3_chunks).lower()
        assert "page 3" in page_3_content or "concludes" in page_3_content or "findings" in page_3_content, "Page 3 chunks should contain page 3 content themes"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_ordering_respects_page_sequence(self):
        """
        GIVEN content spanning multiple pages
        WHEN _create_optimal_chunks is called
        THEN expect chunk ordering generally follows page sequence
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.multi_page_text)
        
        # Then
        for i in range(len(chunks) - 1):
            current_chunk = chunks[i]
            next_chunk = chunks[i + 1]
            assert next_chunk.source_page >= current_chunk.source_page - 1, f"Chunk sequence should generally follow page order: chunk {i} page {current_chunk.source_page}, chunk {i+1} page {next_chunk.source_page}"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_table_content_associated_with_page_2(self):
        """
        GIVEN content spanning multiple pages
        WHEN _create_optimal_chunks is called
        THEN expect table content associated with page 2
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.multi_page_text)
        
        # Then
        table_chunks = [chunk for chunk in chunks if "table" in chunk.semantic_types or "table" in chunk.content.lower()]
        if table_chunks:
            table_pages = {chunk.source_page for chunk in table_chunks}
            assert 2 in table_pages, "Table content should be associated with page 2"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_minimal_small_chunks_due_to_page_boundaries(self):
        """
        GIVEN content spanning multiple pages
        WHEN _create_optimal_chunks is called
        THEN expect at most one small chunk due to page boundary considerations
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.multi_page_text)
        
        # Then
        small_chunks = [chunk for chunk in chunks if chunk.token_count < self.optimizer.min_chunk_size]
        assert len(small_chunks) <= 1, f"Should have at most 1 small chunk (last chunk), found {len(small_chunks)} small chunks"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_cross_page_relationships_not_excessive(self):
        """
        GIVEN content spanning multiple pages
        WHEN _create_optimal_chunks is called
        THEN expect cross-page relationships do not dominate total relationships
        """
        # When
        chunks: list[LLMChunk] = await self.optimizer._create_optimal_chunks(self.multi_page_text)
        
        # Then
        chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}
        cross_page_relationships = 0
        
        for chunk in chunks:
            for relationship in chunk.relationships:
                if 'target_chunk_id' in relationship:
                    target_id = relationship['target_chunk_id']
                    if target_id in chunk_by_id:
                        related_chunk = chunk_by_id[target_id]
                        if chunk.source_page != related_chunk.source_page:
                            cross_page_relationships += 1
        
        total_relationships = sum(len(chunk.relationships) for chunk in chunks)
        cross_page_ratio = cross_page_relationships / total_relationships
        assert cross_page_ratio <= 0.5, f"Cross-page relationships should not dominate: {cross_page_ratio:.2f} ratio"



class TestLLMOptimizerCreateOptimalChunksSemanticGrouping:

    def setup_method(self):
        self.optimizer = LLMOptimizer()

    @property
    def structured_text(self):
        # Content with different semantic types
        structured_text = {
            "pages": [
                {
                    "page_number": 1,
                    "elements": [
                        {
                            "type": "header",
                            "content": "Document Title: Advanced Research Methods",
                            "metadata": {"level": 1, "element_id": "h1"}
                        },
                        {
                            "type": "paragraph",
                            "content": "This introductory paragraph provides context for the research methodology discussion.",
                            "metadata": {"element_id": "p1"}
                        },
                        {
                            "type": "table",
                            "content": "Table 1: Research Results\nMethod A: 85% accuracy\nMethod B: 92% accuracy\nMethod C: 78% accuracy",
                            "metadata": {"table_id": "table1", "element_id": "t1"}
                        },
                        {
                            "type": "paragraph",
                            "content": "The table above demonstrates the comparative performance of different methodological approaches.",
                            "metadata": {"element_id": "p2"}
                        },
                        {
                            "type": "figure_caption",
                            "content": "Figure 1: Visualization of research methodology workflow and decision points.",
                            "metadata": {"figure_id": "fig1", "element_id": "f1"}
                        }
                    ],
                    "full_text": "Combined content representing mixed semantic types for analysis."
                }
            ]
        }
        return structured_text

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_returns_list_for_semantic_content(self):
        """
        GIVEN content with different semantic types
        WHEN _create_optimal_chunks is called
        THEN expect list of chunks returned
        """
        # When
        chunks = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        assert isinstance(chunks, list), "Should return list of chunks"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_creates_chunks_for_semantic_content(self):
        """
        GIVEN content with different semantic types
        WHEN _create_optimal_chunks is called
        THEN expect at least one chunk created
        """
        # When
        chunks = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        assert len(chunks) > 0, "Should create chunks for semantic content"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_preserves_semantic_types(self):
        """
        GIVEN content with different semantic types
        WHEN _create_optimal_chunks is called
        THEN expect semantic types are preserved in chunks
        """
        # When
        chunks = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        semantic_types_found = []
        for chunk in chunks:
            list_ = list(chunk.semantic_types)
            semantic_types_found.extend(list_)
        semantic_types_found = set(semantic_types_found)
        
        assert len(semantic_types_found) > 0, "Should have semantic type classification"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_uses_expected_semantic_types(self):
        """
        GIVEN content with different semantic types
        WHEN _create_optimal_chunks is called
        THEN expect only expected semantic types are used
        """
        # When
        expected_types = {"text", "table", "header", "mixed", "figure_caption"}
        chunks = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        semantic_types_found = []
        for chunk in chunks:
            semantic_types_found.extend(list(chunk.semantic_types))
        semantic_types_found = set(semantic_types_found)

        assert all(st in expected_types for st in semantic_types_found), \
            f"Unexpected semantic types: {semantic_types_found - expected_types}"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_header_content_has_appropriate_semantic_type(self):
        """
        GIVEN content with different semantic types
        WHEN _create_optimal_chunks is called
        THEN expect header content has appropriate semantic type
        """
        # When
        chunks = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        header_chunks = [
            c for c in chunks if "title" in c.content.lower() or "header" in c.semantic_types
        ]

        header_chunk = header_chunks[0]
        for element in header_chunk.semantic_types:
            assert element in ["header", "text", "mixed"], \
                f"Header chunk has unexpected type: {header_chunk.semantic_types}"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_table_content_has_appropriate_semantic_type(self):
        """
        GIVEN content with different semantic types
        WHEN _create_optimal_chunks is called
        THEN expect table content has appropriate semantic type
        """
        # When
        chunks = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        table_chunks = [c for c in chunks if "table" in c.content.lower() or "table" in c.semantic_types]
        
        if table_chunks:
            table_chunk = table_chunks[0]
            for element in table_chunk.semantic_types:
                assert element in ["table", "text", "mixed"], f"Table chunk has unexpected type: {table_chunk.semantic_types}"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_source_elements_is_list(self):
        """
        GIVEN content with different semantic types
        WHEN _create_optimal_chunks is called
        THEN expect source elements are preserved as list
        """
        # When
        chunks = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        for chunk in chunks:
            assert isinstance(chunk.source_elements, list), "Source element should be list of strings"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_source_elements_not_empty(self):
        """
        GIVEN content with different semantic types
        WHEN _create_optimal_chunks is called
        THEN expect source elements are not empty
        """
        # When
        chunks = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        for chunk in chunks:
            assert len(chunk.source_elements) > 0, "Source elements should not be empty"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_content_is_meaningful(self):
        """
        GIVEN content with different semantic types
        WHEN _create_optimal_chunks is called
        THEN expect chunks have meaningful content
        """
        # When
        chunks = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        for chunk in chunks:
            assert len(chunk.content.strip()) > 0, "Chunks should have meaningful content"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_content_not_start_with_whitespace(self):
        """
        GIVEN content with different semantic types
        WHEN _create_optimal_chunks is called
        THEN expect chunk content does not start with whitespace
        """
        # When
        chunks = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        for chunk in chunks:
            assert not chunk.content.startswith(" "), "Chunk content should not start with whitespace"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_content_not_end_with_whitespace(self):
        """
        GIVEN content with different semantic types
        WHEN _create_optimal_chunks is called
        THEN expect chunk content does not end with whitespace
        """
        # When
        chunks = await self.optimizer._create_optimal_chunks(self.structured_text)
        
        # Then
        for chunk in chunks:
            assert not chunk.content.endswith(" "), "chunk.content should not end with whitespace"


class TestLLMOptimizerCreateOptimalChunksEdgeCases:

    def setup_method(self):
        self.optimizer = LLMOptimizer()

    def _get_empty_structured_text(self):
        """Helper method to get empty structured text."""
        return {
            "pages": []
        }

    def _get_structured_text_with_empty_pages(self):
        """Helper method to get structured text with empty pages."""
        return {
            "pages": [
                {"page_number": 1, "elements": [], "full_text": ""},
                {"page_number": 2, "elements": [], "full_text": ""}
            ]
        }

    def _get_structured_text_with_whitespace_only_content(self):
        """Helper method to get structured text with whitespace-only content."""
        return {
            "pages": [
                {
                    "page_number": 1,
                    "elements": [
                        {"type": "header", "content": "", "metadata": {}},
                        {"type": "paragraph", "content": "   ", "metadata": {}},  # Only whitespace
                        {"type": "table", "content": "\n\t", "metadata": {}}  # Only whitespace chars
                    ],
                    "full_text": "   \n\t   "
                }
            ]
        }

    def _get_structured_text_with_none_content(self):
        """Helper method to get structured text with None content."""
        return {
            "pages": [
                {
                    "page_number": 1,
                    "elements": [
                        {"type": "paragraph", "content": None, "metadata": {}},
                        {"type": "header", "content": "", "metadata": {}}
                    ],
                    "full_text": None
                }
            ]
        }

    def _get_malformed_structured_text(self):
        """Helper method to get malformed structured text."""
        return {
            "pages": [
                {"page_number": 1},  # Missing elements
                {"elements": [], "full_text": ""},  # Missing page_number
                None  # None page
            ]
        }

    def _get_structured_text_with_tiny_content(self):
        """Helper method to get structured text with very short content."""
        return {
            "pages": [
                {
                    "page_number": 1,
                    "elements": [
                        {"type": "paragraph", "content": "Hi", "metadata": {}}  # Very short content
                    ],
                    "full_text": "Hi"
                }
            ]
        }

    @pytest.mark.parametrize("test_input_func", [
        "_get_empty_structured_text",
        "_get_structured_text_with_empty_pages"
    ])
    @pytest.mark.asyncio
    async def test_create_optimal_chunks_empty_content_returns_list(self, test_input_func):
        """
        GIVEN structured_text with no valid content
        WHEN _create_optimal_chunks is called
        THEN expect list returned
        """
        # Given
        structured_text = getattr(self, test_input_func)()
        
        # When
        chunks = await self.optimizer._create_optimal_chunks(structured_text)
        
        # Then
        assert isinstance(chunks, list), f"Should return list even for empty content, got {type(chunks).__name__}"

    @pytest.mark.parametrize("test_input_func", [
        "_get_empty_structured_text",
        "_get_structured_text_with_empty_pages",
        "_get_structured_text_with_whitespace_only_content",
        "_get_structured_text_with_none_content",
        "_get_malformed_structured_text",
        "_get_structured_text_with_tiny_content"
    ])
    @pytest.mark.asyncio
    async def test_create_optimal_chunks_returns_empty_list_for_invalid_content(self, test_input_func):
        """
        GIVEN structured_text with invalid/empty content
        WHEN _create_optimal_chunks is called
        THEN expect empty list returned
        """
        # Given
        structured_text = getattr(self, test_input_func)()
        
        # When
        chunks = await self.optimizer._create_optimal_chunks(structured_text)
        
        # Then
        assert len(chunks) == 0, f"Should return empty list for invalid content from {test_input_func}, got {len(chunks)} chunks"

    @pytest.mark.parametrize("test_input_func", [
        ("_get_empty_structured_text"),
        ("_get_structured_text_with_empty_pages"),
        ("_get_structured_text_with_whitespace_only_content"),
        ("_get_structured_text_with_none_content"),
        ("_get_malformed_structured_text"),
        ("_get_structured_text_with_tiny_content")
    ])
    @pytest.mark.asyncio
    async def test_create_optimal_chunks_edge_cases_returns_expected_type(self, test_input_func):
        """
        GIVEN structured_text with various edge case content
        WHEN _create_optimal_chunks is called
        THEN expect correct return type
        """
        # Given
        structured_text = getattr(self, test_input_func)()
        
        # When
        chunks = await self.optimizer._create_optimal_chunks(structured_text)
        
        # Then
        assert isinstance(chunks, list), \
            f"Should return list for {test_input_func}, got {type(chunks).__name__}"



if __name__ == "__main__":
    pytest.main([__file__, "-v"])
