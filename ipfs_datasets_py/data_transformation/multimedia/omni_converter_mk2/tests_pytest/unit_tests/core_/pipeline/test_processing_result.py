"""
Tests for ProcessingResult dataclass (pytest version).

This module contains tests for the ProcessingResult class, covering
initialization, data integrity, and dataclass behavior.

Converted from unittest to pytest format.
"""
import pytest
from datetime import datetime
import time
import os
import shutil
import tempfile

# Skip tests if the module can't be imported
try:
    from core._processing_result import ProcessingResult
except ImportError:
    pytest.skip("core._processing_result module not available", allow_module_level=True)


@pytest.fixture
def temp_dir():
    """Create a temporary directory for test files."""
    temp_dir = tempfile.mkdtemp()
    yield temp_dir
    shutil.rmtree(temp_dir, ignore_errors=True)


@pytest.fixture
def test_file_path(temp_dir):
    """Create a test file with some content."""
    test_file_path = os.path.join(temp_dir, "test_file.txt")
    with open(test_file_path, 'w') as f:
        f.write("Test content")
    return test_file_path


@pytest.fixture
def large_file_path(temp_dir):
    """Create a large test file."""
    large_file_path = os.path.join(temp_dir, "large_file.txt")
    with open(large_file_path, 'w') as f:
        f.write("A" * (15 * 1024 * 1024))  # 15 MB file (exceeds text limit)
    return large_file_path


@pytest.fixture
def executable_file_path(temp_dir):
    """Create an executable script file."""
    executable_file_path = os.path.join(temp_dir, "test_script.sh")
    with open(executable_file_path, 'w') as f:
        f.write("#!/bin/sh\necho 'Hello, world!'")
    return executable_file_path


@pytest.mark.unit
class TestProcessingResultInitialization:
    """Test ProcessingResult dataclass initialization and default values."""

    def test_init_with_only_required_attributes(self):
        """
        Test ProcessingResult initialization with only required parameters.
        
        Expected behavior:
        - success and file_path are set correctly
        - output_path defaults to empty string
        - format defaults to empty string
        - errors defaults to empty list
        - metadata defaults to empty dict
        - content_hash defaults to empty string
        - timestamp is set to current time (datetime.now)
        """
        # Act
        result = ProcessingResult(success=True, file_path="/path/to/file.txt")
        
        # Assert required attributes are set correctly
        assert result.success is True
        assert result.file_path == "/path/to/file.txt"
        
        # Assert default values
        assert result.output_path == ""
        assert result.format == ""
        assert result.errors == []
        assert result.metadata == {}
        assert result.content_hash == ""
        
        # Assert timestamp is close to current time
        now = datetime.now()
        time_diff = abs((result.timestamp - now).total_seconds())
        assert time_diff < 1.0  # Within 1 second
        assert isinstance(result.timestamp, datetime)

    def test_init_with_all_attributes(self):
        """
        Test ProcessingResult initialization with all parameters.
        
        Expected behavior:
        - All attributes are set to provided values
        - No defaults are used
        - timestamp is the provided datetime, not datetime.now
        """
        # Arrange
        test_timestamp = datetime(2023, 1, 1, 12, 0, 0)
        test_errors = ["Error 1", "Error 2"]
        test_metadata = {"key1": "value1", "key2": "value2"}
        
        # Act
        result = ProcessingResult(
            success=False,
            file_path="/input/file.txt",
            output_path="/output/file.txt",
            format="pdf",
            errors=test_errors,
            metadata=test_metadata,
            content_hash="abc123",
            timestamp=test_timestamp
        )
        
        # Assert all attributes are set to provided values
        assert result.success is False
        assert result.file_path == "/input/file.txt"
        assert result.output_path == "/output/file.txt"
        assert result.format == "pdf"
        assert result.errors == test_errors
        assert result.metadata == test_metadata
        assert result.content_hash == "abc123"
        assert result.timestamp == test_timestamp

    def test_default_factory_for_mutable_fields(self):
        """
        Test that mutable fields use default factories to avoid shared state.
        
        Expected behavior:
        - Other instance's fields remain unchanged
        - Each instance has its own list/dict objects
        - No shared mutable state between instances
        """
        # Act
        result1 = ProcessingResult(success=True, file_path="/file1.txt")
        result2 = ProcessingResult(success=True, file_path="/file2.txt")
        
        # Modify mutable fields on first instance
        result1.errors.append("Error in result1")
        result1.metadata["key"] = "value1"
        
        # Assert second instance remains unchanged
        assert result2.errors == []
        assert result2.metadata == {}
        
        # Assert instances have different list/dict objects
        assert result1.errors is not result2.errors
        assert result1.metadata is not result2.metadata

    def test_timestamp_default_uses_current_time(self):
        """
        Test that timestamp defaults use current time and are unique.
        
        Expected behavior:
        - Each has a different timestamp
        - Timestamps are close to creation time
        - Timestamps are datetime objects
        """
        # Act
        result1 = ProcessingResult(success=True, file_path="/file1.txt")
        time1 = datetime.now()
        
        # Wait a small amount of time
        time.sleep(0.01)
        
        result2 = ProcessingResult(success=True, file_path="/file2.txt")
        time2 = datetime.now()
        
        # Assert timestamps are different
        assert result1.timestamp != result2.timestamp
        
        # Assert timestamps are close to creation times
        time_diff1 = abs((result1.timestamp - time1).total_seconds())
        time_diff2 = abs((result2.timestamp - time2).total_seconds())
        assert time_diff1 < 1.0  # Within 1 second
        assert time_diff2 < 1.0  # Within 1 second
        
        # Assert both are datetime objects
        assert isinstance(result1.timestamp, datetime)
        assert isinstance(result2.timestamp, datetime)


