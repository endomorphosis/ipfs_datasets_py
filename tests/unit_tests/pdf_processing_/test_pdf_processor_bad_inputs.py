"""
Test cases for path-related input validation in process_pdf method.

This module tests the process_pdf method's handling of various invalid path inputs,
including type validation, empty paths, and malformed path strings.
Shared terminology: "invalid path" refers to any path input that violates the
Union[str, Path] contract or filesystem naming conventions.
"""

import pytest
from pathlib import Path
from typing import Any


import tests.unit_tests.pdf_processing_.conftest as conftest



class TestProcessPdfInvalidPathArg:
    """
    Test path-related input validation for the process_pdf method.
    
    Tests the process_pdf method's ability to validate and reject invalid path inputs
    according to the public contract. Covers type validation, empty paths, and
    malformed path strings.
    
    Shared terminology:
    - "invalid path": Path input that violates Union[str, Path] contract
    - "malformed path": String paths with invalid filesystem characters
    """
    @pytest.fixture
    def valid_metadata(self) -> dict[str, Any]:
        """Provide valid metadata for testing."""
        return {"test": "metadata"}

    @pytest.fixture
    def directory_path(self, tmp_path) -> Path:
        """Provide directory path instead of file path."""
        test_dir = tmp_path / "test_directory"
        test_dir.mkdir()
        return test_dir

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "invalid_path_input", [
            42,
            ["not", "a", "path"],
            None,
            {},
            True,
            3.14,
            set(),
            lambda x: x,
            object(),
            complex(1, 2),
            b"bytes_path",
            bytearray(b"bytearray_path"),
        ]
    )
    async def test_when_invalid_type_path_provided_then_raises_type_error(
        self, 
        pdf_process_with_debug_logger, 
        invalid_path_input, 
        valid_metadata
    ):
        """
        GIVEN an invalid type as pdf_path
        WHEN process_pdf is called
        THEN raises TypeError with message containing expected message
        """
        expected_message = "pdf_path must be a string or Path object"
        with pytest.raises(TypeError) as exc_info:
            await pdf_process_with_debug_logger.process_pdf(invalid_path_input, valid_metadata)
        
        assert expected_message in str(exc_info.value)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("invalid_path_string", [
        "",
        "   ",
        "\t\n",
    ])
    async def test_when_only_whitespace_in_path_then_raises_value_error(
        self, 
        pdf_process_with_debug_logger, 
        invalid_path_string, 
        valid_metadata
    ):
        """
        GIVEN a path string that is empty or contains only whitespace
        WHEN process_pdf is called
        THEN raises ValueError with expected message
        """
        expected_message = "pdf_path cannot be empty or whitespace"
        with pytest.raises(ValueError) as exc_info:
            await pdf_process_with_debug_logger.process_pdf(invalid_path_string, valid_metadata)

        assert expected_message in str(exc_info.value)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("invalid_path_string", [
        "file\x00.pdf",
        "file\x01name.pdf",
        "file\x1fname.pdf",
        "file\x7fname.pdf",
        "file<name>.pdf",
        "file|name.pdf",
        "file?name.pdf",
        "file*name.pdf",
        "file\"name\".pdf",
    ])
    async def test_when_invalid_chars_in_path_provided_then_raises_value_error(
        self, 
        pdf_process_with_debug_logger, 
        invalid_path_string, 
        valid_metadata
    ):
        """
        GIVEN a pdf_path with invalid characters in the string
        WHEN process_pdf is called
        THEN raises ValueError with expected message
        """
        expected_message = "pdf_path contains invalid characters"
        with pytest.raises(ValueError) as exc_info:
            await pdf_process_with_debug_logger.process_pdf(invalid_path_string, valid_metadata)

        assert expected_message in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_when_directory_path_provided_then_raises_value_error(
        self, 
        pdf_process_with_debug_logger, 
        directory_path, 
        valid_metadata
    ):
        """
        GIVEN a path pointing to a directory
        WHEN process_pdf is called
        THEN raises ValueError with message 'pdf_path must point to a file, not directory'
        """
        expected_message = "PDF path is not a file"

        with pytest.raises(ValueError) as exc_info:
            await pdf_process_with_debug_logger.process_pdf(directory_path, valid_metadata)

        assert expected_message in str(exc_info.value)


class TestProcessPdfMetadataArg:
    """
    Test metadata parameter validation for the process_pdf method.
    
    Tests the process_pdf method's ability to validate metadata parameter
    according to the Optional[dict[str, Any]] contract and reject invalid
    metadata structures.
    
    Shared terminology:
    - "invalid metadata": Metadata that violates Optional[dict[str, Any]] contract
    - "malformed metadata": Dictionary with invalid key types or structure
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "invalid_metadata", [
            "invalid metadata",
            ["invalid", "metadata"],
            42,
            True,
            3.14,
            set(),
            object(),
        ]
    )
    async def test_when_invalid_type_metadata_provided_then_raises_type_error(
        self, 
        pdf_process_with_debug_logger, 
        valid_pdf_document, 
        invalid_metadata
    ):
        """
        GIVEN metadata as invalid type instead of dict
        WHEN process_pdf is called
        THEN raises TypeError with expected message
        """
        expected_message = "metadata must be dict or None"
        with pytest.raises(TypeError) as exc_info:
            await pdf_process_with_debug_logger.process_pdf(valid_pdf_document, invalid_metadata)
        
        assert expected_message in str(exc_info.value)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "invalid_keys_metadata", [
            {123: "value", 456: "another_value"},
            {"valid_key": "value", 123: "invalid_key"},
            {None: "value"},
            {True: "value", False: "another"},
            {(1, 2): "tuple_key"},
        ]
    )
    async def test_when_invalid_keys_metadata_provided_then_raises_value_error(
        self, 
        pdf_process_with_debug_logger, 
        valid_pdf_document, 
        invalid_keys_metadata
    ):
        """
        GIVEN metadata dict with invalid key types
        WHEN process_pdf is called
        THEN raises ValueError with expected message
        """
        expected_message = "metadata keys must be strings"
        with pytest.raises(TypeError) as exc_info:
            await pdf_process_with_debug_logger.process_pdf(valid_pdf_document, invalid_keys_metadata)
        
        assert expected_message in str(exc_info.value)

