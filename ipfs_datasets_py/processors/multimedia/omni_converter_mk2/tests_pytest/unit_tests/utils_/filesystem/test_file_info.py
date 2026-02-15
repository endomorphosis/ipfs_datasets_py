"""
Test suite for utils/filesystem FileInfo class converted from unittest to pytest.
"""
import pytest
from unittest.mock import Mock, MagicMock
from pathlib import Path
import os
import json
import time
import tempfile
import stat
from datetime import datetime, timedelta

# Make sure the input file and documentation file exist.
cwd = os.getcwd()
if not os.path.exists(f'{cwd}/utils/filesystem.py'):
    pytest.skip("utils/filesystem.py does not exist at the specified directory", allow_module_level=True)

try:
    from utils.filesystem import FileInfo
except ImportError:
    pytest.skip("FileInfo cannot be imported", allow_module_level=True)

# Constants
KNOWN_CONTENT = "Hello, World!"
KNOWN_BYTE_COUNT = 13
TIME_LIMIT = 0.1  # seconds


@pytest.fixture
def binary_content():
    """Binary content for testing."""
    return b'\x89PNG\r\n\x1a\n'  # PNG file signature


@pytest.fixture
def temp_file_manager():
    """Fixture to manage temporary files and directories."""
    temp_files = []
    temp_dirs = []
    
    def create_temp_file(content, suffix=".txt", mode="w"):
        """Helper method to create temporary files."""
        fd, temp_path = tempfile.mkstemp(suffix=suffix)
        try:
            if mode == "wb":
                os.write(fd, content)
            else:
                os.write(fd, content.encode('utf-8'))
        finally:
            os.close(fd)
        temp_files.append(temp_path)
        return temp_path
    
    def create_relative_temp_file(content, suffix=".txt"):
        """Helper method to create temporary files accessible via relative path."""
        # Create file in current directory
        temp_file_path = create_temp_file(content, suffix=suffix)
        relative_path = "./" + os.path.basename(temp_file_path)
        
        # Create a symlink or copy to make it accessible via relative path
        relative_temp_path = os.path.join(".", os.path.basename(temp_file_path))
        with open(relative_temp_path, 'w') as f:
            f.write(content)
        temp_files.append(relative_temp_path)
        
        return relative_path
    
    manager = type('TempFileManager', (), {})()
    manager.create_temp_file = create_temp_file
    manager.create_relative_temp_file = create_relative_temp_file
    
    yield manager
    
    # Cleanup
    for temp_file in temp_files:
        try:
            if os.path.exists(temp_file):
                # Restore permissions before deletion
                os.chmod(temp_file, stat.S_IRUSR | stat.S_IWUSR)
                os.unlink(temp_file)
        except (OSError, PermissionError):
            pass
    
    for temp_dir in temp_dirs:
        try:
            if os.path.exists(temp_dir):
                os.rmdir(temp_dir)
        except OSError:
            pass


