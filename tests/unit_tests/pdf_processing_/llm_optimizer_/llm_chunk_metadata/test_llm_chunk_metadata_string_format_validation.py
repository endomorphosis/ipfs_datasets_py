#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for string format validation requirements.

Tests validation of string field formats including ISO timestamps,
JSON structures, and identifier formats.
"""
import pytest
from pydantic import ValidationError

from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunkMetadata
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_factory import (
    LLMChunkMetadataTestDataFactory as DataFactory
)
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_test_utils import all_words_are_present_in_error_msg, field_values_exactly_match_dict_values


class TestLLMChunkMetadataStringFormatValidation:
    """Test suite for string format validation requirements."""

    def test_created_at_invalid_non_iso_format(self):
        """
        GIVEN created_at with "2025/01/15 10:30:45" (non-ISO format)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with format validation message
        """
        # Constants
        FIELD_NAME = "created_at"
        INVALID_VALUE = "2025/01/15 10:30:45"
        ERROR_WORDS = ["created_at", "valid", "iso", "8601", "format"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValueError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_created_at_invalid_date_only_format(self):
        """
        GIVEN created_at with "2025-01-15" (date only, no time)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with timestamp consistency message (since ISO parsing succeeds but timestamps don't match)
        """
        # Constants
        FIELD_NAME = "created_at"
        INVALID_VALUE = "2025-01-15"
        ERROR_WORDS = ["creation_timestamp", "created_at", "time", "consistency", "error"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValueError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_created_at_invalid_time_only_format(self):
        """
        GIVEN created_at with "10:30:45" (time only, no date)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with format validation message
        """
        # Constants
        FIELD_NAME = "created_at"
        INVALID_VALUE = "10:30:45"
        ERROR_WORDS = ["created_at", "valid", "iso", "8601", "format"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValueError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_original_position_invalid_non_json_string(self):
        """
        GIVEN original_position with "x=100,y=200" (non-JSON format)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with JSON format validation message
        """
        # Constants
        FIELD_NAME = "original_position"
        INVALID_VALUE = "x=100,y=200"
        ERROR_WORDS = ["json", "format", "valid"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValueError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_original_position_invalid_malformed_json(self):
        """
        GIVEN original_position with '{"x": 100, "y":}' (malformed JSON)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with JSON format validation message
        """
        # Constants
        FIELD_NAME = "original_position"
        INVALID_VALUE = '{"x": 100, "y":}'
        ERROR_WORDS = ["json", "format", "valid"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValueError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_original_position_valid_empty_json_object(self):
        """
        GIVEN original_position with "{}" (valid empty JSON)
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "original_position"
        VALID_VALUE = "{}"
        EXPECTED_FIELDS = {FIELD_NAME: VALID_VALUE}
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, VALID_VALUE)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert field_values_exactly_match_dict_values(EXPECTED_FIELDS, metadata)

    def test_original_position_valid_complex_json_structure(self):
        """
        GIVEN original_position with complex nested JSON structure
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "original_position"
        VALID_VALUE = '{"bbox": {"x": 100, "y": 200}, "transforms": [{"scale": 1.5}, {"rotate": 90}]}'
        EXPECTED_FIELDS = {FIELD_NAME: VALID_VALUE}
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, VALID_VALUE)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert field_values_exactly_match_dict_values(EXPECTED_FIELDS, metadata)

    def test_element_id_valid_alphanumeric_underscore(self):
        """
        GIVEN element_id with "elem_123_abc" (alphanumeric with underscores)
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "element_id"
        VALID_VALUE = "elem_123_abc"
        EXPECTED_FIELDS = {FIELD_NAME: VALID_VALUE}
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, VALID_VALUE)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert field_values_exactly_match_dict_values(EXPECTED_FIELDS, metadata)

    def test_element_id_valid_uuid_format(self):
        """
        GIVEN element_id with UUID format string
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "element_id"
        VALID_VALUE = "550e8400-e29b-41d4-a716-446655440000"
        EXPECTED_FIELDS = {FIELD_NAME: VALID_VALUE}
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, VALID_VALUE)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert field_values_exactly_match_dict_values(EXPECTED_FIELDS, metadata)

    def test_element_id_invalid_empty_string(self):
        """
        GIVEN element_id with empty string value
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with non-empty string validation
        """
        # Constants
        FIELD_NAME = "element_id"
        INVALID_VALUE = ""
        ERROR_WORDS = ["string", "field", "empty", "whitespace"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValueError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

if __name__ == "__main__":
    pytest.main([__file__, "-v"])