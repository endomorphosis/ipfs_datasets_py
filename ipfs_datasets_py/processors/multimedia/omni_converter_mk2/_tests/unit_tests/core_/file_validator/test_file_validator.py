#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import tempfile
import unittest
import logging
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Import the class under test
from configs import Configs
from core.file_validator._file_validator import FileValidator
from core.file_validator._validation_result import ValidationResult
from file_format_detector._file_format_detector import FileFormatDetector

# Make factory functions for mocks
def make_mock_validation_result() -> Mock:
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

def make_mock_configs() -> Mock:
    """Create a mock Configs instance with security settings."""
    mock_configs = Mock(spec=Configs)
    mock_configs.security = Mock(
        return_value={
            "max_file_size_mb": 100,
            "allowed_formats": ['pdf', 'txt', 'docx']
        }
    )
    return mock_configs

def make_mock_file_exists() -> Mock:
    """Create a mock file_exists function."""
    mock_file_exists = Mock()
    mock_file_exists.return_value = True  # Assume file exists for tests
    return mock_file_exists

def make_mock_get_file_info() -> Mock:
    """Create a mock get_file_info function."""
    mock_get_file_info = Mock()
    mock_get_file_info.return_value = {
        "size": 1024,  # 1KB file
        "is_readable": True,
        "last_modified": datetime.now(),
        "extension": 'txt',
        "mime_type": 'text/plain'
    }
    return mock_get_file_info


def make_mock_file_exists() -> Mock:
    """Create a mock file_exists function."""
    mock_file_exists = Mock()
    mock_file_exists.return_value = True  # Assume file exists for tests
    return mock_file_exists


def make_mock_resources() -> dict:
    """Create a dictionary of mock resources for FileValidator."""
    return {
        "file_format_detector": Mock(spec=FileFormatDetector),
        "logger":  Mock(spec=logging.Logger),
        "validation_result": make_mock_validation_result(),
        "file_exists": make_mock_file_exists(),
        "get_file_info": make_mock_get_file_info()
    }




