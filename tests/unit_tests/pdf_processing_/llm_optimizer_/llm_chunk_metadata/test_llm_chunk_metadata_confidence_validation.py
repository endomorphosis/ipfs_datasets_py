#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for confidence field range validation.

Tests that the confidence field properly validates its range (0.0-1.0) and
raises appropriate ValidationError for out-of-range values.
"""
import pytest
from pydantic import ValidationError

from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunkMetadata
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_factory import (
    LLMChunkMetadataTestDataFactory as DataFactory
)
from .llm_chunk_metadata_test_utils import all_words_are_present_in_error_msg, field_values_exactly_match_dict_values

class TestLLMChunkMetadataConfidenceValidation:
    """Test suite for confidence field range validation."""

    def test_confidence_below_lower_bound(self):
        """
        GIVEN confidence value -0.1 (below 0.0)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with range validation message
        """
        # Constants
        FIELD_NAME = "confidence"
        INVALID_VALUE = -0.1
        ERROR_WORDS = ["confidence", "greater", "0.0", "range"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_confidence_above_upper_bound(self):
        """
        GIVEN confidence value 1.1 (above 1.0)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with range validation message
        """
        # Constants
        FIELD_NAME = "confidence"
        INVALID_VALUE = 1.1
        ERROR_WORDS = ["confidence", "less", "1.0", "range"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)

        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_confidence_infinite_value(self):
        """
        GIVEN confidence value float('inf') (infinite)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with range validation message
        """
        # Constants
        FIELD_NAME = "confidence"
        INVALID_VALUE = float('inf')
        ERROR_WORDS = ["confidence", "finite", "range", "inf"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)

        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_confidence_nan_value(self):
        """
        GIVEN confidence value float('nan') (not a number)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with range validation message
        """
        # Constants
        FIELD_NAME = "confidence"
        INVALID_VALUE = float('nan')
        ERROR_WORDS = ["confidence", "finite", "nan", "number"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)

        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_confidence_at_lower_bound(self):
        """
        GIVEN confidence value 0.0 (lower bound)
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "confidence"
        VALID_VALUE = 0.0
        EXPECTED_FIELDS = {FIELD_NAME: VALID_VALUE}
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, VALID_VALUE)

        # When
        metadata = LLMChunkMetadata(**data)

        # Then
        assert field_values_exactly_match_dict_values(EXPECTED_FIELDS, metadata)

    def test_confidence_at_upper_bound(self):
        """
        GIVEN confidence value 1.0 (upper bound)
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "confidence"
        VALID_VALUE = 1.0
        EXPECTED_FIELDS = {FIELD_NAME: VALID_VALUE}
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, VALID_VALUE)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert field_values_exactly_match_dict_values(EXPECTED_FIELDS, metadata)

    def test_confidence_at_middle_value(self):
        """
        GIVEN confidence value 0.5 (middle)
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "confidence"
        VALID_VALUE = 0.5
        EXPECTED_FIELDS = {FIELD_NAME: VALID_VALUE}
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, VALID_VALUE)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert field_values_exactly_match_dict_values(EXPECTED_FIELDS, metadata)

    def test_confidence_near_upper_bound(self):
        """
        GIVEN confidence value 0.999999 (near upper)
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "confidence"
        VALID_VALUE = 0.999999
        EXPECTED_FIELDS = {FIELD_NAME: VALID_VALUE}
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, VALID_VALUE)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert field_values_exactly_match_dict_values(EXPECTED_FIELDS, metadata)

    def test_confidence_near_lower_bound(self):
        """
        GIVEN confidence value 0.000001 (near lower)
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "confidence"
        VALID_VALUE = 0.000001
        EXPECTED_FIELDS = {FIELD_NAME: VALID_VALUE}
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, VALID_VALUE)

        # When
        metadata = LLMChunkMetadata(**data)

        # Then
        assert field_values_exactly_match_dict_values(EXPECTED_FIELDS, metadata)

if __name__ == "__main__":
    pytest.main([__file__, "-v"])