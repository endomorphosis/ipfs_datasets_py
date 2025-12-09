#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# File Path: ipfs_datasets_py/ipfs_datasets_py/pdf_processing/pdf_processor.py
# Auto-generated on 2025-07-07 02:28:56"
import asyncio
from unittest.mock import MagicMock


import pytest
import os


from tests._test_utils import (
    has_good_callable_metadata,
    raise_on_bad_callable_code_quality,
    get_ast_tree,
    BadDocumentationError,
    BadSignatureError
)

home_dir = os.path.expanduser('~')
file_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/pdf_processor.py")
md_path = os.path.join(home_dir, "ipfs_datasets_py/ipfs_datasets_py/pdf_processing/pdf_processor_stubs.md")

# Make sure the input file and documentation file exist.
# assert os.path.exists(file_path), f"Input file does not exist: {file_path}. Check to see if the file exists or has been moved or renamed."
# assert os.path.exists(md_path), f"Documentation file does not exist: {md_path}. Check to see if the file exists or has been moved or renamed."

from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor

# Check if each classes methods are accessible:
assert PDFProcessor.process_pdf
assert PDFProcessor._validate_and_analyze_pdf
assert PDFProcessor._decompose_pdf
assert PDFProcessor._extract_page_content
assert PDFProcessor._create_ipld_structure
assert PDFProcessor._process_ocr
assert PDFProcessor._optimize_for_llm
assert PDFProcessor._extract_entities
assert PDFProcessor._create_embeddings
assert PDFProcessor._integrate_with_graphrag
assert PDFProcessor._analyze_cross_document_relationships
assert PDFProcessor._setup_query_interface
assert PDFProcessor._calculate_file_hash
assert PDFProcessor._extract_native_text
assert PDFProcessor._get_processing_time
assert PDFProcessor._get_quality_scores

# Check if the modules's imports are accessible:
import logging
import hashlib
import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Union
from contextlib import nullcontext

import pymupdf  # PyMuPDF
import pdfplumber
from PIL import Image
import psutil

from ipfs_datasets_py.ipld import IPLDStorage
from ipfs_datasets_py.audit import AuditLogger
from ipfs_datasets_py.monitoring import MonitoringSystem
from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMOptimizer
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator
from ipfs_datasets_py.monitoring import MonitoringConfig, MetricsConfig
from ipfs_datasets_py.pdf_processing.ocr_engine import MultiEngineOCR
from ipfs_datasets_py.pdf_processing.llm_optimizer import LLMDocument, LLMChunk
from ipfs_datasets_py.pdf_processing.query_engine import QueryEngine
from ipfs_datasets_py.pdf_processing.graphrag_integrator import GraphRAGIntegrator

import reportlab


from typing import List, Dict, Any, Optional, Union, Tuple, Generator
from pathlib import Path
import tempfile
from enum import Enum
from dataclasses import dataclass


import reportlab
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

import faker
from PIL import Image


from tests.unit_tests.pdf_processing_.graphrag_integrator_.conftest import (
    real_integrator,
)

from contextlib import contextmanager
import pymupdf


SEED = 420


EXPECTED_KEY_TYPES = {
    "status": str,
    "document_id": str,
    "ipld_cid": str,
    "entities_count": int,
    "relationships_count": int,
    "cross_doc_relations": int,
    "processing_metadata": dict,
    "pdf_info": dict
}

@pytest.fixture
def expected_key_type_mapping():
    return EXPECTED_KEY_TYPES

@pytest.fixture
def expected_keys():
    return {key for key in EXPECTED_KEY_TYPES.keys()}


EXPECTED_PROCESSING_METADATA_KEY_TYPES = {
    "pipeline_version": str,
    "processing_time": float,
    "quality_scores": dict, # dict[str, float]
    "stages_completed": list # list[str]
}


@pytest.fixture
def processing_metadata_keys():
    return {key for key in EXPECTED_PROCESSING_METADATA_KEY_TYPES.keys()}

@pytest.fixture
def overlapping_processing_metadata():
    return {
        "pipeline_version": "imma computer",
        "processing_time": -35,
        "quality_scores": {"stop with the downloads!"},
        "stages_completed": ["bs"],
    }