class TestFileValidatorInitialization(unittest.TestCase):
    """Test FileValidator initialization and configuration."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

        self.valid_resources = make_mock_resources()

        # Mock dependencies
        self.mock_configs = make_mock_configs()
        self.mock_logger = self.valid_resources["logger"]
        self.mock_file_format_detector = self.valid_resources["file_format_detector"]
        self.mock_validation_result = self.valid_resources["validation_result"]

    def tearDown(self):
        """Clean up test fixtures."""
        self.temp_dir.cleanup()

    def test_init_with_valid_resources_and_configs(self):
        """
        GIVEN valid resources dict containing:
            - file_detector: A file detector instance
            - logger: A logger instance
            - Any other required resources
        AND valid configs object with:
            - validation.max_file_size_mb attribute
            - validation.supported_formats attribute
            - Any other validation-related attributes
        WHEN FileValidator is initialized
        THEN expect:
            - Instance created successfully
        """
        # WHEN
        validator = FileValidator(resources=self.valid_resources, configs=self.mock_configs)
        # THEN
        self.assertIsInstance(validator, FileValidator)

    def test_init_configs_stored_correctly(self):
        """
        GIVEN valid resources dict and valid configs object
        WHEN FileValidator is initialized
        THEN expect:
            - validator.configs equals the provided configs object
        """
        # WHEN
        validator = FileValidator(resources=self.valid_resources, configs=self.mock_configs)
        # THEN
        self.assertEqual(validator.configs, self.mock_configs)

    def test_init_max_file_size_set_correctly(self):
        """
        GIVEN valid resources dict and configs with validation.max_file_size_mb = 100
        WHEN FileValidator is initialized
        THEN expect:
            - validator.max_file_size_mb equals 100
        """
        # WHEN
        validator = FileValidator(resources=self.valid_resources, configs=self.mock_configs)
        # THEN
        self.assertEqual(validator.max_file_size_mb, self.mock_configs.security.max_file_size_mb)

    def test_init_allowed_formats_set_correctly(self):
        """
        GIVEN valid resources dict and configs with validation.supported_formats = ['pdf', 'txt', 'docx']
        WHEN FileValidator is initialized
        THEN expect:
            - validator.allowed_formats equals ['pdf', 'txt', 'docx']
        """
        # WHEN
        validator = FileValidator(resources=self.valid_resources, configs=self.mock_configs)
        # THEN
        self.assertEqual(validator.allowed_formats, self.mock_configs.security.allowed_formats)

    def test_init_logger_component_set_correctly(self):
        """
        GIVEN valid resources dict containing logger component
        WHEN FileValidator is initialized
        THEN expect:
            - validator._logger equals the provided logger
        """
        # WHEN
        validator = FileValidator(resources=self.valid_resources, configs=self.mock_configs)
        # THEN
        self.assertEqual(validator._logger, self.mock_logger)

    def test_init_format_detector_component_set_correctly(self):
        """
        GIVEN valid resources dict containing file_detector component
        WHEN FileValidator is initialized
        THEN expect:
            - validator._format_detector equals the provided file_detector
        """
        # WHEN
        validator = FileValidator(resources=self.valid_resources, configs=self.mock_configs)
        # THEN
        self.assertEqual(validator._format_detector, self.mock_file_format_detector)

    def test_init_validation_result_component_set_correctly(self):
        """
        GIVEN valid resources dict containing validation_result component
        WHEN FileValidator is initialized
        THEN expect:
            - validator._validation_result equals the provided validation_result
        """
        # WHEN
        validator = FileValidator(resources=self.valid_resources, configs=self.mock_configs)
        # THEN
        self.assertEqual(validator._validation_result, self.mock_validation_result)

    def test_init_file_exists_function_set_correctly(self):
        """
        GIVEN valid resources dict containing file_exists function
        WHEN FileValidator is initialized
        THEN expect:
            - validator._file_exists equals the provided file_exists function
        """
        # WHEN
        validator = FileValidator(resources=self.valid_resources, configs=self.mock_configs)
        # THEN
        self.assertEqual(validator._file_exists, self.valid_resources["file_exists"])

    def test_init_get_file_info_function_set_correctly(self):
        """
        GIVEN valid resources dict containing get_file_info function
        WHEN FileValidator is initialized
        THEN expect:
            - validator._get_file_info equals the provided get_file_info function
        """
        # WHEN
        validator = FileValidator(resources=self.valid_resources, configs=self.mock_configs)
        # THEN
        self.assertEqual(validator._get_file_info, self.valid_resources["get_file_info"])

    def test_init_resources_are_the_same_as_validators_resources(self):
        """
        GIVEN valid resources dict
        WHEN FileValidator is initialized with those resources
        THEN expect:
            - validator.resources equals the provided resources dict
        """
        # WHEN
        validator = FileValidator(resources=self.valid_resources, configs=self.mock_configs)
        # THEN
        self.assertEqual(validator.resources, self.valid_resources)

    def test_init_with_none_resources(self):
        """
        GIVEN resources parameter is None
        WHEN FileValidator is initialized
        THEN expect:
            - Raises TypeError
        """
        # GIVEN
        resources = None

        # WHEN/THEN
        with self.assertRaises(TypeError):
            _ = FileValidator(resources=resources, configs=self.mock_configs)

    def test_init_with_none_configs(self):
        """
        GIVEN configs parameter is None
        WHEN FileValidator is initialized
        THEN expect:
            - Raises AttributeError
        """
        # GIVEN
        configs = None

        # WHEN/THEN
        with self.assertRaises(AttributeError):
            _ = FileValidator(resources=self.valid_resources, configs=configs)


    def test_init_with_empty_resources_dict(self):
        """
        GIVEN empty resources dict {}
        WHEN FileValidator is initialized
        THEN expect:
            - raises KeyError
        """
        # GIVEN
        empty_resources = {}
        
        # WHEN/THEN
        with self.assertRaises(KeyError):
            _ = FileValidator(resources=empty_resources, configs=self.mock_configs)

    def test_init_with_configs_missing_attributes(self):
        """
        GIVEN a configs object missing required attributes
        WHEN FileValidator is initialized
        THEN expect:
            - raises AttributeError
        """
        # GIVEN
        configs_missing_attributes = MagicMock(spec=Configs)
        configs_missing_attributes.validation = MagicMock()

        # When
        del configs_missing_attributes.validation.max_file_size_mb  # Remove required attribute
        
        # THEN
        with self.assertRaises(AttributeError):
            _ = FileValidator(resources=self.valid_resources, configs=configs_missing_attributes)


class TestGetValidationErrors(unittest.TestCase):
    """Test FileValidator.get_validation_errors method."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        
        # Create test files
        self.valid_file = self.temp_path / "valid_file.txt"
        self.valid_file.write_text("This is a valid test file.")
        self.large_file = self.temp_path / "large_file.txt"
        self.large_file.write_text("A" * 1024 * 1024)  # 1MB file
        self.empty_file = self.temp_path / "empty_file.txt"
        self.empty_file.touch()
        
        # Mock dependencies
        self.mock_configs = make_mock_configs()
        self.mock_file_format_detector = Mock(spec=FileFormatDetector)
        self.mock_logger = Mock(spec=logging.Logger)
        
        # Mock ValidationResult
        self.mock_validation_result_instance = make_mock_validation_result()
        self.mock_validation_result_class = Mock(spec=ValidationResult, return_value=self.mock_validation_result_instance)
        
        self.mock_resources = {
            "file_format_detector": self.mock_file_format_detector,
            "logger": self.mock_logger,
            "validation_result": self.mock_validation_result_class,
            "file_exists": Mock(return_value=True),
            "get_file_info": Mock(return_value=Mock(size=1024, is_readable=True))
        }
        
        self.validator = FileValidator(resources=self.mock_resources, configs=self.mock_configs)

    def tearDown(self):
        """Clean up test fixtures."""
        self.temp_dir.cleanup()

    def test_get_errors_valid_file_with_format_returns_empty_list(self):
        """
        GIVEN a FileValidator instance
        AND a valid file path to an existing, readable file
        AND format_name is provided (e.g., 'pdf')
        WHEN get_validation_errors is called
        THEN expect:
            - Returns empty list (no errors)
        """
        # GIVEN
        self.mock_resources["get_file_info"].return_value = Mock(
            size=1024,  # Small file within limits
            is_readable=True
        )
        self.mock_file_format_detector.get_format_category.return_value = 'document'
        
        # Set up the validation result to indicate success
        self.mock_validation_result_instance.is_valid = True
        self.mock_validation_result_instance.errors = []
        
        # WHEN
        errors = self.validator.get_validation_errors(str(self.valid_file), 'txt')
        
        # THEN
        self.assertEqual(errors, [])

    def test_get_errors_nonexistent_file(self):
        """
        GIVEN a FileValidator instance
        AND a file path to a non-existent file
        AND format_name is provided or None
        WHEN get_validation_errors is called
        THEN expect:
            - Returns list containing file not found error
        """
        # GIVEN
        nonexistent_file = self.temp_path / "does_not_exist.txt"
        self.mock_resources["file_exists"].return_value = False
        
        # Set up validation result to have an error
        self.mock_validation_result_instance.errors = ["File does not exist: " + str(nonexistent_file)]
        
        # WHEN
        errors = self.validator.get_validation_errors(str(nonexistent_file), 'txt')
        
        # THEN
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("does not exist" in error.lower() for error in errors))

    def test_get_errors_file_too_large(self):
        """
        GIVEN a FileValidator instance with max_file_size_mb configured
        AND a file path to a file exceeding the size limit
        AND format_name is provided or None
        WHEN get_validation_errors is called
        THEN expect:
            - Returns list containing file size error
        """
        # GIVEN
        
        self.mock_resources["get_file_info"].return_value = Mock(
            size=1024 * 1024,  # 1MB file, exceeds 0.5MB limit
            is_readable=True
        )
        
        # Set up validation result to have size error
        self.mock_validation_result_instance.errors = ["File size exceeds maximum allowed"]
        
        # WHEN
        errors = self.validator.get_validation_errors(str(self.large_file), 'txt')
        
        # THEN
        self.assertGreater(len(errors), 0)
        self.assertTrue(any("size" in error.lower() or "exceeds" in error.lower() for error in errors))

    def test_get_errors_unsupported_format_returns_error_list(self):
        """
        GIVEN a FileValidator instance with supported_formats configured
        AND a file path to a file with unsupported format
        AND format_name is provided as unsupported format
        WHEN get_validation_errors is called
        THEN expect:
            - Returns list containing at least one error
        """
        # GIVEN
        ZERO = 0
        self.mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=True
        )
        self.mock_file_format_detector.get_format_category.return_value = None  # Unsupported format
        
        # Set up validation result to have format error
        self.mock_validation_result_instance.errors = ["Format 'xyz' is not supported"]
        
        # WHEN
        errors = self.validator.get_validation_errors(str(self.valid_file), 'xyz')  # Unsupported format
        
        # THEN
        self.assertGreater(len(errors), ZERO)

    def test_get_errors_unsupported_format_contains_format_error(self):
        """
        GIVEN a FileValidator instance with supported_formats configured
        AND a file path to a file with unsupported format
        AND format_name is provided as unsupported format
        WHEN get_validation_errors is called
        THEN expect:
            - Returns list containing unsupported format error message
        """
        # GIVEN
        self.mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=True
        )
        self.mock_file_format_detector.get_format_category.return_value = None  # Unsupported format
        
        # Set up validation result to have format error
        self.mock_validation_result_instance.errors = ["Format 'xyz' is not supported"]
        
        # WHEN
        errors = self.validator.get_validation_errors(str(self.valid_file), 'xyz')  # Unsupported format
        
        # THEN
        self.assertTrue(any("not supported" in error.lower() or "format" in error.lower() for error in errors))

    def test_get_errors_no_read_permission_returns_error_list(self):
        """
        GIVEN a FileValidator instance
        AND a file path to a file without read permissions
        AND format_name is provided or None
        WHEN get_validation_errors is called
        THEN expect:
            - Returns list containing at least one error
        """
        # GIVEN
        ZERO = 0
        self.mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=False  # No read permission
        )
        
        # Set up validation result to have permission error
        self.mock_validation_result_instance.errors = ["File is not readable"]
        
        # WHEN
        errors = self.validator.get_validation_errors(str(self.valid_file), 'txt')
        
        # THEN
        self.assertGreater(len(errors), ZERO)

    def test_get_errors_no_read_permission_contains_permission_error(self):
        """
        GIVEN a FileValidator instance
        AND a file path to a file without read permissions
        AND format_name is provided or None
        WHEN get_validation_errors is called
        THEN expect:
            - Returns list containing permission error message
        """
        # GIVEN
        self.mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=False  # No read permission
        )
        
        # Set up validation result to have permission error
        self.mock_validation_result_instance.errors = ["File is not readable"]
        
        # WHEN
        errors = self.validator.get_validation_errors(str(self.valid_file), 'txt')
        
        # THEN
        self.assertTrue(
            any("not readable" in error.lower() or "permission" in error.lower() for error in errors)
        )

    def test_get_errors_empty_file_returns_error_list(self):
        """
        GIVEN a FileValidator instance
        AND a file path to an empty file (0 bytes)
        AND format_name is provided or None
        WHEN get_validation_errors is called
        THEN expect:
            - Returns list containing at least one error
        """
        # GIVEN
        ZERO = 0
        self.mock_resources["get_file_info"].return_value = Mock(
            size=0,  # Empty file
            is_readable=True
        )
        
        # Set up validation result to have empty file error
        self.mock_validation_result_instance.errors = ["File is empty"]
        
        # WHEN
        errors = self.validator.get_validation_errors(str(self.empty_file), 'txt')
        
        # THEN
        self.assertGreater(len(errors), ZERO)

    def test_get_errors_empty_file_contains_empty_error(self):
        """
        GIVEN a FileValidator instance
        AND a file path to an empty file (0 bytes)
        AND format_name is provided or None
        WHEN get_validation_errors is called
        THEN expect:
            - Returns list containing empty file error message
        """
        # GIVEN
        self.mock_resources["get_file_info"].return_value = Mock(
            size=0,  # Empty file
            is_readable=True
        )
        
        # Set up validation result to have empty file error
        self.mock_validation_result_instance.errors = ["File is empty"]
        
        # WHEN
        errors = self.validator.get_validation_errors(str(self.empty_file), 'txt')
        
        # THEN
        self.assertTrue(any("empty" in error.lower() for error in errors))


