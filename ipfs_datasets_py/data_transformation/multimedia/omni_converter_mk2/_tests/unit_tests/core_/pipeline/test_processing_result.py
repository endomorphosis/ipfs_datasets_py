import unittest
from datetime import datetime
import time
import os
import shutil
import tempfile


from core._processing_result import ProcessingResult


class TestProcessingResultInitialization(unittest.TestCase):
    """Test ProcessingResult dataclass initialization and default values."""

    def setUp(self):
        """Set up test fixtures."""
        # Create a temp directory for test files
        self.temp_dir = tempfile.mkdtemp()

        # Create test files
        self.test_file_path = os.path.join(self.temp_dir, "test_file.txt")
        with open(self.test_file_path, 'w') as f:
            f.write("Test content")

        self.large_file_path = os.path.join(self.temp_dir, "large_file.txt")
        with open(self.large_file_path, 'w') as f:
            f.write("A" * (15 * 1024 * 1024))  # 15 MB file (exceeds text limit)

        self.executable_file_path = os.path.join(self.temp_dir, "test_script.sh")
        with open(self.executable_file_path, 'w') as f:
            f.write("#!/bin/sh\necho 'Hello, world!'")

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_init_with_only_required_attributes(self):
        """
        GIVEN only the required parameters (success and file_path)
        WHEN ProcessingResult is instantiated
        THEN expect:
            - success and file_path are set correctly
            - output_path defaults to empty string
            - format defaults to empty string
            - errors defaults to empty list
            - metadata defaults to empty dict
            - content_hash defaults to empty string
            - timestamp is set to current time (datetime.now)
        """
        # Create ProcessingResult with only required parameters
        result = ProcessingResult(success=True, file_path="/path/to/file.txt")
        
        # Assert required attributes are set correctly
        self.assertTrue(result.success)
        self.assertEqual(result.file_path, "/path/to/file.txt")
        
        # Assert default values
        self.assertEqual(result.output_path, "")
        self.assertEqual(result.format, "")
        self.assertEqual(result.errors, [])
        self.assertEqual(result.metadata, {})
        self.assertEqual(result.content_hash, "")
        
        # Assert timestamp is close to current time
        now = datetime.now()
        time_diff = abs((result.timestamp - now).total_seconds())
        self.assertLess(time_diff, 1.0)  # Within 1 second
        self.assertIsInstance(result.timestamp, datetime)

    def test_init_with_all_attributes(self):
        """
        GIVEN valid parameters for all ProcessingResult attributes
        WHEN ProcessingResult is instantiated with all parameters
        THEN expect:
            - All attributes are set to provided values
            - No defaults are used
            - timestamp is the provided datetime, not datetime.now
        """
        # Create test data
        test_timestamp = datetime(2023, 1, 1, 12, 0, 0)
        test_errors = ["Error 1", "Error 2"]
        test_metadata = {"key1": "value1", "key2": "value2"}
        
        # Create ProcessingResult with all parameters
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
        self.assertFalse(result.success)
        self.assertEqual(result.file_path, "/input/file.txt")
        self.assertEqual(result.output_path, "/output/file.txt")
        self.assertEqual(result.format, "pdf")
        self.assertEqual(result.errors, test_errors)
        self.assertEqual(result.metadata, test_metadata)
        self.assertEqual(result.content_hash, "abc123")
        self.assertEqual(result.timestamp, test_timestamp)

    def test_default_factory_for_mutable_fields(self):
        """
        GIVEN two ProcessingResult instances created with defaults
        WHEN modifying mutable fields (errors, metadata) on one instance
        THEN expect:
            - Other instance's fields remain unchanged
            - Each instance has its own list/dict objects
            - No shared mutable state between instances
        """
        # Create two instances with defaults
        result1 = ProcessingResult(success=True, file_path="/file1.txt")
        result2 = ProcessingResult(success=True, file_path="/file2.txt")
        
        # Modify mutable fields on first instance
        result1.errors.append("Error in result1")
        result1.metadata["key"] = "value1"
        
        # Assert second instance remains unchanged
        self.assertEqual(result2.errors, [])
        self.assertEqual(result2.metadata, {})
        
        # Assert instances have different list/dict objects
        self.assertIsNot(result1.errors, result2.errors)
        self.assertIsNot(result1.metadata, result2.metadata)

    def test_timestamp_default_uses_current_time(self):
        """
        GIVEN multiple ProcessingResult instances created at different times
        WHEN comparing their default timestamps
        THEN expect:
            - Each has a different timestamp
            - Timestamps are close to creation time
            - Timestamps are datetime objects
        """
        # Create first instance
        result1 = ProcessingResult(success=True, file_path="/file1.txt")
        time1 = datetime.now()
        
        # Wait a small amount of time
        time.sleep(0.01)
        
        # Create second instance
        result2 = ProcessingResult(success=True, file_path="/file2.txt")
        time2 = datetime.now()
        
        # Assert timestamps are different
        self.assertNotEqual(result1.timestamp, result2.timestamp)
        
        # Assert timestamps are close to creation times
        self.assertLess(abs((result1.timestamp - time1).total_seconds()), 1.0)
        self.assertLess(abs((result2.timestamp - time2).total_seconds()), 1.0)
        
        # Assert timestamps are datetime objects
        self.assertIsInstance(result1.timestamp, datetime)
        self.assertIsInstance(result2.timestamp, datetime)