@pytest.mark.unit
class TestProcessingResultBehavior:
    """Test ProcessingResult behavior and methods."""

    def test_equality_comparison(self):
        """
        Test equality comparison between ProcessingResult instances.
        
        Expected behavior:
        - Instances with same values are equal
        - Instances with different values are not equal
        - Equality considers all fields
        """
        # Arrange
        timestamp = datetime(2023, 1, 1, 12, 0, 0)
        
        result1 = ProcessingResult(
            success=True,
            file_path="/test/file.txt",
            output_path="/output/file.txt",
            format="pdf",
            errors=["error1"],
            metadata={"key": "value"},
            content_hash="hash123",
            timestamp=timestamp
        )
        
        result2 = ProcessingResult(
            success=True,
            file_path="/test/file.txt",
            output_path="/output/file.txt",
            format="pdf",
            errors=["error1"],
            metadata={"key": "value"},
            content_hash="hash123",
            timestamp=timestamp
        )
        
        result3 = ProcessingResult(
            success=False,  # Different success value
            file_path="/test/file.txt",
            output_path="/output/file.txt",
            format="pdf",
            errors=["error1"],
            metadata={"key": "value"},
            content_hash="hash123",
            timestamp=timestamp
        )
        
        # Assert
        assert result1 == result2  # Same values
        assert result1 != result3  # Different success value

    def test_string_representation(self):
        """
        Test string representation of ProcessingResult.
        
        Expected behavior:
        - __str__ returns readable representation
        - __repr__ returns detailed representation
        - Contains key information
        """
        # Arrange
        result = ProcessingResult(
            success=True,
            file_path="/test/file.txt",
            output_path="/output/file.txt",
            format="pdf"
        )
        
        # Act
        str_repr = str(result)
        repr_str = repr(result)
        
        # Assert
        # The actual string representation format from the class
        assert "Processing /test/file.txt" in str_repr
        assert "SUCCESS" in str_repr
        assert "/test/file.txt" in str_repr
        assert "/output/file.txt" in str_repr
        assert "pdf" in str_repr

    def test_to_dict_conversion(self):
        """
        Test conversion of ProcessingResult to dictionary.
        
        Expected behavior:
        - Returns dict with all attributes
        - Dict is independent of original object
        - Contains all expected keys
        """
        # Arrange
        test_timestamp = datetime(2023, 1, 1, 12, 0, 0)
        result = ProcessingResult(
            success=True,
            file_path="/test/file.txt",
            output_path="/output/file.txt",
            format="pdf",
            errors=["error1"],
            metadata={"key": "value"},
            content_hash="hash123",
            timestamp=test_timestamp
        )
        
        # Act
        result_dict = result.to_dict()
        
        # Assert
        expected_keys = {
            "success", "file_path", "output_path", "format",
            "errors", "metadata", "content_hash", "timestamp"
        }
        assert set(result_dict.keys()) == expected_keys
        
        assert result_dict["success"] is True
        assert result_dict["file_path"] == "/test/file.txt"
        assert result_dict["output_path"] == "/output/file.txt"
        assert result_dict["format"] == "pdf"
        assert result_dict["errors"] == ["error1"]
        assert result_dict["metadata"] == {"key": "value"}
        assert result_dict["content_hash"] == "hash123"
        # The timestamp is converted to ISO string format in to_dict()
        assert result_dict["timestamp"] == test_timestamp.isoformat()


