"""
Simple working tests for pytest migration demonstration.

This module contains basic tests that work without external dependencies
to demonstrate pytest conversion patterns and verify the testing infrastructure.
"""
import pytest
import os
import tempfile
import json
from pathlib import Path


# Test Constants
HELLO_WORLD_TEXT = "Hello, World!"
HELLO_WORLD_UPPER = "HELLO, WORLD!"
HELLO_WORLD_LOWER = "hello, world!"
HELLO_WORLD_LENGTH = 13
WORLD_SUBSTRING = "World"
TEST_LIST = [1, 2, 3, 4, 5]
TEST_LIST_LENGTH = 5
TEST_LIST_SUM = 15
TEST_LIST_MAX = 5
TEST_LIST_MIN = 1
TEST_DICT_NAME = "test"
TEST_DICT_VALUE = 42
TEST_JSON_CONTENT = '{"key": "value", "number": 123}'
EXPECTED_JSON_DICT = {"key": "value", "number": 123}
TEMP_FILE_CONTENT = "Hello from file!"


@pytest.mark.unit
class TestStringOperations:
    """
    Tests for basic string operations functionality.
    Functions under test: str.upper, str.lower, len, str.__contains__
    """

    def test_when_string_upper_called_then_returns_uppercase(self):
        """
        GIVEN a string with mixed case
        WHEN upper method is called
        THEN expect string with all uppercase letters
        """
        result = HELLO_WORLD_TEXT.upper()
        
        assert result == HELLO_WORLD_UPPER, f"Expected {HELLO_WORLD_UPPER}, got {result}"

    def test_when_string_lower_called_then_returns_lowercase(self):
        """
        GIVEN a string with mixed case
        WHEN lower method is called
        THEN expect string with all lowercase letters
        """
        result = HELLO_WORLD_TEXT.lower()
        
        assert result == HELLO_WORLD_LOWER, f"Expected {HELLO_WORLD_LOWER}, got {result}"

    def test_when_string_length_checked_then_returns_character_count(self):
        """
        GIVEN a string with known content
        WHEN len function is called on string
        THEN expect length equals character count
        """
        result = len(HELLO_WORLD_TEXT)
        
        assert result == HELLO_WORLD_LENGTH, f"Expected {HELLO_WORLD_LENGTH}, got {result}"

    def test_when_substring_searched_then_returns_true_if_found(self):
        """
        GIVEN a string with known content
        WHEN substring operator is used with existing substring
        THEN expect True is returned
        """
        result = WORLD_SUBSTRING in HELLO_WORLD_TEXT
        
        assert result is True, f"Expected True for '{WORLD_SUBSTRING}' in '{HELLO_WORLD_TEXT}', got {result}"


@pytest.mark.unit
class TestListOperations:
    """
    Tests for basic list operations functionality.
    Functions under test: len, sum, max, min
    """

    def test_when_list_length_checked_then_returns_element_count(self):
        """
        GIVEN a list with known elements
        WHEN len function is called on list
        THEN expect length equals element count
        """
        result = len(TEST_LIST)
        
        assert result == TEST_LIST_LENGTH, f"Expected {TEST_LIST_LENGTH}, got {result}"

    def test_when_list_sum_calculated_then_returns_total(self):
        """
        GIVEN a list with numeric elements
        WHEN sum function is called on list
        THEN expect sum equals total of all elements
        """
        result = sum(TEST_LIST)
        
        assert result == TEST_LIST_SUM, f"Expected {TEST_LIST_SUM}, got {result}"

    def test_when_list_max_found_then_returns_largest_element(self):
        """
        GIVEN a list with numeric elements
        WHEN max function is called on list
        THEN expect max equals largest element
        """
        result = max(TEST_LIST)
        
        assert result == TEST_LIST_MAX, f"Expected {TEST_LIST_MAX}, got {result}"

    def test_when_list_min_found_then_returns_smallest_element(self):
        """
        GIVEN a list with numeric elements
        WHEN min function is called on list
        THEN expect min equals smallest element
        """
        result = min(TEST_LIST)
        
        assert result == TEST_LIST_MIN, f"Expected {TEST_LIST_MIN}, got {result}"

    @pytest.mark.parametrize("input_val,expected", [
        (2, 4),
        (3, 9), 
        (4, 16),
        (5, 25)
    ])
    def test_when_number_squared_then_returns_square_value(self, input_val, expected):
        """
        GIVEN a numeric input value
        WHEN number is squared using exponentiation operator
        THEN expect result equals expected square value
        """
        result = input_val ** 2
        
        assert result == expected, f"Expected {expected}, got {result}"