class TestAddErrorSideEffects(unittest.TestCase):
    """Test the add_error method and its side effects."""

    def test_add_error_sets_success_to_false(self):
        """
        GIVEN a ProcessingResult with success=True
        WHEN add_error is called
        THEN expect:
            - Error is added to the errors list
            - success is set to False
            - success remains False even if it was already False
        """
        # Test with initially successful result
        result = ProcessingResult(success=True, file_path="/file.txt")
        
        result.add_error("Test error")
        
        self.assertIn("Test error", result.errors)
        self.assertFalse(result.success)
        
        # Test with already failed result
        result.add_error("Another error")
        
        self.assertIn("Another error", result.errors)
        self.assertFalse(result.success)  # Remains False

    def test_add_error_to_empty_list_with_side_effect(self):
        """
        GIVEN a ProcessingResult with empty errors list and success=True
        WHEN add_error is called with an error message
        THEN expect:
            - Error is added to the errors list
            - errors list contains exactly one item
            - success is now False
        """
        result = ProcessingResult(success=True, file_path="/file.txt")
        self.assertEqual(result.errors, [])
        self.assertTrue(result.success)
        
        result.add_error("First error")
        
        self.assertEqual(len(result.errors), 1)
        self.assertEqual(result.errors[0], "First error")
        self.assertFalse(result.success)

    def test_add_multiple_errors_success_remains_false(self):
        """
        GIVEN a ProcessingResult with success=True
        WHEN add_error is called multiple times
        THEN expect:
            - All errors are added in order
            - success is False after first error
            - success remains False after subsequent errors
        """
        result = ProcessingResult(success=True, file_path="/file.txt")
        
        result.add_error("Error 1")
        self.assertFalse(result.success)
        
        result.add_error("Error 2")
        self.assertFalse(result.success)
        
        result.add_error("Error 3")
        self.assertFalse(result.success)
        
        # Assert all errors are added in order
        expected_errors = ["Error 1", "Error 2", "Error 3"]
        self.assertEqual(result.errors, expected_errors)

    def test_add_error_with_empty_string_still_sets_success_false(self):
        """
        GIVEN a ProcessingResult with success=True
        WHEN add_error is called with an empty string
        THEN expect:
            - Empty string is added to errors list
            - success is set to False (even for empty error)
        """
        result = ProcessingResult(success=True, file_path="/file.txt")
        
        result.add_error("")
        
        self.assertIn("", result.errors)
        self.assertFalse(result.success)