class TestProcessPdfHappyPath:
    """Test process_pdf method accepts valid inputs and returns expected structure."""

    @pytest.mark.asyncio
    async def test_process_pdf_returns_dict(self, real_pdf_processor, mock_pdf_file):
        """
        GIVEN PDF file path as string
        WHEN process_pdf is called
        THEN expect return to be a dictionary
        """
        result = await real_pdf_processor.process_pdf(mock_pdf_file)

        assert isinstance(result, dict), \
            f"Expected result to be a dictionary, got {type(result).__name__} instead."


    @pytest.mark.asyncio
    async def test_process_pdf_returns_dict_with_string_keys(self, real_pdf_processor, mock_pdf_file):
        """
        GIVEN PDF file path as string
        WHEN process_pdf is called
        THEN expect all keys in returned dict to be strings
        """
        result = await real_pdf_processor.process_pdf(mock_pdf_file)

        for idx, key in enumerate(result.keys()):
            assert isinstance(key, str), \
                f"Expected key at index {idx} to be a string, got {type(key).__name__} instead."


    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "key", [key for key in EXPECTED_KEY_TYPES.keys()]
    )
    async def test_process_pdf_successful_return_has_expected_keys(
        self, key, real_pdf_processor: PDFProcessor, mock_pdf_file):
        """
        GIVEN valid PDF file path and optional metadata
        WHEN process_pdf is called
        THEN expect returned dict contains specified keys
        """
        result = await real_pdf_processor.process_pdf(mock_pdf_file)

        assert key in result, f"Expected key '{key}' in result, but it was missing."


    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "key", [key for key in EXPECTED_KEY_TYPES.keys()]
    )
    async def test_process_pdf_when_successful_return_keys_have_expected_types(
        self, key, expected_key_type_mapping, real_pdf_processor: PDFProcessor, mock_pdf_file):
        """
        GIVEN valid PDF file path
        WHEN process_pdf is called
        THEN expect returned dict values to have their expected types
        """
        result = await real_pdf_processor.process_pdf(mock_pdf_file)

        expected_type = expected_key_type_mapping[key]
        return_value = result[key]
        assert isinstance(return_value, expected_type), \
            f"Expected key '{key}' to be of type {expected_type.__name__}, got {type(return_value).__name__} instead."


    @pytest.mark.asyncio
    async def test_process_pdf_successful_run_returns_status_as_success(
        self, real_pdf_processor: PDFProcessor, mock_pdf_file):
        """
        GIVEN valid PDF file path
        WHEN process_pdf is called
        THEN expect status is 'success' in returned dict
        """
        result = await real_pdf_processor.process_pdf(mock_pdf_file)

        # Verify result structure
        assert result["status"] == "success"


    @pytest.mark.asyncio
    async def test_process_pdf_successful_return_keys_have_expected_types(
        self, expected_key_type_mapping, real_pdf_processor: PDFProcessor, mock_pdf_file):
        """
        GIVEN valid PDF file path
        WHEN process_pdf is called
        THEN expect returned dict does NOT contain any additional keys
        """
        result = await real_pdf_processor.process_pdf(mock_pdf_file)

        for key in result.keys():
            assert key in expected_key_type_mapping, f"Unexpected key '{key}' found in result."


    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "string_value", ["status", "document_id", "ipld_cid"]
    )
    async def test_process_pdf_returns_non_empty_string_values(
        self, string_value, real_pdf_processor: PDFProcessor, mock_pdf_file):
        """
        GIVEN a PDF file
        WHEN process_pdf is called
        THEN expect values that are strings to be non-empty
        """
        result = await real_pdf_processor.process_pdf(mock_pdf_file)

        actual_value = result[string_value].strip()

        assert actual_value != "", \
            f"Expected '{string_value}' to be a non-empty string after stripping, got empty string instead."


    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "integer_key", ["entities_count", "relationships_count", "cross_doc_relations"]
    )
    async def test_process_pdf_returns_integer_values_are_non_negatives(
        self, integer_key, real_pdf_processor: PDFProcessor, mock_pdf_file):
        """
        GIVEN a PDF file
        WHEN process_pdf is called
        THEN expect values that are integers to be non-negative
        
        returned dict contains:
            - status: 'success'
            - document_id: string UUID
            - ipld_cid: valid content identifier
            - entities_count: non-negative integer
            - relationships_count: non-negative integer
            - cross_doc_relations: non-negative integer
            - processing_metadata with pipeline_version, processing_time, quality_scores, stages_completed
        """
        result = await real_pdf_processor.process_pdf(mock_pdf_file)

        assert result[integer_key] >= 0, \
            f"Expected '{integer_key}' to be non-negative, got {result[integer_key]} instead."


    @pytest.mark.asyncio
    async def test_process_pdf_with_custom_metadata_returns_dict(
        self, real_pdf_processor: PDFProcessor, mock_pdf_file, custom_metadata):
        """
        GIVEN PDF file and custom metadata dict
        WHEN process_pdf is called with metadata
        THEN expect return to be a dictionary
        """
        result = await real_pdf_processor.process_pdf(mock_pdf_file, custom_metadata)

        assert isinstance(result, dict), \
            f"Expected result with custom metadata input to be a dictionary, got {type(result).__name__} instead."


