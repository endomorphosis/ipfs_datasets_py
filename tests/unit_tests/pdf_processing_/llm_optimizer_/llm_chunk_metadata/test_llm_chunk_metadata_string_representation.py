#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for string representation methods.

Tests __str__ and __repr__ methods for LLMChunkMetadata instances,
including content validation and security considerations.
"""
import pytest
from pydantic import ValidationError

from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunkMetadata
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_factory import (
    LLMChunkMetadataTestDataFactory as DataFactory
)


class TestLLMChunkMetadataStringRepresentation:
    """Test suite for string representation methods."""

    def test_str_contains_class_name(self):
        """
        GIVEN a valid LLMChunkMetadata instance
        WHEN str() representation is generated
        THEN output contains class name "LLMChunkMetadata"
        """
        # Constants
        EXPECTED_CLASS_NAME = "LLMChunkMetadata"
        
        # Given
        valid_data = DataFactory.create_valid_baseline_data()
        metadata = LLMChunkMetadata(**valid_data)
        
        # When
        str_repr = str(metadata)
        
        # Then
        assert EXPECTED_CLASS_NAME in str_repr

    def test_str_contains_key_field_values(self):
        """
        GIVEN a valid LLMChunkMetadata instance
        WHEN str() representation is generated
        THEN output contains key field values (element_type, semantic_type)
        """
        # Constants
        KEY_FIELDS = ["element_type", "semantic_type"]

        # Given
        valid_data = DataFactory.create_valid_baseline_data()
        metadata = LLMChunkMetadata(**valid_data)
        
        # When
        str_repr = str(metadata)

        # Then
        for field in KEY_FIELDS:
            assert field in str_repr, f"Field '{field}' not found in str representation: {str_repr}"

    def test_repr_is_valid_python_expression(self):
        """
        GIVEN a valid LLMChunkMetadata instance
        WHEN repr() representation is generated
        THEN output is valid Python expression format
        """
        # Constants
        EXPECTED_STRINGS = ["LLMChunkMetadata", ")", "="]

        # Given
        valid_data = DataFactory.create_valid_baseline_data()
        metadata = LLMChunkMetadata(**valid_data)
        
        # When
        repr_str = repr(metadata)
        
        # Then
        for string in EXPECTED_STRINGS:
            assert string in repr_str, f"String '{string}' not found in repr representation: {repr_str}"

    def test_repr_contains_all_fields(self):
        """
        GIVEN a valid LLMChunkMetadata instance
        WHEN repr() representation is generated
        THEN output contains all fields
        """
        # Given
        valid_data = DataFactory.create_valid_baseline_data()
        metadata = LLMChunkMetadata(**valid_data)
        
        # When
        repr_str = repr(metadata)
        
        # Then
        for field_name in valid_data.keys():
            assert field_name in repr_str

    def test_str_is_non_empty(self):
        """
        GIVEN a valid LLMChunkMetadata instance
        WHEN str() representation is generated
        THEN non-empty string output
        """
        # Constants
        MIN_LENGTH = 0
        
        # Given
        valid_data = DataFactory.create_valid_baseline_data()
        metadata = LLMChunkMetadata(**valid_data)
        
        # When
        str_repr = str(metadata)
        
        # Then
        assert len(str_repr.strip()) > MIN_LENGTH, f"String representation of LLMChunkMetadata is empty."

    def test_repr_is_non_empty(self):
        """
        GIVEN a valid LLMChunkMetadata instance
        WHEN repr() representation is generated
        THEN non-empty string output
        """
        # Constants
        MIN_LENGTH = 0
        
        # Given
        valid_data = DataFactory.create_valid_baseline_data()
        metadata = LLMChunkMetadata(**valid_data)
        
        # When
        repr_str = repr(metadata)
        
        # Then
        assert len(repr_str.strip()) > MIN_LENGTH, f"Repr representation of LLMChunkMetadata is empty."


if __name__ == "__main__":
    pytest.main([__file__, "-v"])