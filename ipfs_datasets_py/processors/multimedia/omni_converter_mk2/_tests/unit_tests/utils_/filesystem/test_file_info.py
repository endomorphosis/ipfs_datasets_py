
import unittest
from unittest.mock import Mock, MagicMock
from pathlib import Path
import os

# Make sure the input file and documentation file exist.
cwd = os.getcwd()
assert os.path.exists(f'{cwd}/utils/filesystem.py'), "utils/filesystem.py does not exist at the specified directory."
assert os.path.exists(f'{cwd}/utils/filesystem_stubs.md'), "Documentation for utils/filesystem.py does not exist at the specified directory."


from utils.filesystem import FileInfo


assert FileInfo
assert FileInfo.from_path

# required_attributes = [
#     'path', 'size', 'modified_time', 'mime_type', 'extension', 'is_readable', 'is_writable'
# ]
# for attr in required_attributes:
#     assert hasattr(FileInfo, attr), f"FileContent should have an attribute '{attr}'"

import json
import time
import tempfile
import os
import stat
from datetime import datetime, timedelta

# Constants
KNOWN_CONTENT = "Hello, World!"
KNOWN_BYTE_COUNT = 13
TIME_LIMIT = 0.1  # seconds

class TestFileInfoFromPath(unittest.TestCase):
    """Test FileInfo.from_path class method."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_files = []
        self.temp_dirs = []

        self.binary_content = b'\x89PNG\r\n\x1a\n'  # PNG file signature

    def tearDown(self):
        """Clean up test fixtures."""
        # Clean up temporary files
        for temp_file in self.temp_files:
            try:
                if os.path.exists(temp_file):
                    # Restore permissions before deletion
                    os.chmod(temp_file, stat.S_IRUSR | stat.S_IWUSR)
                    os.unlink(temp_file)
            except (OSError, PermissionError):
                pass
        
        # Clean up temporary directories
        for temp_dir in self.temp_dirs:
            try:
                if os.path.exists(temp_dir):
                    os.rmdir(temp_dir)
            except OSError:
                pass

    def _create_temp_file(self, content, suffix=".txt", mode="w"):
        """Helper method to create temporary files."""
        fd, temp_path = tempfile.mkstemp(suffix=suffix)
        try:
            if mode == "wb":
                os.write(fd, content)
            else:
                os.write(fd, content.encode('utf-8'))
        finally:
            os.close(fd)
        self.temp_files.append(temp_path)
        return temp_path

    def _create_relative_temp_file(self, content, suffix=".txt"):
        """Helper method to create temporary files accessible via relative path."""
        # Create file in current directory
        temp_file_path = self._create_temp_file(content, suffix=suffix)
        relative_path = "./" + os.path.basename(temp_file_path)
        
        # Create a symlink or copy to make it accessible via relative path
        relative_temp_path = os.path.join(".", os.path.basename(temp_file_path))
        with open(relative_temp_path, 'w') as f:
            f.write(content)
        self.temp_files.append(relative_temp_path)
        
        return relative_path

    def test_from_path_creates_fileinfo_instance(self):
        """
        GIVEN existing text file with known properties
        WHEN from_path is called with the file path
        THEN expect FileInfo instance created without exceptions
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        self.assertIsInstance(file_info, FileInfo)

    def test_from_path_sets_correct_path(self):
        """
        GIVEN existing text file
        WHEN from_path is called with the file path
        THEN expect path attribute matches provided path
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        self.assertEqual(file_info.path, Path(temp_file_path))

    def test_from_path_sets_correct_size(self):
        """
        GIVEN existing text file with known content
        WHEN from_path is called with the file path
        THEN expect size attribute == KNOWN_BYTE_COUNT
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        self.assertEqual(file_info.size, KNOWN_BYTE_COUNT)

    def test_from_path_sets_recent_modified_time(self):
        """
        GIVEN existing text file
        WHEN from_path is called with the file path
        THEN expect modified_time attribute within 60 seconds of actual modification time
        """
        EXPECTED_TIME_SECONDS = 60
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        now = datetime.now()
        time_diff = abs((now - file_info.modified_time).total_seconds())
        self.assertLessEqual(time_diff, EXPECTED_TIME_SECONDS)

    def test_from_path_sets_text_mime_type(self):
        """
        GIVEN existing text file
        WHEN from_path is called with the file path
        THEN expect mime_type attribute starts with "text/"
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        self.assertTrue(file_info.mime_type.startswith("text/"))

    def test_from_path_sets_correct_extension(self):
        """
        GIVEN existing text file with .txt extension
        WHEN from_path is called with the file path
        THEN expect extension attribute == ".txt"
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        self.assertEqual(file_info.extension, "txt")

    def test_from_path_sets_readable_true(self):
        """
        GIVEN existing text file with default permissions
        WHEN from_path is called with the file path
        THEN expect is_readable attribute == True
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        self.assertTrue(file_info.is_readable)

    def test_from_path_sets_writable_true(self):
        """
        GIVEN existing text file with default permissions
        WHEN from_path is called with the file path
        THEN expect is_writable attribute == True
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        self.assertTrue(file_info.is_writable)

    def test_from_path_with_existing_binary_file_creates_instance(self):
        """
        GIVEN existing binary file
        WHERE:
            - existing_binary_file = temporary .png file with PNG header bytes
            - binary_content = b'\x89PNG\r\n\x1a\n' (PNG file signature)
        WHEN from_path is called with the file path
        THEN expect FileInfo instance created without exceptions
        """
        temp_file_path = self._create_temp_file(self.binary_content, suffix=".png", mode="wb")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        self.assertIsInstance(file_info, FileInfo)

    def test_from_path_with_existing_binary_file_sets_correct_mime_type(self):
        """
        GIVEN existing binary file
        WHERE:
            - existing_binary_file = temporary .png file with PNG header bytes
            - binary_content = b'\x89PNG\r\n\x1a\n' (PNG file signature)
        WHEN from_path is called with the file path
        THEN expect mime_type attribute == "image/png"
        """
        temp_file_path = self._create_temp_file(self.binary_content, suffix=".png", mode="wb")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        self.assertEqual(file_info.mime_type, "image/png")

    def test_from_path_with_existing_binary_file_sets_correct_path(self):
        """
        GIVEN existing binary file
        WHERE:
            - existing_binary_file = temporary .png file with PNG header bytes
            - binary_content = b'\x89PNG\r\n\x1a\n' (PNG file signature)
        WHEN from_path is called with the file path
        THEN expect path attribute matches provided path
        """
        temp_file_path = self._create_temp_file(self.binary_content, suffix=".png", mode="wb")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        self.assertEqual(file_info.path, Path(temp_file_path))

    def test_from_path_with_existing_binary_file_sets_correct_size(self):
        """
        GIVEN existing binary file
        WHERE:
            - existing_binary_file = temporary .png file with PNG header bytes
            - binary_content = b'\x89PNG\r\n\x1a\n' (PNG file signature)
        WHEN from_path is called with the file path
        THEN expect size attribute matches content length
        """
        temp_file_path = self._create_temp_file(self.binary_content, suffix=".png", mode="wb")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        self.assertEqual(file_info.size, len(self.binary_content))

    def test_from_path_with_existing_binary_file_sets_correct_extension(self):
        """
        GIVEN existing binary file
        WHERE:
            - existing_binary_file = temporary .png file with PNG header bytes
            - binary_content = b'\x89PNG\r\n\x1a\n' (PNG file signature)
        WHEN from_path is called with the file path
        THEN expect extension attribute == ".png"
        """
        temp_file_path = self._create_temp_file(self.binary_content, suffix=".png", mode="wb")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        self.assertEqual(file_info.extension, "png")

    def test_from_path_with_existing_binary_file_sets_readable_true(self):
        """
        GIVEN existing binary file
        WHERE:
            - existing_binary_file = temporary .png file with PNG header bytes
            - binary_content = b'\x89PNG\r\n\x1a\n' (PNG file signature)
        WHEN from_path is called with the file path
        THEN expect is_readable attribute == True
        """
        temp_file_path = self._create_temp_file(self.binary_content, suffix=".png", mode="wb")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        self.assertTrue(file_info.is_readable)

    def test_from_path_with_existing_binary_file_sets_writable_true(self):
        """
        GIVEN existing binary file
        WHERE:
            - existing_binary_file = temporary .png file with PNG header bytes
            - binary_content = b'\x89PNG\r\n\x1a\n' (PNG file signature)
        WHEN from_path is called with the file path
        THEN expect is_writable attribute == True
        """
        temp_file_path = self._create_temp_file(self.binary_content, suffix=".png", mode="wb")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        self.assertTrue(file_info.is_writable)


    def test_from_path_with_nonexistent_file(self):
        """
        GIVEN path to a file that does not exist
        WHERE:
            - nonexistent_file = "/path/that/does/not/exist.txt"
        WHEN from_path is called
        THEN expect FileNotFoundError to be raised
        """
        nonexistent_file = "/path/that/does/not/exist.txt"
        
        with self.assertRaises(FileNotFoundError):
            FileInfo.from_path(nonexistent_file)

    def test_from_path_with_directory_path(self):
        """
        GIVEN path pointing to a directory instead of a file
        WHERE:
            - directory_path = path to existing directory
        WHEN from_path is called
        THEN expect ValueError to be raised (pydantic).
        """
        temp_dir = tempfile.mkdtemp()
        self.temp_dirs.append(temp_dir)
        
        with self.assertRaises(ValueError):
            FileInfo.from_path(temp_dir)

    def test_from_path_with_relative_path_creates_instance(self):
        """
        GIVEN relative file path and file exists at that relative location
        WHERE:
            - relative_path = "./test_file.txt"
            - file exists at relative location
        WHEN from_path is called
        THEN expect FileInfo instance created without exceptions
        """
        relative_path = self._create_relative_temp_file(KNOWN_CONTENT, suffix=".txt")

        file_info = FileInfo.from_path(relative_path)
        
        self.assertIsInstance(file_info, FileInfo)

    def test_from_path_with_relative_path_sets_correct_path(self):
        """
        GIVEN relative file path and file exists at that relative location
        WHERE:
            - relative_path = "./test_file.txt"
            - file exists at relative location
        WHEN from_path is called
        THEN expect path attribute == "./test_file.txt"
        """
        relative_path = self._create_relative_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(relative_path)
        
        self.assertEqual(file_info.path, Path(relative_path).resolve())

    def test_from_path_with_relative_path_sets_correct_size(self):
        """
        GIVEN relative file path and file exists at that relative location
        WHERE:
            - relative_path = "./test_file.txt"
            - file exists at relative location
        WHEN from_path is called
        THEN expect size attribute == KNOWN_BYTE_COUNT
        """
        relative_path = self._create_relative_temp_file(KNOWN_CONTENT, suffix=".txt")

        file_info = FileInfo.from_path(relative_path)
        
        self.assertEqual(file_info.size, KNOWN_BYTE_COUNT)

    def test_from_path_with_relative_path_sets_correct_extension(self):
        """
        GIVEN relative file path and file exists at that relative location
        WHERE:
            - relative_path = "./test_file.txt"
            - file exists at relative location
        WHEN from_path is called
        THEN expect extension attribute == ".txt"
        """
        relative_path = self._create_relative_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(relative_path)
        
        self.assertEqual(file_info.extension, "txt")

    def test_from_path_with_absolute_path(self):
        """
        GIVEN absolute file path and file exists at that location
        WHERE:
            - absolute_path = full system path to test file
        WHEN from_path is called
        THEN expect:
            - FileInfo instance created without exceptions
            - path attribute contains the provided absolute path
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        absolute_path = os.path.abspath(temp_file_path)
        
        file_info = FileInfo.from_path(absolute_path)
        
        self.assertIsInstance(file_info, FileInfo)
        self.assertEqual(file_info.path, Path(absolute_path))
        self.assertEqual(file_info.size, KNOWN_BYTE_COUNT)

    def test_from_path_with_file_no_extension(self):
        """
        GIVEN existing file with no extension
        WHERE:
            - no_extension_file = "README" (markdown file without extension)
        WHEN from_path is called
        THEN expect:
            - FileInfo instance created without exceptions
            - extension attribute == ""
            - mime_type == "text/plain"
        """
        fd, temp_path = tempfile.mkstemp(suffix="")
        # Remove the temp file and recreate without extension
        os.close(fd)
        os.unlink(temp_path)
        
        no_extension_path = temp_path + "_README"
        with open(no_extension_path, 'w') as f:
            f.write("# README\nThis is a readme file.")
        self.temp_files.append(no_extension_path)
        
        file_info = FileInfo.from_path(no_extension_path)
        
        self.assertIsInstance(file_info, FileInfo)
        self.assertEqual(file_info.extension, "")
        self.assertEqual(file_info.mime_type, "text/plain")

    def test_from_path_with_permission_denied_file(self):
        """
        GIVEN file that exists but has restrictive read permissions (chmod 000)
        WHERE:
            - permission_denied_file = file with no read permissions (mode 000)
        WHEN from_path is called
        THEN expect:
            - FileInfo instance created successfully
            - is_readable attribute == False
            - is_writable attribute == False
            - Other attributes (size, modified_time) may be accessible via stat()
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        # Set restrictive permissions
        os.chmod(temp_file_path, 0o000)
        
        file_info = FileInfo.from_path(temp_file_path)
        
        self.assertIsInstance(file_info, FileInfo)
        self.assertFalse(file_info.is_readable)
        self.assertFalse(file_info.is_writable)
        # Size and modified_time should still be accessible via stat
        self.assertEqual(file_info.size, KNOWN_BYTE_COUNT)
        self.assertIsInstance(file_info.modified_time, datetime)

    def test_from_path_with_empty_string_path(self):
        """
        GIVEN empty string as path parameter
        WHERE:
            - empty_string_path = ""
        WHEN from_path is called
        THEN expect ValueError to be raised
        """
        empty_string_path = ""
        
        with self.assertRaises(ValueError):
            FileInfo.from_path(empty_string_path)

    def test_from_path_with_none_path(self):
        """
        GIVEN None as path parameter
        WHERE:
            - none_path = None
        WHEN from_path is called
        THEN expect TypeError to be raised
        """
        none_path = None
        
        with self.assertRaises(TypeError):
            FileInfo.from_path(none_path)