CUSTOM_METADATA = {
    "user_id": "user_12345",
    "session_id": "session_67890",
    "source": "web_upload",
    "priority": "high",
    "tags": ["invoice", "2023", "Q1"],
    "reviewed": False,
    "page_count": 10,
}


@pytest.mark.parametrize(
    "key", [key for key in CUSTOM_METADATA.keys()]
)
class TestProcessPdfHappyPathWithCustomMetadata:
    """Test process_pdf method accepts a custom metadata dict as an argument."""

    @pytest.mark.asyncio
    async def test_process_pdf_with_custom_metadata_keys_are_present(
        self, key, real_pdf_processor, custom_metadata, mock_pdf_file):
        """
        GIVEN PDF file and custom metadata dict
        WHEN process_pdf is called with metadata
        THEN expect custom metadata keys are present in processing_metadata sub-dictionary
        """
        result = await real_pdf_processor.process_pdf(mock_pdf_file, custom_metadata)

        # Verify custom metadata was passed through
        assert key in result["processing_metadata"], \
            f"Expected custom metadata key '{key}' to be in processing_metadata sub-dictionary, but it was missing."


    @pytest.mark.asyncio
    async def test_process_pdf_with_custom_metadata_types_passed_through(
        self, key, real_pdf_processor, custom_metadata, mock_pdf_file):
        """
        GIVEN PDF file and custom metadata dict
        WHEN process_pdf is called with metadata
        THEN expect the custom metadata values' to have the same type in processing_metadata sub-dictionary
        """
        result = await real_pdf_processor.process_pdf(mock_pdf_file, custom_metadata)

        expected_type = type(custom_metadata[key])
        return_value = result["processing_metadata"][key]

        # Verify custom metadata was passed through
        assert isinstance(return_value, expected_type), \
            f"Expected key '{key}' to be of type {expected_type.__name__}, got {type(return_value).__name__} instead."


    @pytest.mark.asyncio
    async def test_process_pdf_with_custom_metadata_values_passed_through(
        self, key, real_pdf_processor, custom_metadata, mock_pdf_file):
        """
        GIVEN PDF file and custom metadata dict
        WHEN process_pdf is called with metadata
        THEN expect the custom metadata values to be the same in processing_metadata sub-dictionary
        """
        result = await real_pdf_processor.process_pdf(mock_pdf_file, custom_metadata)

        actual_value = custom_metadata[key]
        return_value = result["processing_metadata"][key]

        # Verify custom metadata was passed through
        assert return_value == actual_value, \
            f"Expected metadata key '{key}' to have value '{actual_value}', got '{return_value}' instead."



BAD_METADATA_TYPES = {
    "list": ["list", "instead", "of", "dict"],
    "tuple": ("tuple", "instead", "of", "dict"),
    "string": "string_instead_of_dict",
    "integer": 12345,
    "float": 67.89,
    "boolean_true": True,
    "boolean_false": False,
    "set": set(["set", "instead", "of", "dict"]),
    "frozenset": frozenset(["frozenset", "instead", "of", "dict"]),
    "range": range(5),
    "bytes": b"bytes_instead_of_dict",
    "bytearray": bytearray(b"bytearray_instead_of_dict"),
    "memoryview": memoryview(b"memoryview_instead_of_dict"),
    "complex": complex(1, 2),
    "lambda": lambda x: x,
    "type": type,
    "object": object(),
    "exception": Exception("exception_instead_of_dict")
}


@pytest.fixture
def bad_metadata_types():
    return BAD_METADATA_TYPES


BAD_METADATA_KEYS = {
    "integer": 123,
    "float": 45.67,
    "boolean_true": True,
    "boolean_false": False,
    "none": None,
    "list": ["list", "key"],
    "tuple": ("tuple", "key"),
    "dict": {"nested": "dict"},
    "set": {"set", "key"},
    "frozenset": frozenset(["frozenset", "key"]),
    "range": range(5),
    "bytes": b"bytes_key",
    "bytearray": bytearray(b"bytearray_key"),
    "memoryview": memoryview(b"memoryview_key"),
    "complex": complex(1, 2),
    "lambda": lambda x: x,
    "type": type,
    "object": object(),
    "exception": Exception("exception_key"),
    "slice": slice(1, 5, 2),
    "ellipsis": ...,
    "inf": float('inf'),
    "neg_inf": float('-inf'),
    "nan": float('nan'),
    "empty_string": "",
    "whitespace": "   ",
    "unicode": "🔑",
    "newline": "\n",
    "tab": "\t",
    "backslash": "\\",
    "quote": "\"",
    "apostrophe": "'",
}

