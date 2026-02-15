"""
Test suite for core/file_validator/_file_validator.py converted from unittest to pytest.
"""
import pytest
import tempfile
import logging
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

# Import the class under test
from configs import Configs
from core.file_validator._file_validator import FileValidator
from core.file_validator._validation_result import ValidationResult
from file_format_detector._file_format_detector import FileFormatDetector


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
    mock_configs.security = Mock()
    mock_configs.security.max_file_size_mb = 100
    mock_configs.security.allowed_formats = ['pdf', 'txt', 'docx']
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


@pytest.fixture
def mock_resources():
    """Create a dictionary of mock resources for FileValidator."""
    return {
        "file_format_detector": Mock(spec=FileFormatDetector),
        "logger": Mock(spec=logging.Logger),
        "validation_result": make_mock_validation_result(),
        "file_exists": make_mock_file_exists(),
        "get_file_info": make_mock_get_file_info()
    }


@pytest.fixture
def mock_configs():
    """Create mock configs for testing."""
    return make_mock_configs()


@pytest.fixture
def temp_dir():
    """Create temporary directory for test files."""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield Path(temp_dir)


@pytest.mark.unit
class TestFileValidatorInitialization:
    """Test FileValidator initialization and configuration."""

    def test_init_with_valid_resources_and_configs(self, mock_resources, mock_configs):
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
        validator = FileValidator(resources=mock_resources, configs=mock_configs)
        # THEN
        assert isinstance(validator, FileValidator)

    def test_init_configs_stored_correctly(self, mock_resources, mock_configs):
        """
        GIVEN valid resources dict and valid configs object
        WHEN FileValidator is initialized
        THEN expect:
            - validator.configs equals the provided configs object
        """
        # WHEN
        validator = FileValidator(resources=mock_resources, configs=mock_configs)
        # THEN
        assert validator.configs == mock_configs

    def test_init_max_file_size_set_correctly(self, mock_resources, mock_configs):
        """
        GIVEN valid resources dict and configs with validation.max_file_size_mb = 100
        WHEN FileValidator is initialized
        THEN expect:
            - validator.max_file_size_mb equals 100
        """
        # WHEN
        validator = FileValidator(resources=mock_resources, configs=mock_configs)
        # THEN
        assert validator.max_file_size_mb == mock_configs.security.max_file_size_mb

    def test_init_allowed_formats_set_correctly(self, mock_resources, mock_configs):
        """
        GIVEN valid resources dict and configs with validation.supported_formats = ['pdf', 'txt', 'docx']
        WHEN FileValidator is initialized
        THEN expect:
            - validator.allowed_formats equals ['pdf', 'txt', 'docx']
        """
        # WHEN
        validator = FileValidator(resources=mock_resources, configs=mock_configs)
        # THEN
        assert validator.allowed_formats == mock_configs.security.allowed_formats

    def test_init_logger_component_set_correctly(self, mock_resources, mock_configs):
        """
        GIVEN valid resources dict containing logger component
        WHEN FileValidator is initialized
        THEN expect:
            - validator._logger equals the provided logger
        """
        # WHEN
        validator = FileValidator(resources=mock_resources, configs=mock_configs)
        # THEN
        assert validator._logger == mock_resources["logger"]

    def test_init_format_detector_component_set_correctly(self, mock_resources, mock_configs):
        """
        GIVEN valid resources dict containing file_detector component
        WHEN FileValidator is initialized
        THEN expect:
            - validator._format_detector equals the provided file_detector
        """
        # WHEN
        validator = FileValidator(resources=mock_resources, configs=mock_configs)
        # THEN
        assert validator._format_detector == mock_resources["file_format_detector"]

    def test_init_validation_result_component_set_correctly(self, mock_resources, mock_configs):
        """
        GIVEN valid resources dict containing validation_result component
        WHEN FileValidator is initialized
        THEN expect:
            - validator._validation_result equals the provided validation_result
        """
        # WHEN
        validator = FileValidator(resources=mock_resources, configs=mock_configs)
        # THEN
        assert validator._validation_result == mock_resources["validation_result"]

    def test_init_file_exists_function_set_correctly(self, mock_resources, mock_configs):
        """
        GIVEN valid resources dict containing file_exists function
        WHEN FileValidator is initialized
        THEN expect:
            - validator._file_exists equals the provided file_exists function
        """
        # WHEN
        validator = FileValidator(resources=mock_resources, configs=mock_configs)
        # THEN
        assert validator._file_exists == mock_resources["file_exists"]

    def test_init_get_file_info_function_set_correctly(self, mock_resources, mock_configs):
        """
        GIVEN valid resources dict containing get_file_info function
        WHEN FileValidator is initialized
        THEN expect:
            - validator._get_file_info equals the provided get_file_info function
        """
        # WHEN
        validator = FileValidator(resources=mock_resources, configs=mock_configs)
        # THEN
        assert validator._get_file_info == mock_resources["get_file_info"]

    def test_init_resources_are_the_same_as_validators_resources(self, mock_resources, mock_configs):
        """
        GIVEN valid resources dict
        WHEN FileValidator is initialized with those resources
        THEN expect:
            - validator.resources equals the provided resources dict
        """
        # WHEN
        validator = FileValidator(resources=mock_resources, configs=mock_configs)
        # THEN
        assert validator.resources == mock_resources

    def test_init_with_none_resources(self, mock_configs):
        """
        GIVEN resources parameter is None
        WHEN FileValidator is initialized
        THEN expect:
            - Raises TypeError
        """
        # GIVEN
        resources = None

        # WHEN/THEN
        with pytest.raises(TypeError):
            FileValidator(resources=resources, configs=mock_configs)

    def test_init_with_none_configs(self, mock_resources):
        """
        GIVEN configs parameter is None
        WHEN FileValidator is initialized
        THEN expect:
            - Raises AttributeError
        """
        # GIVEN
        configs = None

        # WHEN/THEN
        with pytest.raises(AttributeError):
            FileValidator(resources=mock_resources, configs=configs)

    def test_init_with_empty_resources_dict(self, mock_configs):
        """
        GIVEN empty resources dict {}
        WHEN FileValidator is initialized
        THEN expect:
            - raises KeyError
        """
        # GIVEN
        empty_resources = {}
        
        # WHEN/THEN
        with pytest.raises(KeyError):
            FileValidator(resources=empty_resources, configs=mock_configs)

    def test_init_with_configs_missing_attributes(self, mock_resources):
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
        with pytest.raises(AttributeError):
            FileValidator(resources=mock_resources, configs=configs_missing_attributes)


