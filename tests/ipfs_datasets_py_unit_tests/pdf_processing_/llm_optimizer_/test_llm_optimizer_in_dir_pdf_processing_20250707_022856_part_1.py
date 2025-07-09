
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer.py
# Auto-generated on 2025-07-07 02:28:56"

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
import asyncio
import logging
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import re

import tiktoken
from transformers import AutoTokenizer
import numpy as np
from sentence_transformers import SentenceTransformer


class TestQualityOfObjectsInModule:
    """
    Test class for the quality of callable objects 
    (e.g. class, method, function, coroutine, or property) in the module.
    """

    def test_callable_objects_metadata_quality(self):
        """
        GIVEN a Python module
        WHEN the module is parsed by the AST
        THEN
         - Each callable object should have a detailed, Google-style docstring.
         - Each callable object should have a detailed signature with type hints and a return annotation.
        """
        tree = get_ast_tree(file_path)
        try:
            raise_on_bad_callable_metadata(tree)
        except (BadDocumentationError, BadSignatureError) as e:
            pytest.fail(f"Code metadata quality check failed: {e}")

    def test_callable_objects_quality(self):
        """
        GIVEN a Python module
        WHEN the module's source code is examined
        THEN if the file is not indicated as a mock, placeholder, stub, or example:
         - The module should not contain intentionally fake or simplified code 
            (e.g. "In a real implementation, ...")
         - Contain no mocked objects or placeholders.
        """
        try:
            raise_on_bad_callable_code_quality(file_path)
        except (BadDocumentationError, BadSignatureError) as e:
            for indicator in ["mock", "placeholder", "stub", "example"]:
                if indicator in file_path:
                    break
            else:
                # If no indicator is found, fail the test
                pytest.fail(f"Code quality check failed: {e}")


class TestChunkOptimizerInitialization:
    """Test ChunkOptimizer initialization and configuration validation."""

    def test_init_with_valid_parameters(self):
        """
        GIVEN valid chunking parameters with max_size > min_size and overlap < max_size
        WHEN ChunkOptimizer is initialized
        THEN expect:
            - Instance created successfully
            - max_size attribute set correctly
            - overlap attribute set correctly  
            - min_size attribute set correctly
            - All parameters stored as expected types (int)
        """
        # Given
        max_size = 2048
        overlap = 200
        min_size = 100
        
        # When
        optimizer = ChunkOptimizer(max_size=max_size, overlap=overlap, min_size=min_size)
        
        # Then
        assert optimizer.max_size == max_size
        assert optimizer.overlap == overlap
        assert optimizer.min_size == min_size
        assert isinstance(optimizer.max_size, int)
        assert isinstance(optimizer.overlap, int)
        assert isinstance(optimizer.min_size, int)

    def test_init_with_boundary_conditions(self):
        """
        GIVEN boundary condition parameters (min valid values)
        WHEN ChunkOptimizer is initialized with max_size=2, overlap=1, min_size=1
        THEN expect:
            - Instance created successfully
            - Parameters accepted and stored correctly
        """
        # Given
        max_size = 2
        overlap = 1
        min_size = 1
        
        # When
        optimizer = ChunkOptimizer(max_size=max_size, overlap=overlap, min_size=min_size)
        
        # Then
        assert optimizer.max_size == max_size
        assert optimizer.overlap == overlap
        assert optimizer.min_size == min_size

    def test_init_max_size_less_than_or_equal_min_size(self):
        """
        GIVEN invalid parameters where max_size <= min_size
        WHEN ChunkOptimizer is initialized
        THEN expect ValueError to be raised with descriptive message
        """
        # Given - max_size equal to min_size
        with pytest.raises(ValueError):
            ChunkOptimizer(max_size=100, overlap=50, min_size=100)
        
        # Given - max_size less than min_size
        with pytest.raises(ValueError):
            ChunkOptimizer(max_size=50, overlap=25, min_size=100)

    def test_init_overlap_greater_than_or_equal_max_size(self):
        """
        GIVEN invalid parameters where overlap >= max_size
        WHEN ChunkOptimizer is initialized
        THEN expect ValueError to be raised with descriptive message
        """
        # Given - overlap equal to max_size
        with pytest.raises(ValueError):
            ChunkOptimizer(max_size=100, overlap=100, min_size=50)
        
        # Given - overlap greater than max_size
        with pytest.raises(ValueError):
            ChunkOptimizer(max_size=100, overlap=150, min_size=50)

    def test_init_negative_parameters(self):
        """
        GIVEN negative values for any parameter
        WHEN ChunkOptimizer is initialized
        THEN expect AssertionError or ValueError to be raised
        """
        # Given - negative max_size
        with pytest.raises((AssertionError, ValueError)):
            ChunkOptimizer(max_size=-100, overlap=50, min_size=25)
        
        # Given - negative overlap
        with pytest.raises((AssertionError, ValueError)):
            ChunkOptimizer(max_size=100, overlap=-50, min_size=25)
        
        # Given - negative min_size
        with pytest.raises((AssertionError, ValueError)):
            ChunkOptimizer(max_size=100, overlap=50, min_size=-25)

    def test_init_zero_parameters(self):
        """
        GIVEN zero values for any parameter
        WHEN ChunkOptimizer is initialized
        THEN expect AssertionError or ValueError to be raised
        """
        # Given - zero max_size
        with pytest.raises((AssertionError, ValueError)):
            ChunkOptimizer(max_size=0, overlap=50, min_size=25)
        
        # Given - zero overlap (this might be valid, but testing based on docstring)
        with pytest.raises((AssertionError, ValueError)):
            ChunkOptimizer(max_size=100, overlap=0, min_size=25)
        
        # Given - zero min_size
        with pytest.raises((AssertionError, ValueError)):
            ChunkOptimizer(max_size=100, overlap=50, min_size=0)

    def test_init_non_integer_parameters(self):
        """
        GIVEN non-integer parameters (float, string, None)
        WHEN ChunkOptimizer is initialized
        THEN expect ValueError to be raised
        """
        # Given - float max_size
        with pytest.raises(ValueError):
            ChunkOptimizer(max_size=100.5, overlap=50, min_size=25)
        
        # Given - string overlap
        with pytest.raises(ValueError):
            ChunkOptimizer(max_size=100, overlap="50", min_size=25)
        
        # Given - None min_size
        with pytest.raises(ValueError):
            ChunkOptimizer(max_size=100, overlap=50, min_size=None)


class TestChunkOptimizerOptimizeChunkBoundaries:
    """Test optimize_chunk_boundaries method functionality and edge cases."""


    def test_optimize_boundaries_with_paragraph_breaks(self):
        """
        GIVEN text with clear paragraph breaks (\n\n) and current boundaries
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Boundaries adjusted to align with paragraph breaks
            - Optimized positions respect natural document structure
            - Return type is List[int]
            - All boundary positions are valid indices within text
        """
        # Given
        text = "First paragraph content.\n\nSecond paragraph content here.\n\nThird paragraph with more text."
        current_boundaries = [25, 60]  # Arbitrary positions
        optimizer = ChunkOptimizer(max_size=1024, overlap=100, min_size=50)
        
        # When
        optimized = optimizer.optimize_chunk_boundaries(text, current_boundaries)
        
        # Then
        assert isinstance(optimized, list)
        assert len(optimized) == len(current_boundaries)
        for boundary in optimized:
            assert isinstance(boundary, int)
            assert 0 <= boundary <= len(text)
        # Should align near paragraph breaks at positions around 25 and 60

    def test_optimize_boundaries_with_sentence_endings(self):
        """
        GIVEN text with sentence endings (. ! ?) but no paragraph breaks
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Boundaries adjusted to align with sentence endings
            - Preference given to sentence boundaries over arbitrary positions
            - Original boundary count preserved
        """
        # Given
        text = "First sentence here. Second sentence content! Third sentence with question? Fourth sentence."
        current_boundaries = [25, 60]  # Somewhere in middle of sentences
        optimizer = ChunkOptimizer(max_size=1024, overlap=100, min_size=50)
        
        # When
        optimized = optimizer.optimize_chunk_boundaries(text, current_boundaries)
        
        # Then
        assert isinstance(optimized, list)
        assert len(optimized) == len(current_boundaries)
        for boundary in optimized:
            assert isinstance(boundary, int)
            assert 0 <= boundary <= len(text)

    def test_optimize_boundaries_mixed_structures(self):
        """
        GIVEN text with both paragraph breaks and sentence endings
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Paragraph breaks prioritized over sentence endings
            - Boundaries moved to most appropriate natural stopping points
            - Reasonable proximity to original positions maintained
        """
        # Given
        text = "First sentence. Second sentence.\n\nNew paragraph starts. Another sentence here! More content."
        current_boundaries = [25, 65]  # Near both sentence and paragraph boundaries
        optimizer = ChunkOptimizer(max_size=1024, overlap=100, min_size=50)
        
        # When
        optimized = optimizer.optimize_chunk_boundaries(text, current_boundaries)
        
        # Then
        assert isinstance(optimized, list)
        assert len(optimized) == len(current_boundaries)
        for boundary in optimized:
            assert isinstance(boundary, int)
            assert 0 <= boundary <= len(text)

    def test_optimize_boundaries_no_natural_breaks(self):
        """
        GIVEN continuous text without clear sentence or paragraph boundaries
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Original boundary positions preserved
            - No adjustments made when natural boundaries unavailable
            - Return original boundary list unchanged
        """
        # Given
        text = "continuousTextwithoutanyBreaksorpunctuationjustOneVeryLongStringOfTextThatHasNoNaturalBoundariesAtAll"
        current_boundaries = [25, 60]
        optimizer = ChunkOptimizer(max_size=1024, overlap=100, min_size=50)
        
        # When
        optimized = optimizer.optimize_chunk_boundaries(text, current_boundaries)
        
        # Then
        assert isinstance(optimized, list)
        assert len(optimized) == len(current_boundaries)
        # Should preserve original boundaries when no natural breaks found
        assert optimized == current_boundaries

    def test_optimize_boundaries_empty_text(self):
        """
        GIVEN empty text string
        WHEN optimize_chunk_boundaries is called with any boundaries
        THEN expect ValueError to be raised
        """
        # Given
        text = ""
        current_boundaries = [10, 20]
        optimizer = ChunkOptimizer(max_size=1024, overlap=100, min_size=50)
        
        # When/Then
        with pytest.raises(ValueError):
            optimizer.optimize_chunk_boundaries(text, current_boundaries)

    def test_optimize_boundaries_empty_boundary_list(self):
        """
        GIVEN valid text and empty boundary list
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Empty list returned
            - No errors raised
            - Method handles edge case gracefully
        """
        # Given
        text = "Some valid text with sentences. And paragraph breaks."
        current_boundaries = []
        optimizer = ChunkOptimizer(max_size=1024, overlap=100, min_size=50)
        
        # When
        optimized = optimizer.optimize_chunk_boundaries(text, current_boundaries)
        
        # Then
        assert isinstance(optimized, list)
        assert len(optimized) == 0
        assert optimized == []

    def test_optimize_boundaries_invalid_positions(self):
        """
        GIVEN boundary positions that exceed text length
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - IndexError handled gracefully with boundary clamping
            - Or boundaries adjusted to valid positions within text
        """
        # Given
        text = "Short text."
        current_boundaries = [50, 100]  # Way beyond text length
        optimizer = ChunkOptimizer(max_size=1024, overlap=100, min_size=50)
        
        # When
        optimized = optimizer.optimize_chunk_boundaries(text, current_boundaries)
        
        # Then
        assert isinstance(optimized, list)
        assert len(optimized) == len(current_boundaries)
        # All boundaries should be clamped to valid positions
        for boundary in optimized:
            assert 0 <= boundary <= len(text)

    def test_optimize_boundaries_single_boundary(self):
        """
        GIVEN text and single boundary position
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Single optimized boundary returned
            - Position adjusted to nearest natural break if available
        """
        # Given
        text = "First sentence. Second sentence with more content."
        current_boundaries = [20]  # In middle of second sentence
        optimizer = ChunkOptimizer(max_size=1024, overlap=100, min_size=50)
        
        # When
        optimized = optimizer.optimize_chunk_boundaries(text, current_boundaries)
        
        # Then
        assert isinstance(optimized, list)
        assert len(optimized) == 1
        assert isinstance(optimized[0], int)
        assert 0 <= optimized[0] <= len(text)

    def test_optimize_boundaries_non_integer_boundaries(self):
        """
        GIVEN boundary list containing non-integer values
        WHEN optimize_chunk_boundaries is called
        THEN expect ValueError to be raised
        """
        # Given
        text = "Some valid text content here."
        current_boundaries = [10.5, "20", None]
        optimizer = ChunkOptimizer(max_size=1024, overlap=100, min_size=50)
        
        # When/Then
        with pytest.raises(ValueError):
            optimizer.optimize_chunk_boundaries(text, current_boundaries)

    def test_optimize_boundaries_maintains_order(self):
        """
        GIVEN multiple boundaries in ascending order
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Returned boundaries maintain ascending order
            - No boundary positions become inverted or duplicated
        """
        # Given
        text = "First sentence. Second sentence. Third sentence. Fourth sentence. Fifth sentence."
        current_boundaries = [20, 40, 65]  # In ascending order
        optimizer = ChunkOptimizer(max_size=1024, overlap=100, min_size=50)
        
        # When
        optimized = optimizer.optimize_chunk_boundaries(text, current_boundaries)
        
        # Then
        assert isinstance(optimized, list)
        assert len(optimized) == len(current_boundaries)
        # Check boundaries are still in ascending order
        for i in range(1, len(optimized)):
            assert optimized[i-1] <= optimized[i]

    def test_optimize_boundaries_proximity_limit(self):
        """
        GIVEN boundaries and text where natural breaks are very far from original positions
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Original positions preserved when natural breaks too distant
            - Reasonable proximity threshold respected
        """
        # Given - boundaries far from any natural breaks
        text = "Very long sentence that goes on and on without any breaks for a very long time until finally ending here. Another very long sentence that continues for quite some time without natural stopping points until this end."
        current_boundaries = [80]  # In middle of long sentence, far from period
        optimizer = ChunkOptimizer(max_size=1024, overlap=100, min_size=50)
        
        # When
        optimized = optimizer.optimize_chunk_boundaries(text, current_boundaries)
        
        # Then
        assert isinstance(optimized, list)
        assert len(optimized) == len(current_boundaries)
        # Should preserve original boundary when natural breaks are too far
        assert optimized[0] == current_boundaries[0]


class TestChunkOptimizerAttributeAccess:
    """Test ChunkOptimizer attribute access and immutability."""


    def test_max_size_attribute_access(self):
        """
        GIVEN initialized ChunkOptimizer
        WHEN max_size attribute is accessed
        THEN expect correct value returned matching initialization parameter
        """
        # Given
        max_size = 2048
        optimizer = ChunkOptimizer(max_size=max_size, overlap=200, min_size=100)
        
        # When/Then
        assert optimizer.max_size == max_size
        assert hasattr(optimizer, 'max_size')

    def test_overlap_attribute_access(self):
        """
        GIVEN initialized ChunkOptimizer
        WHEN overlap attribute is accessed
        THEN expect correct value returned matching initialization parameter
        """
        # Given
        overlap = 200
        optimizer = ChunkOptimizer(max_size=2048, overlap=overlap, min_size=100)
        
        # When/Then
        assert optimizer.overlap == overlap
        assert hasattr(optimizer, 'overlap')

    def test_min_size_attribute_access(self):
        """
        GIVEN initialized ChunkOptimizer
        WHEN min_size attribute is accessed
        THEN expect correct value returned matching initialization parameter
        """
        # Given
        min_size = 100
        optimizer = ChunkOptimizer(max_size=2048, overlap=200, min_size=min_size)
        
        # When/Then
        assert optimizer.min_size == min_size
        assert hasattr(optimizer, 'min_size')

    def test_attribute_modification_prevention(self):
        """
        GIVEN initialized ChunkOptimizer
        WHEN attempts are made to modify core attributes
        THEN expect:
            - Attributes can be modified (no immutability enforced) OR
            - Proper error handling if immutability is implemented
        """
        # Given
        optimizer = ChunkOptimizer(max_size=2048, overlap=200, min_size=100)
        original_max_size = optimizer.max_size
        
        # When - attempt to modify attribute
        optimizer.max_size = 1024
        
        # Then - based on current implementation, attributes are mutable
        assert optimizer.max_size == 1024
        assert optimizer.max_size != original_max_size


class TestChunkOptimizerEdgeCasesAndPerformance:
    """Test ChunkOptimizer with edge cases and performance considerations."""

    def test_very_large_text_processing(self):
        """
        GIVEN very large text input (>100KB)
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Method completes within reasonable time
            - Memory usage remains manageable
            - Correct boundary optimization performed
        """
        # Given - large text (>100KB)
        large_text = "This is a test sentence. " * 5000  # ~125KB
        current_boundaries = [50000, 100000]
        optimizer = ChunkOptimizer(max_size=1024, overlap=100, min_size=50)
        
        # When
        import time
        start_time = time.time()
        optimized = optimizer.optimize_chunk_boundaries(large_text, current_boundaries)
        end_time = time.time()
        
        # Then
        assert isinstance(optimized, list)
        assert len(optimized) == len(current_boundaries)
        assert (end_time - start_time) < 5.0  # Should complete within 5 seconds

    def test_unicode_and_special_characters(self):
        """
        GIVEN text with Unicode characters, emojis, and special formatting
        WHEN optimize_chunk_boundaries is called
        THEN expect:
            - Unicode text handled correctly
            - Boundary detection works with non-ASCII characters
            - No encoding errors or character corruption
        """
        # Given
        text = "Hello 世界! This is a test 🌍. Ñice tëxt with áccents. Мультиязычный текст здесь."
        current_boundaries = [20, 40]
        optimizer = ChunkOptimizer(max_size=1024, overlap=100, min_size=50)
        
        # When
        optimized = optimizer.optimize_chunk_boundaries(text, current_boundaries)
        
        # Then
        assert isinstance(optimized, list)
        assert len(optimized) == len(current_boundaries)
        for boundary in optimized:
            assert isinstance(boundary, int)
            assert 0 <= boundary <= len(text)

    def test_malformed_text_input(self):
        """
        GIVEN malformed text input (None, non-string types)
        WHEN optimize_chunk_boundaries is called
        THEN expect appropriate error handling and type validation
        """
        # Given
        optimizer = ChunkOptimizer(max_size=1024, overlap=100, min_size=50)
        
        # When/Then - None text
        with pytest.raises((TypeError, AttributeError)):
            optimizer.optimize_chunk_boundaries(None, [10, 20])
        
        # When/Then - Non-string text
        with pytest.raises((TypeError, AttributeError)):
            optimizer.optimize_chunk_boundaries(12345, [10, 20])

    def test_boundary_optimization_consistency(self):
        """
        GIVEN identical text and boundary inputs
        WHEN optimize_chunk_boundaries is called multiple times
        THEN expect consistent results across all calls (deterministic behavior)
        """
        # Given
        text = "First sentence. Second sentence. Third sentence."
        current_boundaries = [20, 35]
        optimizer = ChunkOptimizer(max_size=1024, overlap=100, min_size=50)
        
        # When - call multiple times
        result1 = optimizer.optimize_chunk_boundaries(text, current_boundaries)
        result2 = optimizer.optimize_chunk_boundaries(text, current_boundaries)
        result3 = optimizer.optimize_chunk_boundaries(text, current_boundaries)
        
        # Then - should be deterministic
        assert result1 == result2 == result3


class TestLLMChunkDataclassStructure:
    """Test LLMChunk dataclass structure and field definitions."""

    def test_is_dataclass(self):
        """
        GIVEN LLMChunk class
        WHEN checked for dataclass decorator
        THEN expect LLMChunk to be properly decorated as a dataclass
        """
        from dataclasses import is_dataclass
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        
        # When/Then
        assert is_dataclass(LLMChunk)
        assert hasattr(LLMChunk, '__dataclass_fields__')

    def test_required_fields_present(self):
        """
        GIVEN LLMChunk dataclass
        WHEN inspecting field definitions
        THEN expect all required fields to be present:
            - content (str)
            - chunk_id (str)
            - source_page (int)
            - source_element (str)
            - token_count (int)
            - semantic_type (str)
            - relationships (List[str])
            - metadata (Dict[str, Any])
            - embedding (Optional[np.ndarray])
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        
        # When
        fields = LLMChunk.__dataclass_fields__
        field_names = set(fields.keys())
        
        # Then
        expected_fields = {
            'content', 'chunk_id', 'source_page', 'source_element',
            'token_count', 'semantic_type', 'relationships', 'metadata', 'embedding'
        }
        assert expected_fields.issubset(field_names)
        assert len(field_names) == len(expected_fields)

    def test_field_types_correct(self):
        """
        GIVEN LLMChunk dataclass fields
        WHEN inspecting field type annotations
        THEN expect:
            - content: str type annotation
            - chunk_id: str type annotation
            - source_page: int type annotation
            - source_element: str type annotation
            - token_count: int type annotation
            - semantic_type: str type annotation
            - relationships: List[str] type annotation
            - metadata: Dict[str, Any] type annotation
            - embedding: Optional[np.ndarray] type annotation
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        
        # When
        fields = LLMChunk.__dataclass_fields__
        
        # Then
        assert fields['content'].type == str
        assert fields['chunk_id'].type == str
        assert fields['source_page'].type == int
        assert fields['source_element'].type == str
        assert fields['token_count'].type == int
        assert fields['semantic_type'].type == str
        # Note: For complex types like List[str], we check that annotation exists
        assert hasattr(fields['relationships'], 'type')
        assert hasattr(fields['metadata'], 'type')
        assert hasattr(fields['embedding'], 'type')

    def test_field_defaults(self):
        """
        GIVEN LLMChunk dataclass fields
        WHEN inspecting default values
        THEN expect appropriate default values where specified in documentation
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        from dataclasses import MISSING
        
        # When
        fields = LLMChunk.__dataclass_fields__
        
        # Then - check which fields have defaults
        # Most fields should not have defaults (required)
        required_fields = ['content', 'chunk_id', 'source_page', 'source_element', 
                          'token_count', 'semantic_type', 'relationships', 'metadata']
        for field_name in required_fields:
            assert fields[field_name].default == MISSING
            assert fields[field_name].default_factory == MISSING
        
        # embedding should have default None
        assert fields['embedding'].default is None



class TestLLMChunkInstantiation:
    """Test LLMChunk instantiation with various parameter combinations."""

    def test_instantiation_with_all_fields(self):
        """
        GIVEN all required LLMChunk fields with valid values
        WHEN LLMChunk is instantiated
        THEN expect:
            - Instance created successfully
            - All fields accessible with correct values
            - No errors or exceptions raised
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        import numpy as np
        
        # Given
        embedding = np.array([0.1, 0.2, 0.3])
        
        # When
        chunk = LLMChunk(
            content="Test content here",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="paragraph",
            token_count=10,
            semantic_type="text",
            relationships=["chunk_0000", "chunk_0002"],
            metadata={"confidence": 0.9},
            embedding=embedding
        )
        
        # Then
        assert chunk.content == "Test content here"
        assert chunk.chunk_id == "chunk_0001"
        assert chunk.source_page == 1
        assert chunk.source_element == "paragraph"
        assert chunk.token_count == 10
        assert chunk.semantic_type == "text"
        assert chunk.relationships == ["chunk_0000", "chunk_0002"]
        assert chunk.metadata == {"confidence": 0.9}
        assert np.array_equal(chunk.embedding, embedding)

    def test_instantiation_with_minimal_fields(self):
        """
        GIVEN only required LLMChunk fields (no defaults)
        WHEN LLMChunk is instantiated
        THEN expect:
            - Instance created successfully if all required fields provided
            - Default values applied where appropriate
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        
        # When
        chunk = LLMChunk(
            content="Minimal content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        # Then
        assert chunk.content == "Minimal content"
        assert chunk.chunk_id == "chunk_0001"
        assert chunk.source_page == 1
        assert chunk.source_element == "text"
        assert chunk.token_count == 5
        assert chunk.semantic_type == "text"
        assert chunk.relationships == []
        assert chunk.metadata == {}
        assert chunk.embedding is None  # Default value

    def test_instantiation_missing_required_fields(self):
        """
        GIVEN missing required fields during instantiation
        WHEN LLMChunk is instantiated
        THEN expect ValueError to be raised for missing required parameters
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        
        # When/Then - missing content
        with pytest.raises(ValueError):
            LLMChunk(
                chunk_id="chunk_0001",
                source_page=1,
                source_element="text",
                token_count=5,
                semantic_type="text",
                relationships=[],
                metadata={}
            )
        
        # When/Then - missing multiple fields
        with pytest.raises(ValueError):
            LLMChunk(content="Test content")

    def test_instantiation_with_none_embedding(self):
        """
        GIVEN embedding field set to None
        WHEN LLMChunk is instantiated
        THEN expect:
            - Instance created successfully
            - embedding field properly set to None
            - Optional type handling works correctly
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        
        # When
        chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={},
            embedding=None
        )
        
        # Then
        assert chunk.embedding is None

    def test_instantiation_with_numpy_embedding(self):
        """
        GIVEN embedding field set to numpy array
        WHEN LLMChunk is instantiated
        THEN expect:
            - Instance created successfully
            - embedding field contains numpy array
            - Array shape and dtype preserved
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        import numpy as np
        
        # Given
        embedding = np.array([1.0, 2.0, 3.0, 4.0])
        
        # When
        chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={},
            embedding=embedding
        )
        
        # Then
        assert isinstance(chunk.embedding, np.ndarray)
        assert np.array_equal(chunk.embedding, embedding)
        assert chunk.embedding.shape == (4,)
        assert chunk.embedding.dtype == embedding.dtype

    def test_instantiation_with_empty_relationships(self):
        """
        GIVEN relationships field as empty list
        WHEN LLMChunk is instantiated
        THEN expect:
            - Instance created successfully
            - relationships field is empty list
            - List type maintained
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        
        # When
        chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        # Then
        assert isinstance(chunk.relationships, list)
        assert len(chunk.relationships) == 0
        assert chunk.relationships == []

    def test_instantiation_with_populated_relationships(self):
        """
        GIVEN relationships field with list of chunk IDs
        WHEN LLMChunk is instantiated
        THEN expect:
            - Instance created successfully
            - relationships field contains provided chunk IDs
            - List order preserved
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        
        # Given
        relationships = ["chunk_0000", "chunk_0002", "chunk_0003"]
        
        # When
        chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=relationships,
            metadata={}
        )
        
        # Then
        assert isinstance(chunk.relationships, list)
        assert len(chunk.relationships) == 3
        assert chunk.relationships == relationships
        assert chunk.relationships[0] == "chunk_0000"
        assert chunk.relationships[1] == "chunk_0002"
        assert chunk.relationships[2] == "chunk_0003"


