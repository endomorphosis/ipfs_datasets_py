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
            source_elements=["text"],
            token_count=5,
            semantic_types={"text"},
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
            source_elements=["text"],
            token_count=5,
            semantic_types={"text"},
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
                document_id=f"doc_{dtype.__name__}",
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
            source_elements=["text"],
            token_count=5,
            semantic_types={"text"},
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
            original_array: np.ndarray
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
            source_elements=["text"],
            token_count=5,
            semantic_types={"text"},
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