class TestErrorStringFormatting(unittest.TestCase):
    """Test the error_string property formatting."""

    def test_error_string_returns_no_errors_message(self):
        """
        GIVEN a ProcessingResult with empty errors list
        WHEN error_string property is accessed
        THEN expect:
            - Returns exactly "No errors"
            - Not an empty string
        """
        result = ProcessingResult(success=True, file_path="/file.txt")
        
        error_string = result.error_string
        
        self.assertEqual(error_string, "No errors")
        self.assertNotEqual(error_string, "")

    def test_error_string_single_error_with_dash_prefix(self):
        """
        GIVEN a ProcessingResult with one error "File not found"
        WHEN error_string property is accessed
        THEN expect:
            - Returns "- File not found"
            - Has dash and space prefix
        """
        result = ProcessingResult(success=False, file_path="/file.txt")
        result.add_error("File not found")
        
        error_string = result.error_string
        
        self.assertEqual(error_string, "- File not found")
        self.assertTrue(error_string.startswith("- "))

    def test_error_string_multiple_errors_newline_separated(self):
        """
        GIVEN a ProcessingResult with errors ["Error 1", "Error 2", "Error 3"]
        WHEN error_string property is accessed
        THEN expect:
            - Returns "- Error 1\n- Error 2\n- Error 3"
            - Each error on new line with "- " prefix
            - No trailing newline
        """
        result = ProcessingResult(success=False, file_path="/file.txt")
        result.add_error("Error 1")
        result.add_error("Error 2")
        result.add_error("Error 3")
        
        error_string = result.error_string
        
        expected = "- Error 1\n- Error 2\n- Error 3"
        self.assertEqual(error_string, expected)
        self.assertFalse(error_string.endswith("\n"))
        
        # Verify each line has dash prefix
        lines = error_string.split("\n")
        for line in lines:
            self.assertTrue(line.startswith("- "))


class TestStrMethodFormatting(unittest.TestCase):
    """Test the __str__ method specific formatting."""

    def test_str_success_status_uppercase(self):
        """
        GIVEN a ProcessingResult with success=True
        WHEN str() is called
        THEN expect:
            - First line contains "SUCCESS" (uppercase)
            - Format: "Processing {file_path} - SUCCESS"
        """
        result = ProcessingResult(success=True, file_path="/test/file.txt")
        
        str_output = str(result)
        first_line = str_output.split("\n")[0]
        
        self.assertIn("SUCCESS", first_line)
        self.assertEqual(first_line, "Processing /test/file.txt - SUCCESS")

    def test_str_failed_status_uppercase(self):
        """
        GIVEN a ProcessingResult with success=False
        WHEN str() is called
        THEN expect:
            - First line contains "FAILED" (uppercase)
            - Format: "Processing {file_path} - FAILED"
        """
        result = ProcessingResult(success=False, file_path="/test/file.txt")
        
        str_output = str(result)
        first_line = str_output.split("\n")[0]
        
        self.assertIn("FAILED", first_line)
        self.assertEqual(first_line, "Processing /test/file.txt - FAILED")

    def test_str_empty_output_path_shows_none(self):
        """
        GIVEN a ProcessingResult with output_path=""
        WHEN str() is called
        THEN expect:
            - Output line shows "Output: None"
            - Not "Output: " (empty)
        """
        result = ProcessingResult(success=True, file_path="/file.txt", output_path="")
        
        str_output = str(result)
        lines = str_output.split("\n")
        output_line = [line for line in lines if line.startswith("Output:")][0]
        
        self.assertEqual(output_line, "Output: None")
        self.assertNotEqual(output_line, "Output: ")

    def test_str_empty_format_shows_unknown(self):
        """
        GIVEN a ProcessingResult with format=""
        WHEN str() is called
        THEN expect:
            - Format line shows "Format: Unknown"
            - Not "Format: " (empty)
        """
        result = ProcessingResult(success=True, file_path="/file.txt", format="")
        
        str_output = str(result)
        lines = str_output.split("\n")
        format_line = [line for line in lines if line.startswith("Format:")][0]
        
        self.assertEqual(format_line, "Format: Unknown")
        self.assertNotEqual(format_line, "Format: ")

    def test_str_complete_format_structure(self):
        """
        GIVEN a ProcessingResult with all fields populated
        WHEN str() is called
        THEN expect:
            - Line 1: "Processing {file_path} - {STATUS}"
            - Line 2: "Output: {output_path}"
            - Line 3: "Format: {format}"
            - Line 4: "Errors: {error_string}"
            - Line 5: "Timestamp: {timestamp.isoformat()}"
            - Lines separated by \n
        """
        timestamp = datetime(2023, 1, 1, 12, 0, 0)
        result = ProcessingResult(
            success=True,
            file_path="/input.txt",
            output_path="/output.txt",
            format="pdf",
            timestamp=timestamp
        )
        result.add_error("Test error")
        
        str_output = str(result)
        lines = str_output.split("\n")
        
        self.assertEqual(lines[0], "Processing /input.txt - FAILED")  # Failed due to error
        self.assertEqual(lines[1], "Output: /output.txt")
        self.assertEqual(lines[2], "Format: pdf")
        self.assertEqual(lines[3], "Errors: - Test error")
        self.assertEqual(lines[4], f"Timestamp: {timestamp.isoformat()}")

    def test_str_uses_error_string_property(self):
        """
        GIVEN a ProcessingResult with multiple errors
        WHEN str() is called
        THEN expect:
            - Errors line includes the formatted error_string
            - Shows "Errors: No errors" when no errors
            - Shows "Errors: - Error1\n- Error2" when errors exist
        """
        # Test with no errors
        result = ProcessingResult(success=True, file_path="/file.txt")
        str_output = str(result)
        self.assertIn("Errors: No errors", str_output)
        
        # Test with multiple errors
        result.add_error("Error1")
        result.add_error("Error2")
        str_output = str(result)
        
        # Should contain the formatted error string
        expected_error_part = "Errors: - Error1\n- Error2"
        self.assertIn("Errors: - Error1", str_output)
        self.assertIn("- Error2", str_output)