class TestLLMChunkFieldValidation:
    """Test LLMChunk field validation and type checking."""

    def test_content_field_validation(self):
        """
        GIVEN various content field values (empty string, long text, None)
        WHEN LLMChunk is instantiated
        THEN expect:
            - Valid strings accepted
            - Invalid types rejected appropriately
            - Empty strings handled correctly
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        
        # Valid string content should work
        chunk = LLMChunk(
            content="Valid content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        assert chunk.content == "Valid content"
        
        # Empty string should work
        chunk_empty = LLMChunk(
            content="",
            chunk_id="chunk_0002",
            source_page=1,
            source_element="text",
            token_count=0,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        assert chunk_empty.content == ""
        
        # Very long content should work
        long_content = "A" * 10000
        chunk_long = LLMChunk(
            content=long_content,
            chunk_id="chunk_0003",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        assert chunk_long.content == long_content
        
        # None content should raise ValueError
        with pytest.raises(ValueError):
            chunk_none = LLMChunk(
                content=None,
                chunk_id="chunk_0004",
                source_page=1,
                source_element="text",
                token_count=5,
                semantic_type="text",
                relationships=[],
                metadata={}
                )

        # Non-string types should raise ValueError
        invalid_types = [123, [], {}, 45.67]
        for invalid_content in invalid_types:
            with pytest.raises(ValueError):
                chunk_invalid = LLMChunk(
                    content=invalid_content,
                    chunk_id="chunk_invalid",
                    source_page=1,
                    source_element="text",
                    token_count=5,
                    semantic_type="text",
                    relationships=[],
                    metadata={}
                )

    def test_chunk_id_field_validation(self):
        """
        GIVEN various chunk_id field values
        WHEN LLMChunk is instantiated
        THEN expect:
            - Valid string IDs accepted
            - Invalid types rejected
            - Empty strings handled appropriately
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        
        # Valid chunk IDs should work
        valid_ids = ["chunk_0001", "chunk_abc", "test_chunk", ""]
        
        for chunk_id in valid_ids:
            chunk = LLMChunk(
                content="Test content",
                chunk_id=chunk_id,
                source_page=1,
                source_element="text",
                token_count=5,
                semantic_type="text",
                relationships=[],
                metadata={}
            )
            assert chunk.chunk_id == chunk_id

    def test_source_page_field_validation(self):
        """
        GIVEN various source_page field values (positive int, negative, zero, float)
        WHEN LLMChunk is instantiated
        THEN expect:
            - Valid positive integers accepted
            - Invalid types and values rejected appropriately
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        
        # Valid positive integers should work
        valid_pages = [1, 5, 100, 999]
        
        for page_num in valid_pages:
            chunk = LLMChunk(
                content="Test content",
                chunk_id="chunk_0001",
                source_page=page_num,
                source_element="text",
                token_count=5,
                semantic_type="text",
                relationships=[],
                metadata={}
            )
            assert chunk.source_page == page_num
        
        # Zero should work (might be valid for some use cases)
        chunk_zero = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=0,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        assert chunk_zero.source_page == 0

    def test_token_count_field_validation(self):
        """
        GIVEN various token_count field values
        WHEN LLMChunk is instantiated
        THEN expect:
            - Valid non-negative integers accepted
            - Negative values and invalid types rejected
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        
        # Valid non-negative integers should work
        valid_counts = [0, 1, 10, 100, 2048]
        
        for token_count in valid_counts:
            chunk = LLMChunk(
                content="Test content",
                chunk_id="chunk_0001",
                source_page=1,
                source_element="text",
                token_count=token_count,
                semantic_type="text",
                relationships=[],
                metadata={}
            )
            assert chunk.token_count == token_count

    def test_semantic_type_field_validation(self):
        """
        GIVEN various semantic_type field values
        WHEN LLMChunk is instantiated
        THEN expect:
            - Valid semantic type strings accepted ('text', 'table', 'header', etc.)
            - Invalid types rejected
            - Case sensitivity handling
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        
        # Valid semantic types based on documentation
        valid_types = ['text', 'table', 'figure_caption', 'header', 'mixed']
        
        for semantic_type in valid_types:
            chunk = LLMChunk(
                content="Test content",
                chunk_id="chunk_0001",
                source_page=1,
                source_element="text",
                token_count=5,
                semantic_type=semantic_type,
                relationships=[],
                metadata={}
            )
            assert chunk.semantic_type == semantic_type
        
        # Custom types should also work (no strict validation in base dataclass)
        custom_chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="custom_type",
            relationships=[],
            metadata={}
        )
        assert custom_chunk.semantic_type == "custom_type"

    def test_relationships_field_validation(self):
        """
        GIVEN various relationships field values (list of strings, mixed types, None)
        WHEN LLMChunk is instantiated
        THEN expect:
            - Valid List[str] accepted
            - Invalid list contents rejected
            - Type checking for list elements
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        
        # Valid list of strings
        valid_relationships = [
            [],
            ["chunk_0000"],
            ["chunk_0000", "chunk_0002", "chunk_0003"],
            ["related_chunk", "another_chunk"]
        ]
        
        for relationships in valid_relationships:
            chunk = LLMChunk(
                content="Test content",
                chunk_id="chunk_0001",
                source_page=1,
                source_element="text",
                token_count=5,
                semantic_type="text",
                relationships=relationships,
                metadata={}
            )
            assert chunk.relationships == relationships
            assert isinstance(chunk.relationships, list)

    def test_metadata_field_validation(self):
        """
        GIVEN various metadata field values (dict, empty dict, invalid types)
        WHEN LLMChunk is instantiated
        THEN expect:
            - Valid Dict[str, Any] accepted
            - Invalid types rejected
            - Empty dictionaries handled correctly
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        
        # Valid dictionaries
        valid_metadata = [
            {},
            {"confidence": 0.9},
            {"confidence": 0.9, "source": "pdf", "page_info": {"x": 100, "y": 200}},
            {"complex_data": [1, 2, 3], "nested": {"key": "value"}}
        ]
        
        for metadata in valid_metadata:
            chunk = LLMChunk(
                content="Test content",
                chunk_id="chunk_0001",
                source_page=1,
                source_element="text",
                token_count=5,
                semantic_type="text",
                relationships=[],
                metadata=metadata
            )
            assert chunk.metadata == metadata
            assert isinstance(chunk.metadata, dict)

    def test_embedding_field_validation(self):
        """
        GIVEN various embedding field values (numpy arrays, lists, invalid types)
        WHEN LLMChunk is instantiated
        THEN expect:
            - Valid numpy arrays accepted
            - None values accepted (Optional type)
            - Invalid types rejected appropriately
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        import numpy as np
        
        # Valid numpy arrays
        valid_embeddings = [
            None,
            np.array([1.0, 2.0, 3.0]),
            np.array([[1.0, 2.0], [3.0, 4.0]]),  # 2D array
            np.array([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32),
            np.array([])  # Empty array
        ]
        
        for embedding in valid_embeddings:
            chunk = LLMChunk(
                content="Test content",
                chunk_id="chunk_0001",
                source_page=1,
                source_element="text",
                token_count=5,
                semantic_type="text",
                relationships=[],
                metadata={},
                embedding=embedding
            )
            if embedding is None:
                assert chunk.embedding is None
            else:
                assert isinstance(chunk.embedding, np.ndarray)
                assert np.array_equal(chunk.embedding, embedding)


class TestLLMChunkAttributeAccess:
    """Test LLMChunk attribute access and modification."""

    def setup_method(self):
        """Set up test fixtures with sample LLMChunk instance."""
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        import numpy as np
        
        self.sample_chunk = LLMChunk(
            content="Sample test content for testing",
            chunk_id="chunk_test_001",
            source_page=1,
            source_element="paragraph",
            token_count=10,
            semantic_type="text",
            relationships=["chunk_000", "chunk_002"],
            metadata={"confidence": 0.95, "source": "test"},
            embedding=np.array([0.1, 0.2, 0.3, 0.4])
        )

    def test_content_attribute_access(self):
        """
        GIVEN LLMChunk instance with content
        WHEN content attribute is accessed
        THEN expect correct content value returned
        """
        # When/Then
        assert self.sample_chunk.content == "Sample test content for testing"
        assert isinstance(self.sample_chunk.content, str)
        assert hasattr(self.sample_chunk, 'content')

    def test_chunk_id_attribute_access(self):
        """
        GIVEN LLMChunk instance with chunk_id
        WHEN chunk_id attribute is accessed
        THEN expect correct chunk_id value returned
        """
        # When/Then
        assert self.sample_chunk.chunk_id == "chunk_test_001"
        assert isinstance(self.sample_chunk.chunk_id, str)
        assert hasattr(self.sample_chunk, 'chunk_id')

    def test_embedding_attribute_access_none(self):
        """
        GIVEN LLMChunk instance with embedding=None
        WHEN embedding attribute is accessed
        THEN expect None returned
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        
        # Given
        chunk_none_embedding = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={},
            embedding=None
        )
        
        # When/Then
        assert chunk_none_embedding.embedding is None

    def test_embedding_attribute_access_array(self):
        """
        GIVEN LLMChunk instance with numpy array embedding
        WHEN embedding attribute is accessed
        THEN expect:
            - Numpy array returned
            - Array properties preserved (shape, dtype)
            - Array data integrity maintained
        """
        import numpy as np
        
        # When/Then
        assert isinstance(self.sample_chunk.embedding, np.ndarray)
        assert self.sample_chunk.embedding.shape == (4,)
        assert np.array_equal(self.sample_chunk.embedding, np.array([0.1, 0.2, 0.3, 0.4]))
        assert self.sample_chunk.embedding.dtype == np.float64  # Default numpy float type

    def test_relationships_attribute_modification(self):
        """
        GIVEN LLMChunk instance with relationships list
        WHEN relationships list is modified
        THEN expect:
            - Modifications reflected in instance
            - List mutability works as expected
        """
        # Given - initial state
        original_relationships = self.sample_chunk.relationships.copy()
        assert original_relationships == ["chunk_000", "chunk_002"]
        
        # When - modify the list
        self.sample_chunk.relationships.append("chunk_003")
        self.sample_chunk.relationships.remove("chunk_000")
        
        # Then - changes should be reflected
        assert len(self.sample_chunk.relationships) == 2
        assert "chunk_003" in self.sample_chunk.relationships
        assert "chunk_000" not in self.sample_chunk.relationships
        assert "chunk_002" in self.sample_chunk.relationships

    def test_metadata_attribute_modification(self):
        """
        GIVEN LLMChunk instance with metadata dict
        WHEN metadata dict is modified
        THEN expect:
            - Modifications reflected in instance
            - Dict mutability works as expected
        """
        # Given - initial state
        original_metadata = self.sample_chunk.metadata.copy()
        assert original_metadata == {"confidence": 0.95, "source": "test"}
        
        # When - modify the dict
        self.sample_chunk.metadata["new_key"] = "new_value"
        self.sample_chunk.metadata["confidence"] = 0.99
        del self.sample_chunk.metadata["source"]
        
        # Then - changes should be reflected
        assert len(self.sample_chunk.metadata) == 2
        assert self.sample_chunk.metadata["new_key"] == "new_value"
        assert self.sample_chunk.metadata["confidence"] == 0.99
        assert "source" not in self.sample_chunk.metadata


class TestLLMChunkDataclassMethods:
    """Test LLMChunk dataclass auto-generated methods."""

    def test_equality_comparison(self):
        """
        GIVEN two LLMChunk instances with identical field values
        WHEN compared for equality
        THEN expect instances to be equal
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        import numpy as np
        
        # Given - two identical chunks
        embedding = np.array([0.1, 0.2, 0.3])
        
        chunk1 = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=["chunk_000"],
            metadata={"confidence": 0.9},
            embedding=embedding.copy()
        )
        
        chunk2 = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=["chunk_000"],
            metadata={"confidence": 0.9},
            embedding=embedding.copy()
        )
        
        # When/Then - they should be equal
        assert chunk1 == chunk2

    def test_inequality_comparison(self):
        """
        GIVEN two LLMChunk instances with different field values
        WHEN compared for equality
        THEN expect instances to be unequal
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        import numpy as np
        
        # Given - two different chunks
        chunk1 = LLMChunk(
            content="Test content 1",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=["chunk_000"],
            metadata={"confidence": 0.9},
            embedding=np.array([0.1, 0.2, 0.3])
        )
        
        chunk2 = LLMChunk(
            content="Test content 2",  # Different content
            chunk_id="chunk_0002",     # Different ID
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=["chunk_000"],
            metadata={"confidence": 0.9},
            embedding=np.array([0.1, 0.2, 0.3])
        )
        
        # When/Then - they should not be equal
        assert chunk1 != chunk2

    def test_string_representation(self):
        """
        GIVEN LLMChunk instance
        WHEN converted to string representation
        THEN expect:
            - Readable string format
            - All field values included
            - No truncation of important data
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        import numpy as np
        
        # Given
        chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=["chunk_000"],
            metadata={"confidence": 0.9},
            embedding=np.array([0.1, 0.2])
        )
        
        # When
        str_repr = str(chunk)
        
        # Then
        assert isinstance(str_repr, str)
        assert len(str_repr) > 0
        assert "chunk_0001" in str_repr  # Should include chunk ID
        assert "Test content" in str_repr  # Should include content

    def test_repr_representation(self):
        """
        GIVEN LLMChunk instance
        WHEN repr() is called
        THEN expect:
            - Detailed representation suitable for debugging
            - All field values and types visible
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        import numpy as np
        
        # Given
        chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=["chunk_000"],
            metadata={"confidence": 0.9},
            embedding=np.array([0.1, 0.2])
        )
        
        # When
        repr_str = repr(chunk)
        
        # Then
        assert isinstance(repr_str, str)
        assert len(repr_str) > 0
        assert "LLMChunk" in repr_str  # Should include class name
        assert "chunk_0001" in repr_str  # Should include chunk ID

    def test_hash_method_if_frozen(self):
        """
        GIVEN LLMChunk dataclass (if frozen=True)
        WHEN hash() is called
        THEN expect consistent hash values for equal instances
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        from dataclasses import is_dataclass
        import numpy as np
        
        # Given - check if dataclass is frozen
        chunk1 = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=["chunk_000"],
            metadata={"confidence": 0.9},
            embedding=np.array([0.1, 0.2])
        )
        
        chunk2 = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=["chunk_000"],
            metadata={"confidence": 0.9},
            embedding=np.array([0.1, 0.2])
        )
        
        # When/Then - equal instances should have same hash
        assert hash(chunk1) == hash(chunk2)



class TestLLMChunkSemanticTypeClassification:
    """Test LLMChunk semantic type classification and validation."""

    def test_valid_semantic_types(self):
        """
        GIVEN valid semantic type values ('text', 'table', 'figure_caption', 'header', 'mixed')
        WHEN LLMChunk is instantiated with these types
        THEN expect all valid types accepted without error
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        
        # Given - valid semantic types from the documentation
        valid_types = ['text', 'table', 'figure_caption', 'header', 'mixed']
        
        # When/Then - all should be accepted
        for semantic_type in valid_types:
            chunk = LLMChunk(
                content="Test content",
                chunk_id=f"chunk_{semantic_type}",
                source_page=1,
                source_element="test",
                token_count=5,
                semantic_type=semantic_type,
                relationships=[],
                metadata={}
            )
            assert chunk.semantic_type == semantic_type

    def test_invalid_semantic_types(self):
        """
        GIVEN invalid semantic type values
        WHEN LLMChunk is instantiated
        THEN expect:
            - Invalid types handled appropriately
            - Validation or warning mechanisms if implemented
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        
        # Given - since dataclass doesn't enforce validation by default,
        # these should still work but may be flagged by type checkers
        potentially_invalid_types = ['invalid_type', 'HEADER', 'Text', 123, None]
        
        # When/Then - dataclass accepts these but they may not be semantically valid
        for semantic_type in potentially_invalid_types:
            # Should not raise an error during instantiation
            chunk = LLMChunk(
                content="Test content",
                chunk_id="chunk_0001",
                source_page=1,
                source_element="test",
                token_count=5,
                semantic_type=semantic_type,
                relationships=[],
                metadata={}
            )
            assert chunk.semantic_type == semantic_type

    def test_semantic_type_case_sensitivity(self):
        """
        GIVEN semantic type values with different casing
        WHEN LLMChunk is instantiated
        THEN expect consistent handling of case variations
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        
        # Given - different case variations
        case_variations = [
            ('text', 'TEXT', 'Text', 'tEXt'),
            ('header', 'HEADER', 'Header', 'hEAder'),
            ('table', 'TABLE', 'Table', 'tABle')
        ]
        
        # When/Then - all variations should be accepted as-is (no normalization)
        for variations in case_variations:
            for variant in variations:
                chunk = LLMChunk(
                    content="Test content",
                    chunk_id=f"chunk_{variant}",
                    source_page=1,
                    source_element="test",
                    token_count=5,
                    semantic_type=variant,
                    relationships=[],
                    metadata={}
                )
                assert chunk.semantic_type == variant  # Exact match, no case normalization


class TestLLMChunkEmbeddingHandling:
    """Test LLMChunk embedding field handling and numpy array operations."""

    def test_embedding_shape_preservation(self):
        """
        GIVEN numpy array with specific shape as embedding
        WHEN LLMChunk is instantiated and accessed
        THEN expect original array shape preserved
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        
        # Given - arrays with different shapes
        test_arrays = [
            np.array([1.0, 2.0, 3.0]),                    # 1D array
            np.array([[1.0, 2.0], [3.0, 4.0]]),           # 2D array
            np.array([[[1.0, 2.0]], [[3.0, 4.0]]]),       # 3D array
            np.array([]),                                  # Empty array
            np.array([5.0])                                # Single element
        ]
        
        # When/Then - shape should be preserved for each array
        for original_array in test_arrays:
            chunk = LLMChunk(
                content="Test content",
                chunk_id="chunk_0001",
                source_page=1,
                source_element="text",
                token_count=5,
                semantic_type="text",
                relationships=[],
                metadata={},
                embedding=original_array
            )
            
            assert chunk.embedding.shape == original_array.shape
            assert chunk.embedding.ndim == original_array.ndim
            assert chunk.embedding.size == original_array.size

    def test_embedding_dtype_preservation(self):
        """
        GIVEN numpy arrays with different dtypes as embedding
        WHEN LLMChunk is instantiated and accessed
        THEN expect original dtype preserved
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        
        # Given - arrays with different dtypes
        test_arrays = [
            np.array([1.0, 2.0, 3.0], dtype=np.float32),
            np.array([1.0, 2.0, 3.0], dtype=np.float64),
            np.array([1, 2, 3], dtype=np.int32),
            np.array([1, 2, 3], dtype=np.int64),
            np.array([True, False, True], dtype=np.bool_)
        ]
        
        # When/Then - dtype should be preserved for each array
        for original_array in test_arrays:
            chunk = LLMChunk(
                content="Test content",
                chunk_id="chunk_0001",
                source_page=1,
                source_element="text",
                token_count=5,
                semantic_type="text",
                relationships=[],
                metadata={},
                embedding=original_array
            )
            
            assert chunk.embedding.dtype == original_array.dtype
            assert np.array_equal(chunk.embedding, original_array)

    def test_embedding_data_integrity(self):
        """
        GIVEN numpy array with specific values as embedding
        WHEN LLMChunk is instantiated and accessed
        THEN expect original array values unchanged
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        
        # Given - array with specific values
        original_values = [0.123456789, -0.987654321, 1e-10, 1e10, 0.0, -0.0]
        original_array = np.array(original_values, dtype=np.float64)
        
        # When
        chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={},
            embedding=original_array
        )
        
        # Then - values should be exactly preserved
        assert np.array_equal(chunk.embedding, original_array)
        assert np.allclose(chunk.embedding, original_values, rtol=1e-15, atol=1e-15)
        
        # Test edge cases - special float values
        special_values = [np.inf, -np.inf, 0.0, -0.0]
        special_array = np.array(special_values)
        
        chunk_special = LLMChunk(
            content="Test content",
            chunk_id="chunk_0002",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={},
            embedding=special_array
        )
        
        assert np.array_equal(chunk_special.embedding, special_array, equal_nan=True)
        assert np.isinf(chunk_special.embedding[0]) and chunk_special.embedding[0] > 0
        assert np.isinf(chunk_special.embedding[1]) and chunk_special.embedding[1] < 0

    def test_embedding_memory_sharing(self):
        """
        GIVEN numpy array as embedding
        WHEN LLMChunk is instantiated
        THEN expect:
            - Memory sharing behavior documented
            - No unexpected array copying
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk
        
        # Given - original array
        original_array = np.array([1.0, 2.0, 3.0, 4.0])
        
        # When
        chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={},
            embedding=original_array
        )
        
        # Then - check if arrays share memory (implementation dependent)
        # Note: dataclass field assignment may or may not copy the array
        arrays_share_memory = np.shares_memory(chunk.embedding, original_array)
        
        # Verify that changes to original array affect chunk embedding (if sharing memory)
        original_first_value = original_array[0]
        original_array[0] = 999.0
        
        if arrays_share_memory:
            # If memory is shared, chunk embedding should reflect the change
            assert chunk.embedding[0] == 999.0
        else:
            # If memory is not shared, chunk embedding should be unchanged
            assert chunk.embedding[0] == original_first_value
        
        # Restore original value for clean test state
        original_array[0] = original_first_value
        
        # Test with view of array
        array_view = original_array[1:3]
        chunk_view = LLMChunk(
            content="Test content",
            chunk_id="chunk_0002",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={},
            embedding=array_view
        )
        
        # Verify the view is preserved
        assert chunk_view.embedding.shape == (2,)
        assert np.array_equal(chunk_view.embedding, [2.0, 3.0])



class TestLLMDocumentDataclassStructure:
    """Test LLMDocument dataclass structure and field definitions."""

    def test_is_dataclass(self):
        """
        GIVEN LLMDocument class
        WHEN checked for dataclass decorator
        THEN expect LLMDocument to be properly decorated as a dataclass
        """
        from dataclasses import is_dataclass
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument
        
        # When/Then
        assert is_dataclass(LLMDocument)
        assert hasattr(LLMDocument, '__dataclass_fields__')

    def test_required_fields_present(self):
        """
        GIVEN LLMDocument dataclass
        WHEN inspecting field definitions
        THEN expect all required fields to be present:
            - document_id (str)
            - title (str)
            - chunks (List[LLMChunk])
            - summary (str)
            - key_entities (List[Dict[str, Any]])
            - processing_metadata (Dict[str, Any])
            - document_embedding (Optional[np.ndarray])
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument
        
        # When
        fields = LLMDocument.__dataclass_fields__
        field_names = set(fields.keys())
        
        # Then
        expected_fields = {
            'document_id', 'title', 'chunks', 'summary',
            'key_entities', 'processing_metadata', 'document_embedding'
        }
        assert expected_fields.issubset(field_names)
        assert len(field_names) >= len(expected_fields)  # May have additional fields

    def test_field_types_correct(self):
        """
        GIVEN LLMDocument dataclass fields
        WHEN inspecting field type annotations
        THEN expect:
            - document_id: str type annotation
            - title: str type annotation
            - chunks: List[LLMChunk] type annotation
            - summary: str type annotation
            - key_entities: List[Dict[str, Any]] type annotation
            - processing_metadata: Dict[str, Any] type annotation
            - document_embedding: Optional[np.ndarray] type annotation
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument
        
        # When
        fields = LLMDocument.__dataclass_fields__
        
        # Then - check core types (complex generic types may need different handling)
        assert fields['document_id'].type == str
        assert fields['title'].type == str
        assert fields['summary'].type == str
        # Note: For complex types like List[LLMChunk], we check that annotation exists
        assert hasattr(fields['chunks'], 'type')
        assert hasattr(fields['key_entities'], 'type')
        assert hasattr(fields['processing_metadata'], 'type')
        assert hasattr(fields['document_embedding'], 'type')

    def test_field_defaults(self):
        """
        GIVEN LLMDocument dataclass fields
        WHEN inspecting default values
        THEN expect appropriate default values where specified in documentation
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument
        from dataclasses import MISSING
        
        # When
        fields = LLMDocument.__dataclass_fields__
        
        # Then - check which fields have defaults
        # Most fields should not have defaults (required)
        required_fields = ['document_id', 'title', 'chunks', 'summary', 
                          'key_entities', 'processing_metadata']
        for field_name in required_fields:
            assert fields[field_name].default is MISSING
        
        # document_embedding should have default None
        assert fields['document_embedding'].default is None


