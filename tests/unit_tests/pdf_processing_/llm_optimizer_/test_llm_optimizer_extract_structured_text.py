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


class TestLLMOptimizerExtractStructuredText:
    """Test LLMOptimizer._extract_structured_text method."""

    @pytest.fixture
    def optimizer(self) -> LLMOptimizer:
        """Create LLMOptimizer instance for testing."""
        return LLMOptimizer()

    @pytest.fixture
    def decomposed_content_valid(self):
        """Create valid decomposed content for testing."""
        return {
            'pages': [
                {
                    'elements': [
                        {
                            'content': 'Chapter 1: Introduction',
                            'type': 'text',
                            'subtype': 'header',
                            'position': {'x': 100, 'y': 50},
                            'style': {'font_size': 18, 'bold': True},
                            'confidence': 0.95
                        },
                        {
                            'content': 'This is the introduction paragraph with important content.',
                            'type': 'text',
                            'subtype': 'paragraph',
                            'position': {'x': 100, 'y': 100},
                            'style': {'font_size': 12, 'bold': False},
                            'confidence': 0.89
                        }
                    ]
                },
                {
                    'elements': [
                        {
                            'content': 'Table: Sample Data',
                            'type': 'table',
                            'subtype': 'caption',
                            'position': {'x': 100, 'y': 200},
                            'style': {'font_size': 10, 'italic': True},
                            'confidence': 0.92
                        }
                    ]
                }
            ],
            'metadata': {'document_type': 'research_paper', 'total_pages': 2}
        }

    @pytest.mark.asyncio
    async def test_extract_structured_text_returns_dict(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with pages and elements
        WHEN _extract_structured_text is called
        THEN result should be a dictionary
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        assert isinstance(result, dict), "Result should be a dictionary"

    @pytest.mark.asyncio
    async def test_extract_structured_text_contains_pages_key(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with pages and elements
        WHEN _extract_structured_text is called
        THEN result should contain 'pages' key
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        assert 'pages' in result, "Result should contain 'pages' key"

    @pytest.mark.asyncio
    async def test_extract_structured_text_contains_metadata_key(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with pages and elements
        WHEN _extract_structured_text is called
        THEN result should contain 'metadata' key
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        assert 'metadata' in result, "Result should contain 'metadata' key"

    @pytest.mark.asyncio
    async def test_extract_structured_text_contains_structure_key(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with pages and elements
        WHEN _extract_structured_text is called
        THEN result should contain 'structure' key
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        assert 'structure' in result, "Result should contain 'structure' key"

    @pytest.mark.asyncio
    async def test_extract_structured_text_correct_page_count(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with 2 pages
        WHEN _extract_structured_text is called
        THEN result should have 2 pages
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        assert len(result['pages']) == 2, "Should have 2 pages"

    @pytest.mark.asyncio
    async def test_extract_structured_text_page_has_page_number(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with pages
        WHEN _extract_structured_text is called
        THEN first page should have page_number field
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        page1 = result['pages'][0]
        assert 'page_number' in page1, "Page should have page_number"

    @pytest.mark.asyncio
    async def test_extract_structured_text_page_has_elements(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with pages
        WHEN _extract_structured_text is called
        THEN first page should have elements field
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        page1 = result['pages'][0]
        assert 'elements' in page1, "Page should have elements"

    @pytest.mark.asyncio
    async def test_extract_structured_text_page_has_full_text(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with pages
        WHEN _extract_structured_text is called
        THEN first page should have full_text field
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        page1 = result['pages'][0]
        assert 'full_text' in page1, "Page should have full_text"

    @pytest.mark.asyncio
    async def test_extract_structured_text_correct_element_count(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with 2 elements on first page
        WHEN _extract_structured_text is called
        THEN first page should have 2 text elements
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        page1 = result['pages'][0]
        assert len(page1['elements']) == 2, "First page should have 2 text elements"

    @pytest.mark.asyncio
    async def test_extract_structured_text_first_element_content(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with header element
        WHEN _extract_structured_text is called
        THEN first element should preserve content correctly
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        element1 = result['pages'][0]['elements'][0]
        assert element1['content'] == 'Chapter 1: Introduction', "First element content should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_first_element_type_normalization(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with header subtype
        WHEN _extract_structured_text is called
        THEN first element type should be normalized from subtype
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        element1 = result['pages'][0]['elements'][0]
        assert element1['type'] == 'header', "First element type should be normalized from subtype"

    @pytest.mark.asyncio
    async def test_extract_structured_text_first_element_confidence(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with confidence metadata
        WHEN _extract_structured_text is called
        THEN first element should preserve confidence value
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        element1 = result['pages'][0]['elements'][0]
        assert element1['confidence'] == 0.95, "First element confidence should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_first_element_position(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with position metadata
        WHEN _extract_structured_text is called
        THEN first element should preserve complete position metadata
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        element1 = result['pages'][0]['elements'][0]
        assert element1['position'] == {'x': 100, 'y': 50}, "First element position metadata should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_first_element_style(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with style metadata
        WHEN _extract_structured_text is called
        THEN first element should preserve complete style metadata
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        element1 = result['pages'][0]['elements'][0]
        assert element1['style'] == {'font_size': 18, 'bold': True}, "First element style metadata should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_second_element_content(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with paragraph element
        WHEN _extract_structured_text is called
        THEN second element should preserve content correctly
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        element2 = result['pages'][0]['elements'][1]
        assert element2['content'] == 'This is the introduction paragraph with important content.', "Second element content should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_second_element_type_normalization(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with paragraph subtype
        WHEN _extract_structured_text is called
        THEN second element type should be normalized from subtype
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        element2 = result['pages'][0]['elements'][1]
        assert element2['type'] == 'paragraph', "Second element type should be normalized from subtype"

    @pytest.mark.asyncio
    async def test_extract_structured_text_second_element_confidence(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with confidence metadata
        WHEN _extract_structured_text is called
        THEN second element should preserve confidence value
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        element2 = result['pages'][0]['elements'][1]
        assert element2['confidence'] == 0.89, "Second element confidence should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_second_element_position(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with position metadata
        WHEN _extract_structured_text is called
        THEN second element should preserve complete position metadata
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        element2 = result['pages'][0]['elements'][1]
        assert element2['position'] == {'x': 100, 'y': 100}, "Second element position metadata should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_second_element_style(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with style metadata
        WHEN _extract_structured_text is called
        THEN second element should preserve complete style metadata
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        element2 = result['pages'][0]['elements'][1]
        assert element2['style'] == {'font_size': 12, 'bold': False}, "Second element style metadata should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_full_text_contains_header(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with header content
        WHEN _extract_structured_text is called
        THEN full_text should contain header content
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        page1 = result['pages'][0]
        assert 'Chapter 1: Introduction' in page1['full_text'], "Full text should contain header content"

    @pytest.mark.asyncio
    async def test_extract_structured_text_full_text_contains_paragraph(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with paragraph content
        WHEN _extract_structured_text is called
        THEN full_text should contain paragraph content
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        page1 = result['pages'][0]
        assert 'This is the introduction paragraph' in page1['full_text'], "Full text should contain paragraph content"

    @pytest.mark.asyncio
    async def test_extract_structured_text_second_page_element_count(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with 1 element on second page
        WHEN _extract_structured_text is called
        THEN second page should have 1 element
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        page2 = result['pages'][1]
        assert len(page2['elements']) == 1, "Second page should have 1 element"

    @pytest.mark.asyncio
    async def test_extract_structured_text_table_element_type_normalization(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with table caption subtype
        WHEN _extract_structured_text is called
        THEN table element type should be normalized from subtype
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        page2 = result['pages'][1]
        assert page2['elements'][0]['type'] == 'caption', "Table element type should be normalized from subtype"

    @pytest.mark.asyncio
    async def test_extract_structured_text_table_element_content(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with table caption content
        WHEN _extract_structured_text is called
        THEN table element should preserve content
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        page2 = result['pages'][1]
        assert page2['elements'][0]['content'] == 'Table: Sample Data', "Table element content should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_table_element_position(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with table position metadata
        WHEN _extract_structured_text is called
        THEN table element should preserve position metadata
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        page2 = result['pages'][1]
        assert page2['elements'][0]['position'] == {'x': 100, 'y': 200}, "Table element position should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_table_element_style(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with table style metadata
        WHEN _extract_structured_text is called
        THEN table element should preserve style metadata
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        page2 = result['pages'][1]
        assert page2['elements'][0]['style'] == {'font_size': 10, 'italic': True}, "Table element style should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_table_element_confidence(self, optimizer, decomposed_content_valid):
        """
        GIVEN valid decomposed_content with table confidence metadata
        WHEN _extract_structured_text is called
        THEN table element should preserve confidence value
        """
        result = await optimizer._extract_structured_text(decomposed_content_valid)
        page2 = result['pages'][1]
        assert page2['elements'][0]['confidence'] == 0.92, "Table element confidence should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_missing_pages_raises_keyerror(self, optimizer):
        """
        GIVEN decomposed_content missing 'pages' key
        WHEN _extract_structured_text is called
        THEN KeyError should be raised
        """
        decomposed_content = {
            'metadata': {'document_type': 'test'},
            'structure': {}
        }
        
        with pytest.raises(KeyError, match="pages"):
            await optimizer._extract_structured_text(decomposed_content)

    @pytest.fixture
    def decomposed_content_empty_pages(self):
        """Create decomposed content with empty pages for testing."""
        return {
            'pages': [],
            'metadata': {'document_type': 'empty_doc'},
            'structure': {}
        }

    @pytest.mark.asyncio
    async def test_extract_structured_text_empty_pages_returns_dict(self, optimizer, decomposed_content_empty_pages):
        """
        GIVEN decomposed_content with empty pages list
        WHEN _extract_structured_text is called
        THEN result should be a dictionary
        """
        result = await optimizer._extract_structured_text(decomposed_content_empty_pages)
        assert isinstance(result, dict), "Result should be a dictionary"

    @pytest.mark.asyncio
    async def test_extract_structured_text_empty_pages_contains_pages_key(self, optimizer, decomposed_content_empty_pages):
        """
        GIVEN decomposed_content with empty pages list
        WHEN _extract_structured_text is called
        THEN result should contain 'pages' key
        """
        result = await optimizer._extract_structured_text(decomposed_content_empty_pages)
        assert 'pages' in result, "Result should contain 'pages' key"

    @pytest.mark.asyncio
    async def test_extract_structured_text_empty_pages_contains_metadata_key(self, optimizer, decomposed_content_empty_pages):
        """
        GIVEN decomposed_content with empty pages list
        WHEN _extract_structured_text is called
        THEN result should contain 'metadata' key
        """
        result = await optimizer._extract_structured_text(decomposed_content_empty_pages)
        assert 'metadata' in result, "Result should contain 'metadata' key"

    @pytest.mark.asyncio
    async def test_extract_structured_text_empty_pages_contains_structure_key(self, optimizer, decomposed_content_empty_pages):
        """
        GIVEN decomposed_content with empty pages list
        WHEN _extract_structured_text is called
        THEN result should contain 'structure' key
        """
        result = await optimizer._extract_structured_text(decomposed_content_empty_pages)
        assert 'structure' in result, "Result should contain 'structure' key"

    @pytest.mark.asyncio
    async def test_extract_structured_text_empty_pages_zero_page_count(self, optimizer, decomposed_content_empty_pages):
        """
        GIVEN decomposed_content with empty pages list
        WHEN _extract_structured_text is called
        THEN result should have 0 pages
        """
        result = await optimizer._extract_structured_text(decomposed_content_empty_pages)
        assert len(result['pages']) == 0, "Should have 0 pages"

    @pytest.mark.asyncio
    async def test_extract_structured_text_empty_pages_preserves_metadata(self, optimizer, decomposed_content_empty_pages):
        """
        GIVEN decomposed_content with empty pages and specific metadata
        WHEN _extract_structured_text is called
        THEN metadata document_type should be preserved
        """
        result = await optimizer._extract_structured_text(decomposed_content_empty_pages)
        assert result['metadata']['document_type'] == 'empty_doc', "Metadata document_type should be preserved"

    @pytest.fixture
    def decomposed_content_filtering(self):
        """Create decomposed content with various element types for filtering tests."""
        return {
            'pages': [
                {
                    'elements': [
                        {
                            'content': '',  # Empty content - will be included since it's type='text'
                            'type': 'text',
                            'subtype': 'paragraph',
                            'position': {'x': 0, 'y': 0},
                            'style': {},
                            'confidence': 0.9
                        },
                        {
                            'content': '   ',  # Whitespace only - will be included since it's type='text'
                            'type': 'text',
                            'subtype': 'paragraph',
                            'position': {'x': 10, 'y': 10},
                            'style': {},
                            'confidence': 0.8
                        },
                        {
                            'content': 'Valid header content',
                            'type': 'text',
                            'subtype': 'header',
                            'position': {'x': 100, 'y': 50},
                            'style': {'font_size': 18},
                            'confidence': 0.95
                        },
                        {
                            'content': 'Valid paragraph content',
                            'type': 'text',
                            'subtype': 'paragraph',
                            'position': {'x': 100, 'y': 100},
                            'style': {'font_size': 12},
                            'confidence': 0.88
                        },
                        {
                            'content': 'Table data',
                            'type': 'table',
                            'subtype': 'data',
                            'position': {'x': 200, 'y': 200},
                            'style': {'border': True},
                            'confidence': 0.92
                        }
                    ]
                }
            ],
            'metadata': {}
        }

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_element_count(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with various element types including empty content
        WHEN _extract_structured_text is called
        THEN all 5 elements should be processed including empty ones
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        assert len(page['elements']) == 5, "Should have 5 elements (all elements including empty ones are processed)"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_has_paragraph_type(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with paragraph subtypes
        WHEN _extract_structured_text is called
        THEN result should have normalized paragraph type
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        element_types = [elem['type'] for elem in page['elements']]
        assert 'paragraph' in element_types, "Should have normalized paragraph type"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_has_header_type(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with header subtype
        WHEN _extract_structured_text is called
        THEN result should have normalized header type
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        element_types = [elem['type'] for elem in page['elements']]
        assert 'header' in element_types, "Should have normalized header type"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_has_data_type(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with table data subtype
        WHEN _extract_structured_text is called
        THEN result should have table subtype as type
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        element_types = [elem['type'] for elem in page['elements']]
        assert 'data' in element_types, "Should have table subtype as type"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_valid_header_type(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with valid header element
        WHEN _extract_structured_text is called
        THEN valid header should have normalized type
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        valid_header = next(elem for elem in page['elements'] if elem['content'] == 'Valid header content')
        assert valid_header['type'] == 'header', "Valid header type should be normalized from subtype"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_valid_header_position(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with valid header element
        WHEN _extract_structured_text is called
        THEN valid header should preserve position metadata
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        valid_header = next(elem for elem in page['elements'] if elem['content'] == 'Valid header content')
        assert valid_header['position'] == {'x': 100, 'y': 50}, "Valid header position should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_valid_header_style(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with valid header element
        WHEN _extract_structured_text is called
        THEN valid header should preserve style metadata
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        valid_header = next(elem for elem in page['elements'] if elem['content'] == 'Valid header content')
        assert valid_header['style'] == {'font_size': 18}, "Valid header style should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_valid_header_confidence(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with valid header element
        WHEN _extract_structured_text is called
        THEN valid header should preserve confidence value
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        valid_header = next(elem for elem in page['elements'] if elem['content'] == 'Valid header content')
        assert valid_header['confidence'] == 0.95, "Valid header confidence should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_valid_paragraph_type(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with valid paragraph element
        WHEN _extract_structured_text is called
        THEN valid paragraph should have normalized type
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        valid_paragraph = next(elem for elem in page['elements'] if elem['content'] == 'Valid paragraph content')
        assert valid_paragraph['type'] == 'paragraph', "Valid paragraph type should be normalized from subtype"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_valid_paragraph_position(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with valid paragraph element
        WHEN _extract_structured_text is called
        THEN valid paragraph should preserve position metadata
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        valid_paragraph = next(elem for elem in page['elements'] if elem['content'] == 'Valid paragraph content')
        assert valid_paragraph['position'] == {'x': 100, 'y': 100}, "Valid paragraph position should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_valid_paragraph_style(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with valid paragraph element
        WHEN _extract_structured_text is called
        THEN valid paragraph should preserve style metadata
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        valid_paragraph = next(elem for elem in page['elements'] if elem['content'] == 'Valid paragraph content')
        assert valid_paragraph['style'] == {'font_size': 12}, "Valid paragraph style should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_valid_paragraph_confidence(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with valid paragraph element
        WHEN _extract_structured_text is called
        THEN valid paragraph should preserve confidence value
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        valid_paragraph = next(elem for elem in page['elements'] if elem['content'] == 'Valid paragraph content')
        assert valid_paragraph['confidence'] == 0.88, "Valid paragraph confidence should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_empty_element_type(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with empty content element
        WHEN _extract_structured_text is called
        THEN empty element should have normalized type
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        empty_elem = next(elem for elem in page['elements'] if elem['content'] == '')
        assert empty_elem['type'] == 'paragraph', "Empty element type should be normalized"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_empty_element_position(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with empty content element
        WHEN _extract_structured_text is called
        THEN empty element should preserve position metadata
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        empty_elem = next(elem for elem in page['elements'] if elem['content'] == '')
        assert empty_elem['position'] == {'x': 0, 'y': 0}, "Empty element position should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_empty_element_style(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with empty content element
        WHEN _extract_structured_text is called
        THEN empty element should preserve style metadata
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        empty_elem = next(elem for elem in page['elements'] if elem['content'] == '')
        assert empty_elem['style'] == {}, "Empty element style should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_empty_element_confidence(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with empty content element
        WHEN _extract_structured_text is called
        THEN empty element should preserve confidence value
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        empty_elem = next(elem for elem in page['elements'] if elem['content'] == '')
        assert empty_elem['confidence'] == 0.9, "Empty element confidence should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_whitespace_element_type(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with whitespace content element
        WHEN _extract_structured_text is called
        THEN whitespace element should have normalized type
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        whitespace_elem = next(elem for elem in page['elements'] if elem['content'] == '   ')
        assert whitespace_elem['type'] == 'paragraph', "Whitespace element type should be normalized"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_whitespace_element_position(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with whitespace content element
        WHEN _extract_structured_text is called
        THEN whitespace element should preserve position metadata
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        whitespace_elem = next(elem for elem in page['elements'] if elem['content'] == '   ')
        assert whitespace_elem['position'] == {'x': 10, 'y': 10}, "Whitespace element position should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_whitespace_element_style(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with whitespace content element
        WHEN _extract_structured_text is called
        THEN whitespace element should preserve style metadata
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        whitespace_elem = next(elem for elem in page['elements'] if elem['content'] == '   ')
        assert whitespace_elem['style'] == {}, "Whitespace element style should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_whitespace_element_confidence(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with whitespace content element
        WHEN _extract_structured_text is called
        THEN whitespace element should preserve confidence value
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        whitespace_elem = next(elem for elem in page['elements'] if elem['content'] == '   ')
        assert whitespace_elem['confidence'] == 0.8, "Whitespace element confidence should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_content_includes_valid_header(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with valid header content
        WHEN _extract_structured_text is called
        THEN result contents should include valid header content
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        contents = [elem['content'] for elem in page['elements']]
        assert 'Valid header content' in contents, "Contents should include valid header content"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_content_includes_valid_paragraph(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with valid paragraph content
        WHEN _extract_structured_text is called
        THEN result contents should include valid paragraph content
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        contents = [elem['content'] for elem in page['elements']]
        assert 'Valid paragraph content' in contents, "Contents should include valid paragraph content"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_content_includes_empty(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with empty content element
        WHEN _extract_structured_text is called
        THEN result contents should include empty content
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        contents = [elem['content'] for elem in page['elements']]
        assert '' in contents, "Contents should include empty content"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_content_includes_whitespace(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with whitespace content element
        WHEN _extract_structured_text is called
        THEN result contents should include whitespace content
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        contents = [elem['content'] for elem in page['elements']]
        assert '   ' in contents, "Contents should include whitespace content"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_content_includes_table_data(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with table data element
        WHEN _extract_structured_text is called
        THEN result contents should include table data content
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        contents = [elem['content'] for elem in page['elements']]
        assert 'Table data' in contents, "Contents should include table data content"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_full_text_includes_valid_header(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with valid header content
        WHEN _extract_structured_text is called
        THEN full_text should include valid header content
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        full_text = page['full_text']
        assert 'Valid header content' in full_text, "Full text should include valid header content"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_full_text_includes_valid_paragraph(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with valid paragraph content
        WHEN _extract_structured_text is called
        THEN full_text should include valid paragraph content
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        full_text = page['full_text']
        assert 'Valid paragraph content' in full_text, "Full text should include valid paragraph content"

    @pytest.mark.asyncio
    async def test_extract_structured_text_filtering_full_text_includes_table_data(self, optimizer, decomposed_content_filtering):
        """
        GIVEN decomposed_content with table data content
        WHEN _extract_structured_text is called
        THEN full_text should include table data content
        """
        result = await optimizer._extract_structured_text(decomposed_content_filtering)
        page = result['pages'][0]
        full_text = page['full_text']
        assert 'Table data' in full_text, "Full text should include table data content"

    @pytest.fixture
    def decomposed_content_rich_metadata(self):
        """Create decomposed content with rich metadata for testing."""
        original_metadata = {
            'document_type': 'research_paper',
            'author': 'Dr. Smith',
            'creation_date': '2024-01-01',
            'total_pages': 1,
            'language': 'en'
        }
        
        return {
            'pages': [
                {
                    'elements': [
                        {
                            'content': 'Sample content',
                            'type': 'text',
                            'confidence': 0.9
                        }
                    ]
                }
            ],
            'metadata': original_metadata,
            'structure': {
                'sections': ['introduction', 'methodology'],
                'has_tables': True,
                'has_figures': False
            }
        }

    @pytest.mark.asyncio
    async def test_extract_structured_text_metadata_preserves_document_type(self, optimizer, decomposed_content_rich_metadata):
        """
        GIVEN decomposed_content with document_type metadata
        WHEN _extract_structured_text is called
        THEN document_type should be preserved in result metadata
        """
        result = await optimizer._extract_structured_text(decomposed_content_rich_metadata)
        result_metadata = result['metadata']
        assert 'document_type' in result_metadata, "Original metadata key 'document_type' should be preserved"
        assert result_metadata['document_type'] == 'research_paper', "Original metadata value for 'document_type' should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_metadata_preserves_author(self, optimizer, decomposed_content_rich_metadata):
        """
        GIVEN decomposed_content with author metadata
        WHEN _extract_structured_text is called
        THEN author should be preserved in result metadata
        """
        result = await optimizer._extract_structured_text(decomposed_content_rich_metadata)
        result_metadata = result['metadata']
        assert 'author' in result_metadata, "Original metadata key 'author' should be preserved"
        assert result_metadata['author'] == 'Dr. Smith', "Original metadata value for 'author' should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_metadata_preserves_creation_date(self, optimizer, decomposed_content_rich_metadata):
        """
        GIVEN decomposed_content with creation_date metadata
        WHEN _extract_structured_text is called
        THEN creation_date should be preserved in result metadata
        """
        result = await optimizer._extract_structured_text(decomposed_content_rich_metadata)
        result_metadata = result['metadata']
        assert 'creation_date' in result_metadata, "Original metadata key 'creation_date' should be preserved"
        assert result_metadata['creation_date'] == '2024-01-01', "Original metadata value for 'creation_date' should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_metadata_preserves_total_pages(self, optimizer, decomposed_content_rich_metadata):
        """
        GIVEN decomposed_content with total_pages metadata
        WHEN _extract_structured_text is called
        THEN total_pages should be preserved in result metadata
        """
        result = await optimizer._extract_structured_text(decomposed_content_rich_metadata)
        result_metadata = result['metadata']
        assert 'total_pages' in result_metadata, "Original metadata key 'total_pages' should be preserved"
        assert result_metadata['total_pages'] == 1, "Original metadata value for 'total_pages' should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_metadata_preserves_language(self, optimizer, decomposed_content_rich_metadata):
        """
        GIVEN decomposed_content with language metadata
        WHEN _extract_structured_text is called
        THEN language should be preserved in result metadata
        """
        result = await optimizer._extract_structured_text(decomposed_content_rich_metadata)
        result_metadata = result['metadata']
        assert 'language' in result_metadata, "Original metadata key 'language' should be preserved"
        assert result_metadata['language'] == 'en', "Original metadata value for 'language' should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_structure_preservation_contains_structure(self, optimizer, decomposed_content_rich_metadata):
        """
        GIVEN decomposed_content with structure information
        WHEN _extract_structured_text is called
        THEN result should contain structure field
        """
        result = await optimizer._extract_structured_text(decomposed_content_rich_metadata)
        assert 'structure' in result, "Structure should be preserved"

    @pytest.mark.asyncio
    async def test_extract_structured_text_structure_preservation_has_sections(self, optimizer, decomposed_content_rich_metadata):
        """
        GIVEN decomposed_content with sections in structure
        WHEN _extract_structured_text is called
        THEN structure should contain sections field
        """
        result = await optimizer._extract_structured_text(decomposed_content_rich_metadata)
        result_structure = result['structure']
        assert 'sections' in result_structure, "Structure should contain sections field"

    @pytest.mark.asyncio
    async def test_extract_structured_text_structure_preservation_sections_values(self, optimizer, decomposed_content_rich_metadata):
        """
        GIVEN decomposed_content with specific sections
        WHEN _extract_structured_text is called
        THEN sections should preserve original values
        """
        result = await optimizer._extract_structured_text(decomposed_content_rich_metadata)
        result_structure = result['structure']
        assert result_structure['sections'] == ['introduction', 'methodology'], "Sections should preserve original values"

    @pytest.mark.asyncio
    async def test_extract_structured_text_structure_preservation_has_tables_true(self, optimizer, decomposed_content_rich_metadata):
        """
        GIVEN decomposed_content with has_tables=True
        WHEN _extract_structured_text is called
        THEN has_tables should be preserved as True
        """
        result = await optimizer._extract_structured_text(decomposed_content_rich_metadata)
        result_structure = result['structure']
        assert result_structure['has_tables'] is True, "has_tables should be preserved as True"

    @pytest.mark.asyncio
    async def test_extract_structured_text_structure_preservation_has_figures_false(self, optimizer, decomposed_content_rich_metadata):
        """
        GIVEN decomposed_content with has_figures=False
        WHEN _extract_structured_text is called
        THEN has_figures should be preserved as False
        """
        result = await optimizer._extract_structured_text(decomposed_content_rich_metadata)
        result_structure = result['structure']
        assert result_structure['has_figures'] is False, "has_figures should be preserved as False"

    @pytest.mark.asyncio
    async def test_extract_structured_text_hierarchical_organization_one_page(self, optimizer, decomposed_content_rich_metadata):
        """
        GIVEN decomposed_content with one page
        WHEN _extract_structured_text is called
        THEN result should have one page in hierarchical organization
        """
        result = await optimizer._extract_structured_text(decomposed_content_rich_metadata)
        assert len(result['pages']) == 1, "Should have one page in hierarchical organization"

    @pytest.mark.asyncio
    async def test_extract_structured_text_hierarchical_organization_page_has_page_number(self, optimizer, decomposed_content_rich_metadata):
        """
        GIVEN decomposed_content with page structure
        WHEN _extract_structured_text is called
        THEN page should have page_number field
        """
        result = await optimizer._extract_structured_text(decomposed_content_rich_metadata)
        page = result['pages'][0]
        assert 'page_number' in page, "Page should have page_number field"

    @pytest.mark.asyncio
    async def test_extract_structured_text_hierarchical_organization_page_has_elements(self, optimizer, decomposed_content_rich_metadata):
        """
        GIVEN decomposed_content with page structure
        WHEN _extract_structured_text is called
        THEN page should have elements field
        """
        result = await optimizer._extract_structured_text(decomposed_content_rich_metadata)
        page = result['pages'][0]
        assert 'elements' in page, "Page should have elements field"

    @pytest.mark.asyncio
    async def test_extract_structured_text_hierarchical_organization_page_has_full_text(self, optimizer, decomposed_content_rich_metadata):
        """
        GIVEN decomposed_content with page structure
        WHEN _extract_structured_text is called
        THEN page should have full_text field
        """
        result = await optimizer._extract_structured_text(decomposed_content_rich_metadata)
        page = result['pages'][0]
        assert 'full_text' in page, "Page should have full_text field"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