class TestDefaultFactoryBehavior(unittest.TestCase):
    """Test dataclass field default factory behaviors."""

    def test_errors_list_default_factory_creates_new_list(self):
        """
        GIVEN multiple ProcessingResult instances
        WHEN appending to one instance's errors list
        THEN expect:
            - Other instances' errors lists remain empty
            - Each instance has independent list
        """
        result1 = ProcessingResult(success=True, file_path="/file1.txt")
        result2 = ProcessingResult(success=True, file_path="/file2.txt")
        
        # Modify one instance
        result1.errors.append("Error in result1")
        
        # Other instance should remain unchanged
        self.assertEqual(result2.errors, [])
        self.assertEqual(result1.errors, ["Error in result1"])
        
        # Should be different list objects
        self.assertIsNot(result1.errors, result2.errors)

    def test_metadata_dict_default_factory_creates_new_dict(self):
        """
        GIVEN multiple ProcessingResult instances
        WHEN adding to one instance's metadata dict
        THEN expect:
            - Other instances' metadata dicts remain empty
            - Each instance has independent dict
        """
        result1 = ProcessingResult(success=True, file_path="/file1.txt")
        result2 = ProcessingResult(success=True, file_path="/file2.txt")
        
        # Modify one instance
        result1.metadata["key"] = "value"
        
        # Other instance should remain unchanged
        self.assertEqual(result2.metadata, {})
        self.assertEqual(result1.metadata, {"key": "value"})
        
        # Should be different dict objects
        self.assertIsNot(result1.metadata, result2.metadata)

    def test_timestamp_default_factory_calls_datetime_now(self):
        """
        GIVEN ProcessingResult instantiation without timestamp
        WHEN checking the default timestamp
        THEN expect:
            - timestamp is very close to current time
            - timestamp is a datetime object
            - Different instances have slightly different timestamps
        """
        before_time = datetime.now()
        result = ProcessingResult(success=True, file_path="/file.txt")
        after_time = datetime.now()
        
        # Timestamp should be between before and after times
        self.assertGreaterEqual(result.timestamp, before_time)
        self.assertLessEqual(result.timestamp, after_time)
        
        # Should be datetime object
        self.assertIsInstance(result.timestamp, datetime)
        
        # Different instances should have different timestamps
        time.sleep(0.01)
        result2 = ProcessingResult(success=True, file_path="/file2.txt")
        self.assertNotEqual(result.timestamp, result2.timestamp)


