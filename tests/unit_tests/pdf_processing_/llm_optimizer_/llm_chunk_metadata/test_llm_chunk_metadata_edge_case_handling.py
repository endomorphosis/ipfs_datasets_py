#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test suite for edge cases and unusual scenarios.

Tests edge cases including Unicode characters, very long strings,
whitespace handling, and floating point precision issues.
"""
import pytest
from pydantic import ValidationError
from textwrap import dedent


from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunkMetadata
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_factory import (
    LLMChunkMetadataTestDataFactory as DataFactory
)
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_test_utils import (
    all_words_are_present_in_error_msg,
    field_values_exactly_match_dict_values
)


class TestLLMChunkMetadataEdgeCaseHandling:
    """Test suite for edge cases and unusual scenarios."""

    def test_unicode_characters_in_string_fields(self):
        """
        GIVEN string fields containing Unicode characters (emoji, accents)
        WHEN LLMChunkMetadata is instantiated
        THEN field values still contain Unicode characters.
        """
        # Constants
        UNICODE_FIELDS = {
            "element_type": "text_with_émojis_🚀",
            "element_id": "元素_id_🔥",
            "section": "Ñiño_section_测试",
            "source_file": "документ_файл_文档.pdf",
            "semantic_type": "段落_paragraph_абзац"
        }
        
        # Given
        data = DataFactory.create_valid_baseline_data()
        data.update(UNICODE_FIELDS)

        # When
        metadata = LLMChunkMetadata(**data)

        # Then
        assert field_values_exactly_match_dict_values(UNICODE_FIELDS, metadata) == True

    def test_very_long_string_values(self):
        """
        GIVEN string fields with values exceeding length limits.
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError.
        """
        # Constants
        FIELD_NAME = "element_type"
        ERROR_WORDS = ["element_type", "length", "max", "long"]
        
        # Given
        MAX_STRING_LENGTH = LLMChunkMetadata.model_fields[FIELD_NAME].constraints.max_length
        very_long_string = "a" * (MAX_STRING_LENGTH + 1)
        data = DataFactory.make_boundary_value_data(FIELD_NAME, very_long_string)

        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)

        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS) == True


    def test_whitespace_only_string_fields(self):
        """
        GIVEN string fields containing only whitespace characters
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError with non-whitespace validation
        """
        # Constants
        FIELD_NAME = "element_type"
        INVALID_VALUE = "   \t\n  "
        ERROR_WORDS = ["element_type", "whitespace", "empty", "valid"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, INVALID_VALUE)

        # When/Then
        with pytest.raises(ValidationError) as exc_info:
            LLMChunkMetadata(**data)

        assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS) == True


    def test_special_characters_in_identifiers(self):
        """
        GIVEN element_id and source_file with special characters
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error.
        """
        # Constants
        SPECIAL_CHARS_FIELDS = {
            "element_id": "elem-123_456.789@domain#section",
            "source_file": "file_name-v2.1@server[backup].pdf"
        }

        # Given
        data = DataFactory.create_valid_baseline_data()
        data.update(SPECIAL_CHARS_FIELDS)
        
        # When
        metadata = LLMChunkMetadata(**data)

        # Then
        assert field_values_exactly_match_dict_values(SPECIAL_CHARS_FIELDS, metadata) == True


    def test_floating_point_precision_edge_cases(self):
        """
        GIVEN confidence with extreme floating point precision
        WHEN LLMChunkMetadata is instantiated
        THEN floating point precision is maintained in the field.
        """
        # Constants
        FIELD_NAME = "confidence"
        HIGH_PRECISION_VALUE = 0.123456789012345678901234567890
        TOLERANCE = 1e-10  # Allowable precision tolerance
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, HIGH_PRECISION_VALUE)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert abs(metadata.confidence - HIGH_PRECISION_VALUE) < TOLERANCE, dedent(f"""
            Confidence should be approximately '{HIGH_PRECISION_VALUE}',
            but got '{metadata.confidence}' instead.
        """).strip()

    def test_extremely_large_numeric_values(self):
        """
        GIVEN numeric fields with extremely large values near system limits
        WHEN LLMChunkMetadata is instantiated
        THEN proper handling without overflow errors
        """
        # Constants
        VERY_LARGE_INT = 2**31 - 1  # Max 32-bit signed integer
        LARGE_VALUES_FIELDS = {
            "character_count": VERY_LARGE_INT,
            "word_count": VERY_LARGE_INT // 10, 
            "sentence_count": VERY_LARGE_INT // 100,
            "token_count": VERY_LARGE_INT // 5,
        }

        # Given
        data = DataFactory.create_valid_baseline_data()
        data.update(LARGE_VALUES_FIELDS)
   
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        assert metadata.character_count == VERY_LARGE_INT, f"Character count should be {VERY_LARGE_INT}, got {metadata.character_count}"

    def test_iso_timestamp_with_different_timezone_formats(self):
        """
        GIVEN created_at with various valid timezone formats (+00:00, Z, +05:30)
        WHEN LLMChunkMetadata is instantiated
        THEN creation occurs without error for all valid timezone formats
        """
        # Constants
        FIELD_NAME = "created_at"
        TIMEZONE_FORMATS = [
            "2025-01-15T10:30:45+00:00",  # UTC offset
            "2025-01-15T10:30:45Z",       # Zulu time
            "2025-01-15T10:30:45+05:30",  # Positive offset
            "2025-01-15T10:30:45-08:00"   # Negative offset
        ]

        # Given/When/Then
        for timestamp_format in TIMEZONE_FORMATS:
            data = DataFactory.make_boundary_value_data(FIELD_NAME, timestamp_format)
            metadata = LLMChunkMetadata(**data)
            
            assert metadata.created_at == timestamp_format

    def test_json_position_with_nested_complex_structure(self):
        """
        GIVEN original_position with deeply nested JSON structure
        WHEN LLMChunkMetadata is instantiated
        THEN all keys and values are preserved.
        """
        # Constants
        FIELD_NAME = "original_position"
        COMPLEX_JSON = '''
        {
            "page": {
                "dimensions": {"width": 612, "height": 792},
                "margins": {"top": 72, "right": 72, "bottom": 72, "left": 72}
            },
            "element": {
                "bbox": {"x": 100, "y": 200, "width": 300, "height": 50},
                "transforms": [
                    {"type": "translate", "x": 10, "y": 20},
                    {"type": "scale", "factor": 1.2},
                    {"type": "rotate", "angle": 15}
                ],
                "styles": {
                    "font": {"family": "Arial", "size": 12, "weight": "bold"},
                    "color": {"r": 0, "g": 0, "b": 0, "alpha": 1.0}
                }
            }
        }
        '''.strip().replace('\n        ', '').replace('\n    ', '')
        EXPECTED_WORDS = ["page", "dimensions", "width", "height", "margins", "top", "right", "bottom", "left",
                         "element", "bbox", "x", "y", "width", "height", "transforms", "type", "translate",
                         "scale", "rotate", "angle", "styles", "font", "family", "size", "weight", 
                         "color", "r", "g", "b", "alpha"]
        
        # Given
        data = DataFactory.make_boundary_value_data(FIELD_NAME, COMPLEX_JSON)
        
        # When
        metadata = LLMChunkMetadata(**data)
        
        # Then
        position_str = metadata.original_position.lower()
        for word in EXPECTED_WORDS:
            assert word in position_str, f"Word '{word}' not found in original_position"


    def test_semantic_type_with_custom_values(self):
        """
        GIVEN semantic_type with custom/non-standard values
        WHEN LLMChunkMetadata is instantiated
        THEN raise ValidationError.
        """
        # Constants
        FIELD_NAME = "semantic_type"
        CUSTOM_TYPES = [
            "custom_type_not_standard",
            "非标准类型",
            "type-with-dashes",
            "type.with.dots"
        ]
        ERROR_WORDS = ["semantic_type", "valid", "allowed", "enum"]
        
        # Given/When/Then
        for custom_type in CUSTOM_TYPES:
            data = DataFactory.make_boundary_value_data(FIELD_NAME, custom_type)
            
            with pytest.raises(ValidationError) as exc_info:
                LLMChunkMetadata(**data)
            
            assert all_words_are_present_in_error_msg(exc_info, ERROR_WORDS) == True

if __name__ == "__main__":
    pytest.main([__file__, "-v"])