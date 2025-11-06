#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for boundary value testing of all numeric fields.

Tests boundary values for all numeric fields to ensure proper handling
of edge cases at minimum and maximum acceptable values.
"""
import time
from textwrap import dedent


import pytest


from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunkMetadata
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_factory import (
    LLMChunkMetadataTestDataFactory as DataFactory
)
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_test_utils import (
    field_values_exactly_match_dict_values,
    all_words_are_present_in_error_msg
)


class TestLLMChunkMetadataBoundaryValueTesting:
    """Test suite for boundary value testing of all numeric fields."""

    def test_confidence_at_exact_zero_boundary(self):
        """
        GIVEN confidence exactly 0.0 (lower boundary)
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "confidence"
        BOUNDARY_VALUE = 0.0
        EXPECTED_FIELDS = {FIELD_NAME: BOUNDARY_VALUE}
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, BOUNDARY_VALUE)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert field_values_exactly_match_dict_values(EXPECTED_FIELDS, metadata)

    def test_confidence_at_exact_one_boundary(self):
        """
        GIVEN confidence exactly 1.0 (upper boundary)
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "confidence"
        BOUNDARY_VALUE = 1.0
        EXPECTED_FIELDS = {FIELD_NAME: BOUNDARY_VALUE}
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, BOUNDARY_VALUE)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert field_values_exactly_match_dict_values(EXPECTED_FIELDS, metadata)

    def test_character_count_at_zero_boundary(self):
        """
        GIVEN character_count exactly 0 (minimum boundary)
        AND word_count, sentence_count, and token_count also at zero
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "character_count"
        BOUNDARY_VALUE = 0
        COUNT_DICT = {
            "word_count": 0,
            "sentence_count": 0,
            "token_count": 0
        }
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, BOUNDARY_VALUE)
        data.update(COUNT_DICT)
        
        # When
        metadata = LLMChunkMetadata(**data)

        # Then
        assert metadata.character_count == BOUNDARY_VALUE, dedent(f"""
            Character count should be '{BOUNDARY_VALUE}',
            but got '{metadata.character_count}' instead.
        """).strip()

    def test_character_count_at_maximum_realistic_value(self):
        """
        GIVEN character_count at maximum realistic value (10,000,000)
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "character_count"
        BOUNDARY_VALUE = 10_000_000
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, BOUNDARY_VALUE)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert metadata.character_count == BOUNDARY_VALUE, dedent(f"""
            Character count should be '{BOUNDARY_VALUE}',
            but got '{metadata.character_count}' instead.
        """).strip()

    def test_page_number_at_minimum_valid_value(self):
        """
        GIVEN page_number exactly 1 (minimum valid page)
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "page_number"
        BOUNDARY_VALUE = 1
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, BOUNDARY_VALUE)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert metadata.page_number == BOUNDARY_VALUE, dedent(f"""
            Page number should be '{BOUNDARY_VALUE}',
            but got '{metadata.page_number}' instead.
        """).strip()

    def test_page_number_at_maximum_realistic_value(self):
        """
        GIVEN page_number at maximum realistic value (100,000)
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        FIELD_NAME = "page_number"
        BOUNDARY_VALUE = 100_000
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, BOUNDARY_VALUE)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert metadata.page_number == BOUNDARY_VALUE, dedent(f"""
            Page number should be '{BOUNDARY_VALUE}',
            but got '{metadata.page_number}' instead.
        """).strip()

    def test_chunk_position_at_zero_boundary(self):
        """
        GIVEN chunk_position_in_doc exactly 0 (first position)
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        BOUNDARY_VALUE = 0
        UPDATE_DICT = {
            "chunk_position_in_doc": BOUNDARY_VALUE,
            "total_chunks_on_page": 0,  # Minimum valid total chunks
        }
        
        # Given
        data = DataFactory.create_valid_baseline_data()
        data.update(UPDATE_DICT)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert metadata.chunk_position_in_doc == BOUNDARY_VALUE, dedent(f"""
            Chunk position in doc should be '{BOUNDARY_VALUE}',
            but got '{metadata.chunk_position_in_doc}' instead.
        """).strip()

    def test_total_chunks_at_minimum_valid_value(self):
        """
        GIVEN total_chunks_on_page exactly 1 (minimum valid count)
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Constants
        BOUNDARY_VALUE = 1
        UPDATE_DICT = {
            "chunk_position_in_doc": 1,  # Minimum valid chunk position
            "total_chunks_on_page": 1,  # Minimum valid total chunks
        }

        # Given
        data = DataFactory.create_valid_baseline_data()
        data.update(UPDATE_DICT)

        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert metadata.total_chunks_on_page == BOUNDARY_VALUE, dedent(f"""
            Total chunks on page should be '{BOUNDARY_VALUE}',
            but got '{metadata.total_chunks_on_page}' instead.
        """).strip()

    def test_creation_timestamp_at_epoch_zero(self):
        """
        GIVEN creation_timestamp exactly 0.0 (Unix epoch)
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Given
        UNIX_EPOCH = 0.0
        UPDATE_DICT = {
            "creation_timestamp": UNIX_EPOCH,
            "created_at": "1970-01-01T00:00:00Z"
        }
        data = DataFactory.create_valid_baseline_data()
        data.update(UPDATE_DICT)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert metadata.creation_timestamp == UNIX_EPOCH, dedent(f"""
            Creation timestamp should be '{UNIX_EPOCH}',
            but got '{metadata.creation_timestamp}' instead.
        """).strip()

    def test_creation_timestamp_at_current_time_boundary(self):
        """
        GIVEN creation_timestamp at current time boundary
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error
        """
        # Given
        current_time = time.time()
        data = DataFactory.make_boundary_value_data("creation_timestamp", current_time)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert metadata.creation_timestamp == current_time, dedent(f"""
            Creation timestamp should be '{current_time}',
            but got '{metadata.creation_timestamp}' instead.
        """).strip()

if __name__ == "__main__":
    pytest.main([__file__, "-v"])