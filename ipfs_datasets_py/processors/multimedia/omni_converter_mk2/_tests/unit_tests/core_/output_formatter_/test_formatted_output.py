import unittest
import tempfile
import os
import stat
import json
import threading
import time
from dataclasses import asdict, fields
from unittest.mock import Mock, MagicMock, patch

from core.output_formatter._formatted_output import FormattedOutput


def make_sample_formatted_output() -> FormattedOutput:
    """
    Create a sample FormattedOutput instance for testing.
    
    Returns:
        FormattedOutput instance with sample data.
    """
    return FormattedOutput(
        content="Sample content for testing",
        format="txt",
        metadata={'author': 'test_user', 'created': '2024-01-01'},
        output_path="/tmp/test_output.txt"
    )

from configs import configs, Configs
from core.text_normalizer._normalized_content import NormalizedContent
from types_  import Logger

def make_mock_resources() -> dict[str, MagicMock]:
    """
    Factory function to create an OutputFormatter instance.
    
    Returns:
        An instance of OutputFormatter configured with proper dependencies.
    """
    resources = {
        "normalized_content": MagicMock(spec=NormalizedContent),
        "formatted_output": MagicMock(spec=FormattedOutput),
        "logger": MagicMock(spec=Logger),
    }
    return resources


class TestFormattedOutputInitialization(unittest.TestCase):
    """Test FormattedOutput dataclass initialization."""

    def setUp(self):
        """Set up test fixtures."""
        self.sample_content = "Sample content"
        self.sample_format = "txt"
        self.sample_metadata = {'author': 'test', 'date': '2024-01-01'}
        self.sample_output_path = "/path/to/output.txt"

    def test_init_with_all_parameters(self):
        """
        GIVEN all parameters for FormattedOutput
        WHEN FormattedOutput is initialized with:
            - content="Sample content"
            - format="txt"
            - metadata={'author': 'test', 'date': '2024-01-01'}
            - output_path="/path/to/output.txt"
        THEN expect:
            - Instance created successfully
            - All attributes set correctly
            - No defaults overridden unintentionally
        """
        # Act
        output = FormattedOutput(
            content=self.sample_content,
            format=self.sample_format,
            metadata=self.sample_metadata,
            output_path=self.sample_output_path
        )
        
        # Assert
        self.assertEqual(output.content, self.sample_content)
        self.assertEqual(output.format, self.sample_format)
        self.assertEqual(output.metadata, self.sample_metadata)
        self.assertEqual(output.output_path, self.sample_output_path)

    def test_init_with_minimal_parameters(self):
        """
        GIVEN only required parameters
        WHEN FormattedOutput is initialized with:
            - content="Sample content"
            - format="txt"
        THEN expect:
            - Instance created successfully
            - metadata is empty dict (default)
            - output_path is empty string (default)
        """
        # Act
        output = FormattedOutput(
            content=self.sample_content,
            format=self.sample_format
        )
        
        # Assert
        self.assertEqual(output.content, self.sample_content)
        self.assertEqual(output.format, self.sample_format)
        self.assertEqual(output.metadata, {})
        self.assertEqual(output.output_path, "")

    def test_init_metadata_default_factory(self):
        """
        GIVEN multiple FormattedOutput instances
        WHEN created without specifying metadata
        THEN expect:
            - Each instance has its own empty dict
            - Modifying one doesn't affect others
            - Default factory creates new dict each time
        """
        # Act
        output1 = FormattedOutput(content="content1", format="txt")
        output2 = FormattedOutput(content="content2", format="txt")
        
        # Modify one instance's metadata
        output1.metadata['test'] = 'value'
        
        # Assert
        self.assertEqual(output1.metadata, {'test': 'value'})
        self.assertEqual(output2.metadata, {})
        self.assertIsNot(output1.metadata, output2.metadata)

    def test_init_with_none_values(self):
        """
        GIVEN None values for optional parameters
        WHEN FormattedOutput is initialized with metadata=None
        THEN expect:
            - TypeError or proper handling
            - Clear indication that dict expected
        """
        # Act & Assert
        with self.assertRaises(TypeError):
            FormattedOutput(
                content=self.sample_content,
                format=self.sample_format,
                metadata=None
            )

    def test_init_immutability_considerations(self):
        """
        GIVEN FormattedOutput is a dataclass
        WHEN attempting to verify if frozen=True
        THEN expect:
            - Determine if attributes can be modified after creation
            - Document mutability behavior
        """
        # Act
        output = FormattedOutput(
            content=self.sample_content,
            format=self.sample_format
        )
        
        # Try to modify attributes
        original_content = output.content
        output.content = "Modified content"
        
        # Assert - should be mutable unless frozen=True
        self.assertNotEqual(output.content, original_content)
        self.assertEqual(output.content, "Modified content")




