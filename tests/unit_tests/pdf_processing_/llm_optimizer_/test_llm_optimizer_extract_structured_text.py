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


class TestLLMOptimizerExtractStructuredText:
    """Test LLMOptimizer._extract_structured_text method."""

    @pytest.fixture
    def optimizer(self):
        """Create LLMOptimizer instance for testing."""
        return LLMOptimizer()

    @pytest.mark.asyncio
    async def test_extract_structured_text_valid_content(self, optimizer):
        """
        GIVEN valid decomposed_content with pages and elements
        WHEN _extract_structured_text is called
        THEN expect:
            - Structured text format returned
            - Pages organized correctly
            - Element metadata preserved
            - full_text generated for each page
        """
        # Given
        decomposed_content = {
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
        
        # When
        result = await optimizer._extract_structured_text(decomposed_content)
        
        # Then
        assert isinstance(result, dict), "Result should be a dictionary"
        assert 'pages' in result, "Result should contain 'pages' key"
        assert 'metadata' in result, "Result should contain 'metadata' key"
        assert 'structure' in result, "Result should contain 'structure' key"
        
        # Check pages structure
        assert len(result['pages']) == 2, "Should have 2 pages"
        
        # Check first page
        page1 = result['pages'][0]
        assert 'page_number' in page1, "Page should have page_number"
        assert 'elements' in page1, "Page should have elements"
        assert 'full_text' in page1, "Page should have full_text"
        assert len(page1['elements']) == 2, "First page should have 2 text elements"
        
        # Check element preservation - ALL metadata should be preserved
        element1 = page1['elements'][0]
        assert element1['content'] == 'Chapter 1: Introduction'
        assert element1['type'] == 'header'  # Should be normalized from subtype
        assert element1['confidence'] == 0.95
        assert element1['position'] == {'x': 100, 'y': 50}  # Complete position metadata
        assert element1['style'] == {'font_size': 18, 'bold': True}  # Complete style metadata
        
        element2 = page1['elements'][1]
        assert element2['content'] == 'This is the introduction paragraph with important content.'
        assert element2['type'] == 'paragraph'  # Should be normalized from subtype
        assert element2['confidence'] == 0.89
        assert element2['position'] == {'x': 100, 'y': 100}  # Complete position metadata
        assert element2['style'] == {'font_size': 12, 'bold': False}  # Complete style metadata
        
        # Check full_text generation
        assert 'Chapter 1: Introduction' in page1['full_text']
        assert 'This is the introduction paragraph' in page1['full_text']
        
        # Check second page (table element should be normalized to its subtype)
        page2 = result['pages'][1]
        assert len(page2['elements']) == 1, "Second page should have 1 element"
        assert page2['elements'][0]['type'] == 'caption'  # Normalized from subtype
        assert page2['elements'][0]['content'] == 'Table: Sample Data'
        assert page2['elements'][0]['position'] == {'x': 100, 'y': 200}
        assert page2['elements'][0]['style'] == {'font_size': 10, 'italic': True}
        assert page2['elements'][0]['confidence'] == 0.92

    @pytest.mark.asyncio
    async def test_extract_structured_text_missing_pages(self, optimizer):
        """
        GIVEN decomposed_content missing 'pages' key
        WHEN _extract_structured_text is called
        THEN expect KeyError to be raised
        """
        # Given
        decomposed_content = {
            'metadata': {'document_type': 'test'},
            'structure': {}
        }
        
        # When/Then
        with pytest.raises(KeyError, match="pages"):
            await optimizer._extract_structured_text(decomposed_content)

    @pytest.mark.asyncio
    async def test_extract_structured_text_empty_pages(self, optimizer):
        """
        GIVEN decomposed_content with empty pages list
        WHEN _extract_structured_text is called
        THEN expect:
            - Empty structured text returned
            - No errors raised
            - Proper structure maintained
        """
        # Given
        decomposed_content = {
            'pages': [],
            'metadata': {'document_type': 'empty_doc'},
            'structure': {}
        }
        
        # When
        result = await optimizer._extract_structured_text(decomposed_content)
        
        # Then
        assert isinstance(result, dict), "Result should be a dictionary"
        assert 'pages' in result, "Result should contain 'pages' key"
        assert 'metadata' in result, "Result should contain 'metadata' key"
        assert 'structure' in result, "Result should contain 'structure' key"
        assert len(result['pages']) == 0, "Should have 0 pages"
        assert result['metadata']['document_type'] == 'empty_doc'

    @pytest.mark.asyncio
    async def test_extract_structured_text_element_filtering(self, optimizer):
        """
        GIVEN decomposed_content with various element types and empty content
        WHEN _extract_structured_text is called
        THEN expect:
            - Empty content elements filtered out
            - Element types normalized correctly
            - Valid elements preserved
        """
        # Given
        decomposed_content = {
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
        
        # When
        result = await optimizer._extract_structured_text(decomposed_content)
        
        # Then
        page = result['pages'][0]
        assert len(page['elements']) == 5, "Should have 5 elements (all elements including empty ones are processed)"
        
        # Check element type normalization (should use subtype as type for text elements)
        element_types = [elem['type'] for elem in page['elements']]
        assert 'paragraph' in element_types, "Should have normalized paragraph type"
        assert 'header' in element_types, "Should have normalized header type"
        assert 'data' in element_types, "Should have table subtype as type"
        
        # Check ALL metadata is preserved for each element
        valid_header = next(elem for elem in page['elements'] if elem['content'] == 'Valid header content')
        assert valid_header['type'] == 'header'  # normalized from subtype
        assert valid_header['position'] == {'x': 100, 'y': 50}
        assert valid_header['style'] == {'font_size': 18}
        assert valid_header['confidence'] == 0.95
        
        valid_paragraph = next(elem for elem in page['elements'] if elem['content'] == 'Valid paragraph content')
        assert valid_paragraph['type'] == 'paragraph'  # normalized from subtype
        assert valid_paragraph['position'] == {'x': 100, 'y': 100}
        assert valid_paragraph['style'] == {'font_size': 12}
        assert valid_paragraph['confidence'] == 0.88
        
        # Check empty content elements are included with all metadata
        empty_elem = next(elem for elem in page['elements'] if elem['content'] == '')
        assert empty_elem['type'] == 'paragraph'
        assert empty_elem['position'] == {'x': 0, 'y': 0}
        assert empty_elem['style'] == {}
        assert empty_elem['confidence'] == 0.9
        
        whitespace_elem = next(elem for elem in page['elements'] if elem['content'] == '   ')
        assert whitespace_elem['type'] == 'paragraph'
        assert whitespace_elem['position'] == {'x': 10, 'y': 10}
        assert whitespace_elem['style'] == {}
        assert whitespace_elem['confidence'] == 0.8
        
        # Check content preservation (all elements including empty)
        contents = [elem['content'] for elem in page['elements']]
        assert 'Valid header content' in contents
        assert 'Valid paragraph content' in contents
        assert '' in contents  # Empty content included
        assert '   ' in contents  # Whitespace content included
        assert 'Table data' in contents  # Table data now included
        
        # Check full_text includes all element content (including empty)
        full_text = page['full_text']
        assert 'Valid header content' in full_text
        assert 'Valid paragraph content' in full_text
        assert 'Table data' in full_text
        # Note: empty content and whitespace will be in full_text but hard to test

    @pytest.mark.asyncio
    async def test_extract_structured_text_metadata_preservation(self, optimizer):
        """
        GIVEN decomposed_content with rich metadata
        WHEN _extract_structured_text is called
        THEN expect:
            - Original metadata preserved
            - Additional structure metadata added
            - Hierarchical organization maintained
        """
        # Given
        original_metadata = {
            'document_type': 'research_paper',
            'author': 'Dr. Smith',
            'creation_date': '2024-01-01',
            'total_pages': 1,
            'language': 'en'
        }
        
        decomposed_content = {
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
        
        # When
        result = await optimizer._extract_structured_text(decomposed_content)
        
        # Then
        # Check original metadata preservation
        result_metadata = result['metadata']
        for key, value in original_metadata.items():
            assert key in result_metadata, f"Original metadata key '{key}' should be preserved"
            assert result_metadata[key] == value, f"Original metadata value for '{key}' should be preserved"
        
        # Check structure preservation
        assert 'structure' in result, "Structure should be preserved"
        result_structure = result['structure']
        assert 'sections' in result_structure
        assert result_structure['sections'] == ['introduction', 'methodology']
        assert result_structure['has_tables'] is True
        assert result_structure['has_figures'] is False
        
        # Check hierarchical organization
        assert len(result['pages']) == 1
        page = result['pages'][0]
        assert 'page_number' in page
        assert 'elements' in page
        assert 'full_text' in page


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
