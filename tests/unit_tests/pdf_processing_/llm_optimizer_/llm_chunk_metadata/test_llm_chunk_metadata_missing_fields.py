#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for missing required field validation.

Tests that LLMChunkMetadata properly validates the presence of all required fields
and raises appropriate ValidationError when any field is missing.
"""
import pytest
from pydantic import ValidationError

from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunkMetadata
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_factory import (
    LLMChunkMetadataTestDataFactory as DataFactory
)
from .llm_chunk_metadata_test_utils import all_words_are_present_in_error_msg


class TestLLMChunkMetadataMissingFields:
    """Test suite for missing required field validation."""

    def test_metadata_creation_missing_element_type(self):
        """
        GIVEN complete field dictionary missing element_type field
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with "missing" error type
        """
        # Constants
        MISSING_FIELD = "element_type"
        ERROR_WORDS = ["element_type", "missing"]
        
        # Given
        data = DataFactory.create_data_missing_field(MISSING_FIELD)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_metadata_creation_missing_element_id(self):
        """
        GIVEN complete field dictionary missing element_id field
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with "missing" error type
        """
        # Constants
        MISSING_FIELD = "element_id"
        ERROR_WORDS = ["element_id", "missing"]
        
        # Given
        data = DataFactory.create_data_missing_field(MISSING_FIELD)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_metadata_creation_missing_section(self):
        """
        GIVEN complete field dictionary missing section field
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with "missing" error type
        """
        # Constants
        MISSING_FIELD = "section"
        ERROR_WORDS = ["section", "missing"]
        
        # Given
        data = DataFactory.create_data_missing_field(MISSING_FIELD)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_metadata_creation_missing_confidence(self):
        """
        GIVEN complete field dictionary missing confidence field
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with "missing" error type
        """
        # Constants
        MISSING_FIELD = "confidence"
        ERROR_WORDS = ["confidence", "missing"]
        
        # Given
        data = DataFactory.create_data_missing_field(MISSING_FIELD)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_metadata_creation_missing_source_file(self):
        """
        GIVEN complete field dictionary missing source_file field
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with "missing" error type
        """
        # Constants
        MISSING_FIELD = "source_file"
        ERROR_WORDS = ["source_file", "missing"]
        
        # Given
        data = DataFactory.create_data_missing_field(MISSING_FIELD)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_metadata_creation_missing_extraction_method(self):
        """
        GIVEN complete field dictionary missing extraction_method field
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with "missing" error type
        """
        # Constants
        MISSING_FIELD = "extraction_method"
        ERROR_WORDS = ["extraction_method", "missing"]
        
        # Given
        data = DataFactory.create_data_missing_field(MISSING_FIELD)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_metadata_creation_missing_character_count(self):
        """
        GIVEN complete field dictionary missing character_count field
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with "missing" error type
        """
        # Constants
        MISSING_FIELD = "character_count"
        ERROR_WORDS = ["character_count", "missing"]
        
        # Given
        data = DataFactory.create_data_missing_field(MISSING_FIELD)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_metadata_creation_missing_word_count(self):
        """
        GIVEN complete field dictionary missing word_count field
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with "missing" error type
        """
        # Constants
        MISSING_FIELD = "word_count"
        ERROR_WORDS = ["word_count", "missing"]
        
        # Given
        data = DataFactory.create_data_missing_field(MISSING_FIELD)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_metadata_creation_missing_sentence_count(self):
        """
        GIVEN complete field dictionary missing sentence_count field
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with "missing" error type
        """
        # Constants
        MISSING_FIELD = "sentence_count"
        ERROR_WORDS = ["sentence_count", "missing"]
        
        # Given
        data = DataFactory.create_data_missing_field(MISSING_FIELD)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_metadata_creation_missing_token_count(self):
        """
        GIVEN complete field dictionary missing token_count field
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with "missing" error type
        """
        # Constants
        MISSING_FIELD = "token_count"
        ERROR_WORDS = ["token_count", "missing"]
        
        # Given
        data = DataFactory.create_data_missing_field(MISSING_FIELD)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_metadata_creation_missing_creation_timestamp(self):
        """
        GIVEN complete field dictionary missing creation_timestamp field
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with "missing" error type
        """
        # Constants
        MISSING_FIELD = "creation_timestamp"
        ERROR_WORDS = ["creation_timestamp", "missing"]
        
        # Given
        data = DataFactory.create_data_missing_field(MISSING_FIELD)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_metadata_creation_missing_created_at(self):
        """
        GIVEN complete field dictionary missing created_at field
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with "missing" error type
        """
        # Constants
        MISSING_FIELD = "created_at"
        ERROR_WORDS = ["created_at", "missing"]
        
        # Given
        data = DataFactory.create_data_missing_field(MISSING_FIELD)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_metadata_creation_missing_processing_method(self):
        """
        GIVEN complete field dictionary missing processing_method field
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with "missing" error type
        """
        # Constants
        MISSING_FIELD = "processing_method"
        ERROR_WORDS = ["processing_method", "missing"]
        
        # Given
        data = DataFactory.create_data_missing_field(MISSING_FIELD)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_metadata_creation_missing_tokenizer_used(self):
        """
        GIVEN complete field dictionary missing tokenizer_used field
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with "missing" error type
        """
        # Constants
        MISSING_FIELD = "tokenizer_used"
        ERROR_WORDS = ["tokenizer_used", "missing"]
        
        # Given
        data = DataFactory.create_data_missing_field(MISSING_FIELD)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_metadata_creation_missing_semantic_type(self):
        """
        GIVEN complete field dictionary missing semantic_type field
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with "missing" error type
        """
        # Constants
        MISSING_FIELD = "semantic_type"
        ERROR_WORDS = ["semantic_type", "missing"]
        
        # Given
        data = DataFactory.create_data_missing_field(MISSING_FIELD)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_metadata_creation_missing_has_mixed_elements(self):
        """
        GIVEN complete field dictionary missing has_mixed_elements field
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with "missing" error type
        """
        # Constants
        MISSING_FIELD = "has_mixed_elements"
        ERROR_WORDS = ["has_mixed_elements", "missing"]
        
        # Given
        data = DataFactory.create_data_missing_field(MISSING_FIELD)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_metadata_creation_missing_contains_table(self):
        """
        GIVEN complete field dictionary missing contains_table field
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with "missing" error type
        """
        # Constants
        MISSING_FIELD = "contains_table"
        ERROR_WORDS = ["contains_table", "missing"]
        
        # Given
        data = DataFactory.create_data_missing_field(MISSING_FIELD)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_metadata_creation_missing_contains_figure(self):
        """
        GIVEN complete field dictionary missing contains_figure field
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with "missing" error type
        """
        # Constants
        MISSING_FIELD = "contains_figure"
        ERROR_WORDS = ["contains_figure", "missing"]
        
        # Given
        data = DataFactory.create_data_missing_field(MISSING_FIELD)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_metadata_creation_missing_is_header(self):
        """
        GIVEN complete field dictionary missing is_header field
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with "missing" error type
        """
        # Constants
        MISSING_FIELD = "is_header"
        ERROR_WORDS = ["is_header", "missing"]
        
        # Given
        data = DataFactory.create_data_missing_field(MISSING_FIELD)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_metadata_creation_missing_original_position(self):
        """
        GIVEN complete field dictionary missing original_position field
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with "missing" error type
        """
        # Constants
        MISSING_FIELD = "original_position"
        ERROR_WORDS = ["original_position", "missing"]
        
        # Given
        data = DataFactory.create_data_missing_field(MISSING_FIELD)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_metadata_creation_missing_chunk_position_in_doc(self):
        """
        GIVEN complete field dictionary missing chunk_position_in_doc field
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with "missing" error type
        """
        # Constants
        MISSING_FIELD = "chunk_position_in_doc"
        ERROR_WORDS = ["chunk_position_in_doc", "missing"]
        
        # Given
        data = DataFactory.create_data_missing_field(MISSING_FIELD)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_metadata_creation_missing_page_number(self):
        """
        GIVEN complete field dictionary missing page_number field
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with "missing" error type
        """
        # Constants
        MISSING_FIELD = "page_number"
        ERROR_WORDS = ["page_number", "missing"]
        
        # Given
        data = DataFactory.create_data_missing_field(MISSING_FIELD)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

    def test_metadata_creation_missing_total_chunks_on_page(self):
        """
        GIVEN complete field dictionary missing total_chunks_on_page field
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with "missing" error type
        """
        # Constants
        MISSING_FIELD = "total_chunks_on_page"
        ERROR_WORDS = ["total_chunks_on_page", "missing"]
        
        # Given
        data = DataFactory.create_data_missing_field(MISSING_FIELD)
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS)

if __name__ == "__main__":
    pytest.main([__file__, "-v"])