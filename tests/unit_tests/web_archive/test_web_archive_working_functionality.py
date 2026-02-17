#!/usr/bin/env python3
"""
Strategic tests for working WebArchive functionality.

This module tests the actual working methods in WebArchive and WebArchiveProcessor
with proper test data and validation of the real implementations.
"""
import pytest
import tempfile
import os
from pathlib import Path
from ipfs_datasets_py.processors.web_archiving.web_archive import WebArchive, WebArchiveProcessor


class TestWebArchiveWorkingFunctionality:
    """Test working WebArchive methods with proper implementation validation."""

    @pytest.fixture
    def processor(self):
        """Create a WebArchiveProcessor instance for testing."""
        return WebArchiveProcessor()

    @pytest.fixture
    def archive(self):
        """Create a WebArchive instance for testing."""
        return WebArchive()

    def test_web_archive_initialization_with_default_settings(self, archive):
        """
        GIVEN WebArchive class
        WHEN WebArchive is initialized with default parameters
        THEN creates instance with memory-only persistence mode
        """
        # Test the working WebArchive.__init__ method
        assert archive is not None
        assert hasattr(archive, 'archived_items')
        assert hasattr(archive, 'persistence_mode')
        assert archive.persistence_mode == "memory_only"
        assert isinstance(archive.archived_items, dict)

    def test_web_archive_initialization_with_storage_path(self):
        """
        GIVEN WebArchive class and valid storage path
        WHEN WebArchive is initialized with storage_path parameter
        THEN creates instance with persistent mode
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            # Test WebArchive with persistent storage
            archive = WebArchive(storage_path=temp_dir)
            
            assert archive is not None
            assert archive.storage_path == temp_dir
            assert archive.persistence_mode == "persistent"

    def test_web_archive_processor_initialization(self, processor):
        """
        GIVEN WebArchiveProcessor class
        WHEN WebArchiveProcessor is initialized
        THEN creates instance with embedded WebArchive
        """
        # Test the working WebArchiveProcessor.__init__ method
        assert processor is not None
        assert hasattr(processor, 'archive')
        assert isinstance(processor.archive, WebArchive)

    def test_web_archive_url_validation_with_valid_urls(self, archive):
        """
        GIVEN WebArchive instance and valid HTTP URLs
        WHEN URL validation is performed
        THEN validation succeeds for well-formed URLs
        """
        # Test the working URL validation functionality
        valid_urls = [
            "https://example.com",
            "http://test-site.org",
            "https://docs.python.org/3/"
        ]
        
        for url in valid_urls:
            # This tests the internal URL validation used by archive_url
            try:
                result = archive.archive_url(url)
                # archive_url should return success or error dict, not raise exceptions
                assert isinstance(result, dict)
                assert "status" in result
            except Exception as e:
                # If validation works, should not raise exceptions for valid URLs
                pytest.fail(f"Valid URL {url} should not raise exception: {e}")

    def test_web_archive_url_validation_with_invalid_urls(self, archive):
        """
        GIVEN WebArchive instance and invalid URL formats
        WHEN URL validation is performed with malformed URLs
        THEN validation returns error status for invalid URLs
        """
        # Test URL validation with invalid formats
        invalid_urls = [
            "not_a_url",
            "ftp://invalid-scheme.com",
            "https://",
            ""
        ]
        
        for url in invalid_urls:
            result = archive.archive_url(url)
            # Should return error dict for invalid URLs
            assert isinstance(result, dict)
            assert result.get("status") == "error" or "error" in result.get("message", "").lower()