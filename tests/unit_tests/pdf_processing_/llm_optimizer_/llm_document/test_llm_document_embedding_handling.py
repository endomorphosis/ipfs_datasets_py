#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer.py
# Auto-generated on 2025-07-07 02:28:56"
import os


import pytest
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

from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_document.llm_document_factory import (
    LLMDocumentTestDataFactory
)


# Check if each classes methods are accessible:
assert LLMOptimizer._initialize_models, "LLMOptimizer._initialize_models method should be accessible"
assert LLMOptimizer.optimize_for_llm, "LLMOptimizer.optimize_for_llm method should be accessible"
assert LLMOptimizer._extract_structured_text, "LLMOptimizer._extract_structured_text method should be accessible"
assert LLMOptimizer._generate_document_summary, "LLMOptimizer._generate_document_summary method should be accessible"
assert LLMOptimizer._create_optimal_chunks, "LLMOptimizer._create_optimal_chunks method should be accessible"
assert LLMOptimizer._create_chunk, "LLMOptimizer._create_chunk method should be accessible"
assert LLMOptimizer._establish_chunk_relationships, "LLMOptimizer._establish_chunk_relationships method should be accessible"
assert LLMOptimizer._generate_embeddings, "LLMOptimizer._generate_embeddings method should be accessible"
assert LLMOptimizer._extract_key_entities, "LLMOptimizer._extract_key_entities method should be accessible"
assert LLMOptimizer._generate_document_embedding, "LLMOptimizer._generate_document_embedding method should be accessible"
assert LLMOptimizer._count_tokens, "LLMOptimizer._count_tokens method should be accessible"
assert LLMOptimizer._get_chunk_overlap, "LLMOptimizer._get_chunk_overlap method should be accessible"
assert TextProcessor.split_sentences, "TextProcessor.split_sentences method should be accessible"
assert TextProcessor.extract_keywords, "TextProcessor.extract_keywords method should be accessible"
assert ChunkOptimizer.optimize_chunk_boundaries, "ChunkOptimizer.optimize_chunk_boundaries method should be accessible"


# 4. Check if the modules's imports are accessible:
try:
    import anyio
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


@pytest.mark.parametrize("shape", [
    (5,),           # 1D vector
    (10,),          # Different 1D size
    (3, 4),         # 2D matrix
    (2, 3, 4),      # 3D tensor
    (1, 384),       # Common embedding dimension
    (768,),         # Another common embedding size
])
class TestLLMDocumentEmbeddingShapePreservation:

    def test_document_embedding_shape_preservation(self, shape):
        """
        GIVEN numpy array with specific shape as document_embedding
        WHEN LLMDocument is instantiated and accessed
        THEN expect original array shape preserved
        """
        # Create array with specific shape
        original_array = np.random.rand(*shape).astype(np.float32)
        document = LLMDocumentTestDataFactory.create_document_instance(
            document_embedding=original_array
        )
        # When/Then - verify shape preservation
        assert document.document_embedding.shape == shape, f"Shape {shape} not preserved, got {document.document_embedding.shape}"

    def test_document_embedding_shape_matches_original(self, shape):
        """
        GIVEN numpy array with specific shape as document_embedding
        WHEN LLMDocument is instantiated and accessed
        THEN expect shape matches original array shape
        """
        # Create array with specific shape
        original_array = np.random.rand(*shape).astype(np.float32)
        document = LLMDocumentTestDataFactory.create_document_instance(
            document_embedding=original_array
        )
        # When/Then - verify shape matches original
        assert document.document_embedding.shape == original_array.shape, "Shape should match original array"

    def test_document_embedding_values_unchanged(self, shape):
        """
        GIVEN numpy array with specific shape as document_embedding
        WHEN LLMDocument is instantiated and accessed
        THEN expect array values remain unchanged
        """
        # Create array with specific shape
        original_array = np.random.rand(*shape).astype(np.float32)
        document = LLMDocumentTestDataFactory.create_document_instance(
            document_embedding=original_array
        )
        # When/Then - verify values unchanged
        assert np.array_equal(document.document_embedding, original_array), f"Array values changed for shape {shape}"


class TestLLMDocumentEmbeddingHandling:
    """Test LLMDocument document-level embedding handling."""

    def test_document_embedding_empty_array_shape_preservation(self):
        """
        GIVEN numpy array with empty shape as document_embedding
        WHEN LLMDocument is instantiated and accessed
        THEN expect empty array shape preserved
        """
        empty_array = np.array([], dtype=np.float32)
        document_empty = LLMDocumentTestDataFactory.create_document_instance(document_embedding=empty_array)

        assert document_empty.document_embedding.shape == (0,), f"Empty array shape (0,) should be preserved, got {document_empty.document_embedding.shape}"

    def test_document_embedding_empty_array_size_preservation(self):
        """
        GIVEN numpy array with empty shape as document_embedding
        WHEN LLMDocument is instantiated and accessed
        THEN expect empty array size preserved
        """
        empty_array = np.array([], dtype=np.float32)
        document_empty = LLMDocumentTestDataFactory.create_document_instance(document_embedding=empty_array)

        assert document_empty.document_embedding.size == 0, f"Empty array should have size 0, got {document_empty.document_embedding.size}"

    @pytest.mark.parametrize("dtype", [
        np.float32,     # Common embedding dtype
        np.float64,     # Higher precision float
        np.float16,     # Lower precision float
        np.int32,       # 32-bit integer
        np.int64,       # 64-bit integer
        np.bool_,       # Boolean dtype
    ])
    def test_document_embedding_dtype_preservation(self, dtype):
        """
        GIVEN numpy array with arbitrary dtype as document_embedding
        WHEN LLMDocument is instantiated and accessed
        THEN expect dtype to be preserved
        """
        test_data = [0.1, 0.2, 0.3, 0.4, 0.5]
        original_array = np.array(test_data, dtype=dtype)
        
        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=original_array)
        
        assert document.document_embedding.dtype == dtype, f"Dtype '{dtype}' should be preserved, got {document.document_embedding.dtype}"

    @pytest.mark.parametrize("dtype,rtol", [
        (np.float32, 1e-6),     # Common embedding dtype
        (np.float64, 1e-15),    # Higher precision float
        (np.float16, 1e-3),     # Lower precision float
    ])
    def test_document_embedding_float_values_preserved(self, dtype, rtol):
        """
        GIVEN numpy array with float32 values as document_embedding
        WHEN LLMDocument is instantiated and accessed
        THEN expect float32 values preserved within precision
        """
        test_data = [0.1, 0.2, 0.3, 0.4, 0.5]
        original_array = np.array(test_data, dtype=dtype)
        
        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=original_array)
        
        assert np.allclose(document.document_embedding, original_array, rtol=rtol), f"'{dtype}' values not preserved within tolerance '{rtol}', got '{document.document_embedding}' compared to '{original_array}'"

    @pytest.mark.parametrize("dtype", [
        np.int32,       # 32-bit integer
        np.int64,       # 64-bit integer
    ])
    def test_document_embedding_int_values_preserved(self, dtype):
        """
        GIVEN numpy array with int32 values as document_embedding
        WHEN LLMDocument is instantiated and accessed
        THEN expect int32 values preserved exactly
        """
        test_data = [1, 2, 3, 4, 5]
        original_array = np.array(test_data, dtype=dtype)
        
        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=original_array)
        
        assert np.array_equal(document.document_embedding, original_array), f"'{dtype}' values not preserved, got '{document.document_embedding}' compared to '{original_array}'"

    def test_document_embedding_bool_values_preserved(self):
        """
        GIVEN numpy array with bool values as document_embedding
        WHEN LLMDocument is instantiated and accessed
        THEN expect bool values preserved exactly
        """
        test_data = [True, False, True, False]
        bool_array = np.array(test_data, dtype=np.bool_)
        
        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=bool_array)

        assert np.array_equal(document.document_embedding, bool_array), f"'bool_' values not preserved, got '{document.document_embedding}' compared to '{bool_array}'"

    @pytest.mark.parametrize("test_array", [
        np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float32),
        np.array([1e-8, 2e-8, 3e-8], dtype=np.float64),
        np.array([1e8, 2e8, 3e8], dtype=np.float64),
        np.array([-1.5, 0.0, 1.5, -2.5, 2.5], dtype=np.float32),
        np.array([0.123456789, 0.987654321, 0.555555555], dtype=np.float64),
        np.array([10, 20, 30, 40, 50], dtype=np.int32),
    ])
    def test_document_embedding_values_preserved(self, test_array):
        """
        GIVEN numpy array with specific values as document_embedding
        WHEN LLMDocument is instantiated and accessed
        THEN expect values are preserved exactly
        """
        expected_values = test_array.copy()
        
        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=test_array)
        
        assert np.array_equal(document.document_embedding, expected_values), "Document embedding values should match expected values"

    @pytest.mark.parametrize("test_array", [
        np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float32),
        np.array([1e-8, 2e-8, 3e-8], dtype=np.float64),
        np.array([1e8, 2e8, 3e8], dtype=np.float64),
        np.array([-1.5, 0.0, 1.5, -2.5, 2.5], dtype=np.float32),
        np.array([0.123456789, 0.987654321, 0.555555555], dtype=np.float64),
        np.array([10, 20, 30, 40, 50], dtype=np.int32),
    ])
    def test_document_embedding_dtype_preserved_after_instantiation(self, test_array):
        """
        GIVEN numpy array with specific dtype as document_embedding
        WHEN LLMDocument is instantiated
        THEN expect dtype is preserved
        """
        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=test_array)
        assert document.document_embedding.dtype == test_array.dtype, f"Document embedding dtype should match test array dtype, expected {test_array.dtype}, got {document.document_embedding.dtype}"

    @pytest.mark.parametrize("test_array,rtol,atol", [
        (np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float32), 1e-6, 1e-6),
        (np.array([1e-8, 2e-8, 3e-8], dtype=np.float64), 1e-15, 1e-15),
        (np.array([1e8, 2e8, 3e8], dtype=np.float64), 1e-9, 1e-9),
        (np.array([-1.5, 0.0, 1.5, -2.5, 2.5], dtype=np.float32), 1e-6, 1e-6),
        (np.array([0.123456789, 0.987654321, 0.555555555], dtype=np.float64), 1e-15, 1e-15),
    ])
    def test_document_embedding_float_precision_preserved(self, test_array, rtol, atol):
        """
        GIVEN numpy array with floating point values as document_embedding
        WHEN LLMDocument is instantiated
        THEN expect float precision is preserved within tolerance
        """
        expected_values = test_array.copy()
        
        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=test_array)
        
        assert np.allclose(document.document_embedding, expected_values, rtol=rtol, atol=atol), f"Document embedding values should match expected values within tolerance for {test_array.dtype}"

    @pytest.mark.parametrize("test_array", [
        np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float32),
        np.array([1e-8, 2e-8, 3e-8], dtype=np.float64),
        np.array([1e8, 2e8, 3e8], dtype=np.float64),
        np.array([-1.5, 0.0, 1.5, -2.5, 2.5], dtype=np.float32),
        np.array([0.123456789, 0.987654321, 0.555555555], dtype=np.float64),
    ])
    def test_document_embedding_stores_copy_not_reference_float(self, test_array):
        """
        GIVEN numpy float array as document_embedding
        WHEN original array is modified after document creation
        THEN expect document embedding remains unchanged (proving it's a copy)
        """
        expected_values = test_array.copy()
        
        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=test_array)
        
        # Modify the original array
        test_array = 999.999
        
        assert np.array_equal(document.document_embedding, expected_values), "Document embedding should remain unchanged when original array is modified (proving it's a copy)"

    @pytest.mark.parametrize("test_array", [
        np.array([10, 20, 30, 40, 50], dtype=np.int32),
    ])
    def test_document_embedding_stores_copy_not_reference_int(self, test_array):
        """
        GIVEN numpy integer array as document_embedding
        WHEN original array is modified after document creation
        THEN expect document embedding remains unchanged (proving it's a copy)
        """
        expected_values = test_array.copy()

        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=test_array)
        
        # Modify the original array
        test_array = 999
        
        assert np.array_equal(document.document_embedding, expected_values), "Document embedding should remain unchanged when original array is modified (proving it's a copy for integer arrays)"

    @pytest.mark.parametrize("test_array,test_id", [
        (np.array([1.0, 2.0, 3.0, 4.0, 5.0], dtype=np.float32), "basic_values"),
        (np.array([1e-8, 2e-8, 3e-8], dtype=np.float64), "small_values"),
        (np.array([1e8, 2e8, 3e8], dtype=np.float64), "large_values"),
        (np.array([-1.5, 0.0, 1.5, -2.5, 2.5], dtype=np.float32), "mixed_values"),
        (np.array([0.123456789, 0.987654321, 0.555555555], dtype=np.float64), "high_precision"),
    ])
    def test_document_embedding_first_element_unchanged_after_float_modification(self, test_array, test_id):
        """
        GIVEN numpy float array as document_embedding
        WHEN original array's first element is modified after document creation
        THEN expect document embedding's first element remains unchanged
        """
        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=test_array)
        
        # Modify the original array
        modified_number = 999
        test_array[0] = modified_number
        
        assert document.document_embedding[0] != modified_number, f"document_embedding[0] should remain unchanged after input was modified to '{modified_number}', got {document.document_embedding[0]}"

    @pytest.mark.parametrize("test_array", [
        np.array([10, 20, 30, 40, 50], dtype=np.int32),
    ])
    def test_document_embedding_first_element_unchanged_after_int_modification(self, test_array):
        """
        GIVEN numpy integer array as document_embedding
        WHEN original array's first element is modified after document creation
        THEN expect document embedding's first element remains unchanged
        """
        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=test_array)

        # Modify the original array
        modified_number = 999
        test_array = modified_number

        assert document.document_embedding[0] != modified_number, f"document_embedding[0] should remain unchanged after input was modified to '{modified_number}', got {document.document_embedding[0]}"

    def test_document_embedding_nan_value_preserved(self):
        """
        GIVEN numpy array containing NaN as document_embedding
        WHEN LLMDocument is instantiated
        THEN expect NaN value is preserved
        """
        special_values = np.array([np.nan, np.inf, -np.inf, 0.0, 1.0], dtype=np.float64)
        
        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=special_values)
        
        assert np.isnan(document.document_embedding[0]) == True, f"NaN value should be preserved in document embedding, got {document.document_embedding[0]}"

    def test_document_embedding_positive_infinity_preserved(self):
        """
        GIVEN numpy array containing positive infinity as document_embedding
        WHEN LLMDocument is instantiated
        THEN expect positive infinity value is preserved
        """
        special_values = np.array([np.nan, np.inf, -np.inf, 0.0, 1.0], dtype=np.float64)

        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=special_values)

        assert np.isinf(document.document_embedding[1]) == True, f"Positive infinity value should be preserved in document embedding, got {document.document_embedding[1]}"

    def test_document_embedding_positive_value_preserved(self):
        """
        GIVEN numpy array containing positive value as document_embedding
        WHEN LLMDocument is instantiated
        THEN expect positive value is preserved
        """
        special_values = np.array([np.nan, np.inf, -np.inf, 0.0, 1.0], dtype=np.float64)

        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=special_values)

        assert document.document_embedding[1] > 0, f"Positive value should be preserved in document embedding, got {document.document_embedding[1]}"

    def test_document_embedding_negative_infinity_preserved(self):
        """
        GIVEN numpy array containing negative infinity as document_embedding
        WHEN LLMDocument is instantiated
        THEN expect negative infinity value is preserved
        """
        special_values = np.array([np.nan, np.inf, -np.inf, 0.0, 1.0], dtype=np.float64)

        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=special_values)

        assert np.isinf(document.document_embedding[2]) == True, f"Negative infinity value should be preserved in document embedding, got {document.document_embedding[2]}"

    def test_document_embedding_negative_value_preserved(self):
        """
        GIVEN numpy array containing negative value as document_embedding
        WHEN LLMDocument is instantiated
        THEN expect negative value is preserved
        """
        special_values = np.array([np.nan, np.inf, -np.inf, 0.0, 1.0], dtype=np.float64)

        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=special_values)

        assert document.document_embedding[2] < 0, f"Negative value should be preserved in document embedding, got {document.document_embedding[2]}"

    def test_document_embedding_zero_value_preserved(self):
        """
        GIVEN numpy array containing zero as document_embedding
        WHEN LLMDocument is instantiated
        THEN expect zero value is preserved
        """
        test_value = 0.0
        array = [np.nan, np.inf, -np.inf, 0.0, 1.0]
        special_values = np.array(array, dtype=np.float64)
        
        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=special_values)

        assert document.document_embedding[3] == test_value, f"Zero value should be preserved in document embedding, got {document.document_embedding[3]}"

    def test_document_embedding_one_value_preserved(self):
        """
        GIVEN numpy array containing one as document_embedding
        WHEN LLMDocument is instantiated
        THEN expect one value is preserved
        """
        special_values = np.array([np.nan, np.inf, -np.inf, 0.0, 1.0], dtype=np.float64)

        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=special_values)

        assert document.document_embedding[4] == 1.0, f"One value should be preserved in document embedding, got {document.document_embedding[4]}"

    def test_document_embedding_memory_sharing_basic_setup(self):
        """
        GIVEN numpy array as document_embedding
        WHEN LLMDocument is instantiated
        THEN expect basic memory sharing analysis can be performed
        """
        original_array = np.array([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32)
        
        document = LLMDocumentTestDataFactory.create_document_instance(
            document_embedding=original_array
        )
        
        assert document.document_embedding is not None, "Document embedding should not be None for basic memory sharing analysis"

    def test_document_embedding_memory_independence_verification(self):
        """
        GIVEN numpy array as document_embedding
        WHEN LLMDocument is instantiated
        THEN expect memory is not shared between original and document arrays
        """
        original_array = np.array([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32)
        
        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=original_array)
        
        # Check if memory is *not* shared
        original_data_ptr = original_array.__array_interface__['data'][0]
        document_data_ptr = document.document_embedding.__array_interface__['data'][0]
        assert original_data_ptr != document_data_ptr, f"Memory should not be shared, but got {original_data_ptr} == {document_data_ptr}"

    def test_document_embedding_original_array_unchanged_after_modification(self):
        """
        GIVEN numpy array as document_embedding
        WHEN document embedding is modified after instantiation
        THEN expect original array remains unchanged
        """
        original_array = np.array([0.1, 0.2, 0.3, 0.4, 0.5], dtype=np.float32)
        original_value = original_array[0]
        
        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=original_array)
        
        # Modify document embedding
        document.document_embedding[0] = 999.0
        
        # Verify original array is unchanged
        assert original_array[0] == original_value, f"Original array should remain unchanged, expected {original_value}, got {original_array[0]}"

    def test_document_embedding_single_element_array_handling(self):
        """
        GIVEN single element numpy array as document_embedding
        WHEN LLMDocument is instantiated
        THEN expect valid embedding with correct shape
        """
        test_array = np.array([1.0], dtype=np.float32)
        
        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=test_array)
        
        assert document.document_embedding.shape == test_array.shape, f"Document embedding shape should match test array shape, expected {test_array.shape}, got {document.document_embedding.shape}"

    def test_document_embedding_large_array_handling(self):
        """
        GIVEN large numpy array as document_embedding
        WHEN LLMDocument is instantiated
        THEN expect valid embedding is not None
        """
        test_array = np.ones((100,), dtype=np.float32)

        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=test_array)
        
        assert document.document_embedding is not None, "Document embedding should not be None for large arrays"

    def test_document_embedding_2d_array_handling(self):
        """
        GIVEN 2D numpy array as document_embedding
        WHEN LLMDocument is instantiated
        THEN expect array is numpy ndarray type
        """
        test_array = np.eye(3, dtype=np.float64)
        
        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=test_array)
        
        assert isinstance(document.document_embedding, np.ndarray), f"Document embedding should be numpy ndarray type, got {type(document.document_embedding)}"

    def test_document_embedding_3d_array_shape_preservation(self):
        """
        GIVEN 3D numpy array as document_embedding
        WHEN LLMDocument is instantiated
        THEN expect shape is preserved
        """
        test_array = np.zeros((2, 3, 4), dtype=np.float32)
        
        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=test_array)
        
        assert document.document_embedding.shape == test_array.shape, f"Document embedding shape should be preserved for 3D arrays, expected {test_array.shape}, got {document.document_embedding.shape}"

    def test_document_embedding_array_view_shape_preservation(self):
        """
        GIVEN numpy array view as document_embedding
        WHEN LLMDocument is instantiated
        THEN expect view shape is preserved
        """
        base_array = np.arange(20, dtype=np.float32)
        view_array = base_array[5:15]
        
        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=view_array)
        
        assert document.document_embedding.shape == view_array.shape, f"Document embedding shape should be preserved for array views, expected {view_array.shape}, got {document.document_embedding.shape}"

    def test_document_embedding_array_view_data_preservation(self):
        """
        GIVEN numpy array view as document_embedding
        WHEN LLMDocument is instantiated
        THEN expect view data is preserved
        """
        base_array = np.arange(20, dtype=np.float32)
        view_array = base_array[5:15]
        
        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=view_array)
        
        assert np.array_equal(document.document_embedding, view_array), f"Document embedding data should be preserved for array views, expected {view_array}, got {document.document_embedding}"

    def test_document_embedding_readonly_array_not_none(self):
        """
        GIVEN read-only numpy array as document_embedding
        WHEN LLMDocument is instantiated
        THEN expect embedding is not None
        """
        readonly_array = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        readonly_array.flags.writeable = False
        
        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=readonly_array)
        
        assert document.document_embedding is not None, "Document embedding should not be None for read-only arrays"

    def test_document_embedding_readonly_array_data_preservation(self):
        """
        GIVEN read-only numpy array as document_embedding
        WHEN LLMDocument is instantiated
        THEN expect array data is preserved
        """
        readonly_array = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        readonly_array.flags.writeable = False
        
        document = LLMDocumentTestDataFactory.create_document_instance(document_embedding=readonly_array)
        
        assert np.array_equal(document.document_embedding, readonly_array), f"Document embedding data should be preserved for read-only arrays, expected {readonly_array}, got {document.document_embedding}"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