class TestLLMDocumentInstantiation:
    """Test LLMDocument instantiation with various parameter combinations."""

    def test_instantiation_with_all_fields(self):
        """
        GIVEN all required LLMDocument fields with valid values
        WHEN LLMDocument is instantiated
        THEN expect:
            - Instance created successfully
            - All fields accessible with correct values
            - No errors or exceptions raised
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given
        sample_chunk = LLMChunk(
            content="Sample chunk content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="paragraph",
            token_count=10,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        document_embedding = np.array([0.1, 0.2, 0.3, 0.4, 0.5])
        
        # When
        document = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[sample_chunk],
            summary="This is a test document summary",
            key_entities=[{"type": "PERSON", "value": "John Doe", "confidence": 0.95}],
            processing_metadata={"processing_time": 1.23, "model": "test_model"},
            document_embedding=document_embedding
        )
        
        # Then
        assert document.document_id == "doc_001"
        assert document.title == "Test Document"
        assert len(document.chunks) == 1
        assert document.chunks[0] == sample_chunk
        assert document.summary == "This is a test document summary"
        assert len(document.key_entities) == 1
        assert document.key_entities[0]["type"] == "PERSON"
        assert document.processing_metadata["processing_time"] == 1.23
        assert np.array_equal(document.document_embedding, document_embedding)

    def test_instantiation_with_minimal_fields(self):
        """
        GIVEN only required LLMDocument fields (no defaults)
        WHEN LLMDocument is instantiated
        THEN expect:
            - Instance created successfully if all required fields provided
            - Default values applied where appropriate
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given
        sample_chunk = LLMChunk(
            content="Minimal chunk content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        # When - using minimal required fields
        document = LLMDocument(
            document_id="doc_001",
            title="Minimal Document",
            chunks=[sample_chunk],
            summary="Minimal summary",
            key_entities=[],
            processing_metadata={}
        )
        
        # Then
        assert document.document_id == "doc_001"
        assert document.title == "Minimal Document"
        assert len(document.chunks) == 1
        assert document.summary == "Minimal summary"
        assert document.key_entities == []
        assert document.processing_metadata == {}
        assert document.document_embedding is None  # Default value

    def test_instantiation_missing_required_fields(self):
        """
        GIVEN missing required fields during instantiation
        WHEN LLMDocument is instantiated
        THEN expect ValueError to be raised for missing required parameters
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # When/Then - missing document_id
        with pytest.raises(ValueError):
            LLMDocument(
                title="Test Document",
                chunks=[],
                summary="Test summary",
                key_entities=[],
                processing_metadata={}
            )
        
        # When/Then - missing multiple fields
        with pytest.raises(ValueError):
            LLMDocument(document_id="doc_001")
        
        # When/Then - missing chunks field
        with pytest.raises(ValueError):
            LLMDocument(
                document_id="doc_001",
                title="Test Document",
                summary="Test summary",
                key_entities=[],
                processing_metadata={}
            )

    def test_instantiation_with_none_document_embedding(self):
        """
        GIVEN document_embedding field set to None
        WHEN LLMDocument is instantiated
        THEN expect:
            - Instance created successfully
            - document_embedding field properly set to None
            - Optional type handling works correctly
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given
        sample_chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        # When
        document = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[sample_chunk],
            summary="Test summary",
            key_entities=[],
            processing_metadata={},
            document_embedding=None
        )
        
        # Then
        assert document.document_embedding is None

    def test_instantiation_with_numpy_document_embedding(self):
        """
        GIVEN document_embedding field set to numpy array
        WHEN LLMDocument is instantiated
        THEN expect:
            - Instance created successfully
            - document_embedding field contains numpy array
            - Array shape and dtype preserved
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given
        sample_chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        document_embedding = np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float32)
        
        # When
        document = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[sample_chunk],
            summary="Test summary",
            key_entities=[],
            processing_metadata={},
            document_embedding=document_embedding
        )
        
        # Then
        assert isinstance(document.document_embedding, np.ndarray)
        assert np.array_equal(document.document_embedding, document_embedding)
        assert document.document_embedding.shape == (5,)
        assert document.document_embedding.dtype == np.float32

    def test_instantiation_with_empty_chunks_list(self):
        """
        GIVEN chunks field as empty list
        WHEN LLMDocument is instantiated
        THEN expect:
            - Instance created successfully
            - chunks field is empty list
            - List type maintained
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument
        
        # When
        document = LLMDocument(
            document_id="doc_001",
            title="Empty Document",
            chunks=[],
            summary="Document with no chunks",
            key_entities=[],
            processing_metadata={}
        )
        
        # Then
        assert isinstance(document.chunks, list)
        assert len(document.chunks) == 0
        assert document.chunks == []

    def test_instantiation_with_populated_chunks(self):
        """
        GIVEN chunks field with list of LLMChunk instances
        WHEN LLMDocument is instantiated
        THEN expect:
            - Instance created successfully
            - chunks field contains provided LLMChunk instances
            - List order preserved
            - All chunk instances accessible
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given
        chunks = [
            LLMChunk(
                content="First chunk content",
                chunk_id="chunk_0001",
                source_page=1,
                source_element="paragraph",
                token_count=10,
                semantic_type="text",
                relationships=[],
                metadata={}
            ),
            LLMChunk(
                content="Second chunk content",
                chunk_id="chunk_0002",
                source_page=1,
                source_element="paragraph",
                token_count=12,
                semantic_type="text",
                relationships=["chunk_0001"],
                metadata={}
            ),
            LLMChunk(
                content="Third chunk content",
                chunk_id="chunk_0003",
                source_page=2,
                source_element="table",
                token_count=8,
                semantic_type="table",
                relationships=["chunk_0002"],
                metadata={}
            )
        ]
        
        # When
        document = LLMDocument(
            document_id="doc_001",
            title="Multi-chunk Document",
            chunks=chunks,
            summary="Document with multiple chunks",
            key_entities=[],
            processing_metadata={}
        )
        
        # Then
        assert isinstance(document.chunks, list)
        assert len(document.chunks) == 3
        assert document.chunks == chunks
        assert document.chunks[0].chunk_id == "chunk_0001"
        assert document.chunks[1].chunk_id == "chunk_0002"
        assert document.chunks[2].chunk_id == "chunk_0003"
        
        # Verify all chunks are accessible and correct type
        for i, chunk in enumerate(document.chunks):
            assert isinstance(chunk, LLMChunk)
            assert chunk == chunks[i]

    def test_instantiation_with_empty_key_entities(self):
        """
        GIVEN key_entities field as empty list
        WHEN LLMDocument is instantiated
        THEN expect:
            - Instance created successfully
            - key_entities field is empty list
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given
        sample_chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        # When
        document = LLMDocument(
            document_id="doc_001",
            title="No Entities Document",
            chunks=[sample_chunk],
            summary="Document with no entities",
            key_entities=[],
            processing_metadata={}
        )
        
        # Then
        assert isinstance(document.key_entities, list)
        assert len(document.key_entities) == 0
        assert document.key_entities == []

    def test_instantiation_with_populated_key_entities(self):
        """
        GIVEN key_entities field with list of entity dictionaries
        WHEN LLMDocument is instantiated
        THEN expect:
            - Instance created successfully
            - key_entities field contains provided entity data
            - Entity structure preserved
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given
        sample_chunk = LLMChunk(
            content="John Doe works at OpenAI in San Francisco",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=10,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        key_entities = [
            {"type": "PERSON", "value": "John Doe", "confidence": 0.95, "start": 0, "end": 8},
            {"type": "ORG", "value": "OpenAI", "confidence": 0.92, "start": 18, "end": 24},
            {"type": "GPE", "value": "San Francisco", "confidence": 0.88, "start": 28, "end": 41}
        ]
        
        # When
        document = LLMDocument(
            document_id="doc_001",
            title="Entity Rich Document",
            chunks=[sample_chunk],
            summary="Document with multiple entities",
            key_entities=key_entities,
            processing_metadata={}
        )
        
        # Then
        assert isinstance(document.key_entities, list)
        assert len(document.key_entities) == 3
        assert document.key_entities == key_entities
        
        # Verify entity structure
        assert document.key_entities[0]["type"] == "PERSON"
        assert document.key_entities[0]["value"] == "John Doe"
        assert document.key_entities[1]["type"] == "ORG"
        assert document.key_entities[1]["value"] == "OpenAI"
        assert document.key_entities[2]["type"] == "GPE"
        assert document.key_entities[2]["value"] == "San Francisco"
        
        # Verify all entities have expected keys
        for entity in document.key_entities:
            assert isinstance(entity, dict)
            assert "type" in entity
            assert "value" in entity
            assert "confidence" in entity


class TestLLMDocumentFieldValidation:
    """Test LLMDocument field validation and type checking."""

    def test_document_id_field_validation(self):
        """
        GIVEN various document_id field values (valid strings, empty, None)
        WHEN LLMDocument is instantiated
        THEN expect:
            - Valid string IDs accepted
            - Invalid types rejected appropriately
            - Empty strings handled correctly
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given - sample chunk for testing
        sample_chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        # Valid document IDs should work
        valid_ids = ["doc_001", "document_abc", "test_doc_123", ""]
        
        for doc_id in valid_ids:
            document = LLMDocument(
                document_id=doc_id,
                title="Test Document",
                chunks=[sample_chunk],
                summary="Test summary",
                key_entities=[],
                processing_metadata={}
            )
            assert document.document_id == doc_id
        
        # Invalid types should be handled based on implementation
        invalid_types = [123, [], {}, None]
        for invalid_id in invalid_types:
            with pytest.raises(ValueError):
                document = LLMDocument(
                    document_id=invalid_id,
                    title="Test Document",
                    chunks=[sample_chunk],
                    summary="Test summary",
                    key_entities=[],
                    processing_metadata={}
                )

    def test_title_field_validation(self):
        """
        GIVEN various title field values
        WHEN LLMDocument is instantiated
        THEN expect:
            - Valid strings accepted
            - Invalid types rejected
            - Empty titles handled appropriately
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given - sample chunk for testing
        sample_chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        # Valid titles should work
        valid_titles = ["Document Title", "Multi-word Document Title", "Title with Numbers 123", ""]
        
        for title in valid_titles:
            document = LLMDocument(
                document_id="doc_001",
                title=title,
                chunks=[sample_chunk],
                summary="Test summary",
                key_entities=[],
                processing_metadata={}
            )
            assert document.title == title
        
        # Invalid types should raise ValueError with runtime validation
        invalid_types = [123, [], {}, None]
        for invalid_title in invalid_types:
            with pytest.raises(ValueError):
                LLMDocument(
                    document_id="doc_001",
                    title=invalid_title,
                    chunks=[sample_chunk],
                    summary="Test summary",
                    key_entities=[],
                    processing_metadata={}
                )

    def test_chunks_field_validation(self):
        """
        GIVEN various chunks field values (List[LLMChunk], mixed types, None)
        WHEN LLMDocument is instantiated
        THEN expect:
            - Valid List[LLMChunk] accepted
            - Invalid list contents rejected
            - Type checking for list elements
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Valid chunks list should work
        valid_chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        valid_chunks_lists = [
            [valid_chunk],
            [valid_chunk, valid_chunk],
            []  # Empty list should be valid
        ]
        
        for chunks_list in valid_chunks_lists:
            document = LLMDocument(
                document_id="doc_001",
                title="Test Document",
                chunks=chunks_list,
                summary="Test summary",
                key_entities=[],
                processing_metadata={}
            )
            assert document.chunks == chunks_list
        
        # Invalid types should raise ValueError with runtime validation
        invalid_chunks = [None, "not a list", 123, {}]
        for invalid_chunk_list in invalid_chunks:
            with pytest.raises(ValueError):
                LLMDocument(
                    document_id="doc_001",
                    title="Test Document",
                    chunks=invalid_chunk_list,
                    summary="Test summary",
                    key_entities=[],
                    processing_metadata={}
                )
        
        # List with invalid chunk types should raise ValueError
        invalid_chunk_contents = [
            ["not a chunk"],
            [123],
            [{}],
            [valid_chunk, "invalid"]
        ]
        
        for invalid_contents in invalid_chunk_contents:
            with pytest.raises(ValueError):
                LLMDocument(
                    document_id="doc_001",
                    title="Test Document",
                    chunks=invalid_contents,
                    summary="Test summary",
                    key_entities=[],
                    processing_metadata={}
                )

    def test_summary_field_validation(self):
        """
        GIVEN various summary field values
        WHEN LLMDocument is instantiated
        THEN expect:
            - Valid strings accepted
            - Invalid types rejected
            - Empty summaries handled appropriately
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given - sample chunk for testing
        sample_chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        # Valid summaries should work
        valid_summaries = [
            "This is a comprehensive document summary",
            "Short summary",
            "Summary with numbers 123 and symbols @#$",
            "",  # Empty string should be valid
            "A" * 1000  # Very long summary should be valid
        ]
        
        for summary in valid_summaries:
            document = LLMDocument(
                document_id="doc_001",
                title="Test Document",
                chunks=[sample_chunk],
                summary=summary,
                key_entities=[],
                processing_metadata={}
            )
            assert document.summary == summary
        
        # Invalid types should raise ValueError with runtime validation
        invalid_summaries = [123, [], {}, None]
        for invalid_summary in invalid_summaries:
            with pytest.raises(ValueError):
                LLMDocument(
                    document_id="doc_001",
                    title="Test Document",
                    chunks=[sample_chunk],
                    summary=invalid_summary,
                    key_entities=[],
                    processing_metadata={}
                )

    def test_key_entities_field_validation(self):
        """
        GIVEN various key_entities field values (list of dicts, invalid structures)
        WHEN LLMDocument is instantiated
        THEN expect:
            - Valid List[Dict[str, Any]] accepted
            - Invalid structures rejected
            - Entity dictionary format validation
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given - sample chunk for testing
        sample_chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        # Valid key_entities should work
        valid_entities_lists = [
            [],  # Empty list
            [{"type": "PERSON", "value": "John Doe", "confidence": 0.95}],
            [
                {"type": "PERSON", "value": "John Doe", "confidence": 0.95},
                {"type": "ORG", "value": "OpenAI", "confidence": 0.92},
                {"type": "GPE", "value": "San Francisco", "confidence": 0.88}
            ],
            [{"type": "DATE", "value": "2024-01-01", "confidence": 0.99, "extra_field": "allowed"}]
        ]
        
        for entities_list in valid_entities_lists:
            document = LLMDocument(
                document_id="doc_001",
                title="Test Document",
                chunks=[sample_chunk],
                summary="Test summary",
                key_entities=entities_list,
                processing_metadata={}
            )
            assert document.key_entities == entities_list
        
        # Invalid types should raise ValueError with runtime validation
        invalid_entities = [None, "not a list", 123, {}]
        for invalid_entity_list in invalid_entities:
            with pytest.raises(ValueError):
                LLMDocument(
                    document_id="doc_001",
                    title="Test Document",
                    chunks=[sample_chunk],
                    summary="Test summary",
                    key_entities=invalid_entity_list,
                    processing_metadata={}
                )
        
        # List with invalid entity types should raise ValueError
        invalid_entity_contents = [
            ["not a dict"],
            [123],
            ["string", "another string"],
            [{"type": "PERSON"}, "invalid"]  # Mixed valid and invalid
        ]
        
        for invalid_contents in invalid_entity_contents:
            with pytest.raises(ValueError):
                LLMDocument(
                    document_id="doc_001",
                    title="Test Document",
                    chunks=[sample_chunk],
                    summary="Test summary",
                    key_entities=invalid_contents,
                    processing_metadata={}
                )

    def test_processing_metadata_field_validation(self):
        """
        GIVEN various processing_metadata field values
        WHEN LLMDocument is instantiated
        THEN expect:
            - Valid Dict[str, Any] accepted
            - Invalid types rejected
            - Empty dictionaries handled correctly
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given - sample chunk for testing
        sample_chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        # Valid processing_metadata should work
        valid_metadata = [
            {},  # Empty dict
            {"processing_time": 1.23},
            {"model": "test_model", "version": "1.0", "timestamp": "2024-01-01"},
            {
                "processing_time": 1.23,
                "model": "test_model",
                "chunk_count": 5,
                "token_total": 150,
                "entities_found": 3,
                "confidence_avg": 0.89,
                "nested_data": {"sub_key": "sub_value"}
            }
        ]
        
        for metadata in valid_metadata:
            document = LLMDocument(
                document_id="doc_001",
                title="Test Document",
                chunks=[sample_chunk],
                summary="Test summary",
                key_entities=[],
                processing_metadata=metadata
            )
            assert document.processing_metadata == metadata
        
        # Invalid types should raise ValueError with runtime validation
        invalid_metadata = [None, "not a dict", 123, []]
        for invalid_meta in invalid_metadata:
            with pytest.raises(ValueError):
                LLMDocument(
                    document_id="doc_001",
                    title="Test Document",
                    chunks=[sample_chunk],
                    summary="Test summary",
                    key_entities=[],
                    processing_metadata=invalid_meta
                )

    def test_document_embedding_field_validation(self):
        """
        GIVEN various document_embedding field values
        WHEN LLMDocument is instantiated
        THEN expect:
            - Valid numpy arrays accepted
            - None values accepted (Optional type)
            - Invalid types rejected appropriately
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given - sample chunk for testing
        sample_chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        # Valid document embeddings should work
        valid_embeddings = [
            None,  # Optional type allows None
            np.array([1.0, 2.0, 3.0]),
            np.array([[1.0, 2.0], [3.0, 4.0]]),  # 2D array
            np.array([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32),
            np.array([]),  # Empty array
            np.array([5.0])  # Single element
        ]
        
        for embedding in valid_embeddings:
            document = LLMDocument(
                document_id="doc_001",
                title="Test Document",
                chunks=[sample_chunk],
                summary="Test summary",
                key_entities=[],
                processing_metadata={},
                document_embedding=embedding
            )
            if embedding is None:
                assert document.document_embedding is None
            else:
                assert isinstance(document.document_embedding, np.ndarray)
                assert np.array_equal(document.document_embedding, embedding)
        
        # Invalid types should raise ValueError with runtime validation
        invalid_embeddings = ["not an array", 123, [], {}]
        for invalid_embedding in invalid_embeddings:
            with pytest.raises(ValueError):
                LLMDocument(
                    document_id="doc_001",
                    title="Test Document",
                    chunks=[sample_chunk],
                    summary="Test summary",
                    key_entities=[],
                    processing_metadata={},
                    document_embedding=invalid_embedding
                )


class TestLLMDocumentAttributeAccess:
    """Test LLMDocument attribute access and modification."""

    def test_document_id_attribute_access(self):
        """
        GIVEN LLMDocument instance with document_id
        WHEN document_id attribute is accessed
        THEN expect correct document_id value returned
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given
        sample_chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        document = LLMDocument(
            document_id="doc_test_123",
            title="Test Document",
            chunks=[sample_chunk],
            summary="Test summary",
            key_entities=[],
            processing_metadata={}
        )
        
        # When/Then
        assert document.document_id == "doc_test_123"
        assert isinstance(document.document_id, str)
        assert hasattr(document, 'document_id')

    def test_title_attribute_access(self):
        """
        GIVEN LLMDocument instance with title
        WHEN title attribute is accessed
        THEN expect correct title value returned
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given
        sample_chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        document = LLMDocument(
            document_id="doc_001",
            title="Advanced Document Processing Analysis",
            chunks=[sample_chunk],
            summary="Test summary",
            key_entities=[],
            processing_metadata={}
        )
        
        # When/Then
        assert document.title == "Advanced Document Processing Analysis"
        assert isinstance(document.title, str)
        assert hasattr(document, 'title')

    def test_chunks_attribute_access(self):
        """
        GIVEN LLMDocument instance with chunks list
        WHEN chunks attribute is accessed
        THEN expect:
            - List of LLMChunk instances returned
            - All chunks accessible and valid
            - List order preserved
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given
        chunks = [
            LLMChunk(
                content="First chunk content",
                chunk_id="chunk_0001",
                source_page=1,
                source_element="paragraph",
                token_count=10,
                semantic_type="text",
                relationships=[],
                metadata={}
            ),
            LLMChunk(
                content="Second chunk content",
                chunk_id="chunk_0002",
                source_page=1,
                source_element="paragraph",
                token_count=12,
                semantic_type="text",
                relationships=["chunk_0001"],
                metadata={}
            )
        ]
        
        document = LLMDocument(
            document_id="doc_001",
            title="Multi-chunk Document",
            chunks=chunks,
            summary="Document with multiple chunks",
            key_entities=[],
            processing_metadata={}
        )
        
        # When/Then
        assert isinstance(document.chunks, list)
        assert len(document.chunks) == 2
        assert all(isinstance(chunk, LLMChunk) for chunk in document.chunks)
        assert document.chunks[0].chunk_id == "chunk_0001"
        assert document.chunks[1].chunk_id == "chunk_0002"
        assert document.chunks == chunks  # Order preserved
        assert hasattr(document, 'chunks')

    def test_summary_attribute_access(self):
        """
        GIVEN LLMDocument instance with summary
        WHEN summary attribute is accessed
        THEN expect correct summary string returned
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given
        sample_chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        summary_text = "This document analyzes advanced machine learning techniques for document processing and optimization."
        
        document = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[sample_chunk],
            summary=summary_text,
            key_entities=[],
            processing_metadata={}
        )
        
        # When/Then
        assert document.summary == summary_text
        assert isinstance(document.summary, str)
        assert len(document.summary) > 0
        assert hasattr(document, 'summary')

    def test_key_entities_attribute_access(self):
        """
        GIVEN LLMDocument instance with key_entities
        WHEN key_entities attribute is accessed
        THEN expect:
            - List of entity dictionaries returned
            - Entity structure preserved
            - All entities accessible
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given
        sample_chunk = LLMChunk(
            content="John Doe works at OpenAI in San Francisco",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=10,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        key_entities = [
            {"type": "PERSON", "value": "John Doe", "confidence": 0.95},
            {"type": "ORG", "value": "OpenAI", "confidence": 0.92},
            {"type": "GPE", "value": "San Francisco", "confidence": 0.88}
        ]
        
        document = LLMDocument(
            document_id="doc_001",
            title="Entity Rich Document",
            chunks=[sample_chunk],
            summary="Document with multiple entities",
            key_entities=key_entities,
            processing_metadata={}
        )
        
        # When/Then
        assert isinstance(document.key_entities, list)
        assert len(document.key_entities) == 3
        assert all(isinstance(entity, dict) for entity in document.key_entities)
        assert document.key_entities == key_entities
        
        # Verify specific entity access
        assert document.key_entities[0]["type"] == "PERSON"
        assert document.key_entities[0]["value"] == "John Doe"
        assert document.key_entities[1]["type"] == "ORG"
        assert document.key_entities[2]["type"] == "GPE"
        assert hasattr(document, 'key_entities')

    def test_processing_metadata_attribute_access(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN processing_metadata attribute is accessed
        THEN expect:
            - Dictionary returned with metadata
            - All metadata keys and values accessible
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given
        sample_chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        processing_metadata = {
            "processing_time": 2.45,
            "model": "advanced_optimizer_v2",
            "version": "1.2.3",
            "chunk_count": 5,
            "token_total": 150,
            "entities_found": 3,
            "confidence_avg": 0.89,
            "timestamp": "2024-01-01T12:00:00Z"
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[sample_chunk],
            summary="Test summary",
            key_entities=[],
            processing_metadata=processing_metadata
        )
        
        # When/Then
        assert isinstance(document.processing_metadata, dict)
        assert document.processing_metadata == processing_metadata
        assert len(document.processing_metadata) == 8
        
        # Verify specific metadata access
        assert document.processing_metadata["processing_time"] == 2.45
        assert document.processing_metadata["model"] == "advanced_optimizer_v2"
        assert document.processing_metadata["chunk_count"] == 5
        assert "timestamp" in document.processing_metadata
        assert hasattr(document, 'processing_metadata')

    def test_document_embedding_attribute_access_none(self):
        """
        GIVEN LLMDocument instance with document_embedding=None
        WHEN document_embedding attribute is accessed
        THEN expect None returned
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given
        sample_chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        document = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[sample_chunk],
            summary="Test summary",
            key_entities=[],
            processing_metadata={},
            document_embedding=None
        )
        
        # When/Then
        assert document.document_embedding is None
        assert hasattr(document, 'document_embedding')

    def test_document_embedding_attribute_access_array(self):
        """
        GIVEN LLMDocument instance with numpy array document_embedding
        WHEN document_embedding attribute is accessed
        THEN expect:
            - Numpy array returned
            - Array properties preserved (shape, dtype)
            - Array data integrity maintained
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given
        sample_chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        document_embedding = np.array([0.15, 0.25, 0.35, 0.45, 0.55], dtype=np.float32)
        
        document = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[sample_chunk],
            summary="Test summary",
            key_entities=[],
            processing_metadata={},
            document_embedding=document_embedding
        )
        
        # When/Then
        assert isinstance(document.document_embedding, np.ndarray)
        assert document.document_embedding.shape == (5,)
        assert document.document_embedding.dtype == np.float32
        assert np.array_equal(document.document_embedding, document_embedding)
        assert np.allclose(document.document_embedding, [0.15, 0.25, 0.35, 0.45, 0.55])
        assert hasattr(document, 'document_embedding')


class TestLLMDocumentChunkManagement:
    """Test LLMDocument chunk collection management and operations."""

    def test_chunks_list_modification(self):
        """
        GIVEN LLMDocument instance with chunks list
        WHEN chunks list is modified (append, remove, etc.)
        THEN expect:
            - Modifications reflected in instance
            - List mutability works as expected
            - No corruption of existing chunks
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given
        initial_chunk = LLMChunk(
            content="Initial chunk content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="paragraph",
            token_count=10,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        document = LLMDocument(
            document_id="doc_001",
            title="Modifiable Document",
            chunks=[initial_chunk],
            summary="Document for testing modifications",
            key_entities=[],
            processing_metadata={}
        )
        
        # When - append new chunk
        new_chunk = LLMChunk(
            content="New chunk content",
            chunk_id="chunk_0002",
            source_page=1,
            source_element="paragraph",
            token_count=8,
            semantic_type="text",
            relationships=["chunk_0001"],
            metadata={}
        )
        
        document.chunks.append(new_chunk)
        
        # Then - modifications should be reflected
        assert len(document.chunks) == 2
        assert document.chunks[0] == initial_chunk
        assert document.chunks[1] == new_chunk
        
        # When - remove chunk
        document.chunks.remove(initial_chunk)
        
        # Then - chunk should be removed
        assert len(document.chunks) == 1
        assert document.chunks[0] == new_chunk
        assert initial_chunk not in document.chunks

    def test_chunk_access_by_index(self):
        """
        GIVEN LLMDocument instance with multiple chunks
        WHEN accessing chunks by index
        THEN expect:
            - Correct chunk returned for each index
            - IndexError for invalid indices
            - Consistent ordering maintained
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given
        chunks = [
            LLMChunk(
                content="First chunk",
                chunk_id="chunk_0001",
                source_page=1,
                source_element="paragraph",
                token_count=8,
                semantic_type="text",
                relationships=[],
                metadata={}
            ),
            LLMChunk(
                content="Second chunk",
                chunk_id="chunk_0002",
                source_page=1,
                source_element="paragraph",
                token_count=9,
                semantic_type="text",
                relationships=["chunk_0001"],
                metadata={}
            ),
            LLMChunk(
                content="Third chunk",
                chunk_id="chunk_0003",
                source_page=2,
                source_element="table",
                token_count=12,
                semantic_type="table",
                relationships=["chunk_0002"],
                metadata={}
            )
        ]
        
        document = LLMDocument(
            document_id="doc_001",
            title="Multi-chunk Document",
            chunks=chunks,
            summary="Document with multiple chunks for indexing",
            key_entities=[],
            processing_metadata={}
        )
        
        # When/Then - valid indices
        assert document.chunks[0] == chunks[0]
        assert document.chunks[1] == chunks[1]
        assert document.chunks[2] == chunks[2]
        assert document.chunks[-1] == chunks[2]  # Negative indexing
        assert document.chunks[-2] == chunks[1]
        
        # When/Then - invalid indices should raise IndexError
        with pytest.raises(IndexError):
            _ = document.chunks[3]
        
        with pytest.raises(IndexError):
            _ = document.chunks[-4]

    def test_chunk_iteration(self):
        """
        GIVEN LLMDocument instance with chunks
        WHEN iterating over chunks
        THEN expect:
            - All chunks accessible via iteration
            - Iteration order matches list order
            - No chunks skipped or duplicated
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given
        chunks = [
            LLMChunk(
                content=f"Chunk {i} content",
                chunk_id=f"chunk_{i:04d}",
                source_page=1,
                source_element="paragraph",
                token_count=10,
                semantic_type="text",
                relationships=[],
                metadata={}
            )
            for i in range(1, 6)  # Create 5 chunks
        ]
        
        document = LLMDocument(
            document_id="doc_001",
            title="Iteration Test Document",
            chunks=chunks,
            summary="Document for testing chunk iteration",
            key_entities=[],
            processing_metadata={}
        )
        
        # When - iterate over chunks
        iterated_chunks = []
        for chunk in document.chunks:
            iterated_chunks.append(chunk)
        
        # Then - all chunks should be accessible in correct order
        assert len(iterated_chunks) == 5
        assert iterated_chunks == chunks
        
        # Verify order is preserved
        for i, chunk in enumerate(document.chunks):
            assert chunk.chunk_id == f"chunk_{i+1:04d}"
            assert chunk.content == f"Chunk {i+1} content"
        
        # Test list comprehension iteration
        chunk_ids = [chunk.chunk_id for chunk in document.chunks]
        expected_ids = [f"chunk_{i:04d}" for i in range(1, 6)]
        assert chunk_ids == expected_ids

    def test_chunk_count_property(self):
        """
        GIVEN LLMDocument instance with chunks
        WHEN getting chunk count
        THEN expect:
            - Correct count returned via len(chunks)
            - Count updates when chunks modified
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given - document with initial chunks
        initial_chunks = [
            LLMChunk(
                content="First chunk",
                chunk_id="chunk_0001",
                source_page=1,
                source_element="paragraph",
                token_count=8,
                semantic_type="text",
                relationships=[],
                metadata={}
            ),
            LLMChunk(
                content="Second chunk",
                chunk_id="chunk_0002",
                source_page=1,
                source_element="paragraph",
                token_count=9,
                semantic_type="text",
                relationships=["chunk_0001"],
                metadata={}
            )
        ]
        
        document = LLMDocument(
            document_id="doc_001",
            title="Count Test Document",
            chunks=initial_chunks,
            summary="Document for testing chunk counting",
            key_entities=[],
            processing_metadata={}
        )
        
        # When/Then - initial count
        assert len(document.chunks) == 2
        
        # When - add chunk
        new_chunk = LLMChunk(
            content="Third chunk",
            chunk_id="chunk_0003",
            source_page=2,
            source_element="table",
            token_count=12,
            semantic_type="table",
            relationships=["chunk_0002"],
            metadata={}
        )
        document.chunks.append(new_chunk)
        
        # Then - count should update
        assert len(document.chunks) == 3
        
        # When - remove chunk
        document.chunks.pop()
        
        # Then - count should decrease
        assert len(document.chunks) == 2
        
        # When - clear all chunks
        document.chunks.clear()
        
        # Then - count should be zero
        assert len(document.chunks) == 0

    def test_chunk_relationship_integrity(self):
        """
        GIVEN LLMDocument instance with chunks containing relationships
        WHEN accessing chunk relationships
        THEN expect:
            - All relationship references valid
            - Bidirectional relationships consistent
            - No broken or invalid chunk ID references
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given - chunks with relationships
        chunks = [
            LLMChunk(
                content="First chunk content",
                chunk_id="chunk_0001",
                source_page=1,
                source_element="paragraph",
                token_count=10,
                semantic_type="text",
                relationships=[],  # No predecessors
                metadata={}
            ),
            LLMChunk(
                content="Second chunk content",
                chunk_id="chunk_0002",
                source_page=1,
                source_element="paragraph",
                token_count=12,
                semantic_type="text",
                relationships=["chunk_0001"],  # References first chunk
                metadata={}
            ),
            LLMChunk(
                content="Third chunk content",
                chunk_id="chunk_0003",
                source_page=2,
                source_element="table",
                token_count=8,
                semantic_type="table",
                relationships=["chunk_0001", "chunk_0002"],  # References both previous
                metadata={}
            )
        ]
        
        document = LLMDocument(
            document_id="doc_001",
            title="Relationship Test Document",
            chunks=chunks,
            summary="Document for testing chunk relationships",
            key_entities=[],
            processing_metadata={}
        )
        
        # When/Then - verify relationships exist and are valid
        chunk_ids = {chunk.chunk_id for chunk in document.chunks}
        
        for chunk in document.chunks:
            # All relationship references should point to existing chunks
            for related_id in chunk.relationships:
                assert related_id in chunk_ids, f"Chunk {chunk.chunk_id} references non-existent chunk {related_id}"
        
        # Verify specific relationships
        assert document.chunks[0].relationships == []
        assert document.chunks[1].relationships == ["chunk_0001"]
        assert set(document.chunks[2].relationships) == {"chunk_0001", "chunk_0002"}
        
        # Verify no self-references
        for chunk in document.chunks:
            assert chunk.chunk_id not in chunk.relationships, f"Chunk {chunk.chunk_id} contains self-reference"


class TestLLMDocumentEntityManagement:
    """Test LLMDocument key entities management and validation."""

    def test_key_entities_structure_validation(self):
        """
        GIVEN LLMDocument instance with key_entities
        WHEN validating entity structure
        THEN expect each entity to have:
            - 'value' key with string value
            - 'type' key with string value
            - 'confidence' key with float value
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given
        sample_chunk = LLMChunk(
            content="John Doe works at OpenAI in San Francisco on January 1st, 2024",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=15,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        key_entities = [
            {"type": "PERSON", "value": "John Doe", "confidence": 0.95},
            {"type": "ORG", "value": "OpenAI", "confidence": 0.92},
            {"type": "GPE", "value": "San Francisco", "confidence": 0.88},
            {"type": "DATE", "value": "January 1st, 2024", "confidence": 0.85}
        ]
        
        document = LLMDocument(
            document_id="doc_001",
            title="Entity Structure Test",
            chunks=[sample_chunk],
            summary="Document for testing entity structure",
            key_entities=key_entities,
            processing_metadata={}
        )
        
        # When/Then - validate structure of each entity
        for entity in document.key_entities:
            assert isinstance(entity, dict), "Each entity should be a dictionary"
            
            # Required keys
            assert "type" in entity, "Entity missing 'type' key"
            assert "value" in entity, "Entity missing 'value' key"
            assert "confidence" in entity, "Entity missing 'confidence' key"
            
            # Type validation
            assert isinstance(entity["type"], str), "Entity 'type' should be string"
            assert isinstance(entity["value"], str), "Entity 'value' should be string"
            assert isinstance(entity["confidence"], (int, float)), "Entity 'confidence' should be numeric"
            
            # Value validation
            assert len(entity["type"]) > 0, "Entity 'type' should not be empty"
            assert len(entity["value"]) > 0, "Entity 'value' should not be empty"
            assert 0.0 <= entity["confidence"] <= 1.0, f"Entity confidence {entity['confidence']} should be between 0.0 and 1.0"

    def test_key_entities_list_modification(self):
        """
        GIVEN LLMDocument instance with key_entities list
        WHEN entities list is modified
        THEN expect:
            - Modifications reflected in instance
            - List mutability works as expected
            - Entity structure preserved
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given
        sample_chunk = LLMChunk(
            content="Test content with entities",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=10,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        initial_entities = [
            {"type": "PERSON", "value": "John Doe", "confidence": 0.95},
            {"type": "ORG", "value": "OpenAI", "confidence": 0.92}
        ]
        
        document = LLMDocument(
            document_id="doc_001",
            title="Entity Modification Test",
            chunks=[sample_chunk],
            summary="Document for testing entity modifications",
            key_entities=initial_entities.copy(),
            processing_metadata={}
        )
        
        # When - append new entity
        new_entity = {"type": "GPE", "value": "San Francisco", "confidence": 0.88}
        document.key_entities.append(new_entity)
        
        # Then - entity should be added
        assert len(document.key_entities) == 3
        assert document.key_entities[2] == new_entity
        
        # When - modify existing entity
        document.key_entities[0]["confidence"] = 0.98
        
        # Then - modification should be reflected
        assert document.key_entities[0]["confidence"] == 0.98
        assert document.key_entities[0]["type"] == "PERSON"
        assert document.key_entities[0]["value"] == "John Doe"
        
        # When - remove entity
        document.key_entities.remove(new_entity)
        
        # Then - entity should be removed
        assert len(document.key_entities) == 2
        assert new_entity not in document.key_entities
        
        # Verify remaining entities are intact
        assert document.key_entities[0]["type"] == "PERSON"
        assert document.key_entities[1]["type"] == "ORG"

    def test_entity_type_classification(self):
        """
        GIVEN LLMDocument instance with various entity types
        WHEN accessing entity types
        THEN expect:
            - Valid entity types present ('PERSON', 'ORG', 'GPE', 'DATE', etc.)
            - Type consistency maintained
            - Classification accuracy traceable
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given
        sample_chunk = LLMChunk(
            content="Dr. Jane Smith from Microsoft visited New York on December 25, 2023, and sent email to contact@example.com",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=20,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        diverse_entities = [
            {"type": "PERSON", "value": "Dr. Jane Smith", "confidence": 0.95},
            {"type": "ORG", "value": "Microsoft", "confidence": 0.92},
            {"type": "GPE", "value": "New York", "confidence": 0.88},
            {"type": "DATE", "value": "December 25, 2023", "confidence": 0.85},
            {"type": "EMAIL", "value": "contact@example.com", "confidence": 0.90},
            {"type": "MONEY", "value": "$1,000", "confidence": 0.82},
            {"type": "PERCENT", "value": "50%", "confidence": 0.78}
        ]
        
        document = LLMDocument(
            document_id="doc_001",
            title="Entity Classification Test",
            chunks=[sample_chunk],
            summary="Document for testing entity type classification",
            key_entities=diverse_entities,
            processing_metadata={}
        )
        
        # When/Then - verify entity types
        entity_types = [entity["type"] for entity in document.key_entities]
        expected_types = ["PERSON", "ORG", "GPE", "DATE", "EMAIL", "MONEY", "PERCENT"]
        
        assert set(entity_types) == set(expected_types), "Entity types should match expected types"
        
        # Verify type-value consistency
        type_value_mapping = {
            "PERSON": "Dr. Jane Smith",
            "ORG": "Microsoft",
            "GPE": "New York",
            "DATE": "December 25, 2023",
            "EMAIL": "contact@example.com",
            "MONEY": "$1,000",
            "PERCENT": "50%"
        }
        
        for entity in document.key_entities:
            entity_type = entity["type"]
            entity_value = entity["value"]
            assert entity_value == type_value_mapping[entity_type], f"Value '{entity_value}' doesn't match expected for type '{entity_type}'"
        
        # Verify all entity types are uppercase (standard convention)
        for entity in document.key_entities:
            assert entity["type"].isupper(), f"Entity type '{entity['type']}' should be uppercase"

    def test_entity_confidence_scores(self):
        """
        GIVEN LLMDocument instance with entities having confidence scores
        WHEN validating confidence values
        THEN expect:
            - All confidence scores between 0.0 and 1.0
            - Float type for all confidence values
            - Reasonable score distribution
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given
        sample_chunk = LLMChunk(
            content="Test content with various confidence entities",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=10,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        entities_with_varying_confidence = [
            {"type": "PERSON", "value": "High Confidence Person", "confidence": 0.95},
            {"type": "ORG", "value": "Medium Confidence Org", "confidence": 0.75},
            {"type": "GPE", "value": "Low Confidence Place", "confidence": 0.55},
            {"type": "DATE", "value": "Perfect Confidence Date", "confidence": 1.0},
            {"type": "MISC", "value": "Zero Confidence Item", "confidence": 0.0},
            {"type": "MONEY", "value": "Decimal Confidence Amount", "confidence": 0.123456}
        ]
        
        document = LLMDocument(
            document_id="doc_001",
            title="Confidence Score Test",
            chunks=[sample_chunk],
            summary="Document for testing entity confidence scores",
            key_entities=entities_with_varying_confidence,
            processing_metadata={}
        )
        
        # When/Then - validate confidence scores
        confidence_scores = [entity["confidence"] for entity in document.key_entities]
        
        # All scores should be between 0.0 and 1.0
        for score in confidence_scores:
            assert isinstance(score, (int, float)), f"Confidence score {score} should be numeric"
            assert 0.0 <= score <= 1.0, f"Confidence score {score} should be between 0.0 and 1.0"
        
        # Verify specific scores
        assert document.key_entities[0]["confidence"] == 0.95
        assert document.key_entities[1]["confidence"] == 0.75
        assert document.key_entities[2]["confidence"] == 0.55
        assert document.key_entities[3]["confidence"] == 1.0
        assert document.key_entities[4]["confidence"] == 0.0
        assert abs(document.key_entities[5]["confidence"] - 0.123456) < 1e-6
        
        # Test score distribution
        high_confidence = [e for e in document.key_entities if e["confidence"] >= 0.8]
        medium_confidence = [e for e in document.key_entities if 0.5 <= e["confidence"] < 0.8]
        low_confidence = [e for e in document.key_entities if e["confidence"] < 0.5]
        
        assert len(high_confidence) == 2  # 0.95 and 1.0
        assert len(medium_confidence) == 2  # 0.75 and 0.55
        assert len(low_confidence) == 2   # 0.0 and 0.123456


class TestLLMDocumentMetadataManagement:
    """Test LLMDocument processing metadata management."""

    def test_processing_metadata_structure(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN validating metadata structure
        THEN expect:
            - Dictionary with string keys
            - Appropriate value types for different metadata
            - Standard metadata fields present (timestamps, counts, etc.)
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given
        sample_chunk = LLMChunk(
            content="Test content for metadata validation",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=10,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        comprehensive_metadata = {
            "processing_time": 2.45,                    # float
            "model": "advanced_optimizer_v2",           # string
            "version": "1.2.3",                        # string
            "chunk_count": 5,                          # int
            "token_total": 150,                        # int
            "entities_found": 3,                       # int
            "confidence_avg": 0.89,                    # float
            "timestamp": "2024-01-01T12:00:00Z",       # string (ISO format)
            "source_file": "document.pdf",             # string
            "page_count": 10,                          # int
            "optimization_enabled": True,              # boolean
            "chunk_overlap": 200,                      # int
            "min_chunk_size": 100,                     # int
            "max_chunk_size": 2048                     # int
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Structure Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata structure",
            key_entities=[],
            processing_metadata=comprehensive_metadata
        )
        
        # When/Then - validate metadata structure
        metadata = document.processing_metadata
        
        # All keys should be strings
        for key in metadata.keys():
            assert isinstance(key, str), f"Metadata key '{key}' should be string"
            assert len(key) > 0, "Metadata keys should not be empty"
        
        # Validate specific field types
        assert isinstance(metadata["processing_time"], (int, float)), "processing_time should be numeric"
        assert isinstance(metadata["model"], str), "model should be string"
        assert isinstance(metadata["version"], str), "version should be string"
        assert isinstance(metadata["chunk_count"], int), "chunk_count should be integer"
        assert isinstance(metadata["token_total"], int), "token_total should be integer"
        assert isinstance(metadata["entities_found"], int), "entities_found should be integer"
        assert isinstance(metadata["confidence_avg"], (int, float)), "confidence_avg should be numeric"
        assert isinstance(metadata["timestamp"], str), "timestamp should be string"
        assert isinstance(metadata["optimization_enabled"], bool), "optimization_enabled should be boolean"
        
        # Validate value constraints
        assert metadata["processing_time"] > 0, "processing_time should be positive"
        assert metadata["chunk_count"] >= 0, "chunk_count should be non-negative"
        assert metadata["token_total"] >= 0, "token_total should be non-negative"
        assert metadata["entities_found"] >= 0, "entities_found should be non-negative"
        assert 0.0 <= metadata["confidence_avg"] <= 1.0, "confidence_avg should be between 0 and 1"

    def test_processing_metadata_modification(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN metadata is modified
        THEN expect:
            - Modifications reflected in instance
            - Dictionary mutability works as expected
            - No corruption of existing metadata
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given
        sample_chunk = LLMChunk(
            content="Test content for metadata modification",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=10,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        initial_metadata = {
            "processing_time": 1.23,
            "model": "initial_model",
            "chunk_count": 3,
            "confidence_avg": 0.85
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Modification Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata modifications",
            key_entities=[],
            processing_metadata=initial_metadata.copy()
        )
        
        # When - modify existing metadata
        document.processing_metadata["processing_time"] = 2.45
        document.processing_metadata["model"] = "updated_model"
        
        # Then - modifications should be reflected
        assert document.processing_metadata["processing_time"] == 2.45
        assert document.processing_metadata["model"] == "updated_model"
        
        # When - add new metadata
        document.processing_metadata["new_field"] = "new_value"
        document.processing_metadata["timestamp"] = "2024-01-01T12:00:00Z"
        
        # Then - new fields should be added
        assert len(document.processing_metadata) == 6
        assert document.processing_metadata["new_field"] == "new_value"
        assert document.processing_metadata["timestamp"] == "2024-01-01T12:00:00Z"
        
        # When - remove metadata
        del document.processing_metadata["chunk_count"]
        
        # Then - field should be removed
        assert "chunk_count" not in document.processing_metadata
        assert len(document.processing_metadata) == 5
        
        # Verify remaining fields are intact
        assert document.processing_metadata["confidence_avg"] == 0.85
        assert document.processing_metadata["processing_time"] == 2.45
        assert document.processing_metadata["model"] == "updated_model"

    def test_metadata_timestamp_tracking(self):
        """
        GIVEN LLMDocument instance with processing_metadata containing timestamps
        WHEN accessing timestamp information
        THEN expect:
            - Valid timestamp formats
            - Chronological consistency
            - Processing time tracking
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        from datetime import datetime
        import re
        
        # Given
        sample_chunk = LLMChunk(
            content="Test content for timestamp tracking",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=10,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        timestamp_metadata = {
            "created_at": "2024-01-01T10:00:00Z",
            "started_at": "2024-01-01T10:00:05Z",
            "completed_at": "2024-01-01T10:02:50Z",
            "processing_time": 165.0,  # seconds
            "last_modified": "2024-01-01T10:02:50Z",
            "version_timestamp": "2024-01-01T09:59:45Z"
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Timestamp Tracking Test",
            chunks=[sample_chunk],
            summary="Document for testing timestamp tracking",
            key_entities=[],
            processing_metadata=timestamp_metadata
        )
        
        # When/Then - validate timestamp formats (ISO 8601)
        iso_pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$'
        
        timestamp_fields = ["created_at", "started_at", "completed_at", "last_modified", "version_timestamp"]
        for field in timestamp_fields:
            timestamp = document.processing_metadata[field]
            assert isinstance(timestamp, str), f"{field} should be string"
            assert re.match(iso_pattern, timestamp), f"{field} should be valid ISO 8601 format: {timestamp}"
        
        # When/Then - validate chronological consistency
        created_time = datetime.fromisoformat(document.processing_metadata["created_at"].replace('Z', '+00:00'))
        started_time = datetime.fromisoformat(document.processing_metadata["started_at"].replace('Z', '+00:00'))
        completed_time = datetime.fromisoformat(document.processing_metadata["completed_at"].replace('Z', '+00:00'))
        version_time = datetime.fromisoformat(document.processing_metadata["version_timestamp"].replace('Z', '+00:00'))
        
        # Chronological order should be: version <= created <= started <= completed
        assert version_time <= created_time, "version_timestamp should be before or equal to created_at"
        assert created_time <= started_time, "created_at should be before or equal to started_at"
        assert started_time <= completed_time, "started_at should be before completed_at"
        
        # When/Then - validate processing time tracking
        actual_duration = (completed_time - started_time).total_seconds()
        recorded_duration = document.processing_metadata["processing_time"]
        
        assert isinstance(recorded_duration, (int, float)), "processing_time should be numeric"
        assert recorded_duration > 0, "processing_time should be positive"
        assert abs(actual_duration - recorded_duration) < 1.0, f"Processing time mismatch: actual={actual_duration}, recorded={recorded_duration}"
        
        # Verify specific timestamp values
        assert document.processing_metadata["created_at"] == "2024-01-01T10:00:00Z"
        assert document.processing_metadata["started_at"] == "2024-01-01T10:00:05Z"
        assert document.processing_metadata["completed_at"] == "2024-01-01T10:02:50Z"
        assert document.processing_metadata["processing_time"] == 165.0

    def test_metadata_count_tracking(self):
        """
        GIVEN LLMDocument instance with processing_metadata containing counts
        WHEN accessing count information
        THEN expect:
            - Accurate chunk counts
            - Token count totals
            - Entity count summaries
            - Consistency with actual data
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        import tiktoken

        # Get encoding for token counting
        encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")

        # Given - create multiple chunks with known token counts
        chunks = [
            LLMChunk(
                content="First chunk with specific token count",
                chunk_id="chunk_0001",
                source_page=1,
                source_element="paragraph",
                token_count=len(encoding.encode("First chunk with specific token count")),
                semantic_type="text",
                relationships=[],
                metadata={}
            ),
            LLMChunk(
                content="Second chunk with different token count",
                chunk_id="chunk_0002",
                source_page=1,
                source_element="paragraph",
                token_count=len(encoding.encode("Second chunk with different token count")),
                semantic_type="text",
                relationships=["chunk_0001"],
                metadata={}
            ),
            LLMChunk(
                content="Third chunk completing the set",
                chunk_id="chunk_0003",
                source_page=2,
                source_element="table",
                token_count=len(encoding.encode("Third chunk completing the set")),
                semantic_type="table",
                relationships=["chunk_0002"],
                metadata={}
            )
        ]
        
        # Create entities for counting
        key_entities = [
            {"type": "PERSON", "value": "John Doe", "confidence": 0.95},
            {"type": "ORG", "value": "OpenAI", "confidence": 0.92},
            {"type": "GPE", "value": "San Francisco", "confidence": 0.88},
            {"type": "DATE", "value": "January 1st, 2024", "confidence": 0.85}
        ]
        
        # Calculate expected totals
        expected_chunk_count = len(chunks)
        expected_token_total = sum(chunk.token_count for chunk in chunks)
        expected_entity_count = len(key_entities)
        expected_page_count = len(set(chunk.source_page for chunk in chunks))
        
        count_metadata = {
            "chunk_count": expected_chunk_count,
            "token_total": expected_token_total,
            "entity_count": expected_entity_count,
            "page_count": expected_page_count,
            "paragraph_count": len([c for c in chunks if c.source_element == "paragraph"]),
            "table_count": len([c for c in chunks if c.source_element == "table"]),
            "text_chunks": len([c for c in chunks if c.semantic_type == "text"]),
            "table_chunks": len([c for c in chunks if c.semantic_type == "table"]),
            "avg_tokens_per_chunk": expected_token_total / expected_chunk_count,
            "min_chunk_tokens": min(chunk.token_count for chunk in chunks),
            "max_chunk_tokens": max(chunk.token_count for chunk in chunks)
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Count Tracking Test",
            chunks=chunks,
            summary="Document for testing count tracking consistency",
            key_entities=key_entities,
            processing_metadata=count_metadata
        )
        
        # When/Then - validate count consistency with actual data
        assert document.processing_metadata["chunk_count"] == len(document.chunks), "chunk_count should match actual chunks"
        assert document.processing_metadata["entity_count"] == len(document.key_entities), "entity_count should match actual entities"
        
        # Validate token count totals
        actual_token_total = sum(chunk.token_count for chunk in document.chunks)
        assert document.processing_metadata["token_total"] == actual_token_total, f"token_total mismatch: expected {actual_token_total}, got {document.processing_metadata['token_total']}"
        
        # Validate page count
        actual_page_count = len(set(chunk.source_page for chunk in document.chunks))
        assert document.processing_metadata["page_count"] == actual_page_count, "page_count should match unique pages"
        
        # Validate element type counts
        actual_paragraph_count = len([c for c in document.chunks if c.source_element == "paragraph"])
        actual_table_count = len([c for c in document.chunks if c.source_element == "table"])
        assert document.processing_metadata["paragraph_count"] == actual_paragraph_count, "paragraph_count should match actual paragraphs"
        assert document.processing_metadata["table_count"] == actual_table_count, "table_count should match actual tables"
        
        # Validate semantic type counts
        actual_text_chunks = len([c for c in document.chunks if c.semantic_type == "text"])
        actual_table_chunks = len([c for c in document.chunks if c.semantic_type == "table"])
        assert document.processing_metadata["text_chunks"] == actual_text_chunks, "text_chunks should match actual text chunks"
        assert document.processing_metadata["table_chunks"] == actual_table_chunks, "table_chunks should match actual table chunks"
        
        # Validate statistical calculations
        expected_avg = actual_token_total / len(document.chunks)
        assert abs(document.processing_metadata["avg_tokens_per_chunk"] - expected_avg) < 0.01, "avg_tokens_per_chunk calculation incorrect"
        
        actual_min_tokens = min(chunk.token_count for chunk in document.chunks)
        actual_max_tokens = max(chunk.token_count for chunk in document.chunks)
        assert document.processing_metadata["min_chunk_tokens"] == actual_min_tokens, "min_chunk_tokens should match minimum"
        assert document.processing_metadata["max_chunk_tokens"] == actual_max_tokens, "max_chunk_tokens should match maximum"
        
        # Verify specific counts
        assert document.processing_metadata["chunk_count"] == 3
        assert document.processing_metadata["token_total"] == 75  # 25 + 30 + 20
        assert document.processing_metadata["entity_count"] == 4
        assert document.processing_metadata["page_count"] == 2
        assert document.processing_metadata["paragraph_count"] == 2
        assert document.processing_metadata["table_count"] == 1


class TestLLMDocumentDataclassMethods:
    """Test LLMDocument dataclass auto-generated methods."""

    def test_equality_comparison(self):
        """
        GIVEN two LLMDocument instances with identical field values
        WHEN compared for equality
        THEN expect instances to be equal
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        import numpy as np
        
        # Given - create identical chunks
        chunk1 = LLMChunk(
            content="Test chunk content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="paragraph",
            token_count=10,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        chunk2 = LLMChunk(
            content="Test chunk content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="paragraph",
            token_count=10,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        # Create identical key entities
        entities = [{"type": "PERSON", "value": "John Doe", "confidence": 0.95}]
        
        # Create identical metadata
        metadata = {"processing_time": 1.23, "model": "test_model"}
        
        # Create identical document embedding
        embedding = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        
        # Create two identical documents
        document1 = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[chunk1],
            summary="Test summary",
            key_entities=entities.copy(),
            processing_metadata=metadata.copy(),
            document_embedding=embedding.copy()
        )
        
        document2 = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[chunk2],
            summary="Test summary",
            key_entities=entities.copy(),
            processing_metadata=metadata.copy(),
            document_embedding=embedding.copy()
        )
        
        # When/Then - test equality
        assert document1 == document2, "Identical documents should be equal"
        assert not (document1 != document2), "Identical documents should not be unequal"
        
        # Test reflexivity
        assert document1 == document1, "Document should equal itself"
        
        # Test with None embedding
        document3 = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[chunk1],
            summary="Test summary",
            key_entities=entities.copy(),
            processing_metadata=metadata.copy(),
            document_embedding=None
        )
        
        document4 = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[chunk2],
            summary="Test summary",
            key_entities=entities.copy(),
            processing_metadata=metadata.copy(),
            document_embedding=None
        )
        
        assert document3 == document4, "Documents with None embeddings should be equal"

    def test_inequality_comparison(self):
        """
        GIVEN two LLMDocument instances with different field values
        WHEN compared for equality
        THEN expect instances to be unequal
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        import numpy as np
        
        # Given - create base document
        base_chunk = LLMChunk(
            content="Test chunk content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="paragraph",
            token_count=10,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        base_document = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[base_chunk],
            summary="Test summary",
            key_entities=[{"type": "PERSON", "value": "John Doe", "confidence": 0.95}],
            processing_metadata={"processing_time": 1.23},
            document_embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32)
        )
        
        # When/Then - test different document_id
        different_id = LLMDocument(
            document_id="doc_002",  # Different ID
            title="Test Document",
            chunks=[base_chunk],
            summary="Test summary",
            key_entities=[{"type": "PERSON", "value": "John Doe", "confidence": 0.95}],
            processing_metadata={"processing_time": 1.23},
            document_embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32)
        )
        assert base_document != different_id, "Documents with different IDs should be unequal"
        
        # Test different title
        different_title = LLMDocument(
            document_id="doc_001",
            title="Different Title",  # Different title
            chunks=[base_chunk],
            summary="Test summary",
            key_entities=[{"type": "PERSON", "value": "John Doe", "confidence": 0.95}],
            processing_metadata={"processing_time": 1.23},
            document_embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32)
        )
        assert base_document != different_title, "Documents with different titles should be unequal"
        
        # Test different summary
        different_summary = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[base_chunk],
            summary="Different summary",  # Different summary
            key_entities=[{"type": "PERSON", "value": "John Doe", "confidence": 0.95}],
            processing_metadata={"processing_time": 1.23},
            document_embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32)
        )
        assert base_document != different_summary, "Documents with different summaries should be unequal"
        
        # Test different entities
        different_entities = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[base_chunk],
            summary="Test summary",
            key_entities=[{"type": "ORG", "value": "OpenAI", "confidence": 0.92}],  # Different entities
            processing_metadata={"processing_time": 1.23},
            document_embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32)
        )
        assert base_document != different_entities, "Documents with different entities should be unequal"
        
        # Test different metadata
        different_metadata = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[base_chunk],
            summary="Test summary",
            key_entities=[{"type": "PERSON", "value": "John Doe", "confidence": 0.95}],
            processing_metadata={"processing_time": 2.45},  # Different metadata
            document_embedding=np.array([0.1, 0.2, 0.3], dtype=np.float32)
        )
        assert base_document != different_metadata, "Documents with different metadata should be unequal"
        
        # Test different embedding
        different_embedding = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[base_chunk],
            summary="Test summary",
            key_entities=[{"type": "PERSON", "value": "John Doe", "confidence": 0.95}],
            processing_metadata={"processing_time": 1.23},
            document_embedding=np.array([0.4, 0.5, 0.6], dtype=np.float32)  # Different embedding
        )
        assert base_document != different_embedding, "Documents with different embeddings should be unequal"
        
        # Test None vs array embedding
        none_embedding = LLMDocument(
            document_id="doc_001",
            title="Test Document",
            chunks=[base_chunk],
            summary="Test summary",
            key_entities=[{"type": "PERSON", "value": "John Doe", "confidence": 0.95}],
            processing_metadata={"processing_time": 1.23},
            document_embedding=None  # None vs array
        )
        assert base_document != none_embedding, "Documents with None vs array embedding should be unequal"

    def test_string_representation(self):
        """
        GIVEN LLMDocument instance
        WHEN converted to string representation
        THEN expect:
            - Readable string format
            - Key information included (title, chunk count, etc.)
            - No truncation of critical data
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        import numpy as np
        
        # Given
        chunks = [
            LLMChunk(
                content="First chunk content",
                chunk_id="chunk_0001",
                source_page=1,
                source_element="paragraph",
                token_count=10,
                semantic_type="text",
                relationships=[],
                metadata={}
            ),
            LLMChunk(
                content="Second chunk content",
                chunk_id="chunk_0002",
                source_page=1,
                source_element="paragraph",
                token_count=12,
                semantic_type="text",
                relationships=["chunk_0001"],
                metadata={}
            )
        ]
        
        document = LLMDocument(
            document_id="doc_001",
            title="Advanced Document Processing Analysis",
            chunks=chunks,
            summary="This document analyzes advanced techniques for document processing and optimization.",
            key_entities=[
                {"type": "PERSON", "value": "John Doe", "confidence": 0.95},
                {"type": "ORG", "value": "OpenAI", "confidence": 0.92}
            ],
            processing_metadata={
                "processing_time": 2.45,
                "model": "advanced_optimizer_v2",
                "chunk_count": 2
            },
            document_embedding=np.array([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32)
        )
        
        # When
        str_repr = str(document)
        
        # Then - verify string representation contains key information
        assert isinstance(str_repr, str), "String representation should be string type"
        assert len(str_repr) > 0, "String representation should not be empty"
        
        # Check for key information presence
        assert "doc_001" in str_repr, "Document ID should be in string representation"
        assert "Advanced Document Processing Analysis" in str_repr, "Title should be in string representation"
        assert "2" in str_repr, "Chunk count should be represented"
        
        # Verify readability - should not be overly verbose
        assert len(str_repr) < 500, "String representation should be concise and readable"
        
        # Test with None embedding
        document_none_embedding = LLMDocument(
            document_id="doc_002",
            title="Test Document",
            chunks=chunks[:1],
            summary="Test summary",
            key_entities=[],
            processing_metadata={},
            document_embedding=None
        )
        
        str_repr_none = str(document_none_embedding)
        assert isinstance(str_repr_none, str), "String representation with None embedding should be string"
        assert "doc_002" in str_repr_none, "Document ID should be present even with None embedding"
        
        # Test with empty chunks
        document_empty = LLMDocument(
            document_id="doc_003",
            title="Empty Document",
            chunks=[],
            summary="Empty document",
            key_entities=[],
            processing_metadata={},
            document_embedding=None
        )
        
        str_repr_empty = str(document_empty)
        assert isinstance(str_repr_empty, str), "String representation of empty document should be string"
        assert "doc_003" in str_repr_empty, "Document ID should be present even in empty document"
        assert "0" in str_repr_empty, "Zero chunk count should be represented"

    def test_repr_representation(self):
        """
        GIVEN LLMDocument instance
        WHEN repr() is called
        THEN expect:
            - Detailed representation suitable for debugging
            - All field summaries visible
            - Large data structures appropriately summarized
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        import numpy as np
        
        # Given
        chunks = [
            LLMChunk(
                content="First chunk content for testing repr",
                chunk_id="chunk_0001",
                source_page=1,
                source_element="paragraph",
                token_count=15,
                semantic_type="text",
                relationships=[],
                metadata={"test_meta": "value"}
            ),
            LLMChunk(
                content="Second chunk with relationships",
                chunk_id="chunk_0002",
                source_page=2,
                source_element="table",
                token_count=20,
                semantic_type="table",
                relationships=["chunk_0001"],
                metadata={}
            )
        ]
        
        document = LLMDocument(
            document_id="doc_debug_001",
            title="Debug Document for Repr Testing",
            chunks=chunks,
            summary="Comprehensive summary for debugging representation functionality.",
            key_entities=[
                {"type": "PERSON", "value": "Alice Smith", "confidence": 0.95},
                {"type": "ORG", "value": "TechCorp", "confidence": 0.88},
                {"type": "GPE", "value": "New York", "confidence": 0.92}
            ],
            processing_metadata={
                "processing_time": 3.67,
                "model": "debug_optimizer_v1",
                "version": "1.0.0",
                "chunk_count": 2,
                "entity_count": 3,
                "total_tokens": 35
            },
            document_embedding=np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], dtype=np.float32)
        )
        
        # When
        repr_str = repr(document)
        
        # Then - verify repr contains detailed information
        assert isinstance(repr_str, str), "Repr should return string"
        assert len(repr_str) > 0, "Repr should not be empty"
        
        # Check for constructor-like format or detailed field information
        assert "LLMDocument" in repr_str or "doc_debug_001" in repr_str, "Repr should identify the class or instance"
        
        # Should contain key identifying information
        key_elements = ["doc_debug_001", "Debug Document", "chunks", "entities"]
        present_elements = sum(1 for element in key_elements if element in repr_str)
        assert present_elements >= 2, f"Repr should contain at least 2 key elements, found {present_elements}"
        
        # Should be more detailed than str() but not excessively long
        str_repr = str(document)
        assert len(repr_str) >= len(str_repr), "Repr should be at least as detailed as str()"
        assert len(repr_str) < 2000, "Repr should not be excessively verbose"
        
        # Test with None embedding
        document_none = LLMDocument(
            document_id="doc_none_001",
            title="None Embedding Document",
            chunks=chunks[:1],
            summary="Document with None embedding",
            key_entities=[],
            processing_metadata={},
            document_embedding=None
        )
        
        repr_none = repr(document_none)
        assert isinstance(repr_none, str), "Repr with None embedding should be string"
        assert "doc_none_001" in repr_none or "None Embedding Document" in repr_none, "Repr should contain identifying information"
        
        # Test with minimal document
        minimal_document = LLMDocument(
            document_id="minimal",
            title="Minimal",
            chunks=[],
            summary="",
            key_entities=[],
            processing_metadata={},
            document_embedding=None
        )
        
        repr_minimal = repr(minimal_document)
        assert isinstance(repr_minimal, str), "Repr of minimal document should be string"
        assert "minimal" in repr_minimal or "Minimal" in repr_minimal, "Repr should contain basic identifying information"
        assert len(repr_minimal) > 10, "Even minimal repr should have some substance"


