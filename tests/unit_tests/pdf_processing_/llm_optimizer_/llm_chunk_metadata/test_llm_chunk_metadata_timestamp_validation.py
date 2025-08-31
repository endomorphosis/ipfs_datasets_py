#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for timestamp field validation.

Tests validation of creation_timestamp (float) and created_at (ISO string) fields
including format validation, range validation, and consistency checks.
"""
import pytest
from pydantic import ValidationError
from typing import Literal
from datetime import datetime

from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunkMetadata
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_factory import (
    LLMChunkMetadataTestDataFactory as DataFactory
)
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_test_utils import all_words_are_present_in_error_msg

class TestLLMChunkMetadataTimestampValidation:
    """Test suite for timestamp field validation."""

    def test_creation_timestamp_valid_positive_float(self):
        """
        GIVEN creation_timestamp with valid positive float (Unix timestamp)
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "creation_timestamp"
        VALID_VALUE = 1640995200.123
        
        # Given - create matching timestamp and ISO string
        data = DataFactory.create_valid_baseline_data()
        data[FIELD_NAME] = VALID_VALUE
        # Convert to matching ISO string to avoid consistency error
        matching_iso = datetime.fromtimestamp(VALID_VALUE).isoformat()
        data["created_at"] = matching_iso
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert metadata.creation_timestamp == VALID_VALUE

    def test_creation_timestamp_valid_epoch_zero(self):
        """
        GIVEN creation_timestamp value 0.0 (epoch)
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "creation_timestamp"
        VALID_VALUE = 0.0
        
        # Given - create matching timestamp and ISO string
        data = DataFactory.create_valid_baseline_data()
        data[FIELD_NAME] = VALID_VALUE
        # Convert to matching ISO string to avoid consistency error
        matching_iso = datetime.fromtimestamp(VALID_VALUE).isoformat()
        data["created_at"] = matching_iso
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert metadata.creation_timestamp == VALID_VALUE

    def test_creation_timestamp_invalid_negative_float(self):
        """
        GIVEN creation_timestamp with negative float value
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError
        """
        # Constants
        FIELD_NAME = "creation_timestamp"
        INVALID_VALUE = -123.45
        # Update error words to match actual Pydantic error messages
        ERROR_WORDS = ["creation_timestamp", "greater", "equal"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS) == True

    def test_creation_timestamp_invalid_string_representation(self):
        """
        GIVEN creation_timestamp with non-numeric string value
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError
        """
        # Constants
        FIELD_NAME = "creation_timestamp"
        INVALID_VALUE = "not-a-number"  # Use a string that cannot be converted to float
        # Update error words to match actual Pydantic error messages
        ERROR_WORDS = ["creation_timestamp", "input", "float"]
        
        # Given
        data = DataFactory.create_data_with_invalid_type(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS) == True


    def test_creation_timestamp_invalid_none_value(self):
        """
        GIVEN creation_timestamp with None value
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError
        """
        # Constants
        FIELD_NAME = "creation_timestamp"
        INVALID_VALUE = None
        # Update error words to match actual Pydantic error messages
        ERROR_WORDS = ["creation_timestamp", "none", "float"]
        
        # Given
        data = DataFactory.create_data_with_invalid_type(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS) == True

    def test_created_at_valid_basic_iso_format(self):
        """
        GIVEN created_at with "2025-01-15T10:30:45" format
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "created_at"
        VALID_VALUE = "2025-01-15T10:30:45"
        
        # Given - create matching timestamp and ISO string
        data = DataFactory.create_valid_baseline_data()
        data[FIELD_NAME] = VALID_VALUE
        # Convert to matching timestamp to avoid consistency error
        matching_timestamp = datetime.fromisoformat(VALID_VALUE).timestamp()
        data["creation_timestamp"] = matching_timestamp
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert metadata.created_at == VALID_VALUE

    def test_created_at_valid_iso_with_milliseconds_utc(self):
        """
        GIVEN created_at with "2025-01-15T10:30:45.123Z" format
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "created_at"
        VALID_VALUE = "2025-01-15T10:30:45.123Z"
        
        # Given - create matching timestamp and ISO string
        data = DataFactory.create_valid_baseline_data()
        data[FIELD_NAME] = VALID_VALUE
        # Convert to matching timestamp to avoid consistency error
        matching_timestamp = datetime.fromisoformat(VALID_VALUE.replace('Z', '+00:00')).timestamp()
        data["creation_timestamp"] = matching_timestamp
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert metadata.created_at == VALID_VALUE

    def test_created_at_valid_iso_with_timezone_offset(self):
        """
        GIVEN created_at with "2025-01-15T10:30:45+00:00" format
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "created_at"
        VALID_VALUE = "2025-01-15T10:30:45+00:00"
        
        # Given - create matching timestamp and ISO string
        data = DataFactory.create_valid_baseline_data()
        data[FIELD_NAME] = VALID_VALUE
        # Convert to matching timestamp to avoid consistency error
        matching_timestamp = datetime.fromisoformat(VALID_VALUE).timestamp()
        data["creation_timestamp"] = matching_timestamp
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert metadata.created_at == VALID_VALUE

    def test_created_at_invalid_month_thirteen(self):
        """
        GIVEN created_at with "2025-13-01T10:30:45" (month 13)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError
        """
        # Constants
        FIELD_NAME = "created_at"
        INVALID_VALUE = "2025-13-01T10:30:45"
        # Update error words to match actual Pydantic error messages
        ERROR_WORDS = ["created_at", "iso", "8601", "format"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)

        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS) == True


    def test_created_at_invalid_non_timestamp_string(self):
        """
        GIVEN created_at with "not-a-timestamp" value
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError
        """
        # Constants
        FIELD_NAME = "created_at"
        INVALID_VALUE = "not-a-timestamp"
        # Update error words to match actual Pydantic error messages
        ERROR_WORDS = ["created_at", "iso", "8601", "format"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS) == True

    def test_created_at_invalid_empty_string(self):
        """
        GIVEN created_at with empty string value
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError
        """
        # Constants
        FIELD_NAME = "created_at"
        INVALID_VALUE = ""
        # Update error words to match actual Pydantic error messages
        ERROR_WORDS = ["created_at", "string", "least", "character"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)

        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)

        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS) == True


    def test_created_at_invalid_none_value(self):
        """
        GIVEN created_at with None value
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError
        """
        # Constants
        FIELD_NAME = "created_at"
        INVALID_VALUE = None
        # Update error words to match actual Pydantic error messages
        ERROR_WORDS = ["created_at", "none", "string"]
        
        # Given
        data = DataFactory.create_data_with_invalid_type(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS) == True