@pytest.mark.unit
class TestGetValidationErrors:
    """Test FileValidator.get_validation_errors method."""

    @pytest.fixture
    def test_files(self, temp_dir):
        """Create test files in temporary directory."""
        valid_file = temp_dir / "valid_file.txt"
        valid_file.write_text("This is a valid test file.")
        
        large_file = temp_dir / "large_file.txt"
        large_file.write_text("A" * 1024 * 1024)  # 1MB file
        
        empty_file = temp_dir / "empty_file.txt"
        empty_file.touch()
        
        return {
            'valid_file': valid_file,
            'large_file': large_file,
            'empty_file': empty_file
        }

    @pytest.fixture
    def validator(self, mock_resources, mock_configs):
        """Create FileValidator instance for testing."""
        return FileValidator(resources=mock_resources, configs=mock_configs)

    def test_get_errors_valid_file_with_format_returns_empty_list(self, validator, test_files, mock_resources):
        """
        GIVEN a FileValidator instance
        AND a valid file path to an existing, readable file
        AND format_name is provided (e.g., 'pdf')
        WHEN get_validation_errors is called
        THEN expect:
            - Returns empty list (no errors)
        """
        # GIVEN
        mock_resources["get_file_info"].return_value = Mock(
            size=1024,  # Small file within limits
            is_readable=True
        )
        mock_resources["file_format_detector"].get_format_category.return_value = 'document'
        
        # Set up the validation result to indicate success
        mock_validation_result_instance = mock_resources["validation_result"].return_value
        mock_validation_result_instance.is_valid = True
        mock_validation_result_instance.errors = []
        
        # WHEN
        errors = validator.get_validation_errors(str(test_files['valid_file']), 'txt')
        
        # THEN
        assert errors == []

    def test_get_errors_nonexistent_file(self, validator, test_files, mock_resources):
        """
        GIVEN a FileValidator instance
        AND a file path to a non-existent file
        AND format_name is provided or None
        WHEN get_validation_errors is called
        THEN expect:
            - Returns list containing file not found error
        """
        # GIVEN
        nonexistent_file = test_files['valid_file'].parent / "does_not_exist.txt"
        mock_resources["file_exists"].return_value = False
        
        # Set up validation result to have an error
        mock_validation_result_instance = mock_resources["validation_result"].return_value
        mock_validation_result_instance.errors = ["File does not exist: " + str(nonexistent_file)]
        
        # WHEN
        errors = validator.get_validation_errors(str(nonexistent_file), 'txt')
        
        # THEN
        assert len(errors) > 0
        assert any("does not exist" in error.lower() for error in errors)

    def test_get_errors_file_too_large(self, validator, test_files, mock_resources):
        """
        GIVEN a FileValidator instance with max_file_size_mb configured
        AND a file path to a file exceeding the size limit
        AND format_name is provided or None
        WHEN get_validation_errors is called
        THEN expect:
            - Returns list containing file size error
        """
        # GIVEN
        mock_resources["get_file_info"].return_value = Mock(
            size=1024 * 1024,  # 1MB file, exceeds 0.5MB limit
            is_readable=True
        )
        
        # Set up validation result to have size error
        mock_validation_result_instance = mock_resources["validation_result"].return_value
        mock_validation_result_instance.errors = ["File size exceeds maximum allowed"]
        
        # WHEN
        errors = validator.get_validation_errors(str(test_files['large_file']), 'txt')
        
        # THEN
        assert len(errors) > 0
        assert any("size" in error.lower() or "exceeds" in error.lower() for error in errors)

    def test_get_errors_unsupported_format_returns_error_list(self, validator, test_files, mock_resources):
        """
        GIVEN a FileValidator instance with supported_formats configured
        AND a file path to a file with unsupported format
        AND format_name is provided as unsupported format
        WHEN get_validation_errors is called
        THEN expect:
            - Returns list containing at least one error
        """
        # GIVEN
        mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=True
        )
        mock_resources["file_format_detector"].get_format_category.return_value = None  # Unsupported format
        
        # Set up validation result to have format error
        mock_validation_result_instance = mock_resources["validation_result"].return_value
        mock_validation_result_instance.errors = ["Format 'xyz' is not supported"]
        
        # WHEN
        errors = validator.get_validation_errors(str(test_files['valid_file']), 'xyz')  # Unsupported format
        
        # THEN
        assert len(errors) > 0

    def test_get_errors_unsupported_format_contains_format_error(self, validator, test_files, mock_resources):
        """
        GIVEN a FileValidator instance with supported_formats configured
        AND a file path to a file with unsupported format
        AND format_name is provided as unsupported format
        WHEN get_validation_errors is called
        THEN expect:
            - Returns list containing unsupported format error message
        """
        # GIVEN
        mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=True
        )
        mock_resources["file_format_detector"].get_format_category.return_value = None  # Unsupported format
        
        # Set up validation result to have format error
        mock_validation_result_instance = mock_resources["validation_result"].return_value
        mock_validation_result_instance.errors = ["Format 'xyz' is not supported"]
        
        # WHEN
        errors = validator.get_validation_errors(str(test_files['valid_file']), 'xyz')  # Unsupported format
        
        # THEN
        assert any("not supported" in error.lower() or "format" in error.lower() for error in errors)

    def test_get_errors_no_read_permission_returns_error_list(self, validator, test_files, mock_resources):
        """
        GIVEN a FileValidator instance
        AND a file path to a file without read permissions
        AND format_name is provided or None
        WHEN get_validation_errors is called
        THEN expect:
            - Returns list containing at least one error
        """
        # GIVEN
        mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=False  # No read permission
        )
        
        # Set up validation result to have permission error
        mock_validation_result_instance = mock_resources["validation_result"].return_value
        mock_validation_result_instance.errors = ["File is not readable"]
        
        # WHEN
        errors = validator.get_validation_errors(str(test_files['valid_file']), 'txt')
        
        # THEN
        assert len(errors) > 0

    def test_get_errors_no_read_permission_contains_permission_error(self, validator, test_files, mock_resources):
        """
        GIVEN a FileValidator instance
        AND a file path to a file without read permissions
        AND format_name is provided or None
        WHEN get_validation_errors is called
        THEN expect:
            - Returns list containing permission error message
        """
        # GIVEN
        mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=False  # No read permission
        )
        
        # Set up validation result to have permission error
        mock_validation_result_instance = mock_resources["validation_result"].return_value
        mock_validation_result_instance.errors = ["File is not readable"]
        
        # WHEN
        errors = validator.get_validation_errors(str(test_files['valid_file']), 'txt')
        
        # THEN
        assert any("not readable" in error.lower() or "permission" in error.lower() for error in errors)

    def test_get_errors_empty_file_returns_error_list(self, validator, test_files, mock_resources):
        """
        GIVEN a FileValidator instance
        AND a file path to an empty file (0 bytes)
        AND format_name is provided or None
        WHEN get_validation_errors is called
        THEN expect:
            - Returns list containing at least one error
        """
        # GIVEN
        mock_resources["get_file_info"].return_value = Mock(
            size=0,  # Empty file
            is_readable=True
        )
        
        # Set up validation result to have empty file error
        mock_validation_result_instance = mock_resources["validation_result"].return_value
        mock_validation_result_instance.errors = ["File is empty"]
        
        # WHEN
        errors = validator.get_validation_errors(str(test_files['empty_file']), 'txt')
        
        # THEN
        assert len(errors) > 0

    def test_get_errors_empty_file_contains_empty_error(self, validator, test_files, mock_resources):
        """
        GIVEN a FileValidator instance
        AND a file path to an empty file (0 bytes)
        AND format_name is provided or None
        WHEN get_validation_errors is called
        THEN expect:
            - Returns list containing empty file error message
        """
        # GIVEN
        mock_resources["get_file_info"].return_value = Mock(
            size=0,  # Empty file
            is_readable=True
        )
        
        # Set up validation result to have empty file error
        mock_validation_result_instance = mock_resources["validation_result"].return_value
        mock_validation_result_instance.errors = ["File is empty"]
        
        # WHEN
        errors = validator.get_validation_errors(str(test_files['empty_file']), 'txt')
        
        # THEN
        assert any("empty" in error.lower() for error in errors)