class TestAddMetadata(unittest.TestCase):
    """Test the add_metadata method."""

    def test_add_metadata_to_empty_dict(self):
        """
        GIVEN a ProcessingResult with empty metadata dict
        WHEN add_metadata is called with a key-value pair
        THEN expect:
            - Key-value pair is added to metadata dict
            - metadata dict contains exactly one item
            - The item matches the provided key and value
        """
        result = ProcessingResult(success=True, file_path="/file.txt")
        self.assertEqual(result.metadata, {})
        
        result.add_metadata("test_key", "test_value")
        
        self.assertEqual(len(result.metadata), 1)
        self.assertIn("test_key", result.metadata)
        self.assertEqual(result.metadata["test_key"], "test_value")

    def test_add_metadata_to_existing_dict(self):
        """
        GIVEN a ProcessingResult with existing metadata
        WHEN add_metadata is called with a new key-value pair
        THEN expect:
            - New key-value pair is added to metadata dict
            - Previous metadata remains unchanged
            - metadata dict size increases by one
        """
        initial_metadata = {"existing_key": "existing_value"}
        result = ProcessingResult(
            success=True, 
            file_path="/file.txt", 
            metadata=initial_metadata.copy()
        )
        
        result.add_metadata("new_key", "new_value")
        
        self.assertEqual(len(result.metadata), 2)
        self.assertEqual(result.metadata["existing_key"], "existing_value")
        self.assertEqual(result.metadata["new_key"], "new_value")

    def test_add_metadata_overwrites_existing_key(self):
        """
        GIVEN a ProcessingResult with existing metadata key
        WHEN add_metadata is called with same key but different value
        THEN expect:
            - Existing key's value is overwritten
            - metadata dict size remains the same
            - New value is stored for the key
        """
        initial_metadata = {"test_key": "old_value"}
        result = ProcessingResult(
            success=True, 
            file_path="/file.txt", 
            metadata=initial_metadata.copy()
        )
        
        result.add_metadata("test_key", "new_value")
        
        self.assertEqual(len(result.metadata), 1)
        self.assertEqual(result.metadata["test_key"], "new_value")

    def test_add_metadata_with_various_value_types(self):
        """
        GIVEN a ProcessingResult instance
        WHEN add_metadata is called with different value types (str, int, list, dict, None)
        THEN expect:
            - All value types are stored correctly
            - No type conversion occurs
            - Values can be retrieved with correct types
        """
        result = ProcessingResult(success=True, file_path="/file.txt")
        
        # Add various types
        result.add_metadata("string_key", "string_value")
        result.add_metadata("int_key", 42)
        result.add_metadata("list_key", [1, 2, 3])
        result.add_metadata("dict_key", {"nested": "value"})
        result.add_metadata("none_key", None)
        
        # Verify types and values
        self.assertEqual(result.metadata["string_key"], "string_value")
        self.assertIsInstance(result.metadata["string_key"], str)
        
        self.assertEqual(result.metadata["int_key"], 42)
        self.assertIsInstance(result.metadata["int_key"], int)
        
        self.assertEqual(result.metadata["list_key"], [1, 2, 3])
        self.assertIsInstance(result.metadata["list_key"], list)
        
        self.assertEqual(result.metadata["dict_key"], {"nested": "value"})
        self.assertIsInstance(result.metadata["dict_key"], dict)
        
        self.assertIsNone(result.metadata["none_key"])