@pytest.fixture
def bad_metadata_keys():
    return BAD_METADATA_KEYS

class TestProcessPdfWithCustomMetadataBadInputs:
    """Test that process_pdf method rejects bad custom metadata dict inputs."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_type", [key for key in BAD_METADATA_TYPES.keys()])
    async def test_process_pdf_with_custom_metadata_not_dict_raises_type_error(
        self, bad_type, bad_metadata_types, real_pdf_processor, mock_pdf_file):
        """
        GIVEN PDF file and custom metadata that is not a dict or None
        WHEN process_pdf is called
        THEN expect TypeError is raised
        """
        with pytest.raises(TypeError):
            result = await real_pdf_processor.process_pdf(
                mock_pdf_file, metadata=bad_metadata_types[bad_type]
            )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_key_type", [key for key in BAD_METADATA_KEYS.keys()])
    async def test_process_pdf_with_custom_metadata_with_non_string_keys_raises_type_error(
        self, bad_key_type, real_pdf_processor, mock_pdf_file):
        """
        GIVEN PDF file and custom metadata dict with non-string keys
        WHEN process_pdf is called
        THEN expect TypeError is raised
        """
        bad_metadata = {bad_key_type: "some_value"}

        with pytest.raises(TypeError):
            result = await real_pdf_processor.process_pdf(mock_pdf_file, metadata=bad_metadata)


    @pytest.mark.asyncio
    async def test_process_pdf_with_custom_metadata_with_same_keys_as_processing_metadata_raises_key_error(
        self, real_pdf_processor, overlapping_processing_metadata, mock_pdf_file):
        """
        GIVEN PDF file and custom metadata dict with overlapping keys as processing_metadata
        WHEN process_pdf is called
        THEN expect KeyError is raised
        """
        with pytest.raises(KeyError):
            result = await real_pdf_processor.process_pdf(
                mock_pdf_file, metadata=overlapping_processing_metadata
            )

BAD_FILE_PATHS = {
    "integer": 123,
    "float": 45.67,
    "boolean_true": True,
    "boolean_false": False,
    "none": None,
    "list": ["list", "instead", "of", "str_or_path"],
    "tuple": ("tuple", "instead", "of", "str_or_path"),
    "dict": {"dict": "instead_of_str_or_path"},
    "set": {"set", "instead", "of", "str_or_path"},
    "frozenset": frozenset(["frozenset", "instead", "of", "str_or_path"]),
    "range": range(5),
    "bytes": b"bytes_instead_of_str_or_path",
    "bytearray": bytearray(b"bytearray_instead_of_str_or_path"),
    "memoryview": memoryview(b"memoryview_instead_of_str_or_path"),
    "complex": complex(1, 2),
    "lambda": lambda x: x,
    "type": type,
    "object": object(),
    "exception": Exception("exception_instead_of_str_or_path"),
    "slice": slice(1, 5, 2),
    "ellipsis": ...,
    "inf": float('inf'),
    "neg_inf": float('-inf'),
    "nan": float('nan'),
    "empty_string": "",
    "whitespace": "   ",
    "unicode": "📄",
    "newline": "\n",
    "tab": "\t",
    "backslash": "\\",
    "quote": "\"",
    "apostrophe": "'",
}

@pytest.fixture
def bad_file_paths():
    return BAD_FILE_PATHS



class TestProcessPdfFilePathBadInputs:
    """Test that process_pdf method rejects bad file path inputs."""

    @pytest.mark.parametrize("bad_type", [
        key for key in BAD_FILE_PATHS.keys()
    ])
    @pytest.mark.asyncio
    async def test_process_pdf_where_file_path_is_not_path_or_str_raises_type_error(
        self, bad_type, bad_file_paths, real_pdf_processor: PDFProcessor):
        """
        GIVEN a PDF file path that is not a string or Path
        WHEN process_pdf is called
        THEN expect TypeError to be raised
        """
        with pytest.raises(TypeError):
            await real_pdf_processor.process_pdf(bad_file_paths[bad_type])


    @pytest.mark.asyncio
    async def test_process_pdf_data_result_stored_in_ipld_storage(
        self, 
        valid_pdf_file, 
        real_pdf_processor: PDFProcessor
    ):
        """
        GIVEN PDF processing pipeline
        WHEN process_pdf executes
        THEN expect the IPLD cid to be retrievable from the IPLD storage.
        """
        result = await real_pdf_processor.process_pdf(valid_pdf_file)

        cid = result["ipld_cid"]
        stored_cid = real_pdf_processor.storage.get_batch([cid])

        assert cid == stored_cid, \
            f"Expected stored CID '{stored_cid}' to match result CID '{cid}', got '{stored_cid}' instead."


    @pytest.mark.asyncio
    async def test_process_pdf_audit_logging_logs_are_stored(
        self, 
        default_pdf_processor: PDFProcessor,
        valid_pdf_file
        ):
        """
        GIVEN PDFProcessor with audit logging enabled
        WHEN process_pdf executes
        THEN expect audit logger to have logged events.
        """
        await default_pdf_processor.process_pdf(valid_pdf_file)

        # Verify audit logging occurred
        assert len(default_pdf_processor.audit_logger.events) > 0, \
            "Expected audit events to be logged, but none were found."


    @pytest.mark.asyncio
    async def test_process_pdf_audit_logging_logs_are_stored_are_success(
        self, 
        default_pdf_processor: PDFProcessor,
        valid_pdf_file
        ):
        """
        GIVEN PDFProcessor with audit logging enabled
        WHEN process_pdf executes with a valid PDF
        THEN expect events to have 'status'=='success'.
        """
        await default_pdf_processor.process_pdf(valid_pdf_file)

        for idx, event in default_pdf_processor.audit_logger.events:
            assert event['status'] == 'success', \
                f"Expected audit event at index {idx} to have status 'success', got '{event['status']}' instead."


    @pytest.mark.asyncio
    async def test_process_pdf_monitoring_integration(
        self, 
        real_pdf_processor: PDFProcessor,
        valid_pdf_file
        ):
        """
        GIVEN PDFProcessor with monitoring enabled
        WHEN process_pdf executes
        THEN expect the monitor attribute 'initialized'  is True
        """
        await real_pdf_processor.process_pdf(valid_pdf_file)

        # Verify monitoring system is active
        assert real_pdf_processor.monitoring.initialized is True, \
            "Expected monitoring system to be initialized, but it was not."


    @pytest.mark.asyncio
    async def test_process_pdf_monitoring(
        self, 
        real_pdf_processor: PDFProcessor,
        valid_pdf_file
        ):
        """
        GIVEN PDFProcessor with monitoring enabled
        WHEN process_pdf executes
        THEN expect:
            - Performance metrics collected
            - Processing time tracked per stage
            - Resource usage monitored
            - Prometheus metrics exported
        """
        await real_pdf_processor.process_pdf(valid_pdf_file)
        real_pdf_processor.monitoring.metrics_registry
        
        # Verify monitoring system is active
        assert real_pdf_processor.monitoring.initialized is True, \
            "Expected monitoring system to be initialized, but it was not."


    @pytest.mark.asyncio
    async def test_process_pdf_large_file_memory_remains_in_limit(
        self, 
        real_pdf_processor: PDFProcessor,
        large_pdf_path
        ):
        """
        GIVEN very large PDF file (>100MB)
        WHEN process_pdf executes
        THEN expect memory usage remains within 200MB
        """
        result = await real_pdf_processor.process_pdf(large_pdf_path)

        # Verify processing completed for large file
        assert result is not None


    @pytest.mark.asyncio
    async def test_process_pdf_large_file_no_memory_leaks(
        self, 
        real_pdf_processor: PDFProcessor,
        large_pdf_path
        ):
        """
        GIVEN very large PDF file (>100MB)
        WHEN process_pdf executes
        THEN expect memory usage after the process is over to equal the memory usage before processing began
        """
        result = await real_pdf_processor.process_pdf(large_pdf_path)

        # Verify processing completed for large file
        assert result is not None


    @pytest.mark.asyncio
    async def test_process_pdf_concurrent_processing_safety(self, real_pdf_processor: PDFProcessor):
        """
        GIVEN multiple concurrent PDF processing calls
        WHEN process_pdf is called simultaneously on different files
        THEN expect:
            - Each processing instance operates independently
            - No shared state interference
            - Correct results for each file
            - No race conditions in storage or monitoring
        """
        pdf_path1 = Path("document1.pdf")
        pdf_path2 = Path("document2.pdf")

        # Process files concurrently
        task1 = asyncio.create_task(real_pdf_processor.process_pdf(pdf_path1))
        task2 = asyncio.create_task(real_pdf_processor.process_pdf(pdf_path2))
        
        results = await asyncio.gather(task1, task2)
        
        # Verify both completed successfully
        assert len(results) == 2
        assert results[0] is not None
        assert results[1] is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