@pytest.mark.unit
class TestDictionaryOperations:
    """
    Tests for basic dictionary operations functionality.
    Functions under test: dict.__getitem__, dict.get, dict.__contains__, dict.keys
    """

    def test_when_dictionary_key_accessed_then_returns_value(self):
        """
        GIVEN a dictionary with known key-value pairs
        WHEN key is accessed using bracket notation
        THEN expect value associated with key
        """
        data = {"name": TEST_DICT_NAME, "value": TEST_DICT_VALUE}
        result = data["name"]
        
        assert result == TEST_DICT_NAME, f"Expected {TEST_DICT_NAME}, got {result}"

    def test_when_dictionary_get_used_then_returns_value(self):
        """
        GIVEN a dictionary with known key-value pairs
        WHEN get method is called with existing key
        THEN expect value associated with key
        """
        data = {"name": TEST_DICT_NAME, "value": TEST_DICT_VALUE}
        result = data.get("value")
        
        assert result == TEST_DICT_VALUE, f"Expected {TEST_DICT_VALUE}, got {result}"

    def test_when_dictionary_contains_checked_then_returns_true_if_key_exists(self):
        """
        GIVEN a dictionary with known keys
        WHEN in operator is used with existing key
        THEN expect True is returned
        """
        data = {"name": TEST_DICT_NAME, "value": TEST_DICT_VALUE}
        result = "name" in data
        
        assert result is True, f"Expected True for 'name' in dictionary, got {result}"

    def test_when_dictionary_keys_accessed_then_returns_key_set(self):
        """
        GIVEN a dictionary with known keys
        WHEN keys method is called
        THEN expect set containing all dictionary keys
        """
        data = {"name": TEST_DICT_NAME, "value": TEST_DICT_VALUE}
        result = data.keys()
        
        assert result == {"name", "value"}, f"Expected {{'name', 'value'}}, got {result}"


@pytest.mark.unit
class TestFileOperations:
    """
    Tests for file operations functionality.
    Functions under test: file I/O operations with temporary files
    Shared terminology: "temp file" means temporary file created in temp_dir fixture
    """

    def test_when_file_created_then_file_exists_on_filesystem(self, temp_dir):
        """
        GIVEN temporary directory and file content
        WHEN file is created with write operation
        THEN expect file exists on filesystem
        """
        file_path = os.path.join(temp_dir, "test.txt")
        
        with open(file_path, 'w') as f:
            f.write(TEMP_FILE_CONTENT)
        
        assert os.path.exists(file_path), f"Expected file {file_path} to exist"

    def test_when_file_read_then_returns_written_content(self, temp_dir):
        """
        GIVEN temporary file with known content
        WHEN file is read using read operation
        THEN expect content equals originally written content
        """
        file_path = os.path.join(temp_dir, "test.txt")
        
        with open(file_path, 'w') as f:
            f.write(TEMP_FILE_CONTENT)
        
        with open(file_path, 'r') as f:
            result = f.read()
        
        assert result == TEMP_FILE_CONTENT, f"Expected {TEMP_FILE_CONTENT}, got {result}"


@pytest.mark.unit 
class TestJsonOperations:
    """
    Tests for JSON file operations functionality.
    Functions under test: json.dump, json.load
    Shared terminology: "JSON data" means dictionary serializable to JSON
    """

    def test_when_json_data_written_then_file_contains_valid_json(self, temp_dir):
        """
        GIVEN dictionary data and temporary JSON file
        WHEN json.dump is called to write data
        THEN expect file contains valid JSON data
        """
        json_file = os.path.join(temp_dir, "test.json")
        
        with open(json_file, 'w') as f:
            json.dump(EXPECTED_JSON_DICT, f)
        
        with open(json_file, 'r') as f:
            result = json.load(f)
        
        assert result == EXPECTED_JSON_DICT, f"Expected {EXPECTED_JSON_DICT}, got {result}"


