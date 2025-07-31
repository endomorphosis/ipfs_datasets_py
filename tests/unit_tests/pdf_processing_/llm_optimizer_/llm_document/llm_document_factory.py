#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test data factory for generating LLMDocument instances and field dictionaries.

Provides methods to create valid baseline data, invalid variations, and edge cases
for comprehensive testing of the LLMDocument class validation logic.
"""
from typing import Dict, Any, List
import numpy as np
import time

from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk.llm_chunk_factory import (
    LLMChunkTestDataFactory
)


class LLMDocumentTestDataFactory:
    """
    Test data factory for generating LLMDocument instances and field dictionaries.
    
    Provides methods to create valid baseline data, invalid variations, and edge cases
    for comprehensive testing of the LLMDocument class validation logic.
    """

    @classmethod
    def create_valid_baseline_data(cls) -> Dict[str, Any]:
        """
        Create a complete dictionary of valid field values for LLMDocument.
        
        Returns:
            Dict[str, Any]: Dictionary with all required fields populated with valid values for LLMDocument creation.
        """
        # Create sample chunks for the document
        chunk1 = LLMChunkTestDataFactory.create_chunk_instance(
            chunk_id="chunk_0001",
            content="First chunk of sample document content with meaningful text for testing.",
            source_page=1
        )
        chunk2 = LLMChunkTestDataFactory.create_chunk_instance(
            chunk_id="chunk_0002", 
            content="Second chunk of sample document content that continues the narrative.",
            source_page=1
        )
        chunk3 = LLMChunkTestDataFactory.create_chunk_instance(
            chunk_id="chunk_0003",
            content="Third and final chunk completing the sample document for comprehensive testing.",
            source_page=2
        )

        return {
            "document_id": "doc_12345",
            "title": "Sample Test Document",
            "chunks": [chunk1, chunk2, chunk3],
            "summary": "This is a comprehensive sample document used for testing LLM document processing capabilities. It contains multiple chunks across different pages.",
            "key_entities": [
                {"text": "Sample Test Document", "type": "DOCUMENT", "confidence": 0.95},
                {"text": "testing", "type": "ACTIVITY", "confidence": 0.85},
                {"text": "LLM", "type": "TECHNOLOGY", "confidence": 0.90}
            ],
            "processing_metadata": {
                "optimization_timestamp": time.time(),
                "chunk_count": 3,
                "total_tokens": 540,
                "model_used": "gpt-3.5-turbo",
                "tokenizer_used": "cl100k_base",
                "processing_method": "llm_optimization",
                "extraction_method": "llm_optimization"
            },
            "document_embedding": np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8])
        }

    @classmethod
    def create_minimal_valid_data(cls) -> Dict[str, Any]:
        """
        Create minimal valid data using default values for LLMDocument.
        
        Returns:
            Dict[str, Any]: Dictionary with minimal valid values and defaults for LLMDocument creation.
        """
        # Create a single minimal chunk
        minimal_chunk = LLMChunkTestDataFactory.create_minimal_chunk_instance()

        return {
            "document_id": "doc_0000",
            "title": "Minimal Test Document",
            "chunks": [minimal_chunk],
            "summary": "Minimal document for basic testing.",
            "key_entities": [],
            "processing_metadata": {
                "optimization_timestamp": time.time(),
                "chunk_count": 1,
                "total_tokens": 0,
                "model_used": "test_model",
                "tokenizer_used": "cl100k_base"
            },
            "document_embedding": None
        }

    @classmethod
    def create_data_missing_field(cls, field_name: str) -> Dict[str, Any]:
        """
        Create valid data dictionary with one specific field removed for LLMDocument.
        
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
        Create data dictionary with one field having an invalid type for LLMDocument.
        
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
        Create data dictionary with one field set to a boundary value for LLMDocument.
        
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
        Create data dictionary with logically inconsistent field values for LLMDocument.
        
        Args:
            **field_overrides: Fields to override with inconsistent values.
            
        Returns:
            Dict[str, Any]: Data dictionary with logical inconsistencies.
        """
        data = cls.create_valid_baseline_data()
        data.update(field_overrides)
        return data

    @classmethod
    def create_document_instance(cls, **overrides) -> LLMDocument:
        """
        Create a complete LLMDocument instance with optional field overrides.
        
        Args:
            **overrides: Field values to override in the baseline data.
            
        Returns:
            LLMDocument: Fully constructed LLMDocument instance.
        """
        data = cls.create_valid_baseline_data()
        data.update(overrides)
        return LLMDocument(**data)

    @classmethod
    def create_minimal_document_instance(cls, **overrides) -> LLMDocument:
        """
        Create a minimal LLMDocument instance with optional field overrides.
        
        Args:
            **overrides: Field values to override in the minimal data.
            
        Returns:
            LLMDocument: Minimal LLMDocument instance.
        """
        data = cls.create_minimal_valid_data()
        data.update(overrides)
        return LLMDocument(**data)