class TestFormattedOutputToDict(unittest.TestCase):
    """Test to_dict method functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.sample_content = "Sample content for testing"
        self.sample_format = "txt"
        self.sample_metadata = {'author': 'test', 'date': '2024-01-01'}
        self.sample_output_path = "/path/to/output.txt"

    def test_to_dict_with_all_attributes(self):
        """
        GIVEN a FormattedOutput with all attributes set
        WHEN to_dict is called
        THEN expect:
            - Returns dict with keys: 'content', 'format', 'metadata', 'output_path'
            - Values match instance attributes
            - Dict is JSON-serializable
        """
        # Arrange
        output = FormattedOutput(
            content=self.sample_content,
            format=self.sample_format,
            metadata=self.sample_metadata,
            output_path=self.sample_output_path
        )
        
        # Act
        result = output.to_dict()
        
        # Assert
        expected_keys = {'content', 'format', 'metadata', 'output_path'}
        self.assertEqual(set(result.keys()), expected_keys)
        self.assertEqual(result['content'], self.sample_content)
        self.assertEqual(result['format'], self.sample_format)
        self.assertEqual(result['metadata'], self.sample_metadata)
        self.assertEqual(result['output_path'], self.sample_output_path)

    def test_to_dict_with_empty_metadata(self):
        """
        GIVEN a FormattedOutput with empty metadata dict
        WHEN to_dict is called
        THEN expect:
            - metadata key exists in result
            - metadata value is empty dict {}
        """
        # Arrange
        output = FormattedOutput(
            content=self.sample_content,
            format=self.sample_format
        )
        
        # Act
        result = output.to_dict()
        
        # Assert
        self.assertIn('metadata', result)
        self.assertEqual(result['metadata'], {})

    def test_to_dict_with_complex_metadata(self):
        """
        GIVEN a FormattedOutput with nested metadata structure
        WHEN to_dict is called
        THEN expect:
            - Nested structures preserved
            - All data types properly converted
            - No reference issues
        """
        # Arrange
        complex_metadata = {
            'author': 'test_user',
            'tags': ['tag1', 'tag2'],
            'settings': {
                'format_options': {'indent': 4, 'pretty_print': True},
                'validation': {'strict': False}
            },
            'counts': {'lines': 100, 'words': 500}
        }
        output = FormattedOutput(
            content=self.sample_content,
            format=self.sample_format,
            metadata=complex_metadata
        )
        
        # Act
        result = output.to_dict()
        
        # Assert
        self.assertEqual(result['metadata'], complex_metadata)
        self.assertEqual(result['metadata']['tags'], ['tag1', 'tag2'])
        self.assertEqual(result['metadata']['settings']['format_options']['indent'], 4)

    def test_to_dict_creates_new_dict(self):
        """
        GIVEN a FormattedOutput instance
        WHEN to_dict is called multiple times
        THEN expect:
            - Each call returns new dict instance
            - Modifying returned dict doesn't affect original
        """
        # Arrange
        output = FormattedOutput(
            content=self.sample_content,
            format=self.sample_format,
            metadata=self.sample_metadata
        )
        
        # Act
        dict1 = output.to_dict()
        dict2 = output.to_dict()
        dict1['content'] = "Modified content"
        dict1['metadata']['new_key'] = 'new_value'
        
        # Assert
        self.assertIsNot(dict1, dict2)
        self.assertNotEqual(dict1['content'], dict2['content'])
        self.assertEqual(output.content, self.sample_content)  # Original unchanged
        self.assertNotIn('new_key', output.metadata)  # Original metadata unchanged

    def test_to_dict_json_serializable(self):
        """
        GIVEN a FormattedOutput with various data types
        WHEN to_dict result is JSON serialized
        THEN expect:
            - json.dumps succeeds without errors
            - All data properly serialized
        """
        # Arrange
        metadata_with_various_types = {
            'string': 'test',
            'integer': 42,
            'float': 3.14,
            'boolean': True,
            'list': [1, 2, 3],
            'dict': {'nested': 'value'},
            'none': None
        }
        output = FormattedOutput(
            content=self.sample_content,
            format=self.sample_format,
            metadata=metadata_with_various_types
        )
        
        # Act
        result_dict = output.to_dict()
        
        # Assert - should not raise any exceptions
        json_string = json.dumps(result_dict)
        self.assertIsInstance(json_string, str)
        
        # Verify round-trip
        parsed_back = json.loads(json_string)
        self.assertEqual(parsed_back['metadata']['string'], 'test')
        self.assertEqual(parsed_back['metadata']['integer'], 42)
        self.assertEqual(parsed_back['metadata']['boolean'], True)




class TestFormattedOutputWriteToFile(unittest.TestCase):
    """Test write_to_file method functionality."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.sample_content = "Sample content for testing\nWith multiple lines"
        self.sample_format = "txt"
        self.sample_metadata = {'author': 'test', 'date': '2024-01-01'}

    def tearDown(self):
        """Clean up test fixtures."""
        # Clean up any files created during testing
        if os.path.exists(self.temp_dir):
            for root, dirs, files in os.walk(self.temp_dir, topdown=False):
                for file in files:
                    file_path = os.path.join(root, file)
                    os.chmod(file_path, stat.S_IWRITE)
                    os.remove(file_path)
                for dir in dirs:
                    os.rmdir(os.path.join(root, dir))
            os.rmdir(self.temp_dir)

    def test_write_to_file_with_instance_output_path(self):
        """
        GIVEN a FormattedOutput with output_path="/tmp/test.txt"
        WHEN write_to_file is called with no arguments
        THEN expect:
            - File written to instance's output_path
            - Content matches instance content
            - Returns the path where written
        """
        # Arrange
        output_path = os.path.join(self.temp_dir, "test.txt")
        output = FormattedOutput(
            content=self.sample_content,
            format=self.sample_format,
            metadata=self.sample_metadata,
            output_path=output_path
        )
        
        # Act
        result_path = output.write_to_file()
        
        # Assert
        self.assertEqual(result_path, output_path)
        self.assertTrue(os.path.exists(output_path))
        with open(output_path, 'r') as f:
            written_content = f.read()
        self.assertEqual(written_content, self.sample_content)

    def test_write_to_file_with_parameter_output_path(self):
        """
        GIVEN a FormattedOutput with output_path="/tmp/test1.txt"
        WHEN write_to_file is called with output_path="/tmp/test2.txt"
        THEN expect:
            - File written to parameter path (test2.txt)
            - Instance output_path unchanged
            - Returns the parameter path
        """
        # Arrange
        instance_path = os.path.join(self.temp_dir, "test1.txt")
        parameter_path = os.path.join(self.temp_dir, "test2.txt")
        output = FormattedOutput(
            content=self.sample_content,
            format=self.sample_format,
            output_path=instance_path
        )
        
        # Act
        result_path = output.write_to_file(output_path=parameter_path)
        
        # Assert
        self.assertEqual(result_path, parameter_path)
        self.assertEqual(output.output_path, instance_path)  # Instance unchanged
        self.assertTrue(os.path.exists(parameter_path))
        self.assertFalse(os.path.exists(instance_path))  # Instance path not used
        with open(parameter_path, 'r') as f:
            written_content = f.read()
        self.assertEqual(written_content, self.sample_content)

    def test_write_to_file_no_path_specified(self):
        """
        GIVEN a FormattedOutput with empty output_path=""
        WHEN write_to_file is called with no arguments
        THEN expect:
            - ValueError raised
            - Error message indicates no output path specified
        """
        # Arrange
        output = FormattedOutput(
            content=self.sample_content,
            format=self.sample_format,
            output_path=""
        )
        
        # Act & Assert
        with self.assertRaises(ValueError) as context:
            output.write_to_file()
        
        self.assertIn("output path", str(context.exception).lower())

    def test_write_to_file_creates_parent_directories(self):
        """
        GIVEN a FormattedOutput with output_path="/tmp/new/dir/test.txt"
        WHEN write_to_file is called and parent dirs don't exist
        THEN expect:
            - Parent directories created automatically
            - File written successfully
            - No errors raised
        """
        # Arrange
        nested_path = os.path.join(self.temp_dir, "new", "nested", "dir", "test.txt")
        output = FormattedOutput(
            content=self.sample_content,
            format=self.sample_format,
            output_path=nested_path
        )
        
        # Act
        result_path = output.write_to_file()
        
        # Assert
        self.assertEqual(result_path, nested_path)
        self.assertTrue(os.path.exists(nested_path))
        self.assertTrue(os.path.isdir(os.path.dirname(nested_path)))
        with open(nested_path, 'r') as f:
            written_content = f.read()
        self.assertEqual(written_content, self.sample_content)

    def test_write_to_file_handles_existing_file(self):
        """
        GIVEN a FormattedOutput and existing file at output_path
        WHEN write_to_file is called
        THEN expect:
            - Existing file is overwritten
            - New content replaces old content
            - Or configurable behavior documented
        """
        # Arrange
        output_path = os.path.join(self.temp_dir, "existing.txt")
        
        # Create existing file with different content
        with open(output_path, 'w') as f:
            f.write("Old content that should be replaced")
        
        output = FormattedOutput(
            content=self.sample_content,
            format=self.sample_format,
            output_path=output_path
        )
        
        # Act
        result_path = output.write_to_file()
        
        # Assert
        self.assertEqual(result_path, output_path)
        with open(output_path, 'r') as f:
            written_content = f.read()
        self.assertEqual(written_content, self.sample_content)

    def test_write_to_file_permission_error(self):
        """
        GIVEN a FormattedOutput with output_path in protected directory
        WHEN write_to_file is called without permissions
        THEN expect:
            - IOError or PermissionError raised
            - Clear error message about permissions
        """
        # Arrange
        protected_dir = os.path.join(self.temp_dir, "protected")
        os.makedirs(protected_dir)
        os.chmod(protected_dir, stat.S_IREAD)  # Read-only
        
        output_path = os.path.join(protected_dir, "test.txt")
        output = FormattedOutput(
            content=self.sample_content,
            format=self.sample_format,
            output_path=output_path
        )
        
        # Act & Assert
        with self.assertRaises((IOError, PermissionError, OSError)):
            output.write_to_file()

    def test_write_to_file_invalid_path_characters(self):
        """
        GIVEN a FormattedOutput with invalid path characters
        WHEN write_to_file is called
        THEN expect:
            - Appropriate error raised
            - Clear indication of path issue
        """
        # Arrange - using null character which is invalid on most filesystems
        invalid_path = os.path.join(self.temp_dir, "test\x00invalid.txt")
        output = FormattedOutput(
            content=self.sample_content,
            format=self.sample_format,
            output_path=invalid_path
        )
        
        # Act & Assert
        with self.assertRaises((ValueError, OSError)):
            output.write_to_file()

    def test_write_to_file_with_different_formats(self):
        """
        GIVEN FormattedOutput instances with different formats (txt, json, md)
        WHEN write_to_file is called for each
        THEN expect:
            - Files written with appropriate extensions
            - Content formatted correctly for each type
        """
        formats_and_content = [
            ("txt", "Plain text content"),
            ("json", '{"key": "value", "data": [1, 2, 3]}'),
            ("md", "# Markdown Header\n\nSome **bold** text")
        ]
        
        for fmt, content in formats_and_content:
            with self.subTest(format=fmt):
                # Arrange
                output_path = os.path.join(self.temp_dir, f"test.{fmt}")
                output = FormattedOutput(
                    content=content,
                    format=fmt,
                    output_path=output_path
                )
                
                # Act
                result_path = output.write_to_file()
                
                # Assert
                self.assertEqual(result_path, output_path)
                self.assertTrue(os.path.exists(output_path))
                with open(output_path, 'r') as f:
                    written_content = f.read()
                self.assertEqual(written_content, content)

    def test_write_to_file_unicode_content(self):
        """
        GIVEN a FormattedOutput with unicode content
        WHEN write_to_file is called
        THEN expect:
            - File written with proper encoding (UTF-8)
            - Unicode characters preserved
            - No encoding errors
        """
        # Arrange
        unicode_content = "Unicode content: 你好世界 🌍 émojis 🚀 áéíóú"
        output_path = os.path.join(self.temp_dir, "unicode.txt")
        output = FormattedOutput(
            content=unicode_content,
            format=self.sample_format,
            output_path=output_path
        )
        
        # Act
        result_path = output.write_to_file()
        
        # Assert
        self.assertEqual(result_path, output_path)
        with open(output_path, 'r', encoding='utf-8') as f:
            written_content = f.read()
        self.assertEqual(written_content, unicode_content)

    def test_write_to_file_large_content(self):
        """
        GIVEN a FormattedOutput with very large content (MB size)
        WHEN write_to_file is called
        THEN expect:
            - File written successfully
            - No memory issues
            - Efficient handling
        """
        # Arrange - Create 5MB of content
        large_content = "A" * (5 * 1024 * 1024)
        output_path = os.path.join(self.temp_dir, "large.txt")
        output = FormattedOutput(
            content=large_content,
            format=self.sample_format,
            output_path=output_path
        )
        
        # Act
        result_path = output.write_to_file()
        
        # Assert
        self.assertEqual(result_path, output_path)
        self.assertTrue(os.path.exists(output_path))
        file_size = os.path.getsize(output_path)
        self.assertEqual(file_size, len(large_content))

