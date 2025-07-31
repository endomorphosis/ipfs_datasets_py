#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for field type validation.

Tests that LLMChunkMetadata properly validates field types and raises
appropriate ValidationError when fields have incorrect types.
"""
import pytest
from pydantic import ValidationError

from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunkMetadata
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_factory import (
    LLMChunkMetadataTestDataFactory as DataFactory
)
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_test_utils import all_words_are_present_in_error_msg


class TestLLMChunkMetadataTypeValidation:
    """Test suite for field type validation."""

    def test_element_type_invalid_int_type(self):
        """
        GIVEN element_type field with int value instead of str
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError 
        """
        # Constants
        FIELD_NAME = "element_type"
        INVALID_VALUE = 123
        ERROR_WORDS = ["element_type", "type", "string", "str"]
        
        # Given
        data = DataFactory.create_data_with_invalid_type(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)

        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS) == True

    def test_confidence_invalid_str_type(self):
        """
        GIVEN confidence field with str value instead of float
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError 
        """
        # Constants
        FIELD_NAME = "confidence"
        INVALID_VALUE = "0.95"
        ERROR_WORDS = ["confidence", "type", "float", "number"]
        
        # Given
        data = DataFactory.create_data_with_invalid_type(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS) == True

    def test_character_count_invalid_str_type(self):
        """
        GIVEN character_count field with str value instead of int
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError 
        """
        # Constants
        FIELD_NAME = "character_count"
        INVALID_VALUE = "1250"
        ERROR_WORDS = ["character_count", "type", "int", "integer"]
        
        # Given
        data = DataFactory.create_data_with_invalid_type(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS) == True

    def test_word_count_invalid_float_type(self):
        """
        GIVEN word_count field with float value instead of int
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError 
        """
        # Constants
        FIELD_NAME = "word_count"
        INVALID_VALUE = 200.5
        ERROR_WORDS = ["word_count", "type", "int", "integer"]
        
        # Given
        data = DataFactory.create_data_with_invalid_type(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS) == True

    def test_sentence_count_invalid_negative_int(self):
        """
        GIVEN sentence_count field with negative int value
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError
        """
        # Constants
        FIELD_NAME = "sentence_count"
        INVALID_VALUE = -5
        ERROR_WORDS = ["sentence_count", "greater", "positive", "non-negative"]
        
        # Given
        data = DataFactory.create_data_with_invalid_type(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS) == True

    def test_token_count_invalid_none_type(self):
        """
        GIVEN token_count field with None value instead of int
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError 
        """
        # Constants
        FIELD_NAME = "token_count"
        INVALID_VALUE = None
        ERROR_WORDS = ["token_count", "type", "int", "none"]
        
        # Given
        data = DataFactory.create_data_with_invalid_type(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)

        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS) == True

    def test_creation_timestamp_invalid_str_type(self):
        """
        GIVEN creation_timestamp field with str value instead of float
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError 
        """
        # Constants
        FIELD_NAME = "creation_timestamp"
        INVALID_VALUE = "1640995200.123"
        ERROR_WORDS = ["creation_timestamp", "type", "float", "number"]
        
        # Given
        data = DataFactory.create_data_with_invalid_type(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS) == True

    def test_created_at_invalid_int_type(self):
        """
        GIVEN created_at field with int value instead of str
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError 
        """
        # Constants
        FIELD_NAME = "created_at"
        INVALID_VALUE = 123456789099999999999999999999999999999999999
        ERROR_WORDS = ["created_at", "type", "str"]
        
        # Given
        data = DataFactory.create_data_with_invalid_type(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS) == True

    def test_has_mixed_elements_invalid_str_type(self):
        """
        GIVEN has_mixed_elements field with str value instead of bool
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError 
        """
        # Constants
        FIELD_NAME = "has_mixed_elements"
        INVALID_VALUE = "true"
        ERROR_WORDS = ["has_mixed_elements", "type", "bool", "boolean"]
        
        # Given
        data = DataFactory.create_data_with_invalid_type(FIELD_NAME, INVALID_VALUE)

        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)

        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS) == True

    def test_contains_table_invalid_int_type(self):
        """
        GIVEN contains_table field with int value instead of bool
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError 
        """
        # Constants
        FIELD_NAME = "contains_table"
        INVALID_VALUE = 1
        ERROR_WORDS = ["contains_table", "type", "bool"]
        
        # Given
        data = DataFactory.create_data_with_invalid_type(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)

        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS) == True

    def test_page_number_invalid_float_type(self):
        """
        GIVEN page_number field with float value instead of int
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError 
        """
        # Constants
        FIELD_NAME = "page_number"
        INVALID_VALUE = 2.5
        ERROR_WORDS = ["page_number", "type", "int"]
        
        # Given
        data = DataFactory.create_data_with_invalid_type(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS) == True

    def test_total_chunks_on_page_invalid_str_type(self):
        """
        GIVEN total_chunks_on_page field with str value instead of int
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError 
        """
        # Constants
        FIELD_NAME = "total_chunks_on_page"
        INVALID_VALUE = "8"
        ERROR_WORDS = ["total_chunks_on_page", "type", "int"]
        
        # Given
        data = DataFactory.create_data_with_invalid_type(FIELD_NAME, INVALID_VALUE)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS) == True