class TestToDict(unittest.TestCase):
    """Test the to_dict method."""

    def test_to_dict_returns_all_fields(self):
        """
        GIVEN a ProcessingResult with all fields populated
        WHEN to_dict is called
        THEN expect:
            - Returned dict contains all expected keys
            - Values match the instance attributes
            - Dict is a new object (not a reference)
        """
        timestamp = datetime(2023, 1, 1, 12, 0, 0)
        result = ProcessingResult(
            success=True,
            file_path="/input.txt",
            output_path="/output.txt",
            format="pdf",
            errors=["Error 1"],
            metadata={"key": "value"},
            content_hash="abc123",
            timestamp=timestamp
        )
        
        result_dict = result.to_dict()
        
        # Check all expected keys exist
        expected_keys = {
            "success", "file_path", "output_path", "format", 
            "errors", "metadata", "content_hash", "timestamp"
        }
        self.assertEqual(set(result_dict.keys()), expected_keys)
        
        # Check values match (except timestamp which should be ISO string)
        self.assertEqual(result_dict["success"], True)
        self.assertEqual(result_dict["file_path"], "/input.txt")
        self.assertEqual(result_dict["output_path"], "/output.txt")
        self.assertEqual(result_dict["format"], "pdf")
        self.assertEqual(result_dict["errors"], ["Error 1"])
        self.assertEqual(result_dict["metadata"], {"key": "value"})
        self.assertEqual(result_dict["content_hash"], "abc123")
        
        # Dict should be a new object
        self.assertIsNot(result_dict, result.__dict__)

    def test_to_dict_with_empty_collections(self):
        """
        GIVEN a ProcessingResult with empty errors list and metadata dict
        WHEN to_dict is called
        THEN expect:
            - errors key exists with empty list value
            - metadata key exists with empty dict value
            - No keys are omitted
        """
        result = ProcessingResult(success=True, file_path="/file.txt")
        
        result_dict = result.to_dict()
        
        self.assertIn("errors", result_dict)
        self.assertEqual(result_dict["errors"], [])
        
        self.assertIn("metadata", result_dict)
        self.assertEqual(result_dict["metadata"], {})

    def test_to_dict_converts_timestamp_to_isoformat(self):
        """
        GIVEN a ProcessingResult with a datetime timestamp
        WHEN to_dict is called
        THEN expect:
            - timestamp in dict is a string
            - timestamp string is in ISO format
            - Original timestamp attribute remains datetime object
        """
        timestamp = datetime(2023, 1, 1, 12, 0, 0)
        result = ProcessingResult(
            success=True, 
            file_path="/file.txt", 
            timestamp=timestamp
        )
        
        result_dict = result.to_dict()
        
        # Dict timestamp should be string in ISO format
        self.assertIsInstance(result_dict["timestamp"], str)
        self.assertEqual(result_dict["timestamp"], timestamp.isoformat())
        
        # Original should remain datetime
        self.assertIsInstance(result.timestamp, datetime)

    def test_to_dict_returns_direct_references_to_mutable_fields(self):
        """
        GIVEN a ProcessingResult with errors and metadata
        WHEN to_dict is called and returned dict's lists/dicts are modified
        THEN expect:
            - Modifications affect the original ProcessingResult
            - errors and metadata are not deep copied
            - This is shallow copy behavior
        """
        result = ProcessingResult(success=True, file_path="/file.txt")
        result.add_error("Original error")
        result.add_metadata("original_key", "original_value")
        
        result_dict = result.to_dict()
        
        # Modify dict's collections
        result_dict["errors"].append("New error")
        result_dict["metadata"]["new_key"] = "new_value"
        
        # Original should be affected (shallow copy behavior)
        self.assertIn("New error", result.errors)
        self.assertIn("new_key", result.metadata)
        self.assertEqual(result.metadata["new_key"], "new_value")

    def test_to_dict_preserves_all_fields(self):
        """
        GIVEN a ProcessingResult with all fields populated
        WHEN to_dict is called
        THEN expect:
            - All 8 fields are present in dict
            - Keys match exactly: success, file_path, output_path, format, errors, metadata, content_hash, timestamp
            - Values match instance attributes (except timestamp is ISO string)
        """
        timestamp = datetime(2023, 1, 1, 12, 0, 0)
        result = ProcessingResult(
            success=False,
            file_path="/test.txt",
            output_path="/out.txt",
            format="docx",
            errors=["Test error"],
            metadata={"test": "data"},
            content_hash="hash123",
            timestamp=timestamp
        )
        
        result_dict = result.to_dict()
        
        # Verify all 8 expected fields
        expected_fields = {
            "success", "file_path", "output_path", "format",
            "errors", "metadata", "content_hash", "timestamp"
        }
        self.assertEqual(set(result_dict.keys()), expected_fields)
        self.assertEqual(len(result_dict), 8)
        
        # Verify values
        self.assertEqual(result_dict["success"], False)
        self.assertEqual(result_dict["file_path"], "/test.txt")
        self.assertEqual(result_dict["output_path"], "/out.txt")
        self.assertEqual(result_dict["format"], "docx")
        self.assertEqual(result_dict["errors"], ["Test error"])
        self.assertEqual(result_dict["metadata"], {"test": "data"})
        self.assertEqual(result_dict["content_hash"], "hash123")
        self.assertEqual(result_dict["timestamp"], timestamp.isoformat())


