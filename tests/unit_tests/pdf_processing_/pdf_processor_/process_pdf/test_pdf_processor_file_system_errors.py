"""
Test cases for file system related issues in process_pdf method.

This module tests the process_pdf method's handling of file system errors,
including non-existent files, permission errors, and file locking issues.
Shared terminology: "file system error" refers to OS-level errors when
accessing files or directories.
"""

import pytest
import os
import stat
from pathlib import Path
from typing import Any
from unittest.mock import patch, mock_open

from ipfs_datasets_py.pdf_processing.pdf_processor import PDFProcessor

@pytest.fixture
def valid_file_path(tmp_path: Path) -> str:
    """Generate a valid file path for testing."""
    test_file = tmp_path / "test.pdf"
    test_file.write_text("test content" * 10)
    return str(test_file)


@pytest.fixture
def unreachable_network_path() -> str:
    """Generate a network path that is unreachable."""
    return "//unreachable-server/share/file.pdf"


@pytest.fixture
def nonexistent_file_path() -> str:
    """Generate a path to a non-existent file."""
    return "/path/to/nonexistent/file.pdf"


@pytest.fixture
def no_permissions_file_path(tmp_path: Path):
    """Create a file with no read permissions for testing."""
    try:
        no_perm_file = tmp_path / "no_read.pdf"
        no_perm_file.write_text("test content" * 10)
        # Remove read permissions
        no_perm_file.chmod(stat.S_IWUSR)
        yield str(no_perm_file)
    finally:
        # Restore permissions to allow cleanup
        no_perm_file.chmod(stat.S_IWUSR | stat.S_IRUSR)


@pytest.fixture
def test_scenarios(
        unreachable_network_path,
        nonexistent_file_path,
        no_permissions_file_path,
        locked_pdf_file
        ):
    """Store test paths."""
    return {
        'unreachable_network': unreachable_network_path,
        'nonexistent_file': nonexistent_file_path,
        'no_permissions': no_permissions_file_path,
        'locked_file': locked_pdf_file
    }

@pytest.fixture
def expected_permission_denied_message() -> str:
    """Expected error message for permission denied."""
    return "Insufficient permissions to read PDF file"

@pytest.fixture
def expected_locked_file_message() -> str:
    """Expected error message for locked file."""
    return "PDF file is locked by another process"

@pytest.fixture
def expected_file_not_found_message() -> str:
    """Expected error message for file not found."""
    return "does not exist"

@pytest.fixture
def expected_error_messages(
    expected_permission_denied_message,
    expected_locked_file_message,
    expected_file_not_found_message,
    ) -> dict:
    """Aggregate expected error messages for file system errors."""
    return {
        'no_permissions': expected_permission_denied_message,
        'locked_file': expected_locked_file_message,
        'nonexistent_file': expected_file_not_found_message,
        'unreachable_network': expected_file_not_found_message,
        'file_deleted_during_processing': expected_file_not_found_message,
    }


@pytest.fixture
def mock_open_with_deletion(tmp_path: Path):
    """
    Fixture to mock open function that deletes the file when opened.

    This simulates a file being deleted during processing.
    """
    original_open = open
    def mock_open_with_deletion(*args, **kwargs):
        if args[0] == tmp_path:
            # Delete the file before opening
            tmp_path.unlink()
            raise FileNotFoundError(f"No such file: {tmp_path}")
        return original_open(*args, **kwargs)
    return mock_open_with_deletion

@pytest.fixture
def expected_status_error():
    return "error"

class TestProcessPdfFileSystemNonFatalErrors:
    """
    Test file system error handling for the process_pdf method.

    Tests the process_pdf method's ability to handle various file system
    errors gracefully, including missing files, permission issues, and
    file locking scenarios.

    Shared terminology:
    - "file system error": OS-level errors when accessing files
    - "permission error": Insufficient rights to perform file operations
    - "locked file": File currently in use by another process
    """

    @pytest.mark.asyncio
    async def test_when_file_deleted_during_processing_then_returns_error_status(
        self, 
        real_pdf_processor_defaults, 
        valid_file_path,
        valid_metadata,
        mock_open_with_deletion,
        expected_status_error
    ):
        """
        GIVEN a file that gets deleted during processing
        WHEN process_pdf is called
        THEN returns dictionary with status='error'
        """
        with patch("builtins.open", side_effect=mock_open_with_deletion):
            result = await real_pdf_processor_defaults.process_pdf(valid_file_path, valid_metadata)

        assert result['status'] == expected_status_error, \
            f"Expected status to be error, got {result['status']} instead."


    @pytest.mark.asyncio
    async def test_when_file_deleted_during_processing_then_error_message_contains_file_path(
        self, 
        real_pdf_processor_defaults, 
        valid_file_path,
        valid_metadata,
        mock_open_with_deletion
    ):
        """
        GIVEN a file that gets deleted during processing
        WHEN process_pdf is called
        THEN error message contains the file path
        """
        with patch("builtins.open", side_effect=mock_open_with_deletion):
            result = await real_pdf_processor_defaults.process_pdf(valid_file_path, valid_metadata)

        assert valid_file_path in result['error'], \
            f"Expected error message to contain '{valid_file_path}', got '{result['error']}' instead."

    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", [
        'no_permissions',
        'unreachable_network',
        'locked_file',
        'nonexistent_file',
    ])
    async def test_when_file_encounters_bad_file_on_opening_then_returns_error_status(
        self, 
        scenario, 
        real_pdf_processor_defaults: PDFProcessor, 
        test_scenarios, 
        valid_metadata, 
        expected_status_error
    ):
        """
        GIVEN a file that encounters a file system error
        WHEN process_pdf is called
        THEN returns dictionary with status='error'
        """
        bad_file = test_scenarios[scenario]

        result = await real_pdf_processor_defaults.process_pdf(bad_file, valid_metadata)

        assert result['status'] == expected_status_error, \
            f"Expected status to be error, got {result['status']} instead."


    @pytest.mark.asyncio
    @pytest.mark.parametrize("scenario", [
        'no_permissions',
        'unreachable_network',
        #'locked_file', FIXME locking it via open('w') doesn't actually lock the file.
        'nonexistent_file',
    ])
    async def test_when_file_encounters_bad_file_on_opening_then_returns_error_status(
        self, 
        scenario, 
        real_pdf_processor_defaults, 
        test_scenarios,
        expected_error_messages, 
        valid_metadata
    ):
        """
        GIVEN a file that encounters a file system error
        WHEN process_pdf is called
        THEN returns dictionary with status='error'
        """
        bad_file = test_scenarios[scenario]
        error_msg = expected_error_messages[scenario]

        result = await real_pdf_processor_defaults.process_pdf(bad_file, valid_metadata)

        assert error_msg in result['error'], \
            f"Expected error message to contain '{error_msg}', got '{result['error']}' instead."