@pytest.mark.unit
class TestFileInfoFromPath:
    """Test FileInfo.from_path class method."""

    def test_from_path_creates_fileinfo_instance(self, temp_file_manager):
        """
        GIVEN existing text file with known properties
        WHEN from_path is called with the file path
        THEN expect FileInfo instance created without exceptions
        """
        temp_file_path = temp_file_manager.create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        assert isinstance(file_info, FileInfo)

    def test_from_path_sets_correct_path(self, temp_file_manager):
        """
        GIVEN existing text file
        WHEN from_path is called with the file path
        THEN expect path attribute matches provided path
        """
        temp_file_path = temp_file_manager.create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        assert file_info.path == Path(temp_file_path)

    def test_from_path_sets_correct_size(self, temp_file_manager):
        """
        GIVEN existing text file with known content
        WHEN from_path is called with the file path
        THEN expect size attribute == KNOWN_BYTE_COUNT
        """
        temp_file_path = temp_file_manager.create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        assert file_info.size == KNOWN_BYTE_COUNT

    def test_from_path_sets_recent_modified_time(self, temp_file_manager):
        """
        GIVEN existing text file
        WHEN from_path is called with the file path
        THEN expect modified_time attribute within 60 seconds of actual modification time
        """
        EXPECTED_TIME_SECONDS = 60
        temp_file_path = temp_file_manager.create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        now = datetime.now()
        time_diff = abs((now - file_info.modified_time).total_seconds())
        assert time_diff <= EXPECTED_TIME_SECONDS

    def test_from_path_sets_text_mime_type(self, temp_file_manager):
        """
        GIVEN existing text file
        WHEN from_path is called with the file path
        THEN expect mime_type attribute starts with "text/"
        """
        temp_file_path = temp_file_manager.create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        assert file_info.mime_type.startswith("text/")

    def test_from_path_sets_correct_extension(self, temp_file_manager):
        """
        GIVEN existing text file with .txt extension
        WHEN from_path is called with the file path
        THEN expect extension attribute == ".txt"
        """
        temp_file_path = temp_file_manager.create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        assert file_info.extension == "txt"

    def test_from_path_sets_readable_true(self, temp_file_manager):
        """
        GIVEN existing text file with default permissions
        WHEN from_path is called with the file path
        THEN expect is_readable attribute == True
        """
        temp_file_path = temp_file_manager.create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        assert file_info.is_readable is True

    def test_from_path_sets_writable_true(self, temp_file_manager):
        """
        GIVEN existing text file with default permissions
        WHEN from_path is called with the file path
        THEN expect is_writable attribute == True
        """
        temp_file_path = temp_file_manager.create_temp_file(KNOWN_CONTENT, suffix=".txt")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        assert file_info.is_writable is True

    def test_from_path_with_existing_binary_file_creates_instance(self, temp_file_manager, binary_content):
        """
        GIVEN existing binary file
        WHERE:
            - existing_binary_file = temporary .png file with PNG header bytes
            - binary_content = b'\x89PNG\r\n\x1a\n' (PNG file signature)
        WHEN from_path is called with the file path
        THEN expect FileInfo instance created without exceptions
        """
        temp_file_path = temp_file_manager.create_temp_file(binary_content, suffix=".png", mode="wb")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        assert isinstance(file_info, FileInfo)

    def test_from_path_with_existing_binary_file_sets_correct_mime_type(self, temp_file_manager, binary_content):
        """
        GIVEN existing binary file
        WHERE:
            - existing_binary_file = temporary .png file with PNG header bytes
            - binary_content = b'\x89PNG\r\n\x1a\n' (PNG file signature)
        WHEN from_path is called with the file path
        THEN expect mime_type attribute == "image/png"
        """
        temp_file_path = temp_file_manager.create_temp_file(binary_content, suffix=".png", mode="wb")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        assert file_info.mime_type == "image/png"

    def test_from_path_with_existing_binary_file_sets_correct_path(self, temp_file_manager, binary_content):
        """
        GIVEN existing binary file
        WHERE:
            - existing_binary_file = temporary .png file with PNG header bytes
            - binary_content = b'\x89PNG\r\n\x1a\n' (PNG file signature)
        WHEN from_path is called with the file path
        THEN expect path attribute matches provided path
        """
        temp_file_path = temp_file_manager.create_temp_file(binary_content, suffix=".png", mode="wb")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        assert file_info.path == Path(temp_file_path)

    def test_from_path_with_existing_binary_file_sets_correct_size(self, temp_file_manager, binary_content):
        """
        GIVEN existing binary file
        WHERE:
            - existing_binary_file = temporary .png file with PNG header bytes
            - binary_content = b'\x89PNG\r\n\x1a\n' (PNG file signature)
        WHEN from_path is called with the file path
        THEN expect size attribute matches content length
        """
        temp_file_path = temp_file_manager.create_temp_file(binary_content, suffix=".png", mode="wb")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        assert file_info.size == len(binary_content)

    def test_from_path_with_existing_binary_file_sets_correct_extension(self, temp_file_manager, binary_content):
        """
        GIVEN existing binary file
        WHERE:
            - existing_binary_file = temporary .png file with PNG header bytes
            - binary_content = b'\x89PNG\r\n\x1a\n' (PNG file signature)
        WHEN from_path is called with the file path
        THEN expect extension attribute == ".png"
        """
        temp_file_path = temp_file_manager.create_temp_file(binary_content, suffix=".png", mode="wb")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        assert file_info.extension == "png"

    def test_from_path_with_existing_binary_file_sets_readable_true(self, temp_file_manager, binary_content):
        """
        GIVEN existing binary file
        WHERE:
            - existing_binary_file = temporary .png file with PNG header bytes
            - binary_content = b'\x89PNG\r\n\x1a\n' (PNG file signature)
        WHEN from_path is called with the file path
        THEN expect is_readable attribute == True
        """
        temp_file_path = temp_file_manager.create_temp_file(binary_content, suffix=".png", mode="wb")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        assert file_info.is_readable is True

    def test_from_path_with_existing_binary_file_sets_writable_true(self, temp_file_manager, binary_content):
        """
        GIVEN existing binary file
        WHERE:
            - existing_binary_file = temporary .png file with PNG header bytes
            - binary_content = b'\x89PNG\r\n\x1a\n' (PNG file signature)
        WHEN from_path is called with the file path
        THEN expect is_writable attribute == True
        """
        temp_file_path = temp_file_manager.create_temp_file(binary_content, suffix=".png", mode="wb")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        assert file_info.is_writable is True

    def test_from_path_with_nonexistent_file(self):
        """
        GIVEN nonexistent file path
        WHEN from_path is called with the file path
        THEN expect appropriate exception raised
        """
        nonexistent_path = "/this/path/does/not/exist.txt"
        
        with pytest.raises((FileNotFoundError, OSError)):
            FileInfo.from_path(nonexistent_path)

    @pytest.mark.parametrize("file_extension,expected_mime_prefix", [
        (".txt", "text/"),
        (".json", "application/"),
        (".html", "text/"),
        (".css", "text/"),
        (".js", "application/"),
    ])
    def test_from_path_mime_type_detection(self, temp_file_manager, file_extension, expected_mime_prefix):
        """
        GIVEN files with different extensions
        WHEN from_path is called
        THEN expect appropriate mime type prefix
        """
        temp_file_path = temp_file_manager.create_temp_file("test content", suffix=file_extension)
        
        file_info = FileInfo.from_path(temp_file_path)
        
        assert file_info.mime_type.startswith(expected_mime_prefix)


@pytest.mark.unit
@pytest.mark.filesystem
class TestFileInfoEdgeCases:
    """Test FileInfo edge cases and error conditions."""
    
    def test_from_path_with_empty_file(self, temp_file_manager):
        """
        GIVEN empty file
        WHEN from_path is called
        THEN expect size == 0
        """
        temp_file_path = temp_file_manager.create_temp_file("")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        assert file_info.size == 0
        assert isinstance(file_info, FileInfo)
    
    def test_from_path_with_no_extension(self, temp_file_manager):
        """
        GIVEN file without extension
        WHEN from_path is called
        THEN expect empty extension
        """
        temp_file_path = temp_file_manager.create_temp_file("content", suffix="")
        
        file_info = FileInfo.from_path(temp_file_path)
        
        # Extension should be empty or None depending on implementation
        assert file_info.extension == "" or file_info.extension is None