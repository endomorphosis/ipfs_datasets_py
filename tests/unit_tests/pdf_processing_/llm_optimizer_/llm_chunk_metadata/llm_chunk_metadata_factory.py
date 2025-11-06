#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test data factory for generating LLMChunkMetadata instances and field dictionaries.

Provides methods to create valid baseline data, invalid variations, and edge cases
for comprehensive testing of the LLMChunkMetadata class validation logic.
"""
from datetime import datetime
import time
from typing import Dict, Any


class LLMChunkMetadataTestDataFactory:
    """
    Test data factory for generating LLMChunkMetadata instances and field dictionaries.
    
    Provides methods to create valid baseline data, invalid variations, and edge cases
    for comprehensive testing of the LLMChunkMetadata class validation logic.
    """

    @classmethod
    def create_valid_baseline_data(cls) -> Dict[str, Any]:
        """
        Create a complete dictionary of valid field values for LLMChunkMetadata.
        
        Returns:
            Dict[str, Any]: Dictionary with all 23 required fields populated with valid values.
        """
        current_time = time.time()
        current_iso = datetime.now().isoformat()
        
        return {
            # Source provenance fields
            "element_type": "text",
            "element_id": "elem_12345",
            "section": "introduction",
            "confidence": 0.95,
            "source_file": "document.pdf",
            "extraction_method": "llm_optimization",
            
            # Content metrics fields
            "character_count": 1250,
            "word_count": 200,
            "sentence_count": 15,
            "token_count": 180,
            
            # Processing information fields
            "creation_timestamp": current_time,
            "created_at": current_iso,
            "processing_method": "llm_optimization",
            "tokenizer_used": "cl100k_base",
            "semantic_type": "paragraph",
            
            # Semantic analysis flags
            "has_mixed_elements": False,
            "contains_table": False,
            "contains_figure": False,
            "is_header": False,
            
            # Position and structure fields
            "original_position": '{"x": 100, "y": 200, "width": 500, "height": 300}',
            "chunk_position_in_doc": 5,
            "page_number": 2,
            "total_chunks_on_page": 8
        }

    @classmethod
    def create_minimal_valid_data(cls) -> Dict[str, Any]:
        """
        Create minimal valid data using default values mentioned in docstring.
        
        Returns:
            Dict[str, Any]: Dictionary with minimal valid values and defaults.
        """
        current_time = time.time()
        current_iso = datetime.now().isoformat()
        
        return {
            # Source provenance with defaults
            "element_type": "text",  # default if unknown
            "element_id": "generated_id_001",  # default generated ID
            "section": "unknown",  # default if not provided
            "confidence": 1.0,  # default for calculated fields
            "source_file": "unknown",  # default if not provided
            "extraction_method": "llm_optimization",  # default
            
            # Content metrics (minimal valid values)
            "character_count": 0,
            "word_count": 0,
            "sentence_count": 0,
            "token_count": 0,
            
            # Processing information
            "creation_timestamp": current_time,
            "created_at": current_iso,
            "processing_method": "llm_optimization",  # always this value
            "tokenizer_used": "cl100k_base",
            "semantic_type": "text",
            
            # Semantic analysis flags (minimal)
            "has_mixed_elements": False,
            "contains_table": False,
            "contains_figure": False,
            "is_header": False,
            
            # Position and structure with defaults
            "original_position": "{}",  # default if unknown
            "chunk_position_in_doc": 0,  # default
            "page_number": 1,
            "total_chunks_on_page": 1  # default if unknown
        }

    @classmethod
    def create_data_missing_field(cls, field_name: str) -> Dict[str, Any]:
        """
        Create valid data dictionary with one specific field removed.
        
        Args:
            field_name: Name of field to exclude from the dictionary.
            
        Returns:
            Dict[str, Any]: Valid data dictionary missing the specified field.
        """
        data = cls.create_valid_baseline_data()
        if field_name in data:
            del data[field_name]
        return data

    @classmethod
    def create_data_with_invalid_type(cls, field_name: str, invalid_value: Any) -> Dict[str, Any]:
        """
        Create data dictionary with one field having an invalid type.
        
        Args:
            field_name: Name of field to modify with invalid value.
            invalid_value: Invalid value to assign to the field.
            
        Returns:
            Dict[str, Any]: Data dictionary with one field having invalid type.
        """
        data = cls.create_valid_baseline_data()
        data[field_name] = invalid_value
        return data

    @classmethod
    def make_boundary_value_data(cls, field_name: str, boundary_value: Any) -> Dict[str, Any]:
        """
        Create data dictionary with one field set to a boundary value.
        
        Args:
            field_name: Name of field to set to boundary value.
            boundary_value: Boundary value to test.
            
        Returns:
            Dict[str, Any]: Data dictionary with field at boundary value.
        """
        data = cls.create_valid_baseline_data()
        data[field_name] = boundary_value
        return data

    @classmethod
    def create_logically_inconsistent_data(cls, **field_overrides) -> Dict[str, Any]:
        """
        Create data dictionary with logically inconsistent field values.
        
        Args:
            **field_overrides: Fields to override with inconsistent values.
            
        Returns:
            Dict[str, Any]: Data dictionary with logical inconsistencies.
        """
        data = cls.create_valid_baseline_data()
        data.update(field_overrides)
        return data
