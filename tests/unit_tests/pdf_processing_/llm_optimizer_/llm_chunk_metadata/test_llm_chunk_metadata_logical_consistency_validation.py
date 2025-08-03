#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for cross-field logical consistency validation.

Tests logical relationships and consistency between different fields
to ensure data integrity and realistic field combinations.
"""
import pytest
from pydantic import ValidationError

from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunkMetadata
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_factory import (
    LLMChunkMetadataTestDataFactory as DataFactory
)

from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_test_utils import (
    all_words_are_present_in_error_msg
)


class TestLLMChunkMetadataLogicalConsistencyValidation:
    """Test suite for cross-field logical consistency validation."""

    def test_word_count_exceeds_character_count_invalid(self):
        """
        GIVEN word_count=100 and character_count=50 (impossible relationship)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with logical consistency message
        """
        # Constants
        CHARACTER_COUNT = 50
        WORD_COUNT = 100
        EXPECTED_WORDS = ["consistency", "logical", "exceed", "word_count", "character_count"]
        
        # Given
        data = DataFactory.create_logically_inconsistent_data(
            character_count=CHARACTER_COUNT,
            word_count=WORD_COUNT
        )
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)

        assert all_words_are_present_in_error_msg(exc_info, EXPECTED_WORDS) == True


    def test_sentence_count_exceeds_word_count_invalid(self):
        """
        GIVEN sentence_count=20 and word_count=10 (impossible relationship)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with logical consistency message
        """
        # Constants
        WORD_COUNT = 10
        SENTENCE_COUNT = 20
        EXPECTED_WORDS = ["sentence_count", "word_count", "consistency", "logical", "exceed"]

        # Given
        data = DataFactory.create_logically_inconsistent_data(
            word_count=WORD_COUNT,
            sentence_count=SENTENCE_COUNT
        )
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)

        assert all_words_are_present_in_error_msg(exc_info, EXPECTED_WORDS) == True


    def test_token_count_extremely_disproportionate_to_word_count(self):
        """
        GIVEN token_count=1000 and word_count=10 (unrealistic ratio)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with token ratio validation message
        """
        # Constants
        WORD_COUNT = 10
        TOKEN_COUNT = 1000
        SENTENCE_COUNT = 2
        EXPECTED_WORDS = ["token_count", "word_count", "ratio", "unrealistic"]
        
        # Given
        data = DataFactory.create_logically_inconsistent_data(
            word_count=WORD_COUNT,
            token_count=TOKEN_COUNT,
            sentence_count=SENTENCE_COUNT
        )
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, EXPECTED_WORDS) == True


    def test_chunk_position_exceeds_total_chunks_invalid(self):
        """
        GIVEN chunk_position_in_doc=5 and total_chunks_on_page=3 (position beyond total)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with position consistency message
        """
        # Constants
        CHUNK_POSITION = 5
        TOTAL_CHUNKS = 3
        EXPECTED_FIELDS = ["chunk_position_in_doc", "total_chunks_on_page"]
        EXPECTED_WORDS = ["position", "exceed", "total"]
        
        # Given
        data = DataFactory.create_logically_inconsistent_data(
            chunk_position_in_doc=CHUNK_POSITION,
            total_chunks_on_page=TOTAL_CHUNKS
        )
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert any(field in str(exc_info.value) for field in EXPECTED_FIELDS)
        assert any(word in str(exc_info.value).lower() for word in EXPECTED_WORDS)

    def test_zero_character_count_with_nonzero_word_count_invalid(self):
        """
        GIVEN character_count=0 and word_count=5 (logical inconsistency)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with zero character consistency message
        """
        # Constants
        CHARACTER_COUNT = 0
        WORD_COUNT = 5
        EXPECTED_FIELDS = ["character_count", "word_count"]
        EXPECTED_WORDS = ["zero", "consistency", "impossible"]
        
        # Given
        data = DataFactory.create_logically_inconsistent_data(
            character_count=CHARACTER_COUNT,
            word_count=WORD_COUNT
        )
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert any(field in str(exc_info.value) for field in EXPECTED_FIELDS)
        assert any(word in str(exc_info.value).lower() for word in EXPECTED_WORDS)

    def test_zero_word_count_with_nonzero_sentence_count_invalid(self):
        """
        GIVEN word_count=0 and sentence_count=2 (logical inconsistency)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with zero word consistency message
        """
        # Constants
        WORD_COUNT = 0
        SENTENCE_COUNT = 2
        EXPECTED_FIELDS = ["word_count", "sentence_count"]
        EXPECTED_WORDS = ["zero", "consistency", "impossible"]
        
        # Given
        data = DataFactory.create_logically_inconsistent_data(
            word_count=WORD_COUNT,
            sentence_count=SENTENCE_COUNT
        )
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert any(field in str(exc_info.value) for field in EXPECTED_FIELDS)
        assert any(word in str(exc_info.value).lower() for word in EXPECTED_WORDS)

    def test_semantic_flags_consistency_with_semantic_type(self):
        """
        GIVEN semantic_type="header" and is_header=False (inconsistent flags)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with semantic consistency message
        """
        # Constants
        SEMANTIC_TYPE = "header"
        IS_HEADER = False
        EXPECTED_FIELDS = ["semantic_type", "is_header"]
        EXPECTED_WORDS = ["consistency", "semantic", "flag"]
        
        # Given
        data = DataFactory.create_logically_inconsistent_data(
            semantic_type=SEMANTIC_TYPE,
            is_header=IS_HEADER
        )
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert any(field in str(exc_info.value) for field in EXPECTED_FIELDS)
        assert any(word in str(exc_info.value).lower() for word in EXPECTED_WORDS)

    def test_creation_timestamp_and_created_at_consistency(self):
        """
        GIVEN creation_timestamp and created_at representing different times
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with timestamp consistency message
        """
        # Constants
        CREATION_TIMESTAMP = 1640995200.0  # Jan 1, 2022
        CREATED_AT = "2025-01-15T10:30:45"  # Different date
        EXPECTED_WORDS = ["creation_timestamp", "created_at", "timestamp", "consistency"]

        # Given
        data = DataFactory.create_logically_inconsistent_data(
            creation_timestamp=CREATION_TIMESTAMP,
            created_at=CREATED_AT
        )
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, EXPECTED_WORDS) == True

    def test_extraction_method_and_processing_method_consistency(self):
        """
        GIVEN  extraction_method="manual"
            AND processing_method="llm_optimization" (extraction method inconsistency)
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError.
        """
        # Constants
        EXTRACTION_METHOD = "manual"
        PROCESSING_METHOD = "llm_optimization"
        EXPECTED_WORDS = ["extraction_method", "processing_method", "consistency", "method", "compatible"]
        
        # Given
        data = DataFactory.create_logically_inconsistent_data(
            extraction_method=EXTRACTION_METHOD,
            processing_method=PROCESSING_METHOD
        )
        
        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)
        
        assert all_words_are_present_in_error_msg(exc_info, EXPECTED_WORDS) == True

if __name__ == "__main__":
    pytest.main([__file__, "-v"])