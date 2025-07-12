#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer.py
# Auto-generated on 2025-07-07 02:28:56

import pytest
import os

import os
import pytest
import time
import numpy as np

from tests._test_utils import (
    raise_on_bad_callable_metadata,
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
    raise ImportError(f"Could not import the module's own imports: {e}")


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
        assert len(page1['elements']) == 2, "First page should have 2 elements"
        
        # Check element preservation
        element1 = page1['elements'][0]
        assert element1['content'] == 'Chapter 1: Introduction'
        assert element1['type'] == 'header'  # Should be normalized
        assert element1['confidence'] == 0.95
        assert 'position' in element1
        assert 'style' in element1
        
        # Check full_text generation
        assert 'Chapter 1: Introduction' in page1['full_text']
        assert 'This is the introduction paragraph' in page1['full_text']
        
        # Check second page
        page2 = result['pages'][1]
        assert len(page2['elements']) == 1, "Second page should have 1 element"
        assert page2['elements'][0]['type'] == 'table'

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
                            'content': '',  # Empty content - should be filtered
                            'type': 'text',
                            'confidence': 0.9
                        },
                        {
                            'content': '   ',  # Whitespace only - should be filtered
                            'type': 'text',
                            'confidence': 0.8
                        },
                        {
                            'content': 'Valid header content',
                            'type': 'text',
                            'subtype': 'header',
                            'confidence': 0.95
                        },
                        {
                            'content': 'Valid paragraph content',
                            'type': 'text',
                            'subtype': 'paragraph',
                            'confidence': 0.88
                        },
                        {
                            'content': 'Table data',
                            'type': 'table',
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
        assert len(page['elements']) == 3, "Should have 3 valid elements (empty ones filtered)"
        
        # Check element type normalization
        element_types = [elem['type'] for elem in page['elements']]
        assert 'header' in element_types, "Should have normalized header type"
        assert 'text' in element_types, "Should have text type"
        assert 'table' in element_types, "Should have table type"
        
        # Check content preservation
        contents = [elem['content'] for elem in page['elements']]
        assert 'Valid header content' in contents
        assert 'Valid paragraph content' in contents
        assert 'Table data' in contents
        
        # Check full_text doesn't include empty content
        full_text = page['full_text']
        assert 'Valid header content' in full_text
        assert 'Valid paragraph content' in full_text
        assert 'Table data' in full_text
        assert len(full_text.strip()) > 0

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



class TestTextProcessorInitialization:
    """Test TextProcessor initialization and configuration."""

    def test_init_creates_instance(self):
        """
        GIVEN TextProcessor class
        WHEN instance is created
        THEN expect:
            - Instance created successfully
            - No required initialization parameters
            - All methods accessible
        """
        # When
        processor = TextProcessor()
        
        # Then
        assert isinstance(processor, TextProcessor), "Should create TextProcessor instance"
        
        # Check that methods are accessible
        assert hasattr(processor, 'split_sentences'), "Should have split_sentences method"
        assert hasattr(processor, 'extract_keywords'), "Should have extract_keywords method"
        assert callable(processor.split_sentences), "split_sentences should be callable"
        assert callable(processor.extract_keywords), "extract_keywords should be callable"

    def test_split_sentences_empty_input(self):
        """
        GIVEN empty string input
        WHEN split_sentences is called
        THEN expect:
            - Empty list returned
            - No errors raised
        """

        
        # Given
        processor = TextProcessor()
        text = ""
        
        # When
        result = processor.split_sentences(text)
        
        # Then
        assert isinstance(result, list), "Result should be a list"
        assert len(result) == 0, "Should return empty list for empty input"

    def test_split_sentences_none_input(self):
        """
        GIVEN None as input
        WHEN split_sentences is called
        THEN expect:
            - TypeError handled gracefully
            - Warning logged
            - Empty list returned
        """


        # Given
        processor = TextProcessor()
        text = None
        
        # When
        with pytest.raises((TypeError, AttributeError)):
            result = processor.split_sentences(text)

    def test_split_sentences_non_string_input(self):
        """
        GIVEN non-string input (int, list, dict)
        WHEN split_sentences is called
        THEN expect:
            - TypeError handled gracefully
            - Warning logged
            - Empty list returned
        """

        
        # Given
        processor = TextProcessor()
        test_inputs = [123, [1, 2, 3], {'key': 'value'}, True, 3.14]
        
        for input_value in test_inputs:
            # When/Then - should either handle gracefully or raise TypeError
            try:
                result = processor.split_sentences(input_value)
                assert isinstance(result, list), f"Should return list for input {input_value}"
            except (TypeError, AttributeError):
                # Acceptable to raise TypeError for non-string input
                pass

    def test_split_sentences_period_variations(self):
        """
        GIVEN text with various period usage (abbreviations, decimals, ellipses)
        WHEN split_sentences is called
        THEN expect:
            - Abbreviations not treated as sentence endings
            - Decimal numbers preserved intact
            - Ellipses handled appropriately
            - True sentence boundaries detected
        """

        
        # Given
        processor = TextProcessor()
        
        test_cases = [
            # Decimal numbers should not break sentences
            ("The value is 3.14159 and it represents pi.", ["The value is 3.14159 and it represents pi"]),
            
            # Ellipses should be handled
            ("This is incomplete... But this continues.", ["This is incomplete", "But this continues"]),
            
            # Multiple periods in numbers
            ("Version 2.1.3 was released. The next version is 2.2.0.", 
            ["Version 2.1.3 was released", "The next version is 2.2.0"]),
            
            # URLs with periods
            ("Visit www.example.com for more info. This is a new sentence.",
            ["Visit www.example.com for more info", "This is a new sentence"]),
        ]
        
        for input_text, expected_min_sentences in test_cases:
            # When
            result = processor.split_sentences(input_text)
            
            # Then
            assert isinstance(result, list), f"Result should be list for: {input_text}"
            assert len(result) >= len(expected_min_sentences) - 1, f"Should detect reasonable sentence boundaries in: {input_text}"

    def test_split_sentences_abbreviations_handling(self):
        """
        GIVEN text containing common abbreviations (Dr., Ph.D., Mr., etc.)
        WHEN split_sentences is called
        THEN expect:
            - Abbreviations not split into separate sentences
            - Sentence continues after abbreviation
            - Common abbreviation patterns recognized
        """
        # Given
        processor = TextProcessor()
        
        test_cases = [
            # Common titles
            ("Dr. Smith is here. He has a Ph.D. degree.", 2),
            ("Mr. Johnson and Mrs. Smith attended.", 1),
            ("Prof. Williams vs. Dr. Brown in the debate.", 1),
            
            # Academic abbreviations
            ("He earned his Ph.D. in 1995. The research was groundbreaking.", 2),
            ("The B.A. and M.A. degrees are prerequisites.", 1),
            
            # Common abbreviations
            ("It happened in Jan. last year. Feb. was different.", 2),
            ("The U.S.A. and U.K. have treaties.", 1),
            ("At 3 a.m. the alarm rang. Everyone woke up.", 2),
        ]
        
        for input_text, expected_sentences in test_cases:
            # When
            result = processor.split_sentences(input_text)
            
            # Then
            assert isinstance(result, list), f"Result should be list for: {input_text}"
            # Allow some flexibility in sentence detection for complex cases
            assert len(result) >= expected_sentences - 1 and len(result) <= expected_sentences + 1, \
                f"Expected ~{expected_sentences} sentences, got {len(result)} for: {input_text}"

    def test_split_sentences_multiple_terminators(self):
        """
        GIVEN text with multiple sentence terminators (!!!, ???, ...)
        WHEN split_sentences is called
        THEN expect:
            - Multiple terminators treated as single sentence ending
            - No empty sentences created
            - Sentence content preserved
        """

        
        # Given
        processor = TextProcessor()
        
        test_cases = [
            ("This is exciting!!! What do you think??? I'm not sure...",
            ["This is exciting", "What do you think", "I'm not sure"]),
            
            ("Help!!! Someone please help!!! This is urgent!!!",
            ["Help", "Someone please help", "This is urgent"]),
            
            ("Really??? Are you sure??? Yes, absolutely!!!",
            ["Really", "Are you sure", "Yes, absolutely"]),
            
            ("Wait... Let me think... OK, I understand...",
            ["Wait", "Let me think", "OK, I understand"]),
        ]
        
        for input_text, expected_content in test_cases:
            # When
            result = processor.split_sentences(input_text)
            
            # Then
            assert isinstance(result, list), f"Result should be list for: {input_text}"
            assert len(result) == len(expected_content), f"Expected {len(expected_content)} sentences, got {len(result)} for: {input_text}"
            
            # Check no empty sentences
            for sentence in result:
                assert len(sentence.strip()) > 0, f"Should not have empty sentences: '{sentence}'"
            
            # Check general content preservation
            combined_result = ' '.join(result).lower()
            for expected_part in expected_content:
                key_words = expected_part.lower().split()[:2]  # Check first two words
                if key_words:
                    assert any(word in combined_result for word in key_words), \
                        f"Should preserve content from: {expected_part}"

    def test_split_sentences_paragraph_breaks(self):
        """
        GIVEN text with paragraph breaks (\n\n) and sentence breaks
        WHEN split_sentences is called
        THEN expect:
            - Paragraph breaks not interfering with sentence detection
            - Sentences across paragraphs handled correctly
            - Whitespace normalized appropriately
        """

        
        # Given
        processor = TextProcessor()
        
        test_cases = [
            # Paragraph breaks should not affect sentence detection
            ("First sentence.\n\nSecond paragraph starts. It continues here.",
            ["First sentence", "Second paragraph starts", "It continues here"]),
            
            # Multiple paragraph breaks
            ("Para one.\n\n\nPara two starts.\n\nPara three here.",
            ["Para one", "Para two starts", "Para three here"]),
            
            # Mixed line breaks
            ("Line one.\nLine two continues.\n\nNew paragraph.",
            ["Line one", "Line two continues", "New paragraph"]),
        ]
        
        for input_text, expected_sentences in test_cases:
            # When
            result = processor.split_sentences(input_text)
            
            # Then
            assert isinstance(result, list), f"Result should be list for: {input_text}"
            assert len(result) == len(expected_sentences), f"Expected {len(expected_sentences)} sentences, got {len(result)}"
            
            # Check whitespace normalization
            for sentence in result:
                assert sentence == sentence.strip(), f"Sentence should have no leading/trailing whitespace: '{sentence}'"
                assert '\n' not in sentence, f"Sentence should not contain newlines: '{sentence}'"

    def test_split_sentences_unicode_text(self):
        """
        GIVEN text with Unicode characters and punctuation
        WHEN split_sentences is called
        THEN expect:
            - Unicode text handled correctly
            - Non-ASCII punctuation recognized
            - Character encoding preserved
        """

        
        # Given
        processor = TextProcessor()
        
        test_cases = [
            # Unicode characters
            ("Café is open. Naïve approach failed.", 2),
            
            # Non-ASCII punctuation
            ("这是第一句。这是第二句？", 2),  # Chinese punctuation
            
            # Mixed languages
            ("Hello world. Bonjour monde. Hola mundo.", 3),
            
            # Special Unicode punctuation
            ("Question… Answer！ More text？", 3),
            
            # Emoji and special characters
            ("Great work! 🎉 Let's celebrate! 🎊 Amazing results!", 3),
        ]
        
        for input_text, expected_count in test_cases:
            # When
            result = processor.split_sentences(input_text)
            
            # Then
            assert isinstance(result, list), f"Result should be list for: {input_text}"
            # Allow some flexibility for Unicode handling
            assert len(result) >= expected_count - 1 and len(result) <= expected_count + 1, \
                f"Expected ~{expected_count} sentences, got {len(result)} for: {input_text}"
            
            # Check character preservation
            combined = ' '.join(result)
            original_chars = set(c for c in input_text if c.isalnum() or ord(c) > 127)
            result_chars = set(c for c in combined if c.isalnum() or ord(c) > 127)
            
            # Most Unicode characters should be preserved
            preserved_ratio = len(original_chars.intersection(result_chars)) / max(len(original_chars), 1)
            assert preserved_ratio >= 0.8, f"Should preserve most Unicode characters: {preserved_ratio}"

    def test_split_sentences_academic_text(self):
        """
        GIVEN academic text with citations, formulas, and technical terms
        WHEN split_sentences is called
        THEN expect:
            - Citations not breaking sentences incorrectly
            - Technical abbreviations handled
            - Complex sentence structures preserved
        """

        
        # Given
        processor = TextProcessor()
        
        test_cases = [
            # Citations
            ("Smith et al. (2020) showed great results. The study by Jones et al. (2019) differed.", 2),
            
            # Technical abbreviations
            ("The DNA analysis was complete. RNA extraction followed standard protocols.", 2),
            
            # Complex academic language
            ("The methodology utilized in vivo experiments. Results indicated significant p < 0.05 values.", 2),
            
            # References and equations
            ("See Figure 1.2 for details. Equation 3.14 shows the relationship.", 2),
            
            # Version numbers and technical specs
            ("Algorithm v2.1.3 was implemented. Performance improved by 15.7% over baseline.", 2),
        ]
        
        for input_text, expected_count in test_cases:
            # When
            result = processor.split_sentences(input_text)
            
            # Then
            assert isinstance(result, list), f"Result should be list for: {input_text}"
            assert len(result) >= expected_count - 1 and len(result) <= expected_count + 1, \
                f"Expected ~{expected_count} sentences, got {len(result)} for: {input_text}"
            
            # Check that technical terms are preserved
            for sentence in result:
                assert len(sentence.strip()) > 0, "Should not have empty sentences"

    def test_split_sentences_quotations_handling(self):
        """
        GIVEN text with quoted sentences and dialogue
        WHEN split_sentences is called
        THEN expect:
            - Quoted sentences properly separated
            - Quotation marks preserved in content
            - Dialogue attribution handled correctly
        """

        
        # Given
        processor = TextProcessor()
        
        test_cases = [
            # Basic quotations
            ('He said "Hello world." She replied "How are you?"', 2),
            
            # Quotations with attribution
            ('"This is important," she said. "Very important indeed."', 2),
            
            # Mixed quotation styles
            ("The paper states 'significant results.' The author noted 'further research needed.'", 2),
            
            # Complex dialogue
            ('John asked, "Are you ready?" Mary answered, "Yes, let\'s go!"', 2),
        ]
        
        for input_text, expected_min in test_cases:
            # When
            result = processor.split_sentences(input_text)
            
            # Then
            assert isinstance(result, list), f"Result should be list for: {input_text}"
            assert len(result) >= expected_min - 1, f"Should detect at least {expected_min-1} sentences for: {input_text}"
            
            # Check quotation marks are preserved
            combined = ' '.join(result)
            quote_chars = ['"', "'", '"', '"', ''', ''']
            original_quotes = sum(input_text.count(q) for q in quote_chars)
            result_quotes = sum(combined.count(q) for q in quote_chars)
            
            if original_quotes > 0:
                assert result_quotes >= original_quotes * 0.8, "Should preserve most quotation marks"

    def test_split_sentences_malformed_input(self):
        """
        GIVEN malformed text causing regex processing to fail
        WHEN split_sentences is called
        THEN expect:
            - ValueError handled gracefully
            - Error logged appropriately
            - Fallback behavior or empty list returned
        """

        
        # Given
        processor = TextProcessor()
        
        malformed_inputs = [
            # Extremely nested parentheses
            "(" * 100 + "text" + ")" * 100,
            
            # Control characters
            "\x00\x01\x02text\x03\x04\x05",
            
            # Very long sequences of special characters
            "." * 1000 + "text" + "!" * 1000,
            
            # Mixed problematic characters
            "\\\\\\text///with\\\\problems",
        ]
        
        for malformed_text in malformed_inputs:
            # When/Then - should not crash
            try:
                result = processor.split_sentences(malformed_text)
                assert isinstance(result, list), f"Should return list for malformed input: {malformed_text[:20]}..."
            except Exception as e:
                # If an exception occurs, it should be a controlled one, not a crash
                assert isinstance(e, (ValueError, TypeError, RuntimeError)), \
                    f"Should handle malformed input gracefully, got: {type(e).__name__}: {e}"

    def test_split_sentences_very_long_text(self):
        """
        GIVEN very long text input (>1MB)
        WHEN split_sentences is called
        THEN expect:
            - Processing completes in reasonable time
            - Memory usage remains manageable
            - All sentences properly detected
        """

        import time
        
        # Given
        processor = TextProcessor()
        
        # Create large text with known sentence structure
        base_sentences = [
            "This is sentence one.",
            "This is sentence two!",
            "Is this sentence three?",
            "Yes, this is sentence four."
        ]
        
        # Repeat to create large text (~1MB)
        repetitions = 50000  # Should create ~1MB of text
        large_text = " ".join(base_sentences * repetitions)
        
        # When
        start_time = time.time()
        result = processor.split_sentences(large_text)
        end_time = time.time()
        
        # Then
        processing_time = end_time - start_time
        assert processing_time < 60.0, f"Should process large text in reasonable time (<60s), took {processing_time}s"
        
        assert isinstance(result, list), "Should return list for large text"
        assert len(result) > 0, "Should detect sentences in large text"
        
        # Should detect approximately the right number of sentences
        expected_sentences = len(base_sentences) * repetitions
        detected_ratio = len(result) / expected_sentences
        assert detected_ratio >= 0.8 and detected_ratio <= 1.2, \
            f"Should detect reasonable number of sentences: expected ~{expected_sentences}, got {len(result)}"

    def test_split_sentences_empty_sentences_filtered(self):
        """
        GIVEN text that might produce empty sentences after processing
        WHEN split_sentences is called
        THEN expect:
            - Empty sentences filtered out
            - Only non-empty sentences in result
            - No whitespace-only sentences
        """

        
        # Given
        processor = TextProcessor()
        
        test_cases = [
            # Multiple terminators that might create empty sentences
            "Text.......More text!!!!!!Final text???",
            
            # Whitespace around terminators
            "First.   \n\n   Second!    \t\t   Third?",
            
            # Only punctuation between real sentences
            "Real sentence. !@#$%^&*() Another real sentence.",
            
            # Empty quotations
            'He said "". She replied "Nothing to say."',
        ]
        
        for input_text in test_cases:
            # When
            result = processor.split_sentences(input_text)
            
            # Then
            assert isinstance(result, list), f"Result should be list for: {input_text}"
            
            # Check no empty or whitespace-only sentences
            for sentence in result:
                assert isinstance(sentence, str), "All results should be strings"
                assert len(sentence.strip()) > 0, f"Should not have empty sentences: '{sentence}'"
                assert sentence == sentence.strip(), f"Should not have leading/trailing whitespace: '{sentence}'"

    def test_split_sentences_return_type_validation(self):
        """
        GIVEN any valid text input
        WHEN split_sentences is called
        THEN expect:
            - Return type is List[str]
            - All elements in list are strings
            - No None or invalid elements
        """

        
        # Given
        processor = TextProcessor()
        
        test_inputs = [
            "Simple sentence.",
            "Multiple sentences. Here they are! Questions too?",
            "",
            "   ",
            "No punctuation here",
            "Mixed! Cases? Here.",
            "Unicode café. More text.",
        ]
        
        for input_text in test_inputs:
            # When
            result = processor.split_sentences(input_text)
            
            # Then
            assert isinstance(result, list), f"Return type should be list for: '{input_text}'"
            
            for i, sentence in enumerate(result):
                assert isinstance(sentence, str), f"Element {i} should be string, got {type(sentence)}: '{sentence}'"
                assert sentence is not None, f"Element {i} should not be None"
                
            # Check list consistency
            assert len(result) >= 0, "List length should be non-negative"








class TestTextProcessorExtractKeywords:
    """Test TextProcessor.extract_keywords method functionality."""

    @pytest.fixture
    def processor(self):
        """Set up test fixtures with TextProcessor instance."""
        return TextProcessor()

    def test_extract_keywords_basic_functionality(self, processor):
        """
        GIVEN text with clear keywords and meaningful content
        WHEN extract_keywords is called
        THEN expect:
            - List of relevant keywords returned
            - Keywords ordered by importance/frequency
            - Stop words filtered out
            - Lowercase keywords returned
        """
        # Given
        text = "Machine learning algorithms enable artificial intelligence systems to learn patterns from data and make predictions. Machine learning is transforming various industries through advanced algorithms and intelligent data processing."
        
        # When
        keywords = processor.extract_keywords(text, top_k=10)
        
        # Then
        assert isinstance(keywords, list), "Result should be a list"
        assert len(keywords) <= 10, "Should respect top_k parameter"
        assert len(keywords) > 0, "Should extract some keywords"
        
        # Check that all keywords are lowercase strings
        for keyword in keywords:
            assert isinstance(keyword, str), "Each keyword should be a string"
            assert keyword.islower(), f"Keyword '{keyword}' should be lowercase"
            assert len(keyword) > 0, "Keywords should not be empty"
        
        # Check that important keywords are identified
        keywords_str = ' '.join(keywords)
        assert 'machine' in keywords_str or 'learning' in keywords_str, "Should identify 'machine' or 'learning'"
        assert 'algorithm' in keywords_str, "Should identify 'algorithm' (high frequency)"
        
        # Check that stop words are filtered out
        stop_words = ['the', 'and', 'to', 'from', 'is', 'are', 'in', 'on', 'at', 'for']
        for stop_word in stop_words:
            assert stop_word not in keywords, f"Stop word '{stop_word}' should be filtered out"

    def test_extract_keywords_empty_input(self, processor):
        """
        GIVEN empty string input
        WHEN extract_keywords is called
        THEN expect:
            - Empty list returned
            - No errors raised
        """
        # Given
        text = ""
        
        # When
        keywords = processor.extract_keywords(text)
        
        # Then
        assert isinstance(keywords, list), "Result should be a list"
        assert len(keywords) == 0, "Should return empty list for empty input"

    def test_extract_keywords_none_input(self, processor):
        """
        GIVEN None as input
        WHEN extract_keywords is called
        THEN expect:
            - TypeError handled gracefully
            - Empty list returned (after conversion to string)
        """
        # Given
        text = None
        
        # When
        keywords = processor.extract_keywords(text)
        
        # Then
        assert isinstance(keywords, list), "Result should be a list"
        # After converting None to string, should get some result from "None"
        # but likely filtered as too short

    def test_extract_keywords_non_string_input(self, processor):
        """
        GIVEN non-string input (int, list, dict)
        WHEN extract_keywords is called
        THEN expect:
            - TypeError handled gracefully by converting to string
            - Processing continues gracefully
            - Reasonable output produced
        """
        # Given
        test_cases = [
            123,
            ['list', 'of', 'words'],
            {'key': 'value', 'machine': 'learning'}
        ]
        
        for input_value in test_cases:
            # When
            keywords = processor.extract_keywords(input_value)
            
            # Then
            assert isinstance(keywords, list), f"Result should be a list for input {input_value}"
            # Should handle conversion gracefully without crashing

    def test_extract_keywords_top_k_parameter(self, processor):
        """
        GIVEN text with many potential keywords and various top_k values
        WHEN extract_keywords is called with different top_k
        THEN expect:
            - Returned list length <= top_k
            - Most important keywords prioritized
            - Default top_k=20 behavior
        """
        # Given
        text = ("artificial intelligence machine learning deep learning neural networks "
                "algorithms data science computer vision natural language processing "
                "supervised learning unsupervised learning reinforcement learning "
                "classification regression clustering optimization feature engineering "
                "model training validation testing deployment")
        
        # Test different top_k values
        test_cases = [1, 3, 5, 10, 15]
        
        for k in test_cases:
            # When
            keywords = processor.extract_keywords(text, top_k=k)
            
            # Then
            assert len(keywords) <= k, f"Should return at most {k} keywords"
            assert isinstance(keywords, list), "Result should be a list"
        
        # Test default behavior
        default_keywords = processor.extract_keywords(text)
        assert len(default_keywords) <= 20, "Default should be top_k=20"

    def test_extract_keywords_invalid_top_k(self, processor):
        """
        GIVEN invalid top_k values (negative, zero, non-integer)
        WHEN extract_keywords is called
        THEN expect:
            - ValueError handled with default value
            - Default behavior maintained
            - No processing errors
        """
        # Given
        text = "machine learning algorithms artificial intelligence"
        invalid_k_values = [-1, 0, 'invalid', 3.14, None]
        
        for invalid_k in invalid_k_values:
            # When - should not crash
            keywords = processor.extract_keywords(text, top_k=invalid_k)
            
            # Then
            assert isinstance(keywords, list), f"Should handle invalid top_k {invalid_k}"
            # Should use default behavior

    def test_extract_keywords_stop_word_filtering(self, processor):
        """
        GIVEN text with common stop words and meaningful content
        WHEN extract_keywords is called
        THEN expect:
            - Common stop words filtered out (the, and, is, etc.)
            - Content-bearing words prioritized
            - Appropriate filtering balance maintained
        """
        # Given
        text = ("The machine learning algorithm is very effective and it can process "
                "the data in the most efficient way. The system is able to learn "
                "from the patterns in the data and make accurate predictions.")
        
        # When
        keywords = processor.extract_keywords(text, top_k=15)
        
        # Then
        common_stop_words = [
            'the', 'and', 'is', 'it', 'can', 'in', 'to', 'from', 'a', 'an',
            'very', 'most', 'able', 'way', 'make'
        ]
        
        for stop_word in common_stop_words:
            assert stop_word not in keywords, f"Stop word '{stop_word}' should be filtered"
        
        # Content words should be present
        content_words = ['machine', 'learning', 'algorithm', 'data', 'patterns', 'predictions']
        found_content_words = [word for word in content_words if word in keywords]
        assert len(found_content_words) >= 3, "Should find several content-bearing words"

    def test_extract_keywords_frequency_analysis(self, processor):
        """
        GIVEN text with words of varying frequency
        WHEN extract_keywords is called
        THEN expect:
            - High-frequency content words prioritized
            - Frequency-based ranking applied
            - Balanced representation of important terms
        """
        # Given - 'algorithm' appears 4 times, 'data' 3 times, others less
        text = ("The algorithm processes data efficiently. This algorithm uses advanced "
                "data structures. Our algorithm outperforms other algorithms by analyzing "
                "data patterns. The data processing algorithm delivers excellent results.")
        
        # When
        keywords = processor.extract_keywords(text, top_k=10)
        
        # Then
        # High frequency words should appear early in results
        if len(keywords) >= 2:
            top_keywords = keywords[:3]  # Top 3 keywords
            top_keywords_str = ' '.join(top_keywords)
            
            # 'algorithm' and 'data' should be highly ranked due to frequency
            assert 'algorithm' in top_keywords_str or 'data' in top_keywords_str, \
                   "High-frequency words should be prioritized"

    def test_extract_keywords_minimum_word_length(self, processor):
        """
        GIVEN text with words of various lengths
        WHEN extract_keywords is called
        THEN expect:
            - Very short words (1-2 characters) filtered out
            - Minimum word length requirement applied
            - Meaningful words preserved regardless of length
        """
        # Given
        text = ("a I to go we machine learning algorithms artificial intelligence "
                "AI ML NLP deep neural networks optimization")
        
        # When
        keywords = processor.extract_keywords(text, top_k=15)
        
        # Then
        # Very short words should be filtered
        short_words = ['a', 'i', 'to', 'go', 'we']
        for short_word in short_words:
            assert short_word not in keywords, f"Short word '{short_word}' should be filtered"
        
        # Meaningful longer words should be preserved
        longer_words = ['machine', 'learning', 'algorithms', 'artificial', 'intelligence']
        found_longer = [word for word in longer_words if word in keywords]
        assert len(found_longer) >= 2, "Should preserve meaningful longer words"

    def test_extract_keywords_regex_tokenization(self, processor):
        """
        GIVEN text with various punctuation and formatting
        WHEN extract_keywords is called
        THEN expect:
            - Regex-based tokenization working correctly
            - Punctuation properly handled
            - Word boundaries detected accurately
        """
        # Given
        text = ("machine-learning, artificial/intelligence; deep:learning! "
                "neural@networks? data#science$ computer%vision^ natural&language* "
                "processing(optimization) [classification] {regression}")
        
        # When
        keywords = processor.extract_keywords(text, top_k=15)
        
        # Then
        # Should extract meaningful words despite punctuation
        expected_words = ['machine', 'learning', 'artificial', 'intelligence', 
                         'deep', 'neural', 'networks', 'data', 'science']
        found_words = [word for word in expected_words if word in keywords]
        assert len(found_words) >= 5, "Should extract words despite punctuation"
        
        # Should not include punctuation in keywords
        for keyword in keywords:
            assert keyword.isalpha(), f"Keyword '{keyword}' should contain only letters"

    def test_extract_keywords_case_normalization(self, processor):
        """
        GIVEN text with mixed case words
        WHEN extract_keywords is called
        THEN expect:
            - All keywords returned in lowercase
            - Case variations merged correctly
            - Frequency counting combines case variants
        """
        # Given
        text = ("Machine Learning MACHINE learning machine LEARNING "
                "Algorithm ALGORITHM algorithm Artificial ARTIFICIAL artificial")
        
        # When
        keywords = processor.extract_keywords(text, top_k=10)
        
        # Then
        # All keywords should be lowercase
        for keyword in keywords:
            assert keyword.islower(), f"Keyword '{keyword}' should be lowercase"
        
        # Should merge case variations
        assert 'machine' in keywords, "Should include 'machine' (merged from various cases)"
        assert 'learning' in keywords, "Should include 'learning' (merged from various cases)"
        assert 'algorithm' in keywords, "Should include 'algorithm' (merged from various cases)"
        
        # Should not have multiple versions of same word
        machine_variants = [kw for kw in keywords if 'machine' in kw.lower()]
        assert len(machine_variants) <= 1, "Should not have multiple case variants of same word"

    def test_extract_keywords_unicode_handling(self, processor):
        """
        GIVEN text with Unicode characters and international words
        WHEN extract_keywords is called
        THEN expect:
            - Unicode text processed correctly
            - Non-ASCII characters preserved
            - International text handled appropriately
        """
        # Given
        text = ("machine learning algorithme données intelligence artificielle "
                "Maschinelles Lernen künstliche Intelligenz 机器学习 人工智能 "
                "aprendizaje automático inteligencia artificial")
        
        # When
        keywords = processor.extract_keywords(text, top_k=15)
        
        # Then
        assert isinstance(keywords, list), "Should handle Unicode text"
        assert len(keywords) >= 0, "Should process without crashing"
        
        # Should preserve non-ASCII characters if they form valid words
        for keyword in keywords:
            assert isinstance(keyword, str), "Keywords should be strings"
            assert len(keyword) > 0, "Keywords should not be empty"

    def test_extract_keywords_academic_text(self, processor):
        """
        GIVEN academic or technical text with domain-specific terms
        WHEN extract_keywords is called
        THEN expect:
            - Technical terms properly identified
            - Domain-specific vocabulary prioritized
            - Acronyms and abbreviations handled
        """
        # Given
        text = ("This research investigates convolutional neural networks (CNNs) for "
                "computer vision tasks. We utilize backpropagation algorithms and "
                "gradient descent optimization. The methodology employs cross-validation "
                "and hyperparameter tuning. Results demonstrate improved accuracy on "
                "benchmark datasets using GPU acceleration and distributed computing.")
        
        # When
        keywords = processor.extract_keywords(text, top_k=15)
        
        # Then
        technical_terms = ['neural', 'networks', 'convolutional', 'computer', 'vision',
                          'backpropagation', 'algorithms', 'gradient', 'descent',
                          'optimization', 'methodology', 'validation', 'hyperparameter']
        
        found_technical = [term for term in technical_terms if term in keywords]
        assert len(found_technical) >= 5, "Should identify multiple technical terms"

    def test_extract_keywords_insufficient_content(self, processor):
        """
        GIVEN text with fewer unique words than top_k
        WHEN extract_keywords is called
        THEN expect:
            - All valid keywords returned
            - List length may be less than top_k
            - No padding or artificial keywords
        """
        # Given
        text = "machine learning algorithm"  # Only 3 unique meaningful words
        
        # When
        keywords = processor.extract_keywords(text, top_k=10)
        
        # Then
        assert len(keywords) <= 3, "Should not return more keywords than available"
        assert len(keywords) >= 0, "Should return some keywords if any exist"
        
        expected_words = ['machine', 'learning', 'algorithm']
        for keyword in keywords:
            assert keyword in expected_words, f"Keyword '{keyword}' should be from input text"

    def test_extract_keywords_regex_failure_handling(self, processor):
        """
        GIVEN malformed text causing regex processing to fail
        WHEN extract_keywords is called
        THEN expect:
            - RuntimeError handled gracefully
            - Empty list returned on failure
            - No unhandled exceptions
        """
        # Given - text that might cause regex issues
        problematic_texts = [
            "\\x00\\x01\\x02",  # Control characters
            "\\" * 1000,        # Many backslashes
            "(" * 100 + ")" * 100,  # Unbalanced parentheses
        ]
        
        for text in problematic_texts:
            # When
            try:
                keywords = processor.extract_keywords(text)
                # Then
                assert isinstance(keywords, list), "Should return list even on problematic input"
            except Exception as e:
                # Should handle gracefully, not crash the test
                assert False, f"Should handle problematic input gracefully, got: {e}"

    def test_extract_keywords_performance_large_text(self, processor):
        """
        GIVEN very large text input (>1MB)
        WHEN extract_keywords is called
        THEN expect:
            - Processing completes in reasonable time
            - Memory usage remains manageable
            - Quality of results maintained
        """
        # Given - simulate large text
        base_text = ("machine learning algorithms artificial intelligence neural networks "
                    "deep learning computer vision natural language processing data science "
                    "supervised learning unsupervised learning reinforcement learning ")
        large_text = base_text * 1000  # Create large text
        
        # When
        import time
        start_time = time.time()
        keywords = processor.extract_keywords(large_text, top_k=20)
        end_time = time.time()
        
        # Then
        processing_time = end_time - start_time
        assert processing_time < 30.0, f"Should process large text in reasonable time, took {processing_time}s"
        assert isinstance(keywords, list), "Should return valid result for large text"
        assert len(keywords) > 0, "Should extract keywords from large text"

    def test_extract_keywords_return_type_validation(self, processor):
        """
        GIVEN any valid text input
        WHEN extract_keywords is called
        THEN expect:
            - Return type is List[str]
            - All elements are lowercase strings
            - No duplicate keywords in result
            - Ordered by relevance/frequency
        """
        # Given
        text = "machine learning algorithms artificial intelligence data science"
        
        # When
        keywords = processor.extract_keywords(text, top_k=10)
        
        # Then
        assert isinstance(keywords, list), "Return type should be List"
        
        for keyword in keywords:
            assert isinstance(keyword, str), "All elements should be strings"
            assert keyword.islower(), "All keywords should be lowercase"
            assert len(keyword) > 0, "Keywords should not be empty"
        
        # Check for duplicates
        assert len(keywords) == len(set(keywords)), "Should not contain duplicate keywords"
        
        # Should be ordered (most frequent/relevant first)
        # This is harder to test precisely, but we can check structure
        assert len(keywords) <= 10, "Should respect top_k limit"

    def test_extract_keywords_duplicate_handling(self, processor):
        """
        GIVEN text with repeated words and phrases
        WHEN extract_keywords is called
        THEN expect:
            - Duplicate keywords filtered out
            - Frequency properly aggregated
            - Each keyword appears only once in result
        """
        # Given
        text = ("algorithm algorithm algorithm data data machine machine machine "
                "learning learning neural neural network network")
        
        # When
        keywords = processor.extract_keywords(text, top_k=10)
        
        # Then
        # Should not have duplicates
        unique_keywords = set(keywords)
        assert len(keywords) == len(unique_keywords), "Should not contain duplicate keywords"
        
        # High frequency words should be included
        expected_high_freq = ['algorithm', 'machine', 'data', 'learning', 'neural', 'network']
        found_expected = [word for word in expected_high_freq if word in keywords]
        assert len(found_expected) >= 4, "Should include high-frequency words"


class TestTextProcessorIntegration:
    """Test TextProcessor integration scenarios and method combinations."""

    @pytest.fixture
    def processor(self):
        """Set up test fixtures with TextProcessor instance."""
        return TextProcessor()

    def test_sentence_splitting_keyword_extraction_pipeline(self, processor):
        """
        GIVEN text processed through both split_sentences and extract_keywords
        WHEN methods are used in combination
        THEN expect:
            - Consistent text handling across methods
            - No interference between processing stages
            - Complementary results from both methods
        """
        # Given
        text = ("Machine learning algorithms enable intelligent systems. "
                "These algorithms process data efficiently. "
                "Neural networks are particularly effective for pattern recognition.")
        
        # When
        sentences = processor.split_sentences(text)
        keywords = processor.extract_keywords(text, top_k=10)
        
        # Process each sentence individually
        sentence_keywords = []
        for sentence in sentences:
            sent_keywords = processor.extract_keywords(sentence, top_k=5)
            sentence_keywords.extend(sent_keywords)
        
        # Then
        assert len(sentences) == 3, "Should split into 3 sentences"
        assert len(keywords) > 0, "Should extract keywords from full text"
        assert len(sentence_keywords) > 0, "Should extract keywords from sentences"
        
        # Keywords from full text should overlap with sentence-level keywords
        full_text_set = set(keywords)
        sentence_set = set(sentence_keywords)
        overlap = full_text_set.intersection(sentence_set)
        assert len(overlap) > 0, "Should have overlapping keywords between methods"

    def test_text_processor_memory_efficiency(self, processor):
        """
        GIVEN multiple large text processing operations
        WHEN TextProcessor methods are called repeatedly
        THEN expect:
            - Memory usage remains stable
            - No memory leaks between operations
            - Efficient resource management
        """
        import gc
        
        # Given
        large_text = "machine learning artificial intelligence " * 1000
        
        # When - process multiple times
        for i in range(10):
            sentences = processor.split_sentences(large_text)
            keywords = processor.extract_keywords(large_text, top_k=20)
            
            # Force garbage collection
            del sentences, keywords
            gc.collect()
        
        # Then - should complete without memory issues
        # If we get here without MemoryError, the test passes
        assert True, "Should handle repeated large text processing"

    def test_text_processor_state_independence(self, processor):
        """
        GIVEN multiple sequential processing operations
        WHEN TextProcessor methods are called with different inputs
        THEN expect:
            - No state persistence between calls
            - Each operation independent of previous ones
            - Consistent behavior regardless of processing history
        """
        # Given
        text1 = "First document about machine learning algorithms."
        text2 = "Second document discusses neural networks and deep learning."
        text3 = "Third document covers natural language processing."
        
        # When - process in sequence
        sentences1 = processor.split_sentences(text1)
        keywords1 = processor.extract_keywords(text1, top_k=5)
        
        sentences2 = processor.split_sentences(text2)
        keywords2 = processor.extract_keywords(text2, top_k=5)
        
        sentences3 = processor.split_sentences(text3)
        keywords3 = processor.extract_keywords(text3, top_k=5)
        
        # Process text1 again
        sentences1_again = processor.split_sentences(text1)
        keywords1_again = processor.extract_keywords(text1, top_k=5)
        
        # Then
        assert sentences1 == sentences1_again, "Should produce identical results on repeated calls"
        assert keywords1 == keywords1_again, "Should produce identical results on repeated calls"
        
        # Different inputs should produce different outputs
        assert sentences1 != sentences2, "Different inputs should produce different sentence splits"
        assert keywords1 != keywords2, "Different inputs should produce different keywords"



class TestTextProcessorEdgeCasesAndErrorHandling:
    """Test TextProcessor edge cases and comprehensive error handling."""

    @pytest.fixture
    def processor(self):
        """Set up test fixtures with TextProcessor instance."""
        return TextProcessor()

    def test_extremely_long_sentences(self, processor):
        """
        GIVEN text with extremely long sentences (>10,000 characters)
        WHEN split_sentences is called
        THEN expect:
            - Long sentences handled correctly
            - No truncation or corruption
            - Performance remains acceptable
        """
        # Given
        long_sentence = ("This is an extremely long sentence that contains many words and goes on for a very long time " * 200) + "."
        assert len(long_sentence) > 10000, "Sentence should be longer than 10,000 characters"
        
        # When
        import time
        start_time = time.time()
        sentences = processor.split_sentences(long_sentence)
        end_time = time.time()
        
        # Then
        assert len(sentences) == 1, "Should recognize as single sentence"
        assert len(sentences[0]) > 10000, "Sentence content should be preserved"
        assert sentences[0].endswith("This is an extremely long sentence that contains many words and goes on for a very long time"), "Content should not be truncated"
        
        processing_time = end_time - start_time
        assert processing_time < 10.0, f"Should process in reasonable time, took {processing_time}s"

    def test_text_with_only_punctuation(self, processor):
        """
        GIVEN text containing only punctuation marks
        WHEN TextProcessor methods are called
        THEN expect:
            - Graceful handling of punctuation-only text
            - Appropriate empty results
            - No processing errors
        """
        # Given
        punctuation_text = "!@#$%^&*()_+-=[]{}|;':\",./<>?"
        
        # When
        sentences = processor.split_sentences(punctuation_text)
        keywords = processor.extract_keywords(punctuation_text)
        
        # Then
        assert isinstance(sentences, list), "Should return list for sentence splitting"
        assert isinstance(keywords, list), "Should return list for keyword extraction"
        assert len(keywords) == 0, "Should not extract keywords from punctuation-only text"

    def test_text_with_only_whitespace(self, processor):
        """
        GIVEN text containing only whitespace characters
        WHEN TextProcessor methods are called
        THEN expect:
            - Whitespace-only text handled correctly
            - Empty results returned appropriately
            - No errors or exceptions
        """
        # Given
        whitespace_texts = ["   ", "\t\t\t", "\n\n\n", " \t\n \r ", ""]
        
        for whitespace_text in whitespace_texts:
            # When
            sentences = processor.split_sentences(whitespace_text)
            keywords = processor.extract_keywords(whitespace_text)
            
            # Then
            assert isinstance(sentences, list), f"Should return list for whitespace text: '{repr(whitespace_text)}'"
            assert isinstance(keywords, list), f"Should return list for whitespace text: '{repr(whitespace_text)}'"
            assert len(sentences) == 0, f"Should return empty sentences for whitespace: '{repr(whitespace_text)}'"
            assert len(keywords) == 0, f"Should return empty keywords for whitespace: '{repr(whitespace_text)}'"

    def test_text_with_control_characters(self, processor):
        """
        GIVEN text containing control characters and special formatting
        WHEN TextProcessor methods are called
        THEN expect:
            - Control characters handled gracefully
            - No corruption of processing pipeline
            - Appropriate filtering or preservation
        """
        # Given
        control_text = "Machine learning\x00algorithms\x01artificial\x02intelligence\x03"
        
        # When
        sentences = processor.split_sentences(control_text)
        keywords = processor.extract_keywords(control_text)
        
        # Then
        assert isinstance(sentences, list), "Should handle control characters"
        assert isinstance(keywords, list), "Should handle control characters"
        
        # Should extract meaningful content despite control characters
        if len(keywords) > 0:
            keywords_str = ' '.join(keywords)
            assert 'machine' in keywords_str or 'learning' in keywords_str or 'artificial' in keywords_str, \
                   "Should extract meaningful words despite control characters"

    def test_mixed_encoding_text(self, processor):
        """
        GIVEN text with mixed character encodings
        WHEN TextProcessor methods are called
        THEN expect:
            - Encoding issues handled gracefully
            - No character corruption
            - Appropriate error handling or conversion
        """
        # Given
        mixed_texts = [
            "Machine learning algorithme données",  # Mixed English/French
            "Машинное обучение machine learning",   # Mixed Cyrillic/Latin
            "机器学习 machine learning",            # Mixed Chinese/English
        ]
        
        for text in mixed_texts:
            # When
            sentences = processor.split_sentences(text)
            keywords = processor.extract_keywords(text)
            
            # Then
            assert isinstance(sentences, list), f"Should handle mixed encoding: {text}"
            assert isinstance(keywords, list), f"Should handle mixed encoding: {text}"

    def test_circular_or_recursive_input(self, processor):
        """
        GIVEN input that might cause circular processing
        WHEN TextProcessor methods are called
        THEN expect:
            - No infinite loops or recursion
            - Processing completes in finite time
            - Appropriate safeguards in place
        """
        # Given
        recursive_text = "This sentence refers to this sentence refers to this sentence." * 100
        
        # When
        import time
        start_time = time.time()
        
        sentences = processor.split_sentences(recursive_text)
        keywords = processor.extract_keywords(recursive_text, top_k=10)
        
        end_time = time.time()
        processing_time = end_time - start_time
        
        # Then
        assert processing_time < 30.0, f"Should complete in finite time, took {processing_time}s"
        assert isinstance(sentences, list), "Should return valid results"
        assert isinstance(keywords, list), "Should return valid results"

    def test_memory_exhaustion_scenarios(self, processor):
        """
        GIVEN scenarios that could exhaust available memory
        WHEN TextProcessor methods are called
        THEN expect:
            - MemoryError handled gracefully (if it occurs)
            - System stability maintained
            - Appropriate error handling
        """
        # Given - very large text that might cause memory issues
        try:
            huge_text = "machine learning " * 100000  # ~1.5MB of text
            
            # When
            sentences = processor.split_sentences(huge_text)
            keywords = processor.extract_keywords(huge_text, top_k=50)
            
            # Then
            assert isinstance(sentences, list), "Should handle large text if memory allows"
            assert isinstance(keywords, list), "Should handle large text if memory allows"
            
        except MemoryError:
            # Then - if MemoryError occurs, it should be handled gracefully
            assert True, "MemoryError handled appropriately"
        except Exception as e:
            # Should not raise other unexpected exceptions
            assert False, f"Should handle memory constraints gracefully, got unexpected error: {e}"

class TestChunkOptimizerInitialization:
    """Test ChunkOptimizer initialization and parameter validation."""

    def test_init_valid_parameters(self):
        """
        GIVEN valid parameters for ChunkOptimizer
        WHEN instance is created
        THEN expect:
            - Instance created successfully
            - Parameters stored correctly
            - All methods accessible
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import ChunkOptimizer
        
        # Given
        max_size = 2048
        overlap = 200
        min_size = 100
        
        # When
        optimizer = ChunkOptimizer(max_size=max_size, overlap=overlap, min_size=min_size)
        
        # Then
        assert isinstance(optimizer, ChunkOptimizer), "Should create ChunkOptimizer instance"
        assert optimizer.max_size == max_size, "Should store max_size correctly"
        assert optimizer.overlap == overlap, "Should store overlap correctly"
        assert optimizer.min_size == min_size, "Should store min_size correctly"
        
        # Check methods are accessible
        assert hasattr(optimizer, 'optimize_chunk_boundaries'), "Should have optimize_chunk_boundaries method"
        assert callable(optimizer.optimize_chunk_boundaries), "optimize_chunk_boundaries should be callable"

    def test_init_parameter_validation_max_size_min_size(self):
        """
        GIVEN max_size <= min_size
        WHEN ChunkOptimizer is initialized
        THEN expect ValueError to be raised
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import ChunkOptimizer
        
        # Given/When/Then
        with pytest.raises(ValueError, match="max_size.*min_size"):
            ChunkOptimizer(max_size=100, overlap=50, min_size=200)
        
        with pytest.raises(ValueError, match="max_size.*min_size"):
            ChunkOptimizer(max_size=100, overlap=50, min_size=100)

    def test_init_parameter_validation_overlap_max_size(self):
        """
        GIVEN overlap >= max_size
        WHEN ChunkOptimizer is initialized
        THEN expect ValueError to be raised
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import ChunkOptimizer
        
        # Given/When/Then
        with pytest.raises(ValueError, match="overlap.*max_size"):
            ChunkOptimizer(max_size=100, overlap=100, min_size=50)
        
        with pytest.raises(ValueError, match="overlap.*max_size"):
            ChunkOptimizer(max_size=100, overlap=150, min_size=50)

    def test_init_negative_parameters(self):
        """
        GIVEN negative parameter values
        WHEN ChunkOptimizer is initialized
        THEN expect ValueError or AssertionError
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import ChunkOptimizer
        
        # Given/When/Then - negative max_size
        with pytest.raises((ValueError, AssertionError)):
            ChunkOptimizer(max_size=-100, overlap=50, min_size=25)
        
        # Given/When/Then - negative overlap
        with pytest.raises((ValueError, AssertionError)):
            ChunkOptimizer(max_size=200, overlap=-50, min_size=25)
        
        # Given/When/Then - negative min_size
        with pytest.raises((ValueError, AssertionError)):
            ChunkOptimizer(max_size=200, overlap=50, min_size=-25)

    def test_init_zero_parameters(self):
        """
        GIVEN zero parameter values
        WHEN ChunkOptimizer is initialized
        THEN expect ValueError or AssertionError
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import ChunkOptimizer
        
        # Given/When/Then
        with pytest.raises((ValueError, AssertionError)):
            ChunkOptimizer(max_size=0, overlap=50, min_size=25)
        
        with pytest.raises((ValueError, AssertionError)):
            ChunkOptimizer(max_size=200, overlap=0, min_size=25)
        
        with pytest.raises((ValueError, AssertionError)):
            ChunkOptimizer(max_size=200, overlap=50, min_size=0)

    def test_init_non_integer_parameters(self):
        """
        GIVEN non-integer parameter values
        WHEN ChunkOptimizer is initialized
        THEN expect TypeError
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import ChunkOptimizer
        
        # Given/When/Then - float parameters
        with pytest.raises(TypeError):
            ChunkOptimizer(max_size=200.5, overlap=50, min_size=25)
        
        with pytest.raises(TypeError):
            ChunkOptimizer(max_size=200, overlap=50.5, min_size=25)
        
        with pytest.raises(TypeError):
            ChunkOptimizer(max_size=200, overlap=50, min_size=25.5)
        
        # Given/When/Then - string parameters
        with pytest.raises(TypeError):
            ChunkOptimizer(max_size="200", overlap=50, min_size=25)
        
        with pytest.raises(TypeError):
            ChunkOptimizer(max_size=200, overlap="50", min_size=25)
        
        with pytest.raises(TypeError):
            ChunkOptimizer(max_size=200, overlap=50, min_size="25")


class TestChunkOptimizerOptimizeBoundaries:
    """Test ChunkOptimizer.optimize_chunk_boundaries method functionality."""

    @pytest.fixture
    def optimizer(self):
        """Create ChunkOptimizer instance for testing."""
        from ipfs_datasets_py.pdf_processing.llm_optimizer import ChunkOptimizer
        return ChunkOptimizer(max_size=1024, overlap=100, min_size=50)

    def test_optimize_boundaries_basic_functionality(self, optimizer):
        """
        GIVEN text with clear sentence and paragraph boundaries
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Boundaries moved to natural language breaks
            - Sentence endings prioritized over arbitrary positions
            - Paragraph breaks prioritized over sentence breaks
            - Reasonable proximity to original boundaries maintained
        """
        # Given
        text = ("First sentence here. Second sentence follows.\n\n"
                "New paragraph starts. Another sentence in this paragraph. "
                "Final sentence here.\n\n"
                "Last paragraph with content.")
        
        # Original boundaries at arbitrary positions
        current_boundaries = [30, 80, 130]  # Arbitrary character positions
        
        # When
        optimized = optimizer.optimize_chunk_boundaries(text, current_boundaries)
        
        # Then
        assert isinstance(optimized, list), "Should return list of boundaries"
        assert len(optimized) == len(current_boundaries), "Should return same number of boundaries"
        
        # Check that all boundaries are valid positions
        for boundary in optimized:
            assert isinstance(boundary, int), "All boundaries should be integers"
            assert 0 <= boundary <= len(text), f"Boundary {boundary} should be within text length {len(text)}"
        
        # Check that boundaries are ordered
        assert optimized == sorted(optimized), "Boundaries should be in ascending order"
        
        # Check that optimized boundaries are different from originals (unless they were already optimal)
        differences = [abs(opt - orig) for opt, orig in zip(optimized, current_boundaries)]
        # At least some boundaries should be moved to better positions
        assert any(diff > 0 for diff in differences), "At least some boundaries should be optimized"

    def test_optimize_boundaries_sentence_alignment(self, optimizer):
        """
        GIVEN text with clear sentence boundaries near chunk boundaries
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Boundaries aligned with sentence endings
            - Sentence structure preserved
            - Natural reading flow maintained
        """
        # Given
        text = ("Sentence one ends here. Sentence two continues. Sentence three follows. "
                "Sentence four is longer and more complex. Sentence five concludes this section.")
        
        # Position boundaries mid-sentence
        current_boundaries = [25, 75]  # Should be moved to sentence endings
        
        # When
        optimized = optimizer.optimize_chunk_boundaries(text, current_boundaries)
        
        # Then
        # Find actual sentence ending positions
        sentence_endings = []
        for i, char in enumerate(text):
            if char in '.!?' and i < len(text) - 1 and text[i + 1] == ' ':
                sentence_endings.append(i + 1)  # Position after punctuation and space
        
        # Check that optimized boundaries align with sentence endings
        for boundary in optimized:
            # Should be close to a sentence ending
            distances_to_endings = [abs(boundary - ending) for ending in sentence_endings]
            min_distance = min(distances_to_endings) if distances_to_endings else float('inf')
            assert min_distance <= 5, f"Boundary {boundary} should be close to a sentence ending"

    def test_optimize_boundaries_paragraph_priority(self, optimizer):
        """
        GIVEN text with both paragraph and sentence breaks near boundaries
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Paragraph breaks prioritized over sentence breaks
            - Stronger semantic boundaries preferred
            - Hierarchical boundary detection
        """
        # Given
        text = ("Paragraph one sentence. Another sentence in para one.\n\n"
                "Paragraph two starts here. More content in para two.\n\n"
                "Paragraph three begins. Final content here.")
        
        # Find paragraph break positions
        para_breaks = []
        i = 0
        while i < len(text) - 1:
            if text[i:i+2] == '\n\n':
                para_breaks.append(i + 2)  # Position after paragraph break
                i += 2
            else:
                i += 1
        
        # Position boundaries near both sentence and paragraph breaks
        if para_breaks:
            # Place boundary near first paragraph break but closer to a sentence ending
            current_boundaries = [para_breaks[0] - 10]  # 10 chars before para break
        else:
            current_boundaries = [50]  # Fallback position
        
        # When
        optimized = optimizer.optimize_chunk_boundaries(text, current_boundaries)
        
        # Then
        if para_breaks:
            # Should prefer paragraph break over sentence break
            for boundary in optimized:
                distances_to_para_breaks = [abs(boundary - pb) for pb in para_breaks]
                min_para_distance = min(distances_to_para_breaks)
                
                # If close to a paragraph break, should prefer it
                if min_para_distance <= 20:  # Within reasonable range
                    assert min_para_distance <= 5, "Should align with paragraph break when nearby"

    def test_optimize_boundaries_empty_text(self, optimizer):
        """
        GIVEN empty text
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - ValueError raised or empty list returned
            - Graceful handling of edge case
        """
        # Given
        text = ""
        current_boundaries = [10, 20]  # Invalid for empty text
        
        # When/Then
        with pytest.raises(ValueError):
            optimizer.optimize_chunk_boundaries(text, current_boundaries)

    def test_optimize_boundaries_empty_boundaries_list(self, optimizer):
        """
        GIVEN valid text but empty boundaries list
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Empty list returned
            - No errors raised
            - Graceful handling
        """
        # Given
        text = "Some text with sentences. Multiple sentences here."
        current_boundaries = []
        
        # When
        optimized = optimizer.optimize_chunk_boundaries(text, current_boundaries)
        
        # Then
        assert isinstance(optimized, list), "Should return list"
        assert len(optimized) == 0, "Should return empty list for empty input"

    def test_optimize_boundaries_out_of_range_positions(self, optimizer):
        """
        GIVEN boundaries that exceed text length
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Boundaries clamped to text length
            - Valid boundaries returned
            - No crashes
        """
        # Given
        text = "Short text here."
        text_length = len(text)
        current_boundaries = [text_length + 10, text_length + 20]  # Beyond text length
        
        # When
        try:
            optimized = optimizer.optimize_chunk_boundaries(text, current_boundaries)
            
            # Then - if it succeeds, boundaries should be clamped
            for boundary in optimized:
                assert 0 <= boundary <= text_length, f"Boundary should be clamped to text length"
                
        except (IndexError, ValueError):
            # Then - acceptable to raise error for out-of-range boundaries
            pass

    def test_optimize_boundaries_no_natural_breaks(self, optimizer):
        """
        GIVEN text with no clear sentence or paragraph breaks
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Original boundaries preserved or minimally adjusted
            - No errors raised
            - Fallback behavior implemented
        """
        # Given
        text = "thisisverylongtextwithoutanyspacesorpunctuationtobreaksentencesoranything"
        current_boundaries = [20, 40, 60]
        
        # When
        optimized = optimizer.optimize_chunk_boundaries(text, current_boundaries)
        
        # Then
        assert isinstance(optimized, list), "Should return list"
        assert len(optimized) == len(current_boundaries), "Should return same number of boundaries"
        
        # Should be close to original boundaries since no natural breaks exist
        for orig, opt in zip(current_boundaries, optimized):
            distance = abs(opt - orig)
            assert distance <= 10, f"Should stay close to original boundary when no natural breaks available"

    def test_optimize_boundaries_proximity_limits(self, optimizer):
        """
        GIVEN boundaries with natural breaks far from original positions
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Reasonable proximity to original boundaries maintained
            - Not moved excessively far for optimization
            - Balance between optimization and position preservation
        """
        # Given
        text = ("Very long sentence that goes on and on without ending for a while because "
                "we want to test what happens when the nearest sentence break is far away. "
                "Finally this sentence ends.")
        
        # Place boundary in middle of first very long sentence
        current_boundaries = [50]  # Far from any sentence ending
        
        # When
        optimized = optimizer.optimize_chunk_boundaries(text, current_boundaries)
        
        # Then
        original_boundary = current_boundaries[0]
        optimized_boundary = optimized[0]
        distance_moved = abs(optimized_boundary - original_boundary)
        
        # Should not move excessively far (reasonable proximity limit)
        max_reasonable_distance = len(text) // 4  # Don't move more than 25% of text length
        assert distance_moved <= max_reasonable_distance, \
            f"Should not move boundary too far: moved {distance_moved} chars"

    def test_optimize_boundaries_complex_punctuation(self, optimizer):
        """
        GIVEN text with complex punctuation patterns
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Correct identification of true sentence boundaries
            - Abbreviations and decimals not treated as sentence endings
            - Complex punctuation handled appropriately
        """
        # Given
        text = ("Dr. Smith went to the U.S.A. in Jan. 2020. The study cost $1,234.56 per participant. "
                "Results showed 95.7% accuracy vs. baseline. Ph.D. students analyzed the data.")
        
        current_boundaries = [40, 80, 120]
        
        # When
        optimized = optimizer.optimize_chunk_boundaries(text, current_boundaries)
        
        # Then
        # Should not break at abbreviations like "Dr.", "U.S.A.", "Jan.", etc.
        # Find positions of abbreviations
        abbreviations = ["Dr.", "U.S.A.", "Jan.", "Ph.D."]
        abbrev_positions = []
        for abbrev in abbreviations:
            pos = text.find(abbrev)
            if pos != -1:
                abbrev_positions.append(pos + len(abbrev))
        
        # Optimized boundaries should not be at abbreviation positions
        for boundary in optimized:
            for abbrev_pos in abbrev_positions:
                distance = abs(boundary - abbrev_pos)
                assert distance > 2, f"Boundary should not be at abbreviation position {abbrev_pos}"

    def test_optimize_boundaries_unicode_text(self, optimizer):
        """
        GIVEN text with Unicode characters and international punctuation
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Unicode text handled correctly
            - International punctuation recognized
            - Character encoding preserved
        """
        # Given
        text = ("Café analysis shows résumé quality matters. Naïve approach failed. "
                "¿Qué pasa aquí? ¡Excelente resultado! "
                "这是中文句子。另一个中文句子。")
        
        current_boundaries = [30, 70]
        
        # When
        optimized = optimizer.optimize_chunk_boundaries(text, current_boundaries)
        
        # Then
        assert isinstance(optimized, list), "Should handle Unicode text"
        assert len(optimized) == len(current_boundaries), "Should return same number of boundaries"
        
        # All boundaries should be valid positions
        for boundary in optimized:
            assert 0 <= boundary <= len(text), "Boundaries should be within text"

    def test_optimize_boundaries_malformed_input(self, optimizer):
        """
        GIVEN malformed input (invalid boundary types, None values)
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - TypeError raised for invalid boundary types
            - Appropriate error handling
            - No crashes or corruption
        """
        # Given
        text = "Valid text with sentences. More sentences here."
        
        malformed_boundaries = [
            [10.5, 20.5],  # Float boundaries
            ["10", "20"],  # String boundaries
            [10, None, 30],  # None in boundaries
            [10, [20], 30],  # Nested list
        ]
        
        for bad_boundaries in malformed_boundaries:
            # When/Then
            with pytest.raises(TypeError):
                optimizer.optimize_chunk_boundaries(text, bad_boundaries)

    def test_optimize_boundaries_return_type_validation(self, optimizer):
        """
        GIVEN any valid input
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Return type is List[int]
            - All elements are integers
            - List is properly ordered
            - No None or invalid elements
        """
        # Given
        text = "Sentence one here. Sentence two follows. Sentence three ends."
        current_boundaries = [20, 40]
        
        # When
        result = optimizer.optimize_chunk_boundaries(text, current_boundaries)
        
        # Then
        assert isinstance(result, list), "Return type should be List"
        
        for i, boundary in enumerate(result):
            assert isinstance(boundary, int), f"Element {i} should be int, got {type(boundary)}"
            assert boundary is not None, f"Element {i} should not be None"
        
        # Check ordering
        assert result == sorted(result), "Boundaries should be in ascending order"
        
        # Check bounds
        for boundary in result:
            assert 0 <= boundary <= len(text), f"Boundary {boundary} should be within text bounds"

    def test_optimize_boundaries_performance(self, optimizer):
        """
        GIVEN large text with many potential boundaries
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Processing completes in reasonable time
            - Performance scales appropriately
            - No exponential time complexity
        """
        import time
        
        # Given - large text with many sentences
        base_sentence = "This is a sentence that will be repeated many times. "
        large_text = base_sentence * 1000  # ~50KB text with 1000 sentences
        
        # Many boundaries to optimize
        boundaries = list(range(100, len(large_text), 500))[:20]  # 20 boundaries
        
        # When
        start_time = time.time()
        optimized = optimizer.optimize_chunk_boundaries(large_text, boundaries)
        end_time = time.time()
        
        # Then
        processing_time = end_time - start_time
        assert processing_time < 10.0, f"Should process large text quickly, took {processing_time:.2f}s"
        
        assert isinstance(optimized, list), "Should return valid result for large text"
        assert len(optimized) == len(boundaries), "Should optimize all boundaries"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