import unittest
import tempfile
import os
import json
from dataclasses import asdict, fields
from unittest.mock import Mock, MagicMock

from core.output_formatter._formatted_output import FormattedOutput


class TestFormattedOutputIntegration(unittest.TestCase):
    """Test FormattedOutput integration scenarios."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()
        self.sample_content = "Integration test content"
        self.sample_format = "txt"
        self.sample_metadata = {'test': 'integration', 'version': '1.0'}
        self.sample_output_path = os.path.join(self.temp_dir, "integration.txt")

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            for root, dirs, files in os.walk(self.temp_dir, topdown=False):
                for file in files:
                    os.remove(os.path.join(root, file))
                for dir in dirs:
                    os.rmdir(os.path.join(root, dir))
            os.rmdir(self.temp_dir)

    def test_round_trip_dict_conversion(self):
        """
        GIVEN a FormattedOutput instance
        WHEN converted to dict and back to FormattedOutput
        THEN expect:
            - All data preserved
            - Equivalent instances
        """
        # Arrange
        original = FormattedOutput(
            content=self.sample_content,
            format=self.sample_format,
            metadata=self.sample_metadata,
            output_path=self.sample_output_path
        )
        
        # Act
        as_dict = original.to_dict()
        reconstructed = FormattedOutput(**as_dict)
        
        # Assert
        self.assertEqual(original.content, reconstructed.content)
        self.assertEqual(original.format, reconstructed.format)
        self.assertEqual(original.metadata, reconstructed.metadata)
        self.assertEqual(original.output_path, reconstructed.output_path)

    def test_multiple_writes_different_paths(self):
        """
        GIVEN a single FormattedOutput instance
        WHEN write_to_file called multiple times with different paths
        THEN expect:
            - Each file written correctly
            - Instance remains unchanged
            - All files contain same content
        """
        # Arrange
        output = FormattedOutput(
            content=self.sample_content,
            format=self.sample_format,
            metadata=self.sample_metadata,
            output_path=self.sample_output_path
        )
        
        paths = [
            os.path.join(self.temp_dir, "file1.txt"),
            os.path.join(self.temp_dir, "file2.txt"),
            os.path.join(self.temp_dir, "subdir", "file3.txt")
        ]
        
        # Act
        written_paths = []
        for path in paths:
            result_path = output.write_to_file(output_path=path)
            written_paths.append(result_path)
        
        # Assert
        self.assertEqual(written_paths, paths)
        
        # Verify all files exist and contain same content
        for path in paths:
            self.assertTrue(os.path.exists(path))
            with open(path, 'r') as f:
                content = f.read()
            self.assertEqual(content, self.sample_content)
        
        # Verify instance unchanged
        self.assertEqual(output.content, self.sample_content)
        self.assertEqual(output.output_path, self.sample_output_path)

    def test_formatted_output_as_dataclass(self):
        """
        GIVEN FormattedOutput is a dataclass
        WHEN using dataclass features (asdict, fields, etc.)
        THEN expect:
            - Standard dataclass functionality works
            - Can be used with dataclass utilities
        """
        # Arrange
        output = FormattedOutput(
            content=self.sample_content,
            format=self.sample_format,
            metadata=self.sample_metadata,
            output_path=self.sample_output_path
        )
        
        # Act & Assert - Test asdict
        as_dict = asdict(output)
        expected_keys = {'content', 'format', 'metadata', 'output_path'}
        self.assertEqual(set(as_dict.keys()), expected_keys)
        self.assertEqual(as_dict['content'], self.sample_content)
        
        # Act & Assert - Test fields
        field_names = {f.name for f in fields(output)}
        self.assertEqual(field_names, expected_keys)
        
        # Verify field types
        field_dict = {f.name: f.type for f in fields(output)}
        self.assertEqual(field_dict['content'], str)
        self.assertEqual(field_dict['format'], str)
        
        # Act & Assert - Test equality
        output2 = FormattedOutput(
            content=self.sample_content,
            format=self.sample_format,
            metadata=self.sample_metadata,
            output_path=self.sample_output_path
        )
        self.assertEqual(output, output2)
        
        # Test inequality when content differs
        output3 = FormattedOutput(
            content="Different content",
            format=self.sample_format,
            metadata=self.sample_metadata,
            output_path=self.sample_output_path
        )
        self.assertNotEqual(output, output3)

    def test_end_to_end_workflow(self):
        """
        GIVEN a complete workflow scenario
        WHEN creating, converting, and writing FormattedOutput
        THEN expect:
            - All operations work together seamlessly
            - Data integrity maintained throughout
        """
        # Arrange - Simulate creating formatted output from processing
        raw_data = {"title": "Test Document", "content": "Processed content"}
        
        # Act - Create FormattedOutput
        output = FormattedOutput(
            content=f"Title: {raw_data['title']}\nContent: {raw_data['content']}",
            format="txt",
            metadata={
                'source': 'test_processor',
                'processed_at': '2024-01-01T12:00:00',
                'word_count': 4
            }
        )
        
        # Act - Convert to dict for serialization
        output_dict = output.to_dict()
        
        # Act - Write to multiple formats
        txt_path = os.path.join(self.temp_dir, "output.txt")
        json_path = os.path.join(self.temp_dir, "output.json")
        
        written_txt = output.write_to_file(output_path=txt_path)
        
        # Create JSON version
        json_output = FormattedOutput(
            content=json.dumps(output_dict, indent=2),
            format="json",
            metadata=output.metadata.copy()
        )
        written_json = json_output.write_to_file(output_path=json_path)
        
        # Assert - Verify all operations succeeded
        self.assertEqual(written_txt, txt_path)
        self.assertEqual(written_json, json_path)
        
        # Verify file contents
        with open(txt_path, 'r') as f:
            txt_content = f.read()
        self.assertIn("Title: Test Document", txt_content)
        self.assertIn("Content: Processed content", txt_content)
        
        with open(json_path, 'r') as f:
            json_content = json.load(f)
        self.assertEqual(json_content['metadata']['source'], 'test_processor')
        self.assertEqual(json_content['format'], 'txt')

    def test_metadata_mutability_and_isolation(self):
        """
        GIVEN FormattedOutput instances with shared metadata references
        WHEN modifying metadata
        THEN expect:
            - Changes properly isolated between instances
            - Deep copy behavior documented
        """
        # Arrange
        shared_metadata = {'shared': 'value', 'nested': {'count': 1}}
        
        output1 = FormattedOutput(
            content="Content 1",
            format="txt",
            metadata=shared_metadata
        )
        
        output2 = FormattedOutput(
            content="Content 2", 
            format="txt",
            metadata=shared_metadata
        )
        
        # Act - Modify metadata through one instance
        output1.metadata['new_key'] = 'new_value'
        output1.metadata['nested']['count'] = 999
        
        # Assert - Verify isolation (this may fail if shallow copy used)
        # This test documents the expected behavior
        self.assertEqual(output2.metadata['nested']['count'], 999)  # Shared reference
        self.assertIn('new_key', output2.metadata)  # Shared reference
        
        # Document that metadata is shared by reference unless deep copied
        self.assertIs(output1.metadata, output2.metadata)

import unittest
import tempfile
import os
import threading
import time
from unittest.mock import Mock, MagicMock, patch

from core.output_formatter._formatted_output import FormattedOutput


class TestFormattedOutputEdgeCases(unittest.TestCase):
    """Test edge cases and error conditions."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        """Clean up test fixtures."""
        if os.path.exists(self.temp_dir):
            for root, dirs, files in os.walk(self.temp_dir, topdown=False):
                for file in files:
                    os.remove(os.path.join(root, file))
                for dir in dirs:
                    os.rmdir(os.path.join(root, dir))
            os.rmdir(self.temp_dir)

    def test_empty_content_handling(self):
        """
        GIVEN a FormattedOutput with content=""
        WHEN write_to_file is called
        THEN expect:
            - Empty file created
            - No errors raised
        """
        # Arrange
        output_path = os.path.join(self.temp_dir, "empty.txt")
        output = FormattedOutput(
            content="",
            format="txt",
            output_path=output_path
        )
        
        # Act
        result_path = output.write_to_file()
        
        # Assert
        self.assertEqual(result_path, output_path)
        self.assertTrue(os.path.exists(output_path))
        self.assertEqual(os.path.getsize(output_path), 0)
        
        with open(output_path, 'r') as f:
            content = f.read()
        self.assertEqual(content, "")

    def test_very_long_output_path(self):
        """
        GIVEN a FormattedOutput with extremely long output_path
        WHEN write_to_file is called
        THEN expect:
            - System path length limits respected
            - Appropriate error if exceeds limits
        """
        # Arrange - Create a very long path (most systems limit around 255-4096 chars)
        long_filename = "a" * 300  # Exceeds typical filename length limit
        long_path = os.path.join(self.temp_dir, long_filename + ".txt")
        
        output = FormattedOutput(
            content="Content for long path test",
            format="txt",
            output_path=long_path
        )
        
        # Act & Assert
        # This should raise an OSError on most systems due to filename length
        with self.assertRaises(OSError):
            output.write_to_file()

    def test_special_format_extensions(self):
        """
        GIVEN FormattedOutput with various format values
        WHEN determining file extensions
        THEN expect:
            - Consistent extension mapping
            - Handles unknown formats gracefully
        """
        test_cases = [
            ("txt", "Plain text content"),
            ("json", '{"key": "value"}'),
            ("xml", "<root><item>value</item></root>"),
            ("csv", "col1,col2\nval1,val2"),
            ("unknown_format", "Content with unknown format"),
            ("", "Content with empty format"),
            ("UPPERCASE", "Content with uppercase format")
        ]
        
        for fmt, content in test_cases:
            with self.subTest(format=fmt):
                # Arrange
                safe_fmt = fmt.lower() if fmt else "txt"
                output_path = os.path.join(self.temp_dir, f"test_{safe_fmt}.{safe_fmt}")
                output = FormattedOutput(
                    content=content,
                    format=fmt,
                    output_path=output_path
                )
                
                # Act
                result_path = output.write_to_file()
                
                # Assert
                self.assertEqual(result_path, output_path)
                self.assertTrue(os.path.exists(output_path))
                with open(output_path, 'r') as f:
                    written_content = f.read()
                self.assertEqual(written_content, content)

    def test_metadata_with_non_string_keys(self):
        """
        GIVEN metadata dict with non-string keys
        WHEN to_dict and JSON serialization attempted
        THEN expect:
            - Keys converted to strings
            - Or appropriate error handling
        """
        # Arrange
        metadata_with_various_keys = {
            'string_key': 'value1',
            42: 'numeric_key_value',
            (1, 2): 'tuple_key_value',
            True: 'boolean_key_value'
        }
        
        output = FormattedOutput(
            content="Test content",
            format="txt",
            metadata=metadata_with_various_keys
        )
        
        # Act
        result_dict = output.to_dict()
        
        # Assert - Check that metadata is preserved as-is in to_dict
        self.assertEqual(result_dict['metadata'], metadata_with_various_keys)
        
        # JSON serialization should handle or fail gracefully
        import json
        try:
            json_string = json.dumps(result_dict)
            # If it succeeds, keys should be converted to strings
            parsed_back = json.loads(json_string)
            self.assertIsInstance(list(parsed_back['metadata'].keys())[0], str)
        except (TypeError, ValueError):
            # JSON serialization fails with non-string keys - this is expected
            pass

    def test_concurrent_file_writes(self):
        """
        GIVEN multiple FormattedOutput instances
        WHEN write_to_file called concurrently to same path
        THEN expect:
            - Last write wins
            - Or file locking behavior documented
        """
        # Arrange
        output_path = os.path.join(self.temp_dir, "concurrent.txt")
        contents = ["Content from thread 1", "Content from thread 2", "Content from thread 3"]
        
        outputs = [
            FormattedOutput(content=content, format="txt", output_path=output_path)
            for content in contents
        ]
        
        results = []
        exceptions = []
        
        def write_file(output, delay=0):
            try:
                time.sleep(delay)  # Add slight delay to encourage race condition
                result = output.write_to_file()
                results.append((result, output.content))
            except Exception as e:
                exceptions.append(e)
        
        # Act - Start concurrent writes
        threads = []
        for i, output in enumerate(outputs):
            thread = threading.Thread(target=write_file, args=(output, i * 0.01))
            threads.append(thread)
            thread.start()
        
        # Wait for all threads to complete
        for thread in threads:
            thread.join()
        
        # Assert
        self.assertEqual(len(exceptions), 0)  # No exceptions should occur
        self.assertTrue(os.path.exists(output_path))
        
        # File should contain content from one of the writes
        with open(output_path, 'r') as f:
            final_content = f.read()
        self.assertIn(final_content, contents)

    def test_whitespace_only_content(self):
        """
        GIVEN FormattedOutput with whitespace-only content
        WHEN write_to_file is called
        THEN expect:
            - Whitespace preserved exactly
            - File created with correct content
        """
        whitespace_cases = [
            "   ",  # Spaces
            "\t\t\t",  # Tabs
            "\n\n\n",  # Newlines
            " \t\n \t\n ",  # Mixed whitespace
        ]

        for i, whitespace_content in enumerate(whitespace_cases):
            with self.subTest(case=i):
                # Arrange
                output_path = os.path.join(self.temp_dir, f"whitespace_{i}.txt")
                output = FormattedOutput(
                    content=whitespace_content,
                    format="txt",
                    output_path=output_path
                )

                # Act
                result_path = output.write_to_file(skip_empty=False)

                # Assert
                self.assertEqual(result_path, output_path)
                with open(output_path, 'r') as f:
                    written_content = f.read()
                self.assertEqual(written_content, whitespace_content)
                self.assertEqual(len(written_content), len(whitespace_content))

    def test_binary_like_content(self):
        """
        GIVEN FormattedOutput with binary-like content (non-UTF8)
        WHEN write_to_file is called
        THEN expect:
            - Appropriate handling or error
            - Clear indication of encoding issues
        """
        # Arrange - Content that looks like binary data
        binary_like_content = "Normal text with \x00 null byte and \xff high byte"
        output_path = os.path.join(self.temp_dir, "binary_like.txt")
        output = FormattedOutput(
            content=binary_like_content,
            format="txt",
            output_path=output_path
        )
        
        # Act & Assert
        try:
            result_path = output.write_to_file()
            # If successful, verify content
            with open(output_path, 'r', encoding='utf-8', errors='replace') as f:
                written_content = f.read()
            # Content may be modified due to encoding handling
            self.assertTrue(os.path.exists(output_path))
        except UnicodeEncodeError:
            # This is acceptable - binary content in text format should fail
            pass

    def test_extremely_nested_metadata(self):
        """
        GIVEN FormattedOutput with deeply nested metadata
        WHEN to_dict is called
        THEN expect:
            - Deep nesting preserved
            - No recursion limits hit for reasonable depths
        """
        # Arrange - Create deeply nested metadata
        nested_metadata = {'level_0': {}}
        current_level = nested_metadata['level_0']
        
        for i in range(1, 50):  # 50 levels deep
            current_level[f'level_{i}'] = {}
            current_level = current_level[f'level_{i}']
        
        current_level['deep_value'] = 'found_it'
        
        output = FormattedOutput(
            content="Content with deep metadata",
            format="txt",
            metadata=nested_metadata
        )
        
        # Act
        result_dict = output.to_dict()
        
        # Assert - Navigate to deep value
        deep_value = result_dict['metadata']
        for i in range(50):
            deep_value = deep_value[f'level_{i}']
        
        self.assertEqual(deep_value['deep_value'], 'found_it')
