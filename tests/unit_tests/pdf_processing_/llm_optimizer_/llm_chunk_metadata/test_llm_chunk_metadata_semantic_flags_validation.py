#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for semantic boolean flag validation.

Tests validation of semantic analysis boolean flags: has_mixed_elements,
contains_table, contains_figure, and is_header.
"""
import pytest
from pydantic import ValidationError

from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunkMetadata
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_factory import (
    LLMChunkMetadataTestDataFactory as DataFactory
)
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_test_utils import all_words_are_present_in_error_msg, field_values_exactly_match_dict_values


class TestLLMChunkMetadataSemanticFlagsValidation:
    """Test suite for semantic boolean flag validation."""

    def test_has_mixed_elements_valid_true(self):
        """
        GIVEN has_mixed_elements field with bool True value
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "has_mixed_elements"
        VALID_VALUE = True
        EXPECTED_FIELDS = {FIELD_NAME: VALID_VALUE}
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, VALID_VALUE)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert field_values_exactly_match_dict_values(EXPECTED_FIELDS, metadata)

    def test_has_mixed_elements_valid_false(self):
        """
        GIVEN has_mixed_elements field with bool False value
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "has_mixed_elements"
        VALID_VALUE = False
        EXPECTED_FIELDS = {FIELD_NAME: VALID_VALUE}
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, VALID_VALUE)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert field_values_exactly_match_dict_values(EXPECTED_FIELDS, metadata)

    def test_has_mixed_elements_string_true_conversion(self):
        """
        GIVEN has_mixed_elements field with string "true"
        WHEN LLMChunkMetadata is instantiated
        THEN Pydantic automatically converts it to bool True
        """
        # Constants
        FIELD_NAME = "has_mixed_elements"
        STRING_VALUE = "true"
        EXPECTED_FIELDS = {FIELD_NAME: True}
        
        # Given
        data = DataFactory.create_data_with_invalid_type(FIELD_NAME, STRING_VALUE)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert field_values_exactly_match_dict_values(EXPECTED_FIELDS, metadata)

    def test_has_mixed_elements_integer_one_conversion(self):
        """
        GIVEN has_mixed_elements field with integer 1
        WHEN LLMChunkMetadata is instantiated
        THEN Pydantic automatically converts it to bool True
        """
        # Constants
        FIELD_NAME = "has_mixed_elements"
        INTEGER_VALUE = 1
        EXPECTED_FIELDS = {FIELD_NAME: True}
        
        # Given
        data = DataFactory.create_data_with_invalid_type(FIELD_NAME, INTEGER_VALUE)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert field_values_exactly_match_dict_values(EXPECTED_FIELDS, metadata)

    def test_has_mixed_elements_invalid_none_value(self):
        """
        GIVEN has_mixed_elements field with None instead of bool
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError
        """
        # Constants
        FIELD_NAME = "has_mixed_elements"
        INVALID_VALUE = None
        ERROR_WORDS = ["has_mixed_elements", "bool"]  # Updated expected words
        
        # Given
        data = DataFactory.create_data_with_invalid_type(FIELD_NAME, INVALID_VALUE)
        
        # When/Then - Pydantic raises ValidationError, not ValueError
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_has_mixed_elements_invalid_empty_string(self):
        """
        GIVEN has_mixed_elements field with empty string instead of bool
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError
        """
        # Constants
        FIELD_NAME = "has_mixed_elements"
        INVALID_VALUE = ""
        ERROR_WORDS = ["has_mixed_elements", "bool"]  # Updated expected words
        
        # Given
        data = DataFactory.create_data_with_invalid_type(FIELD_NAME, INVALID_VALUE)
        
        # When/Then - Pydantic raises ValidationError, not ValueError
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_contains_table_valid_true(self):
        """
        GIVEN contains_table field with bool True value
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "contains_table"
        VALID_VALUE = True
        EXPECTED_FIELDS = {FIELD_NAME: VALID_VALUE}
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, VALID_VALUE)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert field_values_exactly_match_dict_values(EXPECTED_FIELDS, metadata)

    def test_contains_table_valid_false(self):
        """
        GIVEN contains_table field with bool False value
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "contains_table"
        VALID_VALUE = False
        EXPECTED_FIELDS = {FIELD_NAME: VALID_VALUE}
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, VALID_VALUE)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert field_values_exactly_match_dict_values(EXPECTED_FIELDS, metadata)

    def test_contains_figure_valid_true(self):
        """
        GIVEN contains_figure field with bool True value
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "contains_figure"
        VALID_VALUE = True
        EXPECTED_FIELDS = {FIELD_NAME: VALID_VALUE}
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, VALID_VALUE)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert field_values_exactly_match_dict_values(EXPECTED_FIELDS, metadata)

    def test_contains_figure_valid_false(self):
        """
        GIVEN contains_figure field with bool False value
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "contains_figure"
        VALID_VALUE = False
        EXPECTED_FIELDS = {FIELD_NAME: VALID_VALUE}
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, VALID_VALUE)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert field_values_exactly_match_dict_values(EXPECTED_FIELDS, metadata)

    def test_is_header_valid_true(self):
        """
        GIVEN is_header field with bool True value
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "is_header"
        VALID_VALUE = True
        EXPECTED_FIELDS = {FIELD_NAME: VALID_VALUE}
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, VALID_VALUE)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert field_values_exactly_match_dict_values(EXPECTED_FIELDS, metadata)

    def test_is_header_valid_false(self):
        """
        GIVEN is_header field with bool False value
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "is_header"
        VALID_VALUE = False
        EXPECTED_FIELDS = {FIELD_NAME: VALID_VALUE}
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, VALID_VALUE)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert field_values_exactly_match_dict_values(EXPECTED_FIELDS, metadata)

if __name__ == "__main__":
    pytest.main([__file__, "-v"])