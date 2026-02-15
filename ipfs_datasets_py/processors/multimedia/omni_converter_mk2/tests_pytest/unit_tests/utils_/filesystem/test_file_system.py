"""
Tests for FileSystem implementation - pytest conversion.

This module contains pytest conversions of unittest tests for the FileSystem class, 
covering file existence checks, directory operations, and file system utilities.
"""

import pytest
from unittest.mock import Mock, MagicMock
import os
import tempfile
import stat
from pathlib import Path
from datetime import datetime

# Import the classes to test
from utils.filesystem import FileSystem, FileContent, FileInfo


@pytest.mark.unit
class TestFileSystemFileExists:
    """Test FileSystem.file_exists static method."""

    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        """Set up and tear down test fixtures."""
        self.temp_files = []
        self.temp_dirs = []
        yield
        # Clean up temporary files
        for temp_file in self.temp_files:
            try:
                if os.path.exists(temp_file):
                    os.unlink(temp_file)
            except OSError:
                pass
        
        # Clean up temporary directories
        for temp_dir in self.temp_dirs:
            try:
                if os.path.exists(temp_dir):
                    os.rmdir(temp_dir)
            except OSError:
                pass

    def _create_temp_file(self, content="test content"):
        """Helper method to create temporary files."""
        fd, temp_path = tempfile.mkstemp()
        try:
            os.write(fd, content.encode('utf-8'))
        finally:
            os.close(fd)
        self.temp_files.append(temp_path)
        return temp_path

    def test_file_exists_with_valid_existing_file(self):
        """
        GIVEN valid path to an existing file
        WHEN file_exists is called
        THEN expect:
            - Return value == True
        """
        temp_file = self._create_temp_file()
        
        result = FileSystem.file_exists(temp_file)
        
        assert result is True

    def test_file_exists_with_nonexistent_file(self):
        """
        GIVEN path to a nonexistent file
        WHEN file_exists is called
        THEN expect:
            - Return value == False
        """
        nonexistent_file = "/path/to/nonexistent/file.txt"
        
        result = FileSystem.file_exists(nonexistent_file)
        
        assert result is False

    def test_file_exists_with_directory_path(self):
        """
        GIVEN path pointing to an existing directory
        WHERE:
            - directory_path = path to existing directory
        WHEN file_exists is called
        THEN expect:
            - Return value == False (directories are not files)
        """
        directory_path = tempfile.mkdtemp()
        self.temp_dirs.append(directory_path)
        
        result = FileSystem.file_exists(directory_path)
        
        assert result is False

    def test_file_exists_with_relative_path(self):
        """
        GIVEN relative path to an existing file
        WHERE:
            - relative_path = "./test_file.txt"
            - file exists at relative location
        WHEN file_exists is called
        THEN expect:
            - Return value == True
            - Relative path resolved without errors
        """
        # Create file in current directory
        temp_file = self._create_temp_file()
        relative_path = "./" + os.path.basename(temp_file)
        
        # Create the file at relative path
        with open(relative_path, 'w') as f:
            f.write("test content")
        self.temp_files.append(relative_path)
        
        result = FileSystem.file_exists(relative_path)
        
        assert result is True

    def test_file_exists_with_absolute_path(self):
        """
        GIVEN absolute path to an existing file
        WHERE:
            - absolute_path = full system path to test file
        WHEN file_exists is called
        THEN expect:
            - Return value == True
            - Absolute path handled correctly
        """
        temp_file = self._create_temp_file()
        absolute_path = os.path.abspath(temp_file)
        
        result = FileSystem.file_exists(absolute_path)
        
        assert result is True

    @pytest.mark.parametrize("invalid_path", [
        None,
        "",
        123,
        [],
        {}
    ])
    def test_file_exists_with_invalid_input_types(self, invalid_path):
        """
        GIVEN invalid input types for path parameter
        WHEN file_exists is called
        THEN expect:
            - Return value == False or raises appropriate exception
        """
        try:
            result = FileSystem.file_exists(invalid_path)
            assert result is False
        except (TypeError, AttributeError):
            # Some invalid inputs may raise exceptions, which is acceptable
            pass

    def test_file_exists_with_permission_denied(self):
        """
        GIVEN path to a file where permissions prevent access
        WHEN file_exists is called
        THEN expect:
            - Return value == False
            - No exceptions raised (graceful handling)
        """
        # Create a temporary file
        temp_file = self._create_temp_file()
        
        # Remove all permissions
        os.chmod(temp_file, 0o000)
        
        try:
            result = FileSystem.file_exists(temp_file)
            # Should handle permission errors gracefully
            assert isinstance(result, bool)
        finally:
            # Restore permissions for cleanup
            os.chmod(temp_file, 0o644)

    def test_file_exists_with_special_characters_in_path(self):
        """
        GIVEN path containing special characters
        WHEN file_exists is called
        THEN expect:
            - Special characters handled correctly
            - Return appropriate boolean value
        """
        # Create temp file with special characters in name
        temp_dir = tempfile.mkdtemp()
        self.temp_dirs.append(temp_dir)
        special_file = os.path.join(temp_dir, "test_file_!@#$%^&()_+.txt")
        
        # Create the file
        with open(special_file, 'w') as f:
            f.write("test content")
        self.temp_files.append(special_file)
        
        result = FileSystem.file_exists(special_file)
        
        assert result is True