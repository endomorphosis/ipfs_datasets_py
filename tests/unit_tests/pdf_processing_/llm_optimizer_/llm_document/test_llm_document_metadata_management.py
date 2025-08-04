#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer.py
# Auto-generated on 2025-07-07 02:28:56"

from datetime import datetime
import pytest
import os

import os
import pytest
import time
import numpy as np

from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

home_dir = os.path.expanduser('~')
file_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer.py")
md_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/llm_optimizer_stubs.md")

# Make sure the input file and documentation file exist.
assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."

from ipfs_datasets_py.pdf_processing.llm_optimizer import (
    ChunkOptimizer,
    LLMOptimizer,
    TextProcessor,
    LLMChunk,
    LLMDocument
)

from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_document.llm_document_factory import (
    LLMDocumentTestDataFactory
)
from tests.unit_tests.pdf_processing_.llm_optimizer_.llm_chunk.llm_chunk_factory import (
    LLMChunkTestDataFactory
)


# Check if each classes methods are accessible:
assert LLMOptimizer._initialize_models
assert LLMOptimizer.optimize_for_llm
assert LLMOptimizer._extract_structured_text
assert LLMOptimizer._generate_document_summary
assert LLMOptimizer._create_optimal_chunks
assert LLMOptimizer._create_chunk
assert LLMOptimizer._establish_chunk_relationships
assert LLMOptimizer._generate_embeddings
assert LLMOptimizer._extract_key_entities
assert LLMOptimizer._generate_document_embedding
assert LLMOptimizer._count_tokens
assert LLMOptimizer._get_chunk_overlap
assert TextProcessor.split_sentences
assert TextProcessor.extract_keywords
assert ChunkOptimizer.optimize_chunk_boundaries


# 4. Check if the modules's imports are accessible:
try:
    import asyncio
    import logging
    from typing import Dict, List, Any, Optional
    from dataclasses import dataclass
    import re

    import tiktoken
    from transformers import AutoTokenizer
    import numpy as np
    from sentence_transformers import SentenceTransformer
except ImportError as e:
    raise ImportError(f"Failed to import necessary modules: {e}")