class TestProcessingResultIntegration(unittest.TestCase):
    """Test integrated behavior of ProcessingResult methods."""

    def test_add_error_affects_error_string(self):
        """
        GIVEN a ProcessingResult instance
        WHEN errors are added via add_error
        THEN expect:
            - error_string property reflects all added errors
            - Format remains consistent
        """
        result = ProcessingResult(success=True, file_path="/file.txt")
        
        # Initially no errors
        self.assertEqual(result.error_string, "No errors")
        
        # Add first error
        result.add_error("First error")
        self.assertEqual(result.error_string, "- First error")
        
        # Add second error
        result.add_error("Second error")
        expected = "- First error\n- Second error"
        self.assertEqual(result.error_string, expected)

    def test_add_metadata_affects_to_dict(self):
        """
        GIVEN a ProcessingResult instance
        WHEN metadata is added via add_metadata
        THEN expect:
            - to_dict includes all added metadata
            - Metadata structure is preserved
        """
        result = ProcessingResult(success=True, file_path="/file.txt")
        
        # Add metadata
        result.add_metadata("key1", "value1")
        result.add_metadata("key2", {"nested": "data"})
        
        result_dict = result.to_dict()
        
        expected_metadata = {"key1": "value1", "key2": {"nested": "data"}}
        self.assertEqual(result_dict["metadata"], expected_metadata)

    def test_full_workflow_simulation(self):
        """
        GIVEN a new ProcessingResult instance
        WHEN simulating a full processing workflow (add errors, add metadata, check string)
        THEN expect:
            - All methods work together coherently
            - State changes are reflected across all methods
            - No unexpected interactions between methods
        """
        # Start with successful processing
        result = ProcessingResult(
            success=True, 
            file_path="/input.doc",
            output_path="/output.pdf",
            format="pdf"
        )
        
        # Add some metadata about processing
        result.add_metadata("processing_time", 2.5)
        result.add_metadata("pages_converted", 10)
        
        # Encounter an error during processing
        result.add_error("Warning: Some formatting lost")
        
        # Verify state is consistent across all methods
        self.assertFalse(result.success)  # Should be False due to error
        self.assertIn("Warning: Some formatting lost", result.errors)
        self.assertEqual(result.error_string, "- Warning: Some formatting lost")
        
        # Check string representation
        str_output = str(result)
        self.assertIn("FAILED", str_output)
        self.assertIn("Warning: Some formatting lost", str_output)
        
        # Check dictionary representation
        result_dict = result.to_dict()
        self.assertFalse(result_dict["success"])
        self.assertEqual(result_dict["metadata"]["processing_time"], 2.5)
        self.assertEqual(result_dict["metadata"]["pages_converted"], 10)
        self.assertIn("Warning: Some formatting lost", result_dict["errors"])


if __name__ == '__main__':
    unittest.main()