#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for content metrics logical consistency validation.

Tests logical relationships between character_count, word_count, sentence_count,
and token_count fields to ensure they maintain realistic proportions.
"""
import pytest
from pydantic import ValidationError
from textwrap import dedent

from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunkMetadata
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_factory import (
    LLMChunkMetadataTestDataFactory as DataFactory
)


class TestLLMChunkMetadataContentMetricsConsistency:
    """Test suite for content metrics logical consistency validation."""

    def test_word_count_not_exceeding_character_count(self):
        """
        GIVEN word_count and character_count values
        WHEN validating logical relationship
        THEN word_count ≤ character_count
        """
        # Constants
        CHARACTER_COUNT = 100
        WORD_COUNT = 20  # Valid: 20 words in 100 characters is reasonable. TODO According to who?
        
        # Given
        data = DataFactory.create_logically_inconsistent_data(
            character_count=CHARACTER_COUNT,
            word_count=WORD_COUNT
        )
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert metadata.word_count <= metadata.character_count, \
            f"Word count '{metadata.word_count}' exceeds character count '{metadata.character_count}'"

    def test_sentence_count_not_exceeding_word_count(self):
        """
        GIVEN sentence_count and word_count values
        WHEN validating logical relationship
        THEN sentence_count ≤ word_count
        """
        # Constants
        WORD_COUNT = 50
        SENTENCE_COUNT = 5  # Valid: 5 sentences in 50 words is reasonable # TODO According to who?
        
        # Given
        data = DataFactory.create_logically_inconsistent_data(
            word_count=WORD_COUNT,
            sentence_count=SENTENCE_COUNT
        )
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert metadata.sentence_count <= metadata.word_count, \
            f"Sentence count '{metadata.sentence_count}' exceeds word count '{metadata.word_count}'"

    def test_character_count_non_negative(self):
        """
        GIVEN character_count value is non-negative
        WHEN validating value constraints
        THEN character_count ≥ 0
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
        assert metadata.character_count >= BOUNDARY_VALUE, \
            f"Character count must be non-negative, but got '{metadata.character_count}'"

    def test_word_count_non_negative(self):
        """
        GIVEN word_count value
        WHEN validating value constraints
        THEN word_count ≥ 0
        """
        # Constants
        FIELD_NAME = "word_count"
        BOUNDARY_VALUE = 0
        COUNT_DICT = {
            "character_count": 0,
            "sentence_count": 0,
            "token_count": 0
        }

        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, BOUNDARY_VALUE)
        data.update(COUNT_DICT)

        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert metadata.word_count >= BOUNDARY_VALUE, \
            f"Word count must be non-negative, but got '{metadata.word_count}'"

    def test_sentence_count_non_negative(self):
        """
        GIVEN sentence_count value
        WHEN validating value constraints
        THEN sentence_count ≥ 0
        """
        # Constants
        FIELD_NAME = "sentence_count"
        BOUNDARY_VALUE = 0
        COUNT_DICT = {
            "character_count": 0,
            "word_count": 0,
            "token_count": 0
        }

        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, BOUNDARY_VALUE)
        data.update(COUNT_DICT)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert metadata.sentence_count >= BOUNDARY_VALUE, \
            f"Sentence count must be non-negative, but got '{metadata.sentence_count}'"

    def test_token_count_non_negative(self):
        """
        GIVEN token_count value
        WHEN validating value constraints
        THEN token_count ≥ 0
        """
        # Constants
        FIELD_NAME = "token_count"
        BOUNDARY_VALUE = 0
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, BOUNDARY_VALUE)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert metadata.token_count >= BOUNDARY_VALUE, \
            f"Token count '{metadata.token_count}' is not non-negative"

    def test_zero_character_count_implies_zero_word_count(self):
        """
        GIVEN character_count = 0
        WHEN validating logical consistency
        THEN word_count = 0
        AND sentence_count = 0
        AND token_count = 0
        """
        # Constants
        CHARACTER_COUNT = 0
        WORD_COUNT = 0
        SENTENCE_COUNT = 0
        
        # Given
        data = DataFactory.create_logically_inconsistent_data(
            character_count=CHARACTER_COUNT,
            word_count=WORD_COUNT,
            sentence_count=SENTENCE_COUNT
        )
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert metadata.character_count == metadata.word_count, dedent(f"""
        When character_count is '{CHARACTER_COUNT}', 
        word_count must also be '{WORD_COUNT}', got character_count of '{metadata.character_count}', 
        and word_count of '{metadata.word_count}'
        """).strip()

    def test_zero_character_count_implies_zero_sentence_count(self):
        """
        GIVEN character_count = 0
        WHEN validating logical consistency
        THEN sentence_count = 0
        """
        # Constants
        CHARACTER_COUNT = 0
        SENTENCE_COUNT = 0
        WORD_COUNT = 0
        
        # Given
        data = DataFactory.create_logically_inconsistent_data(
            character_count=CHARACTER_COUNT,
            sentence_count=SENTENCE_COUNT,
            word_count=WORD_COUNT
        )
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert metadata.character_count == metadata.sentence_count, dedent(f"""
        When character_count is '{CHARACTER_COUNT}', 
        word_count must also be '{SENTENCE_COUNT}', got character_count of '{metadata.character_count}', 
        and word_count of '{metadata.sentence_count}'
        """).strip()

    def test_zero_word_count_implies_zero_sentence_count(self):
        """
        GIVEN word_count = 0
        WHEN validating logical consistency
        THEN sentence_count = 0
        """
        # Constants
        WORD_COUNT = 0
        SENTENCE_COUNT = 0
        
        # Given
        data = DataFactory.create_logically_inconsistent_data(
            word_count=WORD_COUNT,
            sentence_count=SENTENCE_COUNT
        )
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert metadata.word_count == metadata.sentence_count, dedent(f"""
        When word_count is '{WORD_COUNT}',
        sentence_count must also be '{SENTENCE_COUNT}', got word_count of '{metadata.word_count}',
        and sentence_count of '{metadata.sentence_count}'
        """).strip()

    def test_token_count_correlates_with_word_count(self):
        """
        GIVEN token_count and word_count values
        WHEN validating logical relationship
        THEN token_count to word_count ratio within a 3/4 ratio (e.g. 1 token ≈ 0.75 words)
        """
        # Constants
        WORD_COUNT = 100
        TOKEN_COUNT = 75
        MIN_RATIO_THRESHOLD = 0.5
        MAX_RATIO_THRESHOLD = 1.5
        
        # Given
        data = DataFactory.create_logically_inconsistent_data(
            word_count=WORD_COUNT,
            token_count=TOKEN_COUNT
        )
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        ratio = metadata.token_count / metadata.word_count
        assert MIN_RATIO_THRESHOLD <= ratio <= MAX_RATIO_THRESHOLD, dedent(f"""
            Token to word ratio '{ratio:.2f}' must be between '{MIN_RATIO_THRESHOLD}' and 
            '{MAX_RATIO_THRESHOLD}'. token_count was '{metadata.token_count}', 
            word_count was '{metadata.word_count}'"
        """).strip()

if __name__ == "__main__":
    pytest.main([__file__, "-v"])