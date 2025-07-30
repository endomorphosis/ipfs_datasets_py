#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for numeric range validation beyond confidence field.

Tests range validation for all numeric fields including character counts,
page numbers, and timestamp values.
"""
import pytest
from pydantic import ValidationError

from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunkMetadata
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_factory import (
    LLMChunkMetadataTestDataFactory as DataFactory
)
from .llm_chunk_metadata_test_utils import all_words_are_present_in_error_msg


class TestLLMChunkMetadataRangeValidation:
    """Test suite for numeric range validation beyond confidence field."""

    def test_character_count_invalid_negative_value(self):
        """
        GIVEN character_count with -1 (negative value)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with non-negative validation message
        """
        # Constants
        FIELD_NAME = "character_count"
        INVALID_VALUE = -1
        ERROR_WORDS = ["character_count", "greater", "non-negative", "positive"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_word_count_invalid_negative_value(self):
        """
        GIVEN word_count with -5 (negative value)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with non-negative validation message
        """
        # Constants
        FIELD_NAME = "word_count"
        INVALID_VALUE = -5
        ERROR_WORDS = ["word_count", "greater", "non-negative", "positive"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_sentence_count_invalid_negative_value(self):
        """
        GIVEN sentence_count with -2 (negative value)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with non-negative validation message
        """
        # Constants
        FIELD_NAME = "sentence_count"
        INVALID_VALUE = -2
        ERROR_WORDS = ["sentence_count", "greater", "non-negative", "positive"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_token_count_invalid_negative_value(self):
        """
        GIVEN token_count with -10 (negative value)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with non-negative validation message
        """
        # Constants
        FIELD_NAME = "token_count"
        INVALID_VALUE = -10
        ERROR_WORDS = ["token_count", "greater", "non-negative", "positive"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_page_number_invalid_zero_value(self):
        """
        GIVEN page_number with 0 (invalid page number)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with positive integer message
        """
        # Constants
        FIELD_NAME = "page_number"
        INVALID_VALUE = 0
        ERROR_WORDS = ["page_number", "greater", "positive", "1"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_page_number_invalid_negative_value(self):
        """
        GIVEN page_number with -1 (negative page number)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with positive integer message
        """
        # Constants
        FIELD_NAME = "page_number"
        INVALID_VALUE = -1
        ERROR_WORDS = ["page_number", "greater", "positive", "1"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_chunk_position_in_doc_invalid_negative_value(self):
        """
        GIVEN chunk_position_in_doc with -1 (negative position)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with non-negative validation message
        """
        # Constants
        FIELD_NAME = "chunk_position_in_doc"
        INVALID_VALUE = -1
        ERROR_WORDS = ["chunk_position_in_doc", "greater", "non-negative", "0"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_total_chunks_on_page_invalid_zero_value(self):
        """
        GIVEN total_chunks_on_page with 0 (invalid count)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with positive integer message
        """
        # Constants
        FIELD_NAME = "total_chunks_on_page"
        INVALID_VALUE = 0
        ERROR_WORDS = ["total_chunks_on_page", "greater", "positive", "1"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_total_chunks_on_page_invalid_negative_value(self):
        """
        GIVEN total_chunks_on_page with -3 (negative count)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with positive integer message
        """
        # Constants
        FIELD_NAME = "total_chunks_on_page"
        INVALID_VALUE = -3
        ERROR_WORDS = ["total_chunks_on_page", "greater", "positive", "1"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_creation_timestamp_invalid_future_value(self):
        """
        GIVEN creation_timestamp with far future timestamp (year 2100)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with time stamp message
        """
        # Constants
        FIELD_NAME = "creation_timestamp"
        INVALID_VALUE = 4102444800.0  # Jan 1, 2100
        ERROR_WORDS = ["creation_timestamp", "future", "reasonable", "range"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_creation_timestamp_invalid_too_old_value(self):
        """
        GIVEN creation_timestamp with very old timestamp (year 1900)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with time stamp message
        """
        # Constants
        FIELD_NAME = "creation_timestamp"
        INVALID_VALUE = -2208988800.0  # Jan 1, 1900
        ERROR_WORDS = ["creation_timestamp", "greater", "reasonable", "range"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

if __name__ == "__main__":
    pytest.main([__file__, "-v"])