@pytest.mark.unit
class TestPathOperations:
    """
    Tests for Path operations functionality. 
    Functions under test: Path.exists, Path.is_dir, Path.write_text, Path.read_text
    Shared terminology: "path object" means pathlib.Path instance
    """

    def test_when_temp_directory_checked_then_exists_returns_true(self, temp_dir):
        """
        GIVEN temporary directory path
        WHEN exists method is called on path object
        THEN expect True is returned
        """
        path = Path(temp_dir)
        result = path.exists()
        
        assert result is True, f"Expected True for directory existence, got {result}"

    def test_when_temp_directory_checked_then_is_dir_returns_true(self, temp_dir):
        """
        GIVEN temporary directory path
        WHEN is_dir method is called on path object
        THEN expect True is returned
        """
        path = Path(temp_dir)
        result = path.is_dir()
        
        assert result is True, f"Expected True for directory type, got {result}"

    def test_when_text_written_to_path_then_file_exists(self, temp_dir):
        """
        GIVEN path object and text content
        WHEN write_text method is called
        THEN expect file exists on filesystem
        """
        file_path = Path(temp_dir) / "test_file.txt"
        file_path.write_text(TEMP_FILE_CONTENT)
        
        assert file_path.exists(), f"Expected file {file_path} to exist"

    def test_when_text_written_to_path_then_is_file_returns_true(self, temp_dir):
        """
        GIVEN path object with written text content
        WHEN is_file method is called
        THEN expect True is returned
        """
        file_path = Path(temp_dir) / "test_file.txt"
        file_path.write_text(TEMP_FILE_CONTENT)
        
        assert file_path.is_file(), f"Expected True for file type, got {file_path.is_file()}"

    def test_when_text_read_from_path_then_returns_written_content(self, temp_dir):
        """
        GIVEN path object with written text content
        WHEN read_text method is called
        THEN expect content equals originally written text
        """
        file_path = Path(temp_dir) / "test_file.txt"
        file_path.write_text(TEMP_FILE_CONTENT)
        
        result = file_path.read_text()
        
        assert result == TEMP_FILE_CONTENT, f"Expected {TEMP_FILE_CONTENT}, got {result}"


@pytest.mark.unit
class TestExceptionHandling:
    """
    Tests for exception handling patterns functionality.
    Functions under test: division, dictionary access, type operations, int conversion
    """

    def test_when_division_by_zero_performed_then_raises_zero_division_error(self):
        """
        GIVEN numeric value and zero divisor
        WHEN division operation is performed
        THEN expect ZeroDivisionError is raised
        """
        with pytest.raises(ZeroDivisionError):
            result = 10 / 0

    def test_when_nonexistent_key_accessed_then_raises_key_error(self):
        """
        GIVEN dictionary without specific key
        WHEN nonexistent key is accessed using bracket notation
        THEN expect KeyError is raised
        """
        data = {"a": 1}
        
        with pytest.raises(KeyError):
            value = data["nonexistent"]

    def test_when_incompatible_types_added_then_raises_type_error(self):
        """
        GIVEN string and integer values
        WHEN addition operation is performed between incompatible types
        THEN expect TypeError is raised
        """
        with pytest.raises(TypeError):
            result = "string" + 5

    def test_when_invalid_string_converted_to_int_then_raises_value_error(self):
        """
        GIVEN non-numeric string
        WHEN int conversion is attempted
        THEN expect ValueError is raised with invalid literal message
        """
        with pytest.raises(ValueError, match="invalid literal"):
            int("not_a_number")


@pytest.mark.unit
class TestDataStructures:
    """Test various data structures."""

    def test_set_operations(self):
        """Test set operations."""
        set1 = {1, 2, 3}
        set2 = {2, 3, 4}
        
        assert set1.union(set2) == {1, 2, 3, 4}
        assert set1.intersection(set2) == {2, 3}
        assert set1.difference(set2) == {1}

    def test_tuple_operations(self):
        """Test tuple operations."""
        data = ("a", "b", "c")
        assert len(data) == 3
        assert data[0] == "a"
        assert data[-1] == "c"
        assert "b" in data

    @pytest.mark.parametrize("data_structure,expected_len", [
        ([1, 2, 3], 3),
        ({"a", "b", "c"}, 3),
        ({"x": 1, "y": 2}, 2),
        ("hello", 5)
    ])
    def test_length_operations(self, data_structure, expected_len):
        """Test length operations on different data structures."""
        assert len(data_structure) == expected_len


@pytest.mark.integration  
class TestIntegrationExample:
    """Example integration tests."""

    def test_multiple_operations_together(self, temp_dir):
        """Test multiple operations working together."""
        # Create test data
        test_data = {
            "files": ["file1.txt", "file2.txt", "file3.txt"],
            "metadata": {
                "created": "2023-01-01",
                "version": "1.0"
            }
        }
        
        # Write JSON config
        config_file = os.path.join(temp_dir, "config.json")
        with open(config_file, 'w') as f:
            json.dump(test_data, f)
        
        # Create referenced files
        for filename in test_data["files"]:
            file_path = os.path.join(temp_dir, filename)
            with open(file_path, 'w') as f:
                f.write(f"Content of {filename}")
        
        # Verify all files exist
        for filename in test_data["files"]:
            file_path = os.path.join(temp_dir, filename)
            assert os.path.exists(file_path)
        
        # Verify config can be loaded
        with open(config_file, 'r') as f:
            loaded_config = json.load(f)
        
        assert loaded_config == test_data
        assert len(loaded_config["files"]) == 3
        assert loaded_config["metadata"]["version"] == "1.0"