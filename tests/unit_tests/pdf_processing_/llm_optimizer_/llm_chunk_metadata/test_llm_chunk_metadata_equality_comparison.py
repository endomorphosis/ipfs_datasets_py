#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for equality comparison operations.

Tests equality, inequality, and hash operations for LLMChunkMetadata instances
including edge cases with None and non-metadata objects.
"""
import pytest
from pydantic import ValidationError

from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunkMetadata
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_factory import (
    LLMChunkMetadataTestDataFactory as DataFactory
)


class TestLLMChunkMetadataEqualityComparison:
    """Test suite for equality comparison operations."""

    def test_identical_instances_equal_comparison_true(self):
        """
        GIVEN two LLMChunkMetadata instances with identical field values
        WHEN comparing using == operator
        THEN result is True
        """
        # Constants
        EXPECTED_RESULT = True
        
        # Given
        valid_data = DataFactory.create_valid_baseline_data()
        metadata1 = LLMChunkMetadata(**valid_data)
        metadata2 = LLMChunkMetadata(**valid_data)
        
        # When
        result = metadata1 == metadata2
        
        # Then
        assert result is EXPECTED_RESULT

    def test_identical_instances_not_equal_comparison_false(self):
        """
        GIVEN two LLMChunkMetadata instances with identical field values
        WHEN comparing using != operator
        THEN result is False
        """
        # Constants
        EXPECTED_RESULT = False
        
        # Given
        valid_data = DataFactory.create_valid_baseline_data()
        metadata1 = LLMChunkMetadata(**valid_data)
        metadata2 = LLMChunkMetadata(**valid_data)
        
        # When
        result = metadata1 != metadata2
        
        # Then
        assert result is EXPECTED_RESULT

    def test_different_instances_equal_comparison_false(self):
        """
        GIVEN two LLMChunkMetadata instances with different field values
        WHEN comparing using == operator
        THEN result is False
        """
        # Constants
        FIELD_TO_CHANGE = "element_type"
        DIFFERENT_VALUE = "table"
        EXPECTED_RESULT = False
        
        # Given
        data1 = DataFactory.create_valid_baseline_data()
        data2 = DataFactory.create_valid_baseline_data()
        data2[FIELD_TO_CHANGE] = DIFFERENT_VALUE  # Make them different
        metadata1 = LLMChunkMetadata(**data1)
        metadata2 = LLMChunkMetadata(**data2)
        
        # When
        result = metadata1 == metadata2
        
        # Then
        assert result is EXPECTED_RESULT

    def test_different_instances_not_equal_comparison_true(self):
        """
        GIVEN two LLMChunkMetadata instances with different field values
        WHEN comparing using != operator
        THEN result is True
        """
        # Constants
        FIELD_TO_CHANGE = "confidence"
        DIFFERENT_VALUE = 0.5
        EXPECTED_RESULT = True
        
        # Given
        data1 = DataFactory.create_valid_baseline_data()
        data2 = DataFactory.create_valid_baseline_data()
        data2[FIELD_TO_CHANGE] = DIFFERENT_VALUE  # Make them different
        metadata1 = LLMChunkMetadata(**data1)
        metadata2 = LLMChunkMetadata(**data2)
        
        # When
        result = metadata1 != metadata2
        
        # Then
        assert result is EXPECTED_RESULT

    def test_comparison_with_non_metadata_object_false(self):
        """
        GIVEN LLMChunkMetadata instance and non-LLMChunkMetadata object
        WHEN comparing using == operator
        THEN result is False
        """
        # Constants
        NON_METADATA_OBJECT = {"some": "dict"}
        EXPECTED_RESULT = False
        
        # Given
        valid_data = DataFactory.create_valid_baseline_data()
        metadata = LLMChunkMetadata(**valid_data)
        
        # When
        result = metadata == NON_METADATA_OBJECT
        
        # Then
        assert result is EXPECTED_RESULT

    def test_comparison_with_none_false(self):
        """
        GIVEN LLMChunkMetadata instance and None
        WHEN comparing using == operator
        THEN result is False
        """
        # Constants
        NONE_VALUE = None
        EXPECTED_RESULT = False
        
        # Given
        valid_data = DataFactory.create_valid_baseline_data()
        metadata = LLMChunkMetadata(**valid_data)
        
        # When
        result = metadata == NONE_VALUE
        
        # Then
        assert result is EXPECTED_RESULT

    def test_hash_values_consistent_for_equal_instances(self):
        """
        GIVEN two LLMChunkMetadata instances with identical field values
        WHEN hash values are computed
        THEN hash values are consistent for equal instances
        """
        # Given
        valid_data = DataFactory.create_valid_baseline_data()
        metadata1 = LLMChunkMetadata(**valid_data)
        metadata2 = LLMChunkMetadata(**valid_data)
        
        # When
        hash1 = hash(metadata1)
        hash2 = hash(metadata2)
        
        # Then
        assert metadata1 == metadata2  # Verify they are equal first
        assert hash1 == hash2  # Hash values must be equal for equal objects

if __name__ == "__main__":
    pytest.main([__file__, "-v"])