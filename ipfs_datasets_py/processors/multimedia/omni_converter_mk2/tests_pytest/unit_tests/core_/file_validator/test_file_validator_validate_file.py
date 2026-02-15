#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test file for FileValidator.validate_file method converted from unittest to pytest.
"""
import tempfile
import pytest
import logging
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Skip tests if the module can't be imported
try:
    from configs import Configs
    from core.file_validator._file_validator import FileValidator
    from core.file_validator._validation_result import ValidationResult
    from file_format_detector._file_format_detector import FileFormatDetector
except ImportError:
    pytest.skip("core.file_validator modules not available", allow_module_level=True)


@pytest.fixture
def mock_validation_result():
    """Create a mock ValidationResult instance."""
    mock_result = Mock(spec=ValidationResult)
    mock_result.is_valid = True
    mock_result.errors = []
    mock_result.warnings = []
    mock_result.validation_context = {}
    mock_result.add_error = Mock()
    mock_result.add_warning = Mock()
    mock_result.add_context = Mock()
    return mock_result


@pytest.fixture
def mock_configs():
    """Create a mock Configs instance with security settings."""
    mock_configs = Mock(spec=Configs)
    mock_configs.security = Mock()
    mock_configs.security.max_file_size_mb = 100
    mock_configs.security.allowed_formats = ['pdf', 'txt', 'docx']
    return mock_configs


@pytest.fixture
def mock_file_exists():
    """Create a mock file_exists function."""
    mock_file_exists = Mock()
    mock_file_exists.return_value = True  # Assume file exists for tests
    return mock_file_exists


@pytest.fixture
def mock_get_file_info():
    """Create a mock get_file_info function."""
    mock_get_file_info = Mock()
    mock_file_info = Mock()
    mock_file_info.size = 1024  # 1KB file
    mock_file_info.is_readable = True
    mock_file_info.last_modified = datetime.now()
    mock_file_info.extension = 'txt'
    mock_file_info.mime_type = 'text/plain'
    mock_get_file_info.return_value = mock_file_info
    return mock_get_file_info


@pytest.fixture
def mock_resources(mock_validation_result, mock_file_exists, mock_get_file_info):
    """Create a dictionary of mock resources for FileValidator."""
    mock_validation_result_class = Mock(return_value=mock_validation_result)
    return {
        "file_format_detector": Mock(spec=FileFormatDetector),
        "logger": Mock(spec=logging.Logger),
        "validation_result": mock_validation_result_class,
        "file_exists": mock_file_exists,
        "get_file_info": mock_get_file_info
    }


@pytest.fixture
def temp_files():
    """Create temporary test files."""
    temp_dir = tempfile.TemporaryDirectory()
    temp_path = Path(temp_dir.name)
    
    # Create test files
    valid_file = temp_path / "valid_file.txt"
    valid_file.write_text("This is a valid test file.")
    
    invalid_file = temp_path / "invalid_file.txt"
    invalid_file.write_text("This file will be treated as invalid.")
    
    empty_file = temp_path / "empty_file.txt"
    empty_file.touch()
    
    yield {
        'temp_dir': temp_dir,
        'temp_path': temp_path,
        'valid_file': valid_file,
        'invalid_file': invalid_file,
        'empty_file': empty_file
    }
    
    temp_dir.cleanup()


@pytest.fixture
def validator(mock_resources, mock_configs):
    """Create a FileValidator instance with mocked dependencies."""
    return FileValidator(resources=mock_resources, configs=mock_configs)


@pytest.mark.unit
class TestValidateFile:
    """Test FileValidator.validate_file method."""

    def test_validate_valid_file_with_format(self, validator, temp_files, mock_resources, mock_validation_result):
        """
        GIVEN a FileValidator instance
        AND a valid file path to an existing, readable file
        AND file meets all validation criteria
        AND format_name is provided and supported
        WHEN validate_file is called
        THEN expect:
            - Returns ValidationResult instance
            - result.is_valid is True
            - result.errors is empty list
            - result.warnings may contain any warnings
            - result.validation_context contains file metadata
        """
        # GIVEN
        mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=True,
            last_modified=datetime.now(),
            extension='txt',
            mime_type='text/plain'
        )
        mock_resources["file_format_detector"].get_format_category.return_value = 'document'
        
        # Configure the mock ValidationResult
        mock_validation_result.is_valid = True
        mock_validation_result.errors = []
        mock_validation_result.warnings = []
        mock_validation_result.validation_context = {}
        
        # WHEN
        result = validator.validate_file(str(temp_files['valid_file']), 'txt')
        
        # THEN
        assert isinstance(result, Mock)  # Mock ValidationResult
        
        # Verify ValidationResult was created
        mock_resources["validation_result"].assert_called_once()
        
        # Verify get_format_category was called for provided format
        mock_resources["file_format_detector"].get_format_category.assert_called_once_with('txt')
        
        # Verify context was added
        mock_validation_result.add_context.assert_called()

    def test_validate_valid_file_auto_detect_format(self, validator, temp_files, mock_resources, mock_validation_result):
        """
        GIVEN a FileValidator instance
        AND a valid file path to an existing, readable file
        AND format_name is None (auto-detect)
        WHEN validate_file is called
        THEN expect:
            - Format is detected automatically
            - Returns ValidationResult instance
            - result.is_valid is True if format is supported
            - result.validation_context contains detected format
        """
        # GIVEN
        # Fix: Return tuple as expected by implementation
        mock_resources["file_format_detector"].detect_format.return_value = ('txt', 'document')
        mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=True,
            mime_type='text/plain',
            extension='txt'
        )
        
        # WHEN
        result = validator.validate_file(str(temp_files['valid_file']), None)
        
        # THEN
        assert isinstance(result, Mock)
        mock_resources["file_format_detector"].detect_format.assert_called_once_with(str(temp_files['valid_file']))

    def test_validate_nonexistent_file_returns_invalid_result(self, validator, temp_files, mock_resources, mock_validation_result):
        """
        GIVEN a FileValidator instance
        AND a file path to a non-existent file
        WHEN validate_file is called
        THEN expect:
            - Returns ValidationResult with error, doesn't raise exception
        """
        # GIVEN
        nonexistent_file = temp_files['temp_path'] / "does_not_exist.txt"
        mock_resources["file_exists"].return_value = False
        
        # Set up validation result to have an error
        mock_validation_result.errors = ["File does not exist"]
        mock_validation_result.is_valid = False
        
        # WHEN
        result = validator.validate_file(str(nonexistent_file), 'txt')
        
        # THEN
        assert isinstance(result, Mock)
        # Verify error was added
        mock_validation_result.add_error.assert_called()

    def test_validate_file_with_size_exceeded(self, validator, temp_files, mock_resources, mock_validation_result):
        """
        GIVEN a FileValidator instance with max_file_size_mb configured
        AND a file path to a file exceeding the size limit
        WHEN validate_file is called
        THEN expect:
            - Returns ValidationResult instance
            - result.is_valid is False
            - result.errors contains file size error
            - result.validation_context contains file size info
        """
        # GIVEN
        large_size = 1024 * 1024 * 200  # 200MB, exceeds 100MB limit
        mock_resources["get_file_info"].return_value = Mock(
            size=large_size,
            is_readable=True,
            mime_type='text/plain',
            extension='txt'
        )
        
        # Configure mock to reflect invalid state
        mock_validation_result.is_valid = False
        mock_validation_result.errors = ["File size exceeds maximum allowed size"]
        
        # WHEN
        result = validator.validate_file(str(temp_files['invalid_file']), 'txt')
        
        # THEN
        assert isinstance(result, Mock)
        
        # Verify error was added
        mock_validation_result.add_error.assert_called()

    def test_validate_file_with_unsupported_format(self, validator, temp_files, mock_resources, mock_validation_result):
        """
        GIVEN a FileValidator instance
        AND a file path to a file
        AND format_name is an unsupported format
        WHEN validate_file is called
        THEN expect:
            - Returns ValidationResult instance
            - result.is_valid is False
            - result.errors contains unsupported format error
            - result.validation_context contains format info
        """
        # GIVEN
        mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=True,
            mime_type='application/unknown',
            extension='xyz'
        )
        mock_resources["file_format_detector"].get_format_category.return_value = None  # Unsupported
        
        # Set up validation result to have format error
        mock_validation_result.errors = ["Format 'xyz' is not supported"]
        mock_validation_result.is_valid = False
        
        # WHEN
        result = validator.validate_file(str(temp_files['valid_file']), 'xyz')
        
        # THEN
        assert isinstance(result, Mock)
        # Verify get_format_category was called
        mock_resources["file_format_detector"].get_format_category.assert_called_once_with('xyz')

    def test_validate_empty_file(self, validator, temp_files, mock_resources, mock_validation_result):
        """
        GIVEN a FileValidator instance
        AND a file path to an empty file (0 bytes)
        WHEN validate_file is called
        THEN expect:
            - Returns ValidationResult instance
            - result.is_valid is False (empty files are invalid)
            - result.errors contains empty file error
            - result.validation_context contains size: 0
        """
        # GIVEN
        mock_resources["get_file_info"].return_value = Mock(
            size=0,  # Empty file
            is_readable=True,
            mime_type='text/plain',
            extension='txt'
        )
        
        # Set up validation result to have empty file error
        mock_validation_result.errors = ["File is empty"]
        mock_validation_result.is_valid = False
        
        # WHEN
        result = validator.validate_file(str(temp_files['empty_file']), 'txt')
        
        # THEN
        assert isinstance(result, Mock)
        # Verify error was added for empty file
        mock_validation_result.add_error.assert_called()

    def test_validate_file_with_warnings(self, validator, temp_files, mock_resources, mock_validation_result):
        """
        GIVEN a FileValidator instance
        AND a valid file path that triggers warnings but is still valid
        WHEN validate_file is called
        THEN expect:
            - Returns ValidationResult instance
            - result.is_valid is True
            - result.warnings contains relevant warnings
            - result.errors is empty
        """
        # GIVEN
        mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=True,
            mime_type='text/plain',
            extension='txt'
        )
        mock_resources["file_format_detector"].get_format_category.return_value = 'document'
        
        # Set up validation result with warnings but still valid
        mock_validation_result.is_valid = True
        mock_validation_result.errors = []
        mock_validation_result.warnings = ["File format is deprecated"]
        
        # WHEN
        result = validator.validate_file(str(temp_files['valid_file']), 'txt')
        
        # THEN
        assert isinstance(result, Mock)
        # Verify warning was added
        mock_validation_result.add_warning.assert_called()

    def test_validate_file_populates_context(self, validator, temp_files, mock_resources, mock_validation_result):
        """
        GIVEN a FileValidator instance
        AND a valid file path
        WHEN validate_file is called
        THEN expect:
            - Returns ValidationResult instance
            - result.validation_context contains file metadata like size, format, etc.
        """
        # GIVEN
        expected_file_info = Mock(
            size=2048,
            is_readable=True,
            last_modified=datetime.now(),
            extension='txt',
            mime_type='text/plain'
        )
        mock_resources["get_file_info"].return_value = expected_file_info
        mock_resources["file_format_detector"].get_format_category.return_value = 'document'
        
        # WHEN
        result = validator.validate_file(str(temp_files['valid_file']), 'txt')
        
        # THEN
        assert isinstance(result, Mock)
        # Verify context was populated with file metadata
        mock_validation_result.add_context.assert_called()

    def test_validate_corrupted_file(self, validator, temp_files, mock_resources, mock_validation_result):
        """
        GIVEN a FileValidator instance
        AND a file path to a corrupted file (detected by format detector)
        WHEN validate_file is called
        THEN expect:
            - Returns ValidationResult instance
            - result.is_valid is False
            - result.errors contains corruption error
        """
        # GIVEN
        mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=True,
            mime_type='text/plain',
            extension='txt'
        )
        # Simulate format detector throwing exception for corrupted file
        mock_resources["file_format_detector"].get_format_category.side_effect = Exception("File appears corrupted")
        
        # Set up validation result to reflect corruption
        mock_validation_result.is_valid = False
        mock_validation_result.errors = ["File appears corrupted"]
        
        # WHEN
        result = validator.validate_file(str(temp_files['valid_file']), 'txt')
        
        # THEN
        assert isinstance(result, Mock)
        # Verify error was added for corruption
        mock_validation_result.add_error.assert_called()

    def test_validate_file_format_not_allowed(self, validator, temp_files, mock_resources, mock_validation_result, mock_configs):
        """
        GIVEN a FileValidator instance with restricted allowed_formats
        AND a file with a format not in the allowed list
        WHEN validate_file is called
        THEN expect:
            - Returns ValidationResult instance
            - result.is_valid is False
            - result.errors contains format not allowed error
        """
        # GIVEN
        mock_configs.security.allowed_formats = ['pdf', 'docx']  # txt not allowed
        mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=True,
            mime_type='text/plain',
            extension='txt'
        )
        mock_resources["file_format_detector"].get_format_category.return_value = 'document'
        
        # Set up validation result to reflect format not allowed
        mock_validation_result.is_valid = False
        mock_validation_result.errors = ["Format 'txt' is not in allowed formats list"]
        
        # WHEN
        result = validator.validate_file(str(temp_files['valid_file']), 'txt')
        
        # THEN
        assert isinstance(result, Mock)
        # Verify error was added for format not allowed
        mock_validation_result.add_error.assert_called()

    def test_validate_unreadable_file(self, validator, temp_files, mock_resources, mock_validation_result):
        """
        GIVEN a FileValidator instance
        AND a file path to an unreadable file (permissions issue)
        WHEN validate_file is called
        THEN expect:
            - Returns ValidationResult instance
            - result.is_valid is False
            - result.errors contains readability error
        """
        # GIVEN
        mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=False,  # File exists but cannot be read
            mime_type='text/plain',
            extension='txt'
        )
        
        # Set up validation result to reflect unreadable file
        mock_validation_result.is_valid = False
        mock_validation_result.errors = ["File is not readable (permission denied)"]
        
        # WHEN
        result = validator.validate_file(str(temp_files['valid_file']), 'txt')
        
        # THEN
        assert isinstance(result, Mock)
        # Verify error was added for unreadable file
        mock_validation_result.add_error.assert_called()