class TestLLMDocumentEmbeddingHandling:
    """Test LLMDocument document-level embedding handling."""

    def test_document_embedding_shape_preservation(self):
        """
        GIVEN numpy array with specific shape as document_embedding
        WHEN LLMDocument is instantiated and accessed
        THEN expect original array shape preserved
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        import numpy as np
        
        # Given
        sample_chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        # Test different shapes
        shapes_to_test = [
            (5,),           # 1D vector
            (10,),          # Different 1D size
            (3, 4),         # 2D matrix
            (2, 3, 4),      # 3D tensor
            (1, 384),       # Common embedding dimension
            (768,),         # Another common embedding size
        ]
        
        for shape in shapes_to_test:
            # Create array with specific shape
            original_array = np.random.rand(*shape).astype(np.float32)
            
            document = LLMDocument(
                document_id=f"doc_{len(shape)}d",
                title="Shape Preservation Test",
                chunks=[sample_chunk],
                summary="Testing shape preservation",
                key_entities=[],
                processing_metadata={},
                document_embedding=original_array
            )
            
            # When/Then - verify shape preservation
            assert document.document_embedding.shape == shape, f"Shape {shape} not preserved, got {document.document_embedding.shape}"
            assert document.document_embedding.shape == original_array.shape, "Shape should match original array"
            
            # Verify it's the same array (reference check)
            assert np.array_equal(document.document_embedding, original_array), f"Array values changed for shape {shape}"
            
        # Test edge case: empty array
        empty_array = np.array([], dtype=np.float32)
        document_empty = LLMDocument(
            document_id="doc_empty",
            title="Empty Array Test",
            chunks=[sample_chunk],
            summary="Testing empty array",
            key_entities=[],
            processing_metadata={},
            document_embedding=empty_array
        )
        
        assert document_empty.document_embedding.shape == (0,), "Empty array shape should be preserved"
        assert document_empty.document_embedding.size == 0, "Empty array should have size 0"

    def test_document_embedding_dtype_preservation(self):
        """
        GIVEN numpy array with specific dtype as document_embedding
        WHEN LLMDocument is instantiated and accessed
        THEN expect original array dtype preserved
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        import numpy as np
        
        # Given
        sample_chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        # Test different dtypes
        dtypes_to_test = [
            np.float32,
            np.float64,
            np.int32,
            np.int64,
            np.float16,
        ]
        
        test_data = [0.1, 0.2, 0.3, 0.4, 0.5]
        
        for dtype in dtypes_to_test:
            # Create array with specific dtype
            original_array = np.array(test_data, dtype=dtype)
            
            document = LLMDocument(
                document_id=f"doc_{dtype.name}",
                title="Dtype Preservation Test",
                chunks=[sample_chunk],
                summary="Testing dtype preservation",
                key_entities=[],
                processing_metadata={},
                document_embedding=original_array
            )
            
            # When/Then - verify dtype preservation
            assert document.document_embedding.dtype == dtype, f"Dtype {dtype} not preserved, got {document.document_embedding.dtype}"
            assert document.document_embedding.dtype == original_array.dtype, "Dtype should match original array"
            
            # Verify values are preserved (within dtype precision)
            if dtype in [np.float16, np.float32, np.float64]:
                assert np.allclose(document.document_embedding, original_array, rtol=1e-6), f"Float values changed for dtype {dtype}"
            else:
                assert np.array_equal(document.document_embedding, original_array), f"Integer values changed for dtype {dtype}"
        
        # Test with boolean dtype
        bool_array = np.array([True, False, True, False], dtype=np.bool_)
        document_bool = LLMDocument(
            document_id="doc_bool",
            title="Boolean Dtype Test",
            chunks=[sample_chunk],
            summary="Testing boolean dtype",
            key_entities=[],
            processing_metadata={},
            document_embedding=bool_array
        )
        
        assert document_bool.document_embedding.dtype == np.bool_, "Boolean dtype should be preserved"
        assert np.array_equal(document_bool.document_embedding, bool_array), "Boolean values should be preserved"

    def test_document_embedding_data_integrity(self):
        """
        GIVEN numpy array with specific values as document_embedding
        WHEN LLMDocument is instantiated and accessed
        THEN expect document stores a copy and preserves original values
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        import numpy as np
        
        # Given
        sample_chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        # Test with specific values that could be subject to precision issues
        test_cases = [
            # Basic values
            np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float32),
            # Very small values
            np.array([1e-8, 2e-8, 3e-8], dtype=np.float64),
            # Very large values
            np.array([1e8, 2e8, 3e8], dtype=np.float64),
            # Mixed positive/negative
            np.array([-1.5, 0.0, 1.5, -2.5, 2.5], dtype=np.float32),
            # High precision values
            np.array([0.123456789, 0.987654321, 0.555555555], dtype=np.float64),
            # Integer values
            np.array([10, 20, 30, 40, 50], dtype=np.int32),
        ]
        
        for i, original_array in enumerate(test_cases):
            # Create a copy to verify original values
            expected_values = original_array.copy()
            
            # When
            document = LLMDocument(
                document_id=f"doc_integrity_{i}",
                title="Data Integrity Test",
                chunks=[sample_chunk],
                summary="Testing data integrity",
                key_entities=[],
                processing_metadata={},
                document_embedding=original_array
            )
            
            # Then - verify values are preserved exactly
            assert np.array_equal(document.document_embedding, expected_values), f"Values not preserved for test case {i}"
            assert document.document_embedding.dtype == original_array.dtype, f"Dtype not preserved for test case {i}"
            
            # Verify precision for floating point arrays
            if original_array.dtype in [np.float32, np.float64]:
                assert np.allclose(document.document_embedding, expected_values, rtol=1e-15, atol=1e-15), f"Float precision lost for test case {i}"
            
            # Test that document stores a copy, not a reference
            # Modify the original array after document creation
            if original_array.size > 0:
                if original_array.dtype in [np.float32, np.float64]:
                    original_array[0] = 999.999
                else:
                    original_array[0] = 999
                
                # Document embedding should still match expected values (proving it's a copy)
                assert np.array_equal(document.document_embedding, expected_values), f"Document not storing copy for test case {i}"
                assert document.document_embedding[0] != 999, f"Document storing reference instead of copy for test case {i}"
        
        # Test with array containing NaN and inf
        special_values = np.array([np.nan, np.inf, -np.inf, 0.0, 1.0], dtype=np.float64)
        document_special = LLMDocument(
            document_id="doc_special",
            title="Special Values Test",
            chunks=[sample_chunk],
            summary="Testing special values",
            key_entities=[],
            processing_metadata={},
            document_embedding=special_values
        )
        
        # Then - verify special values are preserved
        result_array = document_special.document_embedding
        assert np.isnan(result_array[0]), "NaN value should be preserved"
        assert np.isinf(result_array[1]) and result_array[1] > 0, "Positive infinity should be preserved"
        assert np.isinf(result_array[2]) and result_array[2] < 0, "Negative infinity should be preserved"
        assert result_array[3] == 0.0, "Zero should be preserved"
        assert result_array[4] == 1.0, "One should be preserved"

    def test_document_embedding_memory_sharing(self):
        """
        GIVEN numpy array as document_embedding
        WHEN LLMDocument is instantiated
        THEN expect:
            - Memory sharing behavior documented
            - No unexpected array copying
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        import numpy as np
        
        # Given
        sample_chunk = LLMChunk(
            content="Test content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="text",
            token_count=5,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        # Test memory sharing behavior
        original_array = np.array([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32)
        original_id = id(original_array)
        original_data_ptr = original_array.__array_interface__['data'][0]
        
        document = LLMDocument(
            document_id="doc_memory",
            title="Memory Sharing Test",
            chunks=[sample_chunk],
            summary="Testing memory sharing",
            key_entities=[],
            processing_metadata={},
            document_embedding=original_array
        )
        
        # When/Then - analyze memory sharing behavior
        document_array = document.document_embedding
        document_id = id(document_array)
        document_data_ptr = document_array.__array_interface__['data'][0]
        
        # Test whether arrays share memory
        memory_shared = (original_data_ptr == document_data_ptr)
        reference_shared = (original_id == document_id)
        
        if memory_shared:
            # If memory is shared, modifications should be visible in both
            print("Memory is shared between original and document embedding")
            original_value = original_array[0]
            document_array[0] = 999.0
            assert original_array[0] == 999.0, "Modification should be visible in original array when memory is shared"
            # Restore original value
            document_array[0] = original_value
        else:
            # If memory is not shared, arrays should be independent
            print("Memory is not shared - arrays are independent")
            original_value = original_array[0]
            document_array[0] = 999.0
            assert original_array[0] == original_value, "Original array should not be modified when memory is not shared"
        
        # Test with different array configurations
        test_arrays = [
            # Different shapes and sizes
            np.array([1.0], dtype=np.float32),  # Single element
            np.ones((100,), dtype=np.float32),   # Larger array
            np.eye(3, dtype=np.float64),         # 2D array
            np.zeros((2, 3, 4), dtype=np.float32),  # 3D array
        ]
        
        for i, test_array in enumerate(test_arrays):
            doc_test = LLMDocument(
                document_id=f"doc_mem_{i}",
                title="Memory Test",
                chunks=[sample_chunk],
                summary="Testing memory behavior",
                key_entities=[],
                processing_metadata={},
                document_embedding=test_array
            )
            
            # Verify the document has a valid embedding
            assert doc_test.document_embedding is not None, f"Document embedding should not be None for test {i}"
            assert isinstance(doc_test.document_embedding, np.ndarray), f"Document embedding should be numpy array for test {i}"
            assert doc_test.document_embedding.shape == test_array.shape, f"Shape should be preserved for test {i}"
            
        # Test memory behavior with array views
        base_array = np.arange(20, dtype=np.float32)
        view_array = base_array[5:15]  # Create a view
        
        document_view = LLMDocument(
            document_id="doc_view",
            title="View Test",
            chunks=[sample_chunk],
            summary="Testing array view behavior",
            key_entities=[],
            processing_metadata={},
            document_embedding=view_array
        )
        
        # Verify view properties are handled correctly
        assert document_view.document_embedding.shape == view_array.shape, "View shape should be preserved"
        assert np.array_equal(document_view.document_embedding, view_array), "View data should be preserved"
        
        # Test with read-only array
        readonly_array = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        readonly_array.flags.writeable = False
        
        document_readonly = LLMDocument(
            document_id="doc_readonly",
            title="Read-only Test",
            chunks=[sample_chunk],
            summary="Testing read-only array",
            key_entities=[],
            processing_metadata={},
            document_embedding=readonly_array
        )
        
        assert document_readonly.document_embedding is not None, "Read-only array should be handled"
        assert np.array_equal(document_readonly.document_embedding, readonly_array), "Read-only array data should be preserved"


class TestLLMDocumentIntegration:
    """Test LLMDocument integration with related classes and overall coherence."""

    def test_document_chunk_consistency(self):
        """
        GIVEN LLMDocument instance with chunks and document-level data
        WHEN validating consistency
        THEN expect:
            - Document title consistent with chunk content
            - Summary reflects chunk content accurately
            - Token counts add up correctly
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given - create chunks with consistent content theme
        chunks = [
            LLMChunk(
                content="Machine learning algorithms are transforming data analysis in modern computing systems.",
                chunk_id="chunk_0001",
                source_page=1,
                source_element="paragraph",
                token_count=15,
                semantic_type="text",
                relationships=[],
                metadata={"topic": "machine_learning"}
            ),
            LLMChunk(
                content="Deep neural networks provide powerful tools for pattern recognition and classification tasks.",
                chunk_id="chunk_0002",
                source_page=1,
                source_element="paragraph",
                token_count=14,
                semantic_type="text",
                relationships=["chunk_0001"],
                metadata={"topic": "machine_learning"}
            ),
            LLMChunk(
                content="Data preprocessing and feature engineering are crucial steps in machine learning pipelines.",
                chunk_id="chunk_0003",
                source_page=2,
                source_element="paragraph",
                token_count=13,
                semantic_type="text",
                relationships=["chunk_0002"],
                metadata={"topic": "machine_learning"}
            )
        ]
        
        # Create document with consistent theme
        document = LLMDocument(
            document_id="doc_ml_001",
            title="Machine Learning in Modern Data Analysis",
            chunks=chunks,
            summary="This document explores machine learning algorithms, deep neural networks, and data preprocessing techniques for modern data analysis applications.",
            key_entities=[
                {"type": "TECH", "value": "machine learning", "confidence": 0.95},
                {"type": "TECH", "value": "neural networks", "confidence": 0.90},
                {"type": "TECH", "value": "data analysis", "confidence": 0.88}
            ],
            processing_metadata={
                "chunk_count": 3,
                "total_tokens": 42,  # 15 + 14 + 13
                "topic_consistency": 0.95,
                "processing_time": 1.23
            }
        )
        
        # When/Then - validate consistency
        
        # 1. Token count consistency
        actual_token_total = sum(chunk.token_count for chunk in document.chunks)
        metadata_token_total = document.processing_metadata.get("total_tokens", 0)
        assert actual_token_total == metadata_token_total, f"Token count mismatch: chunks={actual_token_total}, metadata={metadata_token_total}"
        
        # 2. Chunk count consistency
        actual_chunk_count = len(document.chunks)
        metadata_chunk_count = document.processing_metadata.get("chunk_count", 0)
        assert actual_chunk_count == metadata_chunk_count, f"Chunk count mismatch: actual={actual_chunk_count}, metadata={metadata_chunk_count}"
        
        # 3. Thematic consistency - title should relate to content
        title_lower = document.title.lower()
        content_text = " ".join(chunk.content for chunk in document.chunks).lower()
        
        # Check for key terms from title in content
        title_terms = ["machine", "learning", "data", "analysis"]
        content_matches = sum(1 for term in title_terms if term in content_text)
        assert content_matches >= 3, f"Title themes should be reflected in content, found {content_matches}/4 terms"
        
        # 4. Summary consistency with content
        summary_lower = document.summary.lower()
        summary_terms = ["machine learning", "neural networks", "data"]
        summary_matches = sum(1 for term in summary_terms if term in content_text)
        assert summary_matches >= 2, f"Summary themes should match content, found {summary_matches}/3 terms"
        
        # 5. Entity consistency with content
        entity_values = [entity["value"].lower() for entity in document.key_entities]
        entity_matches = sum(1 for value in entity_values if value in content_text)
        assert entity_matches >= 2, f"Entities should be present in content, found {entity_matches}/{len(entity_values)} entities"
        
        # 6. Page sequence consistency
        page_numbers = [chunk.source_page for chunk in document.chunks]
        assert all(isinstance(page, int) and page > 0 for page in page_numbers), "All page numbers should be positive integers"
        assert max(page_numbers) - min(page_numbers) <= 5, "Page span should be reasonable for a coherent document"
        
        # 7. Relationship chain consistency
        chunk_ids = {chunk.chunk_id for chunk in document.chunks}
        for chunk in document.chunks:
            for related_id in chunk.relationships:
                assert related_id in chunk_ids, f"Relationship {related_id} should reference an existing chunk"

    def test_document_entity_chunk_alignment(self):
        """
        GIVEN LLMDocument instance with entities and chunks
        WHEN validating entity-chunk alignment
        THEN expect:
            - Entities traceable to specific chunks
            - No entities from missing content
            - Entity confidence aligned with chunk quality
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        
        # Given - create chunks with specific named entities
        chunks = [
            LLMChunk(
                content="Dr. Sarah Johnson from Stanford University published groundbreaking research on artificial intelligence.",
                chunk_id="chunk_0001",
                source_page=1,
                source_element="paragraph",
                token_count=16,
                semantic_type="text",
                relationships=[],
                metadata={"quality_score": 0.95}
            ),
            LLMChunk(
                content="The study was conducted in collaboration with Microsoft Research and OpenAI in San Francisco.",
                chunk_id="chunk_0002",
                source_page=1,
                source_element="paragraph",
                token_count=15,
                semantic_type="text",
                relationships=["chunk_0001"],
                metadata={"quality_score": 0.88}
            ),
            LLMChunk(
                content="The research was published on January 15, 2024, and received significant attention from the AI community.",
                chunk_id="chunk_0003",
                source_page=2,
                source_element="paragraph",
                token_count=17,
                semantic_type="text",
                relationships=["chunk_0002"],
                metadata={"quality_score": 0.92}
            )
        ]
        
        # Define entities with source chunk tracking
        key_entities = [
            {"type": "PERSON", "value": "Dr. Sarah Johnson", "confidence": 0.95, "source_chunk": "chunk_0001"},
            {"type": "ORG", "value": "Stanford University", "confidence": 0.92, "source_chunk": "chunk_0001"},
            {"type": "ORG", "value": "Microsoft Research", "confidence": 0.90, "source_chunk": "chunk_0002"},
            {"type": "ORG", "value": "OpenAI", "confidence": 0.88, "source_chunk": "chunk_0002"},
            {"type": "GPE", "value": "San Francisco", "confidence": 0.85, "source_chunk": "chunk_0002"},
            {"type": "DATE", "value": "January 15, 2024", "confidence": 0.93, "source_chunk": "chunk_0003"},
            {"type": "TECH", "value": "artificial intelligence", "confidence": 0.89, "source_chunk": "chunk_0001"}
        ]
        
        document = LLMDocument(
            document_id="doc_entity_align_001",
            title="AI Research Collaboration Study",
            chunks=chunks,
            summary="Research collaboration between universities and tech companies on AI advancements.",
            key_entities=key_entities,
            processing_metadata={
                "entity_extraction_confidence": 0.91,
                "chunk_quality_avg": 0.92
            }
        )
        
        # When/Then - validate entity-chunk alignment
        
        # 1. Verify all entities are traceable to existing chunks
        chunk_ids = {chunk.chunk_id for chunk in document.chunks}
        for entity in document.key_entities:
            if "source_chunk" in entity:
                source_chunk_id = entity["source_chunk"]
                assert source_chunk_id in chunk_ids, f"Entity '{entity['value']}' references non-existent chunk '{source_chunk_id}'"
        
        # 2. Verify entities actually appear in their source chunks
        chunk_content_map = {chunk.chunk_id: chunk.content.lower() for chunk in document.chunks}
        
        for entity in document.key_entities:
            entity_value = entity["value"].lower()
            if "source_chunk" in entity:
                source_chunk_id = entity["source_chunk"]
                source_content = chunk_content_map[source_chunk_id]
                
                # Check if entity value appears in source chunk content
                entity_in_content = entity_value in source_content
                if not entity_in_content:
                    # For compound entities, check if key parts are present
                    entity_words = entity_value.split()
                    words_in_content = sum(1 for word in entity_words if word in source_content)
                    entity_coverage = words_in_content / len(entity_words)
                    assert entity_coverage >= 0.5, f"Entity '{entity['value']}' not sufficiently present in source chunk '{source_chunk_id}'"
        
        # 3. Verify entity confidence aligns with chunk quality
        for entity in document.key_entities:
            if "source_chunk" in entity:
                source_chunk_id = entity["source_chunk"]
                source_chunk = next(chunk for chunk in document.chunks if chunk.chunk_id == source_chunk_id)
                chunk_quality = source_chunk.metadata.get("quality_score", 0.5)
                entity_confidence = entity["confidence"]
                
                # Entity confidence should correlate with chunk quality
                confidence_quality_diff = abs(entity_confidence - chunk_quality)
                assert confidence_quality_diff <= 0.2, f"Entity confidence {entity_confidence} too far from chunk quality {chunk_quality} for '{entity['value']}'"
        
        # 4. Verify no orphaned entities (entities without corresponding content)
        all_content = " ".join(chunk.content.lower() for chunk in document.chunks)
        
        for entity in document.key_entities:
            entity_value = entity["value"].lower()
            # Check if entity appears somewhere in the document
            entity_words = entity_value.split()
            words_found = sum(1 for word in entity_words if word in all_content)
            coverage = words_found / len(entity_words)
            assert coverage >= 0.5, f"Entity '{entity['value']}' appears to be orphaned - not found in document content"
        
        # 5. Verify entity type consistency with content context
        person_entities = [e for e in document.key_entities if e["type"] == "PERSON"]
        org_entities = [e for e in document.key_entities if e["type"] == "ORG"]
        date_entities = [e for e in document.key_entities if e["type"] == "DATE"]
        
        # Should have reasonable distribution of entity types for research paper content
        assert len(person_entities) >= 1, "Research content should contain person entities"
        assert len(org_entities) >= 1, "Research content should contain organization entities"
        assert len(date_entities) >= 1, "Research content should contain date entities"
        
        # 6. Verify high-confidence entities appear in high-quality chunks
        high_confidence_entities = [e for e in document.key_entities if e.get("confidence", 0) >= 0.9]
        for entity in high_confidence_entities:
            if "source_chunk" in entity:
                source_chunk_id = entity["source_chunk"]
                source_chunk = next(chunk for chunk in document.chunks if chunk.chunk_id == source_chunk_id)
                chunk_quality = source_chunk.metadata.get("quality_score", 0.5)
                assert chunk_quality >= 0.85, f"High-confidence entity '{entity['value']}' should come from high-quality chunk"
                def test_document_large_scale_handling(self):
                    """
                    GIVEN LLMDocument instance with large number of chunks (>100)
                    WHEN performing operations
                    THEN expect:
                        - Performance remains acceptable for production use
                        - Memory usage stays within production limits
                        - All chunks accessible and valid under load
                    """
                    from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
                    import time
                    import numpy as np
                    import gc
                    import psutil
                    import os
                    
                    # Given - create production-scale number of chunks
                    num_chunks = 500  # Increased for production testing
                    chunks = []
                    
                    # Monitor memory before chunk creation
                    process = psutil.Process(os.getpid())
                    initial_memory = process.memory_info().rss / 1024 / 1024  # MB
                    
                    start_time = time.time()
                    
                    for i in range(num_chunks):
                        # Create realistic production content
                        content_base = f"Production chunk {i+1}: This document section discusses critical business processes and technical implementations. "
                        content_extensions = [
                            "The analysis reveals significant performance improvements in distributed systems architecture.",
                            "Implementation considerations include scalability, reliability, and maintainability factors.",
                            "Security protocols must be integrated throughout the entire development lifecycle.",
                            "Performance metrics indicate optimal resource utilization under high-load scenarios.",
                            "Compliance requirements necessitate comprehensive audit trails and monitoring capabilities."
                        ]
                        content = content_base + content_extensions[i % len(content_extensions)]
                        
                        chunk = LLMChunk(
                            content=content,
                            chunk_id=f"chunk_{i+1:05d}",  # 5-digit padding for production scale
                            source_page=(i // 20) + 1,  # 20 chunks per page for realistic documents
                            source_element="paragraph" if i % 4 != 3 else "table",
                            token_count=45 + (i % 15),  # More realistic token counts
                            semantic_type="text" if i % 7 != 0 else ("table" if i % 14 == 0 else "header"),
                            relationships=[f"chunk_{max(1, i):05d}"] if i > 0 else [],
                            metadata={
                                "index": i,
                                "topic": f"production_topic_{i % 20}",
                                "priority": "high" if i % 10 == 0 else "normal",
                                "processing_stage": "complete",
                                "validation_status": "passed"
                            }
                        )
                        chunks.append(chunk)
                    
                    chunk_creation_time = time.time() - start_time
                    
                    # Create production-scale entities
                    num_entities = 1000  # Production-level entity count
                    key_entities = []
                    entity_types = ["PERSON", "ORG", "GPE", "DATE", "TECH", "MONEY", "PRODUCT", "EVENT"]
                    
                    for i in range(num_entities):
                        entity = {
                            "type": entity_types[i % len(entity_types)],
                            "value": f"ProductionEntity_{i+1:04d}",
                            "confidence": 0.65 + (i % 35) / 100.0,  # Confidence between 0.65 and 0.99
                            "source_chunk": f"chunk_{(i % num_chunks) + 1:05d}",
                            "extraction_method": "production_nlp",
                            "validation_score": 0.8 + (i % 20) / 100.0
                        }
                        key_entities.append(entity)
                    
                    # Create comprehensive production metadata
                    processing_metadata = {
                        "chunk_count": num_chunks,
                        "entity_count": num_entities,
                        "total_tokens": sum(chunk.token_count for chunk in chunks),
                        "processing_time": chunk_creation_time,
                        "production_scale_test": True,
                        "performance_benchmark": f"{num_chunks}_chunks_{num_entities}_entities",
                        "memory_baseline_mb": initial_memory,
                        "processing_stage": "production_validation",
                        "quality_score": 0.94,
                        "compliance_validated": True,
                        "security_scan_passed": True,
                        "performance_tier": "production",
                        "scalability_tested": True
                    }
                    
                    # Create production-grade document embedding
                    embedding_size = 1024  # Larger embedding for production quality
                    document_embedding = np.random.rand(embedding_size).astype(np.float32)
                    
                    # When - create production-scale document
                    doc_start_time = time.time()
                    
                    large_document = LLMDocument(
                        document_id="prod_large_doc_001",
                        title="Production Scale Document Processing Validation Test",
                        chunks=chunks,
                        summary="This comprehensive production validation document contains extensive content for testing system performance under realistic load conditions with full-scale data processing requirements.",
                        key_entities=key_entities,
                        processing_metadata=processing_metadata,
                        document_embedding=document_embedding
                    )
                    
                    doc_creation_time = time.time() - doc_start_time
                    
                    # Monitor memory after document creation
                    post_creation_memory = process.memory_info().rss / 1024 / 1024  # MB
                    memory_usage = post_creation_memory - initial_memory
                    
                    # Then - validate production-scale handling
                    
                    # 1. Production performance validation
                    assert doc_creation_time < 2.0, f"Production document creation exceeded limit: {doc_creation_time:.2f}s (limit: 2.0s)"
                    assert chunk_creation_time < 3.0, f"Production chunk creation exceeded limit: {chunk_creation_time:.2f}s (limit: 3.0s)"
                    
                    # 2. Production memory constraints
                    assert memory_usage < 200, f"Memory usage exceeded production limit: {memory_usage:.1f}MB (limit: 200MB)"
                    
                    # 3. Data integrity validation at production scale
                    assert len(large_document.chunks) == num_chunks, f"Expected {num_chunks} chunks, got {len(large_document.chunks)}"
                    assert len(large_document.key_entities) == num_entities, f"Expected {num_entities} entities, got {len(large_document.key_entities)}"
                    
                    # 4. Production access performance validation
                    access_start_time = time.time()
                    
                    # Validate all chunks are accessible with production performance
                    chunk_ids = [chunk.chunk_id for chunk in large_document.chunks]
                    assert len(chunk_ids) == num_chunks, "All production chunks should be accessible"
                    assert len(set(chunk_ids)) == num_chunks, "All production chunk IDs should be unique"
                    
                    # Validate entity access performance
                    entity_values = [entity["value"] for entity in large_document.key_entities]
                    assert len(entity_values) == num_entities, "All production entities should be accessible"
                    
                    access_time = time.time() - access_start_time
                    assert access_time < 0.5, f"Production data access exceeded limit: {access_time:.2f}s (limit: 0.5s)"
                    
                    # 5. Production iteration performance
                    iteration_start_time = time.time()
                    
                    processed_chunks = 0
                    token_sum = 0
                    for chunk in large_document.chunks:
                        assert isinstance(chunk.content, str), "Production chunk content should be string"
                        assert len(chunk.content) > 50, "Production chunk content should have substantial content"
                        assert chunk.token_count > 0, "Production chunks should have positive token counts"
                        token_sum += chunk.token_count
                        processed_chunks += 1
                    
                    iteration_time = time.time() - iteration_start_time
                    assert processed_chunks == num_chunks, "All production chunks should be iterable"
                    assert iteration_time < 1.0, f"Production iteration exceeded limit: {iteration_time:.2f}s (limit: 1.0s)"
                    
                    # 6. Production memory stability validation
                    gc.collect()  # Force garbage collection
                    post_iteration_memory = process.memory_info().rss / 1024 / 1024  # MB
                    memory_stability = abs(post_iteration_memory - post_creation_memory)
                    assert memory_stability < 50, f"Memory instability detected: {memory_stability:.1f}MB variance (limit: 50MB)"
                    
                    # 7. Production relationship integrity validation
                    relationship_start_time = time.time()
                    
                    all_chunk_ids = {chunk.chunk_id for chunk in large_document.chunks}
                    invalid_relationships = 0
                    total_relationships = 0
                    
                    for chunk in large_document.chunks:
                        for rel_id in chunk.relationships:
                            total_relationships += 1
                            if rel_id not in all_chunk_ids:
                                invalid_relationships += 1
                    
                    relationship_time = time.time() - relationship_start_time
                    assert invalid_relationships == 0, f"Production system has {invalid_relationships} invalid relationships"
                    assert relationship_time < 1.5, f"Production relationship validation exceeded limit: {relationship_time:.2f}s (limit: 1.5s)"
                    
                    # 8. Production-specific quality validations
                    
                    # Page distribution validation
                    page_numbers = [chunk.source_page for chunk in large_document.chunks]
                    unique_pages = len(set(page_numbers))
                    expected_pages = (num_chunks // 20) + 1
                    assert unique_pages >= expected_pages * 0.9, f"Expected ~{expected_pages} pages, got {unique_pages}"
                    
                    # Token distribution validation
                    token_counts = [chunk.token_count for chunk in large_document.chunks]
                    total_tokens = sum(token_counts)
                    avg_tokens = total_tokens / len(token_counts)
                    assert 40 <= avg_tokens <= 65, f"Production average tokens per chunk out of range: {avg_tokens} (expected: 40-65)"
                    assert total_tokens == token_sum, "Token count consistency check failed"
                    
                    # Entity confidence validation for production quality
                    confidences = [entity["confidence"] for entity in large_document.key_entities]
                    avg_confidence = sum(confidences) / len(confidences)
                    assert 0.75 <= avg_confidence <= 0.9, f"Production entity confidence out of range: {avg_confidence} (expected: 0.75-0.9)"
                    
                    # Production semantic type distribution
                    semantic_types = [chunk.semantic_type for chunk in large_document.chunks]
                    text_ratio = semantic_types.count("text") / len(semantic_types)
                    assert 0.6 <= text_ratio <= 0.9, f"Production text chunk ratio out of range: {text_ratio} (expected: 0.6-0.9)"
                    
                    # Production metadata validation
                    assert large_document.processing_metadata["production_scale_test"] == True
                    assert large_document.processing_metadata["quality_score"] >= 0.9
                    assert large_document.processing_metadata["compliance_validated"] == True
                    
                    # 9. Production stress test - rapid repeated access
                    stress_start_time = time.time()
                    for _ in range(100):  # 100 rapid access cycles
                        _ = len(large_document.chunks)
                        _ = len(large_document.key_entities)
                        _ = large_document.document_id
                    stress_time = time.time() - stress_start_time
                    assert stress_time < 0.1, f"Production stress test failed: {stress_time:.3f}s (limit: 0.1s)"
                    
                    # 10. Final production memory validation
                    final_memory = process.memory_info().rss / 1024 / 1024  # MB
                    total_memory_growth = final_memory - initial_memory
                    assert total_memory_growth < 250, f"Total production memory growth exceeded limit: {total_memory_growth:.1f}MB (limit: 250MB)"
                    
                    # Log production performance metrics for monitoring
                    print(f"Production Performance Metrics:")
                    print(f"  Document Creation: {doc_creation_time:.3f}s")
                    print(f"  Memory Usage: {memory_usage:.1f}MB")
                    print(f"  Access Performance: {access_time:.3f}s")
                    print(f"  Iteration Performance: {iteration_time:.3f}s")
                    print(f"  Relationship Validation: {relationship_time:.3f}s")
                    print(f"  Total Memory Growth: {total_memory_growth:.1f}MB")
                    print(f"  Chunks: {num_chunks}, Entities: {num_entities}")
                    print(f"  Average Tokens/Chunk: {avg_tokens:.1f}")
                    print(f"  Average Entity Confidence: {avg_confidence:.3f}")



class TestLLMOptimizerInitialization:
    """Test LLMOptimizer initialization and configuration validation."""

    def test_init_with_default_parameters(self):
        """
        GIVEN default initialization parameters
        WHEN LLMOptimizer is initialized without arguments
        THEN expect:
            - Instance created successfully
            - Default model_name set to "sentence-transformers/all-MiniLM-L6-v2"
            - Default tokenizer_name set to "gpt-3.5-turbo"
            - Default max_chunk_size set to 2048
            - Default chunk_overlap set to 200
            - Default min_chunk_size set to 100
            - All attributes properly initialized
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer
        
        # When - create optimizer with default parameters
        optimizer = LLMOptimizer()
        
        # Then - verify default parameters
        assert hasattr(optimizer, 'model_name'), "Optimizer should have model_name attribute"
        assert hasattr(optimizer, 'tokenizer_name'), "Optimizer should have tokenizer_name attribute"
        assert hasattr(optimizer, 'max_chunk_size'), "Optimizer should have max_chunk_size attribute"
        assert hasattr(optimizer, 'chunk_overlap'), "Optimizer should have chunk_overlap attribute"
        assert hasattr(optimizer, 'min_chunk_size'), "Optimizer should have min_chunk_size attribute"
        
        # Verify default values
        assert optimizer.model_name == "sentence-transformers/all-MiniLM-L6-v2", "Default model_name incorrect"
        assert optimizer.tokenizer_name == "gpt-3.5-turbo", "Default tokenizer_name incorrect"
        assert optimizer.max_chunk_size == 2048, "Default max_chunk_size incorrect"
        assert optimizer.chunk_overlap == 200, "Default chunk_overlap incorrect"
        assert optimizer.min_chunk_size == 100, "Default min_chunk_size incorrect"
        
        # Verify additional attributes are initialized
        assert hasattr(optimizer, 'embedding_model'), "Optimizer should have embedding_model attribute"
        assert hasattr(optimizer, 'tokenizer'), "Optimizer should have tokenizer attribute"
        assert hasattr(optimizer, 'text_processor'), "Optimizer should have text_processor attribute"
        assert hasattr(optimizer, 'chunk_optimizer'), "Optimizer should have chunk_optimizer attribute"

    @pytest.mark.asyncio
    async def test_generate_document_summary_empty_content(self):
        """
        GIVEN structured_text with no extractable text
        WHEN _generate_document_summary is called
        THEN expect:
            - Empty string or default summary returned
            - ValueError raised or graceful handling
            - No processing errors
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer
        
        # Given
        optimizer = LLMOptimizer()
        
        # Test completely empty structured text
        empty_structured_text = {}
        
        # When/Then - should handle empty content gracefully
        try:
            summary = await optimizer._generate_document_summary(empty_structured_text)
            # If no exception, should return empty string or default
            assert isinstance(summary, str), "Summary should be string type"
            assert len(summary.strip()) == 0 or summary.strip().lower() in ["no content", "empty document"], "Should return empty or default summary"
        except ValueError as e:
            # Acceptable to raise ValueError for empty content
            assert "empty" in str(e).lower() or "content" in str(e).lower(), "Error message should indicate empty content issue"
        
        # Test structured text with empty pages
        empty_pages_text = {"pages": []}
        
        try:
            summary = await optimizer._generate_document_summary(empty_pages_text)
            assert isinstance(summary, str), "Summary should be string type"
            assert len(summary.strip()) == 0 or "empty" in summary.lower(), "Should indicate empty content"
        except ValueError:
            # Acceptable to raise ValueError
            pass
        
        # Test structured text with pages but no text content
        no_content_text = {
            "pages": [
                {"page_number": 1, "elements": []},
                {"page_number": 2, "elements": []}
            ]
        }
        
        try:
            summary = await optimizer._generate_document_summary(no_content_text)
            assert isinstance(summary, str), "Summary should be string type"
        except ValueError:
            # Acceptable to raise ValueError
            pass

    @pytest.mark.asyncio
    async def test_generate_document_summary_missing_pages(self):
        """
        GIVEN structured_text missing 'pages' key
        WHEN _generate_document_summary is called
        THEN expect KeyError to be raised
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer
        
        # Given
        optimizer = LLMOptimizer()
        
        # Test structured text missing pages key
        missing_pages_text = {
            "document_metadata": {"title": "Test Document"},
            "content": "Some content but no pages structure"
        }
        
        # When/Then
        with pytest.raises((KeyError, ValueError, AttributeError)) as exc_info:
            await optimizer._generate_document_summary(missing_pages_text)
        
        # Error message should be clear about the issue
        error_message = str(exc_info.value).lower()
        assert any(keyword in error_message for keyword in ["pages", "missing", "key", "structure"]), f"Error message should be descriptive: {error_message}"

    @pytest.mark.asyncio
    async def test_generate_document_summary_keyword_analysis(self):
        """
        GIVEN structured_text with specific keywords and themes
        WHEN _generate_document_summary is called
        THEN expect:
            - Key themes reflected in summary
            - Important keywords included
            - Keyword frequency analysis working
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer
        
        # Given
        optimizer = LLMOptimizer()
        
        # Structured text with specific themes and keywords
        structured_text = {
            "pages": [
                {
                    "page_number": 1,
                    "elements": [
                        {
                            "type": "header",
                            "content": "Machine Learning Research and Development",
                            "metadata": {"level": 1}
                        },
                        {
                            "type": "paragraph",
                            "content": "Machine learning algorithms are revolutionizing artificial intelligence applications. Neural networks provide powerful computational frameworks for pattern recognition and data analysis.",
                            "metadata": {}
                        },
                        {
                            "type": "paragraph", 
                            "content": "Deep learning techniques enable advanced computer vision and natural language processing capabilities. These algorithms demonstrate superior performance in classification and prediction tasks.",
                            "metadata": {}
                        }
                    ],
                    "full_text": "Machine Learning Research and Development. Machine learning algorithms are revolutionizing artificial intelligence applications. Neural networks provide powerful computational frameworks for pattern recognition and data analysis. Deep learning techniques enable advanced computer vision and natural language processing capabilities. These algorithms demonstrate superior performance in classification and prediction tasks."
                },
                {
                    "page_number": 2,
                    "elements": [
                        {
                            "type": "paragraph",
                            "content": "Machine learning research continues to advance with new algorithms and methodologies. Artificial intelligence systems are becoming more sophisticated and capable.",
                            "metadata": {}
                        }
                    ],
                    "full_text": "Machine learning research continues to advance with new algorithms and methodologies. Artificial intelligence systems are becoming more sophisticated and capable."
                }
            ]
        }
        
        # When
        summary = await optimizer._generate_document_summary(structured_text)
        
        # Then - verify keyword analysis and theme extraction
        assert isinstance(summary, str), "Summary should be string type"
        assert len(summary.strip()) > 0, "Summary should not be empty"
        
        # Key themes should be reflected in summary
        key_themes = ["machine learning", "artificial intelligence", "neural networks", "deep learning", "algorithms"]
        themes_found = sum(1 for theme in key_themes if theme.lower() in summary.lower())
        assert themes_found >= 3, f"Summary should contain at least 3 key themes, found {themes_found}"
        
        # Important keywords should be included
        important_keywords = ["machine", "learning", "artificial", "intelligence", "neural", "algorithms"]
        keywords_found = sum(1 for keyword in important_keywords if keyword.lower() in summary.lower())
        assert keywords_found >= 4, f"Summary should contain important keywords, found {keywords_found}/{len(important_keywords)}"
        
        # Summary should be comprehensive but concise
        assert 50 <= len(summary) <= 500, f"Summary length should be reasonable: {len(summary)} characters"
        
        # Should contain meaningful content, not just keywords
        assert "." in summary, "Summary should contain proper sentences"
        assert not summary.lower().startswith("the document"), "Summary should be more specific than generic description"

    @pytest.mark.asyncio
    async def test_generate_document_summary_sentence_selection(self):
        """
        GIVEN structured_text with various sentence types
        WHEN _generate_document_summary is called
        THEN expect:
            - Most informative sentences selected
            - Positional importance considered
            - Sentence coherence maintained
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer
        
        # Given
        optimizer = LLMOptimizer()
        
        # Structured text with varying sentence importance
        structured_text = {
            "pages": [
                {
                    "page_number": 1,
                    "elements": [
                        {
                            "type": "header",
                            "content": "Introduction to Advanced Computing Systems",
                            "metadata": {"level": 1}
                        },
                        {
                            "type": "paragraph",
                            "content": "This document presents a comprehensive analysis of distributed computing architectures. The research investigates performance optimization techniques for large-scale data processing. Modern computing systems require efficient resource allocation and management strategies.",
                            "metadata": {}
                        },
                        {
                            "type": "paragraph",
                            "content": "The weather today is nice. Additionally, the methodology employed in this study demonstrates significant improvements in system throughput. However, lunch was served at noon.",
                            "metadata": {}
                        }
                    ],
                    "full_text": "Introduction to Advanced Computing Systems. This document presents a comprehensive analysis of distributed computing architectures. The research investigates performance optimization techniques for large-scale data processing. Modern computing systems require efficient resource allocation and management strategies. The weather today is nice. Additionally, the methodology employed in this study demonstrates significant improvements in system throughput. However, lunch was served at noon."
                }
            ]
        }
        
        # When
        summary = await optimizer._generate_document_summary(structured_text)
        
        # Then - verify sentence selection quality
        assert isinstance(summary, str), "Summary should be string type"
        assert len(summary.strip()) > 0, "Summary should not be empty"
        
        # Should select informative sentences over trivial ones
        informative_phrases = ["computing", "analysis", "performance", "optimization", "systems", "methodology"]
        trivial_phrases = ["weather", "lunch", "noon", "nice"]
        
        informative_count = sum(1 for phrase in informative_phrases if phrase.lower() in summary.lower())
        trivial_count = sum(1 for phrase in trivial_phrases if phrase.lower() in summary.lower())
        
        assert informative_count >= 3, f"Summary should contain informative content, found {informative_count} informative phrases"
        assert trivial_count <= 1, f"Summary should avoid trivial content, found {trivial_count} trivial phrases"
        
        # Should prioritize header and introductory content
        assert "computing" in summary.lower() or "systems" in summary.lower(), "Summary should include header themes"
        
        # Should maintain sentence coherence
        sentences = summary.split('.')
        meaningful_sentences = [s.strip() for s in sentences if len(s.strip()) > 10]
        assert len(meaningful_sentences) >= 1, "Summary should contain at least one meaningful sentence"
        
        # Should consider positional importance (headers, first sentences)
        if "introduction" in summary.lower() or "comprehensive" in summary.lower():
            assert True  # Good - selected important introductory content
        else:
            # Should still contain substantive content even if not positionally biased
            assert any(phrase in summary.lower() for phrase in ["computing", "performance", "optimization", "methodology"])
            
        # Verify sentence boundaries are preserved
        assert not summary.endswith(" "), "Summary should not end with trailing space"
        assert summary.count(". ") <= summary.count("."), "Sentence boundaries should be clean"



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
        
        # Valid decomposed content
        decomposed_content = {
            "pages": [
                {
                    "page_number": 1,
                    "elements": [
                        {"type": "paragraph", "content": "First paragraph content", "metadata": {}},
                        {"type": "paragraph", "content": "Second paragraph content", "metadata": {}}
                    ]
                }
            ],
            "metadata": {"document_id": "test_doc"}
        }
        
        # When
        chunks = await optimizer._create_optimal_chunks(structured_text, decomposed_content)
        
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
            assert isinstance(chunk.semantic_type, str), f"Chunk {i} should have semantic type"
            assert isinstance(chunk.relationships, list), f"Chunk {i} should have relationships list"
            assert isinstance(chunk.metadata, dict), f"Chunk {i} should have metadata dict"

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
        
        decomposed_content = {
            "pages": [{"page_number": 1, "elements": [{"type": "paragraph", "content": large_content, "metadata": {}}]}],
            "metadata": {"document_id": "large_test_doc"}
        }
        
        # When
        chunks = await optimizer._create_optimal_chunks(structured_text, decomposed_content)
        
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
            
            decomposed_content = {
                "pages": [
                    {
                        "page_number": 1,
                        "elements": [
                            {"type": "paragraph", "content": "Page 1 paragraph 1", "metadata": {}},
                            {"type": "paragraph", "content": "Page 1 paragraph 2", "metadata": {}}
                        ]
                    },
                    {
                        "page_number": 2,
                        "elements": [
                            {"type": "paragraph", "content": "Page 2 paragraph 1", "metadata": {}},
                            {"type": "table", "content": "Page 2 table", "metadata": {}}
                        ]
                    },
                    {
                        "page_number": 3,
                        "elements": [
                            {"type": "paragraph", "content": "Page 3 paragraph", "metadata": {}}
                        ]
                    }
                ],
                "metadata": {"document_id": "multi_page_test_doc"}
            }
            
            # When
            chunks = await optimizer._create_optimal_chunks(structured_text, decomposed_content)
            
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
            table_chunks = [chunk for chunk in chunks if chunk.semantic_type == "table" or "table" in chunk.content.lower()]
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
        
        decomposed_content = {
            "pages": [
                {
                    "page_number": 1,
                    "elements": [
                        {"type": "header", "content": "Document Title", "metadata": {}},
                        {"type": "paragraph", "content": "Intro paragraph", "metadata": {}},
                        {"type": "table", "content": "Table content", "metadata": {}},
                        {"type": "paragraph", "content": "Analysis paragraph", "metadata": {}},
                        {"type": "figure_caption", "content": "Figure caption", "metadata": {}}
                    ]
                }
            ],
            "metadata": {"document_id": "semantic_test_doc"}
        }
        
        # When
        chunks = await optimizer._create_optimal_chunks(structured_text, decomposed_content)
        
        # Then - verify semantic grouping
        assert isinstance(chunks, list), "Should return list of chunks"
        assert len(chunks) > 0, "Should create chunks for semantic content"
        
        # Verify semantic types are preserved
        semantic_types_found = {chunk.semantic_type for chunk in chunks}
        expected_types = {"text", "table", "header", "mixed", "figure_caption"}
        
        # At least some semantic types should be represented
        assert len(semantic_types_found) > 0, "Should have semantic type classification"
        assert all(st in expected_types for st in semantic_types_found), f"Unexpected semantic types: {semantic_types_found - expected_types}"
        
        # Verify logical grouping - related elements should be near each other
        header_chunks = [c for c in chunks if "title" in c.content.lower() or c.semantic_type == "header"]
        table_chunks = [c for c in chunks if "table" in c.content.lower() or c.semantic_type == "table"]
        
        if header_chunks:
            # Header content should be preserved with appropriate semantic type
            header_chunk = header_chunks[0]
            assert header_chunk.semantic_type in ["header", "text", "mixed"], f"Header chunk has unexpected type: {header_chunk.semantic_type}"
        
        if table_chunks:
            # Table content should be preserved with appropriate semantic type
            table_chunk = table_chunks[0]
            assert table_chunk.semantic_type in ["table", "mixed"], f"Table chunk has unexpected type: {table_chunk.semantic_type}"
        
        # Verify source element information is preserved
        for chunk in chunks:
            assert isinstance(chunk.source_element, str), "Source element should be string"
            assert len(chunk.source_element) > 0, "Source element should not be empty"
        
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
                
                empty_decomposed_content = {
                    "pages": [],
                    "metadata": {"document_id": "empty_doc"}
                }
                
                # When
                chunks = await optimizer._create_optimal_chunks(empty_structured_text, empty_decomposed_content)
                
                # Then
                assert isinstance(chunks, list), "Should return list even for empty content"
                assert len(chunks) == 0, "Should return empty list for empty content"
                
                # Test structured text with empty pages
                structured_text_empty_pages = {
                    "pages": [
                        {"page_number": 1, "elements": [], "full_text": ""},
                        {"page_number": 2, "elements": [], "full_text": ""}
                    ]
                }
                
                decomposed_content_empty_pages = {
                    "pages": [
                        {"page_number": 1, "elements": []},
                        {"page_number": 2, "elements": []}
                    ],
                    "metadata": {"document_id": "empty_pages_doc"}
                }
                
                # When
                chunks = await optimizer._create_optimal_chunks(structured_text_empty_pages, decomposed_content_empty_pages)
                
                # Then
                assert isinstance(chunks, list), "Should return list for empty pages"
                assert len(chunks) == 0, "Should return empty list for pages with no content"
                
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
                
                decomposed_content_no_content = {
                    "pages": [
                        {
                            "page_number": 1,
                            "elements": [
                                {"type": "header", "content": "", "metadata": {}},
                                {"type": "paragraph", "content": "   ", "metadata": {}},
                                {"type": "table", "content": "\n\t", "metadata": {}}
                            ]
                        }
                    ],
                    "metadata": {"document_id": "no_content_doc"}
                }
                
                # When
                chunks = await optimizer._create_optimal_chunks(structured_text_no_content, decomposed_content_no_content)
                
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
                
                decomposed_content_none_content = {
                    "pages": [
                        {
                            "page_number": 1,
                            "elements": [
                                {"type": "paragraph", "content": None, "metadata": {}},
                                {"type": "header", "content": "", "metadata": {}}
                            ]
                        }
                    ],
                    "metadata": {"document_id": "none_content_doc"}
                }
                
                # When/Then - should handle None content gracefully
                try:
                    chunks = await optimizer._create_optimal_chunks(structured_text_none_content, decomposed_content_none_content)
                    assert isinstance(chunks, list), "Should return list even with None content"
                    assert len(chunks) == 0, "Should return empty list for None content"
                except (TypeError, AttributeError) as e:
                    # These exceptions are acceptable for None content
                    error_msg = str(e).lower()
                    assert any(keyword in error_msg for keyword in ["none", "null", "content", "attribute"]), f"Error should mention None/null issue: {e}"
                
                # Test with malformed page structure
                malformed_structured_text = {
                    "pages": [
                        {"page_number": 1},  # Missing elements
                        {"elements": [], "full_text": ""},  # Missing page_number
                        None  # None page
                    ]
                }
                
                malformed_decomposed_content = {
                    "pages": [
                        {"page_number": 1},
                        {"elements": []},
                        None
                    ],
                    "metadata": {"document_id": "malformed_doc"}
                }
                
                # When/Then - should handle malformed structure gracefully
                try:
                    chunks = await optimizer._create_optimal_chunks(malformed_structured_text, malformed_decomposed_content)
                    assert isinstance(chunks, list), "Should return list for malformed structure"
                    # May return empty or partial results depending on implementation
                except (KeyError, TypeError, AttributeError) as e:
                    # These exceptions are acceptable for malformed structure
                    error_msg = str(e).lower()
                    assert any(keyword in error_msg for keyword in ["key", "missing", "page", "elements", "attribute"]), f"Error should mention structural issue: {e}"
                
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
                
                decomposed_content_tiny = {
                    "pages": [
                        {
                            "page_number": 1,
                            "elements": [
                                {"type": "paragraph", "content": "Hi", "metadata": {}}
                            ]
                        }
                    ],
                    "metadata": {"document_id": "tiny_doc"}
                }
                
                # When
                chunks = await optimizer._create_optimal_chunks(structured_text_tiny, decomposed_content_tiny)
                
                # Then - should handle very short content appropriately
                assert isinstance(chunks, list), "Should return list for tiny content"
                # Implementation may create chunk despite being below min_chunk_size, or return empty list
                if len(chunks) > 0:
                    assert all(isinstance(chunk, optimizer.LLMChunk) for chunk in chunks), "All items should be LLMChunk instances"
                    assert all(len(chunk.content.strip()) > 0 for chunk in chunks), "All chunks should have some content"
                # Empty list is also acceptable for content below threshold


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
        
        chunk_id = "chunk_001"
        page_num = 1
        metadata = {
            "element_type": "paragraph",
            "element_id": "p1",
            "section": "introduction", 
            "confidence": 0.95,
            "source_file": "test_document.pdf",
            "extraction_method": "text_analysis"
        }
        
        # When
        chunk = await optimizer._create_chunk(content, chunk_id, page_num, metadata)
        
        # Then - verify LLMChunk instance and basic structure
        assert isinstance(chunk, LLMChunk), "Should return LLMChunk instance"
        assert chunk.id == chunk_id, f"Expected chunk ID '{chunk_id}', got '{chunk.id}'"
        assert chunk.content == content, "Content should match input exactly"
        assert chunk.page_number == page_num, f"Expected page number {page_num}, got {chunk.page_number}"
        
        # Verify token count calculation
        assert isinstance(chunk.token_count, int), "Token count should be integer"
        assert chunk.token_count > 0, "Token count should be positive for non-empty content"
        
        # Rough validation - content has ~50 words, should be reasonable token count
        word_count = len(content.split())
        assert 30 <= chunk.token_count <= word_count * 2, f"Token count {chunk.token_count} seems unreasonable for {word_count} words"
        
        # Verify semantic type determination
        assert chunk.semantic_type is not None, "Semantic type should be determined"
        assert isinstance(chunk.semantic_type, str), "Semantic type should be string"
        assert len(chunk.semantic_type) > 0, "Semantic type should not be empty"
        
        # Common semantic types for paragraph content
        expected_semantic_types = ["text", "paragraph", "content", "mixed", "narrative"]
        assert chunk.semantic_type in expected_semantic_types, f"Unexpected semantic type: {chunk.semantic_type}"
        
        # Verify source element
        assert chunk.source_element is not None, "Source element should be populated"
        assert isinstance(chunk.source_element, str), "Source element should be string"
        
        # Verify metadata enhancement
        assert chunk.metadata is not None, "Metadata should be present"
        assert isinstance(chunk.metadata, dict), "Metadata should be dictionary"
        
        # Original metadata should be preserved
        for key, value in metadata.items():
            assert key in chunk.metadata, f"Original metadata key '{key}' should be preserved"
            assert chunk.metadata[key] == value, f"Metadata value for '{key}' should be preserved"
        
        # Additional metadata may be added by the method
        # Verify enhanced metadata fields that might be added
        possible_enhanced_fields = ["creation_timestamp", "processing_method", "chunk_position", "content_hash"]
        for field in possible_enhanced_fields:
            if field in chunk.metadata:
                assert chunk.metadata[field] is not None, f"Enhanced field '{field}' should have value if present"
        
        # Verify chunk coherence
        assert not chunk.content.startswith(" "), "Content should not start with whitespace"
        assert not chunk.content.endswith(" "), "Content should not end with whitespace"
        assert len(chunk.content.strip()) == len(chunk.content), "Content should be properly trimmed"
        @pytest.mark.asyncio
        async def test_create_chunk_empty_content(self):
            """
            GIVEN empty content string
            WHEN _create_chunk is called
            THEN expect ValueError to be raised
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
            
            chunk_id = "chunk_001"
            page_num = 1
            metadata = {"element_type": "paragraph"}
            
            # When/Then - test each empty content case
            for empty_content in empty_content_cases:
                with pytest.raises((ValueError, TypeError, AttributeError)) as exc_info:
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
    async def test_create_chunk_semantic_type_determination(self):
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
                "metadata": {"element_type": "header", "level": 1},
                "expected_type": "header",
                "description": "Header element with clear header indicators"
            },
            
            # Table content should be classified as table
            {
                "content": "Table 1: Results\nMethod A: 95%\nMethod B: 87%\nMethod C: 92%",
                "metadata": {"element_type": "table", "table_id": "table_1"},
                "expected_type": "table",
                "description": "Table element with tabular data structure"
            },
            
            # Figure caption should be classified as figure_caption
            {
                "content": "Figure 2: Neural network architecture showing input, hidden, and output layers.",
                "metadata": {"element_type": "figure_caption", "figure_id": "fig_2"},
                "expected_type": "figure_caption",
                "description": "Figure caption with descriptive content"
            },
            
            # Mixed content (contains both text and table-like elements)
            {
                "content": "The following table shows results:\nMethod A: 95%\nMethod B: 87%\nThis demonstrates clear performance differences.",
                "metadata": {"element_type": "paragraph", "contains_table": True},
                "expected_type": "mixed",
                "description": "Mixed content with both narrative and tabular elements"
            },
            
            # Regular paragraph text
            {
                "content": "This is a standard paragraph containing narrative text without any special formatting or tabular data.",
                "metadata": {"element_type": "paragraph", "section": "body"},
                "expected_type": "text",
                "description": "Standard paragraph text content"
            },
            
            # Content with table-like keywords but in text format
            {
                "content": "The research table of contents includes methodology, results, and discussion sections.",
                "metadata": {"element_type": "paragraph"},
                "expected_type": "text",
                "description": "Text content with table keywords but not actual table"
            },
            
            # Content with header-like keywords but not actual header
            {
                "content": "The chapter discusses various header compression techniques used in network protocols.",
                "metadata": {"element_type": "paragraph"},
                "expected_type": "text",
                "description": "Text content mentioning headers but not actual header"
            }
        ]
        
        # Test priority hierarchy: header > table > figure_caption > mixed > text
        priority_test_cases = [
            # Header with table content should prioritize header
            {
                "content": "Chapter 1: Results Table\nMethod A: 95%\nMethod B: 87%",
                "metadata": {"element_type": "header", "level": 1, "contains_table": True},
                "expected_type": "header",
                "description": "Header priority over table content"
            },
            
            # Table with figure reference should prioritize table
            {
                "content": "Table 1: Performance metrics (see Figure 2)\nMethod A: 95%\nMethod B: 87%",
                "metadata": {"element_type": "table", "references_figure": True},
                "expected_type": "table",
                "description": "Table priority over figure references"
            },
            
            # Figure caption with table data should prioritize figure_caption
            {
                "content": "Figure 1: Data table showing Method A: 95%, Method B: 87%",
                "metadata": {"element_type": "figure_caption", "contains_data": True},
                "expected_type": "figure_caption",
                "description": "Figure caption priority over tabular data"
            }
        ]
        
        all_test_cases = test_cases + priority_test_cases
        
        # When/Then - test each semantic type scenario
        for i, test_case in enumerate(all_test_cases):
            chunk_id = f"chunk_{i+1:03d}"
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
            assert hasattr(chunk, 'semantic_type'), f"Chunk should have semantic_type attribute for test case {i+1}"
            assert isinstance(chunk.semantic_type, str), f"Semantic type should be string for test case {i+1}"
            assert len(chunk.semantic_type) > 0, f"Semantic type should not be empty for test case {i+1}"
            
            # Verify expected semantic type
            actual_type = chunk.semantic_type
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
            chunk_id = f"content_chunk_{i+1:03d}"
            page_num = 1
            
            # When
            chunk = await optimizer._create_chunk(
                test_case["content"], 
                chunk_id, 
                page_num, 
                test_case["metadata"]
            )
            
            # Then - verify semantic type is reasonable based on content
            actual_type = chunk.semantic_type
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
            chunk_id = f"edge_chunk_{i+1:03d}"
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
                actual_type = chunk.semantic_type
                
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
            chunk_id = f"similar_chunk_{i+1:03d}"
            chunk = await optimizer._create_chunk(
                test_case["content"], 
                chunk_id, 
                1, 
                test_case["metadata"]
            )
            semantic_types.append(chunk.semantic_type)
        
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
            "chunk_001",
            "chunk_42",
            "section_1_chunk_5",
            "doc_123_chunk_456",
            
            # Non-standard but valid IDs
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
                
                chunk_id = "chunk_meta_001"
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
                semantic_fields = ["semantic_type", "content_complexity", "readability_score", "language_detected"]
                
                semantic_fields_present = [field for field in semantic_fields if field in chunk.metadata]
                
                for field in semantic_fields_present:
                    semantic_value = chunk.metadata[field]
                    
                    if field == "semantic_type":
                        assert isinstance(semantic_value, str), f"Semantic type should be string"
                        expected_types = ["text", "paragraph", "header", "table", "mixed", "figure_caption"]
                        assert semantic_value in expected_types, f"Semantic type should be recognized: {semantic_value}"
                        # Should match chunk's semantic_type attribute
                        assert semantic_value == chunk.semantic_type, f"Metadata semantic_type should match chunk.semantic_type"
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
        chunk_id = "chunk_token_fail_001"
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
                assert chunk.chunk_id == chunk_id, "Chunk ID should be preserved"
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



class TestLLMOptimizerEstablishChunkRelationships:
    """Test LLMOptimizer._establish_chunk_relationships method."""

    def test_establish_chunk_relationships_sequential(self):
        """
        GIVEN list of sequential chunks
        WHEN _establish_chunk_relationships is called
        THEN expect:
            - Adjacent chunks linked in relationships
            - Sequential order preserved
            - Bidirectional relationships established
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer, LLMChunk
        
        # Given
        optimizer = LLMOptimizer()
        
        sequential_chunks = [
            LLMChunk(
                content="First chunk in sequence",
                chunk_id="chunk_0001",
                source_page=1,
                source_element="paragraph",
                token_count=10,
                semantic_type="text",
                relationships=[],
                metadata={}
            ),
            LLMChunk(
                content="Second chunk follows first",
                chunk_id="chunk_0002",
                source_page=1,
                source_element="paragraph",
                token_count=12,
                semantic_type="text",
                relationships=[],
                metadata={}
            ),
            LLMChunk(
                content="Third chunk completes sequence",
                chunk_id="chunk_0003",
                source_page=1,
                source_element="paragraph",
                token_count=14,
                semantic_type="text",
                relationships=[],
                metadata={}
            )
        ]
        
        # When
        optimizer._establish_chunk_relationships(sequential_chunks)
        
        # Then - verify sequential relationships
        assert sequential_chunks[0].relationships == [], "First chunk should have no predecessors"
        assert "chunk_0001" in sequential_chunks[1].relationships, "Second chunk should reference first"
        assert "chunk_0002" in sequential_chunks[2].relationships, "Third chunk should reference second"
        
        # Verify relationship ordering (most recent first if implemented that way)
        for i in range(1, len(sequential_chunks)):
            current_chunk = sequential_chunks[i]
            if current_chunk.relationships:
                # Should have relationship to previous chunk
                previous_chunk_id = sequential_chunks[i-1].chunk_id
                assert previous_chunk_id in current_chunk.relationships, f"Chunk {current_chunk.chunk_id} should reference {previous_chunk_id}"

    def test_establish_chunk_relationships_same_page(self):
        """
        GIVEN chunks from the same page
        WHEN _establish_chunk_relationships is called
        THEN expect:
            - Same-page chunks linked together
            - Page-level contextual relationships established
            - Cross-page relationships avoided
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer, LLMChunk
        
        # Given
        optimizer = LLMOptimizer()
        
        same_page_chunks = [
            LLMChunk(
                content="First paragraph on page 1",
                chunk_id="chunk_0001",
                source_page=1,
                source_element="paragraph",
                token_count=10,
                semantic_type="text",
                relationships=[],
                metadata={}
            ),
            LLMChunk(
                content="Second paragraph on page 1",
                chunk_id="chunk_0002",
                source_page=1,
                source_element="paragraph",
                token_count=12,
                semantic_type="text",
                relationships=[],
                metadata={}
            ),
            LLMChunk(
                content="Table on page 1",
                chunk_id="chunk_0003",
                source_page=1,
                source_element="table",
                token_count=15,
                semantic_type="table",
                relationships=[],
                metadata={}
            ),
            LLMChunk(
                content="First paragraph on page 2",
                chunk_id="chunk_0004",
                source_page=2,
                source_element="paragraph",
                token_count=11,
                semantic_type="text",
                relationships=[],
                metadata={}
            )
        ]
        
        # When
        optimizer._establish_chunk_relationships(same_page_chunks)
        
        # Then - verify same-page relationships are established
        page_1_chunks = [chunk for chunk in same_page_chunks if chunk.source_page == 1]
        page_2_chunks = [chunk for chunk in same_page_chunks if chunk.source_page == 2]
        
        # Check that page 1 chunks reference each other
        assert "chunk_0001" in same_page_chunks[1].relationships, "Second chunk should reference first chunk (same page)"
        assert "chunk_0002" in same_page_chunks[2].relationships, "Table chunk should reference previous paragraph (same page)"
        
        # Check that page 2 chunk doesn't reference page 1 chunks inappropriately
        page_2_chunk = same_page_chunks[3]
        page_1_chunk_ids = {chunk.chunk_id for chunk in page_1_chunks}
        
        # It should reference the immediately previous chunk (cross-page is allowed for sequential flow)
        if page_2_chunk.relationships:
            # At least some relationship should exist for document flow
            assert len(page_2_chunk.relationships) > 0, "Page 2 chunk should have some relationships for document continuity"
        
        # Verify same-page chunks have stronger relationships
        for i in range(len(page_1_chunks) - 1):
            current_chunk = page_1_chunks[i + 1]
            previous_chunk_id = page_1_chunks[i].chunk_id
            assert previous_chunk_id in current_chunk.relationships, f"Same-page chunk {current_chunk.chunk_id} should reference {previous_chunk_id}"

    def test_establish_chunk_relationships_empty_list(self):
        """
        GIVEN empty chunks list
        WHEN _establish_chunk_relationships is called
        THEN expect:
            - ValueError raised or empty list returned
            - No processing errors
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer
        
        # Given
        optimizer = LLMOptimizer()
        empty_chunks = []
        
        # When/Then - should handle empty list gracefully
        try:
            optimizer._establish_chunk_relationships(empty_chunks)
            # If no error raised, verify list remains empty
            assert len(empty_chunks) == 0, "Empty list should remain empty"
        except ValueError as e:
            # ValueError is acceptable for empty input
            assert "empty" in str(e).lower() or "no chunks" in str(e).lower(), f"Error should mention empty input: {e}"
        except Exception as e:
            pytest.fail(f"Unexpected exception type for empty list: {type(e).__name__}: {e}")

    def test_establish_chunk_relationships_single_chunk(self):
        """
        GIVEN single chunk in list
        WHEN _establish_chunk_relationships is called
        THEN expect:
            - Single chunk returned with empty relationships
            - No errors raised
            - Graceful handling of edge case
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer, LLMChunk
        
        # Given
        optimizer = LLMOptimizer()
        
        single_chunk = [
            LLMChunk(
                content="Single lonely chunk",
                chunk_id="chunk_0001",
                source_page=1,
                source_element="paragraph",
                token_count=10,
                semantic_type="text",
                relationships=[],
                metadata={}
            )
        ]
        
        # When
        optimizer._establish_chunk_relationships(single_chunk)
        
        # Then - single chunk should have no relationships
        assert len(single_chunk) == 1, "Should still have one chunk"
        assert single_chunk[0].relationships == [], "Single chunk should have empty relationships"
        assert single_chunk[0].chunk_id == "chunk_0001", "Chunk ID should be preserved"
        assert single_chunk[0].content == "Single lonely chunk", "Chunk content should be preserved"

    def test_establish_chunk_relationships_performance_limits(self):
        """
        GIVEN large number of chunks
        WHEN _establish_chunk_relationships is called
        THEN expect:
            - Relationship limits applied for performance
            - Processing completes in reasonable time
            - Most important relationships preserved
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer, LLMChunk
        import time
        
        # Given
        optimizer = LLMOptimizer()
        
        # Create large number of chunks (100 chunks)
        large_chunk_list = []
        for i in range(100):
            chunk = LLMChunk(
                content=f"Chunk {i+1} content for performance testing",
                chunk_id=f"chunk_{i+1:04d}",
                source_page=(i // 10) + 1,  # 10 chunks per page
                source_element="paragraph",
                token_count=15,
                semantic_type="text",
                relationships=[],
                metadata={}
            )
            large_chunk_list.append(chunk)
        
        # When - measure performance
        start_time = time.time()
        optimizer._establish_chunk_relationships(large_chunk_list)
        processing_time = time.time() - start_time
        
        # Then - verify performance and relationship quality
        assert processing_time < 5.0, f"Processing 100 chunks took too long: {processing_time:.2f}s"
        
        # Verify some relationships are established
        chunks_with_relationships = [chunk for chunk in large_chunk_list if chunk.relationships]
        assert len(chunks_with_relationships) >= 90, "Most chunks should have relationships established"
        
        # Verify sequential relationships exist (at least for first few chunks)
        for i in range(1, min(10, len(large_chunk_list))):
            current_chunk = large_chunk_list[i]
            previous_chunk_id = large_chunk_list[i-1].chunk_id
            assert previous_chunk_id in current_chunk.relationships, f"Sequential relationship missing for chunk {i+1}"
        
        # Verify relationship limits (no chunk should have excessive relationships)
        max_relationships = max(len(chunk.relationships) for chunk in large_chunk_list)
        assert max_relationships <= 10, f"Relationship limit should be applied, found chunk with {max_relationships} relationships"

    def test_establish_chunk_relationships_malformed_chunks(self):
        """
        GIVEN chunks with missing required attributes
        WHEN _establish_chunk_relationships is called
        THEN expect:
            - AttributeError raised
            - Error handling for malformed data
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer, LLMChunk
        
        # Given
        optimizer = LLMOptimizer()
        
        # Create valid chunk for comparison
        valid_chunk = LLMChunk(
            content="Valid chunk content",
            chunk_id="chunk_0001",
            source_page=1,
            source_element="paragraph",
            token_count=10,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        # Test with chunk missing chunk_id attribute
        malformed_chunk_no_id = LLMChunk(
            content="Chunk without ID",
            chunk_id="",  # Empty ID should cause issues
            source_page=1,
            source_element="paragraph",
            token_count=10,
            semantic_type="text",
            relationships=[],
            metadata={}
        )
        
        # When/Then - test with malformed chunk
        malformed_chunks = [valid_chunk, malformed_chunk_no_id]
        
        try:
            optimizer._establish_chunk_relationships(malformed_chunks)
            # If it doesn't raise an error, verify it handled the malformed chunk gracefully
            assert isinstance(malformed_chunk_no_id.relationships, list), "Relationships should be a list"
        except (AttributeError, ValueError) as e:
            # These are acceptable errors for malformed data
            error_msg = str(e).lower()
            assert any(keyword in error_msg for keyword in ["chunk_id", "attribute", "missing", "invalid"]), f"Error should mention the issue: {e}"
        
        # Test with None in chunk list
        chunks_with_none = [valid_chunk, None]
        
        with pytest.raises((AttributeError, TypeError, ValueError)):
            optimizer._establish_chunk_relationships(chunks_with_none)

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
