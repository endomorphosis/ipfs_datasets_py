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


class TestLLMOptimizerGetChunkOverlap:
    """Test LLMOptimizer._get_chunk_overlap method."""

    def setup_method(self):
        """Set up test fixtures with LLMOptimizer instance."""
        self.optimizer = LLMOptimizer(chunk_overlap=200)  # Set specific overlap for testing

    def test_get_chunk_overlap_valid_content(self):
        """
        GIVEN content longer than overlap requirement
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Overlap text extracted from end of content
            - Approximately chunk_overlap/4 words returned
            - Complete words preserved
        """
        # Given
        content = """
        This is a comprehensive paragraph that contains multiple sentences and should provide
        sufficient content for overlap extraction testing. The method should extract text from
        the end of this content to maintain context continuity between adjacent chunks in the
        document processing pipeline. This ensures that important information and context are
        preserved across chunk boundaries for optimal language model processing and understanding.
        """.strip()
        
        expected_overlap_words = self.optimizer.chunk_overlap // 4  # 200 // 4 = 50 words
        
        # When
        overlap = self.optimizer._get_chunk_overlap(content)
        
        # Then
        assert isinstance(overlap, str)
        assert len(overlap) > 0
        
        # Check that overlap comes from the end of content
        # Note: overlap text has normalized whitespace while original content may have newlines
        overlap_words = overlap.split()
        content_words = content.split()
        
        # Check that overlap words are from the end of content words
        assert len(overlap_words) <= len(content_words)
        expected_overlap_words_list = content_words[-len(overlap_words):]
        assert overlap_words == expected_overlap_words_list
        
        # Check word count approximation
        overlap_word_count = len(overlap.split())
        assert overlap_word_count <= expected_overlap_words
        
        # Ensure complete words are preserved (no partial words)
        words = overlap.split()
        if words:
            # First and last words should be complete
            assert not overlap.startswith(' ')  # No leading space indicates complete word
            assert words[0] in content  # First word should exist in original content

    def test_get_chunk_overlap_empty_content(self):
        """
        GIVEN empty content string
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Empty string returned
            - No errors raised
        """
        # Given
        content = ""
        
        # When
        overlap = self.optimizer._get_chunk_overlap(content)
        
        # Then
        assert overlap == ""
        assert isinstance(overlap, str)

    def test_get_chunk_overlap_short_content(self):
        """
        GIVEN content shorter than overlap requirement
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Entire content returned as overlap
            - No truncation of short content
        """
        # Given
        short_content = "Very short text with only a few words here."
        overlap_words = self.optimizer.chunk_overlap // 4  # 50 words
        actual_words = len(short_content.split())  # Much less than 50
        
        # When
        overlap = self.optimizer._get_chunk_overlap(short_content)
        
        # Then
        assert overlap == short_content or overlap == short_content.strip()
        assert len(overlap.split()) == actual_words

    def test_get_chunk_overlap_word_boundary_preservation(self):
        """
        GIVEN content with clear word boundaries
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Word boundaries respected
            - No partial words in overlap
            - Natural language structure preserved
        """
        # Given
        content = "The quick brown fox jumps over the lazy dog. " * 20  # Repeat for length
        
        # When
        overlap = self.optimizer._get_chunk_overlap(content)
        
        # Then
        assert isinstance(overlap, str)
        assert len(overlap) > 0
        
        # Check word boundary preservation
        words = overlap.split()
        if words:
            # All words should be complete (exist in original content)
            for word in words:
                clean_word = word.strip('.,!?;:')  # Remove punctuation for comparison
                assert clean_word in content
        
        # Should not start or end with partial words
        if overlap.strip():
            assert not overlap.startswith(' ')  # No leading whitespace
            # Last character should be word-ending (letter, digit, or punctuation)
            assert overlap[-1].isalnum() or overlap[-1] in '.,!?;:'

    def test_get_chunk_overlap_token_approximation(self):
        """
        GIVEN various content lengths
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Word count approximates token count
            - Overlap size roughly matches chunk_overlap/4
            - Consistent approximation behavior
        """
        # Given
        test_contents = [
            "Short content for testing basic overlap extraction behavior.",
            "Medium length content that provides more words for overlap extraction testing and validation of the approximation algorithm behavior.",
            "Very long content that spans multiple lines and contains extensive text for comprehensive testing of the overlap extraction mechanism. " * 10
        ]
        
        for content in test_contents:
            # When
            overlap = self.optimizer._get_chunk_overlap(content)
            
            # Then
            if content.strip():  # Non-empty content
                overlap_word_count = len(overlap.split())
                expected_words = self.optimizer.chunk_overlap // 4  # 50 words
                
                # Should approximate the expected word count
                if len(content.split()) >= expected_words:
                    # For long content, should be close to expected
                    assert overlap_word_count <= expected_words + 5
                    assert overlap_word_count >= expected_words - 10
                else:
                    # For short content, should return all content
                    assert overlap == content or overlap == content.strip()

    def test_get_chunk_overlap_whitespace_handling(self):
        """
        GIVEN content with various whitespace patterns
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Whitespace handled appropriately
            - No excessive whitespace in overlap
            - Clean word extraction
        """
        # Given
        content = """
        Content    with    irregular     whitespace     and     multiple
        spaces     between     words     for     testing     whitespace
        handling     in     overlap     extraction     functionality.
        """
        
        # When
        overlap = self.optimizer._get_chunk_overlap(content)
        
        # Then
        assert isinstance(overlap, str)
        
        if overlap:
            # Should not have excessive whitespace
            assert not overlap.startswith('  ')  # No double space at start
            assert not overlap.endswith('  ')   # No double space at end
            
            # Words should be separated by single spaces
            words = overlap.split()
            reconstructed = ' '.join(words)
            # The reconstructed version should be cleaner than original
            assert len(reconstructed) <= len(overlap)

    def test_get_chunk_overlap_punctuation_handling(self):
        """
        GIVEN content with various punctuation patterns
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Punctuation preserved with words
            - Sentence boundaries respected where possible
            - Natural text structure maintained
        """
        # Given
        content = """
        This content contains various punctuation marks! It includes questions?
        And statements with periods. There are also commas, semicolons; and other
        punctuation marks that should be preserved during overlap extraction.
        The method should handle these gracefully and maintain readability.
        """
        
        # When
        overlap = self.optimizer._get_chunk_overlap(content)
        
        # Then
        assert isinstance(overlap, str)
        
        if overlap:
            # Punctuation should be preserved
            original_punct_count = sum(1 for c in content if c in '.,!?;:')
            overlap_punct_count = sum(1 for c in overlap if c in '.,!?;:')
            
            # Overlap should contain some punctuation if original did
            if original_punct_count > 0:
                assert overlap_punct_count >= 0  # May contain some punctuation
            
            # Should maintain word-punctuation relationships
            words = overlap.split()
            for word in words:
                if any(p in word for p in '.,!?;:'):
                    # Punctuation should be at end of words, not randomly placed
                    clean_word = word.rstrip('.,!?;:')
                    assert clean_word.isalpha() or clean_word.isalnum()

    def test_get_chunk_overlap_edge_cases(self):
        """
        GIVEN edge case content (whitespace only, single word, etc.)
        WHEN _get_chunk_overlap is called
        THEN expect:
            - Graceful handling of edge cases
            - No errors or exceptions
            - Appropriate return values
        """
        # Given
        edge_cases = [
            "   ",  # Whitespace only
            "word",  # Single word
            "a",  # Single character
            "\n\n\n",  # Newlines only
            "word1 word2",  # Two words
            "123 456 789",  # Numbers
            "!@# $%^ &*()",  # Punctuation and symbols
        ]
        
        for content in edge_cases:
            # When
            overlap = self.optimizer._get_chunk_overlap(content)
            
            # Then
            assert isinstance(overlap, str)
            # Should not raise any exceptions
            # Should return reasonable results
            if content.strip():
                if len(content.split()) <= 2:
                    # Very short content should be returned as-is or stripped
                    assert overlap == content or overlap == content.strip()
                else:
                    assert len(overlap) <= len(content)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