@pytest.mark.unit
class TestIsValidForProcessing:
    """Test FileValidator.is_valid_for_processing method."""

    @pytest.fixture
    def test_files(self, temp_dir):
        """Create test files for validation testing."""
        valid_file = temp_dir / "valid_file.txt"
        valid_file.write_text("This is a valid test file.")
        
        invalid_file = temp_dir / "invalid_file.txt"
        invalid_file.write_text("This file will be treated as invalid.")
        
        return {
            'valid_file': valid_file,
            'invalid_file': invalid_file
        }

    @pytest.fixture
    def validator(self, mock_resources, mock_configs):
        """Create FileValidator instance for testing."""
        return FileValidator(resources=mock_resources, configs=mock_configs)

    def test_is_valid_for_processing_calls_validate_file(self, validator, test_files, mock_resources):
        """
        GIVEN a FileValidator instance
        AND a valid file path to an existing, readable file
        WHEN is_valid_for_processing is called
        THEN expect:
            - validate_file is called once
        """
        # GIVEN
        mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=True,
            mime_type='text/plain',
            extension='txt'
        )
        
        # WHEN
        validator.is_valid_for_processing(str(test_files['valid_file']), 'txt')

        # Verify validate_file was called with no parameters
        mock_resources["validation_result"].assert_called_once()

    def test_is_valid_with_valid_file_and_format(self, validator, test_files, mock_resources):
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
        mock_resources["file_format_detector"].get_format_category.return_value = 'document'
        
        # Set up validation result to indicate success
        mock_validation_result_instance = mock_resources["validation_result"].return_value
        mock_validation_result_instance.is_valid = True
        
        # WHEN
        is_valid = validator.is_valid_for_processing(str(test_files['valid_file']), 'txt')
        
        # THEN
        assert is_valid is True

    def test_is_valid_with_valid_file_auto_detect_format(self, validator, test_files, mock_resources):
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
        mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=True,
            mime_type='text/plain',
            extension='txt'
        )
        mock_resources["file_format_detector"].detect_format.return_value = ('txt', 'document')
        
        # Set up validation result to indicate success
        mock_validation_result_instance = mock_resources["validation_result"].return_value
        mock_validation_result_instance.is_valid = True
        
        # WHEN
        is_valid = validator.is_valid_for_processing(str(test_files['valid_file']), None)
        
        # THEN
        assert is_valid is True

    def test_is_valid_with_nonexistent_file(self, validator, test_files, mock_resources):
        """
        GIVEN a FileValidator instance
        AND a file path to a non-existent file
        WHEN is_valid_for_processing is called
        THEN expect:
            - Returns False
        """
        # GIVEN
        nonexistent_file = test_files['valid_file'].parent / "does_not_exist.txt"
        mock_resources["file_exists"].return_value = False
        
        # Set up validation result to indicate failure
        mock_validation_result_instance = mock_resources["validation_result"].return_value
        mock_validation_result_instance.is_valid = False
        
        # WHEN
        is_valid = validator.is_valid_for_processing(str(nonexistent_file), 'txt')
        
        # THEN
        assert is_valid is False

    def test_is_valid_with_oversized_file(self, validator, test_files, mock_resources):
        """
        GIVEN a FileValidator instance with max_file_size_mb configured
        AND a file path to a file exceeding the size limit
        WHEN is_valid_for_processing is called
        THEN expect:
            - Returns False
        """
        # GIVEN
        mock_resources["get_file_info"].return_value = Mock(
            size=1024 * 1024 * 20,  # 20MB, exceeds 10MB limit
            is_readable=True
        )
        
        # Set up validation result to indicate failure
        mock_validation_result_instance = mock_resources["validation_result"].return_value
        mock_validation_result_instance.is_valid = False
        
        # WHEN
        is_valid = validator.is_valid_for_processing(str(test_files['valid_file']), 'txt')
        
        # THEN
        assert is_valid is False

    def test_init_resources_are_the_same_as_validators_resources(self, mock_resources, mock_configs):
        """
        GIVEN valid resources dict
        WHEN FileValidator is initialized with those resources
        THEN expect:
            - validator.resources equals the provided resources dict
        """
        # WHEN
        validator = FileValidator(resources=mock_resources, configs=mock_configs)
        # THEN
        assert validator.resources == mock_resources

    def test_init_with_none_resources(self, mock_configs):
        """
        GIVEN resources parameter is None
        WHEN FileValidator is initialized
        THEN expect:
            - Raises TypeError
        """
        # GIVEN
        resources = None

        # WHEN/THEN
        with pytest.raises(TypeError):
            FileValidator(resources=resources, configs=mock_configs)

    def test_init_with_none_configs(self, mock_resources):
        """
        GIVEN configs parameter is None
        WHEN FileValidator is initialized
        THEN expect:
            - Raises AttributeError
        """
        # GIVEN
        configs = None

        # WHEN/THEN
        with pytest.raises(AttributeError):
            FileValidator(resources=mock_resources, configs=configs)

    def test_init_with_empty_resources_dict(self, mock_configs):
        """
        GIVEN empty resources dict {}
        WHEN FileValidator is initialized
        THEN expect:
            - raises KeyError
        """
        # GIVEN
        empty_resources = {}
        
        # WHEN/THEN
        with pytest.raises(KeyError):
            FileValidator(resources=empty_resources, configs=mock_configs)

    def test_init_with_configs_missing_attributes(self, mock_resources):
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
        with pytest.raises(AttributeError):
            FileValidator(resources=mock_resources, configs=configs_missing_attributes)