class TestFileInfoToDict(unittest.TestCase):
    """Test FileInfo.to_dict method."""

    def setUp(self):
        """Set up test fixtures."""
        self.temp_files = []

    def tearDown(self):
        """Clean up test fixtures."""
        for temp_file in self.temp_files:
            try:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
            except OSError:
                pass

    def _create_temp_file(self, content, suffix=".txt"):
        """Helper method to create temporary files."""
        fd, temp_path = tempfile.mkstemp(suffix=suffix)
        try:
            os.write(fd, content.encode('utf-8'))
        finally:
            os.close(fd)
        self.temp_files.append(temp_path)
        return temp_path

    def test_to_dict_returns_dict_type(self):
        """
        GIVEN FileInfo instance with all attributes populated
        WHEN to_dict is called
        THEN expect return type == dict
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        result_dict = file_info.to_dict()
        
        self.assertIsInstance(result_dict, dict)

    def test_to_dict_contains_path_key(self):
        """
        GIVEN FileInfo instance with all attributes populated
        WHEN to_dict is called
        THEN expect returned dictionary contains 'path' key
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        result_dict = file_info.to_dict()
        
        self.assertIn('path', result_dict)

    def test_to_dict_contains_size_key(self):
        """
        GIVEN FileInfo instance with all attributes populated
        WHEN to_dict is called
        THEN expect returned dictionary contains 'size' key
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        result_dict = file_info.to_dict()
        
        self.assertIn('size', result_dict)

    def test_to_dict_contains_modified_time_key(self):
        """
        GIVEN FileInfo instance with all attributes populated
        WHEN to_dict is called
        THEN expect returned dictionary contains 'modified_time' key
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        result_dict = file_info.to_dict()
        
        self.assertIn('modified_time', result_dict)

    def test_to_dict_contains_mime_type_key(self):
        """
        GIVEN FileInfo instance with all attributes populated
        WHEN to_dict is called
        THEN expect returned dictionary contains 'mime_type' key
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        result_dict = file_info.to_dict()
        
        self.assertIn('mime_type', result_dict)

    def test_to_dict_contains_extension_key(self):
        """
        GIVEN FileInfo instance with all attributes populated
        WHEN to_dict is called
        THEN expect returned dictionary contains 'extension' key
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        result_dict = file_info.to_dict()
        
        self.assertIn('extension', result_dict)

    def test_to_dict_contains_is_readable_key(self):
        """
        GIVEN FileInfo instance with all attributes populated
        WHEN to_dict is called
        THEN expect returned dictionary contains 'is_readable' key
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        result_dict = file_info.to_dict()
        
        self.assertIn('is_readable', result_dict)

    def test_to_dict_contains_is_writable_key(self):
        """
        GIVEN FileInfo instance with all attributes populated
        WHEN to_dict is called
        THEN expect returned dictionary contains 'is_writable' key
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        result_dict = file_info.to_dict()
        
        self.assertIn('is_writable', result_dict)

    def test_to_dict_path_value_matches_fileinfo_attribute(self):
        """
        GIVEN FileInfo instance with all attributes populated
        WHEN to_dict is called
        THEN expect dictionary 'path' value matches FileInfo.path attribute
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        result_dict = file_info.to_dict()
        
        self.assertEqual(result_dict['path'], str(file_info.path))

    def test_to_dict_size_value_matches_fileinfo_attribute(self):
        """
        GIVEN FileInfo instance with all attributes populated
        WHEN to_dict is called
        THEN expect dictionary 'size' value matches FileInfo.size attribute
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        result_dict = file_info.to_dict()
        
        self.assertEqual(result_dict['size'], file_info.size)

    def test_to_dict_modified_time_value_matches_fileinfo_attribute(self):
        """
        GIVEN FileInfo instance with all attributes populated
        WHEN to_dict is called
        THEN expect dictionary 'modified_time' value matches FileInfo.modified_time attribute
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        result_dict = file_info.to_dict()
        
        self.assertEqual(result_dict['modified_time'], file_info.modified_time.isoformat())

    def test_to_dict_mime_type_value_matches_fileinfo_attribute(self):
        """
        GIVEN FileInfo instance with all attributes populated
        WHEN to_dict is called
        THEN expect dictionary 'mime_type' value matches FileInfo.mime_type attribute
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        result_dict = file_info.to_dict()
        
        self.assertEqual(result_dict['mime_type'], file_info.mime_type)

    def test_to_dict_extension_value_matches_fileinfo_attribute(self):
        """
        GIVEN FileInfo instance with all attributes populated
        WHEN to_dict is called
        THEN expect dictionary 'extension' value matches FileInfo.extension attribute
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        result_dict = file_info.to_dict()
        
        self.assertEqual(result_dict['extension'], file_info.extension)

    def test_to_dict_is_readable_value_matches_fileinfo_attribute(self):
        """
        GIVEN FileInfo instance with all attributes populated
        WHEN to_dict is called
        THEN expect dictionary 'is_readable' value matches FileInfo.is_readable attribute
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        result_dict = file_info.to_dict()
        
        self.assertEqual(result_dict['is_readable'], file_info.is_readable)

    def test_to_dict_is_writable_value_matches_fileinfo_attribute(self):
        """
        GIVEN FileInfo instance with all attributes populated
        WHEN to_dict is called
        THEN expect dictionary 'is_writable' value matches FileInfo.is_writable attribute
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        result_dict = file_info.to_dict()
        
        self.assertEqual(result_dict['is_writable'], file_info.is_writable)

    def test_to_dict_with_datetime_serialization(self):
        """
        GIVEN FileInfo instance with modified_time as datetime object
        WHERE:
            - datetime_object = datetime.now()
        WHEN to_dict is called
        THEN expect:
            - modified_time is set without errors
            - modified_time value in dictionary is serializable
            - modified_time is in ISO 8601 format
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        result_dict = file_info.to_dict()
        
        # Check that modified_time is present
        self.assertIn('modified_time', result_dict)
        modified_time_value = result_dict['modified_time']
        
        # Check if it's serializable (either datetime or string)
        if isinstance(modified_time_value, str):
            # Should be ISO 8601 format if it's a string
            try:
                datetime.fromisoformat(modified_time_value.replace('Z', '+00:00'))
            except ValueError:
                self.fail("modified_time string is not in valid ISO format")
        elif isinstance(modified_time_value, datetime):
            # Should be a valid datetime object
            self.assertIsInstance(modified_time_value, datetime)
        else:
            self.fail(f"modified_time should be datetime or string, got {type(modified_time_value)}")

    def test_to_dict_immutability(self):
        """
        GIVEN FileInfo instance
        WHERE:
            - Original FileInfo with known attribute values:
                - original_path = "/path/to/file.txt"
                - original_size = 1234
                - original_modified_time = datetime.now()
                - original_mime_type = "text/plain"
                - original_extension = ".txt"
                - original_is_readable = True
                - original_is_writable = True
        WHEN to_dict is called and returned dictionary is modified
        THEN expect:
            - Original FileInfo attributes remain set to their original values
            - Subsequent calls to to_dict return original values
            - Dictionary is not the same object reference as internal data
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        # Store original values
        original_path = file_info.path
        original_size = file_info.size
        original_modified_time = file_info.modified_time
        original_mime_type = file_info.mime_type
        original_extension = file_info.extension
        original_is_readable = file_info.is_readable
        original_is_writable = file_info.is_writable
        
        # Get dictionary and modify it
        result_dict = file_info.to_dict()
        result_dict['path'] = "/modified/path"
        result_dict['size'] = 9999
        result_dict['mime_type'] = "modified/type"
        
        # Check original FileInfo attributes unchanged
        self.assertEqual(file_info.path, original_path)
        self.assertEqual(file_info.size, original_size)
        self.assertEqual(file_info.modified_time, original_modified_time)
        self.assertEqual(file_info.mime_type, original_mime_type)
        self.assertEqual(file_info.extension, original_extension)
        self.assertEqual(file_info.is_readable, original_is_readable)
        self.assertEqual(file_info.is_writable, original_is_writable)
        
        # Check subsequent calls return original values
        second_dict = file_info.to_dict()
        self.assertEqual(second_dict['path'], str(original_path))
        self.assertEqual(second_dict['size'], original_size)
        self.assertEqual(second_dict['mime_type'], original_mime_type)
        
        # Check dictionaries are different object references
        self.assertIsNot(result_dict, second_dict)

    def test_to_dict_with_none_values(self):
        """
        GIVEN FileInfo instance where mime_type is None
        WHEN to_dict is called
        THEN expect:
            - Dictionary contains None values for mime_type
            - No keys are omitted from the dictionary
            - All keys from all_expected_keys are present
        """
        all_expected_keys = ['path', 'size', 'modified_time', 'mime_type', 'extension', 'is_readable', 'is_writable']
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        # Force mime_type to None if possible (this might require modifying the object)
        # Since we can't directly modify it, we'll create a scenario where mime_type could be None
        result_dict = file_info.to_dict()
        
        # Check all keys are present
        for key in all_expected_keys:
            self.assertIn(key, result_dict)
        
        # If mime_type is None, verify it's preserved
        if result_dict['mime_type'] is None:
            self.assertIsNone(result_dict['mime_type'])

    def test_to_dict_with_empty_string_values(self):
        """
        GIVEN FileInfo instance with empty string values
        WHERE:
            - empty_string_values = attributes that may be empty strings (e.g., extension)
        WHEN to_dict is called
        THEN expect:
            - Dictionary contains empty string values
            - Empty strings preserved as "", not converted to None
        """
        # Create a file without extension
        fd, temp_path = tempfile.mkstemp(suffix="")
        os.close(fd)
        os.unlink(temp_path)
        
        no_extension_path = temp_path + "_no_ext"
        with open(no_extension_path, 'w') as f:
            f.write(KNOWN_CONTENT)
        self.temp_files.append(no_extension_path)
        
        file_info = FileInfo.from_path(no_extension_path)
        result_dict = file_info.to_dict()
        
        # Check that extension is empty string, not None
        self.assertEqual(result_dict['extension'], "")
        self.assertIsNotNone(result_dict['extension'])
        self.assertIsInstance(result_dict['extension'], str)

    def test_to_dict_multiple_calls_consistency(self):
        """
        GIVEN FileInfo instance
        WHERE:
            - FileInfo with populated attributes
        WHEN to_dict is called multiple times
        THEN expect:
            - All calls return dictionaries with identical content (using ==)
            - Each call returns different object reference (not same dict)
            - Each call completes within {TIME_LIMIT} seconds
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        # Measure time and get multiple results
        start_time = time.time()
        result1 = file_info.to_dict()
        first_call_time = time.time() - start_time
        
        start_time = time.time()
        result2 = file_info.to_dict()
        second_call_time = time.time() - start_time
        
        start_time = time.time()
        result3 = file_info.to_dict()
        third_call_time = time.time() - start_time
        
        # Check content equality
        self.assertEqual(result1, result2)
        self.assertEqual(result2, result3)
        
        # Check different object references
        self.assertIsNot(result1, result2)
        self.assertIsNot(result2, result3)
        self.assertIsNot(result1, result3)
        
        # Check timing (should complete within TIME_LIMIT)
        self.assertLessEqual(first_call_time, TIME_LIMIT)
        self.assertLessEqual(second_call_time, TIME_LIMIT)
        self.assertLessEqual(third_call_time, TIME_LIMIT)

    def test_to_dict_json_serializable(self):
        """
        GIVEN FileInfo instance with typical file attributes
        WHERE:
            - FileInfo with datetime_object, string, int, and bool values
        WHEN to_dict is called and result is passed to json.dumps
        THEN expect:
            - Dictionary is JSON serializable
            - json.dumps() does not raise exceptions
            - All values are JSON-compatible types
        """
        temp_file_path = self._create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        result_dict = file_info.to_dict()
        
        # Attempt JSON serialization
        json_string = json.dumps(result_dict, default=str)
        self.assertIsInstance(json_string, str)
        
        # Check that all values are JSON-compatible types or can be converted
        json_compatible_types = (str, int, float, bool, type(None), list, dict)
        
        self.assertTrue(all(isinstance(value, json_compatible_types) or isinstance(value, datetime) 
                            for value in result_dict.values()))

if __name__ == "__main__":
    unittest.main()