class TestLLMDocumentMetadataManagement:
    """Test LLMDocument processing metadata management."""

    def test_processing_metadata_has_string_keys(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN validating metadata key types
        THEN expect all keys to be strings
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata validation",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        comprehensive_metadata = {
            "processing_time": 2.45,
            "model": "advanced_optimizer_v2",
            "version": "1.2.3",
            "chunk_count": 5,
            "token_total": 150,
            "entities_found": 3,
            "confidence_avg": 0.89,
            "timestamp": "2024-01-01T12:00:00Z",
            "source_file": "document.pdf",
            "page_count": 10,
            "optimization_enabled": True,
            "chunk_overlap": 200,
            "min_chunk_size": 100,
            "max_chunk_size": 2048
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Structure Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata structure",
            key_entities=[],
            processing_metadata=comprehensive_metadata
        )
        
        # When/Then - validate all keys are strings
        for key in document.processing_metadata.keys():
            assert isinstance(key, str)

    def test_processing_metadata_has_non_empty_keys(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN validating metadata key lengths
        THEN expect all keys to be non-empty strings
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata validation",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        comprehensive_metadata = {
            "processing_time": 2.45,
            "model": "advanced_optimizer_v2",
            "version": "1.2.3"
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Structure Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata structure",
            key_entities=[],
            processing_metadata=comprehensive_metadata
        )
        
        # When/Then - validate keys are non-empty
        for key in document.processing_metadata.keys():
            assert len(key) > 0

    def test_processing_metadata_processing_time_type(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN validating processing_time field type
        THEN expect processing_time to be numeric
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata validation",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Structure Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata structure",
            key_entities=[],
            processing_metadata={"processing_time": 2.45}
        )
        
        # When/Then
        assert isinstance(document.processing_metadata["processing_time"], (int, float))

    def test_processing_metadata_model_type(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN validating model field type
        THEN expect model to be string
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata validation",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Structure Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata structure",
            key_entities=[],
            processing_metadata={"model": "advanced_optimizer_v2"}
        )
        
        # When/Then
        assert isinstance(document.processing_metadata["model"], str)

    def test_processing_metadata_version_type(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN validating version field type
        THEN expect version to be string
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata validation",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Structure Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata structure",
            key_entities=[],
            processing_metadata={"version": "1.2.3"}
        )
        
        # When/Then
        assert isinstance(document.processing_metadata["version"], str)

    def test_processing_metadata_chunk_count_type(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN validating chunk_count field type
        THEN expect chunk_count to be integer
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata validation",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Structure Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata structure",
            key_entities=[],
            processing_metadata={"chunk_count": 5}
        )
        
        # When/Then
        assert isinstance(document.processing_metadata["chunk_count"], int)

    def test_processing_metadata_token_total_type(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN validating token_total field type
        THEN expect token_total to be integer
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata validation",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Structure Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata structure",
            key_entities=[],
            processing_metadata={"token_total": 150}
        )
        
        # When/Then
        assert isinstance(document.processing_metadata["token_total"], int)

    def test_processing_metadata_entities_found_type(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN validating entities_found field type
        THEN expect entities_found to be integer
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata validation",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Structure Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata structure",
            key_entities=[],
            processing_metadata={"entities_found": 3}
        )
        
        # When/Then
        assert isinstance(document.processing_metadata["entities_found"], int)

    def test_processing_metadata_confidence_avg_type(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN validating confidence_avg field type
        THEN expect confidence_avg to be numeric
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata validation",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Structure Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata structure",
            key_entities=[],
            processing_metadata={"confidence_avg": 0.89}
        )
        
        # When/Then
        assert isinstance(document.processing_metadata["confidence_avg"], (int, float))

    def test_processing_metadata_timestamp_type(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN validating timestamp field type
        THEN expect timestamp to be string
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata validation",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Structure Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata structure",
            key_entities=[],
            processing_metadata={"timestamp": "2024-01-01T12:00:00Z"}
        )
        
        # When/Then
        assert isinstance(document.processing_metadata["timestamp"], str)

    def test_processing_metadata_optimization_enabled_type(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN validating optimization_enabled field type
        THEN expect optimization_enabled to be boolean
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata validation",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Structure Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata structure",
            key_entities=[],
            processing_metadata={"optimization_enabled": True}
        )
        
        # When/Then
        assert isinstance(document.processing_metadata["optimization_enabled"], bool)

    def test_processing_metadata_processing_time_positive(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN validating processing_time value constraint
        THEN expect processing_time to be positive
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata validation",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Structure Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata structure",
            key_entities=[],
            processing_metadata={"processing_time": 2.45}
        )
        
        # When/Then
        assert document.processing_metadata["processing_time"] > 0

    def test_processing_metadata_chunk_count_non_negative(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN validating chunk_count value constraint
        THEN expect chunk_count to be non-negative
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata validation",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Structure Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata structure",
            key_entities=[],
            processing_metadata={"chunk_count": 5}
        )
        
        # When/Then
        assert document.processing_metadata["chunk_count"] >= 0

    def test_processing_metadata_token_total_non_negative(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN validating token_total value constraint
        THEN expect token_total to be non-negative
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata validation",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Structure Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata structure",
            key_entities=[],
            processing_metadata={"token_total": 150}
        )
        
        # When/Then
        assert document.processing_metadata["token_total"] >= 0

    def test_processing_metadata_entities_found_non_negative(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN validating entities_found value constraint
        THEN expect entities_found to be non-negative
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata validation",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Structure Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata structure",
            key_entities=[],
            processing_metadata={"entities_found": 3}
        )
        
        # When/Then
        assert document.processing_metadata["entities_found"] >= 0

    def test_processing_metadata_confidence_avg_range(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN validating confidence_avg value constraint
        THEN expect confidence_avg to be between 0 and 1
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata validation",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Structure Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata structure",
            key_entities=[],
            processing_metadata={"confidence_avg": 0.89}
        )
        
        # When/Then
        assert 0.0 <= document.processing_metadata["confidence_avg"] <= 1.0

    def test_processing_metadata_modification_existing_field(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN existing metadata field is modified
        THEN expect modification to be reflected in instance
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata modification",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        initial_metadata = {
            "processing_time": 1.23,
            "model": "initial_model",
            "chunk_count": 3,
            "confidence_avg": 0.85
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Modification Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata modifications",
            key_entities=[],
            processing_metadata=initial_metadata.copy()
        )
        
        # When - modify existing metadata
        document.processing_metadata["processing_time"] = 2.45
        
        # Then - modification should be reflected
        assert document.processing_metadata["processing_time"] == 2.45

    def test_processing_metadata_modification_string_field(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN existing string metadata field is modified
        THEN expect string modification to be reflected in instance
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata modification",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        initial_metadata = {
            "processing_time": 1.23,
            "model": "initial_model",
            "chunk_count": 3,
            "confidence_avg": 0.85
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Modification Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata modifications",
            key_entities=[],
            processing_metadata=initial_metadata.copy()
        )
        
        # When - modify existing string metadata
        document.processing_metadata["model"] = "updated_model"
        
        # Then - modification should be reflected
        assert document.processing_metadata["model"] == "updated_model"

    def test_processing_metadata_add_new_field(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN new metadata field is added
        THEN expect new field to be added to metadata
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata modification",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        initial_metadata = {
            "processing_time": 1.23,
            "model": "initial_model",
            "chunk_count": 3,
            "confidence_avg": 0.85
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Modification Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata modifications",
            key_entities=[],
            processing_metadata=initial_metadata.copy()
        )
        
        # When - add new metadata
        document.processing_metadata["new_field"] = "new_value"
        
        # Then - new field should be added
        assert document.processing_metadata["new_field"] == "new_value"

    def test_processing_metadata_add_timestamp_field(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN timestamp metadata field is added
        THEN expect timestamp field to be added to metadata
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata modification",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        initial_metadata = {
            "processing_time": 1.23,
            "model": "initial_model",
            "chunk_count": 3,
            "confidence_avg": 0.85
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Modification Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata modifications",
            key_entities=[],
            processing_metadata=initial_metadata.copy()
        )
        
        # When - add timestamp metadata
        document.processing_metadata["timestamp"] = "2024-01-01T12:00:00Z"
        
        # Then - timestamp field should be added
        assert document.processing_metadata["timestamp"] == "2024-01-01T12:00:00Z"

    def test_processing_metadata_size_after_additions(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN new metadata fields are added
        THEN expect metadata size to increase correctly
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata modification",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        initial_metadata = {
            "processing_time": 1.23,
            "model": "initial_model",
            "chunk_count": 3,
            "confidence_avg": 0.85
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Modification Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata modifications",
            key_entities=[],
            processing_metadata=initial_metadata.copy()
        )
        
        # When - add new metadata fields
        document.processing_metadata["new_field"] = "new_value"
        document.processing_metadata["timestamp"] = "2024-01-01T12:00:00Z"
        
        # Then - size should reflect additions
        assert len(document.processing_metadata) == 6

    def test_processing_metadata_remove_field(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN metadata field is removed
        THEN expect field to be removed from metadata
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata modification",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        initial_metadata = {
            "processing_time": 1.23,
            "model": "initial_model",
            "chunk_count": 3,
            "confidence_avg": 0.85
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Modification Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata modifications",
            key_entities=[],
            processing_metadata=initial_metadata.copy()
        )
        
        # When - remove metadata
        del document.processing_metadata["chunk_count"]
        
        # Then - field should be removed
        assert "chunk_count" not in document.processing_metadata

    def test_processing_metadata_size_after_removal(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN metadata field is removed
        THEN expect metadata size to decrease correctly
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata modification",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        initial_metadata = {
            "processing_time": 1.23,
            "model": "initial_model",
            "chunk_count": 3,
            "confidence_avg": 0.85
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Modification Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata modifications",
            key_entities=[],
            processing_metadata=initial_metadata.copy()
        )
        
        # Add fields first
        document.processing_metadata["new_field"] = "new_value"
        document.processing_metadata["timestamp"] = "2024-01-01T12:00:00Z"
        
        # When - remove metadata
        del document.processing_metadata["chunk_count"]
        
        # Then - size should reflect removal
        assert len(document.processing_metadata) == 5

    def test_processing_metadata_remaining_field_confidence(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN metadata field is removed
        THEN expect remaining confidence field to be intact
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata modification",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        initial_metadata = {
            "processing_time": 1.23,
            "model": "initial_model",
            "chunk_count": 3,
            "confidence_avg": 0.85
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Modification Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata modifications",
            key_entities=[],
            processing_metadata=initial_metadata.copy()
        )
        
        # Modify and add fields
        document.processing_metadata["processing_time"] = 2.45
        document.processing_metadata["model"] = "updated_model"
        document.processing_metadata["new_field"] = "new_value"
        document.processing_metadata["timestamp"] = "2024-01-01T12:00:00Z"
        del document.processing_metadata["chunk_count"]
        
        # Then - confidence field should remain intact
        assert document.processing_metadata["confidence_avg"] == 0.85

    def test_processing_metadata_remaining_field_processing_time(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN metadata field is removed
        THEN expect remaining processing_time field to be intact
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata modification",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        initial_metadata = {
            "processing_time": 1.23,
            "model": "initial_model",
            "chunk_count": 3,
            "confidence_avg": 0.85
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Modification Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata modifications",
            key_entities=[],
            processing_metadata=initial_metadata.copy()
        )
        
        # Modify and add fields
        document.processing_metadata["processing_time"] = 2.45
        document.processing_metadata["model"] = "updated_model"
        document.processing_metadata["new_field"] = "new_value"
        document.processing_metadata["timestamp"] = "2024-01-01T12:00:00Z"
        del document.processing_metadata["chunk_count"]
        
        # Then - processing_time field should remain intact
        assert document.processing_metadata["processing_time"] == 2.45

    def test_processing_metadata_remaining_field_model(self):
        """
        GIVEN LLMDocument instance with processing_metadata
        WHEN metadata field is removed
        THEN expect remaining model field to be intact
        """
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for metadata modification",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        initial_metadata = {
            "processing_time": 1.23,
            "model": "initial_model",
            "chunk_count": 3,
            "confidence_avg": 0.85
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Metadata Modification Test",
            chunks=[sample_chunk],
            summary="Document for testing metadata modifications",
            key_entities=[],
            processing_metadata=initial_metadata.copy()
        )
        
        # Modify and add fields
        document.processing_metadata["processing_time"] = 2.45
        document.processing_metadata["model"] = "updated_model"
        document.processing_metadata["new_field"] = "new_value"
        document.processing_metadata["timestamp"] = "2024-01-01T12:00:00Z"
        del document.processing_metadata["chunk_count"]
        
        # Then - model field should remain intact
        assert document.processing_metadata["model"] == "updated_model"

    def test_metadata_timestamp_tracking(self):
        """
        GIVEN LLMDocument instance with processing_metadata containing timestamps
        WHEN accessing timestamp information
        THEN expect:
            - Valid timestamp formats
            - Chronological consistency
            - Processing time tracking
        """
        from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
        from datetime import datetime
        import re
        
        # Given
        sample_chunk = LLMChunkTestDataFactory.create_chunk_instance(
            content="Test content for timestamp tracking",
            chunk_id="chunk_0001",
            source_page=1,
            token_count=10
        )
        
        timestamp_metadata = {
            "created_at": "2024-01-01T10:00:00Z",
            "started_at": "2024-01-01T10:00:05Z",
            "completed_at": "2024-01-01T10:02:50Z",
            "processing_time": 165.0,  # seconds
            "last_modified": "2024-01-01T10:02:50Z",
            "version_timestamp": "2024-01-01T09:59:45Z"
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Timestamp Tracking Test",
            chunks=[sample_chunk],
            summary="Document for testing timestamp tracking",
            key_entities=[],
            processing_metadata=timestamp_metadata
        )
        
        # When/Then - validate timestamp formats (ISO 8601)
        iso_pattern = r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$'
        
        timestamp_fields = ["created_at", "started_at", "completed_at", "last_modified", "version_timestamp"]
        for field in timestamp_fields:
            timestamp = document.processing_metadata[field]
            assert isinstance(timestamp, str), f"{field} should be string"
            assert re.match(iso_pattern, timestamp), f"{field} should be valid ISO 8601 format: {timestamp}"
        
        # When/Then - validate chronological consistency
        created_time = datetime.fromisoformat(document.processing_metadata["created_at"].replace('Z', '+00:00'))
        started_time = datetime.fromisoformat(document.processing_metadata["started_at"].replace('Z', '+00:00'))
        completed_time = datetime.fromisoformat(document.processing_metadata["completed_at"].replace('Z', '+00:00'))
        version_time = datetime.fromisoformat(document.processing_metadata["version_timestamp"].replace('Z', '+00:00'))
        
        # Chronological order should be: version <= created <= started <= completed
        assert version_time <= created_time, "version_timestamp should be before or equal to created_at"
        assert created_time <= started_time, "created_at should be before or equal to started_at"
        assert started_time <= completed_time, "started_at should be before completed_at"
        
        # When/Then - validate processing time tracking
        actual_duration = (completed_time - started_time).total_seconds()
        recorded_duration = document.processing_metadata["processing_time"]
        
        assert isinstance(recorded_duration, (int, float)), "processing_time should be numeric"
        assert recorded_duration > 0, "processing_time should be positive"
        assert abs(actual_duration - recorded_duration) < 1.0, f"Processing time mismatch: actual={actual_duration}, recorded={recorded_duration}"
        
        # Verify specific timestamp values
        assert document.processing_metadata["created_at"] == "2024-01-01T10:00:00Z"
        assert document.processing_metadata["started_at"] == "2024-01-01T10:00:05Z"
        assert document.processing_metadata["completed_at"] == "2024-01-01T10:02:50Z"
        assert document.processing_metadata["processing_time"] == 165.0