@pytest.mark.unit
class TestGetValidationErrors:
    """Test FileValidator.get_validation_errors method."""

    @pytest.fixture
    def test_files(self, temp_dir):
        """Create test files in temporary directory."""
        valid_file = temp_dir / "valid_file.txt"
        valid_file.write_text("This is a valid test file.")
        
        large_file = temp_dir / "large_file.txt"
        large_file.write_text("A" * 1024 * 1024)  # 1MB file
        
        empty_file = temp_dir / "empty_file.txt"
        empty_file.touch()
        
        return {
            'valid_file': valid_file,
            'large_file': large_file,
            'empty_file': empty_file
        }

    @pytest.fixture
    def validator(self, mock_resources, mock_configs):
        """Create FileValidator instance for testing."""
        return FileValidator(resources=mock_resources, configs=mock_configs)

    def test_get_errors_valid_file_with_format_returns_empty_list(self, validator, test_files, mock_resources):
        """
        GIVEN a FileValidator instance
        AND a valid file path to an existing, readable file
        AND format_name is provided (e.g., 'pdf')
        WHEN get_validation_errors is called
        THEN expect:
            - Returns empty list (no errors)
        """
        # GIVEN
        mock_resources["get_file_info"].return_value = Mock(
            size=1024,  # Small file within limits
            is_readable=True
        )
        mock_resources["file_format_detector"].get_format_category.return_value = 'document'
        
        # Set up the validation result to indicate success
        mock_validation_result_instance = mock_resources["validation_result"].return_value
        mock_validation_result_instance.is_valid = True
        mock_validation_result_instance.errors = []
        
        # WHEN
        errors = validator.get_validation_errors(str(test_files['valid_file']), 'txt')
        
        # THEN
        assert errors == []

    def test_get_errors_nonexistent_file(self, validator, test_files, mock_resources):
        """
        GIVEN a FileValidator instance
        AND a file path to a non-existent file
        AND format_name is provided or None
        WHEN get_validation_errors is called
        THEN expect:
            - Returns list containing file not found error
        """
        # GIVEN
        nonexistent_file = test_files['valid_file'].parent / "does_not_exist.txt"
        mock_resources["file_exists"].return_value = False
        
        # Set up validation result to have an error
        mock_validation_result_instance = mock_resources["validation_result"].return_value
        mock_validation_result_instance.errors = ["File does not exist: " + str(nonexistent_file)]
        
        # WHEN
        errors = validator.get_validation_errors(str(nonexistent_file), 'txt')
        
        # THEN
        assert len(errors) > 0
        assert any("does not exist" in error.lower() for error in errors)

    def test_get_errors_file_too_large(self, validator, test_files, mock_resources):
        """
        GIVEN a FileValidator instance with max_file_size_mb configured
        AND a file path to a file exceeding the size limit
        AND format_name is provided or None
        WHEN get_validation_errors is called
        THEN expect:
            - Returns list containing file size error
        """
        # GIVEN
        mock_resources["get_file_info"].return_value = Mock(
            size=1024 * 1024,  # 1MB file, exceeds 0.5MB limit
            is_readable=True
        )
        
        # Set up validation result to have size error
        mock_validation_result_instance = mock_resources["validation_result"].return_value
        mock_validation_result_instance.errors = ["File size exceeds maximum allowed"]
        
        # WHEN
        errors = validator.get_validation_errors(str(test_files['large_file']), 'txt')
        
        # THEN
        assert len(errors) > 0
        assert any("size" in error.lower() or "exceeds" in error.lower() for error in errors)

    def test_get_errors_unsupported_format_returns_error_list(self, validator, test_files, mock_resources):
        """
        GIVEN a FileValidator instance with supported_formats configured
        AND a file path to a file with unsupported format
        AND format_name is provided as unsupported format
        WHEN get_validation_errors is called
        THEN expect:
            - Returns list containing at least one error
        """
        # GIVEN
        mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=True
        )
        mock_resources["file_format_detector"].get_format_category.return_value = None  # Unsupported format
        
        # Set up validation result to have format error
        mock_validation_result_instance = mock_resources["validation_result"].return_value
        mock_validation_result_instance.errors = ["Format 'xyz' is not supported"]
        
        # WHEN
        errors = validator.get_validation_errors(str(test_files['valid_file']), 'xyz')  # Unsupported format
        
        # THEN
        assert len(errors) > 0

    def test_get_errors_unsupported_format_contains_format_error(self, validator, test_files, mock_resources):
        """
        GIVEN a FileValidator instance with supported_formats configured
        AND a file path to a file with unsupported format
        AND format_name is provided as unsupported format
        WHEN get_validation_errors is called
        THEN expect:
            - Returns list containing unsupported format error message
        """
        # GIVEN
        mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=True
        )
        mock_resources["file_format_detector"].get_format_category.return_value = None  # Unsupported format
        
        # Set up validation result to have format error
        mock_validation_result_instance = mock_resources["validation_result"].return_value
        mock_validation_result_instance.errors = ["Format 'xyz' is not supported"]
        
        # WHEN
        errors = validator.get_validation_errors(str(test_files['valid_file']), 'xyz')  # Unsupported format
        
        # THEN
        assert any("not supported" in error.lower() or "format" in error.lower() for error in errors)

    def test_get_errors_no_read_permission_returns_error_list(self, validator, test_files, mock_resources):
        """
        GIVEN a FileValidator instance
        AND a file path to a file without read permissions
        AND format_name is provided or None
        WHEN get_validation_errors is called
        THEN expect:
            - Returns list containing at least one error
        """
        # GIVEN
        mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=False  # No read permission
        )
        
        # Set up validation result to have permission error
        mock_validation_result_instance = mock_resources["validation_result"].return_value
        mock_validation_result_instance.errors = ["File is not readable"]
        
        # WHEN
        errors = validator.get_validation_errors(str(test_files['valid_file']), 'txt')
        
        # THEN
        assert len(errors) > 0

    def test_get_errors_no_read_permission_contains_permission_error(self, validator, test_files, mock_resources):
        """
        GIVEN a FileValidator instance
        AND a file path to a file without read permissions
        AND format_name is provided or None
        WHEN get_validation_errors is called
        THEN expect:
            - Returns list containing permission error message
        """
        # GIVEN
        mock_resources["get_file_info"].return_value = Mock(
            size=1024,
            is_readable=False  # No read permission
        )
        
        # Set up validation result to have permission error
        mock_validation_result_instance = mock_resources["validation_result"].return_value
        mock_validation_result_instance.errors = ["File is not readable"]
        
        # WHEN
        errors = validator.get_validation_errors(str(test_files['valid_file']), 'txt')
        
        # THEN
        assert any("not readable" in error.lower() or "permission" in error.lower() for error in errors)

    def test_get_errors_empty_file_returns_error_list(self, validator, test_files, mock_resources):
        """
        GIVEN a FileValidator instance
        AND a file path to an empty file (0 bytes)
        AND format_name is provided or None
        WHEN get_validation_errors is called
        THEN expect:
            - Returns list containing at least one error
        """
        # GIVEN
        mock_resources["get_file_info"].return_value = Mock(
            size=0,  # Empty file
            is_readable=True
        )
        
        # Set up validation result to have empty file error
        mock_validation_result_instance = mock_resources["validation_result"].return_value
        mock_validation_result_instance.errors = ["File is empty"]
        
        # WHEN
        errors = validator.get_validation_errors(str(test_files['empty_file']), 'txt')
        
        # THEN
        assert len(errors) > 0

    def test_get_errors_empty_file_contains_empty_error(self, validator, test_files, mock_resources):
        """
        GIVEN a FileValidator instance
        AND a file path to an empty file (0 bytes)
        AND format_name is provided or None
        WHEN get_validation_errors is called
        THEN expect:
            - Returns list containing empty file error message
        """
        # GIVEN
        mock_resources["get_file_info"].return_value = Mock(
            size=0,  # Empty file
            is_readable=True
        )
        
        # Set up validation result to have empty file error
        mock_validation_result_instance = mock_resources["validation_result"].return_value
        mock_validation_result_instance.errors = ["File is empty"]
        
        # WHEN
        errors = validator.get_validation_errors(str(test_files['empty_file']), 'txt')
        
        # THEN
        assert any("empty" in error.lower() for error in errors)


@pytest.mark.unit
class TestIsValidForProcessing:
    """Test FileValidator.is_valid_for_processing method."""

    @pytest.fixture
    def test_files(self, temp_dir):
        """Create test files for validation testing."""
        valid_file = temp_dir / "valid_file.txt"
        valid_file.write_text("This is a valid test file.")
        
        invalid_file = temp_dir / "invalid_file.txt"
        invalid_file.write_text("This file will be treated as invalid.")
        
        return {
            'valid_file': valid_file,
            'invalid_file': invalid_file
        }

    @pytest.fixture
    def validator(self, mock_resources, mock_configs):
        """Create FileValidator instance for testing."""
        return FileValidator(resources=mock_resources, configs=mock_configs)