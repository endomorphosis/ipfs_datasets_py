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


class TestProcessPdfFileSystemErrors:
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
    @pytest.fixture
    def expected_permission_denied_message(self) -> str:
        """Expected error message for permission denied."""
        return "Insufficient permissions to read PDF file"

    @pytest.fixture
    def expected_locked_file_message(self) -> str:
        """Expected error message for locked file."""
        return "PDF file is locked by another process"

    @pytest.mark.asyncio
    async def test_when_nonexistent_file_provided_then_raises_file_not_found_error(
        self, 
        default_pdf_processor, 
        nonexistent_file_path, 
        valid_metadata,
        expected_file_not_found_message
    ):
        """
        GIVEN a path to non-existent file
        WHEN process_pdf is called
        THEN raises FileNotFoundError with message containing the file path
        """
        with pytest.raises(FileNotFoundError) as exc_info:
            await default_pdf_processor.process_pdf(nonexistent_file_path, valid_metadata)
        
        assert expected_file_not_found_message in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_when_file_has_no_read_permissions_then_returns_error_status(
        self, 
        default_pdf_processor, 
        no_read_permissions_file, 
        valid_metadata
    ):
        """
        GIVEN a file with no read permissions
        WHEN process_pdf is called
        THEN returns dictionary with status='error'
        """
        result = await default_pdf_processor.process_pdf(no_read_permissions_file, valid_metadata)
        
        assert result['status'] == 'error', f"Expected status to be error, got {result['status']} instead."

    @pytest.mark.asyncio
    async def test_when_file_has_no_read_permissions_then_error_message_contains_permission_text(
        self, 
        default_pdf_processor, 
        no_read_permissions_file, 
        valid_metadata,
        expected_permission_denied_message
    ):
        """
        GIVEN a file with no read permissions
        WHEN process_pdf is called
        THEN error message contains appropriate permission denied text
        """
        result = await default_pdf_processor.process_pdf(no_read_permissions_file, valid_metadata)
        
        assert expected_permission_denied_message in result['error'], \
            f"Expected error message to be '{expected_permission_denied_message}', got '{result['error']}' instead."

    @pytest.mark.asyncio
    async def test_when_file_is_locked_then_returns_error_status(
        self, 
        default_pdf_processor, 
        tmp_path,
        valid_metadata
    ):
        """
        GIVEN a file locked by another process
        WHEN process_pdf is called
        THEN returns dictionary with status='error'
        """
        locked_file = tmp_path / "locked.pdf"
        locked_file.write_text("test content")
        
        # Simulate file being locked by patching open to raise PermissionError
        with patch("builtins.open", side_effect=PermissionError("File is locked")):
            result = await default_pdf_processor.process_pdf(str(locked_file), valid_metadata)
        
        assert result['status'] == 'error'

    @pytest.mark.asyncio
    async def test_when_file_is_locked_then_error_message_contains_locked_text(
        self, 
        default_pdf_processor, 
        tmp_path,
        valid_metadata,
        expected_locked_file_message
    ):
        """
        GIVEN a file locked by another process
        WHEN process_pdf is called
        THEN error message contains appropriate locked file text
        """
        locked_file = tmp_path / "locked.pdf"
        locked_file.write_text("test content")

        # Simulate file being locked by patching open to raise PermissionError
        with patch("builtins.open", side_effect=PermissionError("File is locked")):
            result = await default_pdf_processor.process_pdf(str(locked_file), valid_metadata)

        assert expected_locked_file_message in result['error'], \
            f"Expected '{expected_locked_file_message}' to be in error, got {result['error']} instead"

    @pytest.mark.asyncio
    async def test_when_file_deleted_during_processing_then_returns_error_status(
        self, 
        default_pdf_processor, 
        tmp_path,
        valid_metadata
    ):
        """
        GIVEN a file that gets deleted during processing
        WHEN process_pdf is called
        THEN returns dictionary with status='error'
        """
        test_file = tmp_path / "temp.pdf"
        test_file.write_text("test content")
        file_path = str(test_file)
        
        # Mock the processing to delete the file after initial validation
        original_open = open
        def mock_open_with_deletion(*args, **kwargs):
            if args[0] == file_path:
                # Delete the file before opening
                test_file.unlink()
                raise FileNotFoundError(f"No such file: {file_path}")
            return original_open(*args, **kwargs)

        with patch("builtins.open", side_effect=mock_open_with_deletion):
            result = await default_pdf_processor.process_pdf(file_path, valid_metadata)
        
        assert result['status'] == 'error'

    @pytest.mark.asyncio
    async def test_when_file_deleted_during_processing_then_error_message_contains_file_path(
        self, 
        default_pdf_processor, 
        tmp_path,
        valid_metadata
    ):
        """
        GIVEN a file that gets deleted during processing
        WHEN process_pdf is called
        THEN error message contains the file path
        """
        test_file = tmp_path / "temp.pdf"
        test_file.write_text("test content")
        file_path = str(test_file)
        
        # Mock the processing to delete the file after initial validation
        original_open = open
        def mock_open_with_deletion(*args, **kwargs):
            if args[0] == file_path:
                # Delete the file before opening
                test_file.unlink()
                raise FileNotFoundError(f"No such file: {file_path}")
            return original_open(*args, **kwargs)
        
        with patch("builtins.open", side_effect=mock_open_with_deletion):
            result = await default_pdf_processor.process_pdf(file_path, valid_metadata)
        
        assert file_path in result['error']

    @pytest.mark.asyncio
    async def test_when_network_file_unavailable_then_returns_error_status(
        self, 
        default_pdf_processor,
        valid_metadata
    ):
        """
        GIVEN a network path that is unavailable
        WHEN process_pdf is called
        THEN returns dictionary with status='error'
        """
        network_path = "//unreachable-server/share/file.pdf"
        
        result = await default_pdf_processor.process_pdf(network_path, valid_metadata)
        
        assert result['status'] == 'error'

    @pytest.mark.asyncio
    async def test_when_network_file_unavailable_then_error_message_contains_network_path(
        self, 
        default_pdf_processor,
        valid_metadata
    ):
        """
        GIVEN a network path that is unavailable
        WHEN process_pdf is called
        THEN error message contains the network path
        """
        network_path = "//unreachable-server/share/file.pdf"
        
        result = await default_pdf_processor.process_pdf(network_path, valid_metadata)
        
        assert network_path in result['error']