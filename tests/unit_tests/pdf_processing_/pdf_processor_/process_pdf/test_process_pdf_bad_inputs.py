import anyio
"""
Test cases for path-related input validation in process_pdf method.

This module tests the process_pdf method's handling of various invalid path inputs,
including type validation, empty paths, and malformed path strings.
Shared terminology: "invalid path" refers to any path input that violates the
Union[str, Path] contract or filesystem naming conventions.
"""
from pathlib import Path
from typing import Any


import pytest


from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor


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
    def directory_path(self, tmp_path) -> Path:
        """Provide directory path instead of file path."""
        test_dir = tmp_path / "test_directory"
        test_dir.mkdir()
        return test_dir

    @pytest.mark.anyio
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
        default_pdf_processor, 
        invalid_path_input, 
        valid_metadata
    ):
        """
        GIVEN an invalid type as pdf_path
        WHEN process_pdf is called
        THEN raises TypeError with message containing expected message
        """
        with pytest.raises(TypeError, match=r"pdf_path must be a string or Path object") as exc_info:
            await default_pdf_processor.process_pdf(invalid_path_input, valid_metadata)

    @pytest.mark.anyio
    @pytest.mark.parametrize("invalid_path_string", [
        "",
        "   ",
        "\t\n",
    ])
    async def test_when_only_whitespace_in_path_then_raises_value_error(
        self, 
        default_pdf_processor, 
        invalid_path_string, 
        valid_metadata
    ):
        """
        GIVEN a path string that is empty or contains only whitespace
        WHEN process_pdf is called
        THEN raises ValueError with expected message
        """
        with pytest.raises(ValueError, match=r"pdf_path cannot be empty or whitespace") as exc_info:
            await default_pdf_processor.process_pdf(invalid_path_string, valid_metadata)

    @pytest.mark.anyio
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
        default_pdf_processor: PDFProcessor, 
        invalid_path_string, 
        valid_metadata
    ):
        """
        GIVEN a pdf_path with invalid characters in the string
        WHEN process_pdf is called
        THEN raises ValueError with expected message
        """
        with pytest.raises(ValueError, match=r"pdf_path contains invalid characters") as exc_info:
            await default_pdf_processor.process_pdf(invalid_path_string, valid_metadata)


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
    @pytest.mark.anyio
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
        default_pdf_processor, 
        valid_pdf_document, 
        invalid_metadata
    ):
        """
        GIVEN metadata as invalid type instead of dict
        WHEN process_pdf is called
        THEN raises TypeError with expected message
        """
        with pytest.raises(TypeError, match=r"metadata must be dict or None") as exc_info:
            await default_pdf_processor.process_pdf(valid_pdf_document, invalid_metadata)

    @pytest.mark.anyio
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
        default_pdf_processor, 
        valid_pdf_document, 
        invalid_keys_metadata
    ):
        """
        GIVEN metadata dict with invalid key types
        WHEN process_pdf is called
        THEN raises ValueError with expected message
        """
        with pytest.raises(TypeError, match=r"metadata keys must be strings") as exc_info:
            await default_pdf_processor.process_pdf(valid_pdf_document, invalid_keys_metadata)