@pytest.mark.unit
class TestProcessingResultEdgeCases:
    """Test ProcessingResult edge cases and error conditions."""

    def test_empty_string_values(self):
        """
        Test ProcessingResult with empty string values.
        
        Expected behavior:
        - Accepts empty strings for string fields
        - Empty strings are preserved
        - No validation errors occur
        """
        # Act
        result = ProcessingResult(
            success=True,
            file_path="",  # Empty file path
            output_path="",
            format="",
            content_hash=""
        )
        
        # Assert
        assert result.file_path == ""
        assert result.output_path == ""
        assert result.format == ""
        assert result.content_hash == ""

    def test_none_values_for_optional_fields(self):
        """
        Test ProcessingResult with None values for optional fields.
        
        Expected behavior:
        - None values are accepted where appropriate
        - Default factories still work for mutable types
        """
        # Act
        result = ProcessingResult(
            success=True,
            file_path="/test/file.txt",
            output_path=None,
            format=None,
            content_hash=None
        )
        
        # Assert
        assert result.output_path is None
        assert result.format is None
        assert result.content_hash is None
        assert result.errors == []  # Still gets default factory
        assert result.metadata == {}  # Still gets default factory

    def test_large_data_values(self):
        """
        Test ProcessingResult with large data values.
        
        Expected behavior:
        - Handles large strings and data structures
        - No performance issues with reasonable sizes
        - Memory efficiency maintained
        """
        # Arrange
        large_errors = [f"Error {i}" for i in range(1000)]
        large_metadata = {f"key_{i}": f"value_{i}" for i in range(1000)}
        large_hash = "a" * 1000
        
        # Act
        result = ProcessingResult(
            success=False,
            file_path="/test/large_file.txt",
            errors=large_errors,
            metadata=large_metadata,
            content_hash=large_hash
        )
        
        # Assert
        assert len(result.errors) == 1000
        assert len(result.metadata) == 1000
        assert len(result.content_hash) == 1000
        assert result.errors[999] == "Error 999"
        assert result.metadata["key_999"] == "value_999"

    def test_immutability_after_creation(self):
        """
        Test that ProcessingResult instances can be modified after creation.
        
        Note: This tests the current behavior - ProcessingResult is NOT frozen.
        If it becomes frozen in the future, this test should be updated.
        """
        # Arrange
        result = ProcessingResult(success=True, file_path="/test/file.txt")
        original_success = result.success
        
        # Act - Try to modify the instance
        result.success = False  # This should work since it's not frozen
        result.errors.append("New error")
        result.metadata["new_key"] = "new_value"
        
        # Assert - Changes should be allowed (not frozen)
        assert result.success != original_success
        assert result.success is False
        assert "New error" in result.errors
        assert result.metadata["new_key"] == "new_value"


@pytest.mark.unit
class TestProcessingResultFileOperations:
    """Test ProcessingResult with real file operations."""

    def test_with_real_file_paths(self, test_file_path):
        """
        Test ProcessingResult with actual file paths.
        
        Expected behavior:
        - Accepts real file paths
        - File existence is not validated by the dataclass
        - Paths are stored as-is
        """
        # Act
        result = ProcessingResult(
            success=True,
            file_path=test_file_path,
            output_path=test_file_path + ".processed"
        )
        
        # Assert
        assert result.file_path == test_file_path
        assert result.output_path == test_file_path + ".processed"
        assert result.success is True

    def test_with_nonexistent_file_paths(self):
        """
        Test ProcessingResult with non-existent file paths.
        
        Expected behavior:
        - Accepts non-existent file paths
        - No validation of file existence
        - Paths stored as provided
        """
        # Act
        result = ProcessingResult(
            success=False,
            file_path="/nonexistent/file.txt",
            output_path="/nonexistent/output.txt"
        )
        
        # Assert
        assert result.file_path == "/nonexistent/file.txt"
        assert result.output_path == "/nonexistent/output.txt"
        assert result.success is False

    def test_error_handling_scenario(self):
        """
        Test ProcessingResult in error handling scenario.
        
        Expected behavior:
        - success=False with error details
        - Errors list contains meaningful messages
        - Metadata can contain debug information
        """
        # Act
        result = ProcessingResult(
            success=False,
            file_path="/problematic/file.txt",
            errors=[
                "File not found: /problematic/file.txt",
                "Permission denied: Cannot read file",
                "Processing timeout after 30 seconds"
            ],
            metadata={
                "attempt_count": 3,
                "last_error_time": "2023-01-01T12:00:00",
                "error_code": "FILE_NOT_ACCESSIBLE"
            }
        )
        
        # Assert
        assert result.success is False
        assert len(result.errors) == 3
        assert "File not found" in result.errors[0]
        assert "Permission denied" in result.errors[1]
        assert "timeout" in result.errors[2]
        assert result.metadata["attempt_count"] == 3
        assert result.metadata["error_code"] == "FILE_NOT_ACCESSIBLE"