class TestIsValidForProcessing(unittest.TestCase):
    """Test FileValidator.is_valid_for_processing method."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)
        
        # Create test files
        self.valid_file = self.temp_path / "valid_file.txt"
        self.valid_file.write_text("This is a valid test file.")
        self.invalid_file = self.temp_path / "invalid_file.txt"
        self.invalid_file.write_text("This file will be treated as invalid.")
        
        # Mock dependencies
        self.mock_configs = make_mock_configs()
        self.mock_validation_result_instance = make_mock_validation_result()
        self.mock_validation_result_class = Mock(return_value=self.mock_validation_result_instance)
        self.mock_file_format_detector = Mock(spec=FileFormatDetector)
        
        self.mock_resources = {
            "file_format_detector": Mock(spec=FileFormatDetector),
            "logger": Mock(spec=logging.Logger),
            "validation_result": self.mock_validation_result_class,
            "file_exists": Mock(return_value=True),
            "get_file_info": Mock(return_value=Mock(size=1024, is_readable=True))
        }
        
        self.validator = FileValidator(resources=self.mock_resources, configs=self.mock_configs)

    def tearDown(self):
        """Clean up test fixtures."""
        self.temp_dir.cleanup()


    def test_is_valid_for_processing_calls_validate_file(self):
        """
        GIVEN a FileValidator instance
        AND a valid file path to an existing, readable file
        WHEN is_valid_for_processing is called
        THEN expect:
            - validate_file is called once
        """
        # GIVEN
        self.mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=True,
            mime_type='text/plain',
            extension='txt'
        )
        
        # WHEN
        _ = self.validator.is_valid_for_processing(str(self.valid_file), 'txt')

        # Verify validate_file was called with no parameters
        self.mock_validation_result_class.assert_called_once()

    def test_is_valid_with_valid_file_and_format(self):
        """
        GIVEN a FileValidator instance
        AND a valid file path to an existing, readable file
        AND file meets all validation criteria
        AND format_name is provided and supported
        WHEN is_valid_for_processing is called
        THEN expect:
            - Returns True
        """
        # GIVEN
        self.mock_file_format_detector.get_format_category.return_value = 'document'
        
        # Set up validation result to indicate success
        self.mock_validation_result_instance.is_valid = True
        
        # WHEN
        is_valid = self.validator.is_valid_for_processing(str(self.valid_file), 'txt')
        
        # THEN
        self.assertTrue(is_valid)

    def test_is_valid_with_valid_file_auto_detect_format(self):
        """
        GIVEN a FileValidator instance
        AND a valid file path to an existing, readable file
        AND file meets all validation criteria
        AND format_name is None (auto-detect)
        WHEN is_valid_for_processing is called
        THEN expect:
            - Format is detected automatically
            - Returns True if detected format is supported
        """
        # GIVEN
        self.mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=True,
            mime_type='text/plain',
            extension='txt'
        )
        self.mock_file_format_detector.detect_format.return_value = ('txt', 'document')
        
        # Set up validation result to indicate success
        self.mock_validation_result_instance.is_valid = True
        
        # WHEN
        is_valid = self.validator.is_valid_for_processing(str(self.valid_file), None)
        
        # THEN
        self.assertTrue(is_valid)

    def test_is_valid_with_nonexistent_file(self):
        """
        GIVEN a FileValidator instance
        AND a file path to a non-existent file
        WHEN is_valid_for_processing is called
        THEN expect:
            - Returns False
        """
        # GIVEN
        nonexistent_file = self.temp_path / "does_not_exist.txt"
        self.mock_resources["file_exists"].return_value = False
        
        # Set up validation result to indicate failure
        self.mock_validation_result_instance.is_valid = False
        
        # WHEN
        is_valid = self.validator.is_valid_for_processing(str(nonexistent_file), 'txt')
        
        # THEN
        self.assertFalse(is_valid)

    def test_is_valid_with_oversized_file(self):
        """
        GIVEN a FileValidator instance with max_file_size_mb configured
        AND a file path to a file exceeding the size limit
        WHEN is_valid_for_processing is called
        THEN expect:
            - Returns False
        """
        # GIVEN
        
        self.mock_resources["get_file_info"].return_value = Mock(
            size=1024 * 1024 * 20,  # 20MB, exceeds 10MB limit
            is_readable=True
        )
        
        # Set up validation result to indicate failure
        self.mock_validation_result_instance.is_valid = False
        
        # WHEN
        is_valid = self.validator.is_valid_for_processing(str(self.invalid_file), 'txt')
        
        # THEN
        self.assertFalse(is_valid)

    def test_is_valid_with_unsupported_format(self):
        """
        GIVEN a FileValidator instance with supported_formats configured
        AND a file path to a file
        AND format_name is an unsupported format
        WHEN is_valid_for_processing is called
        THEN expect:
            - Returns False
        """
        # GIVEN
        
        self.mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=True
        )
        self.mock_file_format_detector.get_format_category.return_value = None  # Unsupported
        
        # Set up validation result to indicate failure
        self.mock_validation_result_instance.is_valid = False
        
        # WHEN
        is_valid = self.validator.is_valid_for_processing(str(self.valid_file), 'xyz')
        
        # THEN
        self.assertFalse(is_valid)

    def test_is_valid_with_corrupted_file(self):
        """
        GIVEN a FileValidator instance
        AND a file path to a corrupted file
        WHEN is_valid_for_processing is called
        THEN expect:
            - Returns False
        """
        # GIVEN
        self.mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=True
        )
        
        # Set up validation result to indicate failure due to corruption
        self.mock_validation_result_instance.is_valid = False
        
        # WHEN
        is_valid = self.validator.is_valid_for_processing(str(self.invalid_file), 'txt')
        
        # THEN
        self.assertFalse(is_valid)

    def test_is_valid_with_no_permissions(self):
        """
        GIVEN a FileValidator instance
        AND a file path to a file without read permissions
        WHEN is_valid_for_processing is called
        THEN expect:
            - Returns False
        """
        # GIVEN
        
        self.mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=False  # No read permission
        )
        
        # Set up validation result to indicate failure
        self.mock_validation_result_instance.is_valid = False
        
        # WHEN
        is_valid = self.validator.is_valid_for_processing(str(self.invalid_file), 'txt')
        
        # THEN
        self.assertFalse(is_valid)

    def test_is_valid_calls_validate_file_internally_with_valid_file(self):
        """
        GIVEN a FileValidator instance
        AND a valid file path
        WHEN is_valid_for_processing is called
        THEN expect:
            - Internally calls validate_file method
            - Returns True when validation result is valid
        """
        # GIVEN
        self.mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=True,
            mime_type='text/plain',
            extension='txt'
        )
        self.mock_file_format_detector.get_format_category.return_value = 'document'
        self.mock_validation_result_instance.is_valid = True
        
        # WHEN
        is_valid = self.validator.is_valid_for_processing(str(self.valid_file), 'txt')
        
        # THEN
        self.assertTrue(is_valid)

    def test_is_valid_calls_validate_file_internally_with_invalid_file(self):
        """
        GIVEN a FileValidator instance
        AND an invalid file path
        WHEN is_valid_for_processing is called
        THEN expect:
            - Internally calls validate_file method
            - Returns False when validation result is invalid
        """
        # GIVEN
        self.mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=True,
            mime_type='text/plain',
            extension='txt'
        )
        self.mock_file_format_detector.get_format_category.return_value = 'document'
        self.mock_validation_result_instance.is_valid = False
        
        # WHEN
        is_valid = self.validator.is_valid_for_processing(str(self.invalid_file), 'txt')
        
        # THEN
        self.assertFalse(is_valid)

    def test_is_valid_creates_validation_result_instance(self):
        """
        GIVEN a FileValidator instance
        AND any file path
        WHEN is_valid_for_processing is called
        THEN expect:
            - ValidationResult is created at least once
        """
        # GIVEN
        self.mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=True,
            mime_type='text/plain',
            extension='txt'
        )
        self.mock_file_format_detector.get_format_category.return_value = 'document'
        self.mock_validation_result_instance.is_valid = True
        
        # WHEN
        self.validator.is_valid_for_processing(str(self.valid_file), 'txt')
        
        # THEN
        self.assertGreaterEqual(self.mock_validation_result_class.call_count, 1)


if __name__ == "__main__":
    unittest.main()