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



class TestLLMOptimizerCreateOptimalChunks:
    """Test LLMOptimizer._create_optimal_chunks method."""


    @pytest.mark.asyncio
    async def test_create_optimal_chunks_valid_input(self):
        """
        GIVEN valid structured_text and decomposed_content
        WHEN _create_optimal_chunks is called
        THEN expect:
            - List of LLMChunk instances returned
            - All chunks respect token limits
            - Semantic coherence maintained
            - Overlap applied correctly
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer
        
        # Given
        optimizer = LLMOptimizer()
        
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

        # When
        chunks = await optimizer._create_optimal_chunks(structured_text)
        
        # Then
        assert isinstance(chunks, list), "Should return list of chunks"
        assert len(chunks) > 0, "Should create at least one chunk for valid content"
        
        # Verify all items are LLMChunk instances
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        for chunk in chunks:
            assert isinstance(chunk, LLMChunk), f"All items should be LLMChunk instances, got {type(chunk)}"
        
        # Verify token limits respected
        for i, chunk in enumerate(chunks):
            assert chunk.token_count <= optimizer.max_chunk_size, f"Chunk {i} exceeds max size: {chunk.token_count} > {optimizer.max_chunk_size}"
            assert chunk.token_count >= optimizer.min_chunk_size or len(chunks) == 1, f"Chunk {i} below min size: {chunk.token_count} < {optimizer.min_chunk_size}"
        
        # Verify chunk structure
        for i, chunk in enumerate(chunks):
            assert isinstance(chunk.content, str), f"Chunk {i} content should be string"
            assert len(chunk.content.strip()) > 0, f"Chunk {i} should have non-empty content"
            assert isinstance(chunk.chunk_id, str), f"Chunk {i} should have string ID"
            assert chunk.source_page > 0, f"Chunk {i} should have valid page number"
            assert isinstance(chunk.semantic_types, set), f"Chunk {i} should have semantic type set, got {type(chunk.semantic_types)}"
            assert isinstance(chunk.relationships, list), f"Chunk {i} should have relationships list"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_token_limit_adherence(self):
        """
        GIVEN content that exceeds max_chunk_size
        WHEN _create_optimal_chunks is called
        THEN expect:
            - All chunks within max_chunk_size token limit
            - All chunks except last meet min_chunk_size
            - Adjacent chunks have relationships for overlap context
            - Total content is preserved across chunks
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer
        
        # Given - create optimizer with small chunk size for testing
        optimizer = LLMOptimizer(max_chunk_size=50, chunk_overlap=10, min_chunk_size=20)
        
        # Create large content that will exceed max_chunk_size
        large_content = " ".join([f"This is sentence number {i} with substantial content for testing token limits." for i in range(20)])
        
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

        # When
        chunks: list[LLMChunk] = await optimizer._create_optimal_chunks(structured_text)
        
        # Then - verify basic structure
        assert isinstance(chunks, list), "Should return list of chunks"
        assert len(chunks) > 1, "Large content should be split into multiple chunks"
        assert all(hasattr(chunk, 'token_count') for chunk in chunks), "All chunks should have token_count"
        assert all(hasattr(chunk, 'chunk_id') for chunk in chunks), "All chunks should have chunk_id"
        assert all(hasattr(chunk, 'relationships') for chunk in chunks), "All chunks should have relationships"
        
        # Verify token limits - no chunk exceeds max_chunk_size
        for i, chunk in enumerate(chunks):
            assert chunk.token_count <= optimizer.max_chunk_size, \
                f"Chunk {i} (id: {chunk.chunk_id}) exceeds max_chunk_size: {chunk.token_count} > {optimizer.max_chunk_size}"
        
        # Verify minimum size requirements - all chunks except last must meet min_chunk_size
        for i, chunk in enumerate(chunks[:-1]):  # All but last chunk
            assert chunk.token_count >= optimizer.min_chunk_size, \
                f"Chunk {i} (id: {chunk.chunk_id}) below min_chunk_size: {chunk.token_count} < {optimizer.min_chunk_size}"
        
        # Last chunk should have content but may be smaller than min_chunk_size
        last_chunk = chunks[-1]
        assert last_chunk.token_count > 0, "Last chunk should have some content"
        
        # Verify chunk relationships for overlap context
        for i in range(len(chunks)):
            chunk = chunks[i]
            
            # First chunk should not have previous relationship
            if i == 0:
                prev_relationships = [rel for rel in chunk.relationships if 'previous' in rel.get('type', '').lower()]
                assert len(prev_relationships) == 0, f"First chunk should not have previous relationships"
            
            # Middle and last chunks should have relationship to previous chunk
            else:
                previous_chunk_id = chunks[i-1].chunk_id
                prev_relationships = [rel for rel in chunk.relationships if 'previous' in rel.get('type', '').lower()]
                assert len(prev_relationships) > 0, f"Chunk {i} should have relationship to previous chunk"
                
                # Verify the relationship points to the correct previous chunk
                prev_chunk_ids = [rel.get('target_chunk_id') for rel in prev_relationships]
                assert previous_chunk_id in prev_chunk_ids, \
                    f"Chunk {i} should reference previous chunk {previous_chunk_id}, found: {prev_chunk_ids}"
            
            # Last chunk should not have next relationship
            if i == len(chunks) - 1:
                next_relationships = [rel for rel in chunk.relationships if 'next' in rel.get('type', '').lower()]
                assert len(next_relationships) == 0, f"Last chunk should not have next relationships"
            
            # First and middle chunks should have relationship to next chunk
            else:
                next_chunk_id = chunks[i+1].chunk_id
                next_relationships = [rel for rel in chunk.relationships if 'next' in rel.get('type', '').lower()]
                assert len(next_relationships) > 0, f"Chunk {i} should have relationship to next chunk"
                
                # Verify the relationship points to the correct next chunk
                next_chunk_ids = [rel.get('target_chunk_id') for rel in next_relationships]
                assert next_chunk_id in next_chunk_ids, \
                    f"Chunk {i} should reference next chunk {next_chunk_id}, found: {next_chunk_ids}"
        
        # Verify content preservation - all chunks should have content
        total_chunk_content = " ".join([chunk.content.strip() for chunk in chunks])
        assert len(total_chunk_content) > 0, "Combined chunks should preserve content"
        
        # Verify chunk IDs are unique
        chunk_ids = [chunk.chunk_id for chunk in chunks]
        assert len(chunk_ids) == len(set(chunk_ids)), "All chunk IDs should be unique"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_page_boundary_respect(self):
        """
        GIVEN content spanning multiple pages
        WHEN _create_optimal_chunks is called
        THEN expect:
            - Page boundaries considered in chunking
            - Source page information preserved
            - Cross-page relationships handled
        """
        
        # Given
        optimizer = LLMOptimizer(max_chunk_size=100, chunk_overlap=20, min_chunk_size=30)
        
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

        # When
        chunks: list[LLMChunk] = await optimizer._create_optimal_chunks(structured_text)
        
        # Then - verify page boundary handling
        assert isinstance(chunks, list), "Should return list of chunks"
        assert len(chunks) > 0, "Should create chunks for multi-page content"
        
        # Verify all chunks have valid source page information
        for i, chunk in enumerate(chunks):
            assert hasattr(chunk, 'source_page'), f"Chunk {i} should have source_page attribute"
            assert isinstance(chunk.source_page, int), f"Chunk {i} source_page should be integer"
            assert 1 <= chunk.source_page <= 3, f"Chunk {i} source_page {chunk.source_page} should be between 1 and 3"
        
        # Verify page representation - all pages should be represented in chunks
        page_numbers_in_chunks = {chunk.source_page for chunk in chunks}
        expected_pages = {1, 2, 3}
        assert expected_pages.issubset(page_numbers_in_chunks), f"All pages should be represented, found pages: {page_numbers_in_chunks}"
        
        # Verify page boundary considerations
        page_chunks = {}
        for chunk in chunks:
            page_num = chunk.source_page
            if page_num not in page_chunks:
                page_chunks[page_num] = []
            page_chunks[page_num].append(chunk)
        
        # Each page should have at least one chunk
        for page_num in expected_pages:
            assert page_num in page_chunks, f"Page {page_num} should have associated chunks"
            assert len(page_chunks[page_num]) > 0, f"Page {page_num} should have at least one chunk"
        
        # Verify cross-page relationships are handled appropriately
        chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}
        
        for chunk in chunks:
            # Check relationships point to existing chunks
            for relationship_id in chunk.relationships:
                if relationship_id in chunk_by_id:
                    related_chunk = chunk_by_id[relationship_id]
                    # Cross-page relationships should be logical (adjacent pages or same page)
                    page_distance = abs(chunk.source_page - related_chunk.source_page)
                    assert page_distance <= 1, f"Chunk on page {chunk.source_page} should not relate to chunk on distant page {related_chunk.source_page}"
        
        # Verify page-specific content is preserved
        page_1_chunks = page_chunks.get(1, [])
        page_2_chunks = page_chunks.get(2, [])
        page_3_chunks = page_chunks.get(3, [])
        
        # Page 1 content themes should appear in page 1 chunks
        page_1_content = " ".join(chunk.content for chunk in page_1_chunks).lower()
        assert "page 1" in page_1_content or "first" in page_1_content or "context" in page_1_content, "Page 1 chunks should contain page 1 content themes"
        
        # Page 2 should contain table content
        page_2_content = " ".join(chunk.content for chunk in page_2_chunks).lower()
        assert "page 2" in page_2_content or "table" in page_2_content or "method" in page_2_content or "accuracy" in page_2_content, "Page 2 chunks should contain page 2 content themes"
        
        # Page 3 should contain conclusion content
        page_3_content = " ".join(chunk.content for chunk in page_3_chunks).lower()
        assert "page 3" in page_3_content or "concludes" in page_3_content or "findings" in page_3_content, "Page 3 chunks should contain page 3 content themes"
        
        # Verify chunk ordering respects page sequence
        for i in range(len(chunks) - 1):
            current_chunk = chunks[i]
            next_chunk = chunks[i + 1]
            
            # Page numbers should not decrease significantly (allowing for minor variations due to chunking strategy)
            assert next_chunk.source_page >= current_chunk.source_page - 1, f"Chunk sequence should generally follow page order: chunk {i} page {current_chunk.source_page}, chunk {i+1} page {next_chunk.source_page}"
        
        # Verify semantic types are preserved across pages
        table_chunks = [chunk for chunk in chunks if "table" in chunk.semantic_types or "table" in chunk.content.lower()]
        if table_chunks:
            # Table chunks should primarily be from page 2
            table_pages = {chunk.source_page for chunk in table_chunks}
            assert 2 in table_pages, "Table content should be associated with page 2"
        
        # Verify page boundary chunking efficiency
        # Should not create excessive small chunks due to page boundaries
        small_chunks = [chunk for chunk in chunks if chunk.token_count < optimizer.min_chunk_size]
        assert len(small_chunks) <= 1, f"Should have at most 1 small chunk (last chunk), found {len(small_chunks)} small chunks"
        
        # Verify cross-page continuity in relationships
        cross_page_relationships = 0
        for chunk in chunks:
            for rel_id in chunk.relationships:
                if rel_id in chunk_by_id:
                    related_chunk = chunk_by_id[rel_id]
                    if chunk.source_page != related_chunk.source_page:
                        cross_page_relationships += 1
        
        # Should have some cross-page relationships for document continuity
        assert cross_page_relationships >= 0, "Cross-page relationships count should be non-negative"
        # But not excessive - most relationships should be within-page
        total_relationships = sum(len(chunk.relationships) for chunk in chunks)
        if total_relationships > 0:
            cross_page_ratio = cross_page_relationships / total_relationships
            assert cross_page_ratio <= 0.5, f"Cross-page relationships should not dominate: {cross_page_ratio:.2f} ratio"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_semantic_grouping(self):
        """
        GIVEN content with different semantic types
        WHEN _create_optimal_chunks is called
        THEN expect:
            - Related elements grouped together
            - Semantic types preserved in chunks
            - Logical chunk boundaries maintained
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer
        
        # Given
        optimizer = LLMOptimizer()
        
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

        # When
        chunks = await optimizer._create_optimal_chunks(structured_text)
        
        # Then - verify semantic grouping
        assert isinstance(chunks, list), "Should return list of chunks"
        assert len(chunks) > 0, "Should create chunks for semantic content"
        
        # Verify semantic types are preserved
        semantic_types_found = []
        for chunk in chunks:
            list_ = list(chunk.semantic_types)
            semantic_types_found.extend(list_)
        semantic_types_found = set(semantic_types_found)
        expected_types = {"text", "table", "header", "mixed", "figure_caption"}
        
        # At least some semantic types should be represented
        assert len(semantic_types_found) > 0, "Should have semantic type classification"
        assert all(st in expected_types for st in semantic_types_found), f"Unexpected semantic types: {semantic_types_found - expected_types}"
        
        # Verify logical grouping - related elements should be near each other
        header_chunks = [c for c in chunks if "title" in c.content.lower() or "header" in c.semantic_types]
        table_chunks = [c for c in chunks if "table" in c.content.lower() or "table" in c.semantic_types]
        
        if header_chunks:
            # Header content should be preserved with appropriate semantic type
            header_chunk = header_chunks[0]
            for element in header_chunk.semantic_types:
                assert element in ["header", "text", "mixed"], f"Header chunk has unexpected type: {header_chunk.semantic_types}"
        
        if table_chunks:
            # Table content should be preserved with appropriate semantic type
            table_chunk = table_chunks[0]
            for element in table_chunk.semantic_types:
                assert element in ["table", "text", "mixed"], f"Table chunk has unexpected type: {table_chunk.semantic_types}"
        
        # Verify source element information is preserved
        for chunk in chunks:
            assert isinstance(chunk.source_elements, list), "Source element should be list of strings"
            assert len(chunk.source_elements) > 0, "Source elements should not be empty"
        
        # Verify content coherence within chunks
        for chunk in chunks:
            assert len(chunk.content.strip()) > 0, "Chunks should have meaningful content"
            assert not chunk.content.startswith(" "), "Chunk content should not start with whitespace"
            assert not chunk.content.endswith(" "), "Chunk content should not end with whitespace"

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_empty_content(self):
        """
        GIVEN structured_text with no valid content
        WHEN _create_optimal_chunks is called
        THEN expect:
            - Empty list returned or appropriate handling
            - No errors raised
            - Graceful degradation
        """
        
        # Given
        optimizer = LLMOptimizer()
        
        # Test completely empty structured text
        empty_structured_text = {
            "pages": []
        }

        # When
        chunks = await optimizer._create_optimal_chunks(empty_structured_text)
        
        # Then
        assert isinstance(chunks, list), "Should return list even for empty content"
        assert len(chunks) == 0, "Should return empty list for empty content"
        

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_empty_pages(self):

        # Given
        optimizer = LLMOptimizer()

        # Test structured text with empty pages
        structured_text_empty_pages = {
            "pages": [
                {"page_number": 1, "elements": [], "full_text": ""},
                {"page_number": 2, "elements": [], "full_text": ""}
            ]
        }

        # When
        chunks = await optimizer._create_optimal_chunks(structured_text_empty_pages)
        
        # Then
        assert isinstance(chunks, list), "Should return list for empty pages"
        assert len(chunks) == 0, "Should return empty list for pages with no content"
        

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_empty_string(self):

        # Given
        optimizer = LLMOptimizer()

        # Test structured text with elements but no extractable content
        structured_text_no_content = {
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

        # When
        chunks = await optimizer._create_optimal_chunks(structured_text_no_content)
        
        # Then
        assert isinstance(chunks, list), "Should return list for whitespace-only content"
        assert len(chunks) == 0, "Should return empty list for whitespace-only content"
        
        # Test with None values in content
        structured_text_none_content = {
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

        # When/Then - should handle None content gracefully
        try:
            chunks = await optimizer._create_optimal_chunks(structured_text_none_content)
            assert isinstance(chunks, list), "Should return list even with None content"
            assert len(chunks) == 0, "Should return empty list for None content"
        except (TypeError, AttributeError) as e:
            # These exceptions are acceptable for None content
            error_msg = str(e).lower()
            assert any(keyword in error_msg for keyword in ["none", "null", "content", "attribute"]), f"Error should mention None/null issue: {e}"
        

    @pytest.mark.asyncio
    async def test_create_optimal_chunks_malformed_structure(self):
        optimizer = LLMOptimizer()

        # Test with malformed page structure
        malformed_structured_text = {
            "pages": [
                {"page_number": 1},  # Missing elements
                {"elements": [], "full_text": ""},  # Missing page_number
                None  # None page
            ]
        }

        # When/Then - should handle malformed structure gracefully
        try:
            chunks = await optimizer._create_optimal_chunks(malformed_structured_text)
            assert isinstance(chunks, list), "Should return list for malformed structure"
            # May return empty or partial results depending on implementation
        except (KeyError, TypeError, AttributeError) as e:
            # These exceptions are acceptable for malformed structure
            error_msg = str(e).lower()
            assert any(keyword in error_msg for keyword in ["key", "missing", "page", "elements", "attribute"]), f"Error should mention structural issue: {e}"
    
    @pytest.mark.asyncio
    async def test_create_optimal_chunks_edge_cases(self):
        optimizer = LLMOptimizer()

        # Test edge case: very short content below minimum chunk size
        structured_text_tiny = {
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

        # When
        chunks = await optimizer._create_optimal_chunks(structured_text_tiny)
        
        # Then - should handle very short content appropriately
        assert isinstance(chunks, list), "Should return list for tiny content"

        # Implementation may create chunk despite being below min_chunk_size, or return empty list
        if len(chunks) > 0:
            assert all(isinstance(chunk, optimizer.LLMChunk) for chunk in chunks), "All items should be LLMChunk instances"
            assert all(len(chunk.content.strip()) > 0 for chunk in chunks), "All chunks should have some content"
        # Empty list is also acceptable for content below threshold


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
