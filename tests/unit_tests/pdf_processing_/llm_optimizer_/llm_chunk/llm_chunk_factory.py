#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test data factory for generating LLMChunk instances and field dictionaries.

Provides methods to create valid baseline data, invalid variations, and edge cases
for comprehensive testing of the LLMChunk class validation logic.
"""
from typing import Dict, Any
import numpy as np

from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMChunk, LLMChunkMetadata
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk_metadata.llm_chunk_metadata_factory import (
    LLMChunkMetadataTestDataFactory
)


class LLMChunkTestDataFactory:
    """
    Test data factory for generating LLMChunk instances and field dictionaries.
    
    Provides methods to create valid baseline data, invalid variations, and edge cases
    for comprehensive testing of the LLMChunk class validation logic.
    """

    @classmethod
    def create_valid_baseline_data(cls) -> Dict[str, Any]:
        """
        Create a complete dictionary of valid field values for LLMChunk.
        
        Returns:
            Dict[str, Any]: Dictionary with all required fields populated with valid values for LLMChunk creation.
        """
        data = LLMChunkMetadataTestDataFactory.create_valid_baseline_data()
        metadata = LLMChunkMetadata(**data)

        return {
            "content": "Sample test content for comprehensive testing of LLM chunk processing.",
            "chunk_id": "chunk_0001",
            "source_page": 2,
            "source_elements": ["paragraph", "text"],
            "token_count": 180,
            "semantic_types": "text",
            "metadata": metadata,
            "relationships": ["chunk_0000", "chunk_0002"],
            "embedding": np.array([0.1, 0.2, 0.3, 0.4, 0.5])
        }

    @classmethod
    def create_minimal_valid_data(cls) -> Dict[str, Any]:
        """
        Create minimal valid data using default values for LLMChunk.
        
        Returns:
            Dict[str, Any]: Dictionary with minimal valid values and defaults for LLMChunk creation.
        """
        data = LLMChunkMetadataTestDataFactory.create_minimal_valid_data()
        metadata = LLMChunkMetadata(**data)

        return {
            "content": "",
            "chunk_id": "chunk_0000",
            "source_page": 1,
            "source_elements": ["text"],
            "token_count": 0,
            "semantic_types": "text",
            "metadata": metadata,
            "relationships": [],
            "embedding": None
        }

    @classmethod
    def create_data_missing_field(cls, field_name: str) -> Dict[str, Any]:
        """
        Create valid data dictionary with one specific field removed for LLMChunk.
        
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
        Create data dictionary with one field having an invalid type for LLMChunk.
        
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
        Create data dictionary with one field set to a boundary value for LLMChunk.
        
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
        Create data dictionary with logically inconsistent field values for LLMChunk.
        
        Args:
            **field_overrides: Fields to override with inconsistent values.
            
        Returns:
            Dict[str, Any]: Data dictionary with logical inconsistencies.
        """
        data = cls.create_valid_baseline_data()
        data.update(field_overrides)
        return data

    @classmethod
    def create_chunk_instance(cls, **overrides) -> LLMChunk:
        """
        Create a complete LLMChunk instance with optional field overrides.
        
        Args:
            **overrides: Field values to override in the baseline data.
            
        Returns:
            LLMChunk: Fully constructed LLMChunk instance.
        """
        data = cls.create_valid_baseline_data()
        data.update(overrides)
        return LLMChunk(**data)

    @classmethod
    def create_minimal_chunk_instance(cls, **overrides) -> LLMChunk:
        """
        Create a minimal LLMChunk instance with optional field overrides.
        
        Args:
            **overrides: Field values to override in the minimal data.
            
        Returns:
            LLMChunk: Minimal LLMChunk instance.
        """
        data = cls.create_minimal_valid_data()
        data.update(overrides)
        return LLMChunk(**data)
