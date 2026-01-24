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

@pytest.fixture
def boundary_condition_params():
    """Provide boundary condition parameters for testing."""
    return {
        "max_size": 2,
        "overlap": 1,
        "min_size": 1
    }


def _scale_attrs(valid_init_params_for_chunk_optimizer, scalar, attr1, attr2):
    """Scale all parameters by a given scalar."""
    params = valid_init_params_for_chunk_optimizer.copy()
    params[attr1] *= scalar
    params[attr1] = params[attr2]
    return params

def _add_constant_to_attrs(valid_init_params_for_chunk_optimizer, constant, attr1, attr2):
    """Add a constant to all parameters."""
    params = valid_init_params_for_chunk_optimizer.copy()
    params[attr1] = params[attr2]
    params[attr1] += constant
    return params


class TestChunkOptimizerInitialization:
    """Test ChunkOptimizer initialization and configuration validation."""


    @pytest.mark.parametrize("attr_name", ["max_size", "overlap", "min_size"])
    def test_init_with_valid_parameters(self, attr_name, valid_init_params_for_chunk_optimizer):
        """
        GIVEN valid chunking parameters with max_size > min_size and overlap < max_size
        WHEN ChunkOptimizer is initialized
        THEN expect all attribute values to be type int
        """
        # Given
        optimizer = ChunkOptimizer(**valid_init_params_for_chunk_optimizer)

        # When
        attr_value = getattr(optimizer, attr_name)

        # Then
        assert isinstance(attr_value, int), \
            f"Expected '{attr_name}' attribute to be of type int, but got {type(attr_value).__name__} instead."


    @pytest.mark.parametrize("param_name", ["max_size", "overlap", "min_size"])
    def test_init_with_boundary_conditions(self, param_name, boundary_condition_params):
        """
        GIVEN boundary condition parameters (min valid values)
        WHEN ChunkOptimizer is initialized with these parameters
        THEN expect the attribute's value to equal the initialization parameter's value
        """
        # Given/When
        expected_value = boundary_condition_params[param_name]

        optimizer = ChunkOptimizer(**boundary_condition_params)

        # Then
        actual_value = getattr(optimizer, param_name)
        assert actual_value == expected_value, \
            f"Expected '{param_name}' attribute to equal {expected_value}, but got {actual_value}"


    @pytest.mark.parametrize("constant", [-50, -100, -250,])
    def test_init_max_size_less_than_or_equal_min_size(self, constant, valid_init_params_for_chunk_optimizer):
        """
        GIVEN invalid parameters where max_size < min_size
        WHEN ChunkOptimizer is initialized
        THEN expect ValueError to be raised
        """
        params = _add_constant_to_attrs(valid_init_params_for_chunk_optimizer, constant, 'max_size', 'min_size')

        with pytest.raises(ValueError):
            ChunkOptimizer(**params)

    @pytest.mark.parametrize("scalar", [1, 2, 5, 10,])
    def test_init_max_size_equal_to_min_size(self, scalar, valid_init_params_for_chunk_optimizer):
        """
        GIVEN invalid parameters where max_size == min_size
        WHEN ChunkOptimizer is initialized
        THEN expect ValueError to be raised
        """
        params = _scale_attrs(valid_init_params_for_chunk_optimizer, scalar, 'max_size', 'min_size')

        with pytest.raises(ValueError):
            ChunkOptimizer(**params)

    @pytest.mark.parametrize("scalar", [1, 2, 5, 10,])
    def test_init_overlap_equal_to_max_size(self, scalar, valid_init_params_for_chunk_optimizer):
        """
        GIVEN invalid parameters where overlap == max_size
        WHEN ChunkOptimizer is initialized
        THEN expect ValueError to be raised
        """
        params = _scale_attrs(valid_init_params_for_chunk_optimizer, scalar, 'max_size', 'overlap')

        with pytest.raises(ValueError):
            ChunkOptimizer(**params)

    @pytest.mark.parametrize("constant", [50, 100, 250,])
    def test_init_overlap_greater_than_max_size(self, constant, valid_init_params_for_chunk_optimizer):
        """
        GIVEN invalid parameters where overlap > max_size
        WHEN ChunkOptimizer is initialized
        THEN expect ValueError to be raised
        """
        params = _add_constant_to_attrs(valid_init_params_for_chunk_optimizer, constant, 'overlap', 'max_size')

        with pytest.raises(ValueError):
            ChunkOptimizer(**params)

    @pytest.mark.parametrize("invalid_value,param_name", [
        # Negative parameters
        (-100, "max_size"),
        (-50, "overlap"),
        (-25, "min_size"),
        # Zero parameters
        (0, "max_size"),
        (0, "overlap"), 
        (0, "min_size"),
    ])
    def test_init_invalid_parameter_values(self, invalid_value, param_name, valid_init_params_for_chunk_optimizer):
        """
        GIVEN negative or zero values for any parameter
        WHEN ChunkOptimizer is initialized
        THEN expect ValueError to be raised
        """
        # Replace the valid parameter with the invalid one
        params = valid_init_params_for_chunk_optimizer.copy()
        params[param_name] = invalid_value

        with pytest.raises(ValueError):
            ChunkOptimizer(**params)

    @pytest.mark.parametrize("param_name,invalid_value", [
        # Float parameters
        ("max_size", 100.5),
        ("overlap", 50.5),
        ("min_size", 25.5),
        # String parameters
        ("max_size", "100"),
        ("overlap", "50"),
        ("min_size", "25"),
        # None parameters
        ("max_size", None),
        ("overlap", None),
        ("min_size", None),
        # List parameters
        ("max_size", [100]),
        ("overlap", [50]),
        ("min_size", [25]),
    ])
    def test_init_non_integer_parameters(self, param_name, invalid_value, valid_init_params_for_chunk_optimizer):
        """
        GIVEN non-integer parameters (float, string, None, list)
        WHEN ChunkOptimizer is initialized
        THEN expect TypeError to be raised
        """
        # Replace the valid parameter with the invalid one
        params = valid_init_params_for_chunk_optimizer.copy()
        params[param_name] = invalid_value

        with pytest.raises(TypeError):
            ChunkOptimizer(**params)



