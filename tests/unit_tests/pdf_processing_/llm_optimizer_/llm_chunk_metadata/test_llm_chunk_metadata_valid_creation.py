#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for valid LLMChunkMetadata creation scenarios.

Tests successful instantiation of LLMChunkMetadata with valid field combinations
and verifies that all required fields are properly populated and accessible.
"""
import pytest

from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunkMetadata
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_factory import (
    LLMChunkMetadataTestDataFactory as DataFactory
)

from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_test_utils import (
    field_values_exactly_match_dict_values,
    all_words_are_present_in_error_msg
)



class TestLLMChunkMetadataValidCreation:
    """Test suite for valid LLMChunkMetadata creation scenarios."""

    def test_metadata_creation_with_valid_data(self):
        """
        GIVEN a complete set of valid field values for all 23 required fields
        WHEN LLMChunkMetadata is instantiated
        THEN successful instantiation without ValidationError
        """
        # Given
        valid_data = DataFactory.create_valid_baseline_data()
        
        # When
        metadata = LLMChunkMetadata(**valid_data)
        
        # Then
        assert isinstance(metadata, LLMChunkMetadata)

    def test_metadata_fields_populated_correctly(self):
        """
        GIVEN a complete set of valid field values for all 23 required fields
        WHEN LLMChunkMetadata is instantiated
        THEN all fields are populated correctly
        """
        # Constants
        EXPECTED_RESULT = True
        
        # Given
        valid_data = DataFactory.create_valid_baseline_data()

        # When
        metadata = LLMChunkMetadata(**valid_data)

        # Then
        assert field_values_exactly_match_dict_values(valid_data, metadata) == EXPECTED_RESULT