class TestLLMDocumentMetadataCountTracking:
    """Unit tests for LLMDocument metadata count tracking functionality."""

    def test_metadata_chunk_count_matches_actual_chunks(self):
        """
        GIVEN LLMDocument instance with processing_metadata containing chunk count
        WHEN validating chunk count consistency
        THEN expect chunk_count to match actual number of chunks
        """
        # Get encoding for token counting
        encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")

        # Given - create multiple chunks with known token counts
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk with specific token count",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=len(encoding.encode("First chunk with specific token count"))
            ),
            LLMChunkTestDataFactory.create_chunk_instance(
                content="Second chunk with different token count",
                chunk_id="chunk_0002",
                source_page=1,
                token_count=len(encoding.encode("Second chunk with different token count"))
            ),
            LLMChunkTestDataFactory.create_chunk_instance(
                content="Third chunk completing the set",
                chunk_id="chunk_0003",
                source_page=2,
                token_count=len(encoding.encode("Third chunk completing the set"))
            )
        ]
        
        # Create entities for counting
        key_entities = [
            {"type": "PERSON", "value": "John Doe", "confidence": 0.95},
            {"type": "ORG", "value": "OpenAI", "confidence": 0.92},
            {"type": "GPE", "value": "San Francisco", "confidence": 0.88},
            {"type": "DATE", "value": "January 1st, 2024", "confidence": 0.85}
        ]
        
        expected_chunk_count = len(chunks)
        
        count_metadata = {
            "chunk_count": expected_chunk_count
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Count Tracking Test",
            chunks=chunks,
            summary="Document for testing count tracking consistency",
            key_entities=key_entities,
            processing_metadata=count_metadata
        )
        
        # When/Then
        assert document.processing_metadata["chunk_count"] == len(document.chunks)

    def test_metadata_entity_count_matches_actual_entities(self):
        """
        GIVEN LLMDocument instance with processing_metadata containing entity count
        WHEN validating entity count consistency
        THEN expect entity_count to match actual number of entities
        """
        # Get encoding for token counting
        encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")

        # Given - create multiple chunks with known token counts
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk with specific token count",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=len(encoding.encode("First chunk with specific token count"))
            )
        ]
        
        # Create entities for counting
        key_entities = [
            {"type": "PERSON", "value": "John Doe", "confidence": 0.95},
            {"type": "ORG", "value": "OpenAI", "confidence": 0.92},
            {"type": "GPE", "value": "San Francisco", "confidence": 0.88},
            {"type": "DATE", "value": "January 1st, 2024", "confidence": 0.85}
        ]
        
        expected_entity_count = len(key_entities)
        
        count_metadata = {
            "entity_count": expected_entity_count
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Count Tracking Test",
            chunks=chunks,
            summary="Document for testing count tracking consistency",
            key_entities=key_entities,
            processing_metadata=count_metadata
        )
        
        # When/Then
        assert document.processing_metadata["entity_count"] == len(document.key_entities)

    def test_metadata_token_total_matches_actual_tokens(self):
        """
        GIVEN LLMDocument instance with processing_metadata containing token total
        WHEN validating token total consistency
        THEN expect token_total to match sum of chunk token counts
        """
        # Get encoding for token counting
        encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")

        # Given - create multiple chunks with known token counts
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk with specific token count",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=len(encoding.encode("First chunk with specific token count"))
            ),
            LLMChunkTestDataFactory.create_chunk_instance(
                content="Second chunk with different token count",
                chunk_id="chunk_0002",
                source_page=1,
                token_count=len(encoding.encode("Second chunk with different token count"))
            )
        ]
        
        expected_token_total = sum(chunk.token_count for chunk in chunks)
        
        count_metadata = {
            "token_total": expected_token_total
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Count Tracking Test",
            chunks=chunks,
            summary="Document for testing count tracking consistency",
            key_entities=[],
            processing_metadata=count_metadata
        )
        
        # When/Then
        actual_token_total = sum(chunk.token_count for chunk in document.chunks)
        assert document.processing_metadata["token_total"] == actual_token_total

    def test_metadata_page_count_matches_actual_pages(self):
        """
        GIVEN LLMDocument instance with processing_metadata containing page count
        WHEN validating page count consistency
        THEN expect page_count to match number of unique pages
        """
        # Get encoding for token counting
        encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")

        # Given - create multiple chunks with known token counts
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk with specific token count",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=len(encoding.encode("First chunk with specific token count"))
            ),
            LLMChunkTestDataFactory.create_chunk_instance(
                content="Second chunk with different token count",
                chunk_id="chunk_0002",
                source_page=1,
                token_count=len(encoding.encode("Second chunk with different token count"))
            ),
            LLMChunkTestDataFactory.create_chunk_instance(
                content="Third chunk completing the set",
                chunk_id="chunk_0003",
                source_page=2,
                token_count=len(encoding.encode("Third chunk completing the set"))
            )
        ]
        
        expected_page_count = len(set(chunk.source_page for chunk in chunks))
        
        count_metadata = {
            "page_count": expected_page_count
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Count Tracking Test",
            chunks=chunks,
            summary="Document for testing count tracking consistency",
            key_entities=[],
            processing_metadata=count_metadata
        )
        
        # When/Then
        actual_page_count = len(set(chunk.source_page for chunk in document.chunks))
        assert document.processing_metadata["page_count"] == actual_page_count

    def test_metadata_paragraph_count_matches_actual_paragraphs(self):
        """
        GIVEN LLMDocument instance with processing_metadata containing paragraph count
        WHEN validating paragraph count consistency
        THEN expect paragraph_count to match actual number of paragraph chunks
        """
        # Get encoding for token counting
        encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")

        # Given - create chunks with specific source elements
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First paragraph chunk",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=len(encoding.encode("First paragraph chunk")),
                source_elements=["paragraph"]
            ),
            LLMChunkTestDataFactory.create_chunk_instance(
                content="Second paragraph chunk",
                chunk_id="chunk_0002",
                source_page=1,
                token_count=len(encoding.encode("Second paragraph chunk")),
                source_elements=["paragraph"]
            ),
            LLMChunkTestDataFactory.create_chunk_instance(
                content="Table chunk",
                chunk_id="chunk_0003",
                source_page=2,
                token_count=len(encoding.encode("Table chunk")),
                source_elements=["table"]
            )
        ]
        
        expected_paragraph_count = len([c for c in chunks if c.source_elements == ["paragraph"]])
        
        count_metadata = {
            "paragraph_count": expected_paragraph_count
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Count Tracking Test",
            chunks=chunks,
            summary="Document for testing count tracking consistency",
            key_entities=[],
            processing_metadata=count_metadata
        )
        
        # When/Then
        actual_paragraph_count = len([c for c in document.chunks if c.source_elements == ["paragraph"]])
        assert document.processing_metadata["paragraph_count"] == actual_paragraph_count

    def test_metadata_table_count_matches_actual_tables(self):
        """
        GIVEN LLMDocument instance with processing_metadata containing table count
        WHEN validating table count consistency
        THEN expect table_count to match actual number of table chunks
        """
        # Get encoding for token counting
        encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")

        # Given - create chunks with specific source elements
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First paragraph chunk",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=len(encoding.encode("First paragraph chunk")),
                source_elements=["paragraph"]
            ),
            LLMChunkTestDataFactory.create_chunk_instance(
                content="Table chunk",
                chunk_id="chunk_0002",
                source_page=2,
                token_count=len(encoding.encode("Table chunk")),
                source_elements=["table"]
            )
        ]
        
        expected_table_count = len([c for c in chunks if c.source_elements == ["table"]])
        
        count_metadata = {
            "table_count": expected_table_count
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Count Tracking Test",
            chunks=chunks,
            summary="Document for testing count tracking consistency",
            key_entities=[],
            processing_metadata=count_metadata
        )
        
        # When/Then
        actual_table_count = len([c for c in document.chunks if c.source_elements == ["table"]])
        assert document.processing_metadata["table_count"] == actual_table_count

    def test_metadata_text_chunks_count_matches_actual_text_chunks(self):
        """
        GIVEN LLMDocument instance with processing_metadata containing text chunks count
        WHEN validating text chunks count consistency
        THEN expect text_chunks to match actual number of text semantic type chunks
        """
        # Get encoding for token counting
        encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")

        # Given - create chunks with specific semantic types
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First text chunk",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=len(encoding.encode("First text chunk")),
                semantic_types="text"
            ),
            LLMChunkTestDataFactory.create_chunk_instance(
                content="Second text chunk",
                chunk_id="chunk_0002",
                source_page=1,
                token_count=len(encoding.encode("Second text chunk")),
                semantic_types="text"
            ),
            LLMChunkTestDataFactory.create_chunk_instance(
                content="Table chunk",
                chunk_id="chunk_0003",
                source_page=2,
                token_count=len(encoding.encode("Table chunk")),
                semantic_types="table"
            )
        ]
        
        expected_text_chunks = len([c for c in chunks if c.semantic_types == "text"])
        
        count_metadata = {
            "text_chunks": expected_text_chunks
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Count Tracking Test",
            chunks=chunks,
            summary="Document for testing count tracking consistency",
            key_entities=[],
            processing_metadata=count_metadata
        )
        
        # When/Then
        actual_text_chunks = len([c for c in document.chunks if c.semantic_types == "text"])
        assert document.processing_metadata["text_chunks"] == actual_text_chunks

    def test_metadata_table_chunks_count_matches_actual_table_chunks(self):
        """
        GIVEN LLMDocument instance with processing_metadata containing table chunks count
        WHEN validating table chunks count consistency
        THEN expect table_chunks to match actual number of table semantic type chunks
        """
        # Get encoding for token counting
        encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")

        # Given - create chunks with specific semantic types
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="Text chunk",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=len(encoding.encode("Text chunk")),
                semantic_types="text"
            ),
            LLMChunkTestDataFactory.create_chunk_instance(
                content="Table chunk",
                chunk_id="chunk_0002",
                source_page=2,
                token_count=len(encoding.encode("Table chunk")),
                semantic_types="table"
            )
        ]
        
        expected_table_chunks = len([c for c in chunks if c.semantic_types == "table"])
        
        count_metadata = {
            "table_chunks": expected_table_chunks
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Count Tracking Test",
            chunks=chunks,
            summary="Document for testing count tracking consistency",
            key_entities=[],
            processing_metadata=count_metadata
        )
        
        # When/Then
        actual_table_chunks = len([c for c in document.chunks if c.semantic_types == "table"])
        assert document.processing_metadata["table_chunks"] == actual_table_chunks

    def test_metadata_avg_tokens_per_chunk_calculation_correct(self):
        """
        GIVEN LLMDocument instance with processing_metadata containing average tokens per chunk
        WHEN validating average calculation
        THEN expect avg_tokens_per_chunk to match calculated average
        """
        # Get encoding for token counting
        encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")

        # Given - create chunks with known token counts
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="First chunk with specific token count",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=len(encoding.encode("First chunk with specific token count"))
            ),
            LLMChunkTestDataFactory.create_chunk_instance(
                content="Second chunk with different token count",
                chunk_id="chunk_0002",
                source_page=1,
                token_count=len(encoding.encode("Second chunk with different token count"))
            )
        ]
        
        expected_token_total = sum(chunk.token_count for chunk in chunks)
        expected_avg = expected_token_total / len(chunks)
        
        count_metadata = {
            "avg_tokens_per_chunk": expected_avg
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Count Tracking Test",
            chunks=chunks,
            summary="Document for testing count tracking consistency",
            key_entities=[],
            processing_metadata=count_metadata
        )
        
        # When/Then
        actual_token_total = sum(chunk.token_count for chunk in document.chunks)
        expected_avg = actual_token_total / len(document.chunks)
        assert abs(document.processing_metadata["avg_tokens_per_chunk"] - expected_avg) < 0.01

    def test_metadata_min_chunk_tokens_matches_actual_minimum(self):
        """
        GIVEN LLMDocument instance with processing_metadata containing minimum chunk tokens
        WHEN validating minimum calculation
        THEN expect min_chunk_tokens to match actual minimum
        """
        # Get encoding for token counting
        encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")

        # Given - create chunks with known token counts
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="Short",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=len(encoding.encode("Short"))
            ),
            LLMChunkTestDataFactory.create_chunk_instance(
                content="This is a much longer chunk with more tokens",
                chunk_id="chunk_0002",
                source_page=1,
                token_count=len(encoding.encode("This is a much longer chunk with more tokens"))
            )
        ]
        
        expected_min_tokens = min(chunk.token_count for chunk in chunks)
        
        count_metadata = {
            "min_chunk_tokens": expected_min_tokens
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Count Tracking Test",
            chunks=chunks,
            summary="Document for testing count tracking consistency",
            key_entities=[],
            processing_metadata=count_metadata
        )
        
        # When/Then
        actual_min_tokens = min(chunk.token_count for chunk in document.chunks)
        assert document.processing_metadata["min_chunk_tokens"] == actual_min_tokens

    def test_metadata_max_chunk_tokens_matches_actual_maximum(self):
        """
        GIVEN LLMDocument instance with processing_metadata containing maximum chunk tokens
        WHEN validating maximum calculation
        THEN expect max_chunk_tokens to match actual maximum
        """
        # Get encoding for token counting
        encoding = tiktoken.encoding_for_model("gpt-3.5-turbo")

        # Given - create chunks with known token counts
        chunks = [
            LLMChunkTestDataFactory.create_chunk_instance(
                content="Short",
                chunk_id="chunk_0001",
                source_page=1,
                token_count=len(encoding.encode("Short"))
            ),
            LLMChunkTestDataFactory.create_chunk_instance(
                content="This is a much longer chunk with more tokens",
                chunk_id="chunk_0002",
                source_page=1,
                token_count=len(encoding.encode("This is a much longer chunk with more tokens"))
            )
        ]
        
        expected_max_tokens = max(chunk.token_count for chunk in chunks)
        
        count_metadata = {
            "max_chunk_tokens": expected_max_tokens
        }
        
        document = LLMDocument(
            document_id="doc_001",
            title="Count Tracking Test",
            chunks=chunks,
            summary="Document for testing count tracking consistency",
            key_entities=[],
            processing_metadata=count_metadata
        )
        
        # When/Then
        actual_max_tokens = max(chunk.token_count for chunk in document.chunks)
        assert document.processing_metadata["max_chunk_tokens"] == actual_max_tokens


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