class TestChunkOptimizerAttributeAccess:
    """Test ChunkOptimizer attribute access and immutability."""

    @pytest.mark.parametrize("attribute", ["max_size", "overlap", "min_size"])
    def test_attributes_exist(self, attribute, valid_init_params_for_chunk_optimizer):
        """
        GIVEN initialized ChunkOptimizer
        WHEN checking for attribute existence
        THEN expect attribute to exist
        """
        # Given
        optimizer = ChunkOptimizer(**valid_init_params_for_chunk_optimizer)
        
        # When/Then
        assert hasattr(optimizer, attribute), \
            f"ChunkOptimizer does not have expected attribute '{attribute}'"

    @pytest.mark.parametrize("param_name,param_value", [
        ("max_size", 2048),
        ("overlap", 200),
        ("min_size", 100)
    ])
    def test_when_init_is_called_attributes_set(self, param_name, param_value, valid_init_params_for_chunk_optimizer):
        """
        GIVEN valid initialization parameters
        WHEN ChunkOptimizer is initialized
        THEN expect the attribute's value to equal the initialization parameter's value
        """
        # Given
        expected_value = param_value
        
        # When
        optimizer = ChunkOptimizer(**valid_init_params_for_chunk_optimizer)
        
        # Then
        actual_value = getattr(optimizer, param_name)
        assert actual_value == expected_value, \
            f"Expected '{param_name}' attribute to equal {expected_value}, but got {actual_value}"

    @pytest.mark.parametrize("attribute", ["max_size", "overlap", "min_size"])
    def test_attribute_can_be_modified(self, chunk_optimizer, attribute, other_valid_init_params_for_chunk_optimizer):
        """
        GIVEN initialized ChunkOptimizer
        WHEN max_size attribute is modified
        THEN expect the attribute to equal the new value
        """
        # Given
        new_attr_value = other_valid_init_params_for_chunk_optimizer[attribute]

        # When
        setattr(chunk_optimizer, attribute, new_attr_value)
        actual_value = getattr(chunk_optimizer, attribute)

        # Then
        assert actual_value == new_attr_value, \
            f"Expected '{attribute}' attribute to be set to {new_attr_value}, but got {actual_value} instead."


    @pytest.mark.parametrize("attribute", ["max_size", "overlap", "min_size"])
    def test_attribute_modification_changes_value(self, chunk_optimizer, attribute, other_valid_init_params_for_chunk_optimizer):
        """
        GIVEN initialized ChunkOptimizer
        WHEN an attribute is modified
        THEN expect the attribute value to not equal the original value
        """
        # Given
        original_attr_value = getattr(chunk_optimizer, attribute)
        new_attr_value = other_valid_init_params_for_chunk_optimizer[attribute]

        # When
        setattr(chunk_optimizer, attribute, new_attr_value)
        actual_value = getattr(chunk_optimizer, attribute)
        
        # Then
        assert actual_value != original_attr_value, \
            f"Expected '{attribute}' attribute to change to {new_attr_value}, but it was still {original_attr_value}"







if __name__ == "__main__":
    pytest.main([__file__, "-v"])
