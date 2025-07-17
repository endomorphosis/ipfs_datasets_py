#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer.py
# Auto-generated on 2025-07-07 02:28:56"

from datetime import datetime
import pytest
import os
import time

from pydantic import ValidationError

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
    LLMChunkMetadata
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

    @pytest.mark.asyncio
    async def test_create_chunk_valid_parameters(self):
        """
        GIVEN valid content, chunk_id, page_num, and metadata
        WHEN _create_chunk is called
        THEN expect:
            - LLMChunk instance returned
            - All fields populated correctly
            - Token count calculated accurately
            - Metadata enhanced appropriately
        """
        # Given
        optimizer = LLMOptimizer()
        
        content = "This is a comprehensive paragraph containing multiple sentences for analysis. " \
                 "It includes various elements such as technical terms, numerical references, " \
                 "and contextual information that would be typical in a research document. " \
                 "The content length is sufficient to provide meaningful token count validation."
        
        chunk_id = 1
        page_num = 1
        metadata = LLMChunkMetadata(
            source_elements=["paragraph"],
            semantic_types={"paragraph"},
            page_number=page_num
        ).model_dump()

        # When
        chunk = await optimizer._create_chunk(content, chunk_id, page_num, metadata)
        
        # Then - verify LLMChunk instance and basic structure
        assert isinstance(chunk, LLMChunk), "Should return LLMChunk instance"
        assert chunk.chunk_id == "chunk_0001", f"Expected chunk ID '{chunk_id}', got '{chunk.chunk_id}'"
        assert chunk.content == content, "Content should match input exactly"
        assert chunk.source_page == page_num, f"Expected page number {page_num}, got {chunk.source_page}"
        
        # Verify token count calculation
        assert isinstance(chunk.token_count, int), "Token count should be integer"
        assert chunk.token_count > 0, "Token count should be positive for non-empty content"
        
        # Rough validation - content has ~50 words, should be reasonable token count
        word_count = len(content.split())
        assert 30 <= chunk.token_count <= word_count * 2, f"Token count {chunk.token_count} seems unreasonable for {word_count} words"
        
        # Verify semantic type determination
        assert chunk.semantic_types is not None, "Semantic type should be determined"
        assert isinstance(chunk.semantic_types, str), "Semantic type should be string"
        assert len(chunk.semantic_types) > 0, "Semantic type should not be empty"
        
        # Common semantic types for paragraph content
        expected_semantic_types = ["text", "paragraph", "content", "mixed", "narrative"]
        assert chunk.semantic_types in expected_semantic_types, f"Unexpected semantic type: {chunk.semantic_types}"
        
        # Verify source element
        assert chunk.source_elements is not None, "Source element should be populated"
        assert isinstance(chunk.source_elements, list), "Source element should be a list of strings"
        
        # Verify metadata enhancement
        assert chunk.metadata is not None, "Metadata should be present"
        assert isinstance(chunk.metadata, dict), "Metadata should be dictionary"
        
        # Original metadata should be preserved
        for key, value in metadata.items():
            assert key in chunk.metadata.keys(), f"Original metadata key '{key}' should be preserved"
            assert chunk.metadata[key] == value, f"Metadata value for '{key}' should be preserved"

        # Verify chunk coherence
        assert not chunk.content.startswith(" "), "Content should not start with whitespace"
        assert not chunk.content.endswith(" "), "Content should not end with whitespace"
        assert len(chunk.content.strip()) == len(chunk.content), "Content should be properly trimmed"

    @pytest.mark.asyncio
    async def test_create_chunk_empty_content(self):
        """
        GIVEN empty content string
        WHEN _create_chunk is called
        THEN expect ValidationError to be raised
        """
        
        # Given
        optimizer = LLMOptimizer()
        
        # Test cases for empty/invalid content
        empty_content_cases = [
            "",           # Empty string
            "   ",        # Only whitespace
            "\n\t  \n",   # Only whitespace characters
            None          # None value
        ]
        
        chunk_id = "chunk_0001"
        page_num = 1
        metadata = {"element_type": "paragraph"}
        
        # When/Then - test each empty content case
        for empty_content in empty_content_cases:
            with pytest.raises((ValidationError)) as exc_info:
                await optimizer._create_chunk(empty_content, chunk_id, page_num, metadata)
            
            # Verify error message is descriptive
            if empty_content is None:
                error_msg = str(exc_info.value).lower()
                assert any(keyword in error_msg for keyword in ["none", "null", "content", "empty"]), \
                    f"Error message should mention None/empty content issue: {exc_info.value}"
            else:
                error_msg = str(exc_info.value).lower()
                assert any(keyword in error_msg for keyword in ["empty", "content", "whitespace", "invalid"]), \
                    f"Error message should mention empty content issue: {exc_info.value}"

    @pytest.mark.asyncio
    async def test_create_chunk_semantic_types_determination(self):
        """
        GIVEN metadata with various semantic types
        WHEN _create_chunk is called
        THEN expect:
            - Correct semantic type priority applied
            - Type classification follows hierarchy (header > table > mixed > text)
            - Semantic type field populated correctly
        """
        # Given
        optimizer = LLMOptimizer()
        
        # Test cases for different semantic type scenarios
        test_cases = [
            # Header content should be classified as header
            {
                "content": "Chapter 1: Introduction to Machine Learning",
                "metadata": {
                    "element_type": "header", 
                    "level": 1,
                    "semantic_types": {"header"},
                    "source_elements": ["header"]
                },
                "expected_type": "header",
                "description": "Header element with clear header indicators"
            },
            
            # Table content should be classified as table
            {
                "content": "Table 1: Results\nMethod A: 95%\nMethod B: 87%\nMethod C: 92%",
                "metadata": {
                    "element_type": "table", 
                    "table_id": "table_1",
                    "semantic_types": {"table"},
                    "source_elements": ["table"]
                },
                "expected_type": "table",
                "description": "Table element with tabular data structure"
            },
            
            # Figure caption should be classified as figure_caption
            {
                "content": "Figure 2: Neural network architecture showing input, hidden, and output layers.",
                "metadata": {
                    "element_type": "figure_caption", 
                    "figure_id": "fig_2",
                    "semantic_types": {"figure_caption"},
                    "source_elements": ["figure_caption"]
                },
                "expected_type": "figure_caption",
                "description": "Figure caption with descriptive content"
            },
            
            # Mixed content (contains both text and table-like elements)
            {
                "content": "The following table shows results:\nMethod A: 95%\nMethod B: 87%\nThis demonstrates clear performance differences.",
                "metadata": {
                    "element_type": "paragraph", 
                    "contains_table": True,
                    "semantic_types": {"paragraph", "table"},
                    "source_elements": ["paragraph", "table"]
                },
                "expected_type": "mixed",
                "description": "Mixed content with both narrative and tabular elements"
            },
            
            # Regular paragraph text
            {
                "content": "This is a standard paragraph containing narrative text without any special formatting or tabular data.",
                "metadata": {
                    "element_type": "paragraph", 
                    "section": "body",
                    "semantic_types": {"paragraph"},
                    "source_elements": ["paragraph"]
                },
                "expected_type": "paragraph",
                "description": "Standard paragraph text content"
            },
            
            # Content with table-like keywords but in text format
            {
                "content": "The research table of contents includes methodology, results, and discussion sections.",
                "metadata": {
                    "element_type": "paragraph",
                    "semantic_types": {"paragraph"},
                    "source_elements": ["paragraph"]
                },
                "expected_type": "paragraph",
                "description": "Text content with table keywords but not actual table"
            },
            
            # Content with header-like keywords but not actual header
            {
                "content": "The chapter discusses various header compression techniques used in network protocols.",
                "metadata": {
                    "element_type": "paragraph",
                    "semantic_types": {"paragraph"},
                    "source_elements": ["paragraph"]
                },
                "expected_type": "paragraph",
                "description": "Text content mentioning headers but not actual header"
            }
        ]
        
        # Test priority hierarchy: header > table > figure_caption > mixed > text
        priority_test_cases = [
            # Header with table content should prioritize header
            {
                "content": "Chapter 1: Results Table\nMethod A: 95%\nMethod B: 87%",
                "metadata": {
                    "element_type": "header", 
                    "level": 1, 
                    "contains_table": True,
                    "semantic_types": {"header", "table"},
                    "source_elements": ["header", "table"]
                },
                "expected_type": "header",
                "description": "Header priority over table content"
            },
            
            # Table with figure reference should prioritize table
            {
                "content": "Table 1: Performance metrics (see Figure 2)\nMethod A: 95%\nMethod B: 87%",
                "metadata": {
                    "element_type": "table", 
                    "references_figure": True,
                    "semantic_types": {"table", "figure_caption"},
                    "source_elements": ["table", "figure_caption"]
                },
                "expected_type": "table",
                "description": "Table priority over figure references"
            },
            
            # Figure caption with table data should prioritize figure_caption
            {
                "content": "Figure 1: Data table showing Method A: 95%, Method B: 87%",
                "metadata": {
                    "element_type": "figure_caption", 
                    "contains_data": True,
                    "semantic_types": {"figure_caption", "table"},
                    "source_elements": ["figure_caption", "table"]
                },
                "expected_type": "figure_caption",
                "description": "Figure caption priority over tabular data"
            }
        ]
        
        all_test_cases = test_cases + priority_test_cases
        
        # When/Then - test each semantic type scenario
        for i, test_case in enumerate(all_test_cases):
            chunk_id = i + 1
            page_num = 1
            
            # When
            chunk = await optimizer._create_chunk(
                test_case["content"], 
                chunk_id, 
                page_num, 
                test_case["metadata"]
            )
            
            # Then - verify semantic type determination
            assert isinstance(chunk, LLMChunk), f"Should return LLMChunk for test case {i+1}"
            assert hasattr(chunk, 'semantic_types'), f"Chunk should have semantic_types attribute for test case {i+1}"
            assert isinstance(chunk.semantic_types, str), f"Semantic type should be string for test case {i+1}"
            assert len(chunk.semantic_types) > 0, f"Semantic type should not be empty for test case {i+1}"
            
            # Verify expected semantic type
            actual_type = chunk.semantic_types
            expected_type = test_case["expected_type"]
            
            assert actual_type == expected_type, \
                f"Test case {i+1} ({test_case['description']}): Expected semantic type '{expected_type}', got '{actual_type}'"
        
        # Test content-based classification when metadata is minimal
        content_based_cases = [
            {
                "content": "# Introduction\n## Overview\nThis section provides an introduction.",
                "metadata": {},  # No explicit type hints
                "possible_types": ["header", "text", "mixed"],
                "description": "Markdown-style headers without metadata hints"
            },
            {
                "content": "| Column A | Column B |\n|----------|----------|\n| Value 1  | Value 2  |",
                "metadata": {},
                "possible_types": ["table", "mixed"],
                "description": "Markdown table format without metadata hints"
            },
            {
                "content": "Figure 1: This image shows the relationship between variables X and Y.",
                "metadata": {},
                "possible_types": ["figure_caption", "text"],
                "description": "Figure caption format without metadata hints"
            }
        ]
        
        for i, test_case in enumerate(content_based_cases):
            chunk_id = i + 1
            page_num = 1
            
            # When
            chunk = await optimizer._create_chunk(
                test_case["content"], 
                chunk_id, 
                page_num, 
                test_case["metadata"]
            )
            
            # Then - verify semantic type is reasonable based on content
            actual_type = chunk.semantic_types
            possible_types = test_case["possible_types"]
            
            assert actual_type in possible_types, \
                f"Content-based test {i+1} ({test_case['description']}): " \
                f"Expected one of {possible_types}, got '{actual_type}'"
        
        # Test edge cases for semantic type determination
        edge_cases = [
            {
                "content": "",  # This should raise ValueError from earlier test
                "metadata": {"element_type": "paragraph"},
                "should_raise": True,
                "description": "Empty content"
            },
            {
                "content": "Valid content",
                "metadata": {"element_type": "unknown_type"},
                "expected_fallback": "text",
                "description": "Unknown element type should fall back to text"
            },
            {
                "content": "Mixed content with Table: data and Figure: reference",
                "metadata": {"element_type": "paragraph", "has_mixed_elements": True},
                "possible_types": ["mixed", "text"],
                "description": "Content with multiple semantic indicators"
            }
        ]
        
        for i, test_case in enumerate(edge_cases):
            chunk_id = i + 1
            page_num = 1
            
            if test_case.get("should_raise", False):
                # This case should raise an exception (empty content)
                with pytest.raises((ValueError, TypeError, AttributeError)):
                    await optimizer._create_chunk(
                        test_case["content"], 
                        chunk_id, 
                        page_num, 
                        test_case["metadata"]
                    )
            else:
                # When
                chunk = await optimizer._create_chunk(
                    test_case["content"], 
                    chunk_id, 
                    page_num, 
                    test_case["metadata"]
                )
                
                # Then - verify appropriate fallback or handling
                actual_type = chunk.semantic_types
                
                if "expected_fallback" in test_case:
                    expected_fallback = test_case["expected_fallback"]
                    assert actual_type == expected_fallback, \
                        f"Edge case {i+1} ({test_case['description']}): " \
                        f"Expected fallback '{expected_fallback}', got '{actual_type}'"
                
                if "possible_types" in test_case:
                    possible_types = test_case["possible_types"]
                    assert actual_type in possible_types, \
                        f"Edge case {i+1} ({test_case['description']}): " \
                        f"Expected one of {possible_types}, got '{actual_type}'"
        
        # Verify semantic type consistency across similar content
        similar_content_cases = [
            {
                "content": "Table 1: Research Results",
                "metadata": {"element_type": "table"},
            },
            {
                "content": "Table 2: Additional Results", 
                "metadata": {"element_type": "table"},
            }
        ]
        
        semantic_types = []
        for i, test_case in enumerate(similar_content_cases):
            chunk_id = i + 1
            chunk = await optimizer._create_chunk(
                test_case["content"], 
                chunk_id, 
                1, 
                test_case["metadata"]
            )
            semantic_types.append(chunk.semantic_types)
        
        # All similar content should have the same semantic type
        assert len(set(semantic_types)) == 1, \
            f"Similar content should have consistent semantic types, got: {semantic_types}"
        assert semantic_types[0] == "table", \
            f"Table content should be classified as 'table', got: {semantic_types[0]}"

    @pytest.mark.asyncio
    async def test_create_chunk_id_formatting(self):
        """
        GIVEN chunk_id parameter
        WHEN _create_chunk is called
        THEN expect:
            - Formatted chunk_id string preserved exactly
            - Consistent chunk_id handling across calls
            - Unique identifiers maintained
        """
        
        # Given
        optimizer = LLMOptimizer()
        
        content = "Test content for chunk ID formatting validation"
        page_num = 1
        metadata = {"element_type": "paragraph"}
        
        # Test cases for different chunk_id formats
        chunk_id_test_cases = [
            # Standard formatted IDs
            "chunk_0001",
            "chunk_0042", 
            "chunk_1000",
            
            # Alternative formatting styles
            # Note: These should FAIL!!!
            "chunk_001",
            "chunk_42",
            "section_1_chunk_5",
            "doc_123_chunk_456",
            
            # Non-standard but valid IDs
            # Note: These should fail too!
            "chunk-001",
            "chunk.001",
            "CHUNK_001",
            "chunk_A001",
            
            # Edge cases
            "a",  # Single character
            "chunk_0",  # Zero padding
            "very_long_chunk_identifier_with_descriptive_name_001"  # Long ID
        ]
        
        created_chunks = []
        
        # When - create chunks with different ID formats
        for i, chunk_id in enumerate(chunk_id_test_cases):
            chunk = await optimizer._create_chunk(
                f"{content} {i+1}",  # Slightly different content
                chunk_id, 
                page_num, 
                metadata.copy()
            )
            created_chunks.append(chunk)
        
        # Then - verify chunk_id formatting and consistency
        
        # 1. Verify chunk_id preservation - IDs should be preserved exactly as provided
        for i, (original_id, chunk) in enumerate(zip(chunk_id_test_cases, created_chunks)):
            assert chunk.chunk_id == original_id, \
                f"Test case {i+1}: Chunk ID should be preserved exactly. Expected '{original_id}', got '{chunk.chunk_id}'"
        
        # 2. Verify all chunk IDs are strings
        for i, chunk in enumerate(created_chunks):
            assert isinstance(chunk.chunk_id, str), \
                f"Test case {i+1}: Chunk ID should be string type, got {type(chunk.chunk_id)}"
            assert len(chunk.chunk_id) > 0, \
                f"Test case {i+1}: Chunk ID should not be empty"
        
        # 3. Verify uniqueness - all provided IDs should remain unique
        chunk_ids = [chunk.chunk_id for chunk in created_chunks]
        unique_chunk_ids = set(chunk_ids)
        assert len(chunk_ids) == len(unique_chunk_ids), \
            f"All chunk IDs should be unique. Found duplicates in: {chunk_ids}"
        
        # 4. Verify chunk_id consistency across multiple calls with same parameters
        consistent_id = "chunk_consistency_test"
        consistent_content = "Consistent content for testing"
        
        chunk1 = await optimizer._create_chunk(consistent_content, consistent_id, page_num, metadata.copy())
        chunk2 = await optimizer._create_chunk(consistent_content, consistent_id, page_num, metadata.copy())
        
        assert chunk1.chunk_id == consistent_id, "First chunk should have correct ID"
        assert chunk2.chunk_id == consistent_id, "Second chunk should have correct ID"
        assert chunk1.chunk_id == chunk2.chunk_id, "Chunks with same ID parameter should have same chunk_id"
        
        # 5. Test special characters in chunk IDs
        special_char_test_cases = [
            "chunk_with_underscore",
            "chunk-with-dash", 
            "chunk.with.dots",
            "chunk with spaces",  # May or may not be supported
            "chunk@special#chars",  # May or may not be supported
            "chunk_αβγ_unicode",  # Unicode characters
        ]
        
        for special_id in special_char_test_cases:
            try:
                chunk = await optimizer._create_chunk(
                    "Content for special character test",
                    special_id,
                    page_num,
                    metadata.copy()
                )
                # If creation succeeds, verify ID is preserved
                assert chunk.chunk_id == special_id, \
                    f"Special character ID should be preserved: expected '{special_id}', got '{chunk.chunk_id}'"
            except (ValueError, TypeError) as e:
                # Some special characters may not be supported - this is acceptable
                error_msg = str(e).lower()
                assert any(keyword in error_msg for keyword in ["invalid", "character", "format", "id"]), \
                    f"Error for special character ID should be descriptive: {e}"
        
        # 6. Test chunk_id immutability - ID should not change after creation
        test_chunk = created_chunks[0]
        original_id = test_chunk.chunk_id
        
        # Attempt to modify chunk_id (should not affect internal state)
        try:
            test_chunk.chunk_id = "modified_id"
            # If modification is allowed, it should be reflected
            if hasattr(test_chunk, '_chunk_id') or test_chunk.chunk_id == "modified_id":
                # Dataclass allows modification
                assert test_chunk.chunk_id == "modified_id", "If modification is allowed, it should be reflected"
            else:
                # Some protection mechanism exists
                assert test_chunk.chunk_id == original_id, "Chunk ID should remain unchanged if protected"
        except AttributeError:
            # ID is read-only or protected
            assert test_chunk.chunk_id == original_id, "Protected chunk ID should remain unchanged"
        
        # 7. Test numeric chunk_id handling (if integers are passed)
        numeric_test_cases = [
            1,
            42, 
            1000,
            0
        ]
        
        for numeric_id in numeric_test_cases:
            try:
                chunk = await optimizer._create_chunk(
                    f"Content for numeric ID {numeric_id}",
                    str(numeric_id),  # Convert to string as expected by interface
                    page_num,
                    metadata.copy()
                )
                # Should work with string conversion
                assert chunk.chunk_id == str(numeric_id), \
                    f"Numeric ID converted to string should be preserved: expected '{str(numeric_id)}', got '{chunk.chunk_id}'"
            except (ValueError, TypeError):
                # If numeric IDs require specific formatting, that's acceptable
                pass
        
        # 8. Test ID length limits (if any)
        very_long_id = "chunk_" + "x" * 1000  # Very long ID
        
        try:
            chunk = await optimizer._create_chunk(
                "Content for very long ID test",
                very_long_id,
                page_num,
                metadata.copy()
            )
            # If long IDs are supported, verify preservation
            assert chunk.chunk_id == very_long_id, "Very long ID should be preserved if supported"
        except (ValueError, TypeError) as e:
            # Length limits are acceptable
            error_msg = str(e).lower()
            assert any(keyword in error_msg for keyword in ["length", "long", "limit", "size"]), \
                f"Error for long ID should mention length issue: {e}"
        
        # 9. Verify chunk_id appears in string representation
        sample_chunk = created_chunks[0]
        chunk_str = str(sample_chunk)
        chunk_repr = repr(sample_chunk)
        
        assert sample_chunk.chunk_id in chunk_str or sample_chunk.chunk_id in chunk_repr, \
            "Chunk ID should appear in string representation for debugging"
        
        # 10. Test empty string chunk_id (should be invalid)
        with pytest.raises((ValueError, TypeError, AttributeError)):
            await optimizer._create_chunk(
                "Content for empty ID test",
                "",  # Empty string ID
                page_num,
                metadata.copy()
            )
        
        # 11. Test None chunk_id (should be invalid)
        with pytest.raises((ValueError, TypeError, AttributeError)):
            await optimizer._create_chunk(
                "Content for None ID test", 
                None,  # None ID
                page_num,
                metadata.copy()
            )

    @pytest.mark.asyncio
    async def test_create_chunk_metadata_enhancement(self):
        """
        GIVEN basic metadata
        WHEN _create_chunk is called
        THEN expect:
            - Timestamps added to metadata
            - Source element counts included
            - Processing information tracked
        """
        
        # Given
        optimizer = LLMOptimizer()
        
        content = "This is test content for metadata enhancement validation. " \
                    "It contains multiple sentences to test processing information tracking."
        
        chunk_id = 1
        page_num = 1
        
        # Basic metadata provided by user
        basic_metadata = {
            "element_type": "paragraph",
            "element_id": "p1",
            "section": "introduction",
            "confidence": 0.95,
            "source_file": "test_document.pdf",
            "extraction_method": "text_analysis",
            "original_position": {"x": 100, "y": 200}
        }
        
        # Record time before chunk creation for timestamp validation
        before_creation = time.time()
        before_creation_iso = datetime.now().isoformat()
        
        # When
        chunk = await optimizer._create_chunk(content, chunk_id, page_num, basic_metadata.copy())
        
        # Record time after chunk creation
        after_creation = time.time()
        after_creation_iso = datetime.now().isoformat()
        
        # Then - verify basic structure and original metadata preservation
        assert isinstance(chunk, LLMChunk), "Should return LLMChunk instance"
        assert isinstance(chunk.metadata, dict), "Metadata should be dictionary"
        
        # Verify all original metadata is preserved
        for key, value in basic_metadata.items():
            assert key in chunk.metadata, f"Original metadata key '{key}' should be preserved"
            assert chunk.metadata[key] == value, f"Original metadata value for '{key}' should be preserved: expected {value}, got {chunk.metadata[key]}"
        
        # Test timestamp enhancement
        timestamp_fields = ["creation_timestamp", "processing_timestamp", "created_at", "processed_at"]
        
        # At least one timestamp field should be present
        timestamp_fields_present = [field for field in timestamp_fields if field in chunk.metadata]
        assert len(timestamp_fields_present) > 0, f"At least one timestamp field should be added: {list(chunk.metadata.keys())}"
        
        # Validate timestamp format and accuracy
        for field in timestamp_fields_present:
            timestamp_value = chunk.metadata[field]
            
            # Test different possible timestamp formats
            if isinstance(timestamp_value, str):
                # ISO format timestamp
                try:
                    parsed_time = datetime.fromisoformat(timestamp_value.replace('Z', '+00:00'))
                    timestamp_seconds = parsed_time.timestamp()
                except ValueError:
                    # Unix timestamp string
                    try:
                        timestamp_seconds = float(timestamp_value)
                    except ValueError:
                        pytest.fail(f"Timestamp field '{field}' has invalid format: {timestamp_value}")
            elif isinstance(timestamp_value, (int, float)):
                # Unix timestamp
                timestamp_seconds = float(timestamp_value)
            else:
                pytest.fail(f"Timestamp field '{field}' has invalid type: {type(timestamp_value)}")
            
            # Verify timestamp is reasonable (within processing window)
            assert before_creation <= timestamp_seconds <= after_creation, \
                f"Timestamp field '{field}' is outside processing window: {timestamp_seconds} not in [{before_creation}, {after_creation}]"
        
        # Test source element counts enhancement
        element_count_fields = ["content_length", "word_count", "sentence_count", "character_count"]
        
        # At least some count fields should be present
        count_fields_present = [field for field in element_count_fields if field in chunk.metadata]
        assert len(count_fields_present) > 0, f"At least one count field should be added: {list(chunk.metadata.keys())}"
        
        # Validate count accuracy
        actual_word_count = len(content.split())
        actual_char_count = len(content)
        actual_sentence_count = len([s for s in content.split('.') if s.strip()])
        
        for field in count_fields_present:
            count_value = chunk.metadata[field]
            assert isinstance(count_value, int), f"Count field '{field}' should be integer, got {type(count_value)}"
            assert count_value >= 0, f"Count field '{field}' should be non-negative, got {count_value}"
            
            # Validate specific counts
            if field == "word_count":
                assert count_value == actual_word_count, f"Word count mismatch: expected {actual_word_count}, got {count_value}"
            elif field == "character_count" or field == "content_length":
                assert count_value == actual_char_count, f"Character count mismatch: expected {actual_char_count}, got {count_value}"
            elif field == "sentence_count":
                # Allow some flexibility in sentence counting logic
                assert abs(count_value - actual_sentence_count) <= 2, f"Sentence count roughly correct: expected ~{actual_sentence_count}, got {count_value}"
        
        # Test processing information tracking
        processing_fields = ["processing_method", "tokenizer_used", "model_version", "chunk_version", "processing_stage"]
        
        processing_fields_present = [field for field in processing_fields if field in chunk.metadata]
        assert len(processing_fields_present) > 0, f"At least one processing field should be added: {list(chunk.metadata.keys())}"
        
        # Validate processing information
        for field in processing_fields_present:
            processing_value = chunk.metadata[field]
            assert isinstance(processing_value, str), f"Processing field '{field}' should be string, got {type(processing_value)}"
            assert len(processing_value) > 0, f"Processing field '{field}' should not be empty"
            
            # Validate specific processing fields
            if field == "tokenizer_used":
                expected_tokenizers = ["gpt-3.5-turbo", "gpt-4", "tiktoken", "transformers"]
                assert any(tokenizer in processing_value for tokenizer in expected_tokenizers), \
                    f"Tokenizer field should contain recognized tokenizer: {processing_value}"
            elif field == "processing_method":
                expected_methods = ["llm_optimization", "text_chunking", "semantic_analysis"]
                assert any(method in processing_value for method in expected_methods), \
                    f"Processing method should be recognized: {processing_value}"
        
        # Test token count enhancement in metadata
        token_fields = ["token_count", "estimated_tokens", "token_calculation_method"]
        
        token_fields_present = [field for field in token_fields if field in chunk.metadata]
        
        for field in token_fields_present:
            if field in ["token_count", "estimated_tokens"]:
                token_value = chunk.metadata[field]
                assert isinstance(token_value, int), f"Token field '{field}' should be integer"
                assert token_value > 0, f"Token field '{field}' should be positive"
                # Should match the chunk's token_count attribute
                if field == "token_count":
                    assert token_value == chunk.token_count, f"Metadata token_count should match chunk.token_count"
            elif field == "token_calculation_method":
                method_value = chunk.metadata[field]
                assert isinstance(method_value, str), f"Token calculation method should be string"
                assert len(method_value) > 0, f"Token calculation method should not be empty"
        
        # Test semantic analysis enhancement
        semantic_fields = ["semantic_types", "content_complexity", "readability_score", "language_detected"]
        
        semantic_fields_present = [field for field in semantic_fields if field in chunk.metadata]
        
        for field in semantic_fields_present:
            semantic_value = chunk.metadata[field]
            
            if field == "semantic_types":
                assert isinstance(semantic_value, str), f"Semantic type should be string"
                expected_types = ["text", "paragraph", "header", "table", "mixed", "figure_caption"]
                assert semantic_value in expected_types, f"Semantic type should be recognized: {semantic_value}"
                # Should match chunk's semantic_types attribute
                assert semantic_value == chunk.semantic_types, f"Metadata semantic_types should match chunk.semantic_types"
            elif field in ["content_complexity", "readability_score"]:
                assert isinstance(semantic_value, (int, float)), f"{field} should be numeric"
                assert 0 <= semantic_value <= 1, f"{field} should be between 0 and 1: {semantic_value}"
            elif field == "language_detected":
                assert isinstance(semantic_value, str), f"Language should be string"
                assert len(semantic_value) >= 2, f"Language code should be at least 2 characters: {semantic_value}"
        
        # Test metadata structure preservation
        assert "element_type" in chunk.metadata, "Original element_type should be preserved"
        assert "element_id" in chunk.metadata, "Original element_id should be preserved"
        assert "section" in chunk.metadata, "Original section should be preserved"
        
        # Test enhanced metadata doesn't overwrite original metadata
        for original_key in basic_metadata.keys():
            assert chunk.metadata[original_key] == basic_metadata[original_key], \
                f"Enhanced metadata should not overwrite original value for '{original_key}'"
        
        # Test metadata size is reasonable (not excessively large)
        metadata_size = len(str(chunk.metadata))
        assert metadata_size < 10000, f"Enhanced metadata should be reasonable size, got {metadata_size} characters"
        
        # Test consistency across multiple chunk creations
        chunk2 = await optimizer._create_chunk(
            "Different content for consistency test",
            "chunk_meta_002", 
            page_num,
            basic_metadata.copy()
        )
        
        # Both chunks should have similar enhancement patterns
        enhanced_fields_chunk1 = set(chunk.metadata.keys()) - set(basic_metadata.keys())
        enhanced_fields_chunk2 = set(chunk2.metadata.keys()) - set(basic_metadata.keys())
        
        # Should have significant overlap in enhanced fields
        common_enhanced_fields = enhanced_fields_chunk1.intersection(enhanced_fields_chunk2)
        assert len(common_enhanced_fields) >= len(enhanced_fields_chunk1) * 0.7, \
            f"Chunks should have consistent enhancement patterns: {enhanced_fields_chunk1} vs {enhanced_fields_chunk2}"
        
        # Test edge cases for metadata enhancement
        
        # Test with minimal basic metadata
        minimal_metadata = {"element_type": "paragraph"}
        
        chunk_minimal = await optimizer._create_chunk(
            "Content with minimal metadata",
            "chunk_meta_minimal",
            page_num,
            minimal_metadata.copy()
        )
        
        # Should still enhance metadata even with minimal input
        enhanced_minimal = set(chunk_minimal.metadata.keys()) - set(minimal_metadata.keys())
        assert len(enhanced_minimal) > 0, "Should enhance metadata even with minimal input"
        
        # Test with extensive existing metadata
        extensive_metadata = {
            **basic_metadata,
            "additional_field_1": "value1",
            "additional_field_2": "value2", 
            "nested_metadata": {"sub_field": "sub_value"},
            "list_metadata": ["item1", "item2"],
            "numeric_metadata": 42
        }
        
        chunk_extensive = await optimizer._create_chunk(
            "Content with extensive metadata",
            "chunk_meta_extensive",
            page_num,
            extensive_metadata.copy()
        )
        
        # All original extensive metadata should be preserved
        for key, value in extensive_metadata.items():
            assert key in chunk_extensive.metadata, f"Extensive metadata key '{key}' should be preserved"
            assert chunk_extensive.metadata[key] == value, f"Extensive metadata value for '{key}' should be preserved"
        
        # Should still add enhancements
        enhanced_extensive = set(chunk_extensive.metadata.keys()) - set(extensive_metadata.keys())
        assert len(enhanced_extensive) > 0, "Should still enhance extensive metadata"
        
        # Test metadata type preservation
        for key, value in chunk_extensive.metadata.items():
            if key in extensive_metadata:
                assert type(value) == type(extensive_metadata[key]), \
                    f"Metadata type should be preserved for '{key}': expected {type(extensive_metadata[key])}, got {type(value)}"

    @pytest.mark.asyncio
    async def test_create_chunk_token_counting_failure(self):
        """
        GIVEN content that causes token counting to fail
        WHEN _create_chunk is called
        THEN expect:
            - ValueError raised or fallback counting used
            - Error handling graceful
            - Processing can continue
        """
        import unittest.mock

        # Given
        optimizer = LLMOptimizer()
        
        content = "This is valid content that should normally count tokens correctly."
        chunk_id = 1
        page_num = 1
        metadata = {"element_type": "paragraph"}
        
        # Test case 1: Mock token counting to raise an exception
        with unittest.mock.patch.object(optimizer, '_count_tokens', side_effect=Exception("Token counting failed")):
            try:
                # When - attempt to create chunk with failing token counter
                chunk = await optimizer._create_chunk(content, chunk_id, page_num, metadata)
                
                # Then - if no exception, verify fallback was used
                assert isinstance(chunk, LLMChunk), "Should return LLMChunk even with token counting failure"
                assert chunk.content == content, "Content should be preserved"
                assert chunk.chunk_id == "chunk_0001", "Chunk ID should be preserved"
                assert isinstance(chunk.token_count, int), "Token count should be integer (fallback value)"
                assert chunk.token_count > 0, "Fallback token count should be positive"
                
                # Fallback might estimate based on word count or character count
                word_count = len(content.split())
                char_count = len(content)
                
                # Verify fallback is reasonable (could be word count * 1.3 or char count / 4 or similar)
                assert 1 <= chunk.token_count <= max(word_count * 3, char_count), \
                    f"Fallback token count {chunk.token_count} should be reasonable for content length"
                
            except (ValueError, RuntimeError, Exception) as e:
                # If exception is raised, verify it's informative
                error_msg = str(e).lower()
                assert any(keyword in error_msg for keyword in ["token", "count", "counting", "failed"]), \
                    f"Error should mention token counting issue: {e}"
        
        # Test case 2: Mock _count_tokens to return invalid values
        invalid_token_values = [None, -1, "invalid", [], 0.5]
        
        for invalid_value in invalid_token_values:
            with unittest.mock.patch.object(optimizer, '_count_tokens', return_value=invalid_value):
                try:
                    chunk = await optimizer._create_chunk(
                        f"{content} {invalid_value}",  # Unique content
                        f"{chunk_id}_{invalid_value}",
                        page_num,
                        metadata.copy()
                    )
                    
                    # Should handle invalid token count gracefully
                    assert isinstance(chunk, LLMChunk), f"Should return LLMChunk even with invalid token count {invalid_value}"
                    assert isinstance(chunk.token_count, int), f"Should convert invalid token count {invalid_value} to valid integer"
                    assert chunk.token_count > 0, f"Should provide positive fallback for invalid token count {invalid_value}"
                    
                except (ValueError, TypeError) as e:
                    # Acceptable to raise error for invalid token count
                    error_msg = str(e).lower()
                    assert any(keyword in error_msg for keyword in ["token", "invalid", "count"]), \
                        f"Error for invalid token count {invalid_value} should be descriptive: {e}"
        
        # Test case 3: Test with problematic content that might cause encoding issues
        problematic_content_cases = [
            "Content with unicode: 你好世界 🌍 αβγ",  # Unicode characters
            "Content with emoji: 😀🎉🔥💯",  # Emoji characters
            "Content\x00with\x01control\x02characters",  # Control characters
            "Content with very long word: " + "x" * 1000,  # Very long tokens
            "\n\t\r   Whitespace heavy content   \n\t\r",  # Whitespace-heavy
        ]
        
        for i, problematic_content in enumerate(problematic_content_cases):
            try:
                chunk = await optimizer._create_chunk(
                    problematic_content,
                    f"chunk_problematic_{i+1:03d}",
                    page_num,
                    metadata.copy()
                )
                
                # Should handle problematic content gracefully
                assert isinstance(chunk, LLMChunk), f"Should handle problematic content case {i+1}"
                assert chunk.content == problematic_content, f"Content should be preserved for case {i+1}"
                assert isinstance(chunk.token_count, int), f"Token count should be integer for case {i+1}"
                assert chunk.token_count >= 0, f"Token count should be non-negative for case {i+1}"
                
            except (ValueError, UnicodeError, Exception) as e:
                # Some problematic content might legitimately cause errors
                error_msg = str(e).lower()
                acceptable_errors = ["unicode", "encoding", "token", "character", "invalid"]
                assert any(keyword in error_msg for keyword in acceptable_errors), \
                    f"Error for problematic content case {i+1} should be related to content issues: {e}"
        
        # Test case 4: Mock tokenizer to be unavailable
        with unittest.mock.patch.object(optimizer, 'tokenizer', None):
            try:
                chunk = await optimizer._create_chunk(
                    "Content without tokenizer",
                    "chunk_no_tokenizer",
                    page_num,
                    metadata.copy()
                )
                
                # Should use fallback counting method
                assert isinstance(chunk, LLMChunk), "Should work without tokenizer"
                assert isinstance(chunk.token_count, int), "Should provide fallback token count"
                assert chunk.token_count > 0, "Fallback should provide positive count"
                
            except (AttributeError, ValueError) as e:
                # Acceptable to fail if tokenizer is required
                error_msg = str(e).lower()
                assert any(keyword in error_msg for keyword in ["tokenizer", "not", "available", "missing"]), \
                    f"Error should mention tokenizer unavailability: {e}"
        
        # Test case 5: Test token counting consistency after failure recovery
        # First create a chunk normally
        normal_chunk = await optimizer._create_chunk(
            "Normal content for comparison",
            "chunk_normal",
            page_num,
            metadata.copy()
        )
        
        # Then simulate failure and recovery
        with unittest.mock.patch.object(optimizer, '_count_tokens', side_effect=[Exception("Fail"), normal_chunk.token_count]):
            try:
                # First call should fail or use fallback
                chunk_after_failure = await optimizer._create_chunk(
                    "Content after token counting failure",
                    "chunk_after_failure",
                    page_num,
                    metadata.copy()
                )
            except Exception as e:
                pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
