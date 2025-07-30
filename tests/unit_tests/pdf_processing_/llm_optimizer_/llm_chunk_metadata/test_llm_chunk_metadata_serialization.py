#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for serialization and deserialization.

Tests serialization to dict, deserialization from dict, and round-trip
preservation of data for LLMChunkMetadata instances.
"""
import pytest
from pydantic import ValidationError

from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunkMetadata
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_factory import (
    LLMChunkMetadataTestDataFactory as DataFactory
)
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_test_utils import (
    field_values_exactly_match_dict_values,
    all_words_are_present_in_error_msg
)


class TestLLMChunkMetadataSerialization:
    """Test suite for serialization and deserialization."""

    def test_serialization_produces_complete_dict(self):
        """
        GIVEN a valid LLMChunkMetadata instance
        WHEN serialized using .model_dump()
        THEN dict with all 23 fields present
        """
        # Constants
        EXPECTED_FIELD_COUNT = 23
        EXPECTED_FIELDS = {
            "element_type", "element_id", "section", "confidence", "source_file", 
            "extraction_method", "character_count", "word_count", "sentence_count", 
            "token_count", "creation_timestamp", "created_at", "processing_method", 
            "tokenizer_used", "semantic_type", "has_mixed_elements", "contains_table", 
            "contains_figure", "is_header", "original_position", "chunk_position_in_doc", 
            "page_number", "total_chunks_on_page"
        }
        
        # Given
        valid_data = DataFactory.create_valid_baseline_data()
        metadata = LLMChunkMetadata(**valid_data)
        
        # When
        serialized = metadata.model_dump()
        
        # Then
        assert isinstance(serialized, dict)
        assert len(serialized) == EXPECTED_FIELD_COUNT
        assert set(serialized.keys()) == EXPECTED_FIELDS

    def test_serialization_preserves_field_values(self):
        """
        GIVEN a valid LLMChunkMetadata instance
        WHEN serialized using .model_dump()
        THEN dict values match original instance values exactly
        """
        # Given
        valid_data = DataFactory.create_valid_baseline_data()
        metadata = LLMChunkMetadata(**valid_data)
        
        # When
        serialized = metadata.model_dump()
        
        # Then
        assert field_values_exactly_match_dict_values(valid_data, metadata) == True
        for field_name, expected_value in valid_data.items():
            assert serialized[field_name] == expected_value
            assert type(serialized[field_name]) == type(expected_value)

    def test_deserialization_creates_equivalent_instance(self):
        """
        GIVEN a serialized LLMChunkMetadata dict
        WHEN deserialized using LLMChunkMetadata(**dict_data)
        THEN equivalent instance to original
        """
        # Given
        valid_data = DataFactory.create_valid_baseline_data()
        original_metadata = LLMChunkMetadata(**valid_data)
        serialized = original_metadata.model_dump()
        
        # When
        deserialized_metadata = LLMChunkMetadata(**serialized)
        
        # Then
        assert deserialized_metadata == original_metadata
        assert deserialized_metadata is not original_metadata  # Different instances

    def test_round_trip_preserves_all_field_types(self):
        """
        GIVEN a valid LLMChunkMetadata instance
        WHEN serialized and then deserialized
        THEN all field types preserved through round-trip
        """
        # Constants
        EXPECTED_TYPES = {
            "element_type": str,
            "confidence": float,
            "character_count": int,
            "creation_timestamp": float,
            "has_mixed_elements": bool,
            "page_number": int
        }
        
        # Given
        valid_data = DataFactory.create_valid_baseline_data()
        original_metadata = LLMChunkMetadata(**valid_data)
        
        # When
        serialized = original_metadata.model_dump()
        round_trip_metadata = LLMChunkMetadata(**serialized)
        
        # Then
        assert type(round_trip_metadata.element_type) == EXPECTED_TYPES["element_type"]
        assert type(round_trip_metadata.confidence) == EXPECTED_TYPES["confidence"]
        assert type(round_trip_metadata.character_count) == EXPECTED_TYPES["character_count"]
        assert type(round_trip_metadata.creation_timestamp) == EXPECTED_TYPES["creation_timestamp"]
        assert type(round_trip_metadata.has_mixed_elements) == EXPECTED_TYPES["has_mixed_elements"]
        assert type(round_trip_metadata.page_number) == EXPECTED_TYPES["page_number"]

    def test_round_trip_has_no_data_loss(self):
        """
        GIVEN a valid LLMChunkMetadata instance
        WHEN serialized and then deserialized
        THEN all field values to match original instance
        """
        # Given
        valid_data = DataFactory.create_valid_baseline_data()
        original_metadata = LLMChunkMetadata(**valid_data)
        
        # When
        serialized = original_metadata.model_dump()
        round_trip_metadata = LLMChunkMetadata(**serialized)
        
        # Then
        assert round_trip_metadata == original_metadata
        assert field_values_exactly_match_dict_values(valid_data, round_trip_metadata) == True

if __name__ == "__main__":
    pytest.main([__file__, "-